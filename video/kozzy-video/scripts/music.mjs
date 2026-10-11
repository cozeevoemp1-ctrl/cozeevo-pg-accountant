// Soundtrack generated in code -> public/music.wav. Reads src/timeline.json so every
// section change lands exactly on a scene cut. Run: node scripts/music.mjs
import fs from "node:fs";

const T = JSON.parse(fs.readFileSync(new URL("../src/timeline.json", import.meta.url)));
const SR = 44100, BEAT = 60 / T.bpm, BAR = BEAT * 4;
const BARS = T.scenes.reduce((a, s) => a + s.bars, 0);
const LEN = Math.ceil(BARS * BAR * SR);
const L = new Float32Array(LEN), R = new Float32Array(LEN);

// scene id for each bar
const sceneOfBar = [];
T.scenes.forEach(s => { for (let i = 0; i < s.bars; i++) sceneOfBar.push({ id: s.id, i, n: s.bars }); });
const startBar = id => sceneOfBar.findIndex(b => b.id === id);

// chords: Am F C G loop, ending F G C
const PROG = [
  { bass: 45, notes: [57, 60, 64] }, // Am
  { bass: 41, notes: [53, 57, 60] }, // F
  { bass: 48, notes: [55, 60, 64] }, // C
  { bass: 43, notes: [55, 59, 62] }, // G
];
const chordOf = b => (b === BARS - 3 ? PROG[1] : b === BARS - 2 ? PROG[3] : b === BARS - 1 ? PROG[2] : PROG[b % 4]);
const hz = m => 440 * Math.pow(2, (m - 69) / 12);

let seed = 7;
const noise = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2147483648 - 1; };
function add(t0, dur, fn, gain = 1, pan = 0) {
  const s0 = Math.floor(t0 * SR), n = Math.floor(dur * SR);
  const gl = gain * Math.min(1, 1 - pan), gr = gain * Math.min(1, 1 + pan);
  for (let i = 0; i < n && s0 + i < LEN; i++) {
    if (s0 + i < 0) continue;
    const v = fn(i / SR);
    L[s0 + i] += v * gl; R[s0 + i] += v * gr;
  }
}

const kick = t0 => add(t0, 0.4, t => { const f = 45 + 110 * Math.exp(-t * 28); return Math.sin(2 * Math.PI * f * t) * Math.exp(-t * 8); }, 0.85);
const impact = t0 => {
  add(t0, 1.6, t => Math.sin(2 * Math.PI * (32 + 60 * Math.exp(-t * 6)) * t) * Math.exp(-t * 2.4), 0.8);
  let lp = 0; add(t0, 0.9, t => { lp += 0.08 * (noise() - lp); return lp * Math.exp(-t * 5); }, 0.9);
};
const hat = (t0, g) => { let lp = 0; add(t0, 0.06, t => { const x = noise(); lp += 0.25 * (x - lp); return (x - lp) * Math.exp(-t * 70); }, g, 0.2); };
const clap = t0 => { let a = 0, b = 0; add(t0, 0.25, t => { const x = noise(); a += 0.35 * (x - a); b += 0.08 * (a - b);
  const bursts = t < 0.03 ? (Math.floor(t / 0.01) % 2 === 0 ? 1 : 0.3) : 1; return (a - b) * bursts * Math.exp(-t * 18); }, 0.5, -0.1); };
const bass = (t0, m, d) => add(t0, d, t => { const f = hz(m); const ph = 2 * Math.PI * f * t;
  return (Math.sin(ph) + 0.35 * Math.sin(3 * ph) + 0.15 * Math.sin(5 * ph)) * Math.min(1, t * 200) * Math.exp(-t * 5); }, 0.2);
const pluck = (t0, m, pan) => add(t0, 0.35, t => { const ph = (hz(m) * t) % 1; const tri = 4 * Math.abs(ph - 0.5) - 1;
  return tri * Math.exp(-t * 11); }, 0.07, pan);
function pad(t0, dur, notes, g = 0.05) {
  notes.forEach((m, k) => [-6, 0, 6].forEach(c => {
    let lp = 0; const f = hz(m) * Math.pow(2, c / 1200);
    add(t0, dur + 0.6, t => { const saw = 2 * ((f * t) % 1) - 1; lp += 0.06 * (saw - lp);
      const env = Math.min(1, t / 0.35) * (t > dur ? Math.exp(-(t - dur) * 6) : 1); return lp * env; }, g, (k - 1) * 0.35);
  }));
}
const stab = t0 => [58, 59, 64].forEach(m => { let lp = 0; add(t0, 0.5, t => { const s = 2 * ((hz(m) * t) % 1) - 1; lp += 0.2 * (s - lp); return lp * Math.exp(-t * 6); }, 0.09); });
function riser(t0, dur) {
  let lp = 0; add(t0, dur, t => { const p = t / dur; lp += (0.01 + 0.3 * p * p) * (noise() - lp);
    return (lp * 0.8 + 0.25 * Math.sin(2 * Math.PI * (180 + 900 * p * p) * t)) * p * p; }, 0.35);
}

const DEMO = startBar("app_collect"), HOW = startBar("how"), WHY = startBar("why"), RES = startBar("result");
for (let b = 0; b < BARS; b++) {
  const t = b * BAR, { id } = sceneOfBar[b], ch = chordOf(b), last = b === BARS - 1;
  pad(t, BAR, ch.notes, last ? 0.07 : 0.05);
  if (last) { bass(t, ch.bass, 3.5); continue; }
  const full = ["app_collect", "app_vacant", "whatsapp", "same_record", "guardrail", "result"].includes(id);
  const drums = !(id === "how" && b === HOW + 1);
  for (let k = 0; k < 8; k++) {
    const tt = t + k * BEAT / 2;
    if (drums && (b > 0 || k >= 4)) hat(tt, k % 2 ? 0.14 : 0.07);
    if (drums && k % 2 === 0 && (b >= 1)) kick(tt);
    if (drums && full && (k === 2 || k === 6)) clap(tt);
    if (id !== "hook" && drums) bass(tt, ch.bass + (k === 7 ? 12 : 0), BEAT / 2);
  }
  if (full) for (let k = 0; k < 16; k++) {
    const m = ch.notes[k % 3] + 12 + (k % 8 >= 6 ? 12 : 0);
    pluck(t + k * BEAT / 4, m, k % 2 ? 0.4 : -0.4);
  }
}
stab(WHY * BAR + BAR + BEAT);         // the "≠" in Why
riser(HOW * BAR, 2 * BAR);            // build through "How" into the app demo
impact(DEMO * BAR);                   // first demo lands
impact(RES * BAR);                    // result lands

// master: soft clip, normalise, fade ends
let peak = 0;
for (let i = 0; i < LEN; i++) { L[i] = Math.tanh(L[i] * 1.1); R[i] = Math.tanh(R[i] * 1.1); peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i])); }
const g = 0.89 / peak, fadeOut = 1.5 * SR;
const buf = Buffer.alloc(44 + LEN * 4);
buf.write("RIFF", 0); buf.writeUInt32LE(36 + LEN * 4, 4); buf.write("WAVE", 8); buf.write("fmt ", 12);
buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(2, 22); buf.writeUInt32LE(SR, 24);
buf.writeUInt32LE(SR * 4, 28); buf.writeUInt16LE(4, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(LEN * 4, 40);
for (let i = 0; i < LEN; i++) {
  const env = Math.min(1, i / 441) * Math.min(1, (LEN - i) / fadeOut);
  buf.writeInt16LE(Math.round(L[i] * g * env * 32767), 44 + i * 4);
  buf.writeInt16LE(Math.round(R[i] * g * env * 32767), 46 + i * 4);
}
fs.writeFileSync(new URL("../public/music.wav", import.meta.url), buf);
console.log(`music.wav: ${BARS} bars, ${(LEN / SR).toFixed(1)} s`);
