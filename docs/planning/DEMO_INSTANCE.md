# Demo Instance (v2 sales demo) — Design

**Date:** 2026-07-20 · **Status:** approved by Kiran (chat) · **Goal:** live demo link for a prospective PG-owner customer, ready in 2–3 days.

## Decisions (locked)

| Question | Decision |
|---|---|
| Format | Live link the lead explores himself (`demo.getkozzy.com`) |
| Bot | PWA only — no demo WhatsApp number (Meta friction). Real bot shown on Kiran's phone if asked |
| Data | Fresh Supabase project, 100% fictional data, our room layout reused (fastest, layout isn't personal) |
| Codebase | **Entirely separate folder + git repo for demo** (Kiran 2026-07-20), generated from the live repo by a sync script — never hand-edited |
| Sync | Every live change propagates: run `scripts/sync_demo_repo.ps1` after live commits → whitelist-copies code into the demo repo, commits, pushes; demo VPS pulls |
| Timeline | 2–3 days |

## Sync pipeline (live → demo, one direction only)

- Whitelist copy: `src/`, `web/` (minus node_modules/.next/test-results), `main.py`, `requirements.txt`, sanitized `.env.example`, `deploy/setup_demo_vps.sh`.
- NEVER copied: `docs/`, `data/`, `memory/`, one-off `scripts/_*.py`, `tests/` (real phone fixtures), Google Sheets scripts, anything on a blocklist.
- Sanitization is enforced by DEMO_MODE at runtime (not by patching code), so copies stay mechanical and repeatable.
- Sync script ends with a grep gate: refuses to commit the demo repo if any known real phone/name/credential pattern appears in the copied tree.

## Architecture

```
demo.getkozzy.com      → nginx → kozzy-pwa-demo.service (Next.js, port 3100)
api-demo.getkozzy.com  → nginx → pg-demo.service        (FastAPI, port 8100)
                                   ↓
                          Demo Supabase project (free tier, fresh DB)
```

- VPS: same Hostinger box, clone at `/opt/pg-demo`, own `.env`.
- No WhatsApp token in demo `.env`; `DEMO_MODE=1` hard-disables all outbound sends + Google Sheets writes anyway (belt and braces).
- Demo auth users created via `scripts/create_auth_users.py` against the demo Supabase (demo admin + demo staff).

## DEMO_MODE flag (leak prevention)

Fresh DB is not enough — real financials are hardcoded in code and would render in the demo UI:

| Leak | Guard |
|---|---|
| `src/reports/pnl_builder.py` frozen verified P&L (Oct'25–May'26 real figures) | demo serves dynamic-months-only P&L |
| `src/api/v2/analytics.py` `VERIFIED_MONTHS` frozen occupancy | demo computes live from DB |
| `src/services/unit_economics.py` `_TOTAL_INVESTMENT` ₹2.31Cr | moved to env `TOTAL_INVESTMENT` (prod default unchanged) |
| Outbound WhatsApp / Sheets writes | no-op at lowest-level send/write functions when `DEMO_MODE=1` |
| Hardcoded admin phones (if any in src/) | env/DB-driven |

Production with flag off = byte-identical behavior.

## Dummy dataset (`scripts/seed_demo_data.py`)

- Deterministic (seed 42), no new deps. Fictional Indian names, fake phone range.
- Rooms from `migrate_all` (our layout). ~92% occupancy, Mar–Jul 2026 history.
- Rent schedules + payments (85% paid / 10% partial / 5% unpaid), ~40 checkouts with refunds, active notices, pending bookings, day-stays, bank_transactions for Jun–Jul so dynamic P&L + Cash + Occupancy tabs all render, 2 fictional investors.
- Guard: refuses to run unless `DEMO_MODE=1` AND tenants table is empty AND `--confirm` passed.

## Repo cleanup (precondition, Kiran's requirement)

1. Leak audit (agent) — every phone/name/financial hardcoded in code, by severity.
2. Redundancy inventory (agent) — one-off scripts → `scripts/archive/`, stray root files, git-tracked data files. Delete list requires Kiran's approval; financial exports are never deleted, only kept local/untracked.

## Rollout steps

1. Land DEMO_MODE + seed script locally, review, commit.
2. Kiran: create demo Supabase project (free), paste DATABASE_URL + keys.
3. Local test: migrate → seed → run API+PWA with DEMO_MODE=1 → walk every page.
4. VPS: `deploy/setup_demo_vps.sh` (services, nginx), Cloudflare DNS for both subdomains, certbot.
5. Create demo auth users; final end-to-end pass on the live link.

## Out of scope (deliberate)

- Demo WhatsApp bot number, multi-tenancy/SaaS-ization, separate sanitized repo (only if code handover is ever agreed), billing/pricing pages.
