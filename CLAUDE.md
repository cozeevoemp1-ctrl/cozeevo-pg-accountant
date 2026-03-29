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
| `src/whatsapp/chat_api.py` | Webhook + pending state |
| `src/database/models.py` | ORM models |
| `src/database/migrate_all.py` | Master migration (append only, never remove) |

## DO NOT touch
- `src/database/migrate_all.py` — only append, never remove existing migrations
- Live VPS DB — always test locally first
- Payment/expense records — use `is_void`, never delete

## Docs index
| Doc | What it covers |
|---|---|
| `docs/BRAIN.md` | Master reference — schema, roles, intents, runtime |
| `docs/REPORTING.md` | Financial formulas — P&L, dues, occupancy, proration |
| `docs/EXCEL_IMPORT.md` | Import workflow — Excel → Sheet → DB, single parser |
| `docs/SHEET_LOGIC.md` | Parsing rules — Chandra, exits, balance, messy cells |
| `docs/BUSINESS_LOGIC.md` | Calculation rules — occupancy, rent, expenses |
| `docs/BOT_FLOWS.md` | Intent catalog, role flows, pending state machine |
| `docs/TESTING.md` | Test SOP — golden suite, thresholds |
| `docs/RECEPTIONIST_CHEAT_SHEET.md` | Staff command reference |
| `docs/DEPLOYMENT.md` | VPS setup — nginx, systemd, SSL |

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

## Preferences
- Short, direct responses — no fluff
- No emojis unless asked
- Show file:line references for code
- Local test before any cloud change
- Keep solutions simple — don't over-engineer
