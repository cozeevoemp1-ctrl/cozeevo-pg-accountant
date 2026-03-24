# Kozzy / PG Accountant — Claude Instructions

## What this project is
WhatsApp AI bot for PG (paying guest hostel) accounting + operations.
Bot name: **Artha**. Brand: **Kozzy** (getkozzy.com).
Stack: FastAPI + Supabase (PostgreSQL) + Groq (llama-3.3-70b) + Meta WhatsApp Cloud API.
Live on Hostinger VPS (187.127.130.194), domain api.getkozzy.com.

## Core rules
- **`docs/REPORTING.md` is the SINGLE SOURCE OF TRUTH for ALL financial logic** — refer to it before any financial report, calculation, or query. If you forget a formula, READ IT. Don't ask Kiran to re-explain.
- **Never hard-delete financial records** — use `is_void = True`
- **Regex handles 97% of intents** — no AI cost for common messages
- **AI (Groq) only for** ambiguous intents, lead chat, unknown merchant classification
- **Test locally before any VPS deploy**
- **`/ship` = git commit + push** — standing authorization, no confirmation needed

## Key commands
```bash
# Start API locally
venv/Scripts/python main.py          # Windows
source venv/bin/activate && python main.py  # Linux/VPS

# Run golden test suite (API must be running + TEST_MODE=1)
python tests/eval_golden.py
python tests/eval_golden.py --id G001         # single test
python tests/eval_golden.py --category correction_mid_flow  # by category

# DB migration (idempotent, safe to re-run)
python -m src.database.migrate_all

# VPS deploy
cd /opt/pg-accountant && git pull && systemctl restart pg-accountant
```

## Architecture — who does what
```
WhatsApp message
    → chat_api.py          (rate limiting, __KEEP_PENDING__ protocol)
    → role_service.py      (identify: admin/power_user/tenant/lead/blocked)
    → intent_detector.py   (regex rules → 97% of intents classified here)
    → gatekeeper.py        (routes by role+intent to correct worker)
        → account_handler.py   (financial: PAYMENT_LOG, REPORT, QUERY_DUES...)
        → owner_handler.py     (operational: CHECKOUT, ADD_TENANT, COMPLAINT...)
        → tenant_handler.py    (self-service: MY_BALANCE, MY_PAYMENTS...)
        → lead_handler.py      (sales: ROOM_PRICE, AVAILABILITY, VISIT_REQUEST...)
    → _shared.py           (fuzzy search helpers shared by all workers)
```

## Active files (touch these)
| File | Purpose |
|---|---|
| `src/whatsapp/intent_detector.py` | Add/fix regex intent patterns |
| `src/whatsapp/handlers/account_handler.py` | Financial intent handlers |
| `src/whatsapp/handlers/owner_handler.py` | Operational intent handlers |
| `src/whatsapp/handlers/tenant_handler.py` | Tenant self-service handlers |
| `src/whatsapp/handlers/lead_handler.py` | Lead/sales handlers |
| `src/whatsapp/handlers/_shared.py` | Shared fuzzy search helpers |
| `src/whatsapp/chat_api.py` | WhatsApp webhook + pending state |
| `src/database/models.py` | ORM models (21 tables) |
| `src/database/migrate_all.py` | Master idempotent migration |
| `tests/golden_test_cases.json` | 100 golden test cases |
| `tests/eval_golden.py` | Golden test runner |

## DO NOT touch
- `src/database/migrate_all.py` — only append, never remove existing migrations
- Live VPS DB — always test locally first
- Payment/expense records — use `is_void`, never delete

## DB schema (Supabase, 21 tables)
Key tables: `tenants`, `tenancies`, `rooms`, `rent_schedule`, `payments`, `expenses`,
`complaints`, `onboarding_sessions`, `checkout_records`, `wifi_networks`, `authorized_users`
Full schema: see `docs/BRAIN.md`

## Environment
```
LLM_PROVIDER=groq
GROQ_API_KEY=...
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
WHATSAPP_TOKEN=...
TEST_MODE=1   # enables /api/test/clear-pending endpoint
```

## Current status (as of 2026-03-16)
- Golden suite: 93/100 PASS (7 failing — see docs/TESTING.md for details)
- All local changes NOT yet pushed to VPS
- Regex accuracy: 99.4% on 177-test eval suite
- Target: fix 7 failing tests → reach 100/100 → then /ship to VPS

## VPS deploy checklist
```bash
# Local first
python tests/eval_golden.py   # must be 100/100
/ship                          # commit + push

# On VPS
cd /opt/pg-accountant && git pull
source venv/bin/activate
python -m src.database.migrate_all
systemctl restart pg-accountant
journalctl -u pg-accountant -f   # watch logs
```

## Preferences
- Short, direct responses — no fluff
- No emojis unless asked
- Show file:line references for code locations
- Local test before any cloud change
- Keep solutions simple — don't over-engineer
