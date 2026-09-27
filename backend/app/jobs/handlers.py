"""Job handlers: long-running work executed by the worker."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.jobs.queue import handler


@handler("research_task")
def _research(db: Session, p: dict[str, Any]) -> Any:
    from app.pipeline.research_pipeline import run_task

    return run_task(db, p["task_id"])


@handler("revise_task")
def _revise(db: Session, p: dict[str, Any]) -> Any:
    from app.pipeline.research_pipeline import revise_task

    return revise_task(db, p["task_id"], p["feedback"])


@handler("ingest_file")
def _ingest(db: Session, p: dict[str, Any]) -> Any:
    from app.knowledge.store import ingest_file

    return ingest_file(db, Path(p["path"]), project_id=p.get("project_id")).id


@handler("coding_task")
def _coding(db: Session, p: dict[str, Any]) -> Any:
    from app.agents.coding import CodingAgent
    from app.core.models import Task

    t = db.get(Task, p["task_id"])
    result = CodingAgent(db, task_id=t.id).build(p["spec"], p.get("project_slug"))
    t.result_summary = result
    t.status = "WAITING_USER" if result["passed"] else "FAILED"
    t.progress = 100
    db.commit()
    return result


@handler("meeting")
def _meeting(db: Session, p: dict[str, Any]) -> Any:
    from app.agents.meeting import run_adhoc_meeting

    return run_adhoc_meeting(db, p["title"], p["agenda"], p["participant_ids"], p.get("task_id"))


@handler("scheduled")
def _scheduled(db: Session, p: dict[str, Any]) -> Any:
    from app.jobs.scheduler import run_schedule

    return run_schedule(db, p["schedule_id"])


@handler("opportunity_scan")
def _opp(db: Session, p: dict[str, Any]) -> Any:
    from app.pipeline.opportunities import scan

    return len(scan(db, interests=p.get("interests")))
