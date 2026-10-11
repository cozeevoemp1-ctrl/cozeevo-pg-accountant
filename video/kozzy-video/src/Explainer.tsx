import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { SCENES, TOTAL } from "./timeline";
import { M } from "./ui";
import { Hook } from "./scenes/Hook";
import { Why } from "./scenes/Why";
import { How } from "./scenes/How";
import { AppCollect, AppVacant, WaQuick, SameRecord } from "./scenes/Demos";
import { Guardrail } from "./scenes/Guardrail";
import { Result } from "./scenes/Result";

const VIEWS: Record<string, React.FC> = {
  hook: Hook, why: Why, how: How, app_collect: AppCollect, app_vacant: AppVacant, whatsapp: WaQuick,
  same_record: SameRecord, guardrail: Guardrail, result: Result,
};

// Every scene cuts on a bar downbeat; a 6-frame dip out keeps cuts clean.
const Cut: React.FC<{ duration: number; last: boolean; children: React.ReactNode }> = ({ duration, last, children }) => {
  const f = useCurrentFrame();
  const out = last ? 1 : interpolate(f, [duration - 6, duration], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity: out }}>{children}</AbsoluteFill>;
};

export const Explainer: React.FC = () => (
  <AbsoluteFill style={{ background: M.bg }}>
    {SCENES.map((s, i) => {
      const View = VIEWS[s.id];
      return (
        <Sequence key={s.id} name={s.id} from={s.from} durationInFrames={s.duration}>
          <Cut duration={s.duration} last={i === SCENES.length - 1}><View /></Cut>
        </Sequence>
      );
    })}
    <Audio src={staticFile("music.wav")} />
  </AbsoluteFill>
);

export const EXPLAINER_FRAMES = TOTAL;
