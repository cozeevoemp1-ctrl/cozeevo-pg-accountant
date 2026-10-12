import React from "react";
import { Video } from "@remotion/media";
import { interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Phone, fill } from "./Phone";
import { Stage, Glow, M, rise, EASE } from "../ui";

export type Pin = { at: number; y: number; label: string }; // at = clip seconds, y = 0..1 of screen height

// One product: outline numeral behind, real recording on a phone, a name + one line, and
// callouts pinned to the screen at the moment they happen in the clip.
export const ProductShot: React.FC<{
  n: string;
  name: string;
  line: string;
  clip: string;
  clipFrom: number; // seconds into the clip to start
  clipTo: number; // seconds into the clip to end (fitted to the scene length)
  aspect: number;
  color: string;
  pins: Pin[];
  eyebrow?: string; // defaults to "Product <n>"
}> = ({ n, name, line, clip, clipFrom, clipTo, aspect, color, pins, eyebrow }) => {
  const f = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const rate = (clipTo - clipFrom) / (durationInFrames / fps);
  const sf = (s: number) => Math.round(((s - clipFrom) / rate) * fps);
  const W = 400, PH = W * aspect, PX = 760, PY = (1080 - PH - 28) / 2;
  return (
    <Stage glows={<Glow x={PX + W / 2} y={540} size={1000} color={color} o={0.35} drift={20} />}>
      {/* outline numeral */}
      <div style={{ position: "absolute", left: 90, top: 60, fontSize: 620, fontWeight: 800, lineHeight: 1, letterSpacing: "-0.06em",
        color: "transparent", WebkitTextStroke: "2px rgba(255,255,255,0.09)",
        opacity: interpolate(f, [0, 20], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>{n}</div>
      <div style={{ position: "absolute", left: 160, top: 640, width: 520 }}>
        <div style={{ ...rise(f, 4), fontSize: 22, fontWeight: 600, letterSpacing: "0.22em", textTransform: "uppercase", color }}>{eyebrow ?? `Product ${n}`}</div>
        <div style={{ ...rise(f, 8), fontSize: 84, fontWeight: 700, letterSpacing: "-0.045em", lineHeight: 1, marginTop: 14 }}>{name}</div>
        <div style={{ ...rise(f, 14), fontSize: 34, color: M.dim, lineHeight: 1.3, marginTop: 18 }}>{line}</div>
      </div>
      <Phone width={W} aspect={aspect} style={{ position: "absolute", left: PX, top: PY, ...rise(f, 0, undefined, 60) }}>
        <Video src={staticFile(clip)} trimBefore={Math.round(clipFrom * fps)} playbackRate={rate} muted style={fill} />
      </Phone>
      {pins.map((p) => {
        const end = sf(p.at + 3); // each callout belongs to its moment, then gets out of the way
        const on = interpolate(f, [sf(p.at), sf(p.at) + 10, end, end + 10], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: EASE });
        const y = PY + 14 + p.y * PH, x0 = PX + W - 30, x1 = PX + W + 90;
        return (
          <React.Fragment key={p.label}>
            <div style={{ position: "absolute", left: x0 - 7, top: y - 7, width: 14, height: 14, borderRadius: "50%", background: color,
              boxShadow: `0 0 0 6px ${color}33`, opacity: on, scale: String(on) }} />
            <div style={{ position: "absolute", left: x0, top: y - 1, width: (x1 - x0) * on, height: 2, background: color }} />
            <div style={{ position: "absolute", left: x1 + 16, top: y - 24, fontSize: 36, fontWeight: 600, whiteSpace: "nowrap",
              opacity: on, translate: `${(1 - on) * -12}px 0px` }}>{p.label}</div>
          </React.Fragment>
        );
      })}
    </Stage>
  );
};
