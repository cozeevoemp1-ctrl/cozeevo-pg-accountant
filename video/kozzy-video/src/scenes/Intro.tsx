import React from "react";
import { useCurrentFrame } from "remotion";
import { BEAT } from "../timeline";
import { Stage, Glow, M, rise } from "../ui";

const STATS = [
  { v: "~300", l: "beds" },
  { v: "4", l: "staff users" },
  { v: "$300k", l: "yearly revenue" },
  { v: "2", l: "products, 1 database" },
];

// What it is and who it is for — nothing else.
export const Intro: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <Stage glows={<><Glow x={1500} y={300} size={1100} color={M.pink} o={0.3} drift={30} /><Glow x={300} y={950} size={900} color={M.blue} o={0.2} drift={30} /></>}>
      <div style={{ position: "absolute", left: 160, top: 250 }}>
        <div style={{ ...rise(f, 0), fontSize: 24, fontWeight: 600, letterSpacing: "0.22em", textTransform: "uppercase", color: M.dim }}>Built for</div>
        <div style={{ ...rise(f, 4), fontSize: 132, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1, marginTop: 22 }}>
          A co-living property.</div>
        <div style={{ display: "flex", marginTop: 90 }}>
          {STATS.map((s, i) => (
            <div key={s.l} style={{ ...rise(f, BEAT + i * 8, undefined, 24), paddingRight: 56, marginRight: 56,
              borderRight: i < STATS.length - 1 ? `1.5px solid ${M.hair}` : "none" }}>
              <div style={{ fontSize: 100, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1, color: i === STATS.length - 1 ? M.pink : M.text }}>{s.v}</div>
              <div style={{ fontSize: 32, color: M.dim, marginTop: 12 }}>{s.l}</div>
            </div>
          ))}
        </div>
      </div>
    </Stage>
  );
};
