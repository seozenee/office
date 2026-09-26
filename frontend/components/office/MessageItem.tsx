"use client";

import Link from "next/link";
import Avatar from "@/components/ui/Avatar";
import { useOffice } from "@/components/OfficeProvider";
import { timeAgo } from "@/lib/labels";
import type { Message } from "@/lib/types";

const KIND_BADGE: Record<string, [string, string]> = {
  approval_request: ["결재요청", "bg-accent text-ink"], approval_stamp: ["결재", "bg-rose text-ink"], meeting: ["회의", "bg-pink-300 text-ink"],
  report: ["보고", "bg-sky text-ink"], progress: ["진행", "bg-mint text-ink"], system: ["지시", "bg-cream text-ink"],
};

export default function MessageItem({ m, showChannel = true }: { m: Message; showChannel?: boolean }) {
  const { empById, channels } = useOffice();
  const emp = m.sender_type === "employee" ? empById(m.sender_id) : undefined;
  const ch = channels.find((c) => c.id === m.channel_id);
  const badge = KIND_BADGE[m.kind];
  const who = m.sender_type === "user" ? "CEO (나)" : emp ? `${emp.name} ${emp.title}` : "시스템";
  return (
    <div className="flex gap-2 py-2 border-b border-black/40">
      {m.sender_type === "system" ? <div className="w-7 h-7 bg-line shadow-pixelsm flex items-center justify-center">🏢</div> : <Avatar employee={emp} size={28} />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 flex-wrap text-[11px]">
          <b className={m.sender_type === "user" ? "text-accent" : "text-cream"}>{who}</b>
          {showChannel && ch && <span className="px-tag bg-ink text-cream/70">#{ch.name}</span>}
          {badge && <span className={`px-tag ${badge[1]}`}>{badge[0]}</span>}
          <span className="text-cream/40 ml-auto">{timeAgo(m.created_at)}</span>
        </div>
        <div className="whitespace-pre-wrap break-words text-[12.5px] mt-0.5 leading-relaxed">{m.content}</div>
        {m.task_id && m.kind !== "chat" && <Link href={`/tasks/${m.task_id}`} className="text-[11px] text-sky underline">작업 #{m.task_id}</Link>}
      </div>
    </div>
  );
}
