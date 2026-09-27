"use client";

import { useState } from "react";
import Avatar from "@/components/ui/Avatar";
import Page from "@/components/ui/Page";
import EmployeePanel from "@/components/office/EmployeePanel";
import { useOffice } from "@/components/OfficeProvider";
import type { Employee } from "@/lib/types";

export default function Agents() {
  const { layout, employees } = useOffice();
  const [sel, setSel] = useState<Employee | null>(null);
  if (!layout) return null;
  const live = sel ? employees.find((e) => e.id === sel.id) || sel : null;
  return (
    <div className="flex h-full">
      <div className="flex-1 overflow-auto">
        <Page title="직원 (Agents)" subtitle="7개 부서 · 부서마다 3명 이상. 각 직원은 전문 에이전트이며 클릭해서 개인 메시지를 보낼 수 있습니다.">
          {Object.entries(layout.departments).map(([key, label]) => (
            <div key={key} className="px-panel p-3">
              <b className="px-title">{label}</b>
              <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-2 mt-2">
                {employees.filter((e) => e.department === key).map((e) => (
                  <button key={e.id} onClick={() => setSel(e)} className={`px-panel-2 p-2 text-left flex gap-2 ${live?.id === e.id ? "ring-2 ring-accent" : ""}`}>
                    <Avatar employee={e} size={40} />
                    <div className="min-w-0">
                      <div><b>{e.name}</b> {e.title} {e.is_lead && <span className="px-tag bg-accent text-ink">팀장</span>}</div>
                      <div className="text-[11px] text-cream/70 truncate">{e.role}</div>
                      <div className="text-[11px] truncate">{e.status === "working" ? "🟢" : e.status === "meeting" ? "🔴" : "⚪"} {e.status_text}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </Page>
      </div>
      {live && <aside className="fixed inset-0 z-40 lg:static w-full lg:w-[380px] shrink-0 bg-panel border-l-2 border-black"><EmployeePanel employee={live} onClose={() => setSel(null)} /></aside>}
    </div>
  );
}
