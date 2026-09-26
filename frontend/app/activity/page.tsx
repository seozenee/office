"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { useOffice } from "@/components/OfficeProvider";
import { api } from "@/lib/api";
import { RISK_COLOR } from "@/lib/labels";
import type { AuditEntry } from "@/lib/types";

export default function Activity() {
  const { messages } = useOffice();
  const [items, setItems] = useState<AuditEntry[]>([]);
  useEffect(() => { api<AuditEntry[]>("/api/audit?limit=400").then(setItems); }, [messages.length]);
  return (
    <Page title="활동 기록 (Audit Log)" subtitle="AI가 수행한 모든 행동 — 검색, 다운로드, 분석, 검증, 문서 생성, 결재. 민감정보는 마스킹되어 저장됩니다.">
      <div className="px-panel p-3 font-pixel text-[12px] leading-6">
        {items.map((a) => (
          <div key={a.id} className="flex gap-2 border-b border-black/30">
            <span className="text-cream/50 w-40 shrink-0">{new Date(a.ts).toLocaleString("ko-KR")}</span>
            <span className={`px-tag ${RISK_COLOR[a.risk]} h-fit`}>{a.risk}</span>
            <span className="text-accent w-28 shrink-0 truncate">{a.actor}</span>
            <span className="w-44 shrink-0">{a.action}</span>
            {a.task_id && <Link className="underline text-sky" href={`/tasks/${a.task_id}`}>#{a.task_id}</Link>}
            <span className="text-cream/50 truncate">{JSON.stringify(a.detail)}</span>
          </div>
        ))}
      </div>
    </Page>
  );
}
