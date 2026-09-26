"""Format-independent content model shared by the DOCX / PPTX / XLSX / MD builders.

Every statement carries a label (FACT, ANALYSIS, ASSUMPTION, ESTIMATE, OPINION, UNKNOWN)
and a list of citation numbers, so the renderers can show where each sentence comes from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

Label = Literal["FACT", "ANALYSIS", "ASSUMPTION", "ESTIMATE", "OPINION", "UNKNOWN", ""]

LABEL_KO = {"FACT": "사실", "ANALYSIS": "분석", "ASSUMPTION": "가정", "ESTIMATE": "추정",
            "OPINION": "의견", "UNKNOWN": "미확인"}
LABEL_COLORS = {"FACT": "1F7A4D", "ANALYSIS": "2B5DAA", "ASSUMPTION": "B7791F", "ESTIMATE": "8A4FBF",
                "OPINION": "666666", "UNKNOWN": "C0392B"}


@dataclass
class Statement:
    text: str
    label: Label = ""
    citations: list[int] = field(default_factory=list)
    footnote: str | None = None  # e.g. supporting passage shown as a Word footnote


@dataclass
class Block:
    type: Literal["paragraph", "bullets", "table", "chart", "image", "callout"]
    statements: list[Statement] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    caption: str | None = None
    chart: dict[str, Any] | None = None  # {"kind": "bar"|"line"|"pie", "categories": [...], "series": [{"name", "values"}], "number_format"}
    image_path: str | None = None


@dataclass
class Section:
    heading: str
    blocks: list[Block] = field(default_factory=list)
    level: int = 1
    notes: str = ""  # speaker notes for slides


@dataclass
class BibEntry:
    number: int
    source_id: int | None
    title: str
    publisher: str | None
    date: str | None
    url: str | None
    accessed: str | None
    tier_label: str | None = None
    page: int | None = None


@dataclass
class ReportContent:
    title: str
    subtitle: str = ""
    author: str = "Personal AI Office"
    organization: str = ""
    date: str = field(default_factory=lambda: date.today().isoformat())
    summary: list[Statement] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    bibliography: list[BibEntry] = field(default_factory=list)
    qc: dict[str, Any] = field(default_factory=dict)


class CitationRegistry:
    """Assigns stable [n] numbers to sources in order of first citation."""

    def __init__(self) -> None:
        self._numbers: dict[int, int] = {}
        self.entries: list[BibEntry] = []

    def cite(self, source: Any, page: int | None = None) -> int:
        sid = source.id
        if sid not in self._numbers:
            n = len(self.entries) + 1
            self._numbers[sid] = n
            self.entries.append(BibEntry(
                number=n, source_id=sid, title=source.title, publisher=getattr(source, "publisher", None),
                date=getattr(source, "publication_date", None), url=getattr(source, "url", None),
                accessed=source.access_date.date().isoformat() if getattr(source, "access_date", None) else None,
                tier_label=getattr(source, "source_type", None), page=page))
        return self._numbers[sid]

    def number_for(self, source_id: int) -> int | None:
        return self._numbers.get(source_id)


def cite_marks(nums: list[int]) -> str:
    return "".join(f"[{n}]" for n in sorted(set(nums)))


def statement_text(s: Statement, with_label: bool = True) -> str:
    label = f"[{s.label}] " if with_label and s.label else ""
    marks = f" {cite_marks(s.citations)}" if s.citations else ""
    return f"{label}{s.text}{marks}"
