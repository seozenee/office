"""Permission system: risk levels, approval gate, 결재선 order, CEO decisions."""
import pytest

from app.core.models import Approval, RiskLevel
from app.office import service as office
from app.pipeline.services import decide_approval
from app.tools.registry import ApprovalRequired, ToolRegistry, ToolSpec, needs_user_approval


def test_risk_thresholds():
    assert not needs_user_approval(RiskLevel.LOW)
    assert not needs_user_approval(RiskLevel.MEDIUM)
    assert needs_user_approval(RiskLevel.HIGH)
    assert needs_user_approval(RiskLevel.CRITICAL)


def test_high_risk_tool_blocked_until_ceo_approves(db):
    calls = []
    reg = ToolRegistry()
    reg.register(ToolSpec("mail.send", "외부 이메일 발송", RiskLevel.HIGH, lambda to, body: calls.append((to, body)) or "sent"))
    reg.register(ToolSpec("calc", "계산", RiskLevel.LOW, lambda: 42))
    assert reg.execute(db, "calc", actor="t") == 42
    with pytest.raises(ApprovalRequired) as ei:
        reg.execute(db, "mail.send", actor="agent", to="a@b.c", body="hi")
    appr = ei.value.approval
    assert calls == [] and appr.requires_user and appr.risk_level == "HIGH"
    # an unapproved id cannot be reused
    with pytest.raises(ApprovalRequired):
        reg.execute(db, "mail.send", actor="agent", approval_id=appr.id, to="a@b.c", body="hi")
    appr.status = "approved"
    db.commit()
    assert reg.execute(db, "mail.send", actor="agent", approval_id=appr.id, to="a@b.c", body="hi") == "sent"
    assert calls == [("a@b.c", "hi")]


def test_approval_line_order_and_ceo_turn(db):
    staff = office.employee(db, "docx_writer")
    appr = office.request_approval(db, staff, "테스트 결재", action="report_submission", task_id=None, requires_user=True)
    names = [s["approver"] for s in appr.line]
    assert names[0].startswith("오지민") and names[1].startswith("강민준") and names[2] == "CEO"
    with pytest.raises(PermissionError):  # chief cannot stamp before the team lead
        office.stamp(db, appr, office.employee(db, "orchestrator"), True)
    with pytest.raises(PermissionError):  # CEO cannot jump the line either
        decide_approval(db, appr.id, True)
    office.stamp(db, appr, office.lead_of(db, "writing"), True, "ok")
    office.stamp(db, appr, office.employee(db, "orchestrator"), True, "ok")
    assert office.next_approver_is_user(appr)
    res = decide_approval(db, appr.id, True, "승인")
    assert res["status"] == "approved"
    assert db.get(Approval, appr.id).decided_at is not None


def test_rejection_stops_the_line(db):
    staff = office.employee(db, "slide_designer")
    appr = office.request_approval(db, staff, "반려 테스트", action="deck_submission", task_id=None)
    office.stamp(db, appr, office.lead_of(db, "design"), False, "근거 부족")
    assert appr.status == "rejected" and appr.decision_note == "근거 부족"


def test_critical_tool_via_api_creates_approval(client):
    r = client.post("/api/tools/files.delete/execute", json={"args": {"path": "nothing.txt"}})
    body = r.json()
    assert r.status_code == 200 and body["approval_required"] and body["approval"]["risk_level"] == "CRITICAL"
