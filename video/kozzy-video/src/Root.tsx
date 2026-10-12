import { Composition } from "remotion";
import "./fonts";
import { Explainer, EXPLAINER_FRAMES } from "./Explainer";
import { FPS } from "./timeline";
import { SpecVideo } from "./brand/SpecVideo";
import { specFrames, type Spec } from "./brand/types";
import appDemo from "./specs/app-demo.json";
import botDemo from "./specs/bot-demo.json";

// Brand videos: one JSON spec each (src/specs/), rendered by SpecVideo — framework in ~/.claude/skills/brand-video.
const BASE = [appDemo, botDemo] as Spec[];
// Every spec also gets a "-Short" cut without the how-it-works scene.
const SPECS = BASE.flatMap((s) => [s, { ...s, id: `${s.id}-Short`, scenes: s.scenes.filter((sc) => sc.type !== "stack") }]);

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="Explainer" component={Explainer} durationInFrames={EXPLAINER_FRAMES} fps={FPS} width={1920} height={1080} />
      {SPECS.map((spec) => (
        <Composition key={spec.id} id={spec.id} component={SpecVideo} defaultProps={{ spec }}
          durationInFrames={specFrames(spec)} fps={spec.fps} width={1920} height={1080} />
      ))}
    </>
  );
};
