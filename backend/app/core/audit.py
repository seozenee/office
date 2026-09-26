"""Audit log: every agent/tool/user action is recorded here."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.models import AuditLog
from app.core.security import mask_obj


def audit(db: Session, actor: str, action: str, *, target_type: str | None = None,
          target_id: int | None = None, task_id: int | None = None, risk: str = "LOW",
          detail: dict[str, Any] | None = None, commit: bool = True) -> AuditLog:
    entry = AuditLog(actor=actor, action=action, target_type=target_type, target_id=target_id,
                     task_id=task_id, risk=risk, detail=mask_obj(detail or {}))
    db.add(entry)
    if commit:
        db.commit()
    return entry
