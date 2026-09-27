"use client";

import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { api, fileUrl } from "@/lib/api";
import { RISK_COLOR } from "@/lib/labels";

const LAYERS = ["preference", "interest", "project", "company", "person", "document", "decision", "task", "fact", "temporary"];

export default function Settings() {
  const [s, setS] = useState<any>(null);
  const [plugins, setPlugins] = useState<any[]>([]);
  const [tools, setTools] = useState<any[]>([]);
  const [memory, setMemory] = useState<any[]>([]);
  const [templates, setTemplates] = useState<any[]>([]);
  const [mem, setMem] = useState({ layer: "preference", key: "", value: "" });
  const [brief, setBrief] = useState<any>(null);
  const [schedules, setSchedules] = useState<any[]>([]);
  const [sch, setSch] = useState({ name: "", kind: "daily_briefing", frequency: "daily", time_of_day: "08:00", weekday: 0, request: "" });
  const [profiles, setProfiles] = useState<string[]>([]);
  const [notif, setNotif] = useState<string>(typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unsupported");
  const load = () => {
    api("/api/settings").then(setS); api<any[]>("/api/plugins").then(setPlugins); api<any[]>("/api/tools").then(setTools);
    api<any[]>("/api/memory").then(setMemory); api<any[]>("/api/templates").then(setTemplates);
    api<any[]>("/api/schedules").then(setSchedules); api<any>("/api/browser/profiles").then((r) => setProfiles(r.profiles));
  };
  useEffect(load, []);
  const addMem = async (e: React.FormEvent) => { e.preventDefault(); await api("/api/memory", { method: "POST", json: mem }); setMem({ ...mem, key: "", value: "" }); load(); };
  const addTemplate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    await api("/api/templates", { method: "POST", body: new FormData(e.currentTarget) });
    e.currentTarget.reset(); load();
  };
  const addSchedule = async (e: React.FormEvent) => {
    e.preventDefault();
    const { request, ...rest } = sch;
    await api("/api/schedules", { method: "POST", json: { ...rest, weekday: Number(rest.weekday), payload: rest.kind === "research_task" ? { request } : {} } });
    setSch({ ...sch, name: "", request: "" }); load();
  };
  const addProfile = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const file = fd.get("file") as File;
    await api("/api/browser/profiles", { method: "POST", json: { name: fd.get("name"), storage_state: JSON.parse(await file.text()) } });
    e.currentTarget.reset(); load();
  };
  return (
    <Page title="설정" subtitle="모델 라우터 · 플러그인 · 도구 위험도 · 메모리 · 템플릿 · 브리핑">
      {s && (
        <div className="px-panel p-3 grid md:grid-cols-2 gap-3 text-[12.5px]">
          <div><b className="px-title">Model Router</b>
            <div>LLM: <b>{s.llm_provider}</b> {s.llm_provider === "offline" && <span className="text-rose">— ANTHROPIC_API_KEY 미설정: 추출·규칙 기반 모드 (근거 없는 문장은 생성하지 않음)</span>}</div>
            {Object.entries(s.models).map(([tier, m]: any) => <div key={tier}>{tier} → {m}</div>)}
            <div className="text-cream/60 mt-1">{Object.entries(s.routing).map(([k, v]: any) => `${k}:${v}`).join(" · ")}</div>
            <div>사용량: {s.usage.calls}회 / 입력 {s.usage.input_tokens} / 출력 {s.usage.output_tokens} 토큰</div>
          </div>
          <div><b className="px-title">Research</b>
            <div>검색 제공자: <b>{s.search_provider || "미설정"}</b></div><div>임베딩: {s.embedding_provider}</div>
            <div>DB: {s.database} · 워커: {s.inline_worker ? "API 내장" : "별도 프로세스"}</div>
            <div>오래된 자료 기준: {s.stale_after_years}년 · 최소 검증 비율: {Math.round(s.min_verified_ratio * 100)}% · 최대 조사 라운드: {s.max_research_rounds}</div>
          </div>
        </div>
      )}
      <div className="px-panel p-3">
        <b className="px-title">Daily CEO Briefing · Weekly Business Review</b>
        <div className="flex gap-2 mt-2">
          <button className="px-btn" onClick={() => api("/api/briefing/daily", { method: "POST" }).then(setBrief)}>오늘의 브리핑</button>
          <button className="px-btn-ghost" onClick={() => api("/api/briefing/weekly", { method: "POST" }).then(setBrief)}>주간 리뷰</button>
          {brief && <a className="underline text-sky self-center" href={fileUrl(`/api/artifacts/${brief.artifact_id}/download`)}>DOCX 다운로드</a>}
        </div>
        {brief && <pre className="whitespace-pre-wrap font-body text-[12.5px] mt-2 bg-ink p-3 max-h-96 overflow-auto">{brief.markdown}</pre>}
      </div>
      <div className="px-panel p-3 text-[12.5px]">
        <b className="px-title">예약 자동화</b> <span className="text-[11px] text-cream/60">데일리 브리핑 · 주간 리뷰 · 기회 스캔 · 반복 조사. 외부 발송 같은 HIGH 작업은 예약되지 않고 항상 결재를 거칩니다.</span>
        <form onSubmit={addSchedule} className="flex gap-2 mt-2 flex-wrap">
          <input className="px-input" required placeholder="이름" value={sch.name} onChange={(e) => setSch({ ...sch, name: e.target.value })} />
          <select className="px-input" value={sch.kind} onChange={(e) => setSch({ ...sch, kind: e.target.value })}>
            <option value="daily_briefing">데일리 CEO 브리핑</option><option value="weekly_review">주간 비즈니스 리뷰</option>
            <option value="opportunity_scan">기회 스캔</option><option value="research_task">반복 조사</option></select>
          <select className="px-input" value={sch.frequency} onChange={(e) => setSch({ ...sch, frequency: e.target.value })}><option value="daily">매일</option><option value="weekly">매주</option><option value="hourly">매시간</option></select>
          {sch.frequency === "weekly" && <select className="px-input" value={sch.weekday} onChange={(e) => setSch({ ...sch, weekday: Number(e.target.value) })}>{"월화수목금토일".split("").map((d, i) => <option key={i} value={i}>{d}요일</option>)}</select>}
          {sch.frequency !== "hourly" && <input className="px-input w-24" type="time" value={sch.time_of_day} onChange={(e) => setSch({ ...sch, time_of_day: e.target.value })} />}
          {sch.kind === "research_task" && <input className="px-input flex-1" required placeholder="조사 지시 내용" value={sch.request} onChange={(e) => setSch({ ...sch, request: e.target.value })} />}
          <button className="px-btn">추가</button>
        </form>
        {schedules.map((x) => (
          <div key={x.id} className="flex gap-2 items-center border-b border-black/30 py-1 flex-wrap">
            <b>{x.name}</b><span className="px-tag bg-ink">{x.kind}</span><span>{x.frequency} {x.frequency !== "hourly" ? x.time_of_day : ""}</span>
            <span className="text-cream/50">다음 {x.next_run_at ? new Date(x.next_run_at).toLocaleString("ko-KR") : "-"} · 최근 {x.last_result || "-"}</span>
            <span className="ml-auto flex gap-1">
              <button className="px-btn-ghost !py-0.5" onClick={() => api(`/api/schedules/${x.id}/run`, { method: "POST" }).then(load)}>지금 실행</button>
              <button className="px-btn-ghost !py-0.5" onClick={() => api(`/api/schedules/${x.id}?enabled=${!x.enabled}`, { method: "PATCH" }).then(load)}>{x.enabled ? "끄기" : "켜기"}</button>
              <button className="px-btn-danger !py-0.5" onClick={() => api(`/api/schedules/${x.id}`, { method: "DELETE" }).then(load)}>삭제</button>
            </span>
          </div>
        ))}
      </div>
      <div className="px-panel p-3 text-[12.5px] grid md:grid-cols-2 gap-3">
        <div>
          <b className="px-title">알림</b>
          <div className="mt-1">브라우저 알림: <b>{notif}</b></div>
          {notif !== "granted" && notif !== "unsupported" && <button className="px-btn mt-2" onClick={() => Notification.requestPermission().then(setNotif)}>작업 완료 알림 켜기</button>}
        </div>
        <div>
          <b className="px-title">브라우저 로그인 세션</b>
          <p className="text-[11px] text-cream/60">로그인 후 작업이 필요한 사이트는 Playwright storage_state JSON(쿠키)을 등록합니다. 비밀번호는 저장하지 않습니다.</p>
          <form onSubmit={addProfile} className="flex gap-2 mt-1 flex-wrap"><input name="name" required className="px-input" placeholder="세션 이름" /><input name="file" type="file" accept=".json" required className="text-[11px]" /><button className="px-btn">등록</button></form>
          <div className="mt-1">{profiles.join(", ") || "등록된 세션 없음"}</div>
        </div>
      </div>
      <div className="px-panel p-3">
        <b className="px-title">플러그인</b> <span className="text-[11px] text-cream/60">자격 증명은 환경변수로만 설정합니다</span>
        <div className="grid md:grid-cols-3 gap-2 mt-2">{plugins.map((p) => (
          <div key={p.key} className="px-panel-2 p-2 text-[12px]"><b>{p.name}</b> {p.configured ? <span className="px-tag bg-mint text-ink">연결됨</span> : <span className="px-tag bg-ink">미연결</span>}
            <div className="text-cream/60">{p.env.join(", ")}</div>
            {p.actions.map((a: any) => <div key={a.name}><span className={`px-tag ${RISK_COLOR[a.risk]}`}>{a.risk}</span> {a.description}</div>)}
          </div>))}</div>
      </div>
      <div className="px-panel p-3 text-[12px]"><b className="px-title">도구 위험도</b> — HIGH 이상은 CEO 결재 후 실행
        <div className="grid md:grid-cols-3 gap-1 mt-2">{tools.map((t) => <div key={t.name}><span className={`px-tag ${RISK_COLOR[t.risk]}`}>{t.risk}</span> {t.name}</div>)}</div>
      </div>
      <div className="px-panel p-3">
        <b className="px-title">메모리</b> <span className="text-[11px] text-cream/60">명시적으로 저장한 정보(explicit)와 자동 저장(auto: 완료 작업·결정)을 구분합니다. temporary는 24시간 후 만료.</span>
        <form onSubmit={addMem} className="flex gap-2 mt-2">
          <select className="px-input" value={mem.layer} onChange={(e) => setMem({ ...mem, layer: e.target.value })}>{LAYERS.map((l) => <option key={l}>{l}</option>)}</select>
          <input className="px-input" required placeholder="키" value={mem.key} onChange={(e) => setMem({ ...mem, key: e.target.value })} />
          <input className="px-input flex-1" required placeholder="값" value={mem.value} onChange={(e) => setMem({ ...mem, value: e.target.value })} />
          <button className="px-btn">저장</button>
        </form>
        <div className="mt-2 text-[12px]">{memory.map((m) => (
          <div key={m.id} className="flex gap-2 border-b border-black/30 py-1"><span className="px-tag bg-ink">{m.layer}</span><span className="px-tag bg-ink">{m.origin}</span><b>{m.key}</b> {m.value}
            <button className="ml-auto text-rose" onClick={() => api(`/api/memory/${m.id}`, { method: "DELETE" }).then(load)}>삭제</button></div>))}</div>
      </div>
      <div className="px-panel p-3">
        <b className="px-title">템플릿</b>
        <div className="grid md:grid-cols-3 gap-2 mt-2 text-[12px]">{templates.map((t) => <div key={t.id} className="px-panel-2 p-2"><b>{t.name}</b> <span className="text-cream/60">{t.kind}{t.has_file ? " · 파일" : ""}</span><div className="text-cream/70">{(t.structure.sections || []).join(" → ")}</div></div>)}</div>
        <form onSubmit={addTemplate} className="flex gap-2 mt-3 flex-wrap text-[12px]">
          <input name="name" required className="px-input" placeholder="템플릿 이름" />
          <select name="kind" className="px-input"><option value="report">보고서</option><option value="business_plan">사업계획서</option><option value="pitch_deck">투자자 PPT</option><option value="minutes">회의록</option><option value="weekly">주간보고</option></select>
          <textarea name="sections" className="px-input flex-1" rows={2} placeholder="섹션 제목 (한 줄에 하나)" />
          <input name="file" type="file" accept=".docx,.pptx" className="text-[11px]" />
          <button className="px-btn">등록</button>
        </form>
      </div>
    </Page>
  );
}
