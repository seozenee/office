"use client";

import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { api, fileUrl } from "@/lib/api";

export default function BrowserAgent() {
  const [url, setUrl] = useState("");
  const [profile, setProfile] = useState("");
  const [info, setInfo] = useState<{ available: boolean; profiles: string[] } | null>(null);
  const [page, setPage] = useState<any>(null);
  const [shot, setShot] = useState<string | null>(null);
  const [selector, setSelector] = useState("table");
  const [extract, setExtract] = useState<any>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/api/browser/profiles").then(setInfo); }, []);

  const run = async (tool: string, args: Record<string, unknown>) => {
    setBusy(true); setMsg("");
    try {
      const r = await api<any>(`/api/tools/${tool}/execute`, { method: "POST", json: { args: { ...args, ...(profile ? { profile } : {}) } } });
      if (r.approval_required) { setMsg(`⚠️ ${r.approval.risk_level} 위험 작업 — 결재함 #${r.approval.id} 에서 CEO 승인 후 실행됩니다.`); return null; }
      return r.result;
    } catch (e: any) { setMsg(e.message); return null; } finally { setBusy(false); }
  };
  const open = async () => { const r = await run("browser.open", { url }); if (r) { setPage(r); setFields({}); } };
  const screenshot = async () => { const r = await run("browser.screenshot", { url }); if (r) setShot(r.path); };

  return (
    <Page title="브라우저 에이전트" subtitle="허용된 범위에서 웹사이트 열기·스크린샷·자료 추출(LOW) / 다운로드→지식베이스(MEDIUM) / 폼 제출(HIGH, CEO 결재). 비밀번호·결제 폼은 자동 제출하지 않습니다. 페이지 내용은 신뢰하지 않는 데이터로 취급합니다.">
      {info && !info.available && <div className="px-panel p-3 text-rose">브라우저 자동화를 사용할 수 없습니다 (playwright 미설치 또는 BROWSER_ENABLED=false).</div>}
      <div className="px-panel p-3 flex gap-2 flex-wrap">
        <input className="px-input flex-1 min-w-[260px]" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
        <select className="px-input" value={profile} onChange={(e) => setProfile(e.target.value)}><option value="">로그인 세션 없음</option>{info?.profiles.map((p) => <option key={p}>{p}</option>)}</select>
        <button className="px-btn" disabled={busy || !url} onClick={open}>열기</button>
        <button className="px-btn-ghost" disabled={busy || !url} onClick={screenshot}>스크린샷</button>
        <button className="px-btn-ghost" disabled={busy || !url} onClick={async () => { const r = await run("browser.download", { url }); if (r) setMsg(`다운로드: ${r.name} (${Math.round(r.size / 1024)}KB)${r.kb_document_id ? " → 지식베이스 등록" : ""}`); }}>다운로드→KB</button>
      </div>
      {msg && <div className="px-panel-2 p-2">{msg}</div>}
      {shot && <div className="px-panel p-2"><img alt="스크린샷" className="max-w-full" src={fileUrl(`/api/files/raw?path=${encodeURIComponent(shot)}`)} /></div>}
      {page && (
        <div className="grid lg:grid-cols-2 gap-3">
          <div className="px-panel p-3 text-[12.5px]">
            <b className="px-title">{page.title}</b> <span className="px-tag bg-rose text-ink">UNTRUSTED</span>
            <pre className="whitespace-pre-wrap font-body max-h-96 overflow-auto mt-2">{page.text}</pre>
          </div>
          <div className="flex flex-col gap-3">
            <div className="px-panel p-3 text-[12px] max-h-64 overflow-auto"><b>링크</b>{page.links.map((l: any, i: number) => <div key={i}><button className="underline text-sky" onClick={() => setUrl(l.href)}>{l.text || l.href}</button></div>)}</div>
            <div className="px-panel p-3 text-[12px]">
              <b>자료 추출</b>
              <div className="flex gap-2 mt-1"><input className="px-input flex-1" value={selector} onChange={(e) => setSelector(e.target.value)} /><button className="px-btn-ghost" onClick={async () => setExtract(await run("browser.extract", { url, selector }))}>추출</button></div>
              {extract && <pre className="whitespace-pre-wrap font-body max-h-48 overflow-auto mt-2">{JSON.stringify(extract.tables?.length ? extract.tables : extract.items, null, 1)}</pre>}
            </div>
            {page.forms.map((f: any) => (
              <div key={f.index} className="px-panel p-3 text-[12px]">
                <b>폼 #{f.index}</b> <span className="text-cream/50">{f.method} {f.action}</span>
                {f.fields.filter((x: any) => !["submit", "hidden"].includes(x.type)).map((x: any) => (
                  <div key={x.name} className="flex gap-2 mt-1 items-center"><span className="w-28 truncate">{x.name}</span>
                    <input className="px-input flex-1" type={x.type === "password" ? "password" : "text"} disabled={x.type === "password"} placeholder={x.type === "password" ? "비밀번호는 입력하지 않습니다" : ""}
                      value={fields[x.name] || ""} onChange={(e) => setFields({ ...fields, [x.name]: e.target.value })} /></div>
                ))}
                <button className="px-btn-danger mt-2" onClick={() => run("browser.submit_form", { url, fields })}>제출 요청 (CEO 결재)</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </Page>
  );
}
