import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { Stage, Glow, M, EASE } from "../ui";
import type { StackScene } from "./types";

const CL = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const COLS = [330, 960, 1590], ROWS = [470, 760], NW = 470, NH = 150;
const pos = (x: number, y: number) => ({ cx: COLS[x], cy: ROWS[y] });

// How it works: ≤6 nodes on a 3×2 grid, edges draw in, a dot travels each edge. No detail.
export const Stack: React.FC<{ s: StackScene }> = ({ s }) => {
  const f = useCurrentFrame();
  const byId = Object.fromEntries(s.nodes.map((n) => [n.id, n]));
  return (
    <Stage glows={<Glow x={960} y={600} size={1300} color={M.blue} o={0.22} drift={20} />}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 120, textAlign: "center", fontSize: 26, fontWeight: 700,
        letterSpacing: "0.24em", textTransform: "uppercase", color: M.blue, opacity: interpolate(f, [0, 10], [0, 1], CL) }}>How it works</div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 170, textAlign: "center", fontSize: 92, fontWeight: 700,
        letterSpacing: "-0.045em", opacity: interpolate(f, [4, 16], [0, 1], CL) }}>{s.title}</div>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <defs><marker id="arr" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="rgba(255,255,255,0.6)" /></marker></defs>
        {s.edges.map(([a, b], i) => {
          const A = pos(byId[a].x, byId[a].y), B = pos(byId[b].x, byId[b].y);
          const horiz = A.cy === B.cy;
          const x1 = horiz ? A.cx + Math.sign(B.cx - A.cx) * NW / 2 : A.cx, y1 = horiz ? A.cy : A.cy + Math.sign(B.cy - A.cy) * NH / 2;
          const x2 = horiz ? B.cx - Math.sign(B.cx - A.cx) * NW / 2 : B.cx, y2 = horiz ? B.cy : B.cy - Math.sign(B.cy - A.cy) * NH / 2;
          const p = interpolate(f, [16 + i * 6, 30 + i * 6], [0, 1], { ...CL, easing: EASE });
          const t = ((f - 30 - i * 6) % 40) / 40;
          return (
            <g key={i}>
              <line x1={x1} y1={y1} x2={x1 + (x2 - x1) * p} y2={y1 + (y2 - y1) * p} stroke="rgba(255,255,255,0.45)" strokeWidth={3}
                markerEnd={p > 0.95 ? "url(#arr)" : undefined} />
              {f > 30 + i * 6 && <circle cx={x1 + (x2 - x1) * t} cy={y1 + (y2 - y1) * t} r={7} fill={M.pink} />}
            </g>
          );
        })}
      </svg>
      {s.nodes.map((n, i) => {
        const { cx, cy } = pos(n.x, n.y);
        const o = interpolate(f, [8 + i * 4, 20 + i * 4], [0, 1], { ...CL, easing: EASE });
        return (
          <div key={n.id} style={{ position: "absolute", left: cx - NW / 2, top: cy - NH / 2, width: NW, height: NH, borderRadius: 30,
            background: "rgba(255,255,255,0.06)", border: `1.5px solid ${M.hair}`, boxShadow: "inset 0 1px 1px rgba(255,255,255,0.12)",
            display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", opacity: o, scale: String(0.9 + 0.1 * o) }}>
            <div style={{ fontSize: 40, fontWeight: 700, letterSpacing: "-0.03em" }}>{n.label}</div>
            <div style={{ fontSize: 26, color: M.dim, marginTop: 6 }}>{n.tech}</div>
          </div>
        );
      })}
    </Stage>
  );
};
