"""Presentation team: builds the storyline deck from the same evidence pack as the report."""
from __future__ import annotations

from app.agents.base import Agent
from app.generators.content import Statement
from app.generators.pptx_builder import SlideSpec
from app.pipeline.pack import EvidencePack


def _or_unknown(stmts: list[Statement], what: str) -> list[Statement]:
    return stmts or [Statement(f"{what}: 검증된 근거가 없어 비워 둡니다.", "UNKNOWN")]


class PresentationAgent(Agent):
    agent_type = "presentation_lead"

    def slides(self, pack: EvidencePack) -> list[SlideSpec]:
        self.work("발표자료 스토리라인 구성 중")
        plan, a, v = pack.plan, pack.analysis, pack.verification
        verified = sorted(pack.verified, key=lambda c: -c.confidence)
        sec = lambda k: [pack.astatement(s) for s in a.sections.get(k, [])][:5]  # noqa: E731
        slides: list[SlideSpec] = [
            SlideSpec("title", plan.get("deck_title") or f"{plan.get('topic', '')}", subtitle=f"{plan.get('audience', 'CEO')} 브리핑 · Personal AI Office",
                      notes=f"목표: {plan.get('goal', '')}. 모든 사실에는 [n] 출처 번호가 있으며 마지막 슬라이드에 목록이 있습니다."),
            SlideSpec("bullets", "문제 정의", kicker="Problem", statements=_or_unknown(sec("problem"), "문제 정의"),
                      notes="문제 정의는 검증된 출처에 근거한 항목만 사실로 표시했습니다."),
            SlideSpec("bullets", "근거: 검증된 핵심 사실", kicker="Evidence",
                      statements=_or_unknown([pack.claim_statement(c, footnote=False) for c in verified[:5]], "핵심 사실"),
                      notes="각 사실은 원문 인용문 존재와 숫자 일치가 확인된 항목입니다. 신뢰도: " +
                            ", ".join(f"{c.confidence:.2f}" for c in verified[:5])),
            SlideSpec("kpi", "검증 현황", kicker="Evidence",
                      kpis=[{"value": str(v.get("verified", 0)), "label": "검증된 주장", "note": f"전체 {v.get('total', 0)}건"},
                            {"value": str(pack.research_notes.get("accessed", 0)), "label": "원문 확인 출처", "note": f"발견 {pack.research_notes.get('found', 0)}건"},
                            {"value": str(v.get("unverified", 0) + v.get("contradicted", 0)), "label": "미확인·충돌", "note": "보고서 부록 참조"}],
                      notes="숫자는 검증 엔진이 집계한 값입니다."),
            SlideSpec("bullets", "핵심 인사이트", kicker="Insight", statements=_or_unknown(sec("insight"), "인사이트")),
            SlideSpec("bullets", "해결 방안", kicker="Solution", statements=_or_unknown(sec("solution"), "해결 방안")),
            SlideSpec("bullets", "비즈니스 모델", kicker="Business Model", statements=_or_unknown(sec("business_model"), "비즈니스 모델")),
        ]
        if a.market_chart:
            nums = pack.cite_claims(a.market_chart_claims)
            chart = dict(a.market_chart, source_note="출처: " + "".join(f"[{n}]" for n in sorted(set(nums))))
            slides.append(SlideSpec("chart", "시장 규모", kicker="Market", chart=chart, statements=sec("market")[:3]))
        else:
            slides.append(SlideSpec("bullets", "시장", kicker="Market", statements=_or_unknown(sec("market"), "시장")))
        slides.append(SlideSpec("bullets", "전략", kicker="Strategy", statements=_or_unknown(sec("strategy"), "전략")))
        swot = a.swot
        if swot:
            slides.append(SlideSpec("comparison", "SWOT", kicker="Strategy", header=["강점(S)", "약점(W)", "기회(O)", "위협(T)"],
                                    rows=[["\n".join(s.text[:90] for s in swot.get(k, [])[:3]) or "UNKNOWN" for k in "SWOT"]]))
        fm = a.financial
        if fm:
            slides.append(SlideSpec("chart", "재무 전망 (모델 계산)", kicker="Financials",
                                    chart={"kind": "bar", "categories": [f"Y{r['year']}" for r in fm.rows],
                                           "series": [{"name": "매출", "values": [r["revenue"] for r in fm.rows]},
                                                      {"name": "영업이익", "values": [r["operating_income"] for r in fm.rows]}],
                                           "source_note": "입력값은 모두 가정(ASSUMPTION) — 스프레드시트 Assumptions 시트 참조"},
                                    statements=[Statement(f"손익분기: {('Y' + str(fm.summary['breakeven_year'])) if fm.summary['breakeven_year'] else '5년 내 미도달'}", "ESTIMATE"),
                                                Statement(f"LTV/CAC {fm.summary['ltv_cac_ratio']}", "ESTIMATE")],
                                    notes="재무 수치는 LLM이 아니라 계산 엔진이 산출했고, XLSX 수식과 대조 검증되었습니다."))
        if a.roadmap:
            slides.append(SlideSpec("timeline", "로드맵", kicker="Roadmap",
                                    steps=[{"label": r["phase"], "text": r["text"]} for r in a.roadmap]))
        slides.append(SlideSpec("process", "업무 수행 과정", kicker="Method",
                                steps=[{"label": "조사", "text": "병렬 검색·공식 자료 우선"}, {"label": "원문 확인", "text": "PDF/웹 원문 파싱"},
                                       {"label": "검증", "text": "인용문·숫자·날짜·교차"}, {"label": "비판 검토", "text": "Critic Agent"},
                                       {"label": "문서화", "text": "DOCX·PPTX·XLSX"}]))
        concl = [pack.astatement(s) for s in a.sections.get("insight", [])[:2]]
        concl += [Statement(f"미확인·충돌 항목 {v.get('unverified', 0) + v.get('contradicted', 0)}건은 결론에서 제외했습니다.", "ANALYSIS")]
        slides.append(SlideSpec("bullets", "결론", kicker="Conclusion", statements=concl))
        slides.append(SlideSpec("sources", "출처", bibliography=pack.registry.entries))
        self.log("slides_planned", count=len(slides))
        return slides
