"use client";

import { useEffect, useRef } from "react";
import { drawCharacter } from "@/components/office/sprites";
import type { Employee } from "@/lib/types";

export default function Avatar({ employee, size = 32 }: { employee?: Employee; size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d")!;
    ctx.clearRect(0, 0, 16, 16);
    ctx.fillStyle = employee ? "#343850" : "#ffcc4d";
    ctx.fillRect(0, 0, 16, 16);
    if (employee) drawCharacter(ctx, 8, 16, employee.appearance, { facing: "down", walking: false, frame: 0 });
    else { // CEO crown
      ctx.fillStyle = "#1b1d2a";
      [[3, 5], [5, 7], [8, 4], [11, 7], [13, 5]].forEach(([x, y]) => ctx.fillRect(x, y, 1, 1));
      ctx.fillRect(3, 6, 11, 5);
      ctx.fillStyle = "#fb7185"; ctx.fillRect(8, 8, 1, 1);
    }
  }, [employee]);
  return <canvas ref={ref} width={16} height={16} style={{ width: size, height: size }} className="shadow-pixelsm shrink-0" />;
}
