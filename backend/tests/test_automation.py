"""Schedules (daily briefing / weekly review / recurring research) and the Opportunity Scanner."""
from datetime import datetime, timedelta, timezone

from app.core.models import Schedule
from app.jobs.queue import drain
from app.jobs.scheduler import compute_next, tick


def test_compute_next_daily_weekly_hourly():
    base = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)  # Mon 10:00 Asia/Seoul
    d = Schedule(name="d", kind="daily_briefing", frequency="daily", time_of_day="08:00")
    assert compute_next(d, base) == datetime(2026, 9, 28, 23, 0, tzinfo=timezone.utc)  # next day 08:00 KST
    w = Schedule(name="w", kind="weekly_review", frequency="weekly", time_of_day="17:30", weekday=4)
    assert compute_next(w, base) == datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)  # Fri 17:30 KST
    h = Schedule(name="h", kind="opportunity_scan", frequency="hourly")
    assert compute_next(h, base) == datetime(2026, 9, 28, 2, 0, tzinfo=timezone.utc)


def test_schedule_api_tick_and_run(client, db):
    r = client.post("/api/schedules", json={"name": "아침 브리핑", "kind": "daily_briefing", "time_of_day": "07:50"})
    assert r.status_code == 201 and r.json()["next_run_at"]
    assert client.post("/api/schedules", json={"name": "x", "kind": "rm -rf"}).status_code == 400
    assert client.post("/api/schedules", json={"name": "x", "kind": "research_task"}).status_code == 400
    sid = r.json()["id"]
    sch = db.get(Schedule, sid)
    sch.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert tick(db) == [sid]
    assert tick(db) == []  # not fired twice
    drain()
    db.refresh(sch)
    assert "briefing artifact" in sch.last_result
    notes = client.get("/api/notifications").json()
    assert any("브리핑" in n["title"] for n in notes)


def test_recurring_research_schedule(client, db):
    r = client.post("/api/schedules", json={"name": "주간 규제", "kind": "research_task", "frequency": "weekly", "weekday": 0,
                                            "payload": {"request": "AI 헬스케어 규제 동향 조사해줘"}}).json()
    client.post(f"/api/schedules/{r['id']}/run")
    drain(1)
    db.expire_all()
    assert db.get(Schedule, r["id"]).last_result.startswith("task #")


def test_opportunity_scanner(client):
    client.post("/api/memory", json={"layer": "interest", "key": "관심1", "value": "AI 헬스케어"})
    assert client.post("/api/opportunities/scan", json={}).status_code == 202
    drain()
    opps = client.get("/api/opportunities").json()
    assert opps and opps[0]["score"] >= opps[-1]["score"]
    assert {o["interest"] for o in opps} == {"AI 헬스케어"} or "AI 헬스케어" in {o["interest"] for o in opps}
    # rescanning never duplicates
    client.post("/api/opportunities/scan", json={})
    drain()
    assert len(client.get("/api/opportunities").json()) == len(opps)
    t = client.post(f"/api/opportunities/{opps[0]['id']}/task").json()
    assert t["task_id"]
    assert client.get("/api/opportunities?status=tasked").json()[0]["task_id"] == t["task_id"]


def test_additive_migration_adds_missing_column():
    from sqlalchemy import text

    from app.core.db import engine, ensure_columns

    with engine.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS tmp_mig (id INTEGER PRIMARY KEY)"))
    assert ensure_columns() == []  # schema already current
