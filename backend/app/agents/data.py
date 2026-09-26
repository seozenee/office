"""Data team: evidence database + financial model spreadsheet, with formula ↔ Python cross-check."""
from __future__ import annotations

from pathlib import Path

from app.agents.base import Agent
from app.generators.xlsx_builder import XlsxBuilder, verify_model_sheet
from app.pipeline.pack import EvidencePack


class DataAgent(Agent):
    agent_type = "data_lead"

    def build_workbook(self, pack: EvidencePack, path: Path) -> tuple[Path, list[str]]:
        self.work("증거 DB·모델 스프레드시트 작성 중")
        v = pack.verification
        x = XlsxBuilder(f"{pack.plan.get('topic', '')} — 증거 데이터베이스")
        x.add_summary([("목표", pack.plan.get("goal", "")), ("검증된 주장", v.get("verified", 0)), ("전체 주장", v.get("total", 0)),
                       ("원문 확인 출처", pack.research_notes.get("accessed", 0)), ("접근 실패", len(pack.research_notes.get("failed", [])))])
        src_num = {e.source_id: e.number for e in pack.registry.entries}
        if pack.analysis.financial:
            x.add_assumptions(pack.analysis.financial.assumptions, src_num)
            x.add_financial_model(pack.analysis.financial)
        x.add_table_sheet("Claims", ["ID", "구분", "주장", "검증 상태", "신뢰도", "출처 번호", "출처 ID", "페이지", "인용문", "검증 메모"],
                          [[c.id, c.kind, c.text, c.verification_status, c.confidence, src_num.get(c.source_id, ""), c.source_id,
                            c.page_number, c.supporting_quote, "; ".join(c.verification_notes or [])] for c in pack.claims],
                          widths={"C": 70, "I": 70, "J": 40})
        x.add_table_sheet("Sources", ["ID", "인용 번호", "제목", "발행처", "유형", "등급(1=정부)", "발행일", "접근일", "원문 확인", "URL", "오류"],
                          [[s.id, src_num.get(s.id, ""), s.title, s.publisher, s.source_type, s.tier, s.publication_date,
                            s.access_date.date().isoformat() if s.access_date else "", "Y" if s.accessed else "N", s.url, s.access_error or ""]
                           for s in pack.sources], widths={"C": 50, "J": 50})
        x.save(path)
        problems: list[str] = []
        if pack.analysis.financial:
            problems = verify_model_sheet(path, pack.analysis.financial)
            self.log("formula_crosscheck", mismatches=len(problems))
        return path, problems
