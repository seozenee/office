"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { api } from "@/lib/api";
import { TIER_KO } from "@/lib/labels";
import type { Source } from "@/lib/types";

export default function Sources() {
  const [items, setItems] = useState<Source[]>([]);
  const [only, setOnly] = useState("");
  useEffect(() => { api<Source[]>(`/api/sources${only ? `?accessed=${only}` : ""}`).then(setItems); }, [only]);
  return (
    <Page title="출처" subtitle="우선순위: 1 정부·공공 → 2 공식 기업 → 3 학술 → 4 국제기구 → 5 전문기관 → 6 언론 → 7 기타. 스니펫만 본 출처는 근거로 쓰지 않습니다."
      actions={<select className="px-input" value={only} onChange={(e) => setOnly(e.target.value)}><option value="">전체</option><option value="true">원문 확인</option><option value="false">접근 실패</option></select>}>
      <div className="px-panel overflow-x-auto">
        <table className="w-full text-[12.5px]">
          <thead className="bg-ink"><tr>{["등급", "제목", "발행처", "발행일", "접근일", "원문", "작업"].map((h) => <th key={h} className="text-left p-2">{h}</th>)}</tr></thead>
          <tbody>{items.map((s) => (
            <tr key={s.id} className="border-t border-black/40 align-top">
              <td className="p-2 whitespace-nowrap">{s.tier} {TIER_KO[s.tier]}</td>
              <td className="p-2">{s.url ? <a className="underline text-sky" href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a> : s.title}{s.access_error && <div className="text-rose text-[11px]">{s.access_error}</div>}</td>
              <td className="p-2">{s.publisher}</td><td className="p-2">{s.publication_date || "미상"}</td><td className="p-2">{s.access_date.slice(0, 10)}</td>
              <td className="p-2">{s.accessed ? "✅" : "❌"}</td>
              <td className="p-2">{s.task_id && <Link className="underline text-sky" href={`/tasks/${s.task_id}`}>#{s.task_id}</Link>}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </Page>
  );
}
