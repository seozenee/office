"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { useOffice } from "@/components/OfficeProvider";
import { api } from "@/lib/api";
import { TIER_KO, timeAgo } from "@/lib/labels";

interface Opp { id: number; interest: string; category: string; title: string; url: string; tier: number; published: string | null; snippet: string; score: number; status: string; task_id: number | null; found_at: string }
const CAT: Record<string, string> = { paper: "📚 논문", competition: "🏆 공모전", grant: "🏛️ 지원사업", market: "📈 시장", company: "🏢 기업", investment: "💰 투자", technology: "🧪 기술" };

export default function Opportunities() {
  const { messages } = useOffice();
  const [items, setItems] = useState<Opp[]>([]);
  const [status, setStatus] = useState("");
  const [interest, setInterest] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api<Opp[]>(`/api/opportunities${status ? `?status=${status}` : ""}`).then(setItems);
  useEffect(() => { load(); }, [status, messages.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const scan = async () => {
    await api("/api/opportunities/scan", { method: "POST", json: { interests: interest ? interest.split(",").map((s) => s.trim()) : null } });
    setMsg("스캔을 시작했습니다. 정우진 선임이 검색 중입니다…");
  };
  const act = async (o: Opp, s: string) => { await api(`/api/opportunities/${o.id}/status?status=${s}`, { method: "POST" }); load(); };
  const task = async (o: Opp) => { const r = await api<{ task_id: number }>(`/api/opportunities/${o.id}/task`, { method: "POST" }); setMsg(`작업 #${r.task_id} 로 조사를 지시했습니다.`); load(); };
  return (
    <Page title="기회 스캐너" subtitle="관심 분야(설정 → 메모리의 interest, 프로젝트 이름)에 대한 새 논문·공모전·지원사업·시장 변화·기업·투자 정보를 찾습니다. 요약은 검색 스니펫(원문 미확인)이며, ‘조사 지시’를 누르면 원문 검증 조사가 시작됩니다."
      actions={<div className="flex gap-2"><input className="px-input" placeholder="관심 분야 (쉼표 구분, 비우면 저장된 관심사)" value={interest} onChange={(e) => setInterest(e.target.value)} /><button className="px-btn" onClick={scan}>지금 스캔</button>
        <select className="px-input" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">전체</option><option value="new">새 항목</option><option value="saved">저장</option><option value="tasked">조사 중</option><option value="dismissed">숨김</option></select></div>}>
      {msg && <div className="px-panel-2 p-2">{msg}</div>}
      <div className="grid md:grid-cols-2 gap-3">
        {items.filter((o) => status || o.status !== "dismissed").map((o) => (
          <div key={o.id} className="px-panel p-3 text-[12.5px]">
            <div className="flex gap-2 items-center flex-wrap"><span className="px-tag bg-accent text-ink">{CAT[o.category] || o.category}</span><span className="px-tag bg-ink">{o.interest}</span>
              <span className="px-tag bg-ink">등급 {o.tier} {TIER_KO[o.tier]}</span><span className="text-cream/50 ml-auto">점수 {o.score} · {timeAgo(o.found_at)}</span></div>
            <a className="block mt-1 text-[14px] underline text-sky" href={o.url} target="_blank" rel="noreferrer noopener">{o.title}</a>
            <p className="text-cream/70 mt-1"><span className="text-rose text-[11px]">[스니펫·미확인]</span> {o.snippet}</p>
            <div className="text-[11px] text-cream/50">발행 {o.published || "미상"}</div>
            <div className="flex gap-2 mt-2">
              {o.task_id ? <Link className="px-btn-ghost" href={`/tasks/${o.task_id}`}>작업 #{o.task_id}</Link> : <button className="px-btn" onClick={() => task(o)}>조사 지시</button>}
              {o.status !== "saved" && <button className="px-btn-ghost" onClick={() => act(o, "saved")}>저장</button>}
              {o.status !== "dismissed" && <button className="px-btn-ghost" onClick={() => act(o, "dismissed")}>숨김</button>}
            </div>
          </div>
        ))}
      </div>
      {!items.length && <p className="text-cream/50">아직 찾은 기회가 없습니다. 관심 분야를 저장하고 스캔하거나, 설정에서 매일 자동 스캔을 예약하세요.</p>}
    </Page>
  );
}
