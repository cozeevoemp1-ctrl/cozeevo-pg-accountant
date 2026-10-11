import T from "./timeline.json";

// Single source of timing for video + music (scripts/music.mjs reads the same JSON).
export const FPS = T.fps;
export const BEAT = Math.round((60 / T.bpm) * FPS); // 15 frames
export const BAR = BEAT * 4; // 60 frames = 2 s

let at = 0;
export const SCENES = T.scenes.map((s) => {
  const from = at;
  at += s.bars * BAR;
  return { id: s.id, from, duration: s.bars * BAR };
});
export const TOTAL = at;
