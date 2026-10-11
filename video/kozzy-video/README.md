# Explainer video (Remotion)

58 s portfolio explainer — "One system. Two front ends." Midnight look (near-black, brand
pink/blue glows, Geist + DM Sans from the app). Every demo is a **real recording on test
data**: the real PWA and the real bot code against the local sandbox DB — never production.

## Layout
- `src/timeline.json` — scene order + bars (120 BPM, 1 bar = 2 s). **Single source**: the video
  (`src/timeline.ts`) and the soundtrack (`scripts/music.mjs`) both read it.
- `src/scenes/` — one file per scene; `Demos.tsx` = the four recorded scenes (step labels carry
  clip timestamps found with ffmpeg scene detection).
- `src/components/PhoneDemo.tsx` — phone + headline + synced steps; `Phone.tsx`; `src/ui.tsx` theme.
- `public/` — fonts (tracked); `*.mp4` recordings + `music.wav` are gitignored, regenerate below.

## Regenerate media (repo root)
```bash
# 1. sandbox Postgres on :55432 (tests/sandbox/README.md), then demo data:
PG_BIN=... BASELINE=.../pgtest_testbase.dump bash tests/sandbox/reset_db.sh
PYTHONPATH=. venv/Scripts/python video/explainer/seed_demo.py      # Jul–Sep paid, Oct ~80%
#    snapshot it once (pg_dump -Fc) and use video/explainer/reset_demo.sh before each take
# 2. sandbox API (finance on, fake Sheets, accepts the PWA dev-login token) + real PWA:
bash video/explainer/start_demo_api.sh          # needs web/.env.development.local (see web/.env.local.example)
cd web && npm run dev                           # dev-login: http://localhost:3000/auth/dev-login
# 3. takes (order matters — later takes show earlier writes):
cd video/explainer && node record_app.mjs collect && node record_app.mjs vacant \
  && node record_wa.mjs --phone --take quick && node record_app.mjs recent
cp out/app_*.mp4 out/wa_quick.mp4 ../kozzy-video/public/
# 4. music + render
cd ../kozzy-video && node scripts/music.mjs && npx remotion render Explainer out/explainer.mp4
```
Review every render with a contact sheet before calling it done:
`ffmpeg -ss 1.6 -i out/explainer.mp4 -vf "fps=0.5,scale=480:-1,tile=6x5" -frames:v 1 out/sheet.png`
