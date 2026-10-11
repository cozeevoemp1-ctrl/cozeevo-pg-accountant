// Record the WhatsApp-style demo: real messages -> real sandbox bot (synthetic data).
// Prereq: sandbox DB reset + sandbox_server.py on :8100. Output: out/wa_demo.mp4
import { chromium } from 'playwright';
import fs from 'node:fs';
import { startCapture } from './capture.mjs';

const BOT = 'http://localhost:8100', PHONE = '917680814628'; // sandbox receptionist
const SCRIPT = [
  ['Arnav Kulkarni arrived', 1700],
  ['skip', 1200],
  ['yes', 1500],
  ['Pratik Rastogi paid 14000 cash', 1900],
];

await fetch(BOT + '/api/test/clear-pending', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ phone: PHONE }) });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1800, height: 1200 }, deviceScaleFactor: 1 });
await page.route('http://demo.local/wa.html', r => r.fulfill({ body: fs.readFileSync('demo/wa.html'), contentType: 'text/html; charset=utf-8' }));
let n = 0;
await page.route('http://demo.local/bot', async r => {
  const { message } = JSON.parse(r.request().postData());
  const res = await fetch(BOT + '/api/whatsapp/process', { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ phone: PHONE, message, message_id: `video-${Date.now()}-${n++}` }) });
  const d = await res.json();
  console.log(`>>> ${message} [${d.intent}]\n${d.reply}\n`);
  await r.fulfill({ body: JSON.stringify(d), contentType: 'application/json' });
});
await page.goto('http://demo.local/wa.html');
await page.waitForTimeout(400);
const stop = await startCapture(page, 'out/wa_frames');
await page.waitForTimeout(700);
for (const [msg, hold] of SCRIPT) {
  await page.click('#box');
  const before = await page.evaluate(() => window.__lastReply);
  await page.keyboard.type(msg, { delay: 38 });
  await page.waitForTimeout(150);
  await page.keyboard.press('Enter');
  await page.waitForFunction(b => window.__lastReply !== b, before, { timeout: 60000 });
  await page.waitForTimeout(hold);
}
await stop('out/wa_demo.mp4');
await browser.close();
