"""Tasks, research, presentations, coding and briefings."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_user
from app.core.audit import audit
from app.core.db import get_db
from app.core.models import Approval, Artifact, AuditLog, Claim, Meeting, Project, Source, Task
from app.jobs.queue import enqueue
from app.pipeline.services import create_task

router = APIRouter(prefix="/api", tags=["tasks"], dependencies=[Depends(current_user)])


class TaskIn(BaseModel):
    request: str = Field(min_length=2, max_length=5000)
    project_id: int | None = None
    priority: int = Field(default=3, ge=1, le=5)
    deadline: datetime | None = None
    title: str | None = None
    deliverables: list[str] | None = None
    template_id: int | None = None
    document_id: int | None = Field(default=None, description="fact-check this knowledge-base document")


class TaskPatch(BaseModel):
    title: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    deadline: datetime | None = None
    status: str | None = None
    dependencies: list[int] | None = None


class ReviseIn(BaseModel):
    feedback: str = Field(min_length=2, max_length=3000)


def _create(db: Session, body: TaskIn, extra: list[str] | None = None) -> Task:
    try:
        t = create_task(db, body.request, body.project_id, priority=body.priority, deadline=body.deadline, title=body.title,
                        extra_deliverables=(body.deliverables or []) + (extra or []))
    except (ValueError, LookupError) as e:
        raise HTTPException(400, str(e)) from e
    if body.document_id:
        from app.core.models import KBDocument

        if db.get(KBDocument, body.document_id) is None:
            raise HTTPException(400, "document not found")
        t.plan = {**(t.plan or {}), "target_document_id": body.document_id}
        db.commit()
    if body.template_id:
        from app.core.models import Template

        tpl = db.get(Template, body.template_id)
        if tpl:
            t.plan = {**(t.plan or {}), "template": {"id": tpl.id, "name": tpl.name, "kind": tpl.kind, "structure": tpl.structure, "file_path": tpl.file_path}}
            db.commit()
    return t


@router.post("/tasks", status_code=201)
def post_task(body: TaskIn, db: Session = Depends(get_db)):
    return ser.task(_create(db, body), detail=True)


@router.post("/research", status_code=201)
def post_research(body: TaskIn, db: Session = Depends(get_db)):
    return ser.task(_create(db, body), detail=True)


@router.post("/presentations", status_code=201)
def post_presentation(body: TaskIn, db: Session = Depends(get_db)):
    return ser.task(_create(db, body, ["pptx"]), detail=True)


@router.get("/tasks")
def list_tasks(status: str | None = None, project_id: int | None = None, limit: int = 100, db: Session = Depends(get_db)):
    stmt = select(Task).order_by(desc(Task.id)).limit(min(limit, 500))
    if status:
        stmt = stmt.where(Task.status == status)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    return [ser.task(t) for t in db.scalars(stmt)]


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    out = ser.task(t, detail=True)
    out["artifacts"] = [ser.artifact(a) for a in db.scalars(select(Artifact).where(Artifact.task_id == task_id))]
    out["approvals"] = [ser.approval(a) for a in db.scalars(select(Approval).where(Approval.task_id == task_id))]
    out["meetings"] = [ser.meeting(m) for m in db.scalars(select(Meeting).where(Meeting.task_id == task_id))]
    srcs = list(db.scalars(select(Source).where(Source.task_id == task_id)))
    claims = list(db.scalars(select(Claim).where(Claim.task_id == task_id)))
    out["counts"] = {"sources": len(srcs), "sources_accessed": sum(s.accessed for s in srcs), "claims": len(claims),
                     "verified": sum(c.verification_status == "verified" for c in claims)}
    return out


@router.patch("/tasks/{task_id}")
def patch_task(task_id: int, body: TaskPatch, db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    audit(db, "CEO", "task_updated", target_type="task", target_id=t.id, task_id=t.id, detail=body.model_dump(exclude_unset=True, mode="json"))
    return ser.task(t, detail=True)


@router.post("/tasks/{task_id}/revise", status_code=202)
def revise(task_id: int, body: ReviseIn, db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    job = enqueue(db, "revise_task", {"task_id": task_id, "feedback": body.feedback}, task_id=task_id)
    return {"job_id": job.id}


@router.post("/tasks/{task_id}/retry", status_code=202)
def retry(task_id: int, db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    t.status, t.error, t.progress = "BACKLOG", None, 0
    db.commit()
    job = enqueue(db, "research_task", {"task_id": task_id}, task_id=task_id)
    return {"job_id": job.id}


@router.get("/tasks/{task_id}/audit")
def task_audit(task_id: int, db: Session = Depends(get_db)):
    return [ser.audit_entry(a) for a in db.scalars(select(AuditLog).where(AuditLog.task_id == task_id).order_by(AuditLog.id))]


@router.get("/tasks/{task_id}/claims")
def task_claims(task_id: int, db: Session = Depends(get_db)):
    return [ser.claim(c) for c in db.scalars(select(Claim).where(Claim.task_id == task_id).order_by(desc(Claim.confidence)))]


# --- coding -----------------------------------------------------------------------------------
class CodingIn(BaseModel):
    spec: str = Field(min_length=5)
    project_id: int | None = None


@router.post("/coding", status_code=201)
def coding(body: CodingIn, db: Session = Depends(get_db)):
    project = db.get(Project, body.project_id) if body.project_id else None
    t = Task(title=f"코딩: {body.spec[:80]}", request=body.spec, project_id=body.project_id, status="PLANNED", agents=["data"])
    db.add(t)
    db.commit()
    enqueue(db, "coding_task", {"task_id": t.id, "spec": body.spec, "project_slug": project.slug if project else None}, task_id=t.id)
    return ser.task(t)


class AnalyzeIn(BaseModel):
    path: str


@router.post("/coding/analyze")
def analyze(body: AnalyzeIn):
    from app.agents.coding import analyze_project
    from app.core.files import UnsafePathError

    try:
        return analyze_project(body.path)
    except UnsafePathError as e:
        raise HTTPException(403, str(e)) from e


# --- briefings --------------------------------------------------------------------------------
@router.post("/briefing/daily")
def briefing_daily(db: Session = Depends(get_db)):
    from app.pipeline.briefing import daily_briefing, save_briefing

    return save_briefing(db, daily_briefing(db), "daily")


@router.post("/briefing/weekly")
def briefing_weekly(db: Session = Depends(get_db)):
    from app.pipeline.briefing import save_briefing, weekly_review

    return save_briefing(db, weekly_review(db), "weekly")
