"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Avatar from "@/components/ui/Avatar";
import CitationCard from "@/components/ui/CitationCard";
import Page from "@/components/ui/Page";
import ApprovalLine from "@/components/ui/Stamp";
import MessageItem from "@/components/office/MessageItem";
import { useOffice } from "@/components/OfficeProvider";
import { api, fileUrl } from "@/lib/api";
import { KIND_KO, STATUS_KO, TIER_KO, VERIF_KO, bar } from "@/lib/labels";
import type { AuditEntry, CitationCard as Card, Claim, Source, Task } from "@/lib/types";

const TABS = ["결과", "근거·검증", "출처", "회의록", "대화", "감사 로그"] as const;

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const { messages, empById, tasks: live } = useOffice();
  const [task, setTask] = useState<Task | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [cards, setCards] = useState<Card[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [tab, setTab] = useState<(typeof TABS)[number]>("결과");
  const [card, setCard] = useState<Card | null>(null);
  const [feedback, setFeedback] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    const [t, c, s, cc, a] = await Promise.all([
      api<Task>(`/api/tasks/${id}`), api<Claim[]>(`/api/claims?task_id=${id}`), api<Source[]>(`/api/sources?task_id=${id}`),
      api<Card[]>(`/api/citations/${id}`), api<AuditEntry[]>(`/api/tasks/${id}/audit`),
    ]);
    setTask(t); setClaims(c); setSources(s); setCards(cc); setAudit(a);
  }, [id]);
  const liveTask = live.find((t) => String(t.id) === id);
  useEffect(() => { load().catch((e) => setMsg(e.message)); }, [load, liveTask?.status, liveTask?.progress]);

  if (!task) return <Page title={`작업 #${id}`}><p>{msg || "불러오는 중…"}</p></Page>;
  const rs = task.result_summary || {};
  const finalAppr = task.approvals?.find((a) => a.action === "final_delivery" && a.status === "pending");
  const cardForSource = (sid: number | null) => cards.find((c) => c.source_id === sid);
  const partial = rs.qc && (!rs.qc.passed || (rs.sources_failed || []).length || rs.claims_unverified);

  const decide = async (approvalId: number, approve: boolean) => {
    try {
      await api(`/api/approvals/${approvalId}/decide`, { method: "POST", json: { approve, note } });
      setNote(""); setMsg(approve ? "승인했습니다. 최종본이 final 폴더에 보관됩니다." : "반려했습니다. 사유가 있으면 개정 작업이 시작됩니다.");
      load();
    } catch (e: any) { setMsg(e.message); }
  };
  const revise = async () => {
    if (!feedback.trim()) return;
    await api(`/api/tasks/${id}/revise`, { method: "POST", json: { feedback } });
    setFeedback(""); setMsg("개정 작업을 시작했습니다. 새 버전(v2…)이 생성됩니다.");
  };

  return (
    <Page title={`#${task.id} ${task.title}`} subtitle={task.request}>
      <div className="px-panel p-3 flex items-center gap-4 flex-wrap">
        <span className="px-tag bg-accent text-ink">{STATUS_KO[task.status]}</span>
        <span className="font-pixel text-mint">{bar(task.progress, 20)}</span><span>{Math.round(task.progress)}%</span>
        <span className="text-cream/70">{task.current_step}</span>
        {task.plan?.planner && <span className="text-[11px] text-cream/50">계획: {task.plan.planner} · 모드: {task.plan.mode} · LLM: {rs.llm || "-"}</span>}
        {task.status === "FAILED" && <button className="px-btn-danger ml-auto" onClick={() => api(`/api/tasks/${id}/retry`, { method: "POST" }).then(load)}>다시 시도</button>}
      </div>
      {task.error && <div className="px-panel p-3 text-rose">❌ {task.error}</div>}
      {msg && <div className="px-panel-2 p-2">{msg}</div>}

      <div className="px-panel p-3">
        <div className="text-[11px] text-cream/60 mb-2">워크플로</div>
        <div className="flex flex-wrap gap-2">
          {(task.steps || []).map((s) => (
            <div key={s.id} className={`px-panel-2 p-2 w-40 text-[12px] ${s.status === "running" ? "ring-2 ring-accent" : ""}`} title={s.detail}>
              <div className="flex items-center gap-2"><Avatar employee={empById(s.employee_id)} size={22} /><b className="truncate">{s.name}</b></div>
              <div className="mt-1 text-cream/60">{s.status === "done" ? "✅ 완료" : s.status === "running" ? "⏳ 진행 중" : s.status === "failed" ? "❌ 실패" : "대기"} · {empById(s.employee_id)?.name}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-1 flex-wrap">{TABS.map((t) => <button key={t} className={tab === t ? "px-btn" : "px-btn-ghost"} onClick={() => setTab(t)}>{t}</button>)}</div>

      {tab === "결과" && (
        <div className="grid lg:grid-cols-2 gap-4">
          <div className="px-panel p-4">
            <div className="px-title mb-2">{rs.qc ? (partial ? "⚠️ Research partially completed." : "✅ Completed.") : "진행 중…"}</div>
            {rs.qc && (
              <pre className="font-body whitespace-pre-wrap text-[13px] leading-relaxed">
{`📄 Research Report${task.artifacts?.some((a) => a.kind === "presentation") ? "\n📑 Presentation" : ""}
📊 Evidence DB / Model
${rs.sources_found} sources found.
${rs.sources_accessed} original documents read.
${(rs.sources_failed || []).length} sources could not be accessed.
Sources verified: ${rs.sources_verified}
Claims checked: ${rs.claims_checked}
Unverified claims: ${rs.claims_unverified}`}
              </pre>
            )}
            {(rs.search_errors || []).length > 0 && <div className="text-rose text-[12px] mt-2">검색 오류: {rs.search_errors.join(" / ")}</div>}
            {partial && <p className="mt-2 text-accent">Would you like me to continue? — 아래에 피드백을 입력하면 개정본을 만듭니다.</p>}
            <div className="mt-3 flex gap-2">
              <input className="px-input flex-1" value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="수정 요청 / 추가 지시 (새 버전 생성)" />
              <button className="px-btn-ghost" onClick={revise}>개정 요청</button>
            </div>
          </div>
          <div className="px-panel p-4">
            <div className="px-title mb-2">산출물</div>
            {(task.artifacts || []).map((a) => (
              <div key={a.id} className="px-panel-2 p-2 mb-2">
                <div className="flex items-center gap-2"><b>{a.kind === "presentation" ? "📑" : a.kind === "spreadsheet" ? "📊" : "📄"} {a.title}</b>
                  <span className="px-tag bg-ink">{a.versions[0]?.format}</span><span className="px-tag bg-ink">{a.status}</span></div>
                <div className="flex flex-wrap gap-2 mt-1 text-[12px]">
                  {a.versions.map((v) => <a key={v.id} className="underline text-sky" href={fileUrl(`/api/artifacts/${a.id}/download?version_id=${v.id}`)}>{v.label} ({Math.round(v.size_bytes / 1024)}KB)</a>)}
                  {["pdf", "md", "csv"].filter((f) => f !== a.versions[0]?.format && (f !== "csv" || a.kind === "spreadsheet")).map((f) => (
                    <a key={f} className="underline text-cream/70" href={fileUrl(`/api/artifacts/${a.id}/export?format=${f}`)}>→{f.toUpperCase()}</a>
                  ))}
                </div>
              </div>
            ))}
            {(task.approvals || []).map((ap) => (
              <div key={ap.id} className="mt-3">
                <div className="text-[12px] mb-1">결재 #{ap.id} · {ap.title} · <b>{ap.status}</b></div>
                <ApprovalLine line={ap.line} />
              </div>
            ))}
            {finalAppr && finalAppr.line.find((s) => s.status === "pending")?.employee_id === null && (
              <div className="mt-3 px-panel-2 p-3">
                <div className="text-accent mb-1">CEO 최종 결재</div>
                <input className="px-input w-full mb-2" value={note} onChange={(e) => setNote(e.target.value)} placeholder="결재 의견 (반려 시 개정 지시로 사용)" />
                <div className="flex gap-2"><button className="px-btn" onClick={() => decide(finalAppr.id, true)}>승인 (도장)</button><button className="px-btn-danger" onClick={() => decide(finalAppr.id, false)}>반려</button></div>
              </div>
            )}
          </div>
          {rs.qc && (
            <div className="px-panel p-4 lg:col-span-2">
              <div className="px-title mb-2">품질 검사 (QC)</div>
              <div className="grid md:grid-cols-2 gap-1 text-[12.5px]">
                {rs.qc.checks.map((c: any) => <div key={c.name}>{c.passed ? "☑" : "☐"} <b>{c.name}</b> <span className="text-cream/60">— {c.detail}</span></div>)}
              </div>
              {(rs.critique || []).length > 0 && <>
                <div className="px-title mt-3 mb-1">Critic Agent 지적 사항</div>
                {rs.critique.map((i: any, k: number) => <div key={k} className="text-[12.5px]">[{i.severity}] {i.question} — {i.message} <span className="text-cream/60">→ {i.suggestion}</span></div>)}
              </>}
            </div>
          )}
        </div>
      )}

      {tab === "근거·검증" && (
        <div className="px-panel overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead className="bg-ink"><tr>{["구분", "주장", "검증", "신뢰도", "출처", "p.", "메모"].map((h) => <th key={h} className="text-left p-2">{h}</th>)}</tr></thead>
            <tbody>
              {claims.map((c) => {
                const k = KIND_KO[c.kind] || [c.kind, ""]; const v = VERIF_KO[c.verification_status] || [c.verification_status, "bg-line"];
                const cardRef = cardForSource(c.source_id);
                return (
                  <tr key={c.id} className="border-t border-black/40 align-top">
                    <td className={`p-2 ${k[1]}`}>{k[0]}</td>
                    <td className="p-2 max-w-xl">{c.text}</td>
                    <td className="p-2"><span className={`px-tag ${v[1]}`}>{v[0]}</span></td>
                    <td className="p-2">{c.confidence.toFixed(2)}</td>
                    <td className="p-2">{cardRef ? <button className="underline text-sky" onClick={() => setCard(cardRef)}>[{cardRef.number}]</button> : `#${c.source_id}`}</td>
                    <td className="p-2">{c.page_number ?? "-"}</td>
                    <td className="p-2 text-[11px] text-cream/70">{c.verification_notes.join("; ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {tab === "출처" && (
        <div className="grid gap-2">
          {sources.map((s) => (
            <div key={s.id} className="px-panel p-3 text-[12.5px]">
              <div className="flex gap-2 items-center flex-wrap"><span className="px-tag bg-accent text-ink">등급 {s.tier} {TIER_KO[s.tier]}</span>
                <b>{s.title}</b>{s.accessed ? <span className="px-tag bg-mint text-ink">원문 확인</span> : <span className="px-tag bg-rose text-ink">접근 실패</span>}
                {cardForSource(s.id) && <button className="underline text-sky" onClick={() => setCard(cardForSource(s.id)!)}>인용 [{cardForSource(s.id)!.number}]</button>}</div>
              <div className="text-cream/60">{s.publisher} · 발행 {s.publication_date || "미상"} · 접근 {s.access_date.slice(0, 10)}{s.query ? ` · 검색어 “${s.query}”` : ""}</div>
              {s.url && <a className="underline text-sky break-all" href={s.url} target="_blank" rel="noreferrer noopener">{s.url}</a>}
              {s.access_error && <div className="text-rose">{s.access_error}</div>}
            </div>
          ))}
        </div>
      )}

      {tab === "회의록" && (
        <div className="grid gap-3">
          {(task.meetings || []).map((m) => (
            <div key={m.id} className="px-panel p-3">
              <div className="px-title">{m.title}</div>
              <div className="text-[12px] text-cream/70">결정: {m.decisions.join(" / ")}</div>
              <table className="w-full text-[12px] mt-2">
                <thead className="bg-ink"><tr>{["Decision", "Action Item", "Owner", "Deadline", "Status"].map((h) => <th key={h} className="p-1 text-left">{h}</th>)}</tr></thead>
                <tbody>{m.action_items.map((a) => <tr key={a.id} className="border-t border-black/40"><td className="p-1">{a.decision}</td><td className="p-1">{a.description}</td><td className="p-1">{a.owner}</td><td className="p-1">{a.deadline}</td><td className="p-1">{a.status}</td></tr>)}</tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {tab === "대화" && <div className="px-panel p-3">{messages.filter((m) => String(m.task_id) === id).map((m) => <MessageItem key={m.id} m={m} />)}</div>}

      {tab === "감사 로그" && (
        <div className="px-panel p-3 font-pixel text-[12px]">
          {audit.map((a) => <div key={a.id}>{new Date(a.ts).toLocaleTimeString("ko-KR")}  <span className="text-accent">{a.actor}</span>  {a.action} <span className="text-cream/50">{JSON.stringify(a.detail).slice(0, 140)}</span></div>)}
        </div>
      )}
      {card && <CitationCard card={card} onClose={() => setCard(null)} />}
    </Page>
  );
}
