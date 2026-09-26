"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Page from "@/components/ui/Page";
import { useOffice } from "@/components/OfficeProvider";
import { api } from "@/lib/api";
import { STATUS_KO, bar, timeAgo } from "@/lib/labels";
import type { Task } from "@/lib/types";

const COLUMNS = ["BACKLOG", "PLANNED", "RESEARCHING", "ANALYZING", "WRITING", "REVIEWING", "WAITING_USER", "DONE", "FAILED"];

export default function Tasks() {
  const { tasks: live } = useOffice();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [view, setView] = useState<"list" | "board">("list");
  useEffect(() => { api<Task[]>("/api/tasks?limit=200").then(setTasks); }, [live]);
  return (
    <Page title="작업 (Tasks)" subtitle="모든 업무는 Task로 관리됩니다 — 상태, 우선순위, 마감, 참여 부서, 산출물, 감사 로그"
      actions={<div className="flex gap-2"><button className={view === "list" ? "px-btn" : "px-btn-ghost"} onClick={() => setView("list")}>목록</button><button className={view === "board" ? "px-btn" : "px-btn-ghost"} onClick={() => setView("board")}>보드</button></div>}>
      {view === "list" ? (
        <div className="px-panel">
          <table className="w-full text-[12.5px]">
            <thead className="bg-ink"><tr>{["#", "제목", "상태", "진행", "우선순위", "마감", "참여", "생성"].map((h) => <th key={h} className="text-left p-2">{h}</th>)}</tr></thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id} className="border-t border-black/40 hover:bg-panel2">
                  <td className="p-2">{t.id}</td>
                  <td className="p-2 max-w-md truncate"><Link className="underline text-sky" href={`/tasks/${t.id}`}>{t.title}</Link></td>
                  <td className="p-2">{STATUS_KO[t.status]}</td>
                  <td className="p-2 font-pixel text-mint whitespace-nowrap">{bar(t.progress)} {Math.round(t.progress)}%</td>
                  <td className="p-2">P{t.priority}</td>
                  <td className="p-2">{t.deadline ? new Date(t.deadline).toLocaleDateString("ko-KR") : "-"}</td>
                  <td className="p-2 text-[11px]">{t.agents.join(", ")}</td>
                  <td className="p-2">{timeAgo(t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!tasks.length && <p className="p-6 text-cream/50">아직 작업이 없습니다. 오피스 화면에서 지시해 보세요.</p>}
        </div>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {COLUMNS.map((c) => (
            <div key={c} className="w-56 shrink-0 px-panel p-2">
              <div className="text-accent mb-2">{STATUS_KO[c]} <span className="text-cream/50">{tasks.filter((t) => t.status === c).length}</span></div>
              {tasks.filter((t) => t.status === c).map((t) => (
                <Link key={t.id} href={`/tasks/${t.id}`} className="block px-panel-2 p-2 mb-2 text-[12px] hover:bg-line">
                  <div className="truncate">#{t.id} {t.title}</div>
                  <div className="font-pixel text-mint text-[11px]">{bar(t.progress, 8)}</div>
                </Link>
              ))}
            </div>
          ))}
        </div>
      )}
    </Page>
  );
}
