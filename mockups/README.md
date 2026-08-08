# Sales demo mockups

Self-contained, static HTML screenshots of the Kozzy app (Home, Finance, Bed Board)
with invented dummy data — for showing prospective PG-owner clients what the product
looks like, without touching the live app or real tenant data.

Each file is one interactive phone screen: tap the bottom tab bar to switch between
Home / Board / Finance, tap a KPI tile to expand its detail rows, tap a room on the
Bed Board to load it into the inspector. No backend, no network calls — everything
is hardcoded HTML/CSS/JS in a single file, fonts included (DM Sans, Geist, Geist Mono
are embedded as base64 so it renders correctly with zero external requests).

## Files

| File | Client |
|---|---|
| `kozzy.html` | Kozzy (Cozeevo) — pink `#EF1F9C` / coral `#E8365B` brand, current baseline |

## Reskinning for a new client

Duplicate `kozzy.html` as `<client-name>.html` and edit two small token blocks near
the top of the `<style>` — search for `BRAND TOKENS`:

1. **Home/Finance brand tokens** (5 values) — `--brand-pink`, `--brand-blue`,
   `--status-due`, `--tile-pink`, `--tile-pink-ink`. Set `--brand-pink` to the
   client's primary color, then derive the other four with the formulas noted next
   to each (tint ≈ 12% of the accent on white, ink ≈ darkened accent).
2. **Bed Board brand tokens** (3 values) — `--h-accent`, `--h-accent-dk`,
   `--h-accent-tint`. Same idea, same accent color, just the Host-kit variable names.

That's it for color. Everything else (paid/due/partial status colors, neutrals,
layout) is intentionally left alone — those are semantic, not brand.

Optional, only if the client needs it:
- **Dummy data** — names, room numbers, ₹ amounts are plain text/inline SVG in the
  HTML body, no data layer to touch. Search-and-replace the specific rows under
  `<!-- HOME -->`, `<!-- FINANCE -->`, `<!-- BED BOARD -->`.
- **Fonts** — swapping DM Sans/Geist for a different typeface means re-encoding a
  new `@font-face` data URI (see how `dmsans.ttf`/`geist.ttf` were embedded — download
  the variable TTF, `base64 -w0 file.ttf`, drop it into the matching `url(data:font/ttf;base64,...)`).
  Skip this unless the client's brand guidelines require a specific typeface.

## Viewing / sharing

Open the `.html` file directly in a browser (double-click, or `file://` path) — it's
fully self-contained.

**Live link (no third-party domain):** these files are also copied into
`web/public/mockups/` and served by the real Next.js app, so once deployed each one
is reachable at `https://app.getkozzy.com/mockups/<file>.html` — e.g.
`https://app.getkozzy.com/mockups/kozzy.html`. `web/middleware.ts` allowlists
`/mockups` so it's reachable **without login** (prospective clients don't have an
account). This folder (`/mockups`) is the source you edit; after reskinning for a
new client, copy the file into `web/public/mockups/` too before shipping, so the
live copy matches.
