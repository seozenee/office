"""Auth, projects, memory, templates, plugins/tools, settings, audit log, health."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_user
from app.core.audit import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.files import project_root, slugify
from app.core.models import AuditLog, Memory, Project, Template, User
from app.core.security import create_token, verify_password
from app.llm.router import TASK_TIER, get_router
from app.plugins.base import PLUGINS
from app.tools.registry import ApprovalRequired, registry
from app.tools.web import get_search_provider

public = APIRouter(prefix="/api", tags=["auth"])
router = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(current_user)])


class LoginIn(BaseModel):
    username: str
    password: str


@public.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        audit(db, body.username[:50], "login_failed", risk="MEDIUM")
        raise HTTPException(401, "invalid credentials")
    audit(db, user.username, "login")
    return {"token": create_token(user.username), "username": user.username}


@public.get("/health")
def health():
    r = get_router()
    return {"status": "ok", "llm": r.provider.name if r.provider else "offline", "time": datetime.now(timezone.utc).isoformat(),
            "auth": get_settings().auth_enabled}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"username": user.username, "role": user.role}


# --- projects --------------------------------------------------------------------------------
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    context: str = ""


@router.get("/projects")
def projects(db: Session = Depends(get_db)):
    return [ser.project(p) for p in db.scalars(select(Project).order_by(Project.id))]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    slug = slugify(body.name)
    base, n = slug, 2
    while db.scalar(select(Project.id).where(Project.slug == slug)):
        slug = f"{base}_{n}"
        n += 1
    p = Project(name=body.name, slug=slug, description=body.description, context=body.context)
    db.add(p)
    db.commit()
    project_root(p.slug)
    audit(db, "CEO", "project_created", target_type="project", target_id=p.id)
    return ser.project(p)


@router.patch("/projects/{pid}")
def update_project(pid: int, body: ProjectIn, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if p is None:
        raise HTTPException(404, "project not found")
    p.name, p.description, p.context = body.name, body.description, body.context
    db.commit()
    return ser.project(p)


@router.get("/projects/{pid}")
def project_detail(pid: int, db: Session = Depends(get_db)):
    from app.core.models import Artifact, KBDocument, Source, Task

    p = db.get(Project, pid)
    if p is None:
        raise HTTPException(404, "project not found")
    return ser.project(p) | {
        "tasks": [ser.task(t) for t in db.scalars(select(Task).where(Task.project_id == pid).order_by(desc(Task.id)))],
        "documents": [ser.kb_document(d) for d in db.scalars(select(KBDocument).where(KBDocument.project_id == pid))],
        "artifacts": [ser.artifact(a) for a in db.scalars(select(Artifact).where(Artifact.project_id == pid))],
        "sources": db.query(Source).filter(Source.project_id == pid).count(),
        "decisions": [{"key": m.key, "value": m.value} for m in db.scalars(select(Memory).where(Memory.project_id == pid, Memory.layer == "decision"))],
    }


# --- memory ---------------------------------------------------------------------------------
MEMORY_LAYERS = ["preference", "project", "company", "person", "document", "decision", "task", "fact", "temporary"]


class MemoryIn(BaseModel):
    layer: str
    key: str = Field(min_length=1, max_length=300)
    value: str = Field(min_length=1, max_length=5000)
    project_id: int | None = None
    ttl_hours: int | None = None


@router.get("/memory")
def memory(layer: str | None = None, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    stmt = select(Memory).where(or_(Memory.expires_at.is_(None), Memory.expires_at > now)).order_by(desc(Memory.id))
    if layer:
        stmt = stmt.where(Memory.layer == layer)
    return [{"id": m.id, "layer": m.layer, "key": m.key, "value": m.value, "project_id": m.project_id, "origin": m.origin,
             "expires_at": m.expires_at.isoformat() if m.expires_at else None} for m in db.scalars(stmt)]


@router.post("/memory", status_code=201)
def add_memory(body: MemoryIn, db: Session = Depends(get_db)):
    from app.pipeline.services import remember

    if body.layer not in MEMORY_LAYERS:
        raise HTTPException(400, f"layer must be one of {MEMORY_LAYERS}")
    ttl = body.ttl_hours or (24 if body.layer == "temporary" else None)
    m = remember(db, body.layer, body.key, body.value, project_id=body.project_id, origin="explicit", ttl_hours=ttl)
    return {"id": m.id}


@router.delete("/memory/{mid}")
def forget(mid: int, db: Session = Depends(get_db)):
    m = db.get(Memory, mid)
    if m is None:
        raise HTTPException(404, "not found")
    db.delete(m)
    db.commit()
    return {"deleted": mid}


# --- templates -----------------------------------------------------------------------------
@router.get("/templates")
def templates(db: Session = Depends(get_db)):
    return [{"id": t.id, "name": t.name, "kind": t.kind, "description": t.description, "structure": t.structure,
             "has_file": bool(t.file_path), "builtin": t.builtin} for t in db.scalars(select(Template).order_by(Template.id))]


@router.post("/templates", status_code=201)
async def add_template(name: str = Form(...), kind: str = Form(...), description: str = Form(""), sections: str = Form(""),
                       file: UploadFile | None = File(default=None), db: Session = Depends(get_db)):
    path = None
    if file is not None and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in (".docx", ".pptx"):
            raise HTTPException(415, "template file must be .docx or .pptx")
        dest = project_root(None) / "data" / "templates" / f"{slugify(name)}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await file.read())
        path = str(dest)
    t = Template(name=name, kind=kind, description=description, file_path=path,
                 structure={"sections": [s.strip() for s in sections.split("\n") if s.strip()]})
    db.add(t)
    db.commit()
    return {"id": t.id}


# --- plugins / tools -------------------------------------------------------------------------
@router.get("/plugins")
def plugins():
    return [p.info() for p in PLUGINS]


@router.get("/tools")
def tools():
    return [{"name": t.name, "description": t.description, "risk": t.risk.value, "category": t.category} for t in registry.list()]


class ToolRun(BaseModel):
    args: dict = {}
    task_id: int | None = None


@router.post("/tools/{name}/execute")
def execute_tool(name: str, body: ToolRun, db: Session = Depends(get_db)):
    try:
        return {"result": registry.execute(db, name, actor="CEO", task_id=body.task_id, **body.args)}
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ApprovalRequired as e:
        return {"approval_required": True, "approval": ser.approval(e.approval)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {e}") from e


# --- settings / audit ---------------------------------------------------------------------------
@router.get("/settings")
def settings_view():
    s = get_settings()
    r = get_router()
    sp = get_search_provider()
    return {"llm_provider": r.provider.name if r.provider else "offline",
            "models": {tier.value: r.model_for(tier) for tier in set(TASK_TIER.values())},
            "routing": {k: v.value for k, v in TASK_TIER.items()}, "usage": r.usage,
            "search_provider": sp.name if sp else None, "embedding_provider": s.embedding_provider,
            "auth_enabled": s.auth_enabled, "inline_worker": s.inline_worker, "database": s.database_url.split(":")[0],
            "stale_after_years": s.stale_after_years, "min_verified_ratio": s.min_verified_ratio, "max_research_rounds": s.max_research_rounds}


@router.get("/audit")
def audit_log(task_id: int | None = None, limit: int = 200, db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(desc(AuditLog.id)).limit(min(limit, 2000))
    if task_id:
        stmt = stmt.where(AuditLog.task_id == task_id)
    return [ser.audit_entry(a) for a in db.scalars(stmt)]
