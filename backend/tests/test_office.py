"""Pixel office: roster, DMs, meetings, briefings."""
from collections import Counter

from app.jobs.queue import drain


def test_every_department_has_three_or_more_staff(client):
    layout = client.get("/api/office/layout").json()
    counts = Counter(e["department"] for e in layout["employees"])
    assert set(counts) == set(layout["departments"])
    assert all(n >= 3 for n in counts.values())
    assert all(sum(e["is_lead"] for e in layout["employees"] if e["department"] == d) == 1 for d in counts)
    rooms = {r["key"] for r in layout["rooms"]}
    assert {"ceo", "meeting"} <= rooms and set(counts) <= rooms


def test_dm_status_question_offline(client):
    emp = client.get("/api/office/employees").json()[3]
    r = client.post(f"/api/office/dm/{emp['id']}", json={"text": "지금 뭐 하고 있어?"}).json()
    assert r["reply"]["sender_id"] == emp["id"] and r["task_id"] is None
    assert "대기" in r["reply"]["content"] or "작업" in r["reply"]["content"]
    history = client.get(f"/api/office/dm/{emp['id']}").json()
    assert [m["sender_type"] for m in history[-2:]] == ["user", "employee"]
    # DMs are private: not in the public office feed
    feed = client.get("/api/office/messages").json()
    assert not any(m["id"] == r["reply"]["id"] for m in feed)


def test_dm_work_order_creates_task(client):
    emp = next(e for e in client.get("/api/office/employees").json() if e["agent_type"] == "research_lead")
    r = client.post(f"/api/office/dm/{emp['id']}", json={"text": "AI 헬스케어 규제 동향을 조사해서 보고서로 정리해줘"}).json()
    assert r["task_id"]
    task = client.get(f"/api/tasks/{r['task_id']}").json()
    assert task["owner"].startswith("CEO→")


def test_ceo_called_meeting_minutes(client):
    emps = client.get("/api/office/employees").json()
    ids = [e["id"] for e in emps if e["is_lead"]][:4]
    assert client.post("/api/office/meetings", json={"title": "전략 점검", "agenda": ["Q4 우선순위", "리스크"], "participant_ids": ids}).status_code == 202
    drain()
    m = client.get("/api/office/meetings").json()[0]
    assert m["title"] == "전략 점검" and m["status"] == "ended"
    detail = client.get(f"/api/office/meetings/{m['id']}").json()
    assert len([x for x in detail["transcript"] if x["sender_type"] == "employee"]) == len(ids) * 2
    assert detail["action_items"] and {"owner", "deadline", "status"} <= set(detail["action_items"][0])


def test_briefings_generate_documents(client):
    d = client.post("/api/briefing/daily").json()
    assert "오늘의 우선순위" in d["markdown"] and "Gmail 미연결" in d["markdown"]
    w = client.post("/api/briefing/weekly").json()
    for h in ("완료", "진행 중", "차단/실패", "주요 결정", "다음 주 우선순위"):
        assert h in w["markdown"]


def test_memory_layers(client):
    assert client.post("/api/memory", json={"layer": "preference", "key": "보고서 톤", "value": "간결하게"}).status_code == 201
    assert client.post("/api/memory", json={"layer": "bogus", "key": "k", "value": "v"}).status_code == 400
    mem = client.get("/api/memory?layer=preference").json()
    assert mem[0]["origin"] == "explicit"


def test_plugins_report_configuration_honestly(client, monkeypatch):
    from app.plugins.base import PLUGINS

    for p in PLUGINS:
        for e in p.env:
            monkeypatch.delenv(e, raising=False)
    plugins = client.get("/api/plugins").json()
    assert {p["key"] for p in plugins} >= {"slack", "github", "notion", "gmail", "calendar", "drive", "dropbox", "discord", "sheets"}
    assert all(p["configured"] is False for p in plugins)
    risks = {a["name"]: a["risk"] for p in plugins for a in p["actions"]}
    assert risks["gmail.send"] == "HIGH" and risks["gmail.list"] == "LOW"
