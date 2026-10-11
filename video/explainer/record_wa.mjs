// Record the WhatsApp-style demo: real messages -> real sandbox bot (synthetic data).
// Prereq: sandbox DB reset + sandbox_server.py on :8100. Output: out/wa_demo.mp4
import { chromium } from 'playwright';
import fs from 'node:fs';
import { startCapture } from './capture.mjs';

// node record_wa.mjs [--phone]  -> out/wa_demo.mp4 (desktop) or out/wa_phone.mp4 (390x844 phone, 2x)
const PHONE_MODE = process.argv.includes('--phone');

const BOT = 'http://localhost:8100', PHONE = '917680814628'; // sandbox receptionist
// Takes: --take checkin (first cut) | quick (v3: queries + payment, needs --allow-finance) | three (30 s cut)
const TAKES = {
  checkin: [
    ['Arnav Kulkarni arrived', 1700],
    ['skip', 1200],
    ['yes', 1500],
    ['Pratik Rastogi paid 14000 cash', 1900],
  ],
  three: [
    ['any male beds available?', 1600],
    ['tap leaking in room 512', 1600],
    ['who is in room 314?', 1800],
  ],
  quick: [
    ['any male beds available?', 2200],
    ['how many beds free in HULK floor 2', 2200],
    ['Vinay Shetty paid 20000 upi', 1600],
    ['yes', 2200],
  ],
};
const TAKE = process.argv.includes('--take') ? process.argv[process.argv.indexOf('--take') + 1] : 'checkin';
const SCRIPT = TAKES[TAKE];

await fetch(BOT + '/api/test/clear-pending', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ phone: PHONE }) });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: PHONE_MODE ? { width: 780, height: 1688 } : { width: 1800, height: 1200 }, deviceScaleFactor: 1 });
await page.route('http://demo.local/wa.html*', r => r.fulfill({ body: fs.readFileSync('demo/wa.html'), contentType: 'text/html; charset=utf-8' }));
let n = 0;
await page.route('http://demo.local/bot', async r => {
  const { message } = JSON.parse(r.request().postData());
  const res = await fetch(BOT + '/api/whatsapp/process', { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ phone: PHONE, message, message_id: `video-${Date.now()}-${n++}` }) });
  const d = await res.json();
  console.log(`>>> ${message} [${d.intent}]\n${d.reply}\n`);
  await r.fulfill({ body: JSON.stringify(d), contentType: 'application/json' });
});
await page.goto('http://demo.local/wa.html' + (PHONE_MODE ? '?m=1&z=2' : '?z=1.5'));
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
await stop(PHONE_MODE ? (TAKE === 'checkin' ? 'out/wa_phone.mp4' : `out/wa_${TAKE}.mp4`) : 'out/wa_demo.mp4');
await browser.close();
