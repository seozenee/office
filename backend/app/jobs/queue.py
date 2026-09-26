"""DB-backed background job queue. Works across processes (API + `python -m app.worker`)
without a broker; swap for Celery/RQ by re-implementing enqueue()/claim()."""
from __future__ import annotations

import logging
import socket
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.models import Job

log = logging.getLogger(__name__)
HANDLERS: dict[str, Callable[[Session, dict[str, Any]], Any]] = {}


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def enqueue(db: Session, kind: str, payload: dict[str, Any], task_id: int | None = None) -> Job:
    job = Job(kind=kind, payload=payload, task_id=task_id)
    db.add(job)
    db.commit()
    return job


def claim(db: Session, worker: str) -> Job | None:
    job_id = db.scalar(select(Job.id).where(Job.status == "queued").order_by(Job.id).limit(1))
    if job_id is None:
        return None
    res = db.execute(update(Job).where(Job.id == job_id, Job.status == "queued")
                     .values(status="running", worker=worker, started_at=datetime.now(timezone.utc), attempts=Job.attempts + 1))
    db.commit()
    if res.rowcount != 1:
        return None  # another worker took it
    return db.get(Job, job_id)


def run_job(db: Session, job: Job) -> None:
    fn = HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise LookupError(f"no handler for job kind {job.kind}")
        fn(db, job.payload)
        job.status = "succeeded"
    except Exception as e:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job.id)
        job.status = "failed"
        job.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}"
        log.error("job %s failed: %s", job.id, e)
    job.finished_at = datetime.now(timezone.utc)
    db.commit()


def recover_stale(db: Session) -> int:
    """Jobs left 'running' by a crashed worker are marked failed (never silently re-run)."""
    stale = list(db.scalars(select(Job).where(Job.status == "running")))
    for j in stale:
        j.status = "failed"
        j.error = "worker stopped while job was running (recovered on startup)"
    db.commit()
    return len(stale)


class Worker:
    def __init__(self) -> None:
        self.name = f"{socket.gethostname()}-{threading.get_ident()}"
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def loop(self) -> None:
        from app.jobs import handlers  # noqa: F401  (register handlers)

        poll = get_settings().worker_poll_seconds
        while not self._stop.is_set():
            db = SessionLocal()
            try:
                job = claim(db, self.name)
                if job is None:
                    db.close()
                    self._stop.wait(poll)
                    continue
                run_job(db, job)
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")
                time.sleep(poll)
            finally:
                db.close()

    def start_background(self) -> None:
        self.thread = threading.Thread(target=self.loop, name="office-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()


def drain(max_jobs: int = 50) -> int:
    """Run queued jobs synchronously (tests / CLI)."""
    from app.jobs import handlers  # noqa: F401

    n = 0
    while n < max_jobs:
        db = SessionLocal()
        try:
            job = claim(db, "drain")
            if job is None:
                return n
            run_job(db, job)
            n += 1
        finally:
            db.close()
    return n
