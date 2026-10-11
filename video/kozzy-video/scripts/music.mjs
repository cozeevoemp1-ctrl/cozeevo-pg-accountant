// Product-launch soundtrack generated in code -> public/music.wav. Reads src/timeline.json
// so every swell, impact and whoosh lands on a scene cut. Run: node scripts/music.mjs
import fs from "node:fs";

const T = JSON.parse(fs.readFileSync(new URL("../src/timeline.json", import.meta.url)));
const SR = 44100, BEAT = 60 / T.bpm, BAR = BEAT * 4;
const BARS = T.scenes.reduce((a, s) => a + s.bars, 0);
const TAIL = 2.5; // reverb ring-out after the last bar (the video length trims it)
const LEN = Math.ceil((BARS * BAR + TAIL) * SR);
const dry = [new Float32Array(LEN), new Float32Array(LEN)];
const send = [new Float32Array(LEN), new Float32Array(LEN)]; // -> reverb bus

const cuts = []; let acc = 0;
T.scenes.forEach(s => { acc += s.bars; cuts.push(acc); });
const startBar = id => { let b = 0; for (const s of T.scenes) { if (s.id === id) return b; b += s.bars; } return -1; };
const FIRST = startBar(T.scenes[1].id), LAST = startBar(T.scenes[T.scenes.length - 1].id);

// warm progression: Fmaj9 – C/E – Am7 – G, resolving to Cmaj7 on the end card
const PROG = [
  { root: 41, notes: [57, 60, 64, 67] },
  { root: 40, notes: [55, 60, 64, 67] },
  { root: 45, notes: [57, 60, 64, 67] },
  { root: 43, notes: [55, 59, 62, 67] },
];
const END = { root: 36, notes: [55, 60, 64, 67, 71] };
const chordOf = b => (b >= LAST + 1 ? END : PROG[b % 4]);
const hz = m => 440 * Math.pow(2, (m - 69) / 12);

let seed = 11;
const noise = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2147483648 - 1; };
function add(t0, dur, fn, gain = 1, pan = 0, rev = 0) {
  const s0 = Math.floor(t0 * SR), n = Math.floor(dur * SR);
  const gl = gain * Math.min(1, 1 - pan), gr = gain * Math.min(1, 1 + pan);
  for (let i = 0; i < n; i++) {
    const k = s0 + i; if (k < 0 || k >= LEN) continue;
    const v = fn(i / SR);
    dry[0][k] += v * gl; dry[1][k] += v * gr;
    if (rev) { send[0][k] += v * gl * rev; send[1][k] += v * gr * rev; }
  }
}
// sidechain pump: melodic parts duck under each kick
const kicks = [];
const duck = t => { let g = 1; for (const k of kicks) { const d = t - k; if (d >= 0 && d < 0.45) g = Math.min(g, 1 - 0.55 * Math.exp(-d * 9)); } return g; };

const kick = t0 => { kicks.push(t0); add(t0, 0.5, t => { const f = 42 + 120 * Math.exp(-t * 32); return Math.tanh(1.6 * Math.sin(2 * Math.PI * f * t) * Math.exp(-t * 6.5)); }, 0.95); };
const clap = t0 => { let a = 0, b = 0; add(t0, 0.3, t => { const x = noise(); a += 0.4 * (x - a); b += 0.07 * (a - b);
  const burst = t < 0.035 ? (Math.floor(t / 0.011) % 2 ? 0.35 : 1) : 1; return (a - b) * burst * Math.exp(-t * 16); }, 0.45, 0, 0.5); };
const shaker = (t0, g) => { let lp = 0; add(t0, 0.07, t => { const x = noise(); lp += 0.35 * (x - lp); return (x - lp) * Math.exp(-t * 55); }, g, 0.25); };
const sub = (t0, m, d) => add(t0, d, t => Math.sin(2 * Math.PI * hz(m) * t) * Math.min(1, t * 60) * Math.min(1, (d - t) * 30) * duck(t0 + t), 0.32);
function pad(t0, dur, notes, g, open) {
  notes.forEach((m, k) => [-9, 0, 9].forEach(c => {
    let lp = 0; const f = hz(m) * Math.pow(2, c / 1200);
    add(t0, dur + 1.2, t => {
      const saw = 2 * ((f * t) % 1) - 1;
      lp += (0.012 + 0.05 * open(t0 + t)) * (saw - lp);
      const env = Math.min(1, t / 0.6) * (t > dur ? Math.exp(-(t - dur) * 3) : 1);
      return lp * env * duck(t0 + t);
    }, g, (k - 1.5) * 0.3, 0.6);
  }));
}
const pluck = (t0, m, pan, g = 0.07) => add(t0, 0.6, t => { const f = hz(m); const ph = (f * t) % 1;
  return (Math.sin(2 * Math.PI * f * t) * 0.7 + (4 * Math.abs(ph - 0.5) - 1) * 0.3) * Math.exp(-t * 7) * duck(t0 + t); }, g, pan, 0.45);
function impact(t0) {
  add(t0, 2.2, t => Math.tanh(1.4 * Math.sin(2 * Math.PI * (28 + 70 * Math.exp(-t * 5)) * t)) * Math.exp(-t * 2), 0.85, 0, 0.3);
  let lp = 0; add(t0, 1.4, t => { lp += 0.15 * (noise() - lp); return lp * Math.exp(-t * 3.5); }, 0.7, 0, 0.8);
}
function whoosh(tEnd, dur = 0.9) { // filtered-noise sweep landing on a cut
  let lp = 0; add(tEnd - dur, dur + 0.25, t => { const p = Math.min(1, t / dur); lp += (0.01 + 0.25 * p * p) * (noise() - lp);
    return lp * Math.sin(Math.PI * Math.min(1, t / (dur + 0.25))) * 1.4; }, 0.5, 0, 0.6);
}
function swell(t0, dur) { // reverse-cymbal rise into the first product
  let lp = 0; add(t0, dur, t => { const p = t / dur; lp += (0.02 + 0.5 * p) * (noise() - lp); return lp * p * p * p; }, 0.55, 0, 0.5);
}
const shimmer = (t0, notes) => notes.forEach((m, i) => pluck(t0 + i * 0.06, m + 24, i % 2 ? 0.5 : -0.5, 0.05));

// ── arrangement ──
const filterOpen = t => Math.min(1, t / (FIRST * BAR)); // pad brightens through the intro
for (let b = 0; b < BARS; b++) {
  const t = b * BAR, ch = chordOf(b), intro = b < FIRST, last = b >= LAST + 1;
  pad(t, BAR, ch.notes, last ? 0.05 : 0.038, intro ? filterOpen : () => 1);
  if (intro) { for (let k = 0; k < 8; k++) shaker(t + k * BEAT / 2, b ? 0.05 : 0.025); sub(t, ch.root, BAR); continue; }
  if (last) { sub(t, ch.root, BAR + 1.5); continue; } // final bar: drums out, chord rings
  for (let k = 0; k < 4; k++) kick(t + k * BEAT);
  clap(t + BEAT); clap(t + 3 * BEAT);
  for (let k = 0; k < 16; k++) shaker(t + k * BEAT / 4, k % 4 === 2 ? 0.09 : 0.045);
  for (let k = 0; k < 8; k++) sub(t + k * BEAT / 2, ch.root + (k % 2 ? 12 : 0), BEAT / 2 - 0.02);
  const arp = [0, 1, 2, 3, 2, 1, 2, 3];
  for (let k = 0; k < 8; k++) pluck(t + k * BEAT / 2, ch.notes[arp[k]] + 12, k % 2 ? 0.45 : -0.45);
}
swell((FIRST - 1) * BAR, BAR);
impact(FIRST * BAR); shimmer(FIRST * BAR, PROG[0].notes);
cuts.slice(1, -1).forEach(c => whoosh(c * BAR));
impact(LAST * BAR); shimmer(LAST * BAR, END.notes);
shimmer((LAST + 1) * BAR, END.notes);

// ── reverb (Schroeder: 4 damped combs + 2 allpasses per channel) on the send bus ──
function reverb(x, spread) {
  const y = new Float32Array(LEN);
  [1557, 1617, 1491, 1422].forEach(d0 => {
    const d = d0 + spread, buf = new Float32Array(d); let i = 0, lp = 0;
    for (let n = 0; n < LEN; n++) { const o = buf[i]; lp = o * 0.75 + lp * 0.25; buf[i] = x[n] + lp * 0.84; i = (i + 1) % d; y[n] += o * 0.25; }
  });
  [556, 441].forEach(d0 => {
    const d = d0 + spread, buf = new Float32Array(d); let i = 0;
    for (let n = 0; n < LEN; n++) { const b = buf[i]; const v = -y[n] + b; buf[i] = y[n] + b * 0.5; i = (i + 1) % d; y[n] = v; }
  });
  return y;
}
const wet = [reverb(send[0], 0), reverb(send[1], 23)];

// ── master: mix, gentle saturation, normalise, fade the tail ──
const out = [new Float32Array(LEN), new Float32Array(LEN)];
let peak = 0;
for (let c = 0; c < 2; c++) for (let n = 0; n < LEN; n++) {
  const v = Math.tanh((dry[c][n] + wet[c][n] * 0.9) * 1.15);
  out[c][n] = v; peak = Math.max(peak, Math.abs(v));
}
const g = 0.89 / peak, fadeStart = (BARS * BAR - 2.5) * SR, fadeLen = 2.5 * SR; // silent exactly at the last frame
const wav = Buffer.alloc(44 + LEN * 4);
wav.write("RIFF", 0); wav.writeUInt32LE(36 + LEN * 4, 4); wav.write("WAVE", 8); wav.write("fmt ", 12);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(2, 22); wav.writeUInt32LE(SR, 24);
wav.writeUInt32LE(SR * 4, 28); wav.writeUInt16LE(4, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36); wav.writeUInt32LE(LEN * 4, 40);
for (let n = 0; n < LEN; n++) {
  const env = Math.min(1, n / 441) * (n < fadeStart ? 1 : Math.max(0, 1 - (n - fadeStart) / fadeLen));
  wav.writeInt16LE(Math.round(out[0][n] * g * env * 32767), 44 + n * 4);
  wav.writeInt16LE(Math.round(out[1][n] * g * env * 32767), 46 + n * 4);
}
fs.writeFileSync(new URL("../public/music.wav", import.meta.url), wav);
console.log(`music.wav: ${BARS} bars, ${(LEN / SR).toFixed(1)} s (incl. ${TAIL}s tail)`);
