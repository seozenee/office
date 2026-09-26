"""Export ReportContent to Markdown / TXT / HTML / PDF, and tables to CSV."""
from __future__ import annotations

import csv
import html
from pathlib import Path

from app.generators.content import LABEL_KO, ReportContent, Statement, cite_marks

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _stmt_md(s: Statement) -> str:
    label = f"**[{LABEL_KO.get(s.label, s.label)}]** " if s.label else ""
    return f"{label}{s.text}{' ' + cite_marks(s.citations) if s.citations else ''}"


def to_markdown(c: ReportContent) -> str:
    out = [f"# {c.title}", ""]
    if c.subtitle:
        out += [f"_{c.subtitle}_", ""]
    out += [f"{c.organization or c.author} · {c.date}", ""]
    if c.summary:
        out += ["## 요약", ""] + [f"- {_stmt_md(s)}" for s in c.summary] + [""]
    for sec in c.sections:
        out += [f"{'#' * min(sec.level + 1, 4)} {sec.heading}", ""]
        for b in sec.blocks:
            if b.type in ("paragraph", "callout"):
                out += [_stmt_md(s) + "\n" for s in b.statements]
            elif b.type == "bullets":
                out += [f"- {_stmt_md(s)}" for s in b.statements] + [""]
            elif b.type == "table" and b.rows:
                hdr = b.header or [""] * len(b.rows[0])
                out += ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
                out += ["| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |" for r in b.rows]
                out += [f"_{b.caption}_" if b.caption else "", ""]
            elif b.type == "chart" and b.chart:
                cats = b.chart.get("categories", [])
                out += [f"_차트: {b.chart.get('title', '')}_", "", "| 항목 | " + " | ".join(s["name"] for s in b.chart.get("series", [])) + " |",
                        "|---|" + "---|" * len(b.chart.get("series", []))]
                for i, cat in enumerate(cats):
                    out.append(f"| {cat} | " + " | ".join(f"{s['values'][i]:,.0f}" for s in b.chart["series"]) + " |")
                out.append("")
    out += ["## 참고문헌", ""]
    for e in c.bibliography:
        out.append(f"{e.number}. <a id=\"ref-{e.number}\"></a>{e.title}. {e.publisher or ''} ({e.date or '발행일 미상'}). "
                   f"{e.url or ''} (접근일 {e.accessed or '-'})")
    return "\n".join(out).strip() + "\n"


def to_text(c: ReportContent) -> str:
    import re

    md = to_markdown(c)
    md = re.sub(r"<a id=\"[^\"]+\"></a>", "", md)
    return re.sub(r"[*_#`]", "", md)


def to_html(c: ReportContent) -> str:
    def stmt(s: Statement) -> str:
        label = f'<b class="lbl">[{LABEL_KO.get(s.label, s.label)}]</b> ' if s.label else ""
        cites = "".join(f'<sup><a href="#ref-{n}">[{n}]</a></sup>' for n in sorted(set(s.citations)))
        return f"{label}{html.escape(s.text)}{cites}"

    parts = [f"<h1>{html.escape(c.title)}</h1>"]
    if c.subtitle:
        parts.append(f"<p><i>{html.escape(c.subtitle)}</i></p>")
    parts.append(f"<p>{html.escape(c.organization or c.author)} · {c.date}</p>")
    if c.summary:
        parts.append("<h2>요약</h2><ul>" + "".join(f"<li>{stmt(s)}</li>" for s in c.summary) + "</ul>")
    for sec in c.sections:
        h = min(sec.level + 1, 4)
        parts.append(f"<h{h}>{html.escape(sec.heading)}</h{h}>")
        for b in sec.blocks:
            if b.type in ("paragraph", "callout"):
                parts += [f"<p>{stmt(s)}</p>" for s in b.statements]
            elif b.type == "bullets":
                parts.append("<ul>" + "".join(f"<li>{stmt(s)}</li>" for s in b.statements) + "</ul>")
            elif b.type == "table" and b.rows:
                head = "".join(f"<th>{html.escape(x)}</th>" for x in b.header)
                body = "".join("<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in r) + "</tr>" for r in b.rows)
                parts.append(f"<table><tr>{head}</tr>{body}</table>")
    parts.append("<h2>참고문헌</h2>")
    for e in c.bibliography:
        parts.append(f'<p id="ref-{e.number}">[{e.number}] {html.escape(e.title)}. {html.escape(e.publisher or "")} '
                     f'({e.date or "발행일 미상"}). {html.escape(e.url or "")}</p>')
    return "\n".join(parts)


def to_pdf(c: ReportContent, path: Path) -> Path:
    import pymupdf

    font = next((f for f in _FONT_CANDIDATES if Path(f).exists()), None)
    css = "body{font-size:10pt;line-height:1.5} h1{font-size:20pt} h2{font-size:14pt} table{border-collapse:collapse} td,th{border:1px solid #999;padding:2px;font-size:8pt} .lbl{color:#2B5DAA}"
    archive = None
    if font:
        archive = pymupdf.Archive(str(Path(font).parent))
        css = f"@font-face {{font-family: kfont; src: url({Path(font).name});}} * {{font-family: kfont;}} " + css
    story = pymupdf.Story(html=to_html(c), user_css=css, archive=archive)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = pymupdf.DocumentWriter(str(path))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (50, 50, -50, -50)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    try:  # embed only the glyphs used (CJK fonts are large)
        doc = pymupdf.open(str(path))
        doc.subset_fonts()
        tmp = path.with_suffix(".tmp.pdf")
        doc.save(str(tmp), garbage=3, deflate=True)
        doc.close()
        tmp.replace(path)
    except Exception:  # noqa: BLE001 - subsetting is an optimisation only
        pass
    return path


def rows_to_csv(header: list[str], rows: list[list[object]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path
