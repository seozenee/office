"""Pixel office: layout, employees, channels, messages, DMs, meetings, approvals (결재), notifications, live events."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_user
from app.core.db import SessionLocal, get_db
from app.core.models import Approval, Channel, Employee, Meeting, Message, Notification, Task
from app.jobs.queue import enqueue
from app.office.dm import dm_channel_messages, handle_dm
from app.office.roster import DEPARTMENTS, MAP, ROOMS
from app.pipeline.services import create_task, decide_approval

router = APIRouter(prefix="/api", tags=["office"], dependencies=[Depends(current_user)])


@router.get("/office/layout")
def layout(db: Session = Depends(get_db)):
    return {"map": MAP, "rooms": ROOMS, "departments": DEPARTMENTS,
            "employees": [ser.employee(e) for e in db.scalars(select(Employee).order_by(Employee.id))]}


@router.get("/office/employees")
def employees(db: Session = Depends(get_db)):
    return [ser.employee(e) for e in db.scalars(select(Employee).order_by(Employee.id))]


@router.get("/office/employees/{emp_id}")
def employee_detail(emp_id: int, db: Session = Depends(get_db)):
    e = db.get(Employee, emp_id)
    if e is None:
        raise HTTPException(404, "employee not found")
    recent = list(db.scalars(select(Message).where(Message.sender_type == "employee", Message.sender_id == emp_id).order_by(desc(Message.id)).limit(20)))
    return ser.employee(e) | {"recent_messages": [ser.message(m) for m in recent]}


@router.get("/office/channels")
def channels(db: Session = Depends(get_db)):
    return [{"id": c.id, "kind": c.kind, "name": c.name, "department": c.department, "employee_id": c.employee_id}
            for c in db.scalars(select(Channel).order_by(Channel.id))]


@router.get("/office/messages")
def messages(channel_id: int | None = None, task_id: int | None = None, after_id: int = 0, limit: int = 200,
             include_dm: bool = False, db: Session = Depends(get_db)):
    stmt = select(Message).where(Message.id > after_id)
    if channel_id:
        stmt = stmt.where(Message.channel_id == channel_id)
    elif not include_dm:
        dm_ids = select(Channel.id).where(Channel.kind == "dm")
        stmt = stmt.where(Message.channel_id.notin_(dm_ids))
    if task_id:
        stmt = stmt.where(Message.task_id == task_id)
    rows = list(db.scalars(stmt.order_by(desc(Message.id)).limit(min(limit, 1000))))
    return [ser.message(m) for m in reversed(rows)]


class DMIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    project_id: int | None = None


@router.get("/office/dm/{emp_id}")
def dm_history(emp_id: int, db: Session = Depends(get_db)):
    e = db.get(Employee, emp_id)
    if e is None:
        raise HTTPException(404, "employee not found")
    return [ser.message(m) for m in dm_channel_messages(db, e)]


@router.post("/office/dm/{emp_id}")
def send_dm(emp_id: int, body: DMIn, db: Session = Depends(get_db)):
    e = db.get(Employee, emp_id)
    if e is None:
        raise HTTPException(404, "employee not found")
    user_msg, reply, task_id = handle_dm(db, e, body.text, project_id=body.project_id,
                                         create_task=lambda text, pid: create_task(db, text, pid, actor=f"CEO→{e.name}"))
    return {"message": ser.message(user_msg), "reply": ser.message(reply), "task_id": task_id}


class MeetingIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    agenda: list[str] = Field(min_length=1, max_length=10)
    participant_ids: list[int] = Field(min_length=2, max_length=12)
    task_id: int | None = None


@router.post("/office/meetings", status_code=202)
def call_meeting(body: MeetingIn, db: Session = Depends(get_db)):
    job = enqueue(db, "meeting", body.model_dump(), task_id=body.task_id)
    return {"job_id": job.id}


@router.get("/office/meetings")
def meetings(db: Session = Depends(get_db)):
    return [ser.meeting(m) for m in db.scalars(select(Meeting).order_by(desc(Meeting.id)).limit(100))]


@router.get("/office/meetings/{meeting_id}")
def meeting_detail(meeting_id: int, db: Session = Depends(get_db)):
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise HTTPException(404, "meeting not found")
    msgs = [x for x in db.scalars(select(Message).where(Message.channel_id == m.channel_id).order_by(Message.id)) if (x.meta or {}).get("meeting_id") == m.id]
    return ser.meeting(m) | {"transcript": [ser.message(x) for x in msgs]}


# --- approvals ----------------------------------------------------------------------------
@router.get("/approvals")
def approvals(status: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Approval).order_by(desc(Approval.id))
    if status:
        stmt = stmt.where(Approval.status == status)
    return [ser.approval(a) for a in db.scalars(stmt.limit(300))]


class DecisionIn(BaseModel):
    approve: bool
    note: str = ""


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: int, body: DecisionIn, db: Session = Depends(get_db)):
    try:
        return decide_approval(db, approval_id, body.approve, body.note)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except (ValueError, PermissionError) as e:
        raise HTTPException(409, str(e)) from e


# --- notifications -------------------------------------------------------------------------
@router.get("/notifications")
def notifications(unread: bool = False, db: Session = Depends(get_db)):
    stmt = select(Notification).order_by(desc(Notification.id)).limit(100)
    if unread:
        stmt = stmt.where(Notification.read.is_(False))
    return [ser.notification(n) for n in db.scalars(stmt)]


@router.post("/notifications/{nid}/read")
def read_notification(nid: int, db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n is None:
        raise HTTPException(404, "not found")
    n.read = True
    db.commit()
    return ser.notification(n)


# --- live events (SSE) ----------------------------------------------------------------------
@router.get("/events/stream")
async def stream(request: Request, after_id: int = 0):
    """Server-sent events: new office messages (non-DM + DM), employee states, active tasks, notifications."""

    async def gen():
        last = after_id
        last_notif = 0
        tick = 0
        while not await request.is_disconnected():
            with SessionLocal() as db:
                if last == 0:
                    last = (db.scalar(select(Message.id).order_by(desc(Message.id)).limit(1)) or 0) - 60
                msgs = list(db.scalars(select(Message).where(Message.id > last).order_by(Message.id).limit(200)))
                for m in msgs:
                    yield f"event: message\ndata: {json.dumps(ser.message(m), ensure_ascii=False)}\n\n"
                    last = m.id
                notifs = list(db.scalars(select(Notification).where(Notification.id > last_notif).order_by(Notification.id)))
                for n in notifs:
                    if last_notif:
                        yield f"event: notification\ndata: {json.dumps(ser.notification(n), ensure_ascii=False)}\n\n"
                    last_notif = n.id
                if tick % 2 == 0 or msgs:
                    emps = [{"id": e.id, "status": e.status, "status_text": e.status_text, "current_task_id": e.current_task_id}
                            for e in db.scalars(select(Employee))]
                    tasks = [ser.task(t) for t in db.scalars(select(Task).order_by(desc(Task.id)).limit(15))]
                    pending = db.scalar(select(Approval.id).where(Approval.status == "pending").limit(1)) is not None
                    yield f"event: state\ndata: {json.dumps({'employees': emps, 'tasks': tasks, 'pending_approvals': pending}, ensure_ascii=False)}\n\n"
            tick += 1
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
