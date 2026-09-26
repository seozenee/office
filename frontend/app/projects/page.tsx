"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { api } from "@/lib/api";
import { STATUS_KO } from "@/lib/labels";
import type { Project } from "@/lib/types";

export default function Projects() {
  const [items, setItems] = useState<Project[]>([]);
  const [sel, setSel] = useState<any>(null);
  const [tree, setTree] = useState<any>(null);
  const [form, setForm] = useState({ name: "", description: "", context: "" });
  const load = () => api<Project[]>("/api/projects").then(setItems);
  useEffect(() => { load(); }, []);
  const open = async (p: Project) => {
    setSel(await api(`/api/projects/${p.id}`));
    setTree(await api(`/api/files/tree?project_id=${p.id}`));
  };
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    await api("/api/projects", { method: "POST", json: form });
    setForm({ name: "", description: "", context: "" });
    load();
  };
  const saveContext = async () => {
    await api(`/api/projects/${sel.id}`, { method: "PATCH", json: { name: sel.name, description: sel.description, context: sel.context } });
    load();
  };
  return (
    <Page title="프로젝트 워크스페이스" subtitle="프로젝트마다 독립 폴더(research/documents/presentations/spreadsheets/source_files/final/archive)와 컨텍스트를 가집니다">
      <div className="grid lg:grid-cols-[320px_1fr] gap-4">
        <div className="flex flex-col gap-3">
          <form onSubmit={create} className="px-panel p-3 flex flex-col gap-2">
            <b className="px-title">새 프로젝트</b>
            <input className="px-input" required placeholder="이름 (예: AI Startup)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input className="px-input" placeholder="설명" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <textarea className="px-input" rows={3} placeholder="에이전트가 참고할 프로젝트 컨텍스트" value={form.context} onChange={(e) => setForm({ ...form, context: e.target.value })} />
            <button className="px-btn justify-center">만들기</button>
          </form>
          {items.map((p) => <button key={p.id} onClick={() => open(p)} className={`px-panel p-3 text-left ${sel?.id === p.id ? "ring-2 ring-accent" : ""}`}>📁 {p.name}<div className="text-[11px] text-cream/60">{p.description}</div></button>)}
        </div>
        {sel ? (
          <div className="flex flex-col gap-3">
            <div className="px-panel p-3">
              <b className="px-title">{sel.name}</b>
              <textarea className="px-input w-full mt-2" rows={3} value={sel.context} onChange={(e) => setSel({ ...sel, context: e.target.value })} />
              <button className="px-btn-ghost mt-2" onClick={saveContext}>컨텍스트 저장</button>
            </div>
            <div className="px-panel p-3"><b>작업</b>{sel.tasks.map((t: any) => <div key={t.id}><Link className="underline text-sky" href={`/tasks/${t.id}`}>#{t.id} {t.title}</Link> — {STATUS_KO[t.status]}</div>)}</div>
            <div className="px-panel p-3"><b>결정 사항</b>{sel.decisions.length ? sel.decisions.map((d: any) => <div key={d.key} className="text-[12px]">• {d.value}</div>) : <p className="text-cream/50">없음</p>}</div>
            {tree && <div className="px-panel p-3 text-[12px]"><b>폴더</b> <span className="text-cream/50">{tree.root}</span>
              {Object.entries(tree.folders).map(([k, files]: any) => <div key={k} className="mt-1"><span className="text-accent">📂 {k}/</span> {files.length === 0 ? <span className="text-cream/40">(비어 있음)</span> : files.map((f: any) => <div key={f.name} className="pl-5">📄 {f.name}</div>)}</div>)}
            </div>}
          </div>
        ) : <p className="text-cream/50">프로젝트를 선택하세요.</p>}
      </div>
    </Page>
  );
}
