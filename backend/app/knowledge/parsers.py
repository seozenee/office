"""Document Intelligence: turn PDF/DOCX/PPTX/XLSX/HTML/TXT/MD/images into structured documents.

Structure is preserved where possible: pages, headings (sections), tables, footnotes,
references (bibliography), image counts and metadata. Scanned PDFs are OCR'd when a
Tesseract installation is available; otherwise the page is reported as unreadable (never faked).
"""
from __future__ import annotations

import io
import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".markdown", ".html", ".htm",
                        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".csv"}


@dataclass
class ParsedPage:
    number: int
    text: str
    section: str | None = None


@dataclass
class ParsedDocument:
    title: str
    mime: str
    pages: list[ParsedPage] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)  # {"heading", "level", "page"}
    tables: list[dict[str, Any]] = field(default_factory=list)  # {"page", "rows", "caption"}
    footnotes: list[dict[str, Any]] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    images: int = 0
    author: str | None = None
    organization: str | None = None
    date: str | None = None
    is_ocr: bool = False
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


class ParseError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_DATE_PATTERNS = [
    re.compile(r"\b(20\d{2}|19\d{2})[-./](0?[1-9]|1[0-2])[-./](0?[1-9]|[12]\d|3[01])\b"),
    re.compile(r"\b(20\d{2}|19\d{2})년\s*(0?[1-9]|1[0-2])월(?:\s*(0?[1-9]|[12]\d|3[01])일)?"),
    re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2}|19\d{2})\b"),
]
_MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                        "September", "October", "November", "December"], 1)}


def find_date(text: str) -> str | None:
    """Return the first explicit calendar date in the text as ISO (YYYY-MM[-DD])."""
    for i, pat in enumerate(_DATE_PATTERNS):
        m = pat.search(text)
        if not m:
            continue
        if i == 2:
            return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
        y, mo = m.group(1), int(m.group(2))
        d = m.group(3)
        return f"{y}-{mo:02d}-{int(d):02d}" if d else f"{y}-{mo:02d}"
    return None


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?", value)  # PDF date
    if m:
        return "-".join(x for x in m.groups() if x)
    return find_date(value) or (value[:10] if re.match(r"\d{4}-\d{2}-\d{2}", value) else None)


_REF_HEADINGS = re.compile(r"^\s*(references|bibliography|works cited|참고\s*문헌|참고\s*자료|출처)\s*$", re.I | re.M)


def extract_references(text: str) -> list[str]:
    m = None
    for m in _REF_HEADINGS.finditer(text):
        pass  # keep the last occurrence
    if not m:
        return []
    tail = text[m.end():]
    refs: list[str] = []
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        if refs and not re.match(r"^(\[\d+\]|\d+[.)]|[-•*])\s*", line) and len(refs[-1]) < 400 and not re.match(r"^[A-Z가-힣][^.]{0,60},", line):
            refs[-1] += " " + line
        else:
            refs.append(re.sub(r"^(\[\d+\]|\d+[.)]|[-•*])\s*", "", line))
        if len(refs) >= 200:
            break
    return [r for r in refs if len(r) > 8]


def _rows_clean(rows: list[list[Any]]) -> list[list[str]]:
    out = []
    for r in rows:
        cells = ["" if c is None else str(c).strip() for c in r]
        if any(cells):
            out.append(cells)
    return out


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def parse_pdf(data: bytes, filename: str = "document.pdf") -> ParsedDocument:
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001 - pymupdf raises various types
        raise ParseError(f"cannot open PDF: {e}") from e
    if doc.needs_pass:
        raise ParseError("PDF is password-protected")
    md = doc.metadata or {}
    pd = ParsedDocument(title=(md.get("title") or Path(filename).stem).strip(), mime="application/pdf",
                        author=md.get("author") or None, date=normalize_date(md.get("creationDate")))
    for level, heading, page in doc.get_toc(simple=True):
        pd.sections.append({"heading": heading, "level": level, "page": page})

    ocr_failed = 0
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        imgs = page.get_images(full=True)
        pd.images += len(imgs)
        if len(text.strip()) < 20 and imgs:
            try:
                tp = page.get_textpage_ocr(full=True, language="eng+kor")
                text = page.get_text("text", textpage=tp)
                pd.is_ocr = True
            except Exception as e:  # noqa: BLE001
                ocr_failed += 1
                log.info("OCR unavailable for page %s: %s", i, e)
        # footnotes: small-font lines in the bottom 15% of the page
        try:
            spans = [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"] if s["text"].strip()]
            if spans:
                body = statistics.median(s["size"] for s in spans)
                h = page.rect.height
                for s in spans:
                    if s["size"] < body * 0.85 and s["bbox"][1] > h * 0.85 and re.match(r"^\s*(\d+|\*|†)", s["text"]):
                        pd.footnotes.append({"page": i, "text": s["text"].strip()})
        except Exception:  # noqa: BLE001 - footnote detection is best effort
            pass
        try:
            for t in page.find_tables().tables:
                rows = _rows_clean(t.extract())
                if len(rows) >= 2:
                    pd.tables.append({"page": i, "rows": rows, "caption": None})
        except Exception:  # noqa: BLE001
            pass
        section = None
        for s in pd.sections:
            if s["page"] <= i:
                section = s["heading"]
        pd.pages.append(ParsedPage(i, text.replace("\xa0", " ").strip(), section))
    if ocr_failed:
        pd.warnings.append(f"{ocr_failed} scanned page(s) could not be OCR'd (install Tesseract to enable OCR)")
    if not pd.sections:  # infer headings from large fonts on first lines
        for p in pd.pages:
            first = p.text.splitlines()[0].strip() if p.text else ""
            if 3 < len(first) < 90 and not first.endswith("."):
                pd.sections.append({"heading": first, "level": 1, "page": p.number})
    pd.references = extract_references(pd.text)
    pd.date = pd.date or find_date(pd.pages[0].text if pd.pages else "")
    pd.meta = {k: v for k, v in md.items() if v}
    return pd


# ---------------------------------------------------------------------------
# Office formats
# ---------------------------------------------------------------------------
def parse_docx(data: bytes, filename: str = "document.docx") -> ParsedDocument:
    import docx

    d = docx.Document(io.BytesIO(data))
    cp = d.core_properties
    pd = ParsedDocument(title=cp.title or Path(filename).stem, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        author=cp.author or None, date=cp.created.date().isoformat() if cp.created else None)
    buf: list[str] = []
    section = None
    for p in d.paragraphs:
        style = (p.style.name or "").lower() if p.style is not None else ""
        if style.startswith("heading") or style == "title":
            level = int(re.sub(r"\D", "", style) or 1)
            section = p.text.strip()
            if section:
                pd.sections.append({"heading": section, "level": level, "page": None})
        if p.text.strip():
            buf.append(p.text)
    for t in d.tables:
        rows = _rows_clean([[c.text for c in r.cells] for r in t.rows])
        if rows:
            pd.tables.append({"page": None, "rows": rows, "caption": None})
    pd.images = sum(1 for r in d.part.rels.values() if "image" in r.reltype)
    pd.pages = [ParsedPage(1, "\n".join(buf), None)]
    pd.references = extract_references(pd.text)
    return pd


def parse_pptx(data: bytes, filename: str = "deck.pptx") -> ParsedDocument:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    pd = ParsedDocument(title=prs.core_properties.title or Path(filename).stem,
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        author=prs.core_properties.author or None)
    for i, slide in enumerate(prs.slides, start=1):
        texts: list[str] = []
        title = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else None
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t:
                    texts.append(t)
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = _rows_clean([[c.text for c in r.cells] for r in shape.table.rows])
                pd.tables.append({"page": i, "rows": rows, "caption": title})
            if shape.shape_type == 13:  # picture
                pd.images += 1
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                texts.append(f"[Speaker notes] {notes}")
        if title:
            pd.sections.append({"heading": title, "level": 1, "page": i})
        pd.pages.append(ParsedPage(i, "\n".join(texts), title))
    return pd


def parse_xlsx(data: bytes, filename: str = "book.xlsx") -> ParsedDocument:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    pd = ParsedDocument(title=Path(filename).stem, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    for i, ws in enumerate(wb.worksheets, start=1):
        rows = _rows_clean([list(r) for r in ws.iter_rows(values_only=True)][:5000])
        pd.sections.append({"heading": ws.title, "level": 1, "page": i})
        pd.tables.append({"page": i, "rows": rows, "caption": ws.title})
        text = "\n".join(" | ".join(r) for r in rows[:500])
        pd.pages.append(ParsedPage(i, f"Sheet: {ws.title}\n{text}", ws.title))
    return pd


def parse_csv(data: bytes, filename: str = "data.csv") -> ParsedDocument:
    import csv

    text = data.decode("utf-8-sig", errors="replace")
    rows = _rows_clean(list(csv.reader(io.StringIO(text))))
    pd = ParsedDocument(title=Path(filename).stem, mime="text/csv")
    pd.tables.append({"page": 1, "rows": rows[:5000], "caption": filename})
    pd.pages = [ParsedPage(1, "\n".join(" | ".join(r) for r in rows[:500]))]
    return pd


# ---------------------------------------------------------------------------
# Text, Markdown, HTML, images
# ---------------------------------------------------------------------------
def parse_text(data: bytes, filename: str = "note.txt", markdown: bool = False) -> ParsedDocument:
    text = data.decode("utf-8-sig", errors="replace")
    pd = ParsedDocument(title=Path(filename).stem, mime="text/markdown" if markdown else "text/plain")
    if markdown:
        for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.M):
            pd.sections.append({"heading": m.group(2).strip(), "level": len(m.group(1)), "page": 1})
        if pd.sections:
            pd.title = pd.sections[0]["heading"]
        for block in re.findall(r"((?:^\|.*\|\s*$\n?){2,})", text, re.M):
            rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in block.strip().splitlines()
                    if not re.match(r"^\|?\s*:?-{2,}", line.strip())]
            pd.tables.append({"page": 1, "rows": rows, "caption": None})
    pd.pages = [ParsedPage(1, text)]
    pd.date = find_date(text[:2000])
    pd.references = extract_references(text)
    return pd


def parse_html(data: bytes | str, url: str | None = None) -> ParsedDocument:
    from bs4 import BeautifulSoup

    html = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    soup = BeautifulSoup(html, "lxml")

    def meta(*names: str) -> str | None:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) or soup.find("meta", attrs={"itemprop": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    title = meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else None) or (url or "Web page")
    date = normalize_date(meta("article:published_time", "datePublished", "pubdate", "date", "DC.date", "dcterms.date"))
    if not date:
        t = soup.find("time")
        if t is not None:
            date = normalize_date(t.get("datetime") or t.get_text())
    author = meta("author", "article:author", "dc.creator")
    org = meta("og:site_name", "publisher", "citation_publisher")

    for bad in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe", "svg"]):
        bad.decompose()
    pd = ParsedDocument(title=title, mime="text/html", author=author, organization=org, date=date)
    for t in soup.find_all("table"):
        rows = _rows_clean([[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in t.find_all("tr")])
        if len(rows) >= 2:
            cap = t.find("caption")
            pd.tables.append({"page": 1, "rows": rows, "caption": cap.get_text(strip=True) if cap else None})
    main = soup.find("article") or soup.find("main") or soup.body or soup
    lines: list[str] = []
    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "td", "figcaption", "pre"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            pd.sections.append({"heading": txt, "level": int(el.name[1]), "page": 1})
            lines.append(f"\n{txt}\n")
        elif el.name != "td":
            lines.append(txt)
    pd.images = len(main.find_all("img"))
    text = "\n".join(lines).strip() or main.get_text("\n", strip=True)
    pd.pages = [ParsedPage(1, text)]
    pd.date = pd.date or find_date(text[:3000])
    pd.references = extract_references(text)
    pd.meta = {"url": url} if url else {}
    return pd


def parse_image(data: bytes, filename: str = "image.png") -> ParsedDocument:
    pd = ParsedDocument(title=Path(filename).stem, mime="image/*", images=1)
    try:
        import pymupdf

        img_doc = pymupdf.open(stream=data, filetype=Path(filename).suffix.lstrip(".") or "png")
        pdf_bytes = img_doc.convert_to_pdf()
        page = pymupdf.open("pdf", pdf_bytes)[0]
        tp = page.get_textpage_ocr(full=True, language="eng+kor")
        pd.pages = [ParsedPage(1, page.get_text("text", textpage=tp).strip())]
        pd.is_ocr = True
    except Exception as e:  # noqa: BLE001
        pd.pages = [ParsedPage(1, "")]
        pd.warnings.append(f"OCR unavailable: {e}")
    return pd


def parse_bytes(data: bytes, filename: str, url: str | None = None, content_type: str | None = None) -> ParsedDocument:
    ext = Path(filename).suffix.lower()
    ct = (content_type or "").lower()
    if ext == ".pdf" or "application/pdf" in ct or data[:5] == b"%PDF-":
        return parse_pdf(data, filename)
    if ext == ".docx":
        return parse_docx(data, filename)
    if ext == ".pptx":
        return parse_pptx(data, filename)
    if ext == ".xlsx":
        return parse_xlsx(data, filename)
    if ext == ".csv":
        return parse_csv(data, filename)
    if ext in (".md", ".markdown"):
        return parse_text(data, filename, markdown=True)
    if ext in (".html", ".htm") or "html" in ct:
        return parse_html(data, url)
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff") or ct.startswith("image/"):
        return parse_image(data, filename)
    if ext == ".txt" or ct.startswith("text/") or not ext:
        return parse_text(data, filename)
    raise ParseError(f"unsupported file type: {ext or ct}")
