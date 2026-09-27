"""Opportunity Scanner: watches the CEO's interests for new papers, competitions, grants, market changes,
companies and investment news. Findings are search results (snippets = unverified) ranked by source tier,
recency and relevance; the CEO can turn any finding into a full research task."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.models import Memory, Opportunity, Project
from app.knowledge.embeddings import tokenize
from app.office import service as office
from app.tools.source_rank import classify_source
from app.tools.web import get_search_provider, parallel_search

CATEGORIES: dict[str, str] = {
    "paper": "최신 논문 연구",
    "competition": "공모전 대회 해커톤",
    "grant": "정부 지원사업 공고",
    "market": "시장 동향 전망",
    "company": "스타트업 기업 동향",
    "investment": "투자 유치 펀딩",
    "technology": "신기술 발표",
}


def interests_from_memory(db: Session) -> list[str]:
    items = [m.value for m in db.scalars(select(Memory).where(Memory.layer == "interest"))]
    items += [p.name for p in db.scalars(select(Project))]
    return list(dict.fromkeys(i.strip() for i in items if i and i.strip()))[:10]


def _recency_bonus(published: str | None) -> float:
    if not published:
        return 0.0
    try:
        d = datetime.fromisoformat(published[:10]).date()
    except ValueError:
        return 0.0
    days = (date.today() - d).days
    return 2.0 if days <= 30 else 1.0 if days <= 180 else 0.0


def scan(db: Session, interests: list[str] | None = None, categories: list[str] | None = None,
         per_query: int = 5) -> list[Opportunity]:
    provider = get_search_provider()
    interests = interests or interests_from_memory(db)
    scout = office.employee(db, "web_researcher")
    if provider is None:
        office.post(db, scout, "⚠️ 기회 스캔 불가: 검색 제공자가 설정되지 않았습니다.", kind="report")
        return []
    if not interests:
        office.post(db, scout, "기회 스캔: 관심 분야가 없습니다. 설정 → 메모리에 layer ‘interest’로 관심 분야를 저장해 주세요.", kind="report")
        return []
    cats = categories or list(CATEGORIES)
    queries: dict[str, tuple[str, str]] = {f"{i} {CATEGORIES[c]}": (i, c) for i in interests for c in cats}
    office.set_status(db, scout, "working", f"기회 스캔: 관심 분야 {len(interests)}개")
    results, errors = parallel_search(provider, list(queries), per_query)
    seen = set(db.scalars(select(Opportunity.url)))
    new: list[Opportunity] = []
    for r in results:
        if r.url in seen:
            continue
        interest, cat = queries.get(r.query, (r.query, "market"))
        tier, stype = classify_source(r.url, title=r.title)
        rel = len(set(tokenize(interest)) & set(tokenize(f"{r.title} {r.snippet}")))
        score = round((8 - tier) * 0.5 + _recency_bonus(r.published) + rel, 2)
        opp = Opportunity(interest=interest, category=cat, title=r.title[:500] or r.url, url=r.url, source_type=stype, tier=tier,
                          published=r.published, snippet=r.snippet[:1000], score=score)
        db.add(opp)
        seen.add(r.url)
        new.append(opp)
    db.commit()
    office.set_status(db, scout, "idle", "대기 중")
    audit(db, scout.name, "opportunity_scan", detail={"interests": interests, "new": len(new), "errors": errors})
    if new:
        top = sorted(new, key=lambda o: -o.score)[:5]
        body = "\n".join(f"· [{o.category}] {o.title[:80]}" for o in top)
        office.post(db, scout, f"🔭 새 기회 {len(new)}건을 찾았습니다 (스니펫 기준, 원문 미확인):\n{body}", channel="all", kind="report")
        office.notify(db, f"🔭 새 기회 {len(new)}건", body, link="/opportunities")
    return new


def to_task(db: Session, opp: Opportunity, project_id: int | None = None) -> Any:
    from app.pipeline.services import create_task

    t = create_task(db, f"{opp.title} — 이 기회를 원문부터 조사해서 핵심 요건·일정·적합성을 보고서로 정리해줘 (출처: {opp.url})", project_id,
                    actor="CEO→기회 스캐너")
    opp.status, opp.task_id = "tasked", t.id
    db.commit()
    return t
