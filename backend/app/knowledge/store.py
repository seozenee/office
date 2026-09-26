"""Knowledge Base: ingest documents and search them with hybrid (BM25 + vector, RRF) retrieval."""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import KBChunk, KBDocument, KBTable
from app.core.security import scan_injection
from app.knowledge.chunking import chunk_document
from app.knowledge.embeddings import get_embedder, tokenize
from app.knowledge.parsers import ParsedDocument


def ingest_parsed(db: Session, doc: ParsedDocument, *, project_id: int | None, source_url: str | None = None,
                  file_path: str | None = None, filename: str | None = None) -> KBDocument:
    content_hash = hashlib.sha256(doc.text.encode()).hexdigest()
    existing = db.scalar(select(KBDocument).where(KBDocument.content_hash == content_hash,
                                                  KBDocument.project_id == project_id))
    if existing:
        return existing
    scan = scan_injection(doc.text)
    kb = KBDocument(project_id=project_id, title=doc.title[:500], filename=filename, mime=doc.mime,
                    source_url=source_url, author=doc.author, organization=doc.organization, date=doc.date,
                    meta={**doc.meta, "warnings": doc.warnings, "images": doc.images, "footnotes": doc.footnotes[:100]},
                    sections=doc.sections[:500], citations=doc.references[:300], file_path=file_path,
                    page_count=len(doc.pages), is_ocr=doc.is_ocr, injection_flags=scan.categories,
                    content_hash=content_hash)
    db.add(kb)
    db.flush()
    chunks = chunk_document(doc)
    if chunks:
        vecs = get_embedder().embed([c.text for c in chunks])
        for c, v in zip(chunks, vecs):
            db.add(KBChunk(document_id=kb.id, ord=c.ord, page=c.page, section=c.section, text=c.text,
                           embedding=v.astype(np.float32).tobytes()))
    for t in doc.tables[:200]:
        db.add(KBTable(document_id=kb.id, page=t.get("page"), caption=t.get("caption"), rows=t["rows"][:500]))
    db.commit()
    return kb


def ingest_file(db: Session, path: Path, *, project_id: int | None) -> KBDocument:
    from app.knowledge.parsers import parse_bytes

    parsed = parse_bytes(path.read_bytes(), path.name)
    return ingest_parsed(db, parsed, project_id=project_id, file_path=str(path), filename=path.name)


@dataclass
class SearchHit:
    chunk_id: int
    document_id: int
    document_title: str
    page: int | None
    section: str | None
    text: str
    score: float
    bm25_rank: int | None
    vector_rank: int | None


def _bm25_scores(query_tokens: list[str], docs_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    n = len(docs_tokens)
    avgdl = sum(len(d) for d in docs_tokens) / max(n, 1)
    df: Counter[str] = Counter()
    for d in docs_tokens:
        df.update(set(d))
    scores = np.zeros(n)
    for i, d in enumerate(docs_tokens):
        tf = Counter(d)
        for q in set(query_tokens):
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            scores[i] += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(d) / max(avgdl, 1)))
    return scores


def hybrid_search(db: Session, query: str, *, project_id: int | None = None, document_ids: list[int] | None = None,
                  limit: int = 8, rrf_k: int = 60) -> list[SearchHit]:
    stmt = select(KBChunk, KBDocument.title).join(KBDocument)
    if project_id is not None:
        stmt = stmt.where(KBDocument.project_id == project_id)
    if document_ids:
        stmt = stmt.where(KBChunk.document_id.in_(document_ids))
    rows = db.execute(stmt).all()
    if not rows:
        return []
    chunks = [r[0] for r in rows]
    titles = [r[1] for r in rows]

    bm25 = _bm25_scores(tokenize(query), [tokenize(c.text) for c in chunks])
    qv = get_embedder().embed([query])[0]
    dim = qv.shape[0]
    mat = np.stack([np.frombuffer(c.embedding, dtype=np.float32) if c.embedding and len(c.embedding) == dim * 4
                    else np.zeros(dim, dtype=np.float32) for c in chunks])
    cos = mat @ qv

    bm_order = [i for i in np.argsort(-bm25) if bm25[i] > 0]
    vec_order = [i for i in np.argsort(-cos) if cos[i] > 0.05]
    bm_rank = {i: r for r, i in enumerate(bm_order)}
    vec_rank = {i: r for r, i in enumerate(vec_order)}
    fused: dict[int, float] = {}
    for i, r in bm_rank.items():
        fused[i] = fused.get(i, 0) + 1 / (rrf_k + r + 1)
    for i, r in vec_rank.items():
        fused[i] = fused.get(i, 0) + 1 / (rrf_k + r + 1)
    best = sorted(fused, key=lambda i: -fused[i])[:limit]
    return [SearchHit(chunks[i].id, chunks[i].document_id, titles[i], chunks[i].page, chunks[i].section,
                      chunks[i].text, round(fused[i], 5), bm_rank.get(i), vec_rank.get(i)) for i in best]


def document_text(db: Session, document_id: int) -> list[KBChunk]:
    return list(db.scalars(select(KBChunk).where(KBChunk.document_id == document_id).order_by(KBChunk.ord)))
