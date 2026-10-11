// Shared constants + drawing primitives — used by the video (index.html) and the storyboard.
const W = 1920, H = 1080, FPS = 30, BPM = 120;
const BEAT = 60 / BPM;   // 0.5 s
const BAR = BEAT * 4;    // 2 s
const DURATION = 46;     // 23 bars
const C = {
  pink: '#EF1F9C', blue: '#00AEED', ink: '#16161D', sub: '#5E5E6B', faint: '#9A9AA6',
  line: '#E4E4EA', card: '#FFFFFF', bg: '#F6F6F9', red: '#E5484D',
  pinkSoft: '#FDE7F3', blueSoft: '#E3F6FD', grey: '#F1F1F5', off: '#D9D9E0',
};
const FONT = '"Segoe UI", system-ui, sans-serif';

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const prog = (t, a, b) => clamp((t - a) / (b - a));
const ease = {
  out: t => 1 - Math.pow(1 - t, 3),
  in: t => t * t * t,
  inOut: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  back: t => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
};
// 1 on each beat, decaying until the next one (t = global seconds)
const beatPulse = (t, decay = 7) => Math.exp(-decay * (t % BEAT));

function rng(seed) {
  return function () {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }

function card(ctx, x, y, w, h, o = {}) {
  ctx.save();
  if (o.shadow !== false) {
    ctx.shadowColor = 'rgba(22,22,40,0.08)'; ctx.shadowBlur = 36; ctx.shadowOffsetY = 12;
  }
  rr(ctx, x, y, w, h, o.r ?? 20);
  ctx.fillStyle = o.fill || C.card; ctx.fill();
  ctx.shadowColor = 'transparent';
  if (o.stroke !== null) { ctx.lineWidth = o.lw || 1.5; ctx.strokeStyle = o.stroke || C.line; ctx.stroke(); }
  ctx.restore();
}

function txt(ctx, s, x, y, o = {}) {
  ctx.save();
  ctx.font = `${o.italic ? 'italic ' : ''}${o.weight || 400} ${o.size || 24}px ${FONT}`;
  ctx.fillStyle = o.color || C.ink;
  ctx.textAlign = o.align || 'left';
  ctx.textBaseline = o.base || 'alphabetic';
  if (o.alpha != null) ctx.globalAlpha *= o.alpha;
  if (o.spacing) ctx.letterSpacing = o.spacing + 'px';
  ctx.fillText(s, x, y);
  const w = ctx.measureText(s).width;
  ctx.restore();
  return w;
}

function measure(ctx, s, size, weight = 400) {
  ctx.save(); ctx.font = `${weight} ${size}px ${FONT}`; const w = ctx.measureText(s).width; ctx.restore(); return w;
}

// Word-by-word caption. Words wrapped in *stars* render pink.
function caption(ctx, str, lt, o = {}) {
  const size = o.size || 52, lh = size * 1.32, step = o.step ?? 0.07, start = o.start || 0;
  const lines = str.split('\n');
  const y0 = (o.y || 905) - ((lines.length - 1) * lh) / 2;
  ctx.save();
  ctx.font = `600 ${size}px ${FONT}`;
  ctx.textBaseline = 'middle';
  const sp = ctx.measureText(' ').width;
  let wi = 0;
  lines.forEach((line, li) => {
    const words = line.split(' ').map(w => ({ hi: w.includes('*'), s: w.replace(/\*/g, '') }));
    words.forEach(w => (w.w = ctx.measureText(w.s).width));
    const total = words.reduce((a, w) => a + w.w, 0) + sp * (words.length - 1);
    let x = W / 2 - total / 2;
    words.forEach(w => {
      const p = ease.out(prog(lt, start + wi * step, start + wi * step + 0.35));
      ctx.globalAlpha = p * (o.alpha ?? 1);
      ctx.fillStyle = w.hi ? C.pink : (o.color || C.ink);
      ctx.fillText(w.s, x, y0 + li * lh + (1 - p) * 20);
      x += w.w + sp; wi++;
    });
  });
  ctx.restore();
}

// Point on a cubic bezier
function bez(p0, p1, p2, p3, t) {
  const u = 1 - t;
  return {
    x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
    y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
  };
}
// Draw a horizontal-ish S-curve from a to b, revealed up to fraction p
function curve(ctx, a, b, p, o = {}) {
  if (p <= 0) return;
  const mx = (a.x + b.x) / 2, c1 = { x: mx, y: a.y }, c2 = { x: mx, y: b.y };
  ctx.save();
  ctx.lineWidth = o.lw || 4; ctx.strokeStyle = o.color || C.line; ctx.lineCap = 'round';
  if (o.dash) ctx.setLineDash(o.dash);
  ctx.beginPath();
  const n = 48;
  for (let i = 0; i <= n * p; i++) { const q = bez(a, c1, c2, b, i / n); i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y); }
  ctx.stroke();
  ctx.restore();
  return t => bez(a, c1, c2, b, t);
}

function dot(ctx, x, y, r, color, alpha = 1) {
  ctx.save(); ctx.globalAlpha *= alpha; ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); ctx.restore();
}

function check(ctx, x, y, r, p = 1, color = C.blue) {
  if (p <= 0) return;
  ctx.save();
  ctx.translate(x, y); ctx.scale(ease.back(p), ease.back(p));
  dot(ctx, 0, 0, r, color);
  ctx.strokeStyle = '#fff'; ctx.lineWidth = r * 0.22; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.beginPath(); ctx.moveTo(-r * 0.42, 0); ctx.lineTo(-r * 0.1, r * 0.32); ctx.lineTo(r * 0.45, -r * 0.3); ctx.stroke();
  ctx.restore();
}

// Phone frame; content(ctx, sx, sy, sw, sh) draws inside the screen (clipped)
function phone(ctx, x, y, w, h, content) {
  card(ctx, x, y, w, h, { r: 46, fill: C.ink, stroke: null });
  const sx = x + 12, sy = y + 12, sw = w - 24, sh = h - 24;
  ctx.save(); rr(ctx, sx, sy, sw, sh, 36); ctx.fillStyle = '#fff'; ctx.fill(); ctx.clip();
  content(ctx, sx, sy, sw, sh);
  ctx.restore();
}

// Laptop: screen rect (x,y,w,h) + base below
function laptop(ctx, x, y, w, h, content) {
  card(ctx, x, y, w, h, { r: 18, fill: C.ink, stroke: null });
  const sx = x + 12, sy = y + 12, sw = w - 24, sh = h - 24;
  ctx.save(); rr(ctx, sx, sy, sw, sh, 8); ctx.fillStyle = '#fff'; ctx.fill(); ctx.clip();
  content(ctx, sx, sy, sw, sh);
  ctx.restore();
  ctx.save();
  ctx.fillStyle = '#2A2A33';
  ctx.beginPath(); ctx.moveTo(x - 40, y + h); ctx.lineTo(x + w + 40, y + h); ctx.lineTo(x + w + 20, y + h + 22); ctx.lineTo(x - 20, y + h + 22); ctx.closePath(); ctx.fill();
  ctx.restore();
}

// Chat bubble; returns its height. side: 'in' (left, grey) | 'out' (right, blue tint)
function bubble(ctx, lines, x, y, maxW, side, p = 1, size = 20) {
  if (p <= 0) return 0;
  const pad = 16, lh = size * 1.35;
  const tw = Math.max(...lines.map(l => measure(ctx, l, size)));
  const bw = Math.min(maxW, tw + pad * 2), bh = lines.length * lh + pad * 1.3;
  const bx = side === 'out' ? x + maxW - bw : x;
  ctx.save();
  const ox = side === 'out' ? bx + bw : bx, s = 0.6 + 0.4 * ease.back(p);
  ctx.translate(ox, y + bh); ctx.scale(s, s); ctx.translate(-ox, -(y + bh));
  ctx.globalAlpha *= clamp(p * 2);
  rr(ctx, bx, y, bw, bh, 16);
  ctx.fillStyle = side === 'out' ? C.blueSoft : C.grey; ctx.fill();
  lines.forEach((l, i) => txt(ctx, l, bx + pad, y + pad * 0.65 + lh * (i + 0.72), { size, color: C.ink }));
  ctx.restore();
  return bh;
}

// Simple database / record stack icon
function cylinder(ctx, cx, cy, w, h, s = 1, color = C.pink) {
  ctx.save();
  ctx.translate(cx, cy); ctx.scale(s, s);
  const rx = w / 2, ry = w * 0.16, top = -h / 2, bot = h / 2;
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.moveTo(-rx, top); ctx.lineTo(-rx, bot); ctx.ellipse(0, bot, rx, ry, 0, Math.PI, 0, true); ctx.lineTo(rx, top); ctx.closePath(); ctx.fill();
  ctx.strokeStyle = 'rgba(255,255,255,0.55)'; ctx.lineWidth = 5;
  [1 / 3, 2 / 3].forEach(f => { const yy = top + h * f; ctx.beginPath(); ctx.ellipse(0, yy, rx, ry, 0, 0, Math.PI); ctx.stroke(); });
  ctx.fillStyle = '#F65DB6';
  ctx.beginPath(); ctx.ellipse(0, top, rx, ry, 0, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}

function toggle(ctx, x, y, on, p = 1) {
  // on: target state; p: progress toward it from the opposite
  const k = on ? ease.inOut(p) : 1 - ease.inOut(p);
  const w = 88, h = 48;
  ctx.save();
  rr(ctx, x, y, w, h, h / 2);
  ctx.fillStyle = k > 0.5 ? C.blue : C.off; ctx.fill();
  dot(ctx, x + h / 2 + (w - h) * k, y + h / 2, h / 2 - 5, '#fff');
  ctx.restore();
}
