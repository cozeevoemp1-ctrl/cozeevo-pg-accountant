import React from "react";
import { useCurrentFrame } from "remotion";
import { BEAT, BAR } from "../timeline";
import { Stage, Glow, H, Sub, M, rise } from "../ui";

export const END_NAME = "Kiran";
export const END_LINE = "upwork.com/freelancers/~017b20a1dfbd090280";

// The result, then the end card.
export const Result: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <Stage glows={<><Glow x={760} y={520} size={1100} color={M.pink} o={0.32} drift={20} /><Glow x={1240} y={560} size={1000} color={M.blue} o={0.22} drift={20} /></>}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 300, textAlign: "center" }}>
        <H size={170} style={rise(f, 0)}>One record.</H>
        <H size={96} style={{ ...rise(f, 2 * BEAT), color: M.dim, marginTop: 24 }}>Everyone sees the same numbers.</H>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 790, textAlign: "center", ...rise(f, BAR + BEAT, undefined, 20) }}>
        <div style={{ width: 64, height: 4, background: M.pink, margin: "0 auto 34px", borderRadius: 2 }} />
        <div style={{ fontSize: 40, fontWeight: 600 }}>{END_NAME}</div>
        <Sub style={{ fontSize: 30, marginTop: 8 }}>{END_LINE}</Sub>
      </div>
    </Stage>
  );
};
