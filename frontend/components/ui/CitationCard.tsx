import type { CitationCard as Card } from "@/lib/types";
import { TIER_KO } from "@/lib/labels";

export default function CitationCard({ card, onClose }: { card: Card; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="px-panel p-4 max-w-2xl w-full max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-start gap-3">
          <div className="px-title text-lg">[{card.number}] 출처</div>
          <button className="px-btn-ghost !py-0.5" onClick={onClose}>✕</button>
        </div>
        <table className="text-[12.5px] mt-2 w-full">
          <tbody>
            {[["Source", card.type + ` (등급 ${card.tier} · ${TIER_KO[card.tier] || ""})`], ["Title", card.title], ["Publisher", card.publisher || "-"],
              ["Date", card.date || "발행일 미상"], ["Accessed", card.accessed?.slice(0, 10) || "-"]].map(([k, v]) => (
              <tr key={k}><td className="pr-3 py-1 text-cream/60 w-28">{k}</td><td>{v}</td></tr>
            ))}
            <tr><td className="pr-3 py-1 text-cream/60">URL</td><td>{card.url ? <a className="underline text-sky break-all" href={card.url} target="_blank" rel="noreferrer noopener">{card.url}</a> : "-"}</td></tr>
          </tbody>
        </table>
        <div className="mt-3 text-accent">Relevant passages</div>
        {card.passages.map((p) => (
          <div key={p.claim_id} className="px-panel-2 p-2 mt-2 text-[12.5px]">
            <div className="text-cream/60 text-[11px]">Page {p.page ?? "-"} · 신뢰도 {p.confidence.toFixed(2)}</div>
            <blockquote className="border-l-4 border-accent pl-2 my-1">“{p.passage}”</blockquote>
            <div className="text-cream/80">→ 주장: {p.claim}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
