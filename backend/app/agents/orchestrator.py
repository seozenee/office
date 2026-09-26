"""CEO / Command agent (실장): understands the request and decomposes it into a plan."""
from __future__ import annotations

import re
from typing import Any

from app.agents.base import Agent

DELIVERABLE_HINTS = {
    "pptx": r"ppt|피피티|프레젠테이션|presentation|슬라이드|slide|발표|deck|피치|pitch",
    "docx": r"보고서|report|문서|docx|워드|word|사업계획서|계획서|제안서|proposal|리포트|백서|연구계획서|정리",
    "xlsx": r"엑셀|excel|xlsx|스프레드시트|spreadsheet|재무|financial|수치|모델|model|데이터|표로",
}
BUSINESS_HINTS = r"사업|비즈니스|business|창업|스타트업|startup|투자|investor|시장|market|수익|매출|사업계획|아이디어"
COMMAND_WORDS = [
    r"조사해서", r"조사하고", r"만들고", r"작성하고", r"찾고", r"분석하고", r"정리하고", r"읽고", r"해서", r"하고", r"조사해줘", r"조사해", r"리서치해줘", r"분석해서", r"분석하고", r"분석해줘", r"만들어줘", r"만들어",
    r"작성해줘", r"작성해", r"정리해서", r"정리해줘", r"찾아줘", r"검증해줘", r"보여줄", r"까지", r"그리고", r"해줘", r"줘",
    r"투자자용", r"투자자에게", r"새로운", r"이번\s*주", r"이번\s*달", r"을", r"를", r"PPT", r"ppt", r"보고서", r"사업계획서",
    r"사업\s*아이디어", r"아이디어", r"프레젠테이션", r"자료", r"엑셀",
]


class OrchestratorAgent(Agent):
    agent_type = "orchestrator"

    def plan(self, request: str, *, project_context: str = "", has_documents: bool = False,
             memory_notes: list[str] | None = None) -> dict[str, Any]:
        plan = self._llm_plan(request, project_context, has_documents, memory_notes or []) or \
            self._heuristic_plan(request, has_documents)
        plan.setdefault("deliverables", ["docx", "xlsx"])
        if "docx" not in plan["deliverables"]:
            plan["deliverables"].insert(0, "docx")  # the evidence-backed research report is always produced
        if "xlsx" not in plan["deliverables"]:
            plan["deliverables"].append("xlsx")  # evidence database / model
        plan["queries"] = [q for q in dict.fromkeys(q.strip() for q in plan.get("queries", [])) if q][:8]
        plan["questions"] = plan.get("questions", [])[:8]
        return plan

    def _llm_plan(self, request: str, ctx: str, has_docs: bool, memory: list[str]) -> dict[str, Any] | None:
        prompt = f"""Decompose the CEO's request into an execution plan for a multi-agent office.

REQUEST: {request}
PROJECT CONTEXT: {ctx or '(none)'}
USER PREFERENCES / MEMORY: {'; '.join(memory) or '(none)'}
UPLOADED PROJECT DOCUMENTS AVAILABLE: {has_docs}

Return JSON with keys:
  mode: one of "research" (web + knowledge base), "knowledge" (only uploaded documents), "verify_document" (check claims of an existing document)
  goal: one sentence
  audience: who will read the output
  topic: short topic phrase used for search
  questions: 3-7 concrete research sub-questions
  queries: 4-8 web search queries (mix Korean and English; include official/government/statistics phrasing)
  deliverables: subset of ["docx","pptx","xlsx"]
  business: true if business model / financials / market sizing are needed
  subtasks: list of {{"title": str, "department": one of research|verification|strategy|writing|design|data}}"""
        data = self.llm_json("plan", prompt)
        if not isinstance(data, dict) or not data.get("queries"):
            return None
        data["deliverables"] = [d for d in data.get("deliverables", []) if d in ("docx", "pptx", "xlsx")]
        data.setdefault("mode", "research")
        data["planner"] = "llm"
        return data

    def _heuristic_plan(self, request: str, has_docs: bool) -> dict[str, Any]:
        low = request.lower()
        deliverables = [k for k, pat in DELIVERABLE_HINTS.items() if re.search(pat, low)]
        business = bool(re.search(BUSINESS_HINTS, low))
        if "pptx" in deliverables or "사업계획" in request:
            business = business or "투자" in request
        mode = "research"
        if re.search(r"검증|확인해|fact.?check|verify", low) and has_docs:
            mode = "verify_document"
        elif re.search(r"이 (논문|자료|문서|보고서|파일)|업로드|첨부", request) and has_docs:
            mode = "knowledge"
        topic = request
        for w in COMMAND_WORDS:
            topic = re.sub(w, " ", topic, flags=re.I)
        topic = re.sub(r"[^\w\s가-힣·-]", " ", topic)
        topic = re.sub(r"\s+", " ", topic).strip() or request.strip()
        queries = [topic, f"{topic} 동향 보고서", f"{topic} 통계", f"{topic} 정부 정책"]
        questions = [f"{topic}의 현황과 최근 동향은?", f"{topic} 관련 공식 통계와 수치는?", f"{topic} 관련 정책·규제는?"]
        if business:
            queries += [f"{topic} 시장 규모", f"{topic} 경쟁사", f"{topic} 비즈니스 모델"]
            questions += [f"{topic} 시장 규모와 성장률은?", f"{topic}의 주요 경쟁자는?", f"{topic}의 고객 문제와 수익 모델은?"]
        subtasks = [{"title": "자료 조사 및 원문 확보", "department": "research"},
                    {"title": "근거 추출 및 교차 검증", "department": "verification"},
                    {"title": "분석 및 전략 수립", "department": "strategy"},
                    {"title": "보고서 작성", "department": "writing"},
                    {"title": "증거 DB·모델 스프레드시트", "department": "data"}]
        if "pptx" in deliverables:
            subtasks.append({"title": "발표자료 제작", "department": "design"})
        return {"mode": mode, "goal": request.strip(), "audience": "투자자" if "투자" in request else "CEO",
                "topic": topic, "questions": questions, "queries": queries, "deliverables": deliverables or ["docx"],
                "business": business, "subtasks": subtasks, "planner": "heuristic"}
