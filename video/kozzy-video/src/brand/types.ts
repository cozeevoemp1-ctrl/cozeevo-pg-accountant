// Brand-video spec (see ~/.claude/skills/brand-video). Every brand video = one JSON in src/specs/.
// Structure is fixed: hook → feature… (product/story) → stack (how it works) → cta.
import type { Pin } from "../components/ProductShot";

export type HookScene = { type: "hook"; bars: number; eyebrow: string; title: string; sub?: string };
export type FeatureScene = {
  type: "feature"; bars: number; n: string; name: string; line: string;
  clip: string; clipFrom: number; clipTo: number; aspect: number; color: "pink" | "blue"; pins: Pin[];
  eyebrow?: string;
};
export type StackNode = { id: string; label: string; tech: string; x: number; y: number };
export type StackScene = { type: "stack"; bars: number; title: string; nodes: StackNode[]; edges: [string, string][] };
export type CtaScene = { type: "cta"; bars: number; q: string; a: string; button: string };
export type Scene = HookScene | FeatureScene | StackScene | CtaScene;

export type Spec = { id: string; bpm: number; fps: number; music: string; scenes: Scene[] };

export const barFrames = (s: Spec) => Math.round((60 / s.bpm) * 4 * s.fps);
export const specFrames = (s: Spec) => s.scenes.reduce((a, sc) => a + sc.bars, 0) * barFrames(s);
