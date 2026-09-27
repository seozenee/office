"""Knowledge base, sources, claims, citations, artifacts (download / export / versions)."""
from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_user
from app.core.audit import audit
from app.core.db import get_db
from app.core.files import UnsafePathError, project_root, safe_resolve, slugify
from app.core.models import Artifact, ArtifactVersion, Claim, KBDocument, Project, Source
from app.knowledge.parsers import SUPPORTED_EXTENSIONS, ParseError
from app.knowledge.store import hybrid_search, ingest_file

router = APIRouter(prefix="/api", tags=["knowledge"], dependencies=[Depends(current_user)])
MAX_UPLOAD = 60 * 1024 * 1024


@router.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...), project_id: int | None = Form(default=None), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(415, f"unsupported file type {ext}; supported: {sorted(SUPPORTED_EXTENSIONS)}")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    if data[:2] == b"MZ" or data[:4] == b"\x7fELF":
        raise HTTPException(415, "executable content rejected")
    project = db.get(Project, project_id) if project_id else None
    dest = project_root(project.slug if project else None) / "source_files" / f"{slugify(Path(file.filename).stem)}{ext}"
    n = 2
    while dest.exists():
        dest = dest.with_name(f"{slugify(Path(file.filename).stem)}_{n}{ext}")
        n += 1
    dest.write_bytes(data)
    try:
        doc = ingest_file(db, dest, project_id=project_id)
    except ParseError as e:
        raise HTTPException(422, f"could not parse document: {e}") from e
    audit(db, "CEO", "document_uploaded", target_type="kb_document", target_id=doc.id, detail={"file": file.filename, "flags": doc.injection_flags})
    return ser.kb_document(doc, detail=False) | {"warnings": doc.meta.get("warnings", [])}


@router.get("/documents")
def list_documents(project_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(KBDocument).order_by(desc(KBDocument.id))
    if project_id:
        stmt = stmt.where(KBDocument.project_id == project_id)
    return [ser.kb_document(d) for d in db.scalars(stmt.limit(500))]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(KBDocument, doc_id)
    if d is None:
        raise HTTPException(404, "document not found")
    return ser.kb_document(d, detail=True)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(KBDocument, doc_id)
    if d is None:
        raise HTTPException(404, "document not found")
    for s in db.scalars(select(Source).where(Source.kb_document_id == doc_id)):
        s.kb_document_id = None
    db.delete(d)
    db.commit()
    audit(db, "CEO", "document_deleted", target_type="kb_document", target_id=doc_id, risk="MEDIUM")
    return {"deleted": doc_id}


@router.get("/search")
def search(q: str, project_id: int | None = None, limit: int = 10, db: Session = Depends(get_db)):
    return [h.__dict__ for h in hybrid_search(db, q, project_id=project_id, limit=min(limit, 50))]


@router.get("/sources")
def list_sources(task_id: int | None = None, project_id: int | None = None, accessed: bool | None = None, db: Session = Depends(get_db)):
    stmt = select(Source).order_by(Source.tier, desc(Source.id))
    if task_id:
        stmt = stmt.where(Source.task_id == task_id)
    if project_id:
        stmt = stmt.where(Source.project_id == project_id)
    if accessed is not None:
        stmt = stmt.where(Source.accessed.is_(accessed))
    return [ser.source(s) for s in db.scalars(stmt.limit(1000))]


@router.get("/sources/{source_id}")
def get_source(source_id: int, db: Session = Depends(get_db)):
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "source not found")
    return ser.source(s) | {"claims": [ser.claim(c) for c in db.scalars(select(Claim).where(Claim.source_id == source_id))]}


@router.get("/claims")
def list_claims(task_id: int | None = None, status: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Claim).order_by(desc(Claim.id))
    if task_id:
        stmt = stmt.where(Claim.task_id == task_id)
    if status:
        stmt = stmt.where(Claim.verification_status == status)
    return [ser.claim(c) for c in db.scalars(stmt.limit(2000))]


@router.get("/citations/{task_id}")
def citations(task_id: int, db: Session = Depends(get_db)):
    """Citation cards for a task: number → Source / Title / Publisher / Date / URL / Page / Relevant passage."""
    claims = list(db.scalars(select(Claim).where(Claim.task_id == task_id, Claim.supporting_quote.is_not(None),
                                                Claim.verification_status.in_(["verified", "partially_verified", "contradicted"]))
                          .order_by(desc(Claim.confidence))))
    out, numbers = [], {}
    for c in claims:
        s = db.get(Source, c.source_id) if c.source_id else None
        if s is None:
            continue
        if s.id not in numbers:
            numbers[s.id] = len(numbers) + 1
            out.append({"number": numbers[s.id], "source_id": s.id, "title": s.title, "publisher": s.publisher, "date": s.publication_date,
                        "url": s.url, "type": s.source_type, "tier": s.tier, "accessed": s.access_date.isoformat() if s.access_date else None, "passages": []})
        out[numbers[s.id] - 1]["passages"].append({"claim_id": c.id, "page": c.page_number, "passage": c.supporting_quote,
                                                    "claim": c.text, "confidence": c.confidence,
                                                    "status": c.verification_status})
    return out


# --- artifacts -----------------------------------------------------------------------------
@router.get("/artifacts")
def list_artifacts(task_id: int | None = None, project_id: int | None = None, kind: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Artifact).order_by(desc(Artifact.id))
    if task_id:
        stmt = stmt.where(Artifact.task_id == task_id)
    if project_id:
        stmt = stmt.where(Artifact.project_id == project_id)
    if kind:
        stmt = stmt.where(Artifact.kind == kind)
    return [ser.artifact(a) for a in db.scalars(stmt.limit(500))]


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: int, db: Session = Depends(get_db)):
    a = db.get(Artifact, artifact_id)
    if a is None:
        raise HTTPException(404, "artifact not found")
    return ser.artifact(a)


def _version(db: Session, artifact_id: int, version_id: int | None) -> ArtifactVersion:
    a = db.get(Artifact, artifact_id)
    if a is None or not a.versions:
        raise HTTPException(404, "artifact not found")
    v = next((x for x in a.versions if x.id == version_id), None) if version_id else a.versions[-1]
    if v is None:
        raise HTTPException(404, "version not found")
    return v


@router.get("/artifacts/{artifact_id}/download")
def download(artifact_id: int, version_id: int | None = None, db: Session = Depends(get_db)):
    v = _version(db, artifact_id, version_id)
    try:
        path = safe_resolve(v.file_path)
    except UnsafePathError as e:
        raise HTTPException(403, str(e)) from e
    if not path.exists():
        raise HTTPException(410, "file missing on disk")
    return FileResponse(path, filename=path.name)


@router.get("/artifacts/{artifact_id}/export")
def export(artifact_id: int, format: str, version_id: int | None = None, db: Session = Depends(get_db)):
    """Convert an artifact version to CSV (xlsx), MD/TXT (docx/pptx/xlsx text) or PDF (text rendering)."""
    from app.generators.export import rows_to_csv
    from app.knowledge.parsers import parse_bytes

    v = _version(db, artifact_id, version_id)
    src = safe_resolve(v.file_path)
    fmt = format.lower()
    out = src.with_suffix(f".{fmt}")
    if fmt == v.format:
        return FileResponse(src, filename=src.name)
    parsed = parse_bytes(src.read_bytes(), src.name)
    if fmt == "csv":
        if not parsed.tables:
            raise HTTPException(422, "no tabular data to export")
        rows_to_csv(parsed.tables[0]["rows"][0], parsed.tables[0]["rows"][1:], out)
    elif fmt in ("md", "txt"):
        body = "\n\n".join((f"## {p.section}\n" if fmt == "md" and p.section else "") + p.text for p in parsed.pages)
        out.write_text(f"# {parsed.title}\n\n{body}" if fmt == "md" else body, encoding="utf-8")
    elif fmt == "pdf":
        from app.generators.content import Block, ReportContent, Section, Statement
        from app.generators.export import to_pdf

        content = ReportContent(title=parsed.title, sections=[Section(p.section or f"Page {p.number}", [Block("paragraph", [Statement(t) for t in p.text.split("\n") if t.strip()])]) for p in parsed.pages])
        to_pdf(content, out)
    else:
        raise HTTPException(400, "format must be one of csv, md, txt, pdf, or the native format")
    return FileResponse(out, filename=out.name)


@router.get("/files/tree")
def file_tree(project_id: int | None = None, db: Session = Depends(get_db)):
    project = db.get(Project, project_id) if project_id else None
    root = project_root(project.slug if project else None)
    out: dict[str, list[dict]] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        out[folder.name] = [{"name": f.name, "size": f.stat().st_size} for f in sorted(folder.iterdir()) if f.is_file()]
    return {"root": str(root), "folders": out}


__all__ = ["router", "io"]


@router.get("/files/raw")
def raw_file(path: str):
    """Serve a workspace file (e.g. browser screenshots). Access is confined to the workspace."""
    try:
        p = safe_resolve(path)
    except UnsafePathError as e:
        raise HTTPException(403, str(e)) from e
    if not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p, filename=p.name)
