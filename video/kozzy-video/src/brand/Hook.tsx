import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { Stage, Glow, M, EASE } from "../ui";
import type { HookScene } from "./types";

const CL = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Hook: one huge line the viewer gets instantly. Words land one by one.
export const Hook: React.FC<{ s: HookScene }> = ({ s }) => {
  const f = useCurrentFrame();
  const words = s.title.split(" ");
  return (
    <Stage glows={<><Glow x={1450} y={300} size={1200} color={M.pink} o={0.38} drift={35} /><Glow x={350} y={950} size={1000} color={M.blue} o={0.25} drift={35} /></>}>
      <div style={{ position: "absolute", left: 140, right: 140, top: 230 }}>
        <div style={{ display: "inline-block", fontSize: 26, fontWeight: 700, letterSpacing: "0.24em", textTransform: "uppercase",
          color: "#fff", background: M.pink, borderRadius: 999, padding: "12px 28px",
          opacity: interpolate(f, [0, 10], [0, 1], CL), scale: String(interpolate(f, [0, 12], [0.85, 1], { ...CL, easing: EASE })) }}>
          {s.eyebrow}</div>
        <div style={{ marginTop: 44, fontSize: 168, fontWeight: 800, letterSpacing: "-0.055em", lineHeight: 0.98 }}>
          {words.map((w, i) => (
            <span key={i} style={{ display: "inline-block", marginRight: "0.24em",
              opacity: interpolate(f, [6 + i * 4, 18 + i * 4], [0, 1], CL),
              translate: interpolate(f, [6 + i * 4, 22 + i * 4], ["0px 60px", "0px 0px"], { ...CL, easing: EASE }) }}>{w}</span>
          ))}
        </div>
        {s.sub && <div style={{ marginTop: 34, fontSize: 56, fontWeight: 500, color: M.dim, letterSpacing: "-0.02em",
          opacity: interpolate(f, [24 + words.length * 4, 40 + words.length * 4], [0, 1], CL) }}>{s.sub}</div>}
      </div>
    </Stage>
  );
};
