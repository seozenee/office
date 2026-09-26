"""Direct messages between the CEO (user) and any employee.

With an LLM the employee answers in persona, grounded in their current work, recent team chat,
project knowledge-base hits and task state. Offline, the employee answers from real office data
(status, progress, sources, approvals) and can accept work orders, which become tasks.
"""
from __future__ import annotations

import re

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.models import Approval, Channel, Employee, Message, Source, Task
from app.core.security import wrap_untrusted
from app.knowledge.store import hybrid_search
from app.llm.base import LLMError
from app.llm.router import get_router
from app.office import service as office
from app.office.roster import DEPARTMENTS

WORK_ORDER = re.compile(r"(조사|분석|만들어|작성|정리|검증|찾아|리서치|보고서|ppt|발표|엑셀|research|make|write|analy[sz]e)", re.I)


def _recent_team_chat(db: Session, emp: Employee, limit: int = 12) -> list[Message]:
    cid = office.channel_id(db, "department", department=emp.department)
    return list(reversed(list(db.scalars(select(Message).where(Message.channel_id == cid).order_by(desc(Message.id)).limit(limit)))))


def _dm_history(db: Session, emp: Employee, limit: int = 10) -> list[Message]:
    cid = office.channel_id(db, "dm", employee_id=emp.id)
    return list(reversed(list(db.scalars(select(Message).where(Message.channel_id == cid).order_by(desc(Message.id)).limit(limit)))))


def handle_dm(db: Session, emp: Employee, text: str, *, project_id: int | None = None,
              create_task=None) -> tuple[Message, Message, int | None]:
    """Store the user's DM, produce the employee's reply. Returns (user_msg, reply_msg, created_task_id)."""
    cid = office.channel_id(db, "dm", employee_id=emp.id)
    user_msg = Message(channel_id=cid, sender_type="user", sender_id=None, recipient_id=emp.id, content=text, kind="chat")
    db.add(user_msg)
    db.commit()

    created_task_id = None
    wants_work = bool(WORK_ORDER.search(text)) and len(text) > 8 and not text.strip().endswith("?")
    if wants_work and create_task is not None:
        task = create_task(text, project_id)
        created_task_id = task.id
    reply = _llm_reply(db, emp, text, project_id, created_task_id) or _rule_reply(db, emp, text, created_task_id)
    reply_msg = Message(channel_id=cid, sender_type="employee", sender_id=emp.id, content=reply, kind="chat",
                        task_id=created_task_id)
    db.add(reply_msg)
    db.commit()
    return user_msg, reply_msg, created_task_id


def _context(db: Session, emp: Employee, text: str, project_id: int | None) -> str:
    parts = [f"현재 상태: {emp.status} — {emp.status_text}"]
    if emp.current_task_id:
        t = db.get(Task, emp.current_task_id)
        if t:
            parts.append(f"진행 중인 작업 #{t.id}: {t.title} ({t.status}, {t.progress:.0f}%, 단계: {t.current_step})")
    chat = _recent_team_chat(db, emp)
    if chat:
        parts.append("최근 팀 채널:\n" + "\n".join(f"- {m.content[:200]}" for m in chat))
    hits = hybrid_search(db, text, project_id=project_id, limit=4)
    if hits:
        parts.append(wrap_untrusted("\n".join(f"[{h.document_title} p.{h.page}] {h.text[:500]}" for h in hits), source="knowledge base"))
    return "\n\n".join(parts)


def _llm_reply(db: Session, emp: Employee, text: str, project_id: int | None, created_task_id: int | None) -> str | None:
    router = get_router()
    if not router.available:
        return None
    history = "\n".join(f"{'CEO' if m.sender_type == 'user' else emp.name}: {m.content}" for m in _dm_history(db, emp)[:-1])
    system = (f"You are {emp.name} ({emp.title}, {emp.role}) in the {DEPARTMENTS.get(emp.department, emp.department)} team "
              f"of the CEO's Personal AI Office. Persona: {emp.persona}\n"
              "Reply to the CEO's direct message briefly and concretely in Korean, in character. Use only the context "
              "given; if you don't know, say so (UNKNOWN). Never claim work was done unless the context shows it.")
    note = f"\n(이 요청은 작업 #{created_task_id}로 등록되어 오피스 전체가 착수했습니다. 그 사실을 알려주세요.)" if created_task_id else ""
    prompt = f"CONTEXT:\n{_context(db, emp, text, project_id)}\n\nDM HISTORY:\n{history or '(none)'}\n\nCEO: {text}{note}"
    try:
        return router.complete("chat", prompt, system=system, max_tokens=800).text.strip()
    except LLMError:
        return None


def _rule_reply(db: Session, emp: Employee, text: str, created_task_id: int | None) -> str:
    low = text.lower()
    if created_task_id:
        return (f"네, 대표님. 작업 #{created_task_id}로 등록했습니다. 강민준 실장님께 전달되어 킥오프 회의부터 시작합니다. "
                f"진행 상황은 오피스 채널과 작업 화면에서 실시간으로 보실 수 있습니다.")
    if re.search(r"안녕|hi|hello|반가", low):
        return f"안녕하세요 대표님, {DEPARTMENTS.get(emp.department, '')} {emp.name} {emp.title}입니다. {emp.role} 업무를 맡고 있습니다. 무엇을 도와드릴까요?"
    if re.search(r"뭐\s*해|진행|상황|어때|status|하고\s*있", low):
        if emp.current_task_id:
            t = db.get(Task, emp.current_task_id)
            if t:
                return f"지금 작업 #{t.id} ‘{t.title[:60]}’의 {t.current_step or '작업'} 단계를 하고 있습니다 (전체 {t.progress:.0f}%). 상태: {emp.status_text}"
        return f"현재는 대기 중입니다. 마지막 상태: {emp.status_text or '없음'}."
    if re.search(r"출처|자료|source|근거", low):
        srcs = list(db.scalars(select(Source).where(Source.accessed.is_(True)).order_by(desc(Source.id)).limit(5)))
        if not srcs:
            return "아직 원문을 확인한 출처가 없습니다."
        return "최근 원문 확인한 출처입니다:\n" + "\n".join(f"· {s.title[:70]} ({s.source_type}, {s.publication_date or '발행일 미상'})" for s in srcs)
    if re.search(r"결재|승인|approval", low):
        pend = list(db.scalars(select(Approval).where(Approval.status == "pending").limit(5)))
        if not pend:
            return "현재 대기 중인 결재는 없습니다."
        return "대기 중인 결재입니다:\n" + "\n".join(f"· #{a.id} {a.title}" for a in pend)
    chat = _recent_team_chat(db, emp, 3)
    recent = f" 최근 팀 소식: “{chat[-1].content[:120]}”" if chat else ""
    return (f"말씀 감사합니다. 지금은 LLM이 연결되지 않은 오프라인 모드라 자유 대화 답변은 제한적입니다. "
            f"‘진행 상황’, ‘출처’, ‘결재’를 물어보시거나 ‘…조사해줘’처럼 업무를 지시해 주시면 바로 처리하겠습니다.{recent}")


def dm_channel_messages(db: Session, emp: Employee, limit: int = 100) -> list[Message]:
    ch = db.scalar(select(Channel).where(Channel.kind == "dm", Channel.employee_id == emp.id))
    if ch is None:
        return []
    return list(reversed(list(db.scalars(select(Message).where(Message.channel_id == ch.id).order_by(desc(Message.id)).limit(limit)))))
