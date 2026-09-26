"""ORM → JSON helpers (kept explicit so secrets/internal fields never leak)."""
from __future__ import annotations

from typing import Any

from app.core.events import iso
from app.core.models import (ActionItem, Approval, Artifact, AuditLog, Claim, Employee, KBDocument, Meeting, Message,
                             Notification, Project, Source, Task, TaskStep)


def task(t: Task, detail: bool = False) -> dict[str, Any]:
    d = {"id": t.id, "title": t.title, "request": t.request, "status": t.status, "priority": t.priority, "deadline": iso(t.deadline),
         "owner": t.owner, "project_id": t.project_id, "progress": t.progress, "current_step": t.current_step, "agents": t.agents,
         "dependencies": t.dependencies, "error": t.error, "created_at": iso(t.created_at), "updated_at": iso(t.updated_at)}
    if detail:
        d["plan"] = t.plan
        d["result_summary"] = t.result_summary
        d["steps"] = [step(s) for s in t.steps]
    return d


def step(s: TaskStep) -> dict[str, Any]:
    return {"id": s.id, "name": s.name, "agent": s.agent, "employee_id": s.employee_id, "status": s.status, "detail": s.detail,
            "started_at": iso(s.started_at), "finished_at": iso(s.finished_at)}


def project(p: Project) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "slug": p.slug, "description": p.description, "context": p.context, "created_at": iso(p.created_at)}


def source(s: Source) -> dict[str, Any]:
    return {"id": s.id, "title": s.title, "url": s.url, "publisher": s.publisher, "source_type": s.source_type, "tier": s.tier,
            "publication_date": s.publication_date, "access_date": iso(s.access_date), "accessed": s.accessed,
            "access_error": s.access_error, "task_id": s.task_id, "project_id": s.project_id, "kb_document_id": s.kb_document_id,
            "snippet": s.snippet, "query": s.query}


def claim(c: Claim) -> dict[str, Any]:
    return {"id": c.id, "text": c.text, "kind": c.kind, "topic": c.topic, "source_id": c.source_id, "supporting_quote": c.supporting_quote,
            "page_number": c.page_number, "confidence": c.confidence, "verification_status": c.verification_status,
            "verification_notes": c.verification_notes, "corroborating_source_ids": c.corroborating_source_ids, "task_id": c.task_id}


def artifact(a: Artifact) -> dict[str, Any]:
    return {"id": a.id, "kind": a.kind, "title": a.title, "status": a.status, "author_agent": a.author_agent, "version": a.current_version,
            "task_id": a.task_id, "project_id": a.project_id, "sources": a.source_ids, "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
            "versions": [{"id": v.id, "version": v.version, "label": v.label, "format": v.format, "file_name": v.file_path.rsplit("/", 1)[-1],
                          "change_note": v.change_note, "size_bytes": v.size_bytes, "checksum": v.checksum, "created_at": iso(v.created_at)} for v in a.versions]}


def approval(a: Approval) -> dict[str, Any]:
    return {"id": a.id, "title": a.title, "action": a.action, "risk_level": a.risk_level, "status": a.status, "line": a.line,
            "requires_user": a.requires_user, "requested_by": a.requested_by, "task_id": a.task_id, "payload": a.payload,
            "decision_note": a.decision_note, "created_at": iso(a.created_at), "decided_at": iso(a.decided_at)}


def employee(e: Employee) -> dict[str, Any]:
    return {"id": e.id, "name": e.name, "department": e.department, "title": e.title, "role": e.role, "agent_type": e.agent_type,
            "is_lead": e.is_lead, "persona": e.persona, "appearance": e.appearance, "desk": e.desk, "status": e.status,
            "status_text": e.status_text, "current_task_id": e.current_task_id}


def message(m: Message) -> dict[str, Any]:
    return {"id": m.id, "channel_id": m.channel_id, "sender_type": m.sender_type, "sender_id": m.sender_id, "recipient_id": m.recipient_id,
            "content": m.content, "kind": m.kind, "task_id": m.task_id, "meta": m.meta, "created_at": iso(m.created_at)}


def meeting(m: Meeting) -> dict[str, Any]:
    return {"id": m.id, "title": m.title, "task_id": m.task_id, "agenda": m.agenda, "participant_ids": m.participant_ids, "status": m.status,
            "decisions": m.decisions, "minutes": m.minutes, "created_at": iso(m.created_at), "ended_at": iso(m.ended_at),
            "action_items": [action_item(a) for a in m.action_items]}


def action_item(a: ActionItem) -> dict[str, Any]:
    return {"id": a.id, "decision": a.decision, "description": a.description, "owner": a.owner, "deadline": a.deadline, "status": a.status,
            "meeting_id": a.meeting_id, "task_id": a.task_id}


def audit_entry(a: AuditLog) -> dict[str, Any]:
    return {"id": a.id, "ts": iso(a.ts), "actor": a.actor, "action": a.action, "target_type": a.target_type, "target_id": a.target_id,
            "task_id": a.task_id, "risk": a.risk, "detail": a.detail}


def kb_document(d: KBDocument, detail: bool = False) -> dict[str, Any]:
    out = {"id": d.id, "title": d.title, "filename": d.filename, "mime": d.mime, "source_url": d.source_url, "author": d.author,
           "organization": d.organization, "date": d.date, "page_count": d.page_count, "is_ocr": d.is_ocr,
           "injection_flags": d.injection_flags, "project_id": d.project_id, "created_at": iso(d.created_at),
           "tables": len(d.tables), "sections_count": len(d.sections or []), "references": len(d.citations or [])}
    if detail:
        out.update(sections=d.sections, citations=d.citations, meta=d.meta,
                   table_data=[{"page": t.page, "caption": t.caption, "rows": t.rows[:30]} for t in d.tables[:20]],
                   chunks=[{"ord": c.ord, "page": c.page, "section": c.section, "text": c.text[:1500]} for c in d.chunks[:200]])
    return out


def notification(n: Notification) -> dict[str, Any]:
    return {"id": n.id, "title": n.title, "body": n.body, "task_id": n.task_id, "link": n.link, "read": n.read, "created_at": iso(n.created_at)}
