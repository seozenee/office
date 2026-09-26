"use client";

import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { api } from "@/lib/api";
import type { KBDoc, Project } from "@/lib/types";

interface Hit { chunk_id: number; document_id: number; document_title: string; page: number | null; section: string | null; text: string; score: number; bm25_rank: number | null; vector_rank: number | null }

export default function Research() {
  const [docs, setDocs] = useState<KBDoc[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [msg, setMsg] = useState("");
  const load = () => api<KBDoc[]>(`/api/documents${projectId ? `?project_id=${projectId}` : ""}`).then(setDocs);
  useEffect(() => { api<Project[]>("/api/projects").then(setProjects); }, []);
  useEffect(() => { load(); }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  const upload = async (files: FileList | null) => {
    if (!files) return;
    for (const f of Array.from(files)) {
      const fd = new FormData();
      fd.append("file", f);
      if (projectId) fd.append("project_id", projectId);
      try {
        const r = await api<any>("/api/documents", { method: "POST", body: fd });
        setMsg(`업로드 완료: ${r.title}${r.injection_flags?.length ? ` ⚠️ 인젝션 의심(${r.injection_flags.join(",")}) — 데이터로만 처리` : ""}${r.warnings?.length ? ` · ${r.warnings.join(" ")}` : ""}`);
      } catch (e: any) { setMsg(`${f.name}: ${e.message}`); }
    }
    load();
  };
  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    setHits(await api<Hit[]>(`/api/search?q=${encodeURIComponent(q)}${projectId ? `&project_id=${projectId}` : ""}`));
  };
  return (
    <Page title="지식베이스" subtitle="PDF · DOCX · PPTX · XLSX · TXT · MD · HTML · 이미지(OCR) — 페이지·섹션·표·참고문헌을 보존하고 BM25+벡터 하이브리드 검색"
      actions={<select className="px-input" value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">전체/미분류</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}>
      <label className="px-panel p-6 text-center cursor-pointer border-dashed">
        <input type="file" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
        📥 파일을 선택해 업로드 (최대 60MB)
      </label>
      {msg && <div className="px-panel-2 p-2 text-[12px]">{msg}</div>}
      <form onSubmit={search} className="flex gap-2"><input className="px-input flex-1" value={q} onChange={(e) => setQ(e.target.value)} placeholder="지식베이스 검색 (하이브리드)" /><button className="px-btn">검색</button></form>
      {hits.map((h) => (
        <div key={h.chunk_id} className="px-panel p-3 text-[12.5px]">
          <div className="text-accent">{h.document_title} · p.{h.page ?? "-"} {h.section ? `· ${h.section}` : ""} <span className="text-cream/50 text-[11px]">RRF {h.score} (BM25 #{h.bm25_rank ?? "-"}, 벡터 #{h.vector_rank ?? "-"})</span></div>
          <p className="whitespace-pre-wrap">{h.text.slice(0, 600)}</p>
        </div>
      ))}
      <div className="px-panel">
        <table className="w-full text-[12.5px]">
          <thead className="bg-ink"><tr>{["제목", "형식", "쪽", "표", "섹션", "참고문헌", "날짜", "보안"].map((h) => <th key={h} className="text-left p-2">{h}</th>)}</tr></thead>
          <tbody>{docs.map((d) => (
            <tr key={d.id} className="border-t border-black/40 hover:bg-panel2 cursor-pointer" onClick={() => api(`/api/documents/${d.id}`).then(setDetail)}>
              <td className="p-2">{d.title}</td><td className="p-2">{d.mime.split("/").pop()}{d.is_ocr ? " (OCR)" : ""}</td><td className="p-2">{d.page_count}</td>
              <td className="p-2">{d.tables}</td><td className="p-2">{d.sections_count}</td><td className="p-2">{d.references}</td><td className="p-2">{d.date || "-"}</td>
              <td className="p-2">{d.injection_flags.length ? <span className="px-tag bg-rose text-ink">의심</span> : "✓"}</td>
            </tr>))}</tbody>
        </table>
      </div>
      {detail && (
        <div className="fixed inset-0 bg-black/60 z-40 flex items-center justify-center p-6" onClick={() => setDetail(null)}>
          <div className="px-panel p-4 max-w-4xl w-full max-h-[85vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between"><b className="px-title">{detail.title}</b><button className="px-btn-ghost" onClick={() => setDetail(null)}>✕</button></div>
            <div className="text-[12px] text-cream/60">{detail.author} · {detail.organization} · {detail.date} · {detail.source_url}</div>
            <div className="mt-2 text-accent">섹션</div>
            <ul className="text-[12px]">{detail.sections.map((s: any, i: number) => <li key={i} style={{ paddingLeft: (s.level - 1) * 12 }}>{s.heading} {s.page ? `(p.${s.page})` : ""}</li>)}</ul>
            {detail.table_data.map((t: any, i: number) => (
              <table key={i} className="text-[11px] my-2 border border-line"><tbody>{t.rows.slice(0, 8).map((r: string[], j: number) => <tr key={j}>{r.map((c, k) => <td key={k} className="border border-line px-1">{c}</td>)}</tr>)}</tbody></table>
            ))}
            {detail.citations.length > 0 && <><div className="mt-2 text-accent">참고문헌</div><ol className="text-[12px] list-decimal pl-5">{detail.citations.map((c: string, i: number) => <li key={i}>{c}</li>)}</ol></>}
            <div className="mt-2 text-accent">본문 청크</div>
            {detail.chunks.slice(0, 30).map((c: any) => <p key={c.ord} className="text-[12px] border-t border-black/40 py-1"><span className="text-cream/50">p.{c.page ?? "-"}</span> {c.text}</p>)}
          </div>
        </div>
      )}
    </Page>
  );
}
