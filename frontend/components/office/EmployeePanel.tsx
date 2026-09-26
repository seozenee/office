"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import Avatar from "@/components/ui/Avatar";
import MessageItem from "@/components/office/MessageItem";
import { useOffice } from "@/components/OfficeProvider";
import { api } from "@/lib/api";
import type { Employee, Message } from "@/lib/types";

const STATUS: Record<string, [string, string]> = {
  idle: ["대기", "bg-cream/70"], working: ["업무 중", "bg-mint"], meeting: ["회의 중", "bg-rose"], away: ["자리 비움", "bg-line"],
};

export default function EmployeePanel({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const { layout, messages, channels } = useOffice();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [history, setHistory] = useState<Message[]>([]);
  const [createdTask, setCreatedTask] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const dmChannel = channels.find((c) => c.kind === "dm" && c.employee_id === employee.id);

  useEffect(() => {
    setCreatedTask(null);
    api<Message[]>(`/api/office/dm/${employee.id}`).then(setHistory).catch(() => setHistory([]));
  }, [employee.id]);

  const live = useMemo(() => {
    const extra = messages.filter((m) => m.channel_id === dmChannel?.id && !history.some((h) => h.id === m.id));
    return [...history, ...extra].sort((a, b) => a.id - b.id);
  }, [messages, history, dmChannel]);
  useEffect(() => endRef.current?.scrollIntoView({ block: "end" }), [live.length]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setSending(true);
    try {
      const r = await api<{ message: Message; reply: Message; task_id: number | null }>(`/api/office/dm/${employee.id}`, { method: "POST", json: { text } });
      setHistory((h) => [...h, r.message, r.reply]);
      if (r.task_id) setCreatedTask(r.task_id);
      setText("");
    } finally { setSending(false); }
  };
  const st = STATUS[employee.status] || STATUS.idle;
  const recent = messages.filter((m) => m.sender_id === employee.id && m.sender_type === "employee" && m.channel_id !== dmChannel?.id).slice(-4);

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 flex gap-3 items-start border-b-2 border-black">
        <Avatar employee={employee} size={56} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2"><b className="text-accent text-[15px]">{employee.name}</b><span>{employee.title}</span>{employee.is_lead && <span className="px-tag bg-accent text-ink">팀장</span>}</div>
          <div className="text-[12px] text-cream/80">{layout?.departments[employee.department]} · {employee.role}</div>
          <div className="text-[12px] mt-1 flex items-center gap-1"><span className={`w-2 h-2 ${st[1]}`} />{st[0]} — {employee.status_text}</div>
          {employee.current_task_id && <Link className="text-[12px] text-sky underline" href={`/tasks/${employee.current_task_id}`}>작업 #{employee.current_task_id} 보기</Link>}
        </div>
        <button onClick={onClose} className="px-btn-ghost !px-2 !py-0.5">✕</button>
      </div>
      <p className="px-3 py-2 text-[12px] text-cream/70 border-b border-black/50">{employee.persona}</p>
      {recent.length > 0 && (
        <div className="px-3 py-1 border-b border-black/50 max-h-40 overflow-auto">
          <div className="text-[11px] text-cream/50">최근 업무 발언</div>
          {recent.map((m) => <MessageItem key={m.id} m={m} />)}
        </div>
      )}
      <div className="px-3 pt-2 text-[11px] text-cream/50">개인 메시지 (DM) — 업무를 지시하면 작업으로 등록됩니다</div>
      <div className="flex-1 overflow-auto px-3">
        {live.map((m) => <MessageItem key={m.id} m={m} showChannel={false} />)}
        {createdTask && <div className="my-2 px-panel-2 p-2 text-[12px]">✅ 작업 #{createdTask} 생성됨 — <Link className="underline text-sky" href={`/tasks/${createdTask}`}>진행 보기</Link></div>}
        <div ref={endRef} />
      </div>
      <form onSubmit={send} className="p-3 flex gap-2 border-t-2 border-black">
        <input className="px-input flex-1" value={text} onChange={(e) => setText(e.target.value)} placeholder={`${employee.name}에게 메시지…`} />
        <button className="px-btn" disabled={sending}>{sending ? "…" : "전송"}</button>
      </form>
    </div>
  );
}
