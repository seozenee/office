"use client";

import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import MessageItem from "@/components/office/MessageItem";
import { useOffice } from "@/components/OfficeProvider";
import { api } from "@/lib/api";
import type { Meeting } from "@/lib/types";

export default function Meetings() {
  const { employees, messages } = useOffice();
  const [items, setItems] = useState<Meeting[]>([]);
  const [sel, setSel] = useState<Meeting | null>(null);
  const [title, setTitle] = useState("");
  const [agenda, setAgenda] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const [msg, setMsg] = useState("");
  const meetingMsgs = messages.filter((m) => m.kind === "meeting").length;
  useEffect(() => { api<Meeting[]>("/api/office/meetings").then(setItems); }, [meetingMsgs]);
  const open = async (m: Meeting) => setSel(await api<Meeting>(`/api/office/meetings/${m.id}`));
  const call = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/office/meetings", { method: "POST", json: { title, agenda: agenda.split("\n").map((s) => s.trim()).filter(Boolean), participant_ids: picked } });
      setMsg("회의를 소집했습니다. 참석자들이 회의실로 이동합니다."); setTitle(""); setAgenda(""); setPicked([]);
    } catch (err: any) { setMsg(err.message); }
  };
  return (
    <Page title="회의" subtitle="킥오프·리뷰(Multi-Agent Debate) 회의와 CEO 소집 회의. 회의록은 Decision / Action Item / Owner / Deadline / Status 로 정리됩니다.">
      <div className="grid lg:grid-cols-[360px_1fr] gap-4">
        <div className="flex flex-col gap-3">
          <form onSubmit={call} className="px-panel p-3 flex flex-col gap-2">
            <b className="px-title">회의 소집</b>
            <input className="px-input" required placeholder="회의 제목" value={title} onChange={(e) => setTitle(e.target.value)} />
            <textarea className="px-input" required rows={3} placeholder="안건 (한 줄에 하나)" value={agenda} onChange={(e) => setAgenda(e.target.value)} />
            <div className="max-h-40 overflow-auto grid grid-cols-2 gap-1 text-[12px]">
              {employees.map((e) => <label key={e.id} className="flex gap-1 items-center"><input type="checkbox" checked={picked.includes(e.id)} onChange={(ev) => setPicked(ev.target.checked ? [...picked, e.id] : picked.filter((x) => x !== e.id))} />{e.name} {e.title}</label>)}
            </div>
            <button className="px-btn justify-center" disabled={picked.length < 2}>소집 ({picked.length}명)</button>
            {msg && <div className="text-[12px]">{msg}</div>}
          </form>
          {items.map((m) => <button key={m.id} onClick={() => open(m)} className={`px-panel p-2 text-left ${sel?.id === m.id ? "ring-2 ring-accent" : ""}`}>🗓️ {m.title}<div className="text-[11px] text-cream/60">{m.status} · 결정 {m.decisions.length} · 액션 {m.action_items.length}</div></button>)}
        </div>
        {sel ? (
          <div className="flex flex-col gap-3">
            <div className="px-panel p-3"><b className="px-title">{sel.title}</b><div className="text-[12px]">안건: {sel.agenda.join(" / ")}</div></div>
            <div className="px-panel p-3">{sel.transcript?.map((m) => <MessageItem key={m.id} m={m} showChannel={false} />)}</div>
            <div className="px-panel p-3"><pre className="whitespace-pre-wrap font-body text-[12.5px]">{sel.minutes}</pre></div>
          </div>
        ) : <p className="text-cream/50">회의를 선택하세요.</p>}
      </div>
    </Page>
  );
}
