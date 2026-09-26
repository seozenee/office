"""Office communication primitives: posting messages, statuses, 결재(approval chain) and meetings.
Every call writes rows the UI streams live (SSE), so the user can watch the whole company work."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.models import ActionItem, Approval, Channel, Employee, Meeting, Message, Notification

_channel_cache: dict[tuple[str, str | None, int | None], int] = {}


def channel_id(db: Session, kind: str, department: str | None = None, employee_id: int | None = None) -> int:
    key = (kind, department, employee_id)
    if key in _channel_cache and db.get(Channel, _channel_cache[key]) is not None:
        return _channel_cache[key]
    stmt = select(Channel.id).where(Channel.kind == kind)
    if department:
        stmt = stmt.where(Channel.department == department)
    if employee_id:
        stmt = stmt.where(Channel.employee_id == employee_id)
    cid = db.scalar(stmt)
    if cid is None:
        ch = Channel(kind=kind, name=department or kind, department=department, employee_id=employee_id)
        db.add(ch)
        db.flush()
        cid = ch.id
    _channel_cache[key] = cid
    return cid


def employee(db: Session, agent_type: str) -> Employee:
    emp = db.scalar(select(Employee).where(Employee.agent_type == agent_type))
    if emp is None:
        raise LookupError(f"no employee with agent_type={agent_type}")
    return emp


def lead_of(db: Session, department: str) -> Employee:
    return db.scalar(select(Employee).where(Employee.department == department, Employee.is_lead.is_(True)))


def post(db: Session, sender: Employee | None, content: str, *, channel: str = "department", kind: str = "chat",
         task_id: int | None = None, meta: dict[str, Any] | None = None, to: Employee | None = None,
         department: str | None = None, commit: bool = True) -> Message:
    dept = department or (sender.department if sender else None)
    if channel == "department":
        cid = channel_id(db, "department", department=dept)
    elif channel == "dm":
        target = to or sender
        cid = channel_id(db, "dm", employee_id=target.id if target else None)
    else:
        cid = channel_id(db, channel)
    msg = Message(channel_id=cid, sender_type="employee" if sender else "system", sender_id=sender.id if sender else None,
                  recipient_id=to.id if to else None, content=content, kind=kind, task_id=task_id, meta=meta or {})
    db.add(msg)
    if commit:
        db.commit()
    return msg


def set_status(db: Session, emp: Employee, status: str, text: str = "", task_id: int | None = None, commit: bool = True) -> None:
    emp.status = status
    emp.status_text = text[:300]
    emp.current_task_id = task_id
    if commit:
        db.commit()


def reset_statuses(db: Session, task_id: int | None = None) -> None:
    stmt = select(Employee)
    if task_id is not None:
        stmt = stmt.where(Employee.current_task_id == task_id)
    for emp in db.scalars(stmt):
        emp.status, emp.status_text, emp.current_task_id = "idle", "대기 중", None
    db.commit()


def notify(db: Session, title: str, body: str = "", task_id: int | None = None, link: str | None = None) -> Notification:
    n = Notification(title=title, body=body, task_id=task_id, link=link)
    db.add(n)
    db.commit()
    return n


# ---------------------------------------------------------------------------
# 결재 (approval chain)
# ---------------------------------------------------------------------------
def approval_line(db: Session, requester: Employee, requires_user: bool) -> list[dict[str, Any]]:
    line: list[dict[str, Any]] = []
    if not requester.is_lead:
        lead = lead_of(db, requester.department)
        line.append({"approver": f"{lead.name} {lead.title}", "employee_id": lead.id, "status": "pending", "note": None, "at": None})
    chief = employee(db, "orchestrator")
    if requester.id != chief.id:
        line.append({"approver": f"{chief.name} {chief.title}", "employee_id": chief.id, "status": "pending", "note": None, "at": None})
    if requires_user:
        line.append({"approver": "CEO", "employee_id": None, "status": "pending", "note": None, "at": None})
    return line


def request_approval(db: Session, requester: Employee, title: str, *, action: str, task_id: int | None,
                     risk: str = "LOW", payload: dict[str, Any] | None = None, requires_user: bool = False) -> Approval:
    appr = Approval(task_id=task_id, title=title, action=action, risk_level=risk, payload=payload or {},
                    requested_by=requester.id, line=approval_line(db, requester, requires_user), requires_user=requires_user)
    db.add(appr)
    db.flush()
    post(db, requester, f"📝 결재 요청: {title}", channel="approval", kind="approval_request", task_id=task_id,
         meta={"approval_id": appr.id, "risk": risk}, commit=False)
    post(db, requester, f"📝 결재 올렸습니다 — {title}", kind="approval_request", task_id=task_id,
         meta={"approval_id": appr.id}, commit=False)
    audit(db, requester.name, "approval_requested", target_type="approval", target_id=appr.id, task_id=task_id, risk=risk,
          detail={"title": title, "action": action}, commit=False)
    db.commit()
    return appr


def stamp(db: Session, appr: Approval, approver: Employee | None, approve: bool, note: str = "") -> Approval:
    """Stamp the next pending step of the approval line. approver=None means the user (CEO)."""
    line = [dict(s) for s in appr.line]
    step = next((s for s in line if s["status"] == "pending"), None)
    if step is None:
        return appr
    expected = step["employee_id"]
    actual = approver.id if approver else None
    if expected != actual:
        raise PermissionError(f"next approver is {step['approver']}")
    step.update(status="approved" if approve else "rejected", note=note or None, at=datetime.now(timezone.utc).isoformat())
    appr.line = line
    who = f"{approver.name} {approver.title}" if approver else "CEO"
    stamp_txt = "✅ 승인" if approve else "↩️ 반려"
    post(db, approver, f"{stamp_txt} [{appr.title}] {note}".strip(), channel="approval", kind="approval_stamp",
         task_id=appr.task_id, meta={"approval_id": appr.id, "approved": approve}, commit=False)
    if not approve:
        appr.status = "rejected"
        appr.decision_note = note
        appr.decided_at = datetime.now(timezone.utc)
    elif all(s["status"] == "approved" for s in line):
        appr.status = "approved"
        appr.decision_note = note
        appr.decided_at = datetime.now(timezone.utc)
    audit(db, who, "approval_stamped", target_type="approval", target_id=appr.id, task_id=appr.task_id,
          risk=appr.risk_level, detail={"approved": approve, "note": note}, commit=False)
    db.commit()
    return appr


def next_approver_is_user(appr: Approval) -> bool:
    step = next((s for s in appr.line if s["status"] == "pending"), None)
    return step is not None and step["employee_id"] is None


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------
def start_meeting(db: Session, title: str, participants: list[Employee], agenda: list[str], task_id: int | None) -> Meeting:
    m = Meeting(title=title, task_id=task_id, agenda=agenda, participant_ids=[p.id for p in participants],
                status="in_progress", channel_id=channel_id(db, "meeting"))
    db.add(m)
    db.flush()
    for p in participants:
        set_status(db, p, "meeting", f"회의 중: {title}", task_id, commit=False)
    post(db, None, f"🗓️ 회의 시작: {title}\n안건: " + " / ".join(agenda), channel="meeting", kind="meeting",
         task_id=task_id, meta={"meeting_id": m.id, "event": "start"}, commit=False)
    db.commit()
    pace(4)  # participants walk to the meeting room
    return m


def pace(factor: float = 1.0) -> None:
    """Presentation pacing so the office is watchable in real time (OFFICE_PACE_SECONDS)."""
    from app.core.config import get_settings

    delay = get_settings().office_pace_seconds * factor
    if delay > 0:
        time.sleep(delay)


def say_in_meeting(db: Session, m: Meeting, speaker: Employee, content: str) -> None:
    pace()
    post(db, speaker, content, channel="meeting", kind="meeting", task_id=m.task_id, meta={"meeting_id": m.id})


def end_meeting(db: Session, m: Meeting, decisions: list[str], action_items: list[dict[str, str]]) -> Meeting:
    m.status = "ended"
    m.ended_at = datetime.now(timezone.utc)
    m.decisions = decisions
    for ai in action_items:
        db.add(ActionItem(meeting_id=m.id, task_id=m.task_id, decision=ai.get("decision", ""), description=ai["description"],
                          owner=ai["owner"], deadline=ai.get("deadline"), status=ai.get("status", "open")))
    lines = [f"# 회의록: {m.title}", "", "## 안건", *[f"- {a}" for a in m.agenda], "", "## 결정 사항 (Decision)",
             *[f"- {d}" for d in decisions], "", "## Action Items", "| Action Item | Owner | Deadline | Status |", "|---|---|---|---|",
             *[f"| {a['description']} | {a['owner']} | {a.get('deadline') or '-'} | {a.get('status', 'open')} |" for a in action_items]]
    m.minutes = "\n".join(lines)
    post(db, None, f"🗓️ 회의 종료: {m.title} — 결정 {len(decisions)}건, 액션아이템 {len(action_items)}건", channel="meeting",
         kind="meeting", task_id=m.task_id, meta={"meeting_id": m.id, "event": "end"}, commit=False)
    for pid in m.participant_ids:
        emp = db.get(Employee, pid)
        if emp:
            set_status(db, emp, "working" if m.task_id else "idle", "회의 후속 작업", m.task_id, commit=False)
    db.commit()
    return m
