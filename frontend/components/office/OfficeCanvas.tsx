"use client";

import { useEffect, useRef } from "react";
import type { Employee, Layout, Room } from "@/lib/types";
import {
  T, doorOf, drawBookshelf, drawCeoDesk, drawChair, drawCharacter, drawCooler, drawDesk, drawFloor, drawInbox,
  drawMeetingTable, drawPlant, drawSofa, drawStatusIcon, drawWalls, drawWhiteboard, meetingSeats, type Facing,
} from "./sprites";

export interface Bubble { employeeId: number; text: string; kind: string }

interface Actor {
  x: number; y: number; path: { x: number; y: number }[]; facing: Facing; frame: number; lastStep: number;
  bubble?: { text: string; kind: string; until: number }; wanderUntil?: number; nextWander: number; seatFacing: Facing;
}

const SPEED = 80; // world px per second

function roomAt(rooms: Room[], x: number, y: number): Room | null {
  const tx = x / T, ty = y / T;
  return rooms.find((r) => tx >= r.x && tx < r.x + r.w && ty >= r.y && ty < r.y + r.h) || null;
}
const corridorRow = (r: Room) => (r.y < 9 ? 9 : r.y < 18 ? 9 : 18);
const center = (t: number) => (t + 0.5) * T;

function route(rooms: Room[], from: { x: number; y: number }, to: { x: number; y: number }) {
  const rf = roomAt(rooms, from.x, from.y), rt = roomAt(rooms, to.x, to.y);
  const pts: { x: number; y: number }[] = [];
  if (rf && rt && rf.key === rt.key) {
    pts.push({ x: to.x, y: from.y }, to);
    return pts;
  }
  let row = rf ? corridorRow(rf) : Math.round(from.y / T - 0.5);
  if (rf) {
    const d = doorOf(rf);
    pts.push({ x: center(d.x) - T / 2, y: from.y }, { x: center(d.x) - T / 2, y: center(row) });
  }
  if (rt) {
    const target = corridorRow(rt);
    if (target !== row) {
      const cur = pts.length ? pts[pts.length - 1].x : from.x;
      const gap = [16, 31].map(center).sort((a, b) => Math.abs(a - cur) - Math.abs(b - cur))[0];
      pts.push({ x: gap, y: center(row) }, { x: gap, y: center(target) });
      row = target;
    }
    const d = doorOf(rt);
    pts.push({ x: center(d.x) - T / 2, y: center(row) }, { x: center(d.x) - T / 2, y: to.y }, to);
  } else {
    pts.push({ x: to.x, y: center(row) }, to);
  }
  return pts;
}

function seatOf(e: Employee) { return { x: e.desk.x * T + 10, y: e.desk.y * T + 7 }; }

function wrapText(ctx: CanvasRenderingContext2D, text: string, max: number, lines = 2): string[] {
  const out: string[] = [];
  let cur = "";
  for (const ch of text.replace(/\s+/g, " ")) {
    if (ctx.measureText(cur + ch).width > max) {
      out.push(cur);
      cur = ch;
      if (out.length === lines) break;
    } else cur += ch;
  }
  if (out.length < lines && cur) out.push(cur);
  if (out.length === lines && text.length > out.join("").length) out[lines - 1] = out[lines - 1].slice(0, -1) + "…";
  return out;
}

export default function OfficeCanvas({ layout, employees, bubbles, pendingApprovals, selectedId, onSelect }: {
  layout: Layout; employees: Employee[]; bubbles: Bubble[]; pendingApprovals: boolean; selectedId: number | null;
  onSelect: (e: Employee | null) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const actors = useRef<Map<number, Actor>>(new Map());
  const empRef = useRef(employees);
  const hover = useRef<number | null>(null);
  const propsRef = useRef({ pendingApprovals, selectedId });
  const seenBubbles = useRef(0);
  empRef.current = employees;
  propsRef.current = { pendingApprovals, selectedId };

  const W = layout.map.width * T, H = layout.map.height * T;

  // new speech bubbles
  useEffect(() => {
    const fresh = bubbles.slice(seenBubbles.current);
    seenBubbles.current = bubbles.length;
    for (const b of fresh) {
      const a = actors.current.get(b.employeeId);
      if (a) a.bubble = { text: b.text, kind: b.kind, until: performance.now() + 5500 };
    }
  }, [bubbles]);

  useEffect(() => {
    const world = document.createElement("canvas");
    world.width = W; world.height = H;
    const wctx = world.getContext("2d")!;
    const staticLayer = document.createElement("canvas");
    staticLayer.width = W; staticLayer.height = H;
    const sctx = staticLayer.getContext("2d")!;
    const rooms = layout.rooms;
    const byKey = Object.fromEntries(rooms.map((r) => [r.key, r]));

    // ---- static layer ----
    sctx.fillStyle = "#3a3d52";
    sctx.fillRect(0, 0, W, H);
    for (let y = 0; y < layout.map.height; y++) for (let x = 0; x < layout.map.width; x++) {
      sctx.fillStyle = (x + y) % 2 ? "#44485f" : "#40445a";
      sctx.fillRect(x * T, y * T, T, T);
    }
    rooms.forEach((r) => drawFloor(sctx, r));
    rooms.forEach((r) => drawWalls(sctx, r));
    const ceo = byKey.ceo, meet = byKey.meeting, lounge = byKey.lounge;
    if (ceo) { drawCeoDesk(sctx, ceo); drawBookshelf(sctx, (ceo.x + 0.5) * T, (ceo.y + 0.2) * T); drawPlant(sctx, (ceo.x + ceo.w - 1.5) * T, (ceo.y + ceo.h - 2) * T); }
    if (meet) { drawWhiteboard(sctx, (meet.x + meet.w / 2 - 1.2) * T, (meet.y + 0.1) * T); drawMeetingTable(sctx, meet); drawPlant(sctx, (meet.x + 0.2) * T, (meet.y + meet.h - 2) * T); }
    if (lounge) { drawSofa(sctx, (lounge.x + 1) * T, (lounge.y + 5) * T); drawCooler(sctx, (lounge.x + lounge.w - 1.6) * T, (lounge.y + 0.6) * T); drawPlant(sctx, (lounge.x + 0.2) * T, (lounge.y + 0.3) * T); }
    rooms.filter((r) => !["ceo", "meeting", "lounge"].includes(r.key)).forEach((r, i) => {
      drawPlant(sctx, (r.x + r.w - 1.3) * T, (r.y + r.h - 2) * T);
      if (i % 2 === 0) drawBookshelf(sctx, (r.x + r.w - 2.2) * T, (r.y + 0.2) * T);
    });
    const seats = meet ? meetingSeats(meet) : [];

    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let raf = 0, last = performance.now(), scale = 1, dpr = 1;

    const resize = () => {
      const w = wrapRef.current!.clientWidth;
      dpr = window.devicePixelRatio || 1;
      scale = w / W;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${H * scale}px`;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(H * scale * dpr);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrapRef.current!);

    const targetFor = (e: Employee, now: number, meetingIndex: Map<number, number>): { x: number; y: number; facing: Facing } => {
      if (e.status === "meeting" && meetingIndex.has(e.id) && seats.length) {
        const s = seats[meetingIndex.get(e.id)! % seats.length];
        return { x: s.x, y: s.y, facing: s.facing };
      }
      const a = actors.current.get(e.id);
      if (e.status === "idle" && a?.wanderUntil && a.wanderUntil > now && lounge) {
        const i = e.id % 5;
        return { x: (lounge.x + 1.5 + i) * T, y: (lounge.y + 3.6 + (i % 2) * 0.6) * T, facing: "down" };
      }
      const s = seatOf(e);
      return { ...s, facing: "down" };
    };

    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const emps = empRef.current;
      const meetingIndex = new Map<number, number>();
      emps.filter((e) => e.status === "meeting").sort((a, b) => a.id - b.id).forEach((e, i) => meetingIndex.set(e.id, i));

      // ---- simulation ----
      for (const e of emps) {
        let a = actors.current.get(e.id);
        const seat = seatOf(e);
        if (!a) {
          a = { x: seat.x, y: seat.y, path: [], facing: "down", frame: 0, lastStep: now, nextWander: now + 8000 + Math.random() * 30000, seatFacing: "down" };
          actors.current.set(e.id, a);
        }
        if (e.status === "idle" && now > a.nextWander) {
          a.wanderUntil = now + 7000 + Math.random() * 6000;
          a.nextWander = now + 25000 + Math.random() * 40000;
        }
        const tgt = targetFor(e, now, meetingIndex);
        const end = a.path.length ? a.path[a.path.length - 1] : { x: a.x, y: a.y };
        if (Math.hypot(end.x - tgt.x, end.y - tgt.y) > 1) a.path = route(rooms, { x: a.x, y: a.y }, tgt);
        a.seatFacing = tgt.facing;
        let budget = SPEED * dt;
        while (budget > 0 && a.path.length) {
          const p = a.path[0];
          const dx = p.x - a.x, dy = p.y - a.y, dist = Math.hypot(dx, dy);
          if (dist <= budget) { a.x = p.x; a.y = p.y; a.path.shift(); budget -= dist; }
          else {
            a.x += (dx / dist) * budget; a.y += (dy / dist) * budget; budget = 0;
            a.facing = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up");
          }
          if (now - a.lastStep > 160) { a.frame++; a.lastStep = now; }
        }
      }

      // ---- world render (1x) ----
      wctx.imageSmoothingEnabled = false;
      wctx.drawImage(staticLayer, 0, 0);
      if (lounge) drawInbox(wctx, (lounge.x + 3.2) * T, (lounge.y + 1.2) * T, propsRef.current.pendingApprovals, now);
      type Drawable = { y: number; draw: () => void };
      const items: Drawable[] = [];
      for (const e of emps) {
        const d = e.desk;
        const working = e.status === "working" && actors.current.get(e.id)?.path.length === 0;
        items.push({ y: d.y * T + 9, draw: () => drawDesk(wctx, d.x, d.y, working, now) });
        items.push({ y: d.y * T - 1, draw: () => drawChair(wctx, d.x * T + 10, d.y * T + 3) });
      }
      for (const e of emps) {
        const a = actors.current.get(e.id)!;
        const walking = a.path.length > 0;
        const atSeat = !walking;
        const typing = atSeat && e.status === "working";
        items.push({
          y: a.y,
          draw: () => {
            drawCharacter(wctx, a.x, a.y, e.appearance, {
              facing: walking ? a.facing : a.seatFacing, walking, frame: a.frame,
              bob: typing ? (Math.floor(now / 220 + e.id) % 2 ? -1 : 0) : 0,
              highlight: propsRef.current.selectedId === e.id || hover.current === e.id,
            });
            if (!walking) drawStatusIcon(wctx, a.x, a.y - 16, e.status, now + e.id * 97);
          },
        });
      }
      items.sort((p, q) => p.y - q.y).forEach((i) => i.draw());

      // ---- screen render ----
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(world, 0, 0, canvas.width, canvas.height);
      const k = scale * dpr;
      ctx.textBaseline = "alphabetic";
      // room labels
      ctx.font = `${Math.round(11 * dpr)}px Galmuri11, monospace`;
      for (const r of rooms) {
        const label = r.name;
        const x = (r.x * T + 2) * k, y = (r.y * T - 2) * k;
        const w = ctx.measureText(label).width + 8 * dpr;
        ctx.fillStyle = "rgba(16,17,26,0.85)";
        ctx.fillRect(x, y - 13 * dpr, w, 16 * dpr);
        ctx.fillStyle = r.key === "ceo" ? "#ffcc4d" : "#f4ecd8";
        ctx.fillText(label, x + 4 * dpr, y);
      }
      // name tags + bubbles
      ctx.font = `${Math.round(11 * dpr)}px Galmuri11, monospace`;
      for (const e of emps) {
        const a = actors.current.get(e.id)!;
        const sx = a.x * k, sy = (a.y - 17) * k;
        if (hover.current === e.id || propsRef.current.selectedId === e.id) {
          const tag = `${e.name} ${e.title}`;
          const w = ctx.measureText(tag).width + 8 * dpr;
          ctx.fillStyle = "rgba(16,17,26,0.9)";
          ctx.fillRect(sx - w / 2, (a.y + 2) * k, w, 15 * dpr);
          ctx.fillStyle = "#ffcc4d";
          ctx.fillText(tag, sx - w / 2 + 4 * dpr, (a.y + 2) * k + 12 * dpr);
        }
        if (a.bubble && a.bubble.until > now) {
          const maxW = 150 * dpr;
          const lines = wrapText(ctx, a.bubble.text, maxW);
          const bw = Math.min(maxW, Math.max(...lines.map((l) => ctx.measureText(l).width))) + 12 * dpr;
          const bh = lines.length * 14 * dpr + 8 * dpr;
          const bx = Math.max(2, Math.min(canvas.width - bw - 2, sx - bw / 2)), by = sy - bh - 10 * dpr;
          const color = a.bubble.kind.startsWith("approval") ? "#ffcc4d" : a.bubble.kind === "meeting" ? "#fda4af" : "#f4ecd8";
          ctx.fillStyle = "#0e0f16";
          ctx.fillRect(bx - 2 * dpr, by - 2 * dpr, bw + 4 * dpr, bh + 4 * dpr);
          ctx.fillStyle = color;
          ctx.fillRect(bx, by, bw, bh);
          ctx.beginPath();
          ctx.moveTo(sx - 5 * dpr, by + bh); ctx.lineTo(sx + 5 * dpr, by + bh); ctx.lineTo(sx, by + bh + 7 * dpr); ctx.fill();
          ctx.fillStyle = "#1b1d2a";
          lines.forEach((l, i) => ctx.fillText(l, bx + 6 * dpr, by + 16 * dpr + i * 14 * dpr - 4 * dpr));
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    const pick = (ev: MouseEvent): Employee | null => {
      const rect = canvas.getBoundingClientRect();
      const wx = (ev.clientX - rect.left) / scale, wy = (ev.clientY - rect.top) / scale;
      let best: Employee | null = null, bestD = 14;
      for (const e of empRef.current) {
        const a = actors.current.get(e.id);
        if (!a) continue;
        const d = Math.hypot(wx - a.x, wy - (a.y - 8));
        if (d < bestD) { best = e; bestD = d; }
      }
      return best;
    };
    const onMove = (ev: MouseEvent) => {
      const e = pick(ev);
      hover.current = e?.id ?? null;
      canvas.style.cursor = e ? "pointer" : "default";
    };
    const onClick = (ev: MouseEvent) => onSelect(pick(ev));
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("click", onClick);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("click", onClick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout]);

  return (
    <div ref={wrapRef} className="w-full">
      <canvas ref={canvasRef} className="block shadow-pixel" aria-label="픽셀 오피스: 직원을 클릭하면 프로필과 DM 창이 열립니다" />
    </div>
  );
}
