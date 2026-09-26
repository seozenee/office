"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import ApprovalLine from "@/components/ui/Stamp";
import { useOffice } from "@/components/OfficeProvider";
import { api } from "@/lib/api";
import { RISK_COLOR, timeAgo } from "@/lib/labels";
import type { Approval } from "@/lib/types";

export default function Approvals() {
  const { pendingApprovals, messages } = useOffice();
  const [items, setItems] = useState<Approval[]>([]);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [filter, setFilter] = useState("pending");
  const [msg, setMsg] = useState("");
  const load = () => api<Approval[]>(`/api/approvals${filter ? `?status=${filter}` : ""}`).then(setItems);
  useEffect(() => { load(); }, [filter, pendingApprovals, messages.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const decide = async (a: Approval, approve: boolean) => {
    try {
      const r = await api<any>(`/api/approvals/${a.id}/decide`, { method: "POST", json: { approve, note: notes[a.id] || "" } });
      setMsg(`결재 #${a.id}: ${r.status}${r.tool_error ? ` — 실행 오류: ${r.tool_error}` : ""}${r.final_files ? ` — 최종본 ${r.final_files.length}개 보관` : ""}`);
      load();
    } catch (e: any) { setMsg(e.message); }
  };
  const ceoTurn = (a: Approval) => a.status === "pending" && a.line.find((s) => s.status === "pending")?.employee_id === null;

  return (
    <Page title="결재함" subtitle="직원 → 팀장 → 실장 → CEO 순으로 결재가 올라옵니다. HIGH 이상(외부 발송·게시·결제·삭제)은 반드시 CEO 승인 후 실행됩니다."
      actions={<select className="px-input" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="pending">대기</option><option value="approved">승인</option><option value="rejected">반려</option><option value="">전체</option></select>}>
      {msg && <div className="px-panel-2 p-2">{msg}</div>}
      {items.map((a) => (
        <div key={a.id} className={`px-panel p-4 ${ceoTurn(a) ? "ring-2 ring-accent" : ""}`}>
          <div className="flex items-center gap-2 flex-wrap">
            <b className="text-[14px]">#{a.id} {a.title}</b>
            <span className={`px-tag ${RISK_COLOR[a.risk_level]}`}>{a.risk_level}</span>
            <span className="px-tag bg-ink">{a.action}</span>
            <span className="text-cream/50 text-[11px]">{timeAgo(a.created_at)}</span>
            {a.task_id && <Link className="underline text-sky text-[12px]" href={`/tasks/${a.task_id}`}>작업 #{a.task_id}</Link>}
          </div>
          <div className="my-2"><ApprovalLine line={a.line} /></div>
          {"kwargs" in (a.payload || {}) && <pre className="text-[11px] bg-ink p-2 overflow-auto">{JSON.stringify((a.payload as any).kwargs, null, 1)}</pre>}
          {a.decision_note && <div className="text-[12px]">의견: {a.decision_note}</div>}
          {ceoTurn(a) && (
            <div className="flex gap-2 mt-2">
              <input className="px-input flex-1" placeholder="결재 의견" value={notes[a.id] || ""} onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} />
              <button className="px-btn" onClick={() => decide(a, true)}>승인</button>
              <button className="px-btn-danger" onClick={() => decide(a, false)}>반려</button>
            </div>
          )}
        </div>
      ))}
      {!items.length && <p className="text-cream/50">해당하는 결재가 없습니다.</p>}
    </Page>
  );
}
