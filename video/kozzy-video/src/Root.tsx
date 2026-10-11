import { Composition } from "remotion";
import "./fonts";
import { Explainer, EXPLAINER_FRAMES } from "./Explainer";
import { FPS } from "./timeline";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition id="Explainer" component={Explainer} durationInFrames={EXPLAINER_FRAMES} fps={FPS} width={1920} height={1080} />
  );
};
