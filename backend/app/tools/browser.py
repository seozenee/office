"""Browser / Computer agent tools (Playwright, headless Chromium).

Risk levels (enforced by the tool registry):
  browser.open, browser.screenshot, browser.extract   LOW       read-only
  browser.download                                    MEDIUM    saves a file into the workspace + knowledge base
  browser.submit_form                                 HIGH      acts on an external site → CEO approval
  (forms with password / payment fields)              CRITICAL  refused unless approved as CRITICAL

Logged-in work uses a stored session profile (Playwright storage_state JSON) that the user provides;
the agent never types passwords itself. Page text is returned as UNTRUSTED content.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.files import project_root, slugify
from app.tools.web import FetchError, _check_ssrf

_PAYMENT = re.compile(r"(card|카드|cvc|cvv|결제|payment|billing|계좌|iban|송금|구매|purchase|checkout)", re.I)


class BrowserError(RuntimeError):
    pass


def browser_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return get_settings().browser_enabled


def _profile_dir() -> Path:
    d = get_settings().workspace_dir / "_browser_profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_url(url: str) -> None:
    s = get_settings()
    try:
        _check_ssrf(url)
    except FetchError as e:
        raise BrowserError(str(e)) from e
    allowed = [d.strip().lower() for d in (s.browser_allowed_domains or "").split(",") if d.strip()]
    host = (urlparse(url).hostname or "").lower()
    if allowed and not any(host == d or host.endswith("." + d) for d in allowed):
        raise BrowserError(f"도메인 {host} 은(는) BROWSER_ALLOWED_DOMAINS 에 없습니다")


@contextmanager
def _page(profile: str | None = None):
    if not browser_available():
        raise BrowserError("브라우저 자동화가 비활성화되었거나 playwright 가 설치되지 않았습니다 (pip install playwright)")
    from playwright.sync_api import sync_playwright

    s = get_settings()
    state = None
    if profile:
        p = _profile_dir() / f"{slugify(profile)}.json"
        if not p.exists():
            raise BrowserError(f"브라우저 세션 프로필 '{profile}' 이(가) 없습니다. 설정에서 storage_state JSON 을 등록하세요.")
        state = str(p)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=state, user_agent=s.fetch_user_agent, accept_downloads=True,
                                  viewport={"width": 1366, "height": 900})
        ctx.set_default_timeout(s.http_timeout * 1000)
        page = ctx.new_page()

        def guard(route):  # every sub-request is SSRF-checked, too
            try:
                _check_ssrf(route.request.url) if route.request.url.startswith("http") else None
            except FetchError:
                return route.abort()
            return route.continue_()

        if not s.fetch_allow_private_network:
            page.route("**/*", guard)
        try:
            yield page
        finally:
            ctx.close()
            browser.close()


def save_profile(name: str, storage_state: dict[str, Any]) -> str:
    if not isinstance(storage_state, dict) or "cookies" not in storage_state:
        raise BrowserError("storage_state JSON 에 cookies 항목이 필요합니다 (Playwright context.storage_state 형식)")
    p = _profile_dir() / f"{slugify(name)}.json"
    p.write_text(json.dumps(storage_state), encoding="utf-8")
    os.chmod(p, 0o600)
    return p.stem


def list_profiles() -> list[str]:
    return sorted(p.stem for p in _profile_dir().glob("*.json"))


def render_html(url: str) -> tuple[str, str]:
    """Render a JavaScript page and return (final_url, html). Used when plain fetch finds no content."""
    _check_url(url)
    with _page() as page:
        page.goto(url, wait_until="networkidle")
        return page.url, page.content()


def open_page(url: str, profile: str | None = None, max_chars: int = 20000) -> dict[str, Any]:
    _check_url(url)
    with _page(profile) as page:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(500)
        text = page.inner_text("body")[:max_chars]
        links = page.eval_on_selector_all("a[href]", "els => els.slice(0, 80).map(e => ({text: e.innerText.trim().slice(0, 80), href: e.href}))")
        forms = page.eval_on_selector_all("form", """els => els.map((f, i) => ({index: i, action: f.action, method: f.method,
            fields: Array.from(f.elements).filter(e => e.name).map(e => ({name: e.name, type: e.type || e.tagName.toLowerCase()}))}))""")
        return {"url": page.url, "title": page.title(), "text": text, "links": links, "forms": forms, "untrusted": True}


def screenshot(url: str, profile: str | None = None, project_slug: str | None = None, full_page: bool = True) -> dict[str, Any]:
    _check_url(url)
    out = project_root(project_slug) / "research" / f"screenshot_{hashlib.sha1(url.encode()).hexdigest()[:10]}.png"
    with _page(profile) as page:
        page.goto(url, wait_until="networkidle")
        page.screenshot(path=str(out), full_page=full_page)
        return {"url": page.url, "title": page.title(), "path": str(out)}


def extract(url: str, selector: str, profile: str | None = None) -> dict[str, Any]:
    _check_url(url)
    with _page(profile) as page:
        page.goto(url, wait_until="domcontentloaded")
        items = page.eval_on_selector_all(selector, "els => els.slice(0, 200).map(e => e.innerText.trim())")
        tables = page.eval_on_selector_all(f"{selector} table, {selector}:is(table)",
                                           "ts => ts.slice(0, 10).map(t => Array.from(t.rows).map(r => Array.from(r.cells).map(c => c.innerText.trim())))")
        return {"url": page.url, "selector": selector, "items": items, "tables": tables, "untrusted": True}


def download(url: str, link_text: str | None = None, profile: str | None = None, project_slug: str | None = None) -> dict[str, Any]:
    """Download a file (directly, or by clicking a link with the given text) into source_files/."""
    _check_url(url)
    dest_dir = project_root(project_slug) / "source_files"
    with _page(profile) as page:
        if link_text:
            page.goto(url, wait_until="domcontentloaded")
            with page.expect_download() as dl:
                page.get_by_text(link_text, exact=False).first.click()
            d = dl.value
            name = d.suggested_filename
            target = dest_dir / f"{hashlib.sha1((url + name).encode()).hexdigest()[:8]}_{name}"
            d.save_as(str(target))
        else:
            resp = page.request.get(url)
            if not resp.ok:
                raise BrowserError(f"다운로드 실패: HTTP {resp.status}")
            name = Path(urlparse(url).path).name or "download.bin"
            target = dest_dir / f"{hashlib.sha1(url.encode()).hexdigest()[:8]}_{name}"
            target.write_bytes(resp.body())
    return {"path": str(target), "size": target.stat().st_size, "name": name}


def form_risk(fields: dict[str, str], page_text: str = "") -> str:
    keys = " ".join(fields) + " " + page_text[:2000]
    if any("pass" in k.lower() for k in fields) or _PAYMENT.search(keys):
        return "CRITICAL"
    return "HIGH"


def submit_form(url: str, fields: dict[str, str], submit_selector: str | None = None, profile: str | None = None,
                project_slug: str | None = None) -> dict[str, Any]:
    """Fill and submit a form. Only runs after CEO approval (registered as HIGH risk)."""
    _check_url(url)
    if form_risk(fields) == "CRITICAL":
        raise BrowserError("비밀번호·결제 관련 폼은 자동 제출하지 않습니다 (CRITICAL). 직접 처리해 주세요.")
    with _page(profile) as page:
        page.goto(url, wait_until="domcontentloaded")
        for name, value in fields.items():
            page.fill(f"[name='{name}']", str(value))
        before = project_root(project_slug) / "research" / f"form_before_{hashlib.sha1(url.encode()).hexdigest()[:8]}.png"
        page.screenshot(path=str(before))
        if submit_selector:
            page.click(submit_selector)
        else:
            page.locator("form [type=submit], form button").first.click()
        page.wait_for_load_state("domcontentloaded")
        after = before.with_name(before.name.replace("before", "after"))
        page.screenshot(path=str(after))
        return {"url": page.url, "title": page.title(), "before": str(before), "after": str(after)}
