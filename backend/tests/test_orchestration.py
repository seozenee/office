from app.agents.orchestrator import OrchestratorAgent
from app.llm.router import ModelRouter


def _plan(db, text, has_docs=False):
    return OrchestratorAgent(db, router=ModelRouter(None)).plan(text, has_documents=has_docs)


def test_deliverable_detection(db):
    p = _plan(db, "이번 주 AI 관련 시장 변화를 조사하고 투자자에게 보여줄 PPT 만들어줘")
    assert p["deliverables"] == ["docx", "pptx", "xlsx"] and p["audience"] == "투자자"
    assert "PPT" not in p["topic"] and "만들어" not in p["topic"]
    assert p["mode"] == "research" and len(p["queries"]) >= 4


def test_verify_and_knowledge_modes(db):
    assert _plan(db, "이 PPT의 모든 숫자와 출처를 검증해줘", has_docs=True)["mode"] == "verify_document"
    assert _plan(db, "이 보고서를 읽고 핵심 내용을 정리해줘", has_docs=True)["mode"] == "knowledge"
    assert _plan(db, "이 보고서를 읽고 핵심 내용을 정리해줘", has_docs=False)["mode"] == "research"


def test_task_api_validation(client):
    assert client.post("/api/tasks", json={"request": " "}).status_code in (400, 422)
    assert client.post("/api/tasks", json={"request": "조사해줘", "project_id": 99999}).status_code == 400
    r = client.post("/api/presentations", json={"request": "양자컴퓨팅 동향 정리"})
    assert r.status_code == 201 and r.json()["plan"]["force_deliverables"] == ["pptx"]


def test_job_failure_is_recorded_not_hidden(db):
    from app.core.models import Job
    from app.jobs.queue import drain, enqueue

    job = enqueue(db, "research_task", {"task_id": 987654})
    drain()
    db.refresh(job)
    assert job.status == "failed" and "not found" in job.error
