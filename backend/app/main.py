"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import knowledge, office, system, tasks
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.core.models import Template, User
from app.core.security import hash_password
from app.jobs.queue import Worker, recover_stale
from app.office.roster import seed_office
from app.tools.builtin import register_builtin_tools

log = logging.getLogger("office")

BUILTIN_TEMPLATES = [
    ("학교 연구보고서", "report", ["연구 배경", "선행 연구", "연구 방법", "결과", "논의", "결론"]),
    ("사업계획서", "business_plan", ["사업 개요", "문제 정의", "해결 방안", "시장 분석", "비즈니스 모델", "전략 및 GTM", "재무 계획", "리스크"]),
    ("투자자 PPT", "pitch_deck", ["Problem", "Evidence", "Insight", "Solution", "Business Model", "Market", "Strategy", "Financials", "Roadmap", "Conclusion"]),
    ("연구 발표 PPT", "research_deck", ["연구 질문", "방법", "데이터", "결과", "시사점", "향후 연구"]),
    ("회의록", "minutes", ["안건", "논의", "Decision", "Action Item", "Owner", "Deadline", "Status"]),
    ("주간보고서", "weekly", ["Completed", "In Progress", "Blocked", "Important Decisions", "Research Findings", "Next Week Priorities"]),
]


def seed() -> None:
    s = get_settings()
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == s.admin_username)):
            db.add(User(username=s.admin_username, password_hash=hash_password(s.admin_password), role="owner"))
        if not db.scalar(select(Template.id).limit(1)):
            for name, kind, sections in BUILTIN_TEMPLATES:
                db.add(Template(name=name, kind=kind, description=f"기본 {name} 템플릿", structure={"sections": sections}, builtin=True))
        db.commit()
        seed_office(db)
        stale = recover_stale(db)
        if stale:
            log.warning("recovered %d stale jobs", stale)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed()
    register_builtin_tools()
    worker = None
    if get_settings().inline_worker:
        worker = Worker()
        worker.start_background()
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    s = get_settings()
    if s.environment == "production" and s.secret_key == "change-me-in-production":
        raise RuntimeError("SECRET_KEY must be set in production")
    app = FastAPI(title=s.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    for r in (system.public, system.router, tasks.router, knowledge.router, office.router):
        app.include_router(r)
    return app


app = create_app()
