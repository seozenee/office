"""Tiny helpers shared by SSE and pollers. Events are rows in DB tables (messages, audit_logs, tasks),
so API and worker processes see the same stream without a broker."""
from __future__ import annotations

from datetime import datetime


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
