// Scene list — single source for the video AND the storyboard.
// Times in seconds; 120 BPM => 1 bar = 2 s. Every cut lands on a bar downbeat.
const END_NAME = '[Your name]   ·   [Upwork / contact]';

// ---------- S1: the mess ----------
const SHEET_ROWS = [
  ['101', '12,000', '24,000', '✓', ''],
  ['118', '11,500', '—', '?', 'refund??'],
  ['204', '12,000', '24,000', '', 'paid cash?'],
  ['207', '13,000', '26,000', '✓', ''],
  ['311', '12,500', '', '', 'checking in?'],
  ['312', '12,500', '25,000', '✓', ''],
  ['409', '11,000', '22,000', 'part', 'see chat'],
  ['412', '13,000', '26,000', '', 'rent changed?'],
  ['415', '12,000', '24,000', '✓', ''],
];
const CHATS = [
  ['in', 'Room 204 paid 11,500 cash'],
  ['in', 'Is 311 checking in today?'],
  ['out', 'Which month is that for?'],
  ['in', 'Deposit for 118 refunded?'],
  ['in', 'Sheet not updated yet'],
  ['out', 'Who collected it?'],
];

function drawSheet(ctx, x, y, w, h, lt) {
  card(ctx, x, y, w, h);
  rr(ctx, x + 28, y + 22, 22, 22, 5); ctx.fillStyle = C.off; ctx.fill();
  txt(ctx, 'rent_tracker_FINAL_v3.xlsx', x + 62, y + 40, { size: 20, color: C.sub });
  const cols = [0.14, 0.2, 0.2, 0.14, 0.32], heads = ['Room', 'Rent', 'Deposit', 'Paid', 'Notes'];
  const gy = y + 64, rh = 52;
  ctx.fillStyle = C.bg; ctx.fillRect(x + 1, gy, w - 2, rh);
  let cx = x + 24;
  heads.forEach((hd, i) => { txt(ctx, hd, cx, gy + 34, { size: 19, weight: 600, color: C.sub }); cx += cols[i] * (w - 48); });
  SHEET_ROWS.forEach((row, ri) => {
    const a = ease.out(prog(lt, 0.1 + ri * 0.06, 0.35 + ri * 0.06));
    const ry = gy + rh * (ri + 1);
    ctx.save(); ctx.globalAlpha *= a;
    ctx.strokeStyle = C.line; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x + 1, ry); ctx.lineTo(x + w - 1, ry); ctx.stroke();
    let cx2 = x + 24;
    row.forEach((v, i) => {
      txt(ctx, v, cx2, ry + 34, { size: 20, color: i === 4 ? C.red : C.ink, italic: i === 4 });
      cx2 += cols[i] * (w - 48);
    });
    ctx.restore();
  });
}

function drawChats(ctx, x, y, w, h, lt) {
  card(ctx, x, y, w, h);
  txt(ctx, 'Chats', x + 28, y + 44, { size: 26, weight: 700 });
  dot(ctx, x + w - 44, y + 35, 18, C.pink);
  txt(ctx, '12', x + w - 44, y + 42, { size: 18, weight: 700, color: '#fff', align: 'center' });
  ctx.strokeStyle = C.line; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x, y + 68); ctx.lineTo(x + w, y + 68); ctx.stroke();
  let by = y + 88;
  CHATS.forEach(([side, s], i) => {
    const p = prog(lt, 0.5 + i * BEAT, 0.5 + i * BEAT + 0.28);
    const bh = bubble(ctx, [s], x + 24, by, w - 48, side, p, 22);
    by += (bh || 58) + 14;
  });
}

function s1(ctx, lt) {
  const a = ease.out(prog(lt, 0, 0.6));
  ctx.save(); ctx.globalAlpha = a;
  ctx.translate(560, 450); ctx.rotate(-0.018); ctx.translate(-560, -450 + (1 - a) * 30);
  drawSheet(ctx, 190, 150, 740, 600, lt);
  ctx.restore();
  ctx.save(); ctx.globalAlpha = a;
  ctx.translate(1370, 450); ctx.rotate(0.014); ctx.translate(-1370, -450 + (1 - a) * 30);
  drawChats(ctx, 1030, 150, 690, 600, lt);
  ctx.restore();
}

// ---------- S2: numbers don't match ----------
function amountCard(ctx, x, y, label, amt, p, redP) {
  const w = 600, h = 340;
  ctx.save(); ctx.globalAlpha *= ease.out(p);
  card(ctx, x, y, w, h);
  txt(ctx, label, x + 48, y + 66, { size: 19, weight: 600, color: C.faint, spacing: 3 });
  txt(ctx, 'Room 204  ·  June rent', x + 48, y + 128, { size: 32, color: C.sub });
  txt(ctx, amt, x + 48, y + 262, { size: 104, weight: 700, color: redP > 0.5 ? C.red : C.ink });
  ctx.restore();
}

function s2(ctx, lt, t) {
  const pl = prog(lt, 0, 0.5), pr = prog(lt, 0.25, 0.75);
  ctx.save(); ctx.translate(-(1 - ease.out(pl)) * 120, 0);
  amountCard(ctx, 300, 250, 'SPREADSHEET', '₹12,000', pl, prog(lt, 1.5, 1.6));
  ctx.restore();
  ctx.save(); ctx.translate((1 - ease.out(pr)) * 120, 0);
  amountCard(ctx, 1020, 250, 'WHATSAPP CHAT', '₹11,500', pr, prog(lt, 1.5, 1.6));
  ctx.restore();
  const bp = prog(lt, 1.0, 1.3);
  if (bp > 0) {
    const s = ease.back(bp) * (1 + 0.08 * beatPulse(t));
    ctx.save(); ctx.translate(960, 420); ctx.scale(s, s);
    dot(ctx, 0, 0, 58, '#fff'); ctx.lineWidth = 5; ctx.strokeStyle = C.red; ctx.beginPath(); ctx.arc(0, 0, 58, 0, Math.PI * 2); ctx.stroke();
    txt(ctx, '≠', 0, 26, { size: 76, weight: 700, color: C.red, align: 'center' });
    ctx.restore();
  }
  const gp = ease.out(prog(lt, 2.0, 2.4));
  txt(ctx, 'Which one is right?', 960, 660 - (1 - gp) * 14, { size: 30, weight: 600, color: C.red, align: 'center', alpha: gp });
}

// ---------- S3: one place ----------
const PARTS = (() => {
  const r = rng(7), out = [];
  for (let i = 0; i < 80; i++) {
    const left = i % 2 === 0;
    out.push({
      x: left ? 200 + r() * 720 : 1040 + r() * 680, y: 160 + r() * 580,
      d: r() * 0.55, arc: (r() - 0.5) * 260, w: 30 + r() * 40,
      c: r() < 0.18 ? C.pink : r() < 0.3 ? C.blue : '#D5D5DE',
    });
  }
  return out;
})();

function s3(ctx, lt, t) {
  const cx = 960, cy = 410;
  const dbS = ease.back(prog(lt, 0.0, 0.45));
  // rings on each beat once the record exists
  if (lt > 2.0) {
    const k = (t % BEAT) / BEAT;
    ctx.save(); ctx.strokeStyle = C.pink; ctx.globalAlpha = 0.35 * (1 - k); ctx.lineWidth = 4;
    ctx.beginPath(); ctx.ellipse(cx, cy + 10, 170 + k * 150, 170 + k * 150, 0, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
  }
  cylinder(ctx, cx, cy, 250, 270, dbS);
  PARTS.forEach(q => {
    const p = ease.inOut(prog(lt, q.d, q.d + 0.95));
    if (p >= 1) return;
    const x = lerp(q.x, cx, p), y = lerp(q.y, cy, p) - Math.sin(Math.PI * p) * q.arc;
    const s = 1 - 0.7 * p;
    ctx.save(); ctx.globalAlpha = 1 - prog(p, 0.75, 1);
    rr(ctx, x - (q.w * s) / 2, y - 8 * s, q.w * s, 16 * s, 6 * s); ctx.fillStyle = q.c; ctx.fill(); ctx.restore();
  });
  const lp = ease.out(prog(lt, 2.0, 2.4));
  txt(ctx, 'One shared record', cx, 660 - (1 - lp) * 14, { size: 36, weight: 600, align: 'center', alpha: lp });
}

// ---------- Demo footage (real screen recordings) ----------
// MEDIA[key] = HTMLVideoElement, loaded by the host page; prepare(t) seeks it before render(t).
const MEDIA = {};
const CLIPS = { wa: 'out/wa_demo.mp4', pwa: 'out/pwa_demo.mp4' };
function clipTime(key, lt, dur) {
  const v = MEDIA[key];
  if (!v || !v.duration) return 0;
  return clamp(lt * (v.duration / dur), 0, v.duration - 0.04);
}

function browserWindow(ctx, x, y, w, h, draw) {
  card(ctx, x, y, w, h, { r: 16, stroke: '#D6D6DE' });
  ctx.save(); rr(ctx, x, y, w, 44, [16, 16, 0, 0]); ctx.fillStyle = '#EEEEF2'; ctx.fill(); ctx.restore();
  ['#FF5F57', '#FEBC2E', '#28C840'].forEach((c, i) => dot(ctx, x + 26 + i * 22, y + 22, 7, c));
  ctx.save(); rr(ctx, x + 1, y + 44, w - 2, h - 45, [0, 0, 15, 15]); ctx.clip();
  draw(x + 1, y + 44, w - 2, h - 45);
  ctx.restore();
}

function sWa(ctx, lt) {
  const a = ease.out(prog(lt, 0, 0.5)), s = 0.94 + 0.06 * a;
  const w = 1230, h = 44 + 1230 / 1.5, x = (W - w) / 2, y = 52;
  ctx.save(); ctx.globalAlpha = a; ctx.translate(W / 2, y + h / 2); ctx.scale(s, s); ctx.translate(-W / 2, -(y + h / 2));
  browserWindow(ctx, x, y, w, h, (sx, sy, sw, sh) => { if (MEDIA.wa) ctx.drawImage(MEDIA.wa, sx, sy, sw, sh); });
  ctx.restore();
  caption(ctx, 'Staff just message the assistant on *WhatsApp.*', lt, { y: 1000, size: 46, start: 0.15 });
}

function sPwa(ctx, lt) {
  const a = ease.out(prog(lt, 0, 0.5));
  const sh = 872, sw = sh * (748 / 1744);
  ctx.save(); ctx.globalAlpha = a; ctx.translate(0, (1 - a) * 40);
  phone(ctx, 470, 92, sw + 24, sh + 24, (c, x, y, w, h) => { if (MEDIA.pwa) c.drawImage(MEDIA.pwa, x, y, w, h); });
  ctx.restore();
  const tx = 1010;
  caption2(ctx, ['Managers see every', 'bed and every due', 'in the *web app.*'], tx, 430, lt, 72);
  txt(ctx, 'Free beds  ·  who is in each room  ·  what is owed', tx, 690, { size: 26, color: C.sub, alpha: ease.out(prog(lt, 1.0, 1.4)) });
}

// left-aligned multi-line word reveal (used where the visual sits beside the text)
function caption2(ctx, lines, x, y, lt, size) {
  ctx.save(); ctx.font = `700 ${size}px ${FONT}`; ctx.textBaseline = 'alphabetic';
  const sp = ctx.measureText(' ').width; let wi = 0;
  lines.forEach((line, li) => {
    let xx = x;
    line.split(' ').forEach(w => {
      const hi = w.includes('*'), s = w.replace(/\*/g, '');
      const p = ease.out(prog(lt, 0.2 + wi * 0.07, 0.55 + wi * 0.07));
      ctx.globalAlpha = p; ctx.fillStyle = hi ? C.pink : C.ink;
      ctx.fillText(s, xx, y + li * size * 1.2 + (1 - p) * 18);
      xx += ctx.measureText(s).width + sp; wi++;
    });
  });
  ctx.restore();
}

// ---------- S5: a person confirms ----------
const FLOW = [
  { x: 270, t: 'Staff message', s: 'text or voice note', at: 0.0 },
  { x: 730, t: 'Assistant reads it', s: 'AI only if it is unclear', at: 0.5, c: C.blue },
  { x: 1190, t: 'Staff confirm', s: 'before key changes', at: 2.0, c: C.pink },
  { x: 1650, t: 'Saved', s: 'with who and when', at: 2.5 },
];
function s5(ctx, lt) {
  const y = 430, w = 320, h = 140;
  for (let i = 0; i < FLOW.length - 1; i++) {
    const a = FLOW[i], b = FLOW[i + 1];
    const ep = prog(lt, b.at - 0.4, b.at);
    curve(ctx, { x: a.x + w / 2, y }, { x: b.x - w / 2, y }, ep, { lw: 5, color: '#CFCFD8' });
    const k = ((lt - b.at) % 1 + 1) % 1;
    if (lt > b.at) dot(ctx, lerp(a.x + w / 2, b.x - w / 2, k), y, 7, b.c || C.pink, 0.8);
  }
  FLOW.forEach((n, i) => {
    const p = prog(lt, n.at, n.at + 0.3);
    if (p <= 0) return;
    const s = 0.85 + 0.15 * ease.back(p);
    ctx.save(); ctx.globalAlpha = ease.out(p); ctx.translate(n.x, y); ctx.scale(s, s); ctx.translate(-n.x, -y);
    card(ctx, n.x - w / 2, y - h / 2, w, h, { stroke: n.c || C.line, lw: n.c ? 3 : 1.5 });
    txt(ctx, n.t, n.x, y - 6, { size: 32, weight: 700, align: 'center' });
    txt(ctx, n.s, n.x, y + 36, { size: 21, color: C.sub, align: 'center' });
    ctx.restore();
    if (i === FLOW.length - 1) check(ctx, n.x + w / 2 - 6, y - h / 2 + 6, 24, prog(lt, n.at + 0.2, n.at + 0.5));
  });
}

// ---------- S6: every change recorded ----------
const LOG = [
  ['10:02', 'Payment', 'Room 204 · ₹12,000', 'Reception'],
  ['10:15', 'Check-in', 'Room 311', 'Reception'],
  ['10:31', 'Deposit updated', 'Room 118', 'Manager'],
  ['10:44', 'Rent changed', 'Room 412 · from July', 'Manager'],
  ['11:05', 'Payment cancelled', 'Room 207 · kept on record', 'Manager'],
  ['11:20', 'Check-out', 'Room 109', 'Reception'],
];
function s6(ctx, lt) {
  const x = 380, y = 140, w = 1160, h = 620;
  const a = ease.out(prog(lt, 0, 0.4));
  ctx.save(); ctx.globalAlpha = a;
  card(ctx, x, y, w, h);
  txt(ctx, 'History', x + 48, y + 64, { size: 32, weight: 700 });
  txt(ctx, 'who changed what, and when', x + w - 48, y + 64, { size: 21, color: C.sub, align: 'right' });
  [['TIME', 48], ['WHAT', 190], ['DETAIL', 500], ['BY', w - 48]].forEach(([l, ox], i) =>
    txt(ctx, l, x + ox, y + 118, { size: 15, weight: 600, color: C.faint, spacing: 2, align: i === 3 ? 'right' : 'left' }));
  LOG.forEach((r, i) => {
    const at = 0.25 + i * BEAT, p = ease.out(prog(lt, at, at + 0.25));
    if (p <= 0) return;
    const ry = y + 136 + i * 76;
    ctx.save(); ctx.globalAlpha *= p; ctx.translate(0, (1 - p) * -12);
    const fl = Math.exp(-4 * Math.max(0, lt - at));
    rr(ctx, x + 24, ry, w - 48, 66, 12); ctx.fillStyle = `rgba(239,31,156,${0.1 * fl})`; ctx.fill();
    txt(ctx, r[0], x + 48, ry + 42, { size: 22, color: C.sub });
    txt(ctx, r[1], x + 190, ry + 42, { size: 24, weight: 600 });
    txt(ctx, r[2], x + 500, ry + 42, { size: 22, color: C.sub });
    txt(ctx, r[3], x + w - 48, ry + 42, { size: 22, color: C.sub, align: 'right' });
    ctx.restore();
  });
  ctx.restore();
}

// ---------- S7: left to people ----------
const TASKS = [
  ['Reading staff messages', 'Assisted by AI', 'Assisted by AI', null],
  ['Recording payments', 'Automatic', 'Staff, in the app', 0.5],
  ['Messages to residents', 'Automatic', 'Sent by people', 1.0],
];
function s7(ctx, lt) {
  const x = 500, y = 200, w = 920, rh = 140;
  const a = ease.out(prog(lt, 0, 0.3));
  ctx.save(); ctx.globalAlpha = a;
  card(ctx, x, y, w, rh * 3 + 40);
  TASKS.forEach(([label, before, after, at], i) => {
    const ry = y + 20 + i * rh;
    if (i) { ctx.strokeStyle = C.line; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x + 40, ry); ctx.lineTo(x + w - 40, ry); ctx.stroke(); }
    const p = at == null ? 0 : prog(lt, at, at + 0.25);
    txt(ctx, label, x + 56, ry + 64, { size: 32, weight: 600 });
    txt(ctx, p > 0.5 ? after : before, x + 56, ry + 104, { size: 23, color: p > 0.5 ? C.pink : C.sub, weight: p > 0.5 ? 600 : 400 });
    toggle(ctx, x + w - 150, ry + 46, at == null, at == null ? 1 : p);
  });
  ctx.restore();
}

// ---------- S8: result + end card ----------
function totalScreen(ctx, sx, sy, sw, sh, size) {
  txt(ctx, 'Collected · June', sx + sw / 2, sy + sh / 2 - size * 0.55, { size: size * 0.42, color: C.sub, align: 'center' });
  txt(ctx, '₹4,82,500', sx + sw / 2, sy + sh / 2 + size * 0.45, { size, weight: 700, align: 'center' });
}
function s8(ctx, lt) {
  const out = ease.inOut(prog(lt, 1.7, 2.1));
  if (out < 1) {
    const a = ease.out(prog(lt, 0, 0.4)) * (1 - out);
    ctx.save(); ctx.globalAlpha = a; ctx.translate(0, -out * 40);
    phone(ctx, 470, 170, 300, 540, (c, sx, sy, sw, sh) => totalScreen(c, sx, sy, sw, sh, 52));
    laptop(ctx, 1080, 250, 460, 300, (c, sx, sy, sw, sh) => totalScreen(c, sx, sy, sw, sh, 64));
    check(ctx, 925, 420, 40, prog(lt, 0.5, 0.8));
    ctx.restore();
    caption(ctx, 'The result:', lt, { alpha: 1 - out, start: 0.2 });
  }
  if (lt > 2.0) {
    const e = lt - 2.0;
    caption(ctx, '*One* record.\n*One* set of numbers.', e, { y: 470, size: 92, step: 0.1 });
    const np = ease.out(prog(e, 0.8, 1.2));
    ctx.save(); ctx.globalAlpha = np;
    ctx.fillStyle = C.pink; ctx.fillRect(960 - 40, 650, 80, 4);
    ctx.restore();
    txt(ctx, END_NAME, 960, 720, { size: 28, color: C.sub, align: 'center', alpha: np });
  }
}

const SCENES = [
  { id: 1, start: 0, end: 4, name: 'The mess', draw: s1, thumbAt: 3.4,
    caption: 'Rent, deposits and check-ins lived in\n*spreadsheets* and *WhatsApp chats.*',
    motion: 'Sheet rows cascade in; chat bubbles pop on every beat, both cards slightly tilted (messy).',
    sound: 'Pad + 8th hats. A soft blip on each bubble.' },
  { id: 2, start: 4, end: 8, name: 'No match', draw: s2, thumbAt: 6.8,
    caption: 'The figures rarely matched.',
    motion: 'Same rent, two amounts. Red ≠ pops on beat 3 and pulses; "Which one is right?"',
    sound: 'Bass enters. Dissonant stab on the ≠.' },
  { id: 3, start: 8, end: 12, name: 'One place', draw: s3, thumbAt: 10.9,
    caption: 'So I brought everything into *one place.*',
    motion: 'Every cell and bubble flies into one pink record; rings pulse on the beat.',
    sound: 'Riser → impact on the downbeat. Kick + clap groove starts.' },
  { id: 4, start: 12, end: 24, name: 'Demo: WhatsApp check-in', draw: sWa, thumbAt: 21.5, media: 'wa', ownCaption: true,
    caption: 'Staff just message the assistant on WhatsApp.',
    motion: 'REAL recording, sandbox bot + test data: "Arnav Kulkarni arrived" → amount due → confirm → checked in. Then a payment message is refused: "use the app".',
    sound: 'Full groove + arp. Soft tick on each sent message.' },
  { id: 5, start: 24, end: 30, name: 'Demo: free beds', draw: sPwa, thumbAt: 28.6, media: 'pwa', ownCaption: true,
    caption: 'Managers see every bed and every due in the web app.',
    motion: 'REAL recording of the app (dummy data): Bed Board → tap rooms with free beds → occupants and dues.',
    sound: 'Groove continues. Tap sound on each room.' },
  { id: 6, start: 30, end: 34, name: 'People confirm', draw: s5, thumbAt: 33.4,
    caption: 'AI only helps with unclear messages.\nIt never saves anything on its *own.*',
    motion: 'Four steps light up left→right; "Staff confirm" in pink; check mark on Saved.',
    sound: 'Groove. Chime on the check.' },
  { id: 7, start: 34, end: 38, name: 'History', draw: s6, thumbAt: 37.4,
    caption: 'Every change is recorded: who, what and when.',
    motion: 'History rows drop in one per beat with a pink flash. Cancelled items stay on record.',
    sound: 'Groove. Tick on each row.' },
  { id: 8, start: 38, end: 40, name: 'Restraint', draw: s7, thumbAt: 39.7,
    caption: 'Some tasks were deliberately\nleft to *people.*',
    motion: 'Two toggles switch off on beats; labels turn pink: "Staff, in the app", "Sent by people".',
    sound: 'Breakdown: drums drop out, pad only. Click on each toggle.' },
  { id: 9, start: 40, end: 46, name: 'Result + end card', draw: s8, thumbAt: 45, ownCaption: true,
    caption: 'The result: One record. One set of numbers. + name / contact',
    motion: 'Phone and web app show the same total, check between. Then the end card holds for 2 bars.',
    sound: 'Full return, resolves on C; final chord rings out.' },
];

function sceneAt(t) { return SCENES.find(s => t >= s.start && t < s.end) || SCENES[SCENES.length - 1]; }

// Load demo clips into MEDIA (call once from the host page)
async function loadMedia() {
  await Promise.all(Object.entries(CLIPS).map(([k, src]) => new Promise((res, rej) => {
    const v = document.createElement('video');
    v.muted = true; v.preload = 'auto';
    fetch(src).then(r => r.blob()).then(b => { v.src = URL.createObjectURL(b); }, rej);
    v.onloadeddata = () => { MEDIA[k] = v; res(); }; v.onerror = () => rej(new Error('cannot load ' + src));
  })));
}
// Seek the clip the frame at t needs; await before render(ctx, t)
async function prepare(t) {
  const s = sceneAt(t);
  if (!s.media || !MEDIA[s.media]) return;
  const v = MEDIA[s.media], target = clipTime(s.media, t - s.start, s.end - s.start);
  if (Math.abs(v.currentTime - target) < 0.001 && v.readyState >= 2) return;
  await new Promise(res => { v.onseeked = res; v.currentTime = target; });
}

function render(ctx, t) {
  ctx.save();
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H);
  const s = sceneAt(t), lt = t - s.start;
  // quick dip at each cut (not on the very first/last frame)
  const fin = s.start === 0 ? 1 : ease.out(prog(lt, 0, 0.12));
  const fout = s.end === DURATION ? 1 : 1 - ease.in(prog(lt, s.end - s.start - 0.1, s.end - s.start));
  ctx.globalAlpha = fin * fout;
  s.draw(ctx, lt, t);
  if (!s.ownCaption) caption(ctx, s.caption, lt, { start: 0.15 });
  ctx.restore();
}
