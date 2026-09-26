"""Artifact system: every output file is an Artifact with immutable versions (v1, v2, …, final)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.files import artifact_path, checksum, promote_to_final
from app.core.models import Artifact, ArtifactVersion, Project

KIND_BY_FORMAT = {"docx": "document", "pptx": "presentation", "xlsx": "spreadsheet", "pdf": "report", "md": "document",
                  "txt": "document", "csv": "dataset", "json": "research", "py": "code"}


def save_artifact(db: Session, *, title: str, fmt: str, build: Callable[[Path], Path], author_agent: str,
                  project: Project | None, task_id: int | None, change_note: str = "", source_ids: list[int] | None = None,
                  kind: str | None = None, artifact: Artifact | None = None) -> tuple[Artifact, ArtifactVersion]:
    """Create a new artifact or add a new version. Existing files are never overwritten."""
    if artifact is None and task_id:
        candidates = db.scalars(select(Artifact).where(Artifact.task_id == task_id, Artifact.title == title,
                                                       Artifact.kind == (kind or KIND_BY_FORMAT.get(fmt, "document"))))
        artifact = next((a for a in candidates if a.versions and a.versions[0].format == fmt), None)
    version = (artifact.current_version + 1) if artifact else 1
    path = artifact_path(project.slug if project else None, title, version, fmt)
    build(path)
    if artifact is None:
        artifact = Artifact(project_id=project.id if project else None, task_id=task_id, kind=kind or KIND_BY_FORMAT.get(fmt, "document"),
                            title=title, author_agent=author_agent, current_version=version, source_ids=source_ids or [],
                            status="draft")
        db.add(artifact)
        db.flush()
    else:
        artifact.current_version = version
        artifact.source_ids = sorted(set((artifact.source_ids or []) + (source_ids or [])))
    ver = ArtifactVersion(artifact_id=artifact.id, version=version, label=f"v{version}", file_path=str(path), format=fmt,
                          change_note=change_note or ("최초 생성" if version == 1 else "개정"), checksum=checksum(path),
                          size_bytes=path.stat().st_size)
    db.add(ver)
    audit(db, author_agent, "artifact_generated", target_type="artifact", target_id=artifact.id, task_id=task_id,
          detail={"title": title, "format": fmt, "version": version, "path": str(path)}, commit=False)
    db.commit()
    return artifact, ver


def finalize_artifact(db: Session, artifact: Artifact, project: Project | None) -> ArtifactVersion:
    latest = artifact.versions[-1]
    final_path = promote_to_final(Path(latest.file_path), project.slug if project else None)
    ver = ArtifactVersion(artifact_id=artifact.id, version=latest.version, label="final", file_path=str(final_path),
                          format=latest.format, change_note=f"{latest.label} 을(를) 최종본으로 승인", checksum=checksum(final_path),
                          size_bytes=final_path.stat().st_size)
    artifact.status = "final"
    db.add(ver)
    audit(db, "CEO", "artifact_finalized", target_type="artifact", target_id=artifact.id, task_id=artifact.task_id,
          detail={"from": latest.label}, commit=False)
    db.commit()
    return ver
