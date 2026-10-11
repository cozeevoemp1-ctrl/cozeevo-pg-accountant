import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { BEAT, BAR } from "../timeline";
import { Stage, Glow, H, Sub, M, rise, Glass, EASE } from "../ui";

const CL = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const Amount: React.FC<{ label: string; amt: string; at: number; from: string; bad: boolean }> = ({ label, amt, at, from, bad }) => {
  const f = useCurrentFrame();
  return (
    <div style={{ opacity: interpolate(f, [at, at + 12], [0, 1], CL),
      translate: interpolate(f, [at, at + 16], [from, "0px 0px"], { ...CL, easing: EASE }) }}>
      <Glass style={{ width: 520 }}>
        <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: "0.2em", color: M.faint }}>{label}</div>
        <div style={{ fontSize: 30, color: M.dim, marginTop: 14 }}>Room 204 · June rent</div>
        <div style={{ fontSize: 108, fontWeight: 700, letterSpacing: "-0.04em", marginTop: 8, color: bad ? M.pink : M.text }}>{amt}</div>
      </Glass>
    </div>
  );
};

// Why it was built: the answers were scattered, and didn't agree.
export const Why: React.FC = () => {
  const f = useCurrentFrame();
  const neq = interpolate(f, [BAR + BEAT, BAR + BEAT + 10], [0, 1], { ...CL, easing: EASE });
  return (
    <Stage glows={<Glow x={960} y={700} size={1300} color={M.pink} o={0.18} drift={30} />}>
      <div style={{ position: "absolute", left: 160, top: 130, width: 1600 }}>
        <H size={92} style={rise(f, 0)}>The answers lived in spreadsheets</H>
        <H size={92} style={{ ...rise(f, BEAT), color: M.dim }}>and a dozen WhatsApp chats.</H>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 470, display: "flex", justifyContent: "center", alignItems: "center", gap: 70 }}>
        <Amount label="SPREADSHEET" amt="₹12,000" at={BAR - 6} from="-120px 0px" bad={f > BAR + BEAT} />
        <div style={{ width: 110, height: 110, borderRadius: "50%", border: `3px solid ${M.pink}`, display: "grid", placeItems: "center",
          fontSize: 72, fontWeight: 700, color: M.pink, opacity: neq, scale: interpolate(neq, [0, 1], [0.5, 1]) }}>≠</div>
        <Amount label="CHAT" amt="₹11,500" at={BAR} from="120px 0px" bad={f > BAR + BEAT} />
      </div>
      <Sub style={{ ...rise(f, BAR + 2 * BEAT), position: "absolute", left: 0, right: 0, top: 900, textAlign: "center", color: M.text, fontWeight: 600, fontSize: 52 }}>
        And they rarely agreed.</Sub>
    </Stage>
  );
};
