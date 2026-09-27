"""Recurring automations. The worker calls `tick()` every poll; due schedules become jobs.

HIGH-risk actions are never scheduled directly: scheduled work only researches, writes and notifies;
anything external still goes through the approval gate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.models import Schedule
from app.jobs.queue import enqueue

log = logging.getLogger(__name__)
KINDS = {"daily_briefing", "weekly_review", "opportunity_scan", "research_task"}


def compute_next(sch: Schedule, after: datetime) -> datetime:
    tz = ZoneInfo(get_settings().timezone)
    local = after.astimezone(tz)
    if sch.frequency == "hourly":
        nxt = (local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        return nxt.astimezone(timezone.utc)
    hh, mm = (int(x) for x in (sch.time_of_day or "08:00").split(":"))
    cand = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if sch.frequency == "weekly":
        cand += timedelta(days=(sch.weekday - cand.weekday()) % 7)
        if cand <= local:
            cand += timedelta(days=7)
    elif cand <= local:
        cand += timedelta(days=1)
    return cand.astimezone(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def tick(db: Session, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    fired: list[int] = []
    for sch in db.scalars(select(Schedule).where(Schedule.enabled.is_(True))):
        nxt = _aware(sch.next_run_at)
        if nxt is None:
            sch.next_run_at = compute_next(sch, now)
            continue
        if nxt > now:
            continue
        # atomic claim so an API-embedded worker and a standalone worker never fire the same run twice
        claimed = db.execute(update(Schedule).where(Schedule.id == sch.id, Schedule.next_run_at == sch.next_run_at)
                             .values(next_run_at=compute_next(sch, now), last_run_at=now)).rowcount
        db.commit()
        if claimed != 1:
            continue
        job = enqueue(db, "scheduled", {"schedule_id": sch.id})
        sch.last_result = f"job #{job.id} queued"
        fired.append(sch.id)
    db.commit()
    return fired


def run_schedule(db: Session, schedule_id: int) -> str:
    from app.office import service as office
    from app.pipeline.briefing import daily_briefing, save_briefing, weekly_review
    from app.pipeline.opportunities import scan
    from app.pipeline.services import create_task

    sch = db.get(Schedule, schedule_id)
    if sch is None:
        raise LookupError("schedule not found")
    if sch.kind == "daily_briefing":
        r = save_briefing(db, daily_briefing(db), "daily")
        office.notify(db, "☀️ 오늘의 CEO 브리핑", r["markdown"][:1500], link="/documents")
        result = f"briefing artifact #{r['artifact_id']}"
    elif sch.kind == "weekly_review":
        r = save_briefing(db, weekly_review(db), "weekly")
        office.notify(db, "📅 주간 비즈니스 리뷰", r["markdown"][:1500], link="/documents")
        result = f"weekly review artifact #{r['artifact_id']}"
    elif sch.kind == "opportunity_scan":
        found = scan(db, interests=sch.payload.get("interests"))
        result = f"{len(found)} new opportunities"
    elif sch.kind == "research_task":
        t = create_task(db, sch.payload["request"], sch.payload.get("project_id"), actor=f"schedule:{sch.name}")
        result = f"task #{t.id}"
    else:
        raise ValueError(f"unknown schedule kind {sch.kind}")
    sch.last_result = result
    db.commit()
    return result
