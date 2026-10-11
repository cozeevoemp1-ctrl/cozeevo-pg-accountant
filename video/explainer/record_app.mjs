// Record the REAL PWA (next dev on :3000, dev-login, sandbox API on :8100 with demo data).
// node record_app.mjs collect|vacant|recent   -> out/app_<take>.mp4 (phone screen, 2x)
import { chromium } from 'playwright';
import { startCapture } from './capture.mjs';

const TAKE = process.argv[2] || 'collect';
const Z = 2; // CSS zoom -> 2x capture of a 430x932 phone viewport
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 430 * Z, height: 932 * Z }, deviceScaleFactor: 1 });
await page.goto('http://localhost:3000/auth/dev-login');
await page.goto('http://localhost:3000/', { waitUntil: 'networkidle' });
const style = `html{zoom:${Z}} nextjs-portal{display:none!important}
  .tapdot{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;background:rgba(239,31,156,.35);
  border:2px solid rgba(239,31,156,.8);pointer-events:none;z-index:2147483647;animation:tap .5s ease-out forwards}
  @keyframes tap{from{transform:scale(.4);opacity:1}to{transform:scale(1.4);opacity:0}}`;
await page.addStyleTag({ content: style });
await page.waitForTimeout(1200);

async function tap(locator, pause = 900) {
  await locator.scrollIntoViewIfNeeded();
  const b = await locator.boundingBox();
  const x = b.x + b.width / 2, y = b.y + b.height / 2;
  await page.evaluate(([x, y, z]) => { const d = document.createElement('div'); d.className = 'tapdot';
    d.style.left = x / z + 'px'; d.style.top = y / z + 'px'; document.body.appendChild(d); setTimeout(() => d.remove(), 600); }, [x, y, Z]);
  await page.mouse.click(x, y);
  await page.waitForTimeout(pause);
}
const scrollTo = async (y, ms = 900) => { await page.evaluate(y => window.scrollTo({ top: y, behavior: 'smooth' }), y); await page.waitForTimeout(ms); };
const type = async (text) => { await page.keyboard.type(text, { delay: 110 }); await page.waitForTimeout(500); };

const stop = await startCapture(page, `out/app_${TAKE}_frames`);
await page.waitForTimeout(1000);

if (TAKE === 'collect') {
  await tap(page.getByText('Dues pending', { exact: false }).first(), 1100);
  await tap(page.getByPlaceholder('Name or room…').first(), 300);
  await type('Reyansh');
  await tap(page.getByText('Collect →').first(), 1000);
  await tap(page.locator('input').nth(2), 300);
  await type('16500');
  await tap(page.getByRole('button', { name: /^Collect ₹/ }), 3800); // KPIs refresh ~3 s
  await scrollTo(0, 1800);
} else if (TAKE === 'vacant') {
  await tap(page.getByText('Vacant beds', { exact: false }).first(), 1600);
  await tap(page.getByRole('button', { name: 'Male', exact: true }), 1600);
  await tap(page.getByRole('button', { name: 'Female', exact: true }), 1600);
} else if (TAKE === 'recent') {
  const sec = page.getByText('Recent payments', { exact: false }).first();
  await sec.scrollIntoViewIfNeeded();
  const y = await page.evaluate(() => window.scrollY);
  await scrollTo(0, 200);
  await scrollTo(y - 40, 1400);
  await page.waitForTimeout(1600);
}

await stop(`out/app_${TAKE}.mp4`);
await browser.close();
