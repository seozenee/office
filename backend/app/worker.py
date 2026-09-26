"""Standalone worker process: python -m app.worker"""
from __future__ import annotations

import logging

from app.core.db import SessionLocal, init_db
from app.jobs.queue import Worker, recover_stale

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    with SessionLocal() as db:
        n = recover_stale(db)
        if n:
            logging.warning("marked %d stale job(s) as failed", n)
    w = Worker()
    logging.info("worker %s started", w.name)
    try:
        w.loop()
    except KeyboardInterrupt:
        w.stop()
