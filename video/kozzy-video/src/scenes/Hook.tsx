import React from "react";
import { useCurrentFrame } from "remotion";
import { BEAT } from "../timeline";
import { Stage, Glow, Eyebrow, H, M, rise } from "../ui";

// Three questions the front desk asks every day — land on beats.
export const Hook: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <Stage glows={<><Glow x={1500} y={260} size={1100} color={M.pink} o={0.35} drift={40} /><Glow x={300} y={980} size={900} color={M.blue} o={0.22} drift={30} /></>}>
      <div style={{ position: "absolute", left: 160, top: 210 }}>
        <div style={rise(f, 0)}><Eyebrow>Running a co-living property</Eyebrow></div>
        <H size={210} style={{ ...rise(f, BEAT), marginTop: 48 }}>Who’s paid?</H>
        <H size={104} style={{ ...rise(f, 3 * BEAT), color: "rgba(255,255,255,0.45)", marginTop: 18 }}>Which beds are free?</H>
        <H size={104} style={{ ...rise(f, 5 * BEAT), color: "rgba(255,255,255,0.22)", marginTop: 6 }}>Who’s moving out?</H>
      </div>
    </Stage>
  );
};
