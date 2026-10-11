import React from "react";
import { useCurrentFrame } from "remotion";
import { BEAT } from "../timeline";
import { Stage, Glow, H, Sub, M, rise } from "../ui";

const NODES = [
  { t: "Staff message", s: "text or voice", c: M.hair },
  { t: "Assistant reads it", s: "AI only if unclear", c: M.blue },
  { t: "Staff confirm", s: "before key changes", c: M.pink },
  { t: "Saved", s: "with who and when", c: M.hair },
];

// AI is a helper, never the one who writes.
export const Guardrail: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <Stage glows={<Glow x={960} y={760} size={1200} color={M.pink} o={0.2} />}>
      <div style={{ position: "absolute", left: 160, top: 170, width: 1600 }}>
        <H size={104} style={rise(f, 0)}>AI only helps with unclear messages.</H>
        <Sub style={{ ...rise(f, BEAT), marginTop: 26, fontSize: 52, color: M.text }}>
          It never saves anything <span style={{ color: M.pink, fontWeight: 600 }}>on its own.</span></Sub>
      </div>
      <div style={{ position: "absolute", left: 120, right: 120, top: 640, display: "flex", alignItems: "center", gap: 14 }}>
        {NODES.map((n, i) => (
          <React.Fragment key={n.t}>
            {i > 0 && <div style={{ ...rise(f, (2 + i) * BEAT - 4, undefined, 0), flex: "0 0 36px", height: 3, background: "rgba(255,255,255,0.25)" }} />}
            <div style={{ ...rise(f, (2 + i) * BEAT, undefined, 24), flex: 1, padding: "26px 28px", borderRadius: 28,
              background: "rgba(255,255,255,0.05)", border: `2px solid ${n.c}` }}>
              <div style={{ fontSize: 34, fontWeight: 700, whiteSpace: "nowrap", letterSpacing: "-0.02em" }}>{n.t}</div>
              <div style={{ fontSize: 26, color: M.dim, marginTop: 6, whiteSpace: "nowrap" }}>{n.s}</div>
            </div>
          </React.Fragment>
        ))}
      </div>
    </Stage>
  );
};
