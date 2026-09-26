"""Meeting agent: runs kickoff and review (multi-agent debate) meetings and writes minutes
as Decision / Action Item / Owner / Deadline / Status."""
from __future__ import annotations

from datetime import date, timedelta

from app.agents.base import Agent
from app.core.models import Employee
from app.office import service as office


class MeetingAgent(Agent):
    agent_type = "planner"  # 윤서연 과장 runs meetings and keeps minutes

    def _emp(self, agent_type: str) -> Employee:
        return office.employee(self.db, agent_type)

    def kickoff(self, plan: dict) -> int:
        chief, planner = self._emp("orchestrator"), self.employee
        depts = {s["department"] for s in plan.get("subtasks", [])}
        leads = [office.lead_of(self.db, d) for d in sorted(depts) if d != "executive"]
        people = [chief, planner, *[p for p in leads if p]]
        m = office.start_meeting(self.db, f"킥오프: {plan.get('topic', '')[:60]}", people,
                                 ["목표·독자 확인", "조사 범위와 질문", "산출물·담당 배정", "검증 기준"], self.task_id)
        office.say_in_meeting(self.db, m, chief, f"CEO 지시입니다: “{plan.get('goal', '')}”. 결론은 검증 가능한 근거로만 냅니다.")
        office.say_in_meeting(self.db, m, planner, "조사 질문은 다음과 같습니다:\n" + "\n".join(f"· {q}" for q in plan.get("questions", [])))
        deliver = {"docx": "보고서(DOCX)", "pptx": "발표자료(PPTX)", "xlsx": "증거DB·모델(XLSX)"}
        office.say_in_meeting(self.db, m, planner, "산출물: " + ", ".join(deliver[d] for d in plan.get("deliverables", []) if d in deliver))
        for lead in leads:
            if lead.department == "research":
                office.say_in_meeting(self.db, m, lead, f"리서치팀은 검색어 {len(plan.get('queries', []))}개로 정부·공식·학술 자료부터 확보하겠습니다. 스니펫만으로는 판단하지 않고 원문을 확인합니다.")
            elif lead.department == "verification":
                office.say_in_meeting(self.db, m, lead, "검증팀은 모든 주장에 대해 원문 인용문 존재, 숫자 일치, 발행일, 교차 출처를 확인합니다.")
            elif lead.department == "strategy":
                office.say_in_meeting(self.db, m, lead, "전략사업팀은 사실과 가정을 분리해서 분석하겠습니다." + (" 재무 모델도 준비합니다." if plan.get("business") else ""))
            elif lead.department == "writing":
                office.say_in_meeting(self.db, m, lead, "문서팀은 [n] 인용과 참고문헌을 자동 연결한 보고서를 작성합니다.")
            elif lead.department == "design":
                office.say_in_meeting(self.db, m, lead, "디자인팀은 Problem→Evidence→…→Conclusion 순서로 덱을 구성합니다.")
            elif lead.department == "data":
                office.say_in_meeting(self.db, m, lead, "데이터팀은 증거 DB와 모델을 XLSX로 만들고 수식을 Python 결과와 대조합니다.")
        due = (date.today() + timedelta(days=1)).isoformat()
        actions = [{"description": s["title"], "owner": (office.lead_of(self.db, s["department"]).name if office.lead_of(self.db, s["department"]) else "-"),
                    "deadline": due, "status": "in_progress", "decision": "킥오프 배정"} for s in plan.get("subtasks", [])]
        office.end_meeting(self.db, m, [f"목표: {plan.get('goal', '')}", "검증되지 않은 내용은 UNKNOWN으로 표기", "HIGH 이상 행동은 CEO 결재 후 실행"], actions)
        return m.id

    def review(self, plan: dict, critique, verification: dict, round_no: int) -> tuple[int, bool]:
        """Multi-agent debate: Research → Strategy → Critic → Verification → Chief decides."""
        chief, critic = self._emp("orchestrator"), self._emp("critic")
        research, verif, strat = (office.lead_of(self.db, d) for d in ("research", "verification", "strategy"))
        m = office.start_meeting(self.db, f"리뷰 회의 #{round_no}: 근거 검토", [chief, self.employee, critic, research, verif, strat],
                                 ["조사 결과 보고", "검증 결과", "비판 검토", "재조사 여부 결정"], self.task_id)
        v = verification
        office.say_in_meeting(self.db, m, research, f"주장 {v.get('total', 0)}건을 원문에서 추출했습니다.")
        office.say_in_meeting(self.db, m, verif, f"검증 결과 확인 {v.get('verified', 0)} · 부분 {v.get('partial', 0)} · 미확인 {v.get('unverified', 0)} · "
                                                 f"충돌 {v.get('contradicted', 0)} · 오래됨 {v.get('outdated', 0)} · 인용 불일치 {v.get('quote_not_found', 0)}")
        if not critique.issues:
            office.say_in_meeting(self.db, m, critic, "제가 찾은 중대한 문제는 없습니다.")
        for issue in critique.issues[:6]:
            office.say_in_meeting(self.db, m, critic, f"[{issue['question']}] {issue['message']}")
            if issue.get("suggestion"):
                office.say_in_meeting(self.db, m, strat if issue["severity"] == "low" else research, f"→ {issue['suggestion']}")
        if self.has_llm and critique.issues:
            text = self.llm_text("critique", "리뷰 회의에서 전략팀장으로서 비판 의견에 대한 반론 또는 수용 의견을 2문장으로 말하세요:\n" +
                                 "\n".join(i["message"] for i in critique.issues[:5]))
            if text:
                office.say_in_meeting(self.db, m, strat, text.strip()[:600])
        redo = (not critique.passed) and bool(critique.requery)
        decision = "추가 조사 후 재검증" if redo else "현재 근거로 문서 작성 진행 (미검증 항목은 한계 섹션에 명시)"
        office.say_in_meeting(self.db, m, chief, f"결정: {decision}.")
        actions = [{"description": f"재조사: {q}", "owner": research.name, "deadline": date.today().isoformat(), "status": "open"} for q in critique.requery[:4]] if redo else \
            [{"description": "보고서·발표자료 작성", "owner": office.lead_of(self.db, "writing").name, "deadline": date.today().isoformat(), "status": "in_progress"}]
        office.end_meeting(self.db, m, [decision], actions)
        return m.id, redo


def run_adhoc_meeting(db, title: str, agenda: list[str], participant_ids: list[int], task_id: int | None = None) -> int:
    """A meeting the CEO calls. Each participant speaks on each agenda item (LLM persona, or grounded rules)."""
    from app.core.models import Task
    from app.llm.base import LLMError
    from app.llm.router import get_router

    people = [p for p in (db.get(Employee, i) for i in participant_ids) if p]
    if not people:
        raise ValueError("no valid participants")
    m = office.start_meeting(db, title, people, agenda, task_id)
    router = get_router()
    transcript: list[str] = []
    for item in agenda:
        for p in people:
            line = None
            if router.available:
                ctx = f"현재 상태: {p.status_text}. 지금까지 발언:\n" + "\n".join(transcript[-8:])
                try:
                    line = router.complete("chat", f"회의 안건: {item}\n{ctx}\n\n{p.name} {p.title}로서 1~2문장으로 발언하세요. 모르는 사실은 지어내지 마세요.",
                                           system=f"You are {p.name}, {p.role}. {p.persona}", max_tokens=300).text.strip()
                except LLMError:
                    line = None
            if not line:
                t = db.get(Task, p.current_task_id) if p.current_task_id else None
                work = f"작업 #{t.id} ({t.current_step}, {t.progress:.0f}%)" if t else "현재 배정 작업 없음"
                line = f"[{item}] {p.role} 관점에서 검토하겠습니다. 제 현황: {work}."
            office.say_in_meeting(db, m, p, line)
            transcript.append(f"{p.name}: {line}")
    lead = next((p for p in people if p.is_lead), people[0])
    actions = [{"description": f"{item} — 후속 검토", "owner": lead.name, "deadline": (date.today() + timedelta(days=3)).isoformat(),
                "status": "open"} for item in agenda]
    office.end_meeting(db, m, [f"안건 ‘{a}’ 논의 완료" for a in agenda], actions)
    return m.id
