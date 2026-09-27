"""Research team: parallel search, credibility ranking, original-document fetch, KB ingest."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.base import Agent
from app.core.files import project_root
from app.core.models import KBDocument, Source
from app.core.security import scan_injection
from app.knowledge.store import ingest_parsed
from app.tools.source_rank import classify_source, host_of
from app.tools.web import FetchError, get_search_provider, parallel_search, fetch_document


@dataclass
class ResearchOutcome:
    sources: list[Source] = field(default_factory=list)
    found: int = 0
    accessed: int = 0
    failed: list[str] = field(default_factory=list)
    search_errors: list[str] = field(default_factory=list)
    provider: str | None = None
    injection_warnings: list[str] = field(default_factory=list)


class ResearchLeadAgent(Agent):
    agent_type = "research_lead"


class WebResearcherAgent(Agent):
    agent_type = "web_researcher"

    def search(self, queries: list[str], limit: int = 8):
        provider = get_search_provider()
        if provider is None:
            return None, [], ["검색 제공자가 설정되지 않았습니다 (TAVILY/BRAVE/SERPER/SEARXNG 키 또는 FIXTURE_SEARCH_FILE 필요)"]
        self.work(f"병렬 검색 {len(queries)}건")
        self.say(f"🔎 검색어 {len(queries)}개로 병렬 검색 시작합니다: " + " · ".join(f"‘{q}’" for q in queries[:6]))
        results, errors = parallel_search(provider, queries, limit)
        self.log("search_performed", provider=provider.name, queries=queries, results=len(results), errors=errors)
        return provider.name, results, errors


class DocumentAnalystAgent(Agent):
    agent_type = "document_analyst"

    def fetch_and_ingest(self, results, *, project_id: int | None, project_slug: str | None, max_sources: int,
                         official_domains: set[str] | None = None) -> ResearchOutcome:
        out = ResearchOutcome(found=len(results))
        ranked = []
        for r in results:
            tier, stype = classify_source(r.url, title=r.title, official_domains=official_domains)
            ranked.append((tier, r, stype))
        ranked.sort(key=lambda x: x[0])  # official sources first
        # keep host diversity: at most 3 documents per host
        per_host: dict[str, int] = {}
        selected = []
        for tier, r, stype in ranked:
            h = host_of(r.url)
            if per_host.get(h, 0) >= 3:
                continue
            per_host[h] = per_host.get(h, 0) + 1
            selected.append((tier, r, stype))
            if len(selected) >= max_sources:
                break
        save_dir = project_root(project_slug) / "source_files"
        self.work(f"원문 {len(selected)}건 확인 중")
        for tier, r, stype in selected:
            existing = self.db.scalar(select(Source).where(Source.url == r.url, Source.task_id == self.task_id))
            if existing:
                continue
            src = Source(project_id=project_id, task_id=self.task_id, title=r.title[:500] or r.url, url=r.url,
                         publisher=host_of(r.url), source_type=stype, tier=tier, publication_date=r.published,
                         snippet=r.snippet[:1000], query=r.query, access_date=datetime.now(timezone.utc))
            try:
                fetched = fetch_document(r.url, save_dir)
                parsed = fetched.parsed
                if len(parsed.text.strip()) < 100 and "html" in (fetched.content_type or "html"):
                    rendered = self._render_with_browser(r.url)
                    if rendered is not None:
                        parsed = rendered
                        src.snippet = (src.snippet + " [브라우저 렌더링으로 원문 확인]").strip()
                if len(parsed.text.strip()) < 100:
                    raise FetchError("original content too short or unreadable (possibly paywalled / scripted)")
                kb = ingest_parsed(self.db, parsed, project_id=project_id, source_url=fetched.final_url,
                                   file_path=fetched.raw_path, filename=fetched.raw_path and fetched.raw_path.rsplit("/", 1)[-1])
                src.kb_document_id = kb.id
                src.accessed = True
                src.title = (parsed.title or r.title)[:500]
                src.publication_date = parsed.date or r.published
                src.publisher = parsed.organization or src.publisher
                src.content_hash = kb.content_hash
                scan = scan_injection(parsed.text)
                if scan.flagged:
                    out.injection_warnings.append(f"{src.title}: {', '.join(scan.categories)}")
                out.accessed += 1
                self.log("source_downloaded", url=r.url, tier=tier, pages=len(parsed.pages), tables=len(parsed.tables))
            except Exception as e:  # noqa: BLE001 - any failure is recorded, never hidden
                src.accessed = False
                src.access_error = str(e)[:500]
                out.failed.append(f"{r.url} — {str(e)[:160]}")
                self.log("source_access_failed", url=r.url, error=str(e)[:300])
            self.db.add(src)
            self.db.commit()
            out.sources.append(src)
        return out

    def _render_with_browser(self, url: str):
        """JavaScript-rendered pages: fall back to the Browser agent (read-only, LOW risk)."""
        from app.core.config import get_settings
        from app.knowledge.parsers import parse_html
        from app.tools.browser import BrowserError, browser_available, render_html

        if not (get_settings().browser_render_fallback and browser_available()):
            return None
        try:
            final_url, html = render_html(url)
            self.log("browser_rendered", url=url)
            return parse_html(html, final_url)
        except (BrowserError, Exception) as e:  # noqa: BLE001
            self.log("browser_render_failed", url=url, error=str(e)[:200])
            return None

    def from_knowledge_base(self, project_id: int | None) -> ResearchOutcome:
        out = ResearchOutcome()
        docs = list(self.db.scalars(select(KBDocument).where(KBDocument.project_id == project_id)))
        out.found = len(docs)
        for d in docs:
            tier, stype = classify_source(d.source_url, title=d.title)
            if not d.source_url:
                tier, stype = 5, "user_upload"
            src = Source(project_id=project_id, task_id=self.task_id, kb_document_id=d.id, title=d.title, url=d.source_url,
                         publisher=d.organization or d.author, source_type=stype, tier=tier, publication_date=d.date,
                         accessed=True, content_hash=d.content_hash)
            self.db.add(src)
            out.sources.append(src)
            out.accessed += 1
            if d.injection_flags:
                out.injection_warnings.append(f"{d.title}: {', '.join(d.injection_flags)}")
        self.db.commit()
        return out
