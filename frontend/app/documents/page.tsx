"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { api, fileUrl } from "@/lib/api";
import { timeAgo } from "@/lib/labels";
import type { Artifact } from "@/lib/types";

const ICON: Record<string, string> = { presentation: "📑", spreadsheet: "📊", report: "📄", document: "📝", research: "🔬", dataset: "🗃️", code: "💻" };

export default function Documents() {
  const [items, setItems] = useState<Artifact[]>([]);
  const [kind, setKind] = useState("");
  useEffect(() => { api<Artifact[]>(`/api/artifacts${kind ? `?kind=${kind}` : ""}`).then(setItems); }, [kind]);
  return (
    <Page title="문서 · 산출물" subtitle="모든 결과물은 Artifact로 관리되며 덮어쓰지 않고 v1 → v2 → final 로 버전이 쌓입니다"
      actions={<select className="px-input" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">전체</option>{Object.keys(ICON).map((k) => <option key={k} value={k}>{k}</option>)}</select>}>
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
        {items.map((a) => (
          <div key={a.id} className="px-panel p-3">
            <div className="flex gap-2 items-center"><span className="text-xl">{ICON[a.kind] || "📄"}</span><b className="truncate">{a.title}</b></div>
            <div className="text-[11px] text-cream/60">{a.author_agent} · {a.status} · {timeAgo(a.created_at)} {a.task_id && <Link className="underline text-sky" href={`/tasks/${a.task_id}`}>작업 #{a.task_id}</Link>}</div>
            <div className="mt-2 flex flex-col gap-1">
              {a.versions.map((v) => (
                <div key={v.id} className="flex items-center gap-2 text-[12px]">
                  <span className={`px-tag ${v.label === "final" ? "bg-accent text-ink" : "bg-ink"}`}>{v.label}</span>
                  <a className="underline text-sky truncate" href={fileUrl(`/api/artifacts/${a.id}/download?version_id=${v.id}`)}>{v.file_name}</a>
                  <span className="text-cream/50 ml-auto shrink-0">{Math.round(v.size_bytes / 1024)}KB</span>
                </div>
              ))}
              <div className="text-[11px] text-cream/50">{a.versions[a.versions.length - 1]?.change_note}</div>
            </div>
          </div>
        ))}
      </div>
      {!items.length && <p className="text-cream/50">아직 생성된 산출물이 없습니다.</p>}
    </Page>
  );
}
