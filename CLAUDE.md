# PG Accountant — Project Instructions

## What this is
WhatsApp bot for PG (paying guest) accounting + operations.
Brand: **Kozzy** (getkozzy.com). Bot name: **Cozeevo Help Desk**.
Stack: FastAPI + Supabase (PostgreSQL) + Groq (llama-3.3-70b) + Meta WhatsApp Cloud API.
Live on Hostinger VPS (187.127.130.194), domain api.getkozzy.com.
Architecture: Meta webhook → nginx → FastAPI (no n8n).

## Core rules
- **`docs/REPORTING.md`** — single source of truth for ALL financial logic
- **`docs/EXCEL_IMPORT.md`** — single source of truth for Excel → Sheet → DB workflow
- **`docs/SHEET_LOGIC.md`** — parsing rules for messy Excel cells
- **Never hard-delete financial records** — use `is_void = True`
- **Regex handles 97% of intents** — AI (Groq) only for ambiguous/lead/classification
- **Test locally before any VPS deploy**

## Dependency sync rule (CRITICAL)
**Every change must check and update ALL dependencies across the project.**
Before closing any feature, run through this checklist:
1. `scripts/clean_and_load.py` — Excel parser column mapping + Sheet writer (TENANTS + monthly tabs)
2. `src/database/excel_import.py` — DB import (uses read_history, must match parser)
3. `src/database/models.py` — DB schema (new columns, enums)
4. `src/database/migrate_all.py` — migrations (append only)
5. `scripts/import_april.py` — April monthly delta importer (DB + Sheet)
6. `scripts/import_daywise.py` — Day-wise short-stay importer (DB + Sheet)
7. `scripts/gsheet_apps_script.js` — Apps Script dashboard (reads monthly tabs)
6. `scripts/gsheet_dashboard_webapp.js` — Apps Script web dashboard
7. `src/whatsapp/intent_detector.py` — new intents registered
9. `src/whatsapp/handlers/owner_handler.py` — handler map + disambiguation
10. `src/integrations/gsheets.py` — Sheet write-back (payments, checkins, etc.)
11. `docs/` — BRAIN.md, BOT_FLOWS.md, cheat sheets, CHANGELOG
12. `.env` / `.env.example` — new config keys
13. `tests/` — golden suite if behavior changed

**If you touch a field, grep the entire project for it. Update every file that reads or writes it.**

## When `is_staff_room` changes on any room (CRITICAL)
Every staff room change must touch ALL of the following — no exceptions:
1. `UPDATE rooms SET is_staff_room=... WHERE room_number='...'` — DB first
2. `docs/MASTER_DATA.md` — staff table + revenue totals + building floor layout
3. `docs/BRAIN.md` — staff rooms section + revenue summary
4. `docs/BUSINESS_LOGIC.md`, `docs/REPORTING.md`, `docs/SHEET_LOGIC.md` — TOTAL_BEDS constant
5. `src/integrations/gsheets.py` — `TOTAL_BEDS`
6. `scripts/clean_and_load.py` — `TOTAL_BEDS`
7. `scripts/gsheet_apps_script.js` — `const TOTAL_BEDS`
8. `scripts/gsheet_dashboard_webapp.js` — `const TOTAL_BEDS`
9. `src/whatsapp/handlers/account_handler.py` — fallback TOTAL_BEDS
10. Re-run `scripts/sync_sheet_from_db.py --write` for current month
Bot command `show master data` gives the live DB snapshot — compare with MASTER_DATA.md before/after.

## Data sync rule (CRITICAL)
**DB is single source of truth. All changes go through the bot.**
- Bot writes DB first (with audit_log), then mirrors to Sheet via `gsheets.update_tenant_field()`
- Sheet is read-only mirror — never sync Sheet→DB
- Every field change must: update DB + update Sheet + write audit_log entry
- Rent changes also create rent_revisions entry with effective date
- See `docs/BRAIN.md` section 15b for full policy

## Key commands
```bash
# Local dev
venv/Scripts/python main.py                          # start API (Windows)
python tests/eval_golden.py                          # golden test suite (API must run + TEST_MODE=1)
python tests/eval_golden.py --id G001                # single test

# Excel import (see docs/EXCEL_IMPORT.md)
python scripts/clean_and_load.py                     # Excel → Google Sheet
python -m src.database.wipe_imported --confirm        # drop L1+L2 data
python -m src.database.excel_import --write           # Excel → DB

# DB migration
python -m src.database.migrate_all

# VPS deploy
cd /opt/pg-accountant && git pull && systemctl restart pg-accountant
```

## Architecture
```
WhatsApp message
    → chat_api.py          (rate limiting, __KEEP_PENDING__ protocol)
    → role_service.py      (admin/power_user/tenant/lead/blocked)
    → intent_detector.py   (regex → 97% classified here)
    → gatekeeper.py        (routes by role+intent)
        → account_handler.py   (financial: PAYMENT_LOG, REPORT, QUERY_DUES...)
        → owner_handler.py     (operational: CHECKOUT, ADD_TENANT, COMPLAINT...)
        → tenant_handler.py    (self-service: MY_BALANCE, MY_PAYMENTS...)
        → lead_handler.py      (sales: ROOM_PRICE, AVAILABILITY, VISIT_REQUEST...)
    → _shared.py           (fuzzy search helpers)
```

## Data flow
```
Kiran's Excel (offline)
    → scripts/clean_and_load.py     (THE parser — read_history())
        → Google Sheet (Cozeevo Operations v2)
        → src/database/excel_import.py → Supabase DB
    ONE parser. Never duplicate.
```

## Active files
| File | Purpose |
|---|---|
| `scripts/clean_and_load.py` | Excel parser + Sheet writer (read_history is THE parser) |
| `src/database/excel_import.py` | DB import (uses read_history, never duplicates) |
| `src/whatsapp/intent_detector.py` | Regex intent patterns |
| `src/whatsapp/handlers/account_handler.py` | Financial handlers |
| `src/whatsapp/handlers/owner_handler.py` | Operational handlers |
| `src/whatsapp/handlers/tenant_handler.py` | Tenant self-service |
| `src/whatsapp/handlers/lead_handler.py` | Lead/sales handlers |
| `src/whatsapp/handlers/_shared.py` | Shared fuzzy search |
| `src/whatsapp/handlers/update_handler.py` | Update + staff handlers (add_staff, assign/exit staff, query staff rooms) |
| `src/whatsapp/chat_api.py` | Webhook + pending state |
| `src/whatsapp/media_handler.py` | WhatsApp media download + Supabase KYC upload |
| `src/services/storage.py` | Supabase Storage wrapper (kyc-documents, agreements buckets) |
| `src/database/models.py` | ORM models |
| `src/database/migrate_all.py` | Master migration (append only, never remove) |

## DO NOT touch
- `src/database/migrate_all.py` — only append, never remove existing migrations
- Live VPS DB — always test locally first
- Payment/expense records — use `is_void`, never delete

## Docs index
| Doc | What it covers |
|---|---|
| `docs/BRAIN.md` | Master reference — architecture, schema overview, workers, intents, master data |
| `docs/DATA_MODEL.md` | Complete DB schema — 26 tables, ERD, enums, constraints |
| `docs/MASTER_DATA.md` | Detailed floor-by-floor room layouts, bed counts, staff rooms |
| `docs/REPORTING.md` | Financial formulas — P&L, dues, occupancy, proration |
| `docs/BUSINESS_LOGIC.md` | Calculation rules — occupancy, rent, expenses, billing |
| `docs/BOT_FLOWS.md` | Intent catalog, role flows, pending state machine |
| `docs/EXCEL_IMPORT.md` | Import workflow — Excel → Sheet → DB, single parser, migration strategy |
| `docs/SHEET_LOGIC.md` | Parsing rules — Chandra, exits, balance, messy cells |
| `docs/INTEGRATIONS.md` | External APIs — WhatsApp, Sheets, Supabase, Groq |
| `docs/RECEPTIONIST_CHEAT_SHEET.md` | Staff command reference |
| `docs/DEPLOYMENT.md` | VPS setup — nginx, systemd, SSL |
| `docs/TESTING.md` | Test SOP — golden suite, thresholds |
| `docs/CHANGELOG.md` | Session history |
| `docs/business/PRICING.md` | SaaS tiers, pricing strategy |
| `docs/planning/PRD.md` | Product requirements document |
| `docs/planning/ROADMAP.md` | Feature priorities, timeline |
| `docs/planning/FINANCIAL_VISION.md` | Reconciliation engine design (future) |

## Environment
```
LLM_PROVIDER=groq
GROQ_API_KEY=...
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
WHATSAPP_TOKEN=...
TEST_MODE=1   # enables /api/test/clear-pending endpoint
```

## Admins
- Kiran (+917845952289)
- Partner (+917358341775)
- Prabhakaran (9444296681)
- Lakshmi Mam

## End of day checklist (COMPULSORY — do this before closing EVERY session)
Before closing any session, complete ALL of these:
1. **CHANGELOG** — update `docs/CHANGELOG.md` with version entry of what was done
2. **Pending tasks** — update `memory/project_pending_tasks.md` with current state
3. **Memory** — save any new decisions, preferences, rules to memory files
4. **Affected docs** — update any docs that describe things that changed today
5. **CLAUDE.md** — if architecture, data flow, or active files changed, update this file
6. **Commit + push** — stage all changes, commit with clear message, push to GitHub
7. **VPS deploy** — if code is stable and tested: `git pull && systemctl restart pg-accountant`
8. **If NOT deploying** — note why in pending tasks (what needs testing/fixing first)

This is NOT optional. Every session ends with this checklist completed.

## Preferences
- Short, direct responses — no fluff
- No emojis unless asked
- Show file:line references for code
- Local test before any cloud change
- Keep solutions simple — don't over-engineer
