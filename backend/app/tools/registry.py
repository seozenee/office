"""Tool registry with risk levels and the approval gate (spec §26).

LOW      search, analysis, document writing         → run
MEDIUM   file modification, calendar events         → run + audit (user can revert)
HIGH     external email, public posts               → requires user approval
CRITICAL payments, contracts, deletion, legal       → requires user approval
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.models import Approval, RiskLevel

_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


@dataclass
class ToolSpec:
    name: str
    description: str
    risk: RiskLevel
    fn: Callable[..., Any]
    category: str = "general"


class ApprovalRequired(Exception):
    def __init__(self, approval: Approval) -> None:
        super().__init__(f"approval #{approval.id} required for {approval.action}")
        self.approval = approval


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def execute(self, db: Session, name: str, *, actor: str, task_id: int | None = None,
                approval_id: int | None = None, **kwargs: Any) -> Any:
        spec = self.get(name)
        if needs_user_approval(spec.risk):
            approval = db.get(Approval, approval_id) if approval_id else None
            if approval is None or approval.status != "approved" or approval.action != name:
                approval = Approval(task_id=task_id, title=f"{spec.description}", action=name, risk_level=spec.risk.value,
                                    payload={"kwargs": {k: str(v)[:500] for k, v in kwargs.items()}, "kwargs_raw": kwargs},
                                    line=[{"approver": "CEO", "employee_id": None, "status": "pending", "note": None, "at": None}],
                                    requires_user=True)
                db.add(approval)
                db.commit()
                audit(db, actor, "approval_requested", target_type="approval", target_id=approval.id, task_id=task_id,
                      risk=spec.risk.value, detail={"tool": name})
                raise ApprovalRequired(approval)
        audit(db, actor, f"tool:{name}", task_id=task_id, risk=spec.risk.value,
              detail={"args": {k: str(v)[:200] for k, v in kwargs.items()}})
        return spec.fn(**kwargs)


def needs_user_approval(risk: RiskLevel) -> bool:
    return _ORDER[risk] >= _ORDER[RiskLevel.HIGH]


registry = ToolRegistry()
