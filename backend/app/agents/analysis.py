"""Strategy & Business team: analysis, business model, market sizing and financial model.

Output statements are always labelled. A FACT must cite verified claim ids; anything else is
ANALYSIS / ASSUMPTION / ESTIMATE / OPINION, or UNKNOWN when there is no basis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import Agent
from app.core.models import Claim
from app.tools.calc import Assumption, FinancialModel, compute_financials, default_assumptions

SECTION_KEYS = ["problem", "insight", "solution", "business_model", "market", "strategy", "risks"]
SECTION_TITLES = {"problem": "문제 정의", "insight": "핵심 인사이트", "solution": "해결 방안", "business_model": "비즈니스 모델",
                  "market": "시장", "strategy": "전략 및 GTM", "risks": "리스크"}

_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)\s*년?")


@dataclass
class AStatement:
    text: str
    label: str
    claim_ids: list[int] = field(default_factory=list)


@dataclass
class AnalysisResult:
    sections: dict[str, list[AStatement]] = field(default_factory=dict)
    swot: dict[str, list[AStatement]] = field(default_factory=dict)
    kpis: list[dict[str, str]] = field(default_factory=list)
    roadmap: list[dict[str, str]] = field(default_factory=list)
    market_chart: dict[str, Any] | None = None
    market_chart_claims: list[int] = field(default_factory=list)
    financial: FinancialModel | None = None
    generated_by: str = "rules"


def detect_money_series(claims: list[Claim]) -> tuple[dict[str, Any] | None, list[int]]:
    """Find (year, amount) pairs in verified claims to chart a market-size series. Deterministic:
    each amount is paired with the nearest preceding year in the same sentence."""
    from app.pipeline.textutil import _EN_MONEY, _EN_SCALE, _KO_MONEY

    points: dict[str, dict[int, tuple[float, int, bool]]] = {}
    for c in claims:
        if c.verification_status != "verified":
            continue
        years = [(m.start(), int(m.group(1))) for m in _YEAR.finditer(c.text)]
        if not years:
            continue
        amounts: list[tuple[int, str, float]] = []
        for m in _KO_MONEY.finditer(c.text):
            jo, eok = m.group(1), m.group(2)
            if jo or eok:
                amounts.append((m.start(), "KRW", (float(jo) * 1e12 if jo else 0) + (float(eok.replace(",", "")) * 1e8 if eok else 0)))
        for m in _EN_MONEY.finditer(c.text):
            num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            amounts.append((m.start(), "USD", float(num) * _EN_SCALE[unit.lower()]))
        for pos, cur, value in amounts:
            prior = [y for p, y in years if p < pos]
            if not prior:
                continue
            points.setdefault(cur, {}).setdefault(prior[-1], (value, c.id, c.kind == "ESTIMATE"))
    best = max(points.items(), key=lambda kv: len(kv[1]), default=None)
    if not best or len(best[1]) < 2:
        return None, []
    currency, series = best
    years_sorted = sorted(series)
    unit, div = ("억원", 1e8) if currency == "KRW" else ("백만 USD", 1e6)
    chart = {"kind": "bar", "title": f"검증된 출처 기반 시장 규모 ({unit}, E=전망치)",
             "categories": [f"{y}{'(E)' if series[y][2] else ''}" for y in years_sorted],
             "series": [{"name": f"시장 규모 ({unit})", "values": [round(series[y][0] / div, 2) for y in years_sorted]}],
             "number_format": "#,##0"}
    return chart, list(dict.fromkeys(series[y][1] for y in years_sorted))


class AnalysisAgent(Agent):
    agent_type = "strategy_lead"

    def analyze(self, plan: dict, claims: list[Claim], verification: dict) -> AnalysisResult:
        self.work("분석 및 전략 수립 중")
        verified = [c for c in claims if c.verification_status == "verified"]
        res = AnalysisResult()
        res.market_chart, res.market_chart_claims = detect_money_series(verified)
        llm = self._llm_analysis(plan, verified) if self.has_llm and verified else None
        if llm:
            res.sections, res.swot, res.kpis, res.roadmap = llm["sections"], llm["swot"], llm["kpis"], llm["roadmap"]
            res.generated_by = "llm"
            assumptions = llm.get("assumptions")
        else:
            self._rules(plan, verified, claims, verification, res)
            assumptions = None
        if plan.get("business"):
            res.financial = compute_financials(assumptions or default_assumptions())
        self.log("analysis_done", by=res.generated_by, sections=len(res.sections), financial=bool(res.financial))
        return res

    # -- deterministic ----------------------------------------------------
    def _rules(self, plan: dict, verified: list[Claim], claims: list[Claim], ver: dict, res: AnalysisResult) -> None:
        topic = plan.get("topic", "")
        n_src = len({c.source_id for c in verified})
        insight = [AStatement(f"‘{topic}’ 관련 추출 주장 {len(claims)}건 중 {len(verified)}건이 원문 인용과 숫자 검사를 통과했고, "
                              f"이는 {n_src}개 출처에서 나왔습니다.", "ANALYSIS")]
        numeric = [c for c in verified if re.search(r"\d", c.text)]
        if numeric:
            insight.append(AStatement(f"검증된 수치 근거 {len(numeric)}건이 확보되어 정량 판단의 출발점으로 사용할 수 있습니다.", "ANALYSIS",
                                      [c.id for c in numeric[:3]]))
        if ver.get("contradicted"):
            insight.append(AStatement(f"출처 간 수치가 충돌하는 항목이 {ver['contradicted']}건 있어 해당 수치는 결론에 사용하기 전 기준 정의를 확인해야 합니다.", "ANALYSIS"))
        by_topic: dict[str, list[Claim]] = {}
        for c in verified:
            by_topic.setdefault(c.topic or "기타", []).append(c)
        res.sections["insight"] = insight
        res.sections["problem"] = [AStatement(c.text, "FACT", [c.id]) for c in verified if re.search(r"문제|과제|부족|어려|한계|risk|challenge|shortage|barrier|problem", c.text, re.I)][:4]
        res.sections["market"] = [AStatement(c.text, c.kind if c.kind in ("FACT", "ESTIMATE") else "FACT", [c.id])
                                  for c in verified if re.search(r"시장|market|규모|성장|CAGR|매출|revenue|투자", c.text, re.I)][:5]
        unknown = AStatement("LLM이 연결되지 않은 오프라인 모드에서는 근거 없는 전략 문장을 자동 생성하지 않습니다. "
                             "위 검증된 사실을 바탕으로 CEO 검토가 필요합니다.", "UNKNOWN")
        for key in ("solution", "business_model", "strategy"):
            res.sections[key] = [unknown]
        res.sections["risks"] = [AStatement(c.text, "FACT", [c.id]) for c in verified if re.search(r"규제|법|위험|리스크|regulat|risk|privacy|개인정보|보안", c.text, re.I)][:4] or \
            [AStatement("검증된 출처에서 리스크 관련 근거를 찾지 못했습니다.", "UNKNOWN")]
        for key in ("problem", "market"):
            if not res.sections[key]:
                res.sections[key] = [AStatement("이 항목을 뒷받침하는 검증된 근거를 찾지 못했습니다.", "UNKNOWN")]
        res.swot = {k: [AStatement("근거 부족 — 자동 생성하지 않음", "UNKNOWN")] for k in ("S", "W", "O", "T")}
        if res.sections["market"] and res.sections["market"][0].label != "UNKNOWN":
            res.swot["O"] = res.sections["market"][:2]
        if res.sections["risks"][0].label != "UNKNOWN":
            res.swot["T"] = res.sections["risks"][:2]
        res.kpis = [{"name": "검증된 핵심 근거 수", "target": str(len(verified)), "label": "FACT"},
                    {"name": "공식(1–4등급) 출처 비율", "target": "측정값은 부록 참조", "label": "ANALYSIS"}]
        res.roadmap = [{"phase": "1단계 (템플릿)", "text": "문제·고객 가설 검증 인터뷰", "label": "ASSUMPTION"},
                       {"phase": "2단계 (템플릿)", "text": "MVP 제작 및 파일럿", "label": "ASSUMPTION"},
                       {"phase": "3단계 (템플릿)", "text": "유료 전환 및 채널 확장", "label": "ASSUMPTION"}]

    # -- LLM --------------------------------------------------------------
    def _llm_analysis(self, plan: dict, verified: list[Claim]) -> dict | None:
        facts = "\n".join(f"({c.id}) {c.text}" for c in verified[:60])
        prompt = f"""You are the strategy & business team. Build the analysis for: {plan.get('goal')}
Audience: {plan.get('audience')}. Business analysis required: {plan.get('business')}.
CEO FEEDBACK TO APPLY (revision): {plan.get('feedback') or '(none)'}

VERIFIED EVIDENCE (id, claim) — the ONLY facts you may use:
{facts}

Return JSON:
{{
 "sections": {{ {', '.join(f'"{k}": [statement]' for k in SECTION_KEYS)} }},
 "swot": {{"S": [statement], "W": [...], "O": [...], "T": [...]}},
 "kpis": [{{"name": str, "target": str, "label": "ASSUMPTION|ESTIMATE"}}],
 "roadmap": [{{"phase": str, "text": str, "label": "ASSUMPTION"}}],
 "assumptions": [{{"key": one of ["customers_y1","customer_growth","arpu","price_growth","gross_margin","fixed_costs_y1","fixed_cost_growth","cac","churn"], "label": str, "value": number, "unit": "%" or other, "kind": "ASSUMPTION|ESTIMATE", "claim_id": int|null, "note": str}}]
}}
where statement = {{"text": str, "label": "FACT|ANALYSIS|ASSUMPTION|ESTIMATE|OPINION|UNKNOWN", "claim_ids": [int]}}.
Rules: a FACT must list claim_ids from the evidence above and must not add numbers that are not in those claims.
Percentages are decimals (0.2 = 20%). If there is no basis, use label UNKNOWN. Write in Korean."""
        data = self.llm_json("analysis", prompt)
        if not isinstance(data, dict) or not isinstance(data.get("sections"), dict):
            return None
        valid = {c.id for c in verified}
        by_id = {c.id: c for c in verified}

        def stmt(d: Any) -> AStatement | None:
            if not isinstance(d, dict) or not d.get("text"):
                return None
            label = str(d.get("label", "ANALYSIS")).upper()
            label = label if label in ("FACT", "ANALYSIS", "ASSUMPTION", "ESTIMATE", "OPINION", "UNKNOWN") else "ANALYSIS"
            ids = [i for i in d.get("claim_ids") or [] if isinstance(i, int) and i in valid]
            if label == "FACT":
                from app.pipeline.textutil import significant_numbers

                allowed = {n for i in ids for n in significant_numbers(by_id[i].text)}
                if not ids or any(n not in allowed for n in significant_numbers(d["text"])):
                    label = "UNKNOWN" if not ids else "ANALYSIS"  # unsupported fact is never shown as FACT
            return AStatement(str(d["text"]), label, ids)

        sections = {k: [s for s in (stmt(x) for x in data["sections"].get(k, []) or []) if s] for k in SECTION_KEYS}
        swot = {k: [s for s in (stmt(x) for x in (data.get("swot") or {}).get(k, []) or []) if s] for k in ("S", "W", "O", "T")}
        kpis = [{"name": str(k.get("name")), "target": str(k.get("target")), "label": str(k.get("label", "ASSUMPTION"))}
                for k in data.get("kpis", []) if isinstance(k, dict)][:6]
        roadmap = [{"phase": str(r.get("phase")), "text": str(r.get("text")), "label": "ASSUMPTION"}
                   for r in data.get("roadmap", []) if isinstance(r, dict)][:6]
        assumptions = None
        raw = data.get("assumptions")
        if isinstance(raw, list):
            defaults = {a.key: a for a in default_assumptions()}
            for a in raw:
                if isinstance(a, dict) and a.get("key") in defaults and isinstance(a.get("value"), (int, float)):
                    d = defaults[a["key"]]
                    cid = a.get("claim_id") if a.get("claim_id") in valid else None
                    defaults[a["key"]] = Assumption(d.key, a.get("label") or d.label, float(a["value"]), d.unit,
                                                    "SOURCE" if cid else ("ESTIMATE" if a.get("kind") == "ESTIMATE" else "ASSUMPTION"),
                                                    by_id[cid].source_id if cid else None, str(a.get("note", ""))[:200])
            assumptions = list(defaults.values())
        return {"sections": sections, "swot": swot, "kpis": kpis, "roadmap": roadmap, "assumptions": assumptions}
