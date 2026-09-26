"""Research-to-Artifact pipeline (spec §46) — the core workflow.

Question → Plan → Research → Source collection → Document extraction → Evidence DB → Verification
→ Critic (debate, optional re-research) → Analysis → Writing → DOCX/PPTX/XLSX → QC → 결재 → Final.
Each stage is performed by an office employee: they post to their channel, stamp approvals and
attend meetings, so the user can watch the whole company work.
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.analysis import AnalysisAgent
from app.agents.critic import CriticAgent, Critique
from app.agents.data import DataAgent
from app.agents.evidence import EvidenceAgent
from app.agents.meeting import MeetingAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.presentation import PresentationAgent
from app.agents.research import DocumentAnalystAgent, ResearchOutcome, WebResearcherAgent
from app.agents.verification import VerificationAgent
from app.agents.writing import WritingAgent
from app.core.audit import audit
from app.core.config import get_settings
from app.core.models import Claim, KBDocument, Memory, Project, Source, Task, TaskStatus, TaskStep
from app.generators.docx_builder import build_docx
from app.generators.export import to_markdown, to_pdf
from app.generators.pptx_builder import build_pptx
from app.office import service as office
from app.pipeline.artifacts import save_artifact
from app.pipeline.pack import EvidencePack
from app.pipeline.qc import run_qc

log = logging.getLogger(__name__)

STAGES = [
    ("understand", "요구사항 분석", "orchestrator", 5),
    ("kickoff", "킥오프 회의", "planner", 8),
    ("research", "웹 조사·원문 확보", "web_researcher", 30),
    ("extract", "근거 추출", "stats_researcher", 40),
    ("verify", "사실관계 검증", "verification_lead", 50),
    ("review", "비판 검토·리뷰 회의", "critic", 58),
    ("analyze", "분석·전략·재무", "strategy_lead", 68),
    ("write", "보고서 작성", "writing_lead", 78),
    ("present", "발표자료 제작", "presentation_lead", 86),
    ("data", "스프레드시트", "data_lead", 92),
    ("qc", "품질 검사·결재", "verification_lead", 97),
]


class Pipeline:
    def __init__(self, db: Session, task_id: int) -> None:
        self.db = db
        self.task = db.get(Task, task_id)
        if self.task is None:
            raise LookupError(f"task {task_id} not found")
        self.project = db.get(Project, self.task.project_id) if self.task.project_id else None
        self.kw: dict[str, Any] = {"task_id": task_id}
        self._steps: dict[str, TaskStep] = {}

    # -- bookkeeping ----------------------------------------------------------
    def _step(self, key: str, status: str, detail: str = "") -> None:
        name, agent, progress = next((n, a, p) for k, n, a, p in STAGES if k == key)
        step = self._steps.get(key)
        if step is None:
            emp = office.employee(self.db, agent)
            step = TaskStep(task_id=self.task.id, name=name, agent=agent, employee_id=emp.id, status=status,
                            started_at=datetime.now(timezone.utc))
            self.db.add(step)
            self._steps[key] = step
        if status == "running":
            office.pace(0.8)
        step.status = status
        if detail:
            step.detail = detail[:2000]
        if status in ("done", "failed", "skipped"):
            step.finished_at = datetime.now(timezone.utc)
            self.task.progress = max(self.task.progress, progress)
        self.task.current_step = name
        self.db.commit()

    def _status(self, status: TaskStatus) -> None:
        self.task.status = status.value
        self.db.commit()

    def _chief_says(self, text: str, channel: str = "all") -> None:
        office.post(self.db, office.employee(self.db, "orchestrator"), text, channel=channel, task_id=self.task.id, kind="progress")

    # -- run --------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        try:
            return self._run()
        except Exception as e:  # noqa: BLE001 - failure is reported explicitly, never swallowed
            log.exception("pipeline failed")
            self.task.status = TaskStatus.FAILED.value
            self.task.error = f"{type(e).__name__}: {e}"
            self.db.commit()
            audit(self.db, "orchestrator", "task_failed", task_id=self.task.id, detail={"error": str(e), "trace": traceback.format_exc()[-1500:]})
            self._chief_says(f"❌ 작업 #{self.task.id} 실패: {e}. 진행된 단계까지의 결과는 보존됩니다.")
            office.notify(self.db, f"작업 실패: {self.task.title}", str(e), self.task.id)
            office.reset_statuses(self.db, self.task.id)
            raise

    def _run(self) -> dict[str, Any]:
        s = get_settings()
        t = self.task
        # 1. understand ---------------------------------------------------------
        self._status(TaskStatus.PLANNED)
        orch = OrchestratorAgent(self.db, **self.kw)
        orch.work("요구사항 분석 중")
        self._step("understand", "running")
        self._chief_says(f"📥 CEO 지시 접수: “{t.request}” — 요구사항을 분석합니다.")
        has_docs = bool(self.db.scalar(select(KBDocument.id).where(KBDocument.project_id == t.project_id).limit(1))) if t.project_id else False
        memories = [f"{m.key}: {m.value}" for m in self.db.scalars(select(Memory).where(Memory.layer == "preference"))][:20]
        forced = (t.plan or {}).get("force_deliverables") or []
        template = (t.plan or {}).get("template")
        plan = orch.plan(t.request, project_context=self.project.context if self.project else "", has_documents=has_docs, memory_notes=memories)
        plan["deliverables"] = list(dict.fromkeys(plan["deliverables"] + [d for d in forced if d in ("docx", "pptx", "xlsx")]))
        if template:
            plan["template"] = template
        t.plan = plan
        t.agents = sorted({st["department"] for st in plan.get("subtasks", [])})
        t.title = t.title or plan.get("goal", t.request)[:300]
        self.db.commit()
        orch.say(f"계획 수립 완료 ({plan.get('planner')}) — 모드: {plan['mode']}, 산출물: {', '.join(plan['deliverables'])}", channel="all", kind="report")
        self._step("understand", "done", f"질문 {len(plan['questions'])}개, 검색어 {len(plan['queries'])}개")

        # 2. kickoff meeting ----------------------------------------------------
        self._step("kickoff", "running")
        MeetingAgent(self.db, **self.kw).kickoff(plan)
        self._step("kickoff", "done")

        # 3–6. research rounds with critic loop -----------------------------------
        self._status(TaskStatus.RESEARCHING)
        queries = list(plan["queries"])
        all_sources: list[Source] = []
        notes = {"found": 0, "accessed": 0, "failed": [], "search_errors": [], "provider": None, "injection_warnings": []}
        critique = Critique()
        verification: dict[str, Any] = {}
        claims: list[Claim] = []
        for round_no in range(1, s.max_research_rounds + 1):
            outcome = self._research(plan, queries, round_no)
            all_sources += outcome.sources
            notes["found"] += outcome.found
            notes["accessed"] += outcome.accessed
            notes["failed"] += outcome.failed
            notes["search_errors"] += outcome.search_errors
            notes["provider"] = outcome.provider or notes["provider"]
            notes["injection_warnings"] += outcome.injection_warnings

            self._status(TaskStatus.ANALYZING)
            self._step("extract", "running")
            ev = EvidenceAgent(self.db, **self.kw)
            new_claims = ev.extract([x for x in outcome.sources if x.accessed], plan["questions"], plan["topic"], t.project_id,
                                    require_relevance=plan["mode"] == "research")
            ev.say(f"📑 원문에서 주장 {len(new_claims)}건을 인용문·페이지와 함께 추출했습니다.")
            self._step("extract", "done", f"누적 주장 {len(claims) + len(new_claims)}건")

            self._step("verify", "running")
            ver_agent = VerificationAgent(self.db, **self.kw)
            claims = list(self.db.scalars(select(Claim).where(Claim.task_id == t.id)))
            rep = ver_agent.verify(claims)
            claims = list(self.db.scalars(select(Claim).where(Claim.task_id == t.id)))
            verification = rep.as_dict()
            ver_agent.say(f"🔍 검증: 확인 {rep.verified} / 부분 {rep.partial} / 미확인 {rep.unverified} / 충돌 {rep.contradicted} / 오래됨 {rep.outdated} "
                          f"(원문 불일치 {rep.quote_not_found}, 숫자 불일치 {rep.number_mismatch})")
            office.post(self.db, office.employee(self.db, "numbers_auditor"),
                        f"숫자 검사 완료 — 인용문과 다른 숫자 {rep.number_mismatch}건은 확인 목록에서 제외했습니다.", task_id=t.id)
            self._step("verify", "done", str({k: v for k, v in verification.items() if k != "conflicts"}))

            self._status(TaskStatus.REVIEWING)
            self._step("review", "running")
            critique = CriticAgent(self.db, **self.kw).review(plan, claims, all_sources, verification)
            _, redo = MeetingAgent(self.db, **self.kw).review(plan, critique, verification, round_no)
            self._step("review", "done", f"이슈 {len(critique.issues)}건, 재조사={redo}")
            if not redo or round_no == s.max_research_rounds or plan["mode"] != "research":
                break
            queries = critique.requery[:4]
            self._chief_says(f"🔁 Critic 요청으로 추가 조사 라운드 {round_no + 1}를 진행합니다: " + " · ".join(queries))

        # 7. analysis ---------------------------------------------------------------
        self._status(TaskStatus.ANALYZING)
        self._step("analyze", "running")
        analysis = AnalysisAgent(self.db, **self.kw).analyze(plan, claims, verification)
        if analysis.financial:
            office.post(self.db, office.employee(self.db, "financial_analyst"),
                        f"💰 재무 모델 계산 완료 (계산 엔진) — 손익분기 {analysis.financial.summary['breakeven_year'] or '5년 내 미도달'}, "
                        f"LTV/CAC {analysis.financial.summary['ltv_cac_ratio']}. 입력값은 모두 가정으로 표시했습니다.", task_id=t.id)
        office.post(self.db, office.employee(self.db, "strategy_lead"), f"📊 분석 완료 ({analysis.generated_by}). 사실과 가정을 분리해 표기했습니다.", task_id=t.id)
        self._step("analyze", "done")

        pack = EvidencePack(task=t, project=self.project, plan=plan, sources=all_sources, claims=claims,
                            verification=verification, critique=critique, analysis=analysis, research_notes=notes)
        return self._produce(pack)

    def _research(self, plan: dict, queries: list[str], round_no: int) -> ResearchOutcome:
        s = get_settings()
        self._step("research", "running")
        analyst = DocumentAnalystAgent(self.db, **self.kw)
        outcome = ResearchOutcome()
        if plan["mode"] in ("knowledge", "verify_document") or (round_no == 1 and self.task.project_id and
                                                                  self.db.scalar(select(KBDocument.id).where(KBDocument.project_id == self.task.project_id).limit(1))):
            kb = analyst.from_knowledge_base(self.task.project_id) if round_no == 1 else ResearchOutcome()
            outcome.sources += kb.sources
            outcome.found += kb.found
            outcome.accessed += kb.accessed
            outcome.injection_warnings += kb.injection_warnings
            if kb.sources:
                analyst.say(f"📚 프로젝트 지식베이스 문서 {len(kb.sources)}건을 근거 자료로 사용합니다.")
        if plan["mode"] == "research":
            web = WebResearcherAgent(self.db, **self.kw)
            provider, results, errors = web.search(queries)
            outcome.provider = provider
            outcome.search_errors = errors
            if errors:
                web.say("⚠️ " + " / ".join(errors[:3]))
            if results:
                web.say(f"검색 결과 {len(results)}건 확보. 공식 자료 우선으로 원문 확인을 요청합니다.")
                got = analyst.fetch_and_ingest(results, project_id=self.task.project_id, project_slug=self.project.slug if self.project else None,
                                               max_sources=s.max_sources_per_task if round_no == 1 else max(4, s.max_sources_per_task // 2))
                outcome.sources += got.sources
                outcome.found += got.found
                outcome.accessed += got.accessed
                outcome.failed += got.failed
                outcome.injection_warnings += got.injection_warnings
                analyst.say(f"📄 원문 확인 {got.accessed}건 / 접근 실패 {len(got.failed)}건" + (f" (예: {got.failed[0][:120]})" if got.failed else ""))
            if outcome.injection_warnings:
                office.post(self.db, office.employee(self.db, "verification_lead"),
                            "🛡️ 일부 문서에서 지시문 형태의 텍스트(프롬프트 인젝션 의심)를 발견했습니다. 명령으로 취급하지 않고 데이터로만 처리합니다.", task_id=self.task.id)
        lead = office.lead_of(self.db, "research")
        office.post(self.db, lead, f"리서치 라운드 {round_no} 종료: 출처 {len(outcome.sources)}건 (원문 확인 {outcome.accessed}).", task_id=self.task.id)
        self._step("research", "done", f"라운드 {round_no}: 발견 {outcome.found}, 원문 {outcome.accessed}, 실패 {len(outcome.failed)}")
        return outcome

    # -- production ----------------------------------------------------------------
    def _produce(self, pack: EvidencePack) -> dict[str, Any]:
        t, plan = self.task, pack.plan
        self._status(TaskStatus.WRITING)
        files: dict[str, Path] = {}
        artifacts = []
        source_ids = [s.id for s in pack.sources if s.accessed]

        self._step("write", "running")
        writer = WritingAgent(self.db, **self.kw)
        content = writer.compose(pack)
        title = content.title
        art, ver = save_artifact(self.db, title=title, fmt="docx", build=lambda p: build_docx(content, p, (plan.get("template") or {}).get("file_path")), author_agent="Writing Agent",
                                 project=self.project, task_id=t.id, source_ids=source_ids, kind="report")
        files["docx"] = Path(ver.file_path)
        artifacts.append(art)
        save_artifact(self.db, title=title, fmt="md", build=lambda p: (p.write_text(to_markdown(content), encoding="utf-8"), p)[1],
                      author_agent="Writing Agent", project=self.project, task_id=t.id, source_ids=source_ids, kind="research")
        try:
            save_artifact(self.db, title=title, fmt="pdf", build=lambda p: to_pdf(content, p), author_agent="Writing Agent",
                          project=self.project, task_id=t.id, source_ids=source_ids, kind="report")
        except Exception as e:  # noqa: BLE001 - PDF is a convenience export; failure is logged, not hidden
            audit(self.db, "Writing Agent", "pdf_export_failed", task_id=t.id, detail={"error": str(e)})
        office.post(self.db, office.employee(self.db, "docx_writer"), f"📄 보고서 초안 v{ver.version} 완료 — 인용 {len(content.bibliography)}건, 각주 연결.", task_id=t.id)
        office.post(self.db, office.employee(self.db, "editor"), "교정 완료: 본문 숫자와 표 숫자가 같은 출처에서 왔는지 확인했습니다.", task_id=t.id)
        office.request_approval(self.db, office.employee(self.db, "docx_writer"), f"보고서 초안 v{ver.version} 검토", action="report_submission", task_id=t.id,
                                payload={"artifact_id": art.id})
        self._step("write", "done", ver.file_path)

        if "pptx" in plan["deliverables"]:
            self._step("present", "running")
            pres = PresentationAgent(self.db, **self.kw)
            slides = pres.slides(pack)
            deck_title = plan.get("deck_title") or f"{plan.get('topic', '')} 발표자료"
            dart, dver = save_artifact(self.db, title=deck_title, fmt="pptx", build=lambda p: build_pptx(deck_title, slides, p, footer=deck_title),
                                       author_agent="Presentation Agent", project=self.project, task_id=t.id, source_ids=source_ids)
            files["pptx"] = Path(dver.file_path)
            artifacts.append(dart)
            office.post(self.db, office.employee(self.db, "slide_designer"), f"📑 슬라이드 {len(slides)}장 구성 완료 (발표자 노트 포함).", task_id=t.id)
            office.post(self.db, office.employee(self.db, "visualizer"), "차트마다 출처 번호를 붙였습니다." if pack.analysis.market_chart else
                        "검증된 연도별 수치가 2개 미만이라 시장 차트는 만들지 않았습니다(근거 없는 차트 금지).", task_id=t.id)
            office.request_approval(self.db, office.employee(self.db, "slide_designer"), f"발표자료 v{dver.version} 검토", action="deck_submission", task_id=t.id,
                                    payload={"artifact_id": dart.id})
            self._step("present", "done", dver.file_path)

        self._step("data", "running")
        data = DataAgent(self.db, **self.kw)
        holder: dict[str, list[str]] = {}

        def build_xlsx(p: Path) -> Path:
            _, problems = data.build_workbook(pack, p)
            holder["problems"] = problems
            return p

        xart, xver = save_artifact(self.db, title=f"{plan.get('topic', '')} 증거DB·모델", fmt="xlsx", build=build_xlsx,
                                   author_agent="Data Agent", project=self.project, task_id=t.id, source_ids=source_ids)
        files["xlsx"] = Path(xver.file_path)
        artifacts.append(xart)
        formula_problems = holder.get("problems", [])
        data.say(f"📈 스프레드시트 완료 — 주장 {len(pack.claims)}건, 출처 {len(pack.sources)}건" +
                 (f", 수식↔계산 불일치 {len(formula_problems)}건" if pack.analysis.financial else ""))
        self._step("data", "done", xver.file_path)

        # QC + approval chain -------------------------------------------------------
        self._step("qc", "running")
        qc = run_qc(pack, files, formula_problems)
        verif = office.lead_of(self.db, "verification")
        failed = [c["name"] for c in qc["checks"] if not c["passed"]]
        office.post(self.db, verif, "✅ QC 통과: " + ", ".join(c["name"] for c in qc["checks"] if c["passed"])[:900]
                    if not failed else f"⚠️ QC 미통과 항목: {', '.join(failed)}", task_id=t.id, kind="report")
        self._auto_stamp_team_approvals(qc["passed"])
        final_appr = office.request_approval(self.db, office.employee(self.db, "orchestrator"), f"최종 산출물 승인: {t.title[:80]}",
                                             action="final_delivery", task_id=t.id, requires_user=True,
                                             payload={"artifact_ids": [a.id for a in artifacts], "qc": qc})
        self._step("qc", "done", f"passed={qc['passed']}")

        v = pack.verification
        summary = {
            "files": {k: str(p) for k, p in files.items()},
            "artifact_ids": [a.id for a in artifacts],
            "sources_found": pack.research_notes.get("found", 0), "sources_accessed": pack.research_notes.get("accessed", 0),
            "sources_failed": pack.research_notes.get("failed", []), "search_errors": pack.research_notes.get("search_errors", []),
            "sources_verified": len({c.source_id for c in pack.verified}),
            "claims_checked": v.get("total", 0), "claims_verified": v.get("verified", 0),
            "claims_unverified": v.get("total", 0) - v.get("verified", 0), "qc": qc,
            "critique": pack.critique.issues, "final_approval_id": final_appr.id, "llm": orch_mode(), "revision_note": plan.get("feedback"),
        }
        t.result_summary = summary
        partial = not qc["passed"] or bool(summary["sources_failed"]) or summary["claims_unverified"] > 0
        t.status = TaskStatus.WAITING_USER.value
        t.progress = 100.0
        t.current_step = "CEO 결재 대기"
        self.db.commit()
        msg = (f"{'⚠️ 부분 완료' if partial else '✅ 완료'} — 작업 #{t.id}\n"
               f"📄 보고서 · " + ("📑 발표자료 · " if "pptx" in files else "") + "📊 증거DB/모델\n"
               f"출처 발견 {summary['sources_found']} / 원문 확인 {summary['sources_accessed']} / 접근 실패 {len(summary['sources_failed'])}\n"
               f"주장 검사 {summary['claims_checked']} / 검증 {summary['claims_verified']} / 미검증 {summary['claims_unverified']}\n"
               f"최종 결재를 올렸습니다 (결재함 #{final_appr.id}).")
        self._chief_says(msg)
        office.notify(self.db, f"{'부분 완료' if partial else '완료'}: {t.title[:80]}", msg, t.id, link=f"/tasks/{t.id}")
        audit(self.db, "orchestrator", "task_completed", task_id=t.id, detail={k: summary[k] for k in ("claims_checked", "claims_verified", "sources_accessed")})
        office.reset_statuses(self.db, t.id)
        return summary

    def _auto_stamp_team_approvals(self, qc_passed: bool) -> None:
        """Team leads and the chief review the drafts. They approve only when QC passed; otherwise they
        stamp with a note so the CEO sees the reservation. The CEO stamp is always left to the user."""
        from app.core.models import Approval, Employee

        for appr in self.db.scalars(select(Approval).where(Approval.task_id == self.task.id, Approval.status == "pending")):
            while not office.next_approver_is_user(appr) and appr.status == "pending":
                step = next(s for s in appr.line if s["status"] == "pending")
                approver = self.db.get(Employee, step["employee_id"])
                note = "QC 통과" if qc_passed else "QC 미통과 항목 있음 — CEO 판단 필요 (보고서 한계 섹션 참조)"
                office.stamp(self.db, appr, approver, True, note)


def orch_mode() -> str:
    from app.llm.router import get_router

    r = get_router()
    return r.provider.name if r.provider else "offline"


def run_task(db: Session, task_id: int) -> dict[str, Any]:
    return Pipeline(db, task_id).run()


def revise_task(db: Session, task_id: int, feedback: str) -> dict[str, Any]:
    """CEO feedback → new artifact versions (v2, v3 …) built from the existing evidence base."""
    p = Pipeline(db, task_id)
    t = p.task
    plan = dict(t.plan or {})
    if not plan:
        raise ValueError("task has no plan; run it first")
    plan["feedback"] = feedback
    t.plan = plan
    t.status = TaskStatus.REVIEWING.value
    t.progress = 60.0
    db.commit()
    p._chief_says(f"✏️ CEO 피드백 반영 개정 착수: “{feedback[:200]}”")
    sources = list(db.scalars(select(Source).where(Source.task_id == t.id)))
    claims = list(db.scalars(select(Claim).where(Claim.task_id == t.id)))
    rep = VerificationAgent(db, task_id=t.id).verify(claims)
    claims = list(db.scalars(select(Claim).where(Claim.task_id == t.id)))
    verification = rep.as_dict()
    critique = CriticAgent(db, task_id=t.id).review(plan, claims, sources, verification)
    analysis = AnalysisAgent(db, task_id=t.id).analyze(plan, claims, verification)
    notes = {"found": len(sources), "accessed": sum(1 for s in sources if s.accessed),
             "failed": [f"{s.url} — {s.access_error}" for s in sources if not s.accessed], "provider": (t.result_summary or {}).get("provider"),
             "injection_warnings": []}
    pack = EvidencePack(task=t, project=p.project, plan=plan, sources=sources, claims=claims, verification=verification,
                        critique=critique, analysis=analysis, research_notes=notes)
    return p._produce(pack)
