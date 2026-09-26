"""Web research tools: pluggable search providers + original-content fetcher.

Search snippets are never used as evidence on their own: the pipeline fetches the page/PDF,
parses it and stores the original text in the Knowledge Base before extracting claims.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.knowledge.embeddings import tokenize
from app.knowledge.parsers import ParsedDocument, parse_bytes

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published: str | None = None
    provider: str = ""
    query: str = ""


class SearchError(RuntimeError):
    pass


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 8) -> list[SearchResult]: ...


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(timeout=s.http_timeout, follow_redirects=True, headers={"User-Agent": s.fetch_user_agent})


class TavilySearch:
    name = "tavily"

    def __init__(self, key: str) -> None:
        self.key = key

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        with _client() as c:
            r = c.post("https://api.tavily.com/search", json={"api_key": self.key, "query": query, "max_results": limit,
                                                              "search_depth": "advanced"})
            r.raise_for_status()
        return [SearchResult(x.get("title", ""), x["url"], x.get("content", ""), x.get("published_date"), self.name, query)
                for x in r.json().get("results", [])]


class BraveSearch:
    name = "brave"

    def __init__(self, key: str) -> None:
        self.key = key

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        with _client() as c:
            r = c.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": limit},
                      headers={"X-Subscription-Token": self.key, "Accept": "application/json"})
            r.raise_for_status()
        return [SearchResult(x.get("title", ""), x["url"], x.get("description", ""), x.get("page_age"), self.name, query)
                for x in r.json().get("web", {}).get("results", [])]


class SerperSearch:
    name = "serper"

    def __init__(self, key: str) -> None:
        self.key = key

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        with _client() as c:
            r = c.post("https://google.serper.dev/search", json={"q": query, "num": limit}, headers={"X-API-KEY": self.key})
            r.raise_for_status()
        return [SearchResult(x.get("title", ""), x["link"], x.get("snippet", ""), x.get("date"), self.name, query)
                for x in r.json().get("organic", [])]


class SearxngSearch:
    name = "searxng"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        with _client() as c:
            r = c.get(f"{self.base_url}/search", params={"q": query, "format": "json"})
            r.raise_for_status()
        return [SearchResult(x.get("title", ""), x["url"], x.get("content", ""), x.get("publishedDate"), self.name, query)
                for x in r.json().get("results", [])[:limit]]


class FixtureSearch:
    """Offline search over a JSON corpus: [{"title","url","snippet","published"}]. Used for tests, demos
    and air-gapped environments. Ranking = token overlap between query and title+snippet."""

    name = "fixture"

    def __init__(self, path: str | Path) -> None:
        self.items = json.loads(Path(path).read_text(encoding="utf-8"))

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        q = set(tokenize(query))
        scored = []
        for it in self.items:
            toks = set(tokenize(f"{it.get('title', '')} {it.get('snippet', '')} {' '.join(it.get('keywords', []))}"))
            overlap = len(q & toks)
            if overlap:
                scored.append((overlap, it))
        scored.sort(key=lambda x: -x[0])
        return [SearchResult(it["title"], it["url"], it.get("snippet", ""), it.get("published"), self.name, query)
                for _, it in scored[:limit]]


def get_search_provider() -> SearchProvider | None:
    s = get_settings()
    choice = s.search_provider.lower()
    options: list[tuple[str, SearchProvider | None]] = [
        ("tavily", TavilySearch(s.tavily_api_key) if s.tavily_api_key else None),
        ("brave", BraveSearch(s.brave_api_key) if s.brave_api_key else None),
        ("serper", SerperSearch(s.serper_api_key) if s.serper_api_key else None),
        ("searxng", SearxngSearch(s.searxng_url) if s.searxng_url else None),
        ("fixture", FixtureSearch(s.fixture_search_file) if s.fixture_search_file else None),
    ]
    if choice == "none":
        return None
    for name, prov in options:
        if prov and (choice == "auto" or choice == name):
            return prov
    return None


def parallel_search(provider: SearchProvider, queries: list[str], limit: int = 8) -> tuple[list[SearchResult], list[str]]:
    """Run queries in parallel; returns de-duplicated results and error messages (never silent)."""
    results: list[SearchResult] = []
    errors: list[str] = []

    def run(q: str) -> list[SearchResult]:
        return provider.search(q, limit)

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(queries)))) as ex:
        futures = {ex.submit(run, q): q for q in queries}
        for fut, q in futures.items():
            try:
                results.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                errors.append(f"search failed for '{q}': {e}")
    seen: set[str] = set()
    uniq = []
    for r in results:
        key = r.url.split("#")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq, errors


# ---------------------------------------------------------------------------
# Fetching original documents
# ---------------------------------------------------------------------------
class FetchError(RuntimeError):
    pass


def _check_ssrf(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"blocked scheme: {parsed.scheme}")
    if get_settings().fetch_allow_private_network:
        return
    host = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise FetchError(f"DNS resolution failed for {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise FetchError(f"blocked private address for {host}")


@dataclass
class FetchedDocument:
    url: str
    final_url: str
    content_type: str
    data: bytes
    parsed: ParsedDocument
    raw_path: str | None = None
    notes: list[str] = field(default_factory=list)


def _from_mirror(url: str) -> tuple[bytes, str, str] | None:
    """Research snapshot replay: serve a previously captured copy of a URL (reproducible runs, air-gapped demos, tests)."""
    mirror = get_settings().fetch_mirror_dir
    if not mirror:
        return None
    index_path = Path(mirror) / "index.json"
    if not index_path.exists():
        return None
    entry = json.loads(index_path.read_text(encoding="utf-8")).get(url)
    if not entry:
        return None
    return (Path(mirror) / entry["file"]).read_bytes(), entry.get("content_type", ""), url


def fetch_document(url: str, save_dir: Path | None = None) -> FetchedDocument:
    s = get_settings()
    mirrored = _from_mirror(url)
    if mirrored:
        data, ct, final_url = mirrored
        return _finish(url, final_url, ct, data, save_dir)
    _check_ssrf(url)
    try:
        with _client() as c, c.stream("GET", url) as r:
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            chunks, size = [], 0
            for block in r.iter_bytes():
                size += len(block)
                if size > s.fetch_max_bytes:
                    raise FetchError("document too large")
                chunks.append(block)
            data = b"".join(chunks)
            final_url = str(r.url)
    except httpx.HTTPError as e:
        raise FetchError(f"{type(e).__name__}: {e}") from e
    return _finish(url, final_url, ct, data, save_dir)


def _finish(url: str, final_url: str, ct: str, data: bytes, save_dir: Path | None) -> FetchedDocument:
    name = Path(urlparse(final_url).path).name or "index.html"
    if "pdf" in ct and not name.lower().endswith(".pdf"):
        name += ".pdf"
    elif "html" in ct and "." not in name:
        name += ".html"
    parsed = parse_bytes(data, name, url=final_url, content_type=ct)
    raw_path = None
    if save_dir is not None:
        import hashlib

        save_dir.mkdir(parents=True, exist_ok=True)
        p = save_dir / f"{hashlib.sha1(final_url.encode()).hexdigest()[:12]}_{name[-60:]}"
        p.write_bytes(data)
        raw_path = str(p)
    return FetchedDocument(url, final_url, ct, data, parsed, raw_path)
