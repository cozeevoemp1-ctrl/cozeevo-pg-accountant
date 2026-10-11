// Record the PWA demo from mockups/kozzy.html (dummy data, no backend). Output: out/pwa_demo.mp4
import { chromium } from 'playwright';
import fs from 'node:fs';
import { startCapture } from './capture.mjs';

const Z = 2; // CSS zoom -> 2x-resolution capture of the 374x872 screen
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 440 * Z, height: 960 * Z }, deviceScaleFactor: 1 });
// file has no <meta charset>; serve it as UTF-8 so ₹ and icons render
await page.route('http://demo.local/kozzy.html', r => r.fulfill({ body: fs.readFileSync('../../mockups/kozzy.html'), contentType: 'text/html; charset=utf-8' }));
await page.goto('http://demo.local/kozzy.html');
await page.addStyleTag({ content: `body{zoom:${Z}} .tapdot{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
  background:rgba(239,31,156,.35);border:2px solid rgba(239,31,156,.8);pointer-events:none;z-index:99999;animation:tap .5s ease-out forwards}
  @keyframes tap{from{transform:scale(.4);opacity:1}to{transform:scale(1.4);opacity:0}}` });
await page.waitForTimeout(800);
const box = await page.locator('.screen').boundingBox();
const crop = `${Math.round(box.width)}:${Math.round(box.height)}:${Math.round(box.x)}:${Math.round(box.y)}`;

async function tap(locator) {
  const b = await locator.boundingBox();
  const x = b.x + b.width / 2, y = b.y + b.height / 2;
  await page.evaluate(([x, y, z]) => { const d = document.createElement('div'); d.className = 'tapdot';
    d.style.left = x / z + 'px'; d.style.top = y / z + 'px'; document.body.appendChild(d); setTimeout(() => d.remove(), 600); }, [x, y, Z]);
  await page.mouse.click(x, y);
}
async function scroll(dy, ms = 700) {
  await page.evaluate(([dy]) => document.querySelector('.scroll.page.active')?.scrollBy({ top: dy, behavior: 'smooth' }), [dy]);
  await page.waitForTimeout(ms);
}

const stop = await startCapture(page, 'out/pwa_frames');
await page.waitForTimeout(1000);
await tap(page.locator('.tab', { hasText: 'Board' }));
await page.waitForTimeout(1300);
for (const room of ['204', '207']) {
  await tap(page.locator('.hroom', { has: page.locator('.rno', { hasText: room }) }).first());
  await page.waitForTimeout(1500);
}
await page.waitForTimeout(400);
await stop('out/pwa_demo.mp4', { crop });
await browser.close();
