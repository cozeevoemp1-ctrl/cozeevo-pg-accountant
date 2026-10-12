import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Stage, Glow, M, EASE } from "../ui";
import { END_NAME, END_ROLE, END_LINE } from "../scenes/Result";
import type { CtaScene } from "./types";

const slow = (f: number, at: number, dist = 30): React.CSSProperties => ({
  opacity: interpolate(f, [at, at + 26], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE }),
  translate: interpolate(f, [at, at + 26], [`0px ${dist}px`, "0px 0px"], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE }),
});

// Call to action — about the viewer, slower, then who to contact.
export const Cta: React.FC<{ s: CtaScene }> = ({ s }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pulse = 1 + 0.03 * Math.sin((f / fps) * Math.PI * 2 * 0.8);
  return (
    <Stage glows={<><Glow x={760} y={480} size={1100} color={M.pink} o={0.32} drift={15} /><Glow x={1240} y={540} size={1000} color={M.blue} o={0.22} drift={15} /></>}>
      <div style={{ position: "absolute", left: 100, right: 100, top: 250, textAlign: "center" }}>
        <div style={{ ...slow(f, 0), fontSize: 70, fontWeight: 600, letterSpacing: "-0.035em", color: M.dim }}>{s.q}</div>
        <div style={{ ...slow(f, 22), fontSize: 98, fontWeight: 800, letterSpacing: "-0.05em", lineHeight: 1.05, marginTop: 14 }}>{s.a}</div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 640, textAlign: "center", ...slow(f, 50, 16) }}>
        <div style={{ display: "inline-block", padding: "18px 40px", borderRadius: 999, background: M.pink, fontSize: 36, fontWeight: 700,
          scale: String(f > 76 ? pulse : 1), boxShadow: `0 20px 60px -15px ${M.pink}` }}>{s.button}</div>
        <div style={{ marginTop: 46, fontSize: 42, fontWeight: 600 }}>{END_NAME}</div>
        <div style={{ fontSize: 28, color: M.dim, marginTop: 6 }}>{END_ROLE}</div>
        <div style={{ fontSize: 26, color: M.dim, marginTop: 10 }}>{END_LINE}</div>
      </div>
    </Stage>
  );
};
