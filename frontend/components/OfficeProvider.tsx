"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, eventStreamUrl, getToken } from "@/lib/api";
import type { Channel, Employee, Layout, Message, Notification, Task } from "@/lib/types";

interface OfficeState {
  layout: Layout | null;
  employees: Employee[];
  channels: Channel[];
  messages: Message[];
  tasks: Task[];
  pendingApprovals: boolean;
  toasts: Notification[];
  connected: boolean;
  dismissToast: (id: number) => void;
  refresh: () => Promise<void>;
  empById: (id: number | null | undefined) => Employee | undefined;
}

const Ctx = createContext<OfficeState | null>(null);

export function useOffice(): OfficeState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useOffice outside provider");
  return v;
}

export default function OfficeProvider({ children }: { children: React.ReactNode }) {
  const [layout, setLayout] = useState<Layout | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [pendingApprovals, setPending] = useState(false);
  const [toasts, setToasts] = useState<Notification[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    const [l, ch, msgs, ts] = await Promise.all([
      api<Layout>("/api/office/layout"), api<Channel[]>("/api/office/channels"),
      api<Message[]>("/api/office/messages?limit=300&include_dm=true"), api<Task[]>("/api/tasks?limit=30"),
    ]);
    setLayout(l); setEmployees(l.employees); setChannels(ch); setMessages(msgs); setTasks(ts);
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    refresh().catch(() => undefined);
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      const es = new EventSource(eventStreamUrl());
      esRef.current = es;
      es.onopen = () => setConnected(true);
      es.onerror = () => { setConnected(false); es.close(); retry = setTimeout(connect, 3000); };
      es.addEventListener("message", (ev) => {
        const m = JSON.parse((ev as MessageEvent).data) as Message;
        setMessages((prev) => (prev.some((x) => x.id === m.id) ? prev : [...prev.slice(-800), m]));
      });
      es.addEventListener("state", (ev) => {
        const s = JSON.parse((ev as MessageEvent).data);
        setEmployees((prev) => prev.map((e) => ({ ...e, ...(s.employees.find((x: Employee) => x.id === e.id) || {}) })));
        setTasks(s.tasks);
        setPending(s.pending_approvals);
      });
      es.addEventListener("notification", (ev) => {
        const n = JSON.parse((ev as MessageEvent).data) as Notification;
        setToasts((t) => [...t, n]);
        try {
          if ("Notification" in window && Notification.permission === "granted" && document.visibilityState !== "visible") {
            const native = new Notification(n.title, { body: n.body.slice(0, 200), tag: `office-${n.id}` });
            native.onclick = () => { window.focus(); if (n.link) window.location.href = n.link; };
          }
        } catch { /* notifications unavailable */ }
        setTimeout(() => setToasts((t) => t.filter((x) => x.id !== n.id)), 12000);
      });
    };
    connect();
    return () => { clearTimeout(retry); esRef.current?.close(); };
  }, [refresh]);

  const empById = useCallback((id: number | null | undefined) => employees.find((e) => e.id === id), [employees]);
  const dismissToast = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));

  return (
    <Ctx.Provider value={{ layout, employees, channels, messages, tasks, pendingApprovals, toasts, connected, dismissToast, refresh, empById }}>
      {children}
    </Ctx.Provider>
  );
}
