"""Model routing, plan parsing and hallucination guards around LLM output (fake provider, no network)."""
import json

import pytest

from app.agents.analysis import AnalysisAgent
from app.agents.orchestrator import OrchestratorAgent
from app.core.models import Claim, Source
from app.llm.base import LLMError, LLMResult, Tier, extract_json
from app.llm.router import ModelRouter


class FakeProvider:
    name = "fake"

    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def complete(self, *, system, messages, model, max_tokens, tier):
        self.calls.append({"model": model, "tier": tier, "system": system, "prompt": messages[0]["content"]})
        for key, reply in self.replies.items():
            if key in messages[0]["content"]:
                return LLMResult(text=reply, model=model)
        raise LLMError("no canned reply")


def test_router_picks_model_per_task_kind():
    r = ModelRouter(FakeProvider({}))
    assert r.route("chat").tier == Tier.FAST and r.route("chat").model == "claude-haiku-4-5"
    assert r.route("plan").tier == Tier.REASONING and r.route("plan").model == "claude-opus-5"
    assert r.route("code").tier == Tier.CODING
    assert r.route("extract_claims").tier == Tier.LONG_CONTEXT
    assert ModelRouter(None).route("plan").provider == "offline"


def test_untrusted_policy_always_in_system_prompt():
    fp = FakeProvider({"hello": "ok"})
    ModelRouter(fp).complete("chat", "hello", system="persona")
    assert "untrusted_document" in fp.calls[0]["system"]


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": [1,2]} done') == {"a": [1, 2]}
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_llm_plan_used_and_normalised(db):
    plan = {"mode": "research", "goal": "g", "topic": "t", "questions": ["q1"], "queries": ["a", "a", "b"],
            "deliverables": ["pptx", "exe"], "business": True, "subtasks": []}
    router = ModelRouter(FakeProvider({"Decompose": json.dumps(plan)}))
    out = OrchestratorAgent(db, router=router).plan("시장 조사해서 PPT 만들어줘")
    assert out["planner"] == "llm" and out["queries"] == ["a", "b"]
    assert out["deliverables"] == ["docx", "pptx", "xlsx"]  # invalid removed, report + evidence DB always added


def test_llm_failure_falls_back_to_heuristic(db):
    out = OrchestratorAgent(db, router=ModelRouter(FakeProvider({}))).plan("AI 교육 사업 아이디어를 조사해서 사업계획서 만들어줘")
    assert out["planner"] == "heuristic" and out["business"] is True and "docx" in out["deliverables"]


def test_unsupported_llm_facts_are_downgraded(db):
    """Hallucination detection: a FACT without valid evidence, or with numbers not in the cited claim, is not shown as FACT."""
    s = Source(title="s", url="https://x.go.kr", tier=1, accessed=True)
    db.add(s)
    db.commit()
    c = Claim(source_id=s.id, text="시장 규모는 2024년 1조원이다.", supporting_quote="시장 규모는 2024년 1조원이다.", verification_status="verified", confidence=0.9)
    db.add(c)
    db.commit()
    reply = {"sections": {"market": [
        {"text": "시장 규모는 2024년 1조원이다.", "label": "FACT", "claim_ids": [c.id]},
        {"text": "시장 규모는 2024년 7조원이다.", "label": "FACT", "claim_ids": [c.id]},
        {"text": "시장은 곧 두 배가 된다.", "label": "FACT", "claim_ids": [99999]},
    ]}, "swot": {}, "kpis": [], "roadmap": [],
        "assumptions": [{"key": "arpu", "value": 50000, "kind": "ASSUMPTION"}, {"key": "hack", "value": 1}]}
    router = ModelRouter(FakeProvider({"strategy & business team": json.dumps(reply)}))
    res = AnalysisAgent(db, router=router).analyze({"goal": "g", "business": True}, [c], {})
    labels = [(s.text, s.label) for s in res.sections["market"]]
    assert labels[0][1] == "FACT"
    assert labels[1][1] == "ANALYSIS"  # number 7 not in evidence
    assert labels[2][1] == "UNKNOWN"  # cites a non-existent claim
    assert res.generated_by == "llm"
    arpu = next(a for a in res.financial.assumptions if a.key == "arpu")
    assert arpu.value == 50000 and arpu.kind == "ASSUMPTION"
    assert res.financial.rows[0]["arpu"] == 50000  # numbers computed by the engine from the assumption
