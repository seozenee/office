"""Daily CEO Briefing and Weekly Business Review, built from real office data (+ connected plugins)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import ActionItem, Approval, Claim, Meeting, Source, Task
from app.generators.content import Block, ReportContent, Section, Statement
from app.generators.docx_builder import build_docx
from app.generators.export import to_markdown
from app.pipeline.artifacts import save_artifact
from app.plugins.base import PluginNotConfigured, calendar_list, get_plugin, gmail_list


def _plugin_section(key: str, fn, label: str) -> list[Statement]:
    p = get_plugin(key)
    if not p.configured:
        return [Statement(f"{label}: {p.name} 미연결 (환경변수 {', '.join(p.env)} 설정 시 표시)", "UNKNOWN")]
    try:
        items = fn()
    except (PluginNotConfigured, Exception) as e:  # noqa: BLE001
        return [Statement(f"{label} 조회 실패: {e}", "UNKNOWN")]
    return [Statement(str(i)[:200]) for i in items[:8]] or [Statement(f"{label}: 없음")]


def daily_briefing(db: Session) -> ReportContent:
    now = datetime.now(timezone.utc)
    open_tasks = list(db.scalars(select(Task).where(Task.status.notin_(["DONE", "FAILED"])).order_by(Task.priority, Task.deadline)))
    soon = [t for t in open_tasks if t.deadline and t.deadline.replace(tzinfo=t.deadline.tzinfo or timezone.utc) <= now + timedelta(days=7)]
    pending = list(db.scalars(select(Approval).where(Approval.status == "pending")))
    user_pending = [a for a in pending if any(s["employee_id"] is None and s["status"] == "pending" for s in a.line)]
    new_sources = list(db.scalars(select(Source).where(Source.access_date >= now - timedelta(days=1), Source.accessed.is_(True))))
    open_actions = list(db.scalars(select(ActionItem).where(ActionItem.status != "done")))
    c = ReportContent(title=f"CEO 데일리 브리핑 — {now.date().isoformat()}", subtitle="오늘의 우선순위와 결재")
    c.sections = [
        Section("오늘의 우선순위", [Block("bullets", [Statement(f"#{t.id} {t.title} — {t.status} {t.progress:.0f}% (우선순위 {t.priority})") for t in open_tasks[:8]]
                                                   or [Statement("진행 중인 작업이 없습니다.")])]),
        Section("마감 임박 (7일 이내)", [Block("bullets", [Statement(f"#{t.id} {t.title} — 마감 {t.deadline.date()}") for t in soon]
                                                     or [Statement("7일 이내 마감 작업이 없습니다.")])]),
        Section("CEO 결재 대기", [Block("bullets", [Statement(f"결재 #{a.id} {a.title} (위험도 {a.risk_level})") for a in user_pending]
                                                or [Statement("대기 중인 결재가 없습니다.")])]),
        Section("중요 이메일", [Block("bullets", _plugin_section("gmail", gmail_list, "메일"))]),
        Section("일정", [Block("bullets", _plugin_section("calendar", calendar_list, "일정"))]),
        Section("리서치 업데이트 (24시간)", [Block("bullets", [Statement(f"{s.title[:90]} ({s.source_type})") for s in new_sources[:10]]
                                                        or [Statement("새로 확인한 출처가 없습니다.")])]),
        Section("열린 액션아이템", [Block("table", header=["Action Item", "Owner", "Deadline", "Status"],
                                          rows=[[a.description, a.owner, a.deadline or "-", a.status] for a in open_actions[:20]])]
                if open_actions else [Block("paragraph", [Statement("열린 액션아이템이 없습니다.")])]),
        Section("추천 작업", [Block("bullets", ([Statement(f"결재 #{user_pending[0].id} 먼저 처리", "OPINION")] if user_pending else []) +
                                    ([Statement(f"마감 임박 작업 #{soon[0].id} 점검", "OPINION")] if soon else []) or
                                    [Statement("새 업무를 지시해 주세요.", "OPINION")])]),
    ]
    return c


def weekly_review(db: Session) -> ReportContent:
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    tasks = list(db.scalars(select(Task).where(Task.updated_at >= week)))
    done = [t for t in tasks if t.status in ("DONE", "WAITING_USER")]
    prog = [t for t in tasks if t.status not in ("DONE", "WAITING_USER", "FAILED")]
    blocked = [t for t in tasks if t.status == "FAILED"]
    decisions = [d for m in db.scalars(select(Meeting).where(Meeting.created_at >= week)) for d in (m.decisions or [])]
    facts = list(db.scalars(select(Claim).where(Claim.created_at >= week, Claim.verification_status == "verified").order_by(Claim.confidence.desc()).limit(8)))
    st = lambda ts: [Statement(f"#{t.id} {t.title}") for t in ts] or [Statement("없음")]  # noqa: E731
    c = ReportContent(title=f"주간 비즈니스 리뷰 — {week.date()} ~ {now.date()}")
    c.sections = [Section("완료", [Block("bullets", st(done))]), Section("진행 중", [Block("bullets", st(prog))]),
                  Section("차단/실패", [Block("bullets", st(blocked))]),
                  Section("주요 결정", [Block("bullets", [Statement(d) for d in decisions[:12]] or [Statement("없음")])]),
                  Section("리서치 발견 (검증된 사실)", [Block("bullets", [Statement(f.text[:250], "FACT") for f in facts] or [Statement("없음")])]),
                  Section("다음 주 우선순위", [Block("bullets", [Statement(f"#{t.id} {t.title}", "OPINION") for t in prog[:5]] or [Statement("새 업무 지시 필요", "OPINION")])])]
    return c


def save_briefing(db: Session, content: ReportContent, kind: str) -> dict:
    art, ver = save_artifact(db, title=content.title, fmt="docx", build=lambda p: build_docx(content, p), author_agent="Chief of Staff",
                             project=None, task_id=None, kind="report")
    md = to_markdown(content)
    return {"artifact_id": art.id, "file": ver.file_path, "markdown": md, "kind": kind}


__all__ = ["daily_briefing", "weekly_review", "save_briefing", "Path"]
