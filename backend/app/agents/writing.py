"""Writing team: assembles the evidence-backed report (DOCX + MD/PDF exports).

The writer does not invent content: it arranges verified claims (with citations and footnotes),
the labelled analysis, the financial model and an explicit limitations section.
"""
from __future__ import annotations

from app.agents.analysis import SECTION_TITLES
from app.agents.base import Agent
from app.generators.content import Block, ReportContent, Section, Statement
from app.pipeline.pack import EvidencePack
from app.pipeline.textutil import content_tokens, relevance


def financial_blocks(pack: EvidencePack) -> list[Block]:
    fm = pack.analysis.financial
    if not fm:
        return []
    arows = [[a.label, f"{a.value:.1%}" if a.unit == "%" else f"{a.value:,.0f} {a.unit}", a.kind, a.note] for a in fm.assumptions]
    mrows = [[str(r["year"]), f"{r['customers']:,.0f}", f"{r['revenue']:,.0f}", f"{r['operating_income']:,.0f}",
              f"{r['cumulative_income']:,.0f}"] for r in fm.rows]
    sm = fm.summary
    return [
        Block("paragraph", [Statement("아래 재무 모델의 입력값은 모두 가정(ASSUMPTION)이며, 계산은 Python 계산 엔진으로 수행하고 "
                                      "XLSX 수식과 대조 검증했습니다. 가정은 Assumptions 시트에서 수정할 수 있습니다.", "ANALYSIS")]),
        Block("table", header=["가정 항목", "값", "구분", "비고"], rows=arows, caption="재무 모델 가정표"),
        Block("table", header=["연도", "고객 수", "매출(원)", "영업이익(원)", "누적 영업이익(원)"], rows=mrows, caption="모델 계산 결과 (MODEL CALCULATION)"),
        Block("chart", chart={"kind": "bar", "title": "매출 및 영업이익 (모델 계산, 원)", "categories": [f"Y{r['year']}" for r in fm.rows],
                              "series": [{"name": "매출", "values": [r["revenue"] for r in fm.rows]},
                                         {"name": "영업이익", "values": [r["operating_income"] for r in fm.rows]}]}),
        Block("bullets", [Statement(f"손익분기 도달 연도: {('Y' + str(sm['breakeven_year'])) if sm['breakeven_year'] else '5년 내 미도달'}", "ESTIMATE"),
                          Statement(f"LTV/CAC: {sm['ltv_cac_ratio']}", "ESTIMATE"),
                          Statement(f"CAC 회수기간: {sm['payback_months']}개월", "ESTIMATE")]),
    ]


TEMPLATE_KEYWORDS = [
    ("problem", r"문제|problem|배경|background"), ("insight", r"개요|요약|insight|시사점|논의|결과|result|finding"),
    ("solution", r"해결|solution|방안|제안"), ("business_model", r"비즈니스|business model|수익|사업 모델"),
    ("market", r"시장|market|경쟁"), ("strategy", r"전략|strategy|gtm|로드맵|roadmap|향후"),
    ("risks", r"리스크|risk|위험|한계"),
]


class WritingAgent(Agent):
    agent_type = "writing_lead"

    def _template_sections(self, pack: EvidencePack, headings: list[str], name: str) -> list[Section]:
        import re

        out = []
        for h in headings:
            if re.search(r"재무|financ", h, re.I) and pack.analysis.financial:
                out.append(Section(h, financial_blocks(pack)))
                continue
            key = next((k for k, pat in TEMPLATE_KEYWORDS if re.search(pat, h, re.I)), None)
            stmts = [pack.astatement(s) for s in pack.analysis.sections.get(key, [])] if key else []
            out.append(Section(h, [Block("bullets", stmts or [Statement(f"‘{name}’ 템플릿의 이 섹션을 채울 검증된 근거가 없습니다.", "UNKNOWN")])]))
        return out

    def compose(self, pack: EvidencePack) -> ReportContent:
        self.work("보고서 구성 중")
        plan, v = pack.plan, pack.verification
        verified = sorted(pack.verified, key=lambda c: -c.confidence)
        content = ReportContent(title=plan.get("report_title") or f"{plan.get('topic', '조사')} 조사 보고서",
                                subtitle=plan.get("goal", ""), organization="Personal AI Office")

        content.summary = [pack.claim_statement(c, footnote=False) for c in verified[:4]]
        content.summary += [pack.astatement(s) for s in pack.analysis.sections.get("insight", [])[:2]]
        content.summary.append(Statement(f"검증 결과: 주장 {v.get('total', 0)}건 중 확인 {v.get('verified', 0)}건, 부분확인 {v.get('partial', 0)}건, "
                                         f"미확인 {v.get('unverified', 0)}건, 충돌 {v.get('contradicted', 0)}건, 오래된 자료 {v.get('outdated', 0)}건.", "ANALYSIS"))

        rn = pack.research_notes
        overview = [Statement(f"목표: {plan.get('goal', '')}"), Statement(f"대상 독자: {plan.get('audience', 'CEO')}"),
                    Statement(f"조사 질문: {' / '.join(plan.get('questions', []))}"),
                    Statement(f"방법: 병렬 웹 검색({rn.get('provider') or '미설정'}) → 공식 자료 우선 선별 → 원문 다운로드·파싱 → "
                              f"근거 추출 → 인용문·숫자·날짜·교차 검증 → 비판 검토 → 문서화"),
                    Statement(f"출처: 발견 {rn.get('found', 0)}건, 원문 확인 {rn.get('accessed', 0)}건, 접근 실패 {len(rn.get('failed', []))}건")]
        if plan.get("feedback"):
            overview.append(Statement(f"개정 요청 반영: {plan['feedback']}"))
        content.sections.append(Section("조사 개요", [Block("bullets", overview)]))

        findings = Section("주요 발견 (검증된 사실)")
        topic_tokens = content_tokens(plan.get("topic", ""))
        questions = plan.get("questions", [])
        buckets: dict[str, list] = {q: [] for q in questions}
        rest = []
        for c in verified:  # assign each claim to its best-matching question (topic words excluded)
            scores = [(relevance(c.text, content_tokens(q) - topic_tokens), q) for q in questions]
            best = max(scores, default=(0, None))
            if c.topic in buckets and best[0] < 1:
                buckets[c.topic].append(c)
            elif best[1] is not None and best[0] > 0:
                buckets[best[1]].append(c)
            else:
                rest.append(c)
        for q in questions:
            findings.blocks.append(Block("paragraph", [Statement(q)]))
            findings.blocks.append(Block("bullets", [pack.claim_statement(c) for c in buckets[q][:6]] or
                                         [Statement("이 질문에 대한 검증된 근거를 찾지 못했습니다.", "UNKNOWN")]))
        if rest:
            findings.blocks.append(Block("paragraph", [Statement("기타 검증된 사실")]))
            findings.blocks.append(Block("bullets", [pack.claim_statement(c) for c in rest[:8]]))
        if pack.analysis.market_chart:
            nums = pack.cite_claims(pack.analysis.market_chart_claims)
            findings.blocks.append(Block("chart", chart=pack.analysis.market_chart,
                                         caption=f"{pack.analysis.market_chart['title']} — 출처 " + "".join(f"[{n}]" for n in sorted(set(nums)))))
        content.sections.append(findings)

        tpl = plan.get("template") or {}
        tpl_sections = (tpl.get("structure") or {}).get("sections") or []
        if tpl_sections:
            content.sections.extend(self._template_sections(pack, tpl_sections, tpl.get("name", "템플릿")))
        else:
            analysis = Section("분석")
            for key, title in SECTION_TITLES.items():
                stmts = pack.analysis.sections.get(key)
                if stmts:
                    analysis.blocks.append(Block("paragraph", [Statement(title)]))
                    analysis.blocks.append(Block("bullets", [pack.astatement(s) for s in stmts]))
            content.sections.append(analysis)

        swot = pack.analysis.swot
        if swot:
            def cell(k: str) -> str:
                return "\n".join(f"[{s.label}] {s.text}" for s in swot.get(k, [])) or "UNKNOWN"
            content.sections.append(Section("SWOT", [Block("table", header=["강점(S)", "약점(W)", "기회(O)", "위협(T)"],
                                                           rows=[[cell("S"), cell("W"), cell("O"), cell("T")]], caption="SWOT 분석")]))
        if pack.analysis.kpis or pack.analysis.roadmap:
            blocks = []
            if pack.analysis.kpis:
                blocks.append(Block("table", header=["KPI", "목표", "구분"], rows=[[k["name"], k["target"], k["label"]] for k in pack.analysis.kpis], caption="KPI"))
            if pack.analysis.roadmap:
                blocks.append(Block("table", header=["단계", "내용", "구분"], rows=[[r["phase"], r["text"], r.get("label", "ASSUMPTION")] for r in pack.analysis.roadmap], caption="로드맵"))
            content.sections.append(Section("KPI 및 로드맵", blocks))
        fin = financial_blocks(pack)
        if fin:
            content.sections.append(Section("재무 모델", fin))

        limits: list[Statement] = []
        for c in pack.claims:
            if c.verification_status in ("unverified", "contradicted", "outdated"):
                limits.append(Statement(f"{c.text[:200]} — {', '.join(c.verification_notes or [])}", "UNKNOWN" if c.verification_status == "unverified" else "ANALYSIS"))
        for f in rn.get("failed", [])[:10]:
            limits.append(Statement(f"접근 실패 출처: {f}", "UNKNOWN"))
        for w in rn.get("injection_warnings", []):
            limits.append(Statement(f"프롬프트 인젝션 의심 문구가 포함된 문서(데이터로만 처리함): {w}", "ANALYSIS"))
        content.sections.append(Section("한계 및 미검증 항목", [Block("bullets", limits[:30] or [Statement("미검증 항목 없음.")])]))

        crit = [Statement(f"[{i['severity'].upper()}] {i['message']} → {i.get('suggestion', '')}", "OPINION") for i in pack.critique.issues]
        content.sections.append(Section("비판 검토 (Critic Agent)", [Block("bullets", crit or [Statement("중대한 문제 없음.", "OPINION")])]))
        content.bibliography = pack.registry.entries
        self.log("report_composed", sections=len(content.sections), citations=len(content.bibliography))
        return content
