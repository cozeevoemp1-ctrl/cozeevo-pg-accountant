// Grab stills from a YouTube video for private style reference: node yt_frames.mjs <id> <outdir> <count>
import { chromium } from 'playwright';
import fs from 'node:fs';
const [id, dir, count = '24'] = process.argv.slice(2);
fs.mkdirSync(dir, { recursive: true });
const b = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 }, locale: 'en-US' });
await p.goto(`https://www.youtube.com/watch?v=${id}`, { waitUntil: 'domcontentloaded' });
await p.waitForSelector('video', { timeout: 30000 });
// wait out any pre-roll ad
for (let i = 0; i < 60; i++) {
  const ad = await p.evaluate(() => !!document.querySelector('.ad-showing'));
  if (!ad) break;
  await p.evaluate(() => document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button-modern')?.click());
  await p.waitForTimeout(1000);
}
await p.evaluate(() => { const v = document.querySelector('video'); v.muted = true; v.play(); });
await p.waitForTimeout(2000);
const dur = await p.evaluate(() => document.querySelector('video').duration);
console.log('duration', dur, 'title', await p.title());
const n = +count;
for (let i = 0; i < n; i++) {
  const t = Math.round((dur * (i + 0.5)) / n);
  await p.evaluate(t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }, t);
  await p.waitForFunction(() => { const v = document.querySelector('video'); return !v.seeking && v.readyState >= 2; }, null, { timeout: 20000 }).catch(() => {});
  await p.waitForTimeout(700);
  await p.locator('video').screenshot({ path: `${dir}/${String(i).padStart(2, '0')}_${t}s.png` });
}
await b.close();
