// Screenshot a page's canvas at 1920x1080: node shot.mjs <page.html> <out.png>
// Pages are served from this folder at http://video.local/ so clips load same-origin.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const [page_, out] = process.argv.slice(2);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mp4': 'video/mp4' };
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on('pageerror', e => { console.error('PAGE ERROR', e.message); process.exitCode = 1; });
page.on('console', m => m.type() === 'error' && console.error('CONSOLE', m.text()));
await page.route('http://video.local/**', r => {
  const f = decodeURIComponent(new URL(r.request().url()).pathname.slice(1));
  if (!fs.existsSync(f)) return r.fulfill({ status: 404 });
  r.fulfill({ body: fs.readFileSync(f), contentType: TYPES[path.extname(f)] || 'application/octet-stream' });
});
await page.goto('http://video.local/' + page_);
await page.waitForFunction(() => window.__done === true, null, { timeout: 30000 });
await page.locator('canvas').screenshot({ path: out });
await browser.close();
console.log('wrote', out);
