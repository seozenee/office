// Procedural pixel-art sprites. Everything is drawn from code — no external image assets.
import type { Employee, Room } from "@/lib/types";

export const T = 16; // world tile size (px before scaling)

type Px = CanvasRenderingContext2D;

function shade(hex: string, amt: number): string {
  const n = parseInt(hex.slice(1), 16);
  const clamp = (v: number) => Math.max(0, Math.min(255, v));
  const r = clamp(((n >> 16) & 255) + amt), g = clamp(((n >> 8) & 255) + amt), b = clamp((n & 255) + amt);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}

function rect(ctx: Px, x: number, y: number, w: number, h: number, color: string) {
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
}

// ---------------------------------------------------------------------------------------------
// Characters (12 x 16 pixel grid)
// ---------------------------------------------------------------------------------------------
const BODY_DOWN = [
  "....HHHH....",
  "...HHHHHH...",
  "..HHHHHHHH..",
  "..HSSSSSSH..",
  "..SSESSESS..",
  "..SSSSSSSS..",
  "...SSMMSS...",
  "....SSSS....",
  "..BBBCCBBB..",
  ".BBBBCCBBBB.",
  ".SBBBBBBBBS.",
  ".SBBBBBBBBS.",
  "..PPPPPPPP..",
  "..PPP..PPP..",
  "..PPP..PPP..",
  "..FFF..FFF..",
];
const BODY_UP = [
  "....HHHH....",
  "...HHHHHH...",
  "..HHHHHHHH..",
  "..HHHHHHHH..",
  "..HHHHHHHH..",
  "..SHHHHHHS..",
  "...SSSSSS...",
  "....SSSS....",
  "..BBBBBBBB..",
  ".BBBBBBBBBB.",
  ".SBBBBBBBBS.",
  ".SBBBBBBBBS.",
  "..PPPPPPPP..",
  "..PPP..PPP..",
  "..PPP..PPP..",
  "..FFF..FFF..",
];
const BODY_SIDE = [
  "....HHHH....",
  "...HHHHHH...",
  "..HHHHHHHH..",
  "..HHHSSSSS..",
  "..HHSSSESS..",
  "..HSSSSSSS..",
  "...SSSSSM...",
  "....SSSS....",
  "...BBBBBB...",
  "..BBBBBBBB..",
  "..BBBSBBBB..",
  "..BBBSBBBB..",
  "...PPPPPP...",
  "...PPPPPP...",
  "...PP..PP...",
  "...FF..FF...",
];
const LEGS_WALK_A = ["..PPPPPPPP..", "..PPP...PP..", ".PPP....PP..", ".FFF....FF.."];
const LEGS_WALK_B = ["..PPPPPPPP..", "..PP...PPP..", "..PP....PPP.", "..FF....FFF."];
const LEGS_SIDE_A = ["...PPPPPP...", "..PPP..PP...", ".PPP....PP..", ".FF.....FF.."];

export type Facing = "down" | "up" | "left" | "right";

export function drawCharacter(ctx: Px, cx: number, footY: number, app: Employee["appearance"], opts: {
  facing: Facing; walking: boolean; frame: number; bob?: number; highlight?: boolean;
}) {
  const base = opts.facing === "up" ? BODY_UP : opts.facing === "down" ? BODY_DOWN : BODY_SIDE;
  let rows = [...base];
  if (opts.walking) {
    const legs = opts.facing === "left" || opts.facing === "right" ? (opts.frame % 2 ? LEGS_SIDE_A : BODY_SIDE.slice(12)) : (opts.frame % 2 ? LEGS_WALK_A : LEGS_WALK_B);
    rows = [...rows.slice(0, 12), ...legs];
  }
  const palette: Record<string, string> = {
    H: app.hair, S: app.skin, E: "#1a1a24", M: shade(app.skin, -40), B: app.shirt, C: shade(app.shirt, 40),
    P: "#2f3448", F: "#16171f",
  };
  const w = 12, h = 16;
  const x0 = Math.round(cx - w / 2);
  const y0 = Math.round(footY - h + (opts.bob || 0));
  const flip = opts.facing === "left";
  // shadow
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.fillRect(x0 + 2, footY - 1, w - 4, 2);
  // outline pass
  if (opts.highlight) {
    ctx.fillStyle = "#ffcc4d";
    for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
      if (rows[r][flip ? w - 1 - c : c] !== ".") ctx.fillRect(x0 + c - 1, y0 + r - 1, 3, 3);
    }
  }
  for (let r = 0; r < h; r++) {
    for (let c = 0; c < w; c++) {
      const ch = rows[r][flip ? w - 1 - c : c];
      if (ch === ".") continue;
      ctx.fillStyle = palette[ch] || "#f0f";
      ctx.fillRect(x0 + c, y0 + r, 1, 1);
    }
  }
  // hair styles
  const hair = app.hair;
  if (app.style === 1 && opts.facing !== "up") { // long hair
    rect(ctx, x0 + 1, y0 + 3, 1, 5, hair); rect(ctx, x0 + 10, y0 + 3, 1, 5, hair);
  } else if (app.style === 2) { // spiky
    rect(ctx, x0 + 3, y0 - 1, 1, 1, hair); rect(ctx, x0 + 6, y0 - 1, 1, 1, hair); rect(ctx, x0 + 8, y0 - 1, 1, 1, hair);
  } else if (app.style === 3) { // bun
    rect(ctx, x0 + 5, y0 - 2, 2, 2, shade(hair, -15));
  }
}

// ---------------------------------------------------------------------------------------------
// Floors, walls, furniture
// ---------------------------------------------------------------------------------------------
const FLOORS: Record<string, [string, string]> = {
  wood: ["#8a6246", "#7c573d"], carpet_blue: ["#3b4a73", "#36446a"], carpet_red: ["#6e3440", "#653039"],
  tile: ["#c9c3b3", "#bdb6a5"], carpet_green: ["#3f6b50", "#3a6349"], carpet_gray: ["#595d6b", "#535764"],
  carpet_purple: ["#57467a", "#504070"], carpet_orange: ["#8a5a33", "#80532f"], carpet_teal: ["#2f6467", "#2b5c5f"],
};

export function drawFloor(ctx: Px, room: Room) {
  const [a, b] = FLOORS[room.floor] || FLOORS.tile;
  for (let ty = room.y; ty < room.y + room.h; ty++) {
    for (let tx = room.x; tx < room.x + room.w; tx++) {
      rect(ctx, tx * T, ty * T, T, T, (tx + ty) % 2 ? a : b);
      if (room.floor === "wood") rect(ctx, tx * T, ty * T + 7, T, 1, shade(a, -18));
      if (room.floor === "tile") { rect(ctx, tx * T, ty * T, T, 1, shade(a, -20)); rect(ctx, tx * T, ty * T, 1, T, shade(a, -20)); }
    }
  }
}

export function doorOf(room: Room): { x: number; y: number; side: "top" | "bottom" } {
  const cx = room.x + Math.floor(room.w / 2);
  if (room.y < 9) return { x: cx, y: room.y + room.h - 1, side: "bottom" };
  return { x: cx, y: room.y, side: "top" };
}

export function drawWalls(ctx: Px, room: Room) {
  const wall = "#e8dcc2", wallDark = "#b9a987", trim = room.accent;
  const d = doorOf(room);
  // top wall (2px tall band + face)
  for (let tx = room.x; tx < room.x + room.w; tx++) {
    const isDoor = d.side === "top" && (tx === d.x || tx === d.x - 1);
    if (!isDoor) {
      rect(ctx, tx * T, room.y * T - 10, T, 10, wall);
      rect(ctx, tx * T, room.y * T - 2, T, 2, wallDark);
      rect(ctx, tx * T, room.y * T - 12, T, 2, trim);
    }
    const isBottomDoor = d.side === "bottom" && (tx === d.x || tx === d.x - 1);
    if (!isBottomDoor) rect(ctx, tx * T, (room.y + room.h) * T - 3, T, 3, wallDark);
  }
  rect(ctx, room.x * T - 3, room.y * T - 12, 3, room.h * T + 12, wallDark);
  rect(ctx, (room.x + room.w) * T, room.y * T - 12, 3, room.h * T + 12, wallDark);
}

export function drawRoomLabel(ctx: Px, room: Room, scale: number) {
  ctx.save();
  ctx.scale(1 / scale, 1 / scale);
  ctx.font = `${Math.max(10, Math.round(5.5 * scale))}px Galmuri11, monospace`;
  const text = room.name;
  const x = (room.x * T + 4) * scale, y = (room.y * T - 3) * scale;
  const w = ctx.measureText(text).width + 8 * (scale / 2);
  ctx.fillStyle = "rgba(20,20,30,0.85)";
  ctx.fillRect(x - 2, y - 8 * (scale / 2) - 2, w, 11 * (scale / 2));
  ctx.fillStyle = room.accent === "#b98b5e" ? "#ffcc4d" : "#f4ecd8";
  ctx.fillText(text, x + 2, y);
  ctx.restore();
}

export function drawDesk(ctx: Px, tx: number, ty: number, screenOn: boolean, t: number) {
  const x = tx * T - 4, y = ty * T + 4;
  rect(ctx, x, y, 28, 10, "#a57946");
  rect(ctx, x, y, 28, 2, "#c4955f");
  rect(ctx, x + 2, y + 10, 2, 5, "#6d4d2b");
  rect(ctx, x + 24, y + 10, 2, 5, "#6d4d2b");
  // monitor (seen from behind-ish, screen facing the sitter)
  rect(ctx, x + 8, y - 8, 12, 9, "#2a2d3e");
  rect(ctx, x + 9, y - 7, 10, 7, screenOn ? ((Math.floor(t / 400) % 2) ? "#6ee7b7" : "#5ad1a3") : "#3b3f55");
  rect(ctx, x + 13, y + 1, 2, 2, "#2a2d3e");
  // keyboard & mug
  rect(ctx, x + 7, y + 3, 10, 2, "#d8d8e0");
  rect(ctx, x + 21, y + 2, 3, 3, "#f4ecd8");
}

export function drawChair(ctx: Px, cx: number, cy: number, color = "#3b3f55") {
  rect(ctx, cx - 5, cy - 3, 10, 4, color);
  rect(ctx, cx - 4, cy - 9, 8, 6, shade(color, 15));
}

export function drawPlant(ctx: Px, x: number, y: number) {
  rect(ctx, x + 4, y + 9, 8, 6, "#b5651d");
  rect(ctx, x + 3, y + 8, 10, 2, "#8a4b15");
  rect(ctx, x + 2, y + 2, 5, 6, "#3f8f4f");
  rect(ctx, x + 7, y, 5, 8, "#4caf62");
  rect(ctx, x + 5, y + 4, 4, 5, "#2f7a3f");
}

export function drawBookshelf(ctx: Px, x: number, y: number) {
  rect(ctx, x, y, 24, 18, "#6d4d2b");
  const colors = ["#c0392b", "#2b5daa", "#1f7a4d", "#e0a93b", "#8a4fbf"];
  for (let r = 0; r < 2; r++) for (let i = 0; i < 6; i++) rect(ctx, x + 2 + i * 3.5, y + 2 + r * 8, 3, 6, colors[(i + r) % colors.length]);
}

export function drawWhiteboard(ctx: Px, x: number, y: number) {
  rect(ctx, x, y, 40, 16, "#9aa0ad");
  rect(ctx, x + 2, y + 2, 36, 12, "#f4f4f6");
  rect(ctx, x + 5, y + 5, 14, 1, "#2b5daa");
  rect(ctx, x + 5, y + 8, 22, 1, "#c0392b");
  rect(ctx, x + 5, y + 11, 10, 1, "#1f7a4d");
}

export function drawMeetingTable(ctx: Px, room: Room) {
  const x = (room.x + 3) * T, y = (room.y + 3) * T, w = (room.w - 6) * T, h = 2 * T;
  rect(ctx, x, y + 4, w, h, "#7a5230");
  rect(ctx, x, y + 4, w, 3, "#9b6b40");
  rect(ctx, x + 4, y + h + 4, 3, 5, "#4d331c");
  rect(ctx, x + w - 7, y + h + 4, 3, 5, "#4d331c");
  for (let i = 0; i < 4; i++) rect(ctx, x + 14 + i * 36, y + 12, 8, 6, "#f4ecd8"); // papers
}

export function meetingSeats(room: Room): { x: number; y: number; facing: Facing }[] {
  const seats: { x: number; y: number; facing: Facing }[] = [];
  const left = room.x + 3, right = room.x + room.w - 3;
  const n = right - left;
  for (let i = 0; i < n; i += 2) seats.push({ x: (left + i + 0.5) * T, y: (room.y + 3) * T + 4, facing: "down" });
  for (let i = 0; i < n; i += 2) seats.push({ x: (left + i + 0.5) * T, y: (room.y + 6) * T + 10, facing: "up" });
  seats.push({ x: (left - 0.6) * T, y: (room.y + 5) * T + 2, facing: "right" });
  seats.push({ x: (right + 0.6) * T, y: (room.y + 5) * T + 2, facing: "left" });
  return seats;
}

export function drawSofa(ctx: Px, x: number, y: number) {
  rect(ctx, x, y, 36, 14, "#5e8a6b");
  rect(ctx, x, y, 36, 5, "#4a7058");
  rect(ctx, x - 3, y + 2, 4, 12, "#3f604b");
  rect(ctx, x + 35, y + 2, 4, 12, "#3f604b");
}

export function drawInbox(ctx: Px, x: number, y: number, pending: boolean, t: number) {
  rect(ctx, x, y + 6, 20, 10, "#8a8f9e");
  rect(ctx, x + 2, y + 4, 16, 4, "#f4ecd8");
  rect(ctx, x + 3, y + 2, 14, 3, "#e8dcc2");
  if (pending && Math.floor(t / 500) % 2 === 0) {
    rect(ctx, x + 7, y - 10, 6, 8, "#ffcc4d");
    rect(ctx, x + 9, y - 8, 2, 3, "#1b1d2a");
    rect(ctx, x + 9, y - 4, 2, 1, "#1b1d2a");
  }
}

export function drawCooler(ctx: Px, x: number, y: number) {
  rect(ctx, x + 2, y, 8, 7, "#7dd3fc");
  rect(ctx, x, y + 7, 12, 12, "#d8d8e0");
  rect(ctx, x + 3, y + 10, 2, 2, "#c0392b");
}

export function drawCeoDesk(ctx: Px, room: Room) {
  const x = (room.x + 3) * T, y = (room.y + 3) * T;
  rect(ctx, x, y, 4 * T, 14, "#5a3a22");
  rect(ctx, x, y, 4 * T, 3, "#7a5230");
  rect(ctx, x + 10, y - 9, 14, 10, "#2a2d3e");
  rect(ctx, x + 11, y - 8, 12, 8, "#7dd3fc");
  rect(ctx, x + 40, y - 4, 10, 5, "#ffcc4d"); // nameplate
  drawChair(ctx, x + 2 * T, y - 2, "#7a2a2a");
}

export function drawStatusIcon(ctx: Px, cx: number, topY: number, status: string, t: number) {
  const y = topY - 7 + (Math.floor(t / 300) % 2);
  if (status === "working") {
    rect(ctx, cx - 5, y, 10, 6, "#f4ecd8");
    const dots = Math.floor(t / 250) % 4;
    for (let i = 0; i < dots; i++) rect(ctx, cx - 3 + i * 2.5, y + 2, 1.5, 1.5, "#1b1d2a");
  } else if (status === "meeting") {
    rect(ctx, cx - 3, y, 6, 6, "#fb7185");
    rect(ctx, cx - 1, y + 1, 2, 3, "#fff");
  }
}
