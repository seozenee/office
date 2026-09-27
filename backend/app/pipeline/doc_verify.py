"""Document fact-check mode: “이 PPT(보고서)의 모든 숫자와 출처를 검증해줘”.

1. Take the target document (explicit id, or the latest upload in the project).
2. Extract every checkable statement (numbers, years, named claims) with its page/slide.
3. Collect independent evidence: other knowledge-base documents + web research (original documents only).
4. For each statement find the best evidence sentence and decide deterministically:
   verified (same figure found) · contradicted (same metric/year, different figure) ·
   partially_verified (similar statement, no figure to compare) · unverified (no evidence).
5. Produce a verification report (DOCX/MD) and a check sheet (XLSX), run QC, send to 결재.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select

from app.agents.research import DocumentAnalystAgent, WebResearcherAgent
from app.agents.verification import TIER_WEIGHT
from app.core.audit import audit
from app.core.config import get_settings
from app.core.models import Claim, KBChunk, KBDocument, Source, TaskStatus
from app.generators.content import Block, CitationRegistry, ReportContent, Section, Statement
from app.generators.docx_builder import build_docx
from app.generators.export import to_markdown
from app.generators.xlsx_builder import XlsxBuilder
from app.knowledge.chunking import split_sentences
from app.knowledge.store import hybrid_search
from app.office import service as office
from app.pipeline.artifacts import save_artifact
from app.pipeline.textutil import content_tokens, jaccard, quantities, significant_numbers, years_in

MAX_STATEMENTS = 40
VERDICT_KO = {"verified": "확인됨", "contradicted": "불일치", "partially_verified": "유사 서술만 확인", "unverified": "근거 없음"}


def target_document(db, plan: dict, project_id: int | None) -> KBDocument | None:
    if plan.get("target_document_id"):
        return db.get(KBDocument, plan["target_document_id"])
    return db.scalar(select(KBDocument).where(KBDocument.project_id == project_id, KBDocument.source_url.is_(None))
                     .order_by(desc(KBDocument.id)).limit(1))


def extract_statements(db, doc: KBDocument) -> list[dict[str, Any]]:
    out, seen = [], set()
    for ch in db.scalars(select(KBChunk).where(KBChunk.document_id == doc.id).order_by(KBChunk.ord)):
        if ch.section and ch.section.startswith("Table"):
            continue
        for sent in split_sentences(ch.text):
            s = re.sub(r"\s+", " ", sent).strip(" -•▪*·")
            if len(s) < 12 or s in seen or s.startswith("[Speaker notes]"):
                continue
            if significant_numbers(s) or years_in(s) or re.search(r"(최초|최대|유일|1위|점유율|성장|증가|감소|first|largest|only)", s, re.I):
                seen.add(s)
                out.append({"text": s, "page": ch.page})
    return out[:MAX_STATEMENTS]


def judge(statement: str, sentence: str) -> tuple[str, float]:
    st_q, se_q = quantities(statement), quantities(sentence)
    st_n = set(significant_numbers(statement)) - set(years_in(statement))
    se_n = set(significant_numbers(sentence))
    sim = jaccard(content_tokens(statement), content_tokens(sentence))
    if (st_q and st_q <= se_q) or (st_n and st_n <= se_n and not st_q):
        return ("verified", sim) if sim >= 0.2 else ("unverified", sim)
    classes = {k for k, _ in st_q} & {k for k, _ in se_q}
    if classes and sim >= 0.3 and set(years_in(statement)) == set(years_in(sentence)):
        return "contradicted", sim
    if not st_q and not st_n and sim >= 0.4:
        return "partially_verified", sim
    return "unverified", sim


def run_verify_document(p, plan: dict) -> dict[str, Any]:  # p: research_pipeline.Pipeline
    from app.pipeline.research_pipeline import orch_mode

    db, t = p.db, p.task
    s = get_settings()
    doc = target_document(db, plan, t.project_id)
    if doc is None:
        raise LookupError("검증할 문서가 없습니다. 지식베이스에 PPT/보고서를 먼저 업로드하세요.")
    from sqlalchemy.orm.attributes import flag_modified

    plan["target_document_id"] = doc.id
    t.plan = dict(plan)
    flag_modified(t, "plan")
    db.commit()

    # evidence ----------------------------------------------------------------------------------
    p._status(TaskStatus.RESEARCHING)
    p._step("research", "running")
    analyst = DocumentAnalystAgent(db, **p.kw)
    target_src = Source(project_id=t.project_id, task_id=t.id, kb_document_id=doc.id, title=f"[검증 대상] {doc.title}",
                        source_type="user_upload", tier=5, accessed=True, publication_date=doc.date)
    db.add(target_src)
    db.commit()
    statements = extract_statements(db, doc)
    analyst.say(f"📑 검증 대상 ‘{doc.title}’에서 확인할 문장 {len(statements)}건(숫자·연도·최상급 표현)을 뽑았습니다.")
    kb = analyst.from_knowledge_base(t.project_id)
    evidence = [x for x in kb.sources if x.kb_document_id != doc.id]
    for x in kb.sources:
        if x.kb_document_id == doc.id:
            db.delete(x)
    notes = {"found": len(evidence), "accessed": len(evidence), "failed": [], "provider": None, "injection_warnings": kb.injection_warnings}
    web = WebResearcherAgent(db, **p.kw)
    queries = [" ".join(st["text"].split()[:12]) for st in statements[:6]]
    provider, results, errors = web.search(queries) if queries else (None, [], [])
    notes["provider"], notes["search_errors"] = provider, errors
    if results:
        got = analyst.fetch_and_ingest(results, project_id=t.project_id, project_slug=p.project.slug if p.project else None,
                                       max_sources=s.max_sources_per_task)
        evidence += [x for x in got.sources if x.accessed]
        notes["found"] += got.found
        notes["accessed"] += got.accessed
        notes["failed"] += got.failed
    elif errors:
        web.say("⚠️ " + " / ".join(errors[:2]))
    p._step("research", "done", f"근거 출처 {len(evidence)}건")

    # verify ------------------------------------------------------------------------------------
    p._status(TaskStatus.ANALYZING)
    p._step("verify", "running")
    ver = office.lead_of(db, "verification")
    ev_by_doc = {x.kb_document_id: x for x in evidence if x.kb_document_id}
    claims: list[Claim] = []
    for st in statements:
        best: tuple[str, float, Any, str] | None = None
        hits = hybrid_search(db, st["text"], document_ids=list(ev_by_doc), limit=6) if ev_by_doc else []
        for h in hits:
            for sent in split_sentences(h.text):
                verdict, sim = judge(st["text"], sent)
                rank = {"verified": 3, "contradicted": 2, "partially_verified": 1, "unverified": 0}[verdict]
                if best is None or (rank, sim) > ({"verified": 3, "contradicted": 2, "partially_verified": 1, "unverified": 0}[best[0]], best[1]):
                    best = (verdict, sim, h, sent)
        verdict = best[0] if best else "unverified"
        src = ev_by_doc.get(best[2].document_id) if best and verdict != "unverified" else None
        conf = round((1.0 if verdict == "verified" else 0.5 if verdict == "partially_verified" else 0.0) * TIER_WEIGHT.get(src.tier if src else 7, 0.6), 3)
        note = {"verified": "독립 출처에서 같은 수치 확인", "contradicted": "독립 출처의 수치와 다름 — 수정 필요",
                "partially_verified": "유사한 서술은 있으나 수치 비교 불가", "unverified": "근거 자료에서 확인되지 않음"}[verdict]
        c = Claim(project_id=t.project_id, task_id=t.id, source_id=src.id if src else None, text=st["text"], kind="FACT",
                  topic="문서 검증", supporting_quote=best[3][:1500] if src else None, page_number=best[2].page if src else None,
                  confidence=conf, verification_status=verdict, verification_notes=[note],
                  origin={"document_id": doc.id, "page": st["page"], "text": st["text"]})
        db.add(c)
        claims.append(c)
    db.commit()
    counts = {k: sum(c.verification_status == k for c in claims) for k in VERDICT_KO}
    office.post(db, ver, "🔍 문서 검증: " + " · ".join(f"{VERDICT_KO[k]} {v}" for k, v in counts.items()), task_id=t.id, kind="report")
    office.post(db, office.employee(db, "numbers_auditor"), f"숫자 대조 완료 — 불일치 {counts['contradicted']}건은 수정이 필요합니다.", task_id=t.id)
    p._step("verify", "done", str(counts))

    # write -------------------------------------------------------------------------------------
    p._status(TaskStatus.WRITING)
    p._step("write", "running")
    reg = CitationRegistry()
    rows = []
    for c in claims:
        src = db.get(Source, c.source_id) if c.source_id else None
        n = reg.cite(src, page=c.page_number) if src else None
        rows.append([f"p.{c.origin['page'] or '-'}", c.text[:200], VERDICT_KO[c.verification_status], f"[{n}]" if n else "-",
                     (c.supporting_quote or "")[:200]])
    label = {"verified": "FACT", "contradicted": "UNKNOWN", "partially_verified": "ANALYSIS", "unverified": "UNKNOWN"}
    content = ReportContent(title=f"문서 검증 보고서 — {doc.title}", subtitle=t.request, organization="Personal AI Office 검증팀")
    total = len(claims) or 1
    content.summary = [Statement(f"검증 대상 문장 {len(claims)}건 중 확인 {counts['verified']}건({counts['verified'] / total:.0%}), "
                                 f"불일치 {counts['contradicted']}건, 유사 서술만 {counts['partially_verified']}건, 근거 없음 {counts['unverified']}건.", "ANALYSIS"),
                       Statement(f"근거로 사용한 독립 출처 {len(evidence)}건 (지식베이스 + 웹 원문).", "ANALYSIS")]
    content.sections = [
        Section("검증 방법", [Block("bullets", [Statement("대상 문서에서 숫자·연도·최상급 표현이 있는 문장을 추출"),
                                                Statement("같은 프로젝트의 다른 자료와 웹 원문(스니펫 아님)에서 가장 유사한 문장을 하이브리드 검색"),
                                                Statement("단위를 정규화한 수치(원·달러·%)가 같으면 확인, 같은 연도·지표인데 다르면 불일치로 판정 (LLM 판단 아님)")])]),
        Section("검증 결과표", [Block("table", header=["위치", "대상 문장", "판정", "근거", "근거 인용"], rows=rows, caption="문장별 판정")]),
    ]
    for key, title in (("contradicted", "수정이 필요한 항목 (불일치)"), ("unverified", "근거를 찾지 못한 항목")):
        items = [c for c in claims if c.verification_status == key]
        stmts = [Statement(f"(p.{c.origin['page'] or '-'}) {c.text}", label[key],
                           [reg.number_for(c.source_id)] if c.source_id and reg.number_for(c.source_id) else [],
                           footnote=f"근거 원문: “{c.supporting_quote[:250]}”" if c.supporting_quote else None) for c in items]
        content.sections.append(Section(title, [Block("bullets", stmts or [Statement("없음")])]))
    content.bibliography = reg.entries
    title = content.title[:120]
    art, v = save_artifact(db, title=title, fmt="docx", build=lambda path: build_docx(content, path), author_agent="Verification Team",
                           project=p.project, task_id=t.id, kind="report", source_ids=[x.id for x in evidence])
    save_artifact(db, title=title, fmt="md", build=lambda path: (path.write_text(to_markdown(content), encoding="utf-8"), path)[1],
                  author_agent="Verification Team", project=p.project, task_id=t.id, kind="research")

    def build_sheet(path: Path) -> Path:
        x = XlsxBuilder(title)
        x.add_summary([("대상 문서", doc.title), *[(VERDICT_KO[k], v) for k, v in counts.items()]], legend=False)
        x.add_table_sheet("Checks", ["위치", "대상 문장", "판정", "신뢰도", "근거 번호", "근거 출처", "근거 페이지", "근거 인용", "메모"],
                          [[f"p.{c.origin['page'] or '-'}", c.text, VERDICT_KO[c.verification_status], c.confidence,
                            reg.number_for(c.source_id) if c.source_id else "", (db.get(Source, c.source_id).title if c.source_id else ""),
                            c.page_number, c.supporting_quote, "; ".join(c.verification_notes)] for c in claims],
                          widths={"B": 60, "H": 60})
        return x.save(path)

    xart, xv = save_artifact(db, title=f"{title} 체크시트", fmt="xlsx", build=build_sheet, author_agent="Data Agent",
                             project=p.project, task_id=t.id, source_ids=[x.id for x in evidence])
    office.request_approval(db, office.employee(db, "citation_checker"), "문서 검증 보고서 검토", action="report_submission", task_id=t.id,
                            payload={"artifact_id": art.id})
    p._step("write", "done", v.file_path)

    # QC + 결재 ------------------------------------------------------------------------------------
    p._step("qc", "running")
    checks = [
        {"name": "검증 대상 문장 추출", "passed": bool(claims), "detail": f"{len(claims)}건"},
        {"name": "독립 근거 출처 확보", "passed": bool(evidence), "detail": f"{len(evidence)}건"},
        {"name": "확인 판정은 모두 근거 인용 보유", "passed": all(c.supporting_quote for c in claims if c.verification_status == "verified"), "detail": ""},
        {"name": "불일치 항목 보고서 명시", "passed": True, "detail": f"{counts['contradicted']}건"},
        {"name": "문서 형식 검사", "passed": Path(v.file_path).exists() and Path(xv.file_path).exists(), "detail": "docx/xlsx"},
    ]
    qc = {"passed": all(c["passed"] for c in checks), "checks": checks,
          "stats": {"statements": len(claims), **counts, "evidence_sources": len(evidence)}}
    p._auto_stamp_team_approvals(qc["passed"])
    final = office.request_approval(db, office.employee(db, "orchestrator"), f"최종 산출물 승인: {t.title[:80]}", action="final_delivery",
                                    task_id=t.id, requires_user=True, payload={"artifact_ids": [art.id, xart.id], "qc": qc})
    p._step("qc", "done", f"passed={qc['passed']}")
    summary = {"files": {"docx": v.file_path, "xlsx": xv.file_path}, "artifact_ids": [art.id, xart.id], "mode": "verify_document",
               "target_document": doc.title, "sources_found": notes["found"], "sources_accessed": notes["accessed"],
               "sources_failed": notes["failed"], "search_errors": notes.get("search_errors", []),
               "sources_verified": len({c.source_id for c in claims if c.verification_status == "verified"}),
               "claims_checked": len(claims), "claims_verified": counts["verified"], "claims_unverified": len(claims) - counts["verified"],
               "verdicts": counts, "qc": qc, "critique": [], "final_approval_id": final.id, "llm": orch_mode()}
    t.result_summary = summary
    t.status, t.progress, t.current_step = TaskStatus.WAITING_USER.value, 100.0, "CEO 결재 대기"
    db.commit()
    msg = (f"{'✅' if counts['contradicted'] == 0 and counts['unverified'] == 0 else '⚠️'} 문서 검증 완료 — ‘{doc.title}’\n"
           f"확인 {counts['verified']} / 불일치 {counts['contradicted']} / 유사 {counts['partially_verified']} / 근거 없음 {counts['unverified']}\n"
           f"📄 검증 보고서 · 📊 체크시트 — 최종 결재를 올렸습니다 (결재함 #{final.id}).")
    p._chief_says(msg)
    office.notify(db, f"문서 검증 완료: {doc.title[:60]}", msg, t.id, link=f"/tasks/{t.id}")
    audit(db, "orchestrator", "task_completed", task_id=t.id, detail={"mode": "verify_document", **counts,
                                                                      "at": datetime.now(timezone.utc).isoformat()})
    office.reset_statuses(db, t.id)
    return summary
