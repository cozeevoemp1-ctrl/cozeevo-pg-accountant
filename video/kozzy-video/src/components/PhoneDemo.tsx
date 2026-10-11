import React from "react";
import { Video } from "@remotion/media";
import { interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Phone, fill } from "./Phone";
import { Stage, Glow, Eyebrow, H, M, rise, EASE } from "../ui";

export type Step = { at: number; label: string }; // `at` = seconds into the CLIP
export type Spot = { from: number; top: string; height: string }; // ring a row of the screen

// Real screen recording on a phone + headline + steps that light up when they happen in the clip.
export const PhoneDemo: React.FC<{
  clip: string;
  clipSeconds: number; // natural length of the recording
  aspect: number; // clip height / width
  eyebrow: string;
  title: React.ReactNode;
  steps?: Step[];
  sub?: React.ReactNode;
  phoneSide?: "left" | "right";
  glow?: string;
  spot?: Spot;
  titleSize?: number;
}> = ({ clip, clipSeconds, aspect, eyebrow, title, steps = [], sub, phoneSide = "right", glow = M.pink, spot, titleSize = 108 }) => {
  const f = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const rate = clipSeconds / (durationInFrames / fps); // fit the whole take into the scene
  const sf = (clipSec: number) => Math.round((clipSec / rate) * fps); // clip time -> scene frame
  const left = phoneSide === "left";
  const spotOn = spot ? interpolate(f, [sf(spot.from), sf(spot.from) + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE }) : 0;
  return (
    <Stage glows={<Glow x={left ? 600 : 1330} y={540} size={1050} color={glow} o={0.4} drift={25} />}>
      <div style={{ position: "absolute", left: left ? 990 : 160, top: steps.length ? 200 : 320, width: 800 }}>
        <div style={rise(f, 0)}><Eyebrow>{eyebrow}</Eyebrow></div>
        <H size={titleSize} style={{ ...rise(f, 6), marginTop: 36 }}>{title}</H>
        {sub && <div style={{ ...rise(f, 15), marginTop: 28, fontSize: 42, color: M.dim, lineHeight: 1.3 }}>{sub}</div>}
        <div style={{ marginTop: 48 }}>
          {steps.map((s, i) => {
            const t = sf(s.at), next = i + 1 < steps.length ? sf(steps[i + 1].at) : Infinity;
            const cur = f >= t && f < next;
            return (
              <div key={s.label} style={{ ...rise(f, t, undefined, 16), display: "flex", alignItems: "center", gap: 22, marginTop: 18 }}>
                <div style={{ width: 44, height: 44, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 22, fontWeight: 700,
                  background: cur ? glow : "rgba(255,255,255,0.08)", color: cur ? "#fff" : M.dim }}>{i + 1}</div>
                <div style={{ fontSize: 38, fontWeight: cur ? 600 : 400, color: cur ? M.text : M.dim }}>{s.label}</div>
              </div>
            );
          })}
        </div>
      </div>
      <Phone width={410} aspect={aspect} style={{ position: "absolute", [left ? "left" : "right"]: left ? 330 : 210, top: 44,
        ...rise(f, 0, undefined, 60) }}>
        <Video src={staticFile(clip)} playbackRate={rate} muted style={fill} />
        {spot && <div style={{ position: "absolute", left: "2.5%", width: "95%", top: spot.top, height: spot.height, borderRadius: 14,
          border: `3px solid ${glow}`, opacity: spotOn, boxShadow: `0 0 0 2000px rgba(7,7,11,${0.5 * spotOn})` }} />}
      </Phone>
    </Stage>
  );
};
