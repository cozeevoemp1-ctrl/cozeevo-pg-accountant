// Explore one PWA flow -> out/ex_*.png (throwaway helper)
import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 430, height: 932 } });
await p.goto('http://localhost:3000/auth/dev-login');
await p.goto('http://localhost:3000/onboarding/bookings', { waitUntil: 'networkidle' });
await p.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
const shot = async n => { await p.waitForTimeout(1500); await p.screenshot({ path: `out/ex_${n}.png` }); };
await shot('b1');
await p.getByRole('button', { name: /Check In/ }).first().click(); await shot('b2');
console.log((await p.evaluate(() => document.body.innerText)).replace(/\n+/g, ' | ').slice(0, 900));
await b.close();
