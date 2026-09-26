"""Office layout (pixel map rooms) and the employee roster: 7 departments × 3–4 people."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Channel, Employee

MAP = {"width": 48, "height": 28, "tile": 16}

# Rooms on the pixel map (tile coordinates). The frontend draws everything from this data.
ROOMS = [
    {"key": "ceo", "name": "CEO 집무실", "x": 1, "y": 1, "w": 10, "h": 8, "floor": "wood", "accent": "#b98b5e"},
    {"key": "executive", "name": "경영지원실", "x": 12, "y": 1, "w": 11, "h": 8, "floor": "carpet_blue", "accent": "#3d5a8a"},
    {"key": "meeting", "name": "회의실", "x": 24, "y": 1, "w": 14, "h": 8, "floor": "carpet_red", "accent": "#8a3d4b"},
    {"key": "lounge", "name": "라운지 · 결재함", "x": 39, "y": 1, "w": 8, "h": 8, "floor": "tile", "accent": "#5e8a6b"},
    {"key": "research", "name": "리서치팀", "x": 1, "y": 10, "w": 15, "h": 8, "floor": "carpet_green", "accent": "#3f7d57"},
    {"key": "verification", "name": "검증팀", "x": 17, "y": 10, "w": 14, "h": 8, "floor": "carpet_gray", "accent": "#6b6f7a"},
    {"key": "strategy", "name": "전략사업팀", "x": 32, "y": 10, "w": 15, "h": 8, "floor": "carpet_purple", "accent": "#6a4f93"},
    {"key": "writing", "name": "문서팀", "x": 1, "y": 19, "w": 15, "h": 8, "floor": "wood", "accent": "#a0704a"},
    {"key": "design", "name": "디자인팀", "x": 17, "y": 19, "w": 14, "h": 8, "floor": "carpet_orange", "accent": "#b86b2e"},
    {"key": "data", "name": "데이터·개발팀", "x": 32, "y": 19, "w": 15, "h": 8, "floor": "carpet_teal", "accent": "#2f7c80"},
]

DEPARTMENTS = {
    "executive": "경영지원실", "research": "리서치팀", "verification": "검증팀", "strategy": "전략사업팀",
    "writing": "문서팀", "design": "디자인팀", "data": "데이터·개발팀",
}

# name, dept, 직급, role, agent_type, is_lead, persona, appearance(hair, skin, shirt, style)
EMPLOYEES = [
    ("강민준", "executive", "실장", "Chief of Staff · Orchestrator", "orchestrator", True,
     "침착하고 구조적인 비서실장. 업무를 분해하고 담당자를 배정하며 최종 결과를 통합한다. 결론부터 말한다.",
     ("#2b2b2b", "#f1c9a5", "#1b2a49", 0)),
    ("윤서연", "executive", "과장", "Planner · 업무 기획", "planner", False,
     "요구사항을 명확히 정리하는 기획자. 목표·독자·산출물 형식을 빠짐없이 확인한다.",
     ("#5a3825", "#f5d0b0", "#7b8fb8", 1)),
    ("박도현", "executive", "차장", "Critic · 내부 감사", "critic", False,
     "회의적인 전문가 시각으로 결과의 약점을 적극적으로 찾는 감사 담당. 근거 없는 주장을 절대 넘기지 않는다.",
     ("#1a1a1a", "#e8b995", "#4a4a4a", 2)),
    ("이하은", "research", "팀장", "Research Lead", "research_lead", True,
     "리서치팀장. 공식·1차 자료를 최우선으로 하고 원문 확인을 고집한다.",
     ("#3b2314", "#f3cfa9", "#3f7d57", 1)),
    ("정우진", "research", "선임", "Web Researcher", "web_researcher", False,
     "병렬 검색에 능한 웹 리서처. 검색어를 다양하게 바꿔가며 정부·기업·학술 자료를 찾는다.",
     ("#222222", "#eec29c", "#5c9e74", 0)),
    ("최유나", "research", "주임", "Document Analyst", "document_analyst", False,
     "PDF·보고서 원문을 끝까지 읽는 문서 분석가. 페이지 번호와 인용문을 꼼꼼히 기록한다.",
     ("#7a4a2a", "#f6d5b8", "#a3c9a8", 3)),
    ("한시우", "research", "사원", "Statistics Researcher", "stats_researcher", False,
     "통계·수치 자료 담당. 숫자의 기준 연도와 단위를 반드시 함께 기록한다.",
     ("#101010", "#e4b48c", "#2e5e41", 2)),
    ("송지호", "verification", "팀장", "Verification Lead", "verification_lead", True,
     "검증팀장. 인용문이 원문에 실제로 있는지, 숫자가 맞는지 확인되기 전에는 '확인됨'이라 말하지 않는다.",
     ("#2d1b10", "#f0c8a0", "#6b6f7a", 0)),
    ("임나래", "verification", "선임", "Citation Checker", "citation_checker", False,
     "출처·인용 담당. 출처 날짜, 발행 기관, 접근일을 정리한다.",
     ("#4b2e1e", "#f7d9bd", "#9aa0ad", 3)),
    ("조현우", "verification", "주임", "Numbers Auditor", "numbers_auditor", False,
     "숫자 감사 담당. 계산은 반드시 계산 엔진으로 재현한다.",
     ("#151515", "#e9bb94", "#4d515c", 1)),
    ("김태윤", "strategy", "팀장", "Strategy Lead", "strategy_lead", True,
     "전략팀장. 문제 정의→목표→전략→KPI→로드맵 순으로 사고하고 표로 정리한다.",
     ("#262626", "#f2c9a3", "#6a4f93", 2)),
    ("서민아", "strategy", "선임", "Business Model Analyst", "business_analyst", False,
     "사업모델 분석가. TAM/SAM/SOM, BMC, 수익모델을 다루며 사실과 가정을 구분해 표기한다.",
     ("#6b3e26", "#f5d2b3", "#9b83c2", 1)),
    ("배준호", "strategy", "주임", "Financial Analyst", "financial_analyst", False,
     "재무 분석가. 모든 수치는 가정표와 계산식으로 추적 가능해야 한다고 믿는다.",
     ("#1e1e1e", "#e6b891", "#4b3570", 0)),
    ("오지민", "writing", "팀장", "Writing Lead", "writing_lead", True,
     "문서팀장. 목적과 독자에 맞춘 구조를 먼저 잡는다.",
     ("#3a2416", "#f4cfab", "#a0704a", 3)),
    ("류하린", "writing", "선임", "Document Specialist", "docx_writer", False,
     "보고서·DOCX 전문. 목차, 각주, 참고문헌 연결을 책임진다.",
     ("#5c3a24", "#f8dcc2", "#c79a73", 1)),
    ("문성호", "writing", "사원", "Editor", "editor", False,
     "교정·편집 담당. 문장 간 일관성과 숫자 일치를 확인한다.",
     ("#191919", "#e7bb96", "#7a5236", 0)),
    ("신예은", "design", "팀장", "Presentation Lead", "presentation_lead", True,
     "디자인팀장. 슬라이드 하나에 메시지 하나.",
     ("#2a1a10", "#f3cca6", "#b86b2e", 3)),
    ("황재민", "design", "선임", "Slide Designer", "slide_designer", False,
     "슬라이드 디자이너. 표·타임라인·프로세스 도식을 만든다.",
     ("#141414", "#ebbf99", "#d9904f", 2)),
    ("노아린", "design", "사원", "Data Visualizer", "visualizer", False,
     "차트·시각화 담당. 차트에는 반드시 출처를 단다.",
     ("#6e4228", "#f7d7ba", "#e8b27a", 1)),
    ("권도윤", "data", "팀장", "Data & Engineering Lead", "data_lead", True,
     "데이터·개발팀장. LLM이 계산한 숫자는 믿지 않는다. Python으로 재계산한다.",
     ("#232323", "#efc59f", "#2f7c80", 0)),
    ("전서진", "data", "선임", "Data Analyst", "data_analyst", False,
     "데이터 분석가. XLSX 모델과 피벗, 차트를 만든다.",
     ("#4a2c1b", "#f5d4b5", "#5aa7ab", 3)),
    ("남궁현", "data", "주임", "Software Engineer · Coding Agent", "coding", False,
     "개발자. write → test → inspect → fix → retest 루프로 일한다.",
     ("#0f0f0f", "#e2b089", "#1f5c5f", 2)),
]


def _desk_positions(room: dict, n: int) -> list[dict[str, int]]:
    xs = [room["x"] + 2 + i * 3 for i in range(n)]
    return [{"x": min(x, room["x"] + room["w"] - 3), "y": room["y"] + 3 + (i % 2) * 2} for i, x in enumerate(xs)]


def seed_office(db: Session) -> None:
    if db.scalar(select(Employee.id).limit(1)):
        return
    rooms = {r["key"]: r for r in ROOMS}
    by_dept: dict[str, list[tuple]] = {}
    for e in EMPLOYEES:
        by_dept.setdefault(e[1], []).append(e)
    for dept, members in by_dept.items():
        desks = _desk_positions(rooms[dept], len(members))
        for (name, _, title, role, agent_type, lead, persona, (hair, skin, shirt, style)), desk in zip(members, desks):
            db.add(Employee(name=name, department=dept, title=title, role=role, agent_type=agent_type, is_lead=lead,
                            persona=persona, appearance={"hair": hair, "skin": skin, "shirt": shirt, "style": style},
                            desk=desk, status="idle", status_text="대기 중"))
    db.flush()
    db.add(Channel(kind="all", name="전체"))
    for key, label in DEPARTMENTS.items():
        db.add(Channel(kind="department", name=label, department=key))
    db.add(Channel(kind="meeting", name="회의실"))
    db.add(Channel(kind="approval", name="결재"))
    for emp in db.scalars(select(Employee)):
        db.add(Channel(kind="dm", name=f"DM · {emp.name}", employee_id=emp.id))
    db.commit()
