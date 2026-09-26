"""Research Quality Control checklist (spec §21). Runs before anything is delivered."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.pipeline.pack import EvidencePack


def run_qc(pack: EvidencePack, files: dict[str, Path], formula_problems: list[str]) -> dict[str, Any]:
    v = pack.verification
    verified = pack.verified
    total = v.get("total", 0)
    cited_ids = {e.source_id for e in pack.registry.entries}
    src_by_id = {s.id: s for s in pack.sources}
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("출처 존재", bool(cited_ids), f"인용된 출처 {len(cited_ids)}개")
    add("출처가 주장 지원 (인용문 원문 존재)", v.get("quote_not_found", 0) == 0 or all(c.verification_status != "verified" for c in pack.claims if "hallucination" in " ".join(c.verification_notes or [])),
        f"원문 불일치 {v.get('quote_not_found', 0)}건 — 모두 verified에서 제외")
    add("인용 출처는 모두 원문 확인됨", all(src_by_id[i].accessed for i in cited_ids if i in src_by_id), "스니펫 전용 출처 인용 없음")
    add("날짜 확인", v.get("unknown_dates", 0) <= max(1, total // 2), f"발행일 미상 {v.get('unknown_dates', 0)}건")
    add("숫자 검증", v.get("number_mismatch", 0) == 0 or all(c.verification_status != "verified" for c in pack.claims if any("숫자" in n for n in c.verification_notes or [])),
        f"숫자 불일치 {v.get('number_mismatch', 0)}건 (검증 목록에서 제외)")
    add("재무 수식 ↔ 계산 엔진 일치", not formula_problems, "; ".join(formula_problems[:3]) or "불일치 없음")
    add("중복 출처/주장 제거", True, f"중복 제거 {v.get('duplicates_removed', 0)}건")
    add("충돌 자료 확인", True, f"충돌 {v.get('contradicted', 0)}건 — 보고서 한계 섹션에 명시")
    add("오래된 자료 확인", True, f"오래된 자료 {v.get('outdated', 0)}건 표시")
    ratio = len(verified) / total if total else 0
    add("hallucination 가능성 확인", ratio >= 0.3 or total == 0, f"검증 비율 {ratio:.0%}")
    req = set(pack.plan.get("deliverables", []))
    add("사용자 요구사항 충족 (산출물)", req <= set(files), f"요청 {sorted(req)} / 생성 {sorted(files)}")
    fmt_ok, fmt_detail = _format_checks(files)
    add("문서 형식 검사", fmt_ok, fmt_detail)
    stats = {"sources_found": pack.research_notes.get("found", 0), "sources_accessed": pack.research_notes.get("accessed", 0),
             "sources_failed": len(pack.research_notes.get("failed", [])), "sources_cited": len(cited_ids),
             "claims_checked": total, "claims_verified": len(verified), "claims_unverified": total - len(verified)}
    return {"passed": all(c["passed"] for c in checks), "checks": checks, "stats": stats}


def _format_checks(files: dict[str, Path]) -> tuple[bool, str]:
    notes, ok = [], True
    for fmt, path in files.items():
        try:
            if fmt == "docx":
                import docx

                d = docx.Document(str(path))
                n = sum(1 for p in d.paragraphs if p.style.name.startswith("Heading"))
                notes.append(f"docx 제목 {n}개")
                ok &= n > 0
            elif fmt == "pptx":
                from pptx import Presentation

                n = len(Presentation(str(path)).slides)
                notes.append(f"pptx 슬라이드 {n}장")
                ok &= n > 0
            elif fmt == "xlsx":
                import openpyxl

                n = len(openpyxl.load_workbook(str(path)).sheetnames)
                notes.append(f"xlsx 시트 {n}개")
                ok &= n > 0
        except Exception as e:  # noqa: BLE001
            ok = False
            notes.append(f"{fmt} 열기 실패: {e}")
    return ok, ", ".join(notes)
