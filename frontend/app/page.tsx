"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import OfficeCanvas, { type Bubble } from "@/components/office/OfficeCanvas";
import EmployeePanel from "@/components/office/EmployeePanel";
import MessageItem from "@/components/office/MessageItem";
import { useOffice } from "@/components/OfficeProvider";
import { api } from "@/lib/api";
import { STATUS_KO, bar } from "@/lib/labels";
import type { Employee, Project } from "@/lib/types";

const STEPS = ["Understanding task…", "Researching…", "Checking primary sources…", "Analyzing…", "Creating deliverables…", "Verifying…", "Done."];

function stepLabel(status: string, progress: number): string {
  if (status === "DONE" || status === "WAITING_USER") return STEPS[6];
  if (progress < 8) return STEPS[0];
  if (progress < 30) return STEPS[1];
  if (progress < 50) return STEPS[2];
  if (progress < 70) return STEPS[3];
  if (progress < 92) return STEPS[4];
  return STEPS[5];
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning." : h < 18 ? "Good afternoon." : "Good evening.";
}

export default function OfficePage() {
  const { layout, employees, messages, channels, tasks, pendingApprovals } = useOffice();
  const [selected, setSelected] = useState<Employee | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [request, setRequest] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [templates, setTemplates] = useState<{ id: number; name: string }[]>([]);
  const [templateId, setTemplateId] = useState<string>("");
  const [deliver, setDeliver] = useState<Record<string, boolean>>({ pptx: false, xlsx: true, docx: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    api<Project[]>("/api/projects").then(setProjects).catch(() => undefined);
    api<{ id: number; name: string }[]>("/api/templates").then(setTemplates).catch(() => undefined);
  }, []);

  const dmIds = useMemo(() => new Set(channels.filter((c) => c.kind === "dm").map((c) => c.id)), [channels]);
  const feed = useMemo(() => messages.filter((m) => !dmIds.has(m.channel_id) && (filter === "all" || String(m.channel_id) === filter)).slice(-150), [messages, dmIds, filter]);
  const bubbles: Bubble[] = useMemo(() => messages.filter((m) => m.sender_type === "employee" && m.sender_id)
    .map((m) => ({ employeeId: m.sender_id!, text: m.content, kind: m.kind })), [messages]);
  const liveSelected = selected ? employees.find((e) => e.id === selected.id) || selected : null;
  const active = tasks.filter((t) => !["DONE", "FAILED"].includes(t.status)).slice(0, 5);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!request.trim()) return;
    setBusy(true); setError("");
    try {
      await api("/api/tasks", { method: "POST", json: {
        request, project_id: projectId ? Number(projectId) : null, template_id: templateId ? Number(templateId) : null,
        deliverables: Object.entries(deliver).filter(([, v]) => v).map(([k]) => k),
      } });
      setRequest("");
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <div className="flex h-full">
      <section className="flex-1 min-w-0 flex flex-col p-4 gap-3 overflow-auto">
        <header className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1 className="px-title text-2xl">{greeting()}</h1>
            <p className="text-cream/80">What should I work on? — 한 줄로 지시하면 회사 전체가 움직입니다.</p>
          </div>
          {pendingApprovals && <Link href="/approvals" className="px-btn animate-pulse">📝 CEO 결재 대기 중</Link>}
        </header>

        <form onSubmit={submit} className="px-panel p-3 flex flex-col gap-2">
          <div className="flex gap-2">
            <input className="px-input flex-1 text-[14px]" value={request} onChange={(e) => setRequest(e.target.value)}
              placeholder="Ask your AI Office…  예) AI 헬스케어 시장을 조사해서 투자자용 PPT까지 만들어줘" />
            <button className="px-btn" disabled={busy}>{busy ? "접수 중…" : "지시 ▶"}</button>
          </div>
          <div className="flex gap-3 items-center flex-wrap text-[12px]">
            <select className="px-input !py-1" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">프로젝트 없음</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <select className="px-input !py-1" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
              <option value="">기본 구성</option>
              {templates.map((t) => <option key={t.id} value={t.id}>템플릿: {t.name}</option>)}
            </select>
            {(["docx", "pptx", "xlsx"] as const).map((k) => (
              <label key={k} className="flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={deliver[k]} onChange={(e) => setDeliver({ ...deliver, [k]: e.target.checked })} />
                {k === "docx" ? "📄 보고서" : k === "pptx" ? "📑 PPT" : "📊 엑셀"}
              </label>
            ))}
            {error && <span className="text-rose">{error}</span>}
          </div>
        </form>

        {active.length > 0 && (
          <div className="px-panel p-3 grid gap-1">
            <div className="text-[11px] text-cream/60">진행 중인 업무</div>
            {active.map((t) => (
              <Link key={t.id} href={`/tasks/${t.id}`} className="flex items-center gap-3 hover:bg-panel2 px-1">
                <span className="w-56 truncate">#{t.id} {t.title}</span>
                <span className="font-pixel text-mint tracking-tighter">{bar(t.progress)}</span>
                <span className="w-10 text-right">{Math.round(t.progress)}%</span>
                <span className="text-cream/70 truncate">{t.status === "WAITING_USER" ? STATUS_KO[t.status] : stepLabel(t.status, t.progress)} · {t.current_step}</span>
              </Link>
            ))}
          </div>
        )}

        <div className="flex gap-1 text-[12px] items-center">
          <span className="text-cream/60 mr-1">배율</span>
          {[1, 1.5, 2].map((z) => <button key={z} className={zoom === z ? "px-btn !py-0.5" : "px-btn-ghost !py-0.5"} onClick={() => setZoom(z)}>{z}x</button>)}
        </div>
        {layout ? (
          <div className="overflow-auto max-h-[75vh]">
            <div style={{ width: `${zoom * 100}%` }}>
              <OfficeCanvas layout={layout} employees={employees} bubbles={bubbles} pendingApprovals={pendingApprovals}
                selectedId={liveSelected?.id ?? null} onSelect={setSelected} />
            </div>
          </div>
        ) : <div className="px-panel p-10 text-center">오피스를 불러오는 중…</div>}
        <p className="text-[11px] text-cream/50">직원을 클릭하면 프로필과 개인 메시지 창이 열립니다. 회의가 시작되면 참석자들이 회의실로 이동합니다. 라운지의 결재함이 깜빡이면 CEO 결재가 필요합니다.</p>
      </section>

      <aside className="w-[380px] shrink-0 bg-panel border-l-2 border-black flex flex-col">
        {liveSelected ? (
          <EmployeePanel employee={liveSelected} onClose={() => setSelected(null)} />
        ) : (
          <>
            <div className="p-3 border-b-2 border-black flex items-center gap-2">
              <b className="px-title">오피스 대화</b>
              <select className="px-input !py-1 ml-auto text-[12px]" value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="all">전체 채널</option>
                {channels.filter((c) => c.kind !== "dm").map((c) => <option key={c.id} value={c.id}>#{c.name}</option>)}
              </select>
            </div>
            <div className="flex-1 overflow-auto px-3 flex flex-col-reverse">
              <div>{feed.length ? feed.map((m) => <MessageItem key={m.id} m={m} />) : <p className="py-6 text-cream/50">아직 대화가 없습니다. 업무를 지시해 보세요.</p>}</div>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
