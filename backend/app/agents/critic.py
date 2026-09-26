"""Critic agent (감사): actively looks for what could be wrong and requests re-research."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.agents.base import Agent
from app.core.config import get_settings
from app.core.models import Claim, Source
from app.pipeline.textutil import content_tokens, relevance

CRITIC_QUESTIONS = [
    "What could be wrong?", "What evidence is missing?", "What assumption is unsupported?",
    "What source contradicts this?", "What information is outdated?", "What would a skeptical expert challenge?",
]


@dataclass
class Critique:
    issues: list[dict] = field(default_factory=list)  # {"severity": high|medium|low, "question", "message", "suggestion"}
    requery: list[str] = field(default_factory=list)
    passed: bool = True

    def add(self, severity: str, question: str, message: str, suggestion: str = "", requery: str | None = None) -> None:
        self.issues.append({"severity": severity, "question": question, "message": message, "suggestion": suggestion})
        if requery:
            self.requery.append(requery)
        if severity == "high":
            self.passed = False


class CriticAgent(Agent):
    agent_type = "critic"

    def review(self, plan: dict, claims: list[Claim], sources: list[Source], verification: dict) -> Critique:
        s = get_settings()
        cr = Critique()
        self.work("결과 비판적 검토 중")
        verified = [c for c in claims if c.verification_status == "verified"]
        total = len(claims)
        accessed = [x for x in sources if x.accessed]

        if not accessed:
            cr.add("high", "What evidence is missing?", "원문을 확인한 출처가 하나도 없습니다.",
                   "검색 제공자 설정 또는 자료 업로드가 필요합니다.")
        ratio = len(verified) / total if total else 0.0
        if total and ratio < s.min_verified_ratio:
            cr.add("high", "What could be wrong?", f"검증된 주장 비율이 {ratio:.0%}로 기준({s.min_verified_ratio:.0%}) 미만입니다.",
                   "공식 자료 위주로 재조사", requery=f"{plan.get('topic', '')} 공식 통계 보고서")
        for q in plan.get("questions", []):
            qt = content_tokens(q)
            if not any(relevance(c.text, qt) >= 1 for c in verified):
                cr.add("medium", "What evidence is missing?", f"질문 ‘{q}’에 대한 검증된 근거가 없습니다.",
                       "해당 질문으로 추가 검색", requery=q)
        tiers = Counter(x.tier for x in accessed)
        if accessed and sum(v for t, v in tiers.items() if t >= 6) / len(accessed) > 0.6:
            cr.add("medium", "What would a skeptical expert challenge?", "출처의 60% 이상이 언론/기타 자료입니다.",
                   "정부·학술·공식 기업 자료 보강", requery=f"{plan.get('topic', '')} site:go.kr OR site:gov OR 백서")
        if verification.get("contradicted"):
            cr.add("medium", "What source contradicts this?", f"출처 간 수치 충돌 {verification['contradicted']}건이 있습니다.",
                   "보고서에 충돌 사실을 명시하고 기준 연도·정의 차이를 확인")
        if verification.get("outdated"):
            cr.add("low", "What information is outdated?", f"오래된 자료 기반 주장 {verification['outdated']}건.",
                   "최신 자료로 대체 검색", requery=f"{plan.get('topic', '')} 최신 동향")
        if verification.get("quote_not_found"):
            cr.add("high" if verification["quote_not_found"] > max(2, total * 0.3) else "medium", "What could be wrong?",
                   f"원문에서 확인되지 않은 인용 {verification['quote_not_found']}건 (hallucination 가능성).",
                   "해당 주장은 최종 문서에서 제외 또는 UNKNOWN 처리")
        single = Counter(c.source_id for c in verified)
        if verified and single.most_common(1)[0][1] / len(verified) > 0.6 and len(single) > 0:
            cr.add("low", "What assumption is unsupported?", "검증된 주장 대부분이 단일 출처에 의존합니다.",
                   "교차 출처 확보")

        if self.has_llm and verified:
            self._llm_review(plan, verified, cr)
        self.log("critique", issues=len(cr.issues), passed=cr.passed, requery=cr.requery)
        return cr

    def _llm_review(self, plan: dict, verified: list[Claim], cr: Critique) -> None:
        facts = "\n".join(f"- ({c.id}) {c.text}" for c in verified[:40])
        prompt = f"""As a skeptical expert, critique this evidence base for the goal: {plan.get('goal')}
Ask: {' / '.join(CRITIC_QUESTIONS)}
Evidence (verified claims):
{facts}
Return JSON {{"issues": [{{"severity": "high|medium|low", "question": str, "message": str, "suggestion": str, "requery": str|null}}]}} (max 5, only substantive issues)."""
        data = self.llm_json("critique", prompt)
        if isinstance(data, dict):
            for it in data.get("issues", [])[:5]:
                if isinstance(it, dict) and it.get("message"):
                    sev = it.get("severity") if it.get("severity") in ("high", "medium", "low") else "low"
                    # LLM findings are advisory: they cannot fail QC on their own
                    cr.add("medium" if sev == "high" else sev, it.get("question", "LLM critique"), it["message"],
                           it.get("suggestion", ""), it.get("requery"))
