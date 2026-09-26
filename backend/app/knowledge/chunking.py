"""Split parsed documents into page/section-aware chunks with sentence boundaries."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.knowledge.parsers import ParsedDocument

_SENT_END = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s*")
_CONTINUES = re.compile(r"([은는이가을를의에로과와및,]|에서|으로|하고|그리고|and|of|the|to|in)\s*$", re.I)
_PARTICLES = re.compile(r"[가-힣](은|는|이|가|을|를|에서|으로|에게|와|과)\s")
_TERMINAL = re.compile(r"([.!?。:;)\]]|다|음|함|됨)\s*$")


def _logical_lines(text: str) -> list[str]:
    """Re-join hard-wrapped lines (PDF) into paragraphs, keeping short title-like lines separate."""
    out: list[str] = []
    buf = ""
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if buf:
                out.append(buf)
                buf = ""
            continue
        is_heading = not buf and len(line) < 30 and not _TERMINAL.search(line) and not _CONTINUES.search(line) and not _PARTICLES.search(line)
        if is_heading:
            out.append(line)
            continue
        buf = f"{buf} {line}".strip() if buf else line
        if _TERMINAL.search(line):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in _logical_lines(text):
        out.extend(s.strip() for s in _SENT_END.split(para) if s and s.strip())
    return out


@dataclass
class Chunk:
    ord: int
    page: int | None
    section: str | None
    text: str


def chunk_document(doc: ParsedDocument, max_chars: int = 1200, overlap_sentences: int = 1) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in doc.pages:
        sents = split_sentences(page.text)
        buf: list[str] = []
        for s in sents:
            if buf and sum(len(x) for x in buf) + len(s) > max_chars:
                chunks.append(Chunk(len(chunks), page.number, page.section, "\n".join(buf)))
                buf = buf[-overlap_sentences:] if overlap_sentences else []
            buf.append(s)
        if buf:
            chunks.append(Chunk(len(chunks), page.number, page.section, "\n".join(buf)))
    for t in doc.tables:
        text = "\n".join(" | ".join(r) for r in t["rows"][:60])
        if text.strip():
            chunks.append(Chunk(len(chunks), t.get("page"), f"Table: {t.get('caption') or ''}".strip(), text[:max_chars * 2]))
    return chunks
