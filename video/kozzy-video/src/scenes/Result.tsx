import React from "react";
import { getInputProps, interpolate, useCurrentFrame } from "remotion";
import { BAR } from "../timeline";
import { Stage, Glow, M, EASE } from "../ui";

export const END_NAME = "Kiran";
export const END_ROLE = "Product Manager & Consultant";
export const END_LINE = "upwork.com/freelancers/~017b20a1dfbd090280";

// Two closes: "build" (spreadsheets → let's build yours) | "ai" (which task should AI take over).
// Pick at render time: npx remotion render Explainer out/x.mp4 --props='{"close":"ai"}'
const CLOSES = {
  build: { q: "Still running your business on spreadsheets and chats?", a: <>Let’s build <span style={{ color: M.pink }}>yours.</span></> },
  ai: { q: "Which daily task should AI take off your team’s plate?", a: <>Let’s find it <span style={{ color: M.pink }}>together.</span></> },
};

// Slow reveal for the close — 26 frames instead of the usual 14.
const slow = (f: number, at: number, dist = 30): React.CSSProperties => ({
  opacity: interpolate(f, [at, at + 26], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE }),
  translate: interpolate(f, [at, at + 26], [`0px ${dist}px`, "0px 0px"], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE }),
});

// Close, written for the viewer: the situation they may be in, a call to action, then who to contact.
export const Result: React.FC = () => {
  const f = useCurrentFrame();
  const c = CLOSES[(getInputProps() as { close?: "build" | "ai" }).close ?? "build"];
  return (
    <Stage glows={<><Glow x={760} y={480} size={1100} color={M.pink} o={0.3} drift={15} /><Glow x={1240} y={540} size={1000} color={M.blue} o={0.2} drift={15} /></>}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 290, textAlign: "center" }}>
        <div style={{ ...slow(f, 0), fontSize: 72, fontWeight: 600, letterSpacing: "-0.035em", color: M.dim }}>{c.q}</div>
        <div style={{ ...slow(f, 24), fontSize: 132, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1.05, marginTop: 10 }}>
          {c.a}</div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 700, textAlign: "center", ...slow(f, BAR + 10, 16) }}>
        <div style={{ width: 64, height: 4, background: M.pink, margin: "0 auto 32px", borderRadius: 2 }} />
        <div style={{ fontSize: 44, fontWeight: 600 }}>{END_NAME}</div>
        <div style={{ fontSize: 30, color: M.dim, marginTop: 6 }}>{END_ROLE}</div>
        <div style={{ display: "inline-block", marginTop: 22, padding: "12px 30px", borderRadius: 999, background: M.pink,
          fontSize: 30, fontWeight: 600 }}>Let’s explore what AI can do for your business →</div>
        <div style={{ fontSize: 26, color: M.dim, marginTop: 14 }}>{END_LINE}</div>
      </div>
    </Stage>
  );
};
