"""Registers built-in tools and plugin actions into the registry with their risk levels."""
from __future__ import annotations

from pathlib import Path

from app.core.files import safe_resolve
from app.core.models import RiskLevel
from app.plugins.base import PLUGINS
from app.tools.calc import safe_eval
from app.tools.registry import ToolSpec, registry
from app.tools.web import fetch_document, get_search_provider


def _search(query: str, limit: int = 8):
    p = get_search_provider()
    if p is None:
        raise RuntimeError("search provider not configured")
    return [r.__dict__ for r in p.search(query, limit)]


def _fetch(url: str):
    d = fetch_document(url)
    return {"title": d.parsed.title, "pages": len(d.parsed.pages), "text": d.parsed.text[:20000]}


def _write_file(path: str, content: str):
    p = safe_resolve(path)
    if p.exists():  # version instead of overwrite
        n = 2
        while (alt := p.with_name(f"{p.stem}_v{n}{p.suffix}")).exists():
            n += 1
        p = alt
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p)


def _delete_file(path: str):
    p = safe_resolve(path)
    archive = p.parent / ".trash"
    archive.mkdir(exist_ok=True)
    return str(p.rename(archive / p.name))


def _browser_download(url: str, link_text: str | None = None, profile: str | None = None, project_id: int | None = None):
    from app.core.db import SessionLocal
    from app.core.models import Project
    from app.knowledge.store import ingest_file
    from app.tools import browser

    with SessionLocal() as db:
        project = db.get(Project, project_id) if project_id else None
        res = browser.download(url, link_text, profile, project.slug if project else None)
        try:
            doc = ingest_file(db, Path(res["path"]), project_id=project_id)
            res["kb_document_id"] = doc.id
        except Exception as e:  # noqa: BLE001 - non-document downloads are kept as files only
            res["kb_error"] = str(e)
        return res


def _b():
    from app.tools import browser

    return browser


def register_builtin_tools() -> None:
    if registry.list():
        return
    for spec in [
        ToolSpec("web.search", "웹 검색", RiskLevel.LOW, _search, "research"),
        ToolSpec("web.fetch", "웹 페이지/PDF 원문 가져오기", RiskLevel.LOW, _fetch, "research"),
        ToolSpec("calc.eval", "계산 엔진", RiskLevel.LOW, lambda expr, **v: safe_eval(expr, v), "analysis"),
        ToolSpec("files.write", "워크스페이스 파일 작성", RiskLevel.MEDIUM, _write_file, "files"),
        ToolSpec("files.delete", "파일 삭제(휴지통 이동)", RiskLevel.CRITICAL, _delete_file, "files"),
        ToolSpec("browser.open", "웹사이트 열기(텍스트·링크·폼 구조)", RiskLevel.LOW, lambda **k: _b().open_page(**k), "browser"),
        ToolSpec("browser.screenshot", "웹페이지 스크린샷", RiskLevel.LOW, lambda **k: _b().screenshot(**k), "browser"),
        ToolSpec("browser.extract", "선택자 기반 자료 추출", RiskLevel.LOW, lambda **k: _b().extract(**k), "browser"),
        ToolSpec("browser.download", "파일 다운로드 → 지식베이스", RiskLevel.MEDIUM, _browser_download, "browser"),
        ToolSpec("browser.submit_form", "외부 사이트 폼 작성·제출", RiskLevel.HIGH, lambda **k: _b().submit_form(**k), "browser"),
    ]:
        registry.register(spec)
    for plugin in PLUGINS:
        for a in plugin.actions:
            registry.register(ToolSpec(a.name, a.description, a.risk, a.fn, f"plugin:{plugin.key}"))


__all__ = ["register_builtin_tools", "Path"]
