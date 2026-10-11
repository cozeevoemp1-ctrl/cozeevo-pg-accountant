import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { BEAT } from "../timeline";
import { Stage, Glow, H, M, rise, EASE, Glass } from "../ui";

const CL = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const Front: React.FC<{ at: number; title: string; line: string; color: string; x: number }> = ({ at, title, line, color, x }) => {
  const f = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: x, top: 610, width: 640, ...rise(f, at, undefined, 30) }}>
      <Glass accent={color}>
        <div style={{ fontSize: 46, fontWeight: 700, letterSpacing: "-0.03em" }}>{title}</div>
        <div style={{ fontSize: 30, color: M.dim, marginTop: 8 }}>{line}</div>
      </Glass>
    </div>
  );
};

// How it was built: one shared record, two ways in.
export const How: React.FC = () => {
  const f = useCurrentFrame();
  const core = interpolate(f, [0, 14], [0, 1], { ...CL, easing: EASE });
  const lines = interpolate(f, [BEAT, BEAT + 14], [0, 1], { ...CL, easing: EASE });
  return (
    <Stage glows={<Glow x={960} y={330} size={900} color={M.pink} o={0.45 * core} />}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 110, textAlign: "center" }}>
        <H size={104} style={rise(f, 0)}>One system. <span style={{ color: M.pink }}>Two front ends.</span></H>
      </div>
      <div style={{ position: "absolute", left: 960 - 75, top: 300, width: 150, height: 150, borderRadius: 42,
        background: `linear-gradient(145deg, ${M.pink}, #B5126F)`, boxShadow: `inset 0 2px 2px rgba(255,255,255,0.35), 0 30px 80px -10px ${M.pink}`,
        opacity: core, scale: interpolate(core, [0, 1], [0.6, 1]) }} />
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {[[880, 600], [1040, 600]].map(([x2, y2], i) => (
          <line key={i} x1={960} y1={450} x2={i ? 1240 : 680} y2={y2} stroke="rgba(255,255,255,0.3)" strokeWidth={3}
            strokeDasharray={420} strokeDashoffset={420 * (1 - lines)} />
        ))}
      </svg>
      <Front at={BEAT + 4} x={300} color={M.blue} title="The app" line="The full picture: rent, beds, every tenant" />
      <Front at={2 * BEAT} x={980} color={M.pink} title="The WhatsApp bot" line="Quick stuff: ask, log, confirm" />
    </Stage>
  );
};
