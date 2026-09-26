import type { ApprovalStep } from "@/lib/types";

// 결재란: a row of stamp boxes, one per approver in the approval line.
export default function ApprovalLine({ line }: { line: ApprovalStep[] }) {
  return (
    <div className="flex gap-1">
      {line.map((s, i) => (
        <div key={i} className="w-20 text-center shadow-inset bg-ink">
          <div className="text-[10px] py-0.5 border-b-2 border-black/60 truncate px-1">{s.approver}</div>
          <div className="h-10 flex items-center justify-center">
            {s.status === "approved" && <span className="w-8 h-8 rounded-full border-2 border-rose-500 text-rose-400 text-[11px] flex items-center justify-center rotate-[-12deg]">승인</span>}
            {s.status === "rejected" && <span className="w-8 h-8 rounded-full border-2 border-sky-400 text-sky-300 text-[11px] flex items-center justify-center rotate-[8deg]">반려</span>}
            {s.status === "pending" && <span className="text-cream/30 text-[11px]">대기</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
