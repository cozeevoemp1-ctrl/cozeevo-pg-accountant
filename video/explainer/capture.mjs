// Screen-record a Playwright page via Chrome's screencast (lossless-ish JPEG frames with
// real timestamps) and assemble a constant-30fps, all-intra MP4 (fast exact seeking).
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

export async function startCapture(page, dir) {
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const cdp = await page.context().newCDPSession(page);
  const frames = [];
  cdp.on('Page.screencastFrame', async f => {
    const file = path.join(dir, `f${String(frames.length).padStart(5, '0')}.jpg`);
    fs.writeFileSync(file, Buffer.from(f.data, 'base64'));
    frames.push({ file, ts: f.metadata.timestamp });
    await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 95, everyNthFrame: 1, maxWidth: 4000, maxHeight: 4000 });
  const t0 = Date.now() / 1000;
  return async function stop(outMp4, { crop } = {}) {
    const tEnd = Date.now() / 1000;
    await cdp.send('Page.stopScreencast');
    let list = 'ffconcat version 1.0\n';
    frames.forEach((f, i) => {
      const next = i + 1 < frames.length ? frames[i + 1].ts : tEnd;
      list += `file '${path.basename(f.file)}'\nduration ${Math.max(0.001, next - f.ts).toFixed(4)}\n`;
    });
    list += `file '${path.basename(frames[frames.length - 1].file)}'\n`;
    fs.writeFileSync(path.join(dir, 'list.txt'), list);
    const vf = ['fps=30', crop ? `crop=${crop}` : null, 'scale=trunc(iw/2)*2:trunc(ih/2)*2'].filter(Boolean).join(',');
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', path.join(dir, 'list.txt'),
      '-vf', vf, '-c:v', 'libx264', '-preset', 'slow', '-crf', '14', '-g', '1', '-pix_fmt', 'yuv420p', outMp4]);
    console.log(`captured ${frames.length} frames, ${(tEnd - frames[0].ts).toFixed(1)} s -> ${outMp4}`);
  };
}
