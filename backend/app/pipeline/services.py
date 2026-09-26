"""Application services used by the API and by employees (DM work orders)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.models import Approval, Artifact, Memory, Project, Task, TaskStatus
from app.jobs.queue import enqueue
from app.office import service as office
from app.pipeline.artifacts import finalize_artifact
from app.tools.registry import ApprovalRequired, registry


def create_task(db: Session, request: str, project_id: int | None = None, *, priority: int = 3,
                deadline: datetime | None = None, title: str | None = None, extra_deliverables: list[str] | None = None,
                actor: str = "CEO") -> Task:
    request = request.strip()
    if not request:
        raise ValueError("request is empty")
    if project_id is not None and db.get(Project, project_id) is None:
        raise LookupError(f"project {project_id} not found")
    t = Task(project_id=project_id, title=(title or request)[:300], request=request, description=request, priority=priority,
             deadline=deadline, status=TaskStatus.BACKLOG.value, owner=actor,
             plan={"force_deliverables": extra_deliverables} if extra_deliverables else {})
    db.add(t)
    db.commit()
    audit(db, actor, "task_created", target_type="task", target_id=t.id, task_id=t.id, detail={"request": request[:500]})
    office.post(db, None, f"📨 CEO 지시 #{t.id}: {request[:300]}", channel="all", kind="system", task_id=t.id)
    enqueue(db, "research_task", {"task_id": t.id}, task_id=t.id)
    return t


def remember(db: Session, layer: str, key: str, value: str, *, project_id: int | None = None, origin: str = "explicit",
             ttl_hours: int | None = None) -> Memory:
    existing = db.scalar(select(Memory).where(Memory.layer == layer, Memory.key == key, Memory.project_id == project_id))
    if existing:
        existing.value = value
        existing.origin = origin
        db.commit()
        return existing
    m = Memory(layer=layer, key=key, value=value, project_id=project_id, origin=origin,
               expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours) if ttl_hours else None)
    db.add(m)
    db.commit()
    return m


def decide_approval(db: Session, approval_id: int, approve: bool, note: str = "") -> dict[str, Any]:
    appr = db.get(Approval, approval_id)
    if appr is None:
        raise LookupError("approval not found")
    if appr.status != "pending":
        raise ValueError(f"approval already {appr.status}")
    if not office.next_approver_is_user(appr):
        raise PermissionError("이 결재는 아직 CEO 차례가 아닙니다")
    office.stamp(db, appr, None, approve, note)
    result: dict[str, Any] = {"approval_id": appr.id, "status": appr.status}
    task = db.get(Task, appr.task_id) if appr.task_id else None

    if appr.action == "final_delivery" and task:
        if appr.status == "approved":
            finals = []
            project = db.get(Project, task.project_id) if task.project_id else None
            for aid in appr.payload.get("artifact_ids", []):
                art = db.get(Artifact, aid)
                if art:
                    finals.append(finalize_artifact(db, art, project).file_path)
            task.status = TaskStatus.DONE.value
            task.current_step = "완료 (CEO 승인)"
            result["final_files"] = finals
            remember(db, "task", f"task:{task.id}", f"{task.title} — 완료, 산출물 {len(finals)}개", origin="auto", project_id=task.project_id)
            remember(db, "decision", f"approval:{appr.id}", f"CEO 승인: {appr.title} {note}".strip(), origin="auto", project_id=task.project_id)
            office.post(db, office.employee(db, "orchestrator"), f"🎉 CEO 최종 승인 — 작업 #{task.id} 최종본을 final 폴더에 보관했습니다.", channel="all", task_id=task.id)
        else:
            task.status = TaskStatus.REVIEWING.value
            task.current_step = "CEO 반려 — 피드백 대기"
            remember(db, "decision", f"approval:{appr.id}", f"CEO 반려: {appr.title} — {note}", origin="auto", project_id=task.project_id)
            office.post(db, office.employee(db, "orchestrator"), f"↩️ CEO 반려 — “{note or '사유 없음'}”. 피드백을 반영해 개정하겠습니다.", channel="all", task_id=task.id)
            if note:
                enqueue(db, "revise_task", {"task_id": task.id, "feedback": note}, task_id=task.id)
                result["revision_enqueued"] = True
        db.commit()
    elif appr.status == "approved" and appr.action in {s.name for s in registry.list()}:
        kwargs = appr.payload.get("kwargs_raw") or appr.payload.get("kwargs", {})
        try:
            result["tool_result"] = registry.execute(db, appr.action, actor="CEO-approved", task_id=appr.task_id, approval_id=appr.id, **kwargs)
        except ApprovalRequired:
            raise
        except Exception as e:  # noqa: BLE001
            result["tool_error"] = str(e)
    return result
