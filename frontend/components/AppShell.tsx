"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import OfficeProvider, { useOffice } from "@/components/OfficeProvider";
import { getToken, setToken } from "@/lib/api";

const NAV = [
  ["/", "🏢", "오피스"], ["/tasks", "📋", "작업"], ["/approvals", "📝", "결재함"], ["/research", "🔎", "지식베이스"],
  ["/projects", "📁", "프로젝트"], ["/documents", "📄", "문서"], ["/sources", "🔗", "출처"], ["/agents", "👥", "직원"],
  ["/meetings", "🗓️", "회의"], ["/activity", "📜", "활동 기록"], ["/settings", "⚙️", "설정"],
] as const;

function Sidebar() {
  const path = usePathname();
  const { pendingApprovals, connected, tasks } = useOffice();
  const active = tasks.filter((t) => !["DONE", "FAILED", "WAITING_USER"].includes(t.status)).length;
  return (
    <aside className="w-44 shrink-0 bg-ink border-r-2 border-black flex flex-col">
      <div className="p-3 border-b-2 border-black">
        <div className="px-title text-[15px] leading-tight">PERSONAL<br />AI OFFICE</div>
        <div className="text-[11px] mt-1 flex items-center gap-1 text-cream/70">
          <span className={`w-2 h-2 ${connected ? "bg-mint" : "bg-rose"}`} /> {connected ? "실시간 연결" : "연결 중…"}
        </div>
      </div>
      <nav className="flex-1 py-2">
        {NAV.map(([href, icon, label]) => {
          const on = href === "/" ? path === "/" : path.startsWith(href);
          return (
            <Link key={href} href={href} className={`flex items-center gap-2 px-3 py-2 ${on ? "bg-panel2 text-accent" : "hover:bg-panel"}`}>
              <span>{icon}</span><span>{label}</span>
              {href === "/approvals" && pendingApprovals && <span className="ml-auto px-tag bg-accent text-ink">!</span>}
              {href === "/tasks" && active > 0 && <span className="ml-auto px-tag bg-mint text-ink">{active}</span>}
            </Link>
          );
        })}
      </nav>
      <button className="m-3 px-btn-ghost justify-center" onClick={() => { setToken(null); location.href = "/login"; }}>로그아웃</button>
    </aside>
  );
}

function Toasts() {
  const { toasts, dismissToast } = useOffice();
  return (
    <div className="fixed right-4 bottom-4 z-50 flex flex-col gap-2 w-80">
      {toasts.map((t) => (
        <div key={t.id} className="px-panel p-3">
          <div className="flex justify-between"><b className="text-accent">🔔 {t.title}</b><button onClick={() => dismissToast(t.id)}>✕</button></div>
          <pre className="whitespace-pre-wrap text-[12px] mt-1 font-body">{t.body}</pre>
          {t.task_id && <Link className="underline text-sky text-[12px]" href={`/tasks/${t.task_id}`}>결과 보기 →</Link>}
        </div>
      ))}
    </div>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (path !== "/login" && !getToken()) router.replace("/login");
    else setReady(true);
  }, [path, router]);
  if (path === "/login") return <>{children}</>;
  if (!ready) return null;
  return (
    <OfficeProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
      <Toasts />
    </OfficeProvider>
  );
}
