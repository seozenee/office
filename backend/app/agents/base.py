"""Agent base class. An agent = role + judgement (LLM prompt or deterministic rules) + office identity.
Agents never touch vendor SDKs or side-effectful code directly; they use the router and tools."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.models import Employee
from app.llm.base import LLMError
from app.llm.router import ModelRouter, get_router
from app.office import service as office

log = logging.getLogger(__name__)


class Agent:
    agent_type: str = "agent"
    name: str = "Agent"

    def __init__(self, db: Session, *, task_id: int | None = None, router: ModelRouter | None = None) -> None:
        self.db = db
        self.task_id = task_id
        self.router = router or get_router()
        self._employee: Employee | None = None

    @property
    def employee(self) -> Employee:
        if self._employee is None:
            self._employee = office.employee(self.db, self.agent_type)
        return self._employee

    @property
    def has_llm(self) -> bool:
        return self.router.available

    def persona_system(self) -> str:
        e = self.employee
        return (f"You are {e.name} ({e.title}, {e.role}) at the user's Personal AI Office. {e.persona}\n"
                "Rules: never present unsupported statements as facts; label statements FACT/ANALYSIS/ASSUMPTION/"
                "ESTIMATE/OPINION/UNKNOWN; if you do not know, say UNKNOWN. Answer in the user's language (Korean by default).")

    def say(self, text: str, *, channel: str = "department", kind: str = "chat", meta: dict[str, Any] | None = None) -> None:
        office.post(self.db, self.employee, text, channel=channel, kind=kind, task_id=self.task_id, meta=meta)

    def work(self, text: str) -> None:
        office.set_status(self.db, self.employee, "working", text, self.task_id)

    def idle(self) -> None:
        office.set_status(self.db, self.employee, "idle", "대기 중", None)

    def log(self, action: str, **detail: Any) -> None:
        audit(self.db, self.employee.name, action, task_id=self.task_id, detail=detail)

    def llm_json(self, task_kind: str, prompt: str, *, system: str | None = None) -> Any | None:
        """Call the LLM for JSON. Returns None (never raises) so callers fall back deterministically."""
        if not self.has_llm:
            return None
        try:
            return self.router.complete_json(task_kind, prompt, system=system or self.persona_system())
        except LLMError as e:
            log.warning("%s LLM call failed: %s", self.agent_type, e)
            self.log("llm_error", error=str(e)[:300], task_kind=task_kind)
            return None

    def llm_text(self, task_kind: str, prompt: str, *, system: str | None = None) -> str | None:
        if not self.has_llm:
            return None
        try:
            return self.router.complete(task_kind, prompt, system=system or self.persona_system()).text
        except LLMError as e:
            self.log("llm_error", error=str(e)[:300], task_kind=task_kind)
            return None
