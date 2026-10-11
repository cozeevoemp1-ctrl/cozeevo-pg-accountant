import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { FONTS } from "./fonts";

// Midnight look — chosen 2026-10-11 from the style frames.
export const M = {
  bg: "#07070B",
  pink: "#EF1F9C",
  blue: "#00AEED",
  text: "#FFFFFF",
  dim: "rgba(255,255,255,0.6)",
  faint: "rgba(255,255,255,0.28)",
  hair: "rgba(255,255,255,0.12)",
  glass: "rgba(255,255,255,0.05)",
};
export const EASE = Easing.bezier(0.16, 1, 0.3, 1);
const CL = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Fade + rise in at frame `at`, optional fade out at `out`
export const rise = (f: number, at: number, out?: number, dist = 40): React.CSSProperties => ({
  opacity:
    interpolate(f, [at, at + 14], [0, 1], { ...CL, easing: EASE }) *
    (out === undefined ? 1 : interpolate(f, [out, out + 8], [1, 0], { ...CL, easing: EASE })),
  translate: interpolate(f, [at, at + 14], [`0px ${dist}px`, "0px 0px"], { ...CL, easing: EASE }),
});

export const Stage: React.FC<{ children: React.ReactNode; glows?: React.ReactNode }> = ({ children, glows }) => (
  <AbsoluteFill style={{ background: M.bg, overflow: "hidden", fontFamily: FONTS.ui, color: M.text }}>
    {glows}
    {children}
  </AbsoluteFill>
);

export const Glow: React.FC<{ x: number; y: number; size: number; color: string; o: number; drift?: number }> = ({
  x, y, size, color, o, drift = 0,
}) => {
  const f = useCurrentFrame();
  const dx = Math.sin(f / 90) * drift, dy = Math.cos(f / 110) * drift;
  return (
    <div style={{ position: "absolute", left: x - size / 2 + dx, top: y - size / 2 + dy, width: size, height: size,
      borderRadius: "50%", background: `radial-gradient(circle, ${color} 0%, transparent 65%)`, opacity: o }} />
  );
};

export const Eyebrow: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ display: "inline-block", fontSize: 22, fontWeight: 600, letterSpacing: "0.22em", textTransform: "uppercase",
    color: "rgba(255,255,255,0.72)", border: `1.5px solid ${M.hair}`, borderRadius: 999, padding: "10px 22px", ...style }}>
    {children}
  </div>
);

export const H: React.FC<{ size: number; children: React.ReactNode; style?: React.CSSProperties }> = ({ size, children, style }) => (
  <div style={{ fontWeight: 700, fontSize: size, lineHeight: 1.0, letterSpacing: "-0.045em", ...style }}>{children}</div>
);

export const Sub: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ fontSize: 42, fontWeight: 400, lineHeight: 1.3, color: M.dim, ...style }}>{children}</div>
);

// Glass card with hairline + inner highlight (double-bezel)
export const Glass: React.FC<{ children: React.ReactNode; style?: React.CSSProperties; accent?: string }> = ({ children, style, accent }) => (
  <div style={{ padding: 8, borderRadius: 36, background: "rgba(255,255,255,0.03)", border: `1px solid ${M.hair}`, ...style }}>
    <div style={{ borderRadius: 28, background: "rgba(255,255,255,0.05)", padding: "28px 34px",
      boxShadow: `inset 0 1px 1px rgba(255,255,255,0.12)${accent ? `, 0 0 0 2px ${accent}` : ""}` }}>
      {children}
    </div>
  </div>
);
