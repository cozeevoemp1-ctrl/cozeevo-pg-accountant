import { Composition, Folder } from "remotion";
import "./fonts";
import { StyleFrame, Look, Shot } from "./style-frames/StyleFrame";

const LOOKS: Look[] = ["signal", "midnight", "paper"];
const SHOTS: Shot[] = ["hook", "demo"];

export const RemotionRoot: React.FC = () => {
  return (
    <Folder name="StyleFrames">
      {LOOKS.flatMap((look) =>
        SHOTS.map((shot) => (
          <Composition
            key={`${look}-${shot}`}
            id={`SF-${look}-${shot}`}
            component={StyleFrame}
            defaultProps={{ look, shot }}
            durationInFrames={60}
            fps={30}
            width={1920}
            height={1080}
          />
        )),
      )}
    </Folder>
  );
};
