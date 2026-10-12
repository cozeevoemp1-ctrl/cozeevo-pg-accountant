import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { M } from "../ui";
import { ProductShot } from "../components/ProductShot";
import { Hook } from "./Hook";
import { Stack } from "./Stack";
import { Cta } from "./Cta";
import { barFrames, type Scene, type Spec } from "./types";

const View: React.FC<{ s: Scene }> = ({ s }) => {
  switch (s.type) {
    case "hook": return <Hook s={s} />;
    case "feature": return <ProductShot n={s.n} name={s.name} line={s.line} clip={s.clip} clipFrom={s.clipFrom} clipTo={s.clipTo}
      aspect={s.aspect} color={s.color === "blue" ? M.blue : M.pink} pins={s.pins} eyebrow={s.eyebrow} />;
    case "stack": return <Stack s={s} />;
    case "cta": return <Cta s={s} />;
  }
};

const Cut: React.FC<{ duration: number; last: boolean; children: React.ReactNode }> = ({ duration, last, children }) => {
  const f = useCurrentFrame();
  const out = last ? 1 : interpolate(f, [duration - 6, duration], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity: out }}>{children}</AbsoluteFill>;
};

// Renders any brand-video spec. Every cut lands on a bar of the spec's BPM.
export const SpecVideo: React.FC<{ spec: Spec }> = ({ spec }) => {
  const bar = barFrames(spec);
  const { durationInFrames, fps } = useVideoConfig();
  const fade = Math.round(2.5 * fps); // music always fades to silence on the last frame, whatever the cut length
  let at = 0;
  return (
    <AbsoluteFill style={{ background: M.bg }}>
      {spec.scenes.map((s, i) => {
        const from = at, dur = s.bars * bar;
        at += dur;
        return (
          <Sequence key={i} name={`${i + 1}-${s.type}`} from={from} durationInFrames={dur}>
            <Cut duration={dur} last={i === spec.scenes.length - 1}><View s={s} /></Cut>
          </Sequence>
        );
      })}
      <Audio src={staticFile(spec.music)} volume={(f) => interpolate(f, [durationInFrames - fade, durationInFrames - 1], [1, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />
    </AbsoluteFill>
  );
};
