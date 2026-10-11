import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ locale: 'en-US' });
await p.goto('https://www.youtube.com/results?search_query=' + encodeURIComponent(process.argv[2]), { waitUntil: 'domcontentloaded' });
await p.waitForTimeout(4000);
const rows = await p.evaluate(() => [...document.querySelectorAll('ytd-video-renderer')].slice(0, 12).map(v =>
  `${v.querySelector('#video-title')?.textContent.trim()} | ${v.querySelector('#channel-name a, ytd-channel-name a')?.textContent.trim()} | ${v.querySelector('#metadata-line')?.innerText.replace(/\n/g,' ')} | ${v.querySelector('a#thumbnail')?.href}`));
console.log(rows.join('\n') || (await p.title()) + '\n' + (await p.content()).slice(0, 500));
await b.close();
