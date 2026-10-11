// Open the real PWA (local dev, sandbox data) via dev-login; screenshot a path + report API failures.
// node pwa_peek.mjs <path> <out.png>
import { chromium } from 'playwright';
const [path = '/', out = 'out/pwa_peek.png'] = process.argv.slice(2);
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2 });
const bad = [];
p.on('response', r => { if (r.url().includes(':8100') && r.status() >= 400) bad.push(`${r.status()} ${r.url()}`); });
p.on('pageerror', e => bad.push('pageerror ' + e.message));
await p.goto('http://localhost:3000/auth/dev-login');
await p.goto('http://localhost:3000' + path, { waitUntil: 'networkidle', timeout: 120000 });
await p.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
await p.waitForTimeout(1500);
await p.screenshot({ path: out });
console.log('url', p.url()); console.log(bad.slice(0, 10).join('\n') || 'no API errors');
await b.close();
