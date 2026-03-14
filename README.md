# Cozeevo PG Accountant

> AI-powered WhatsApp bot + bookkeeping system for PG (Paying Guest) businesses.
> Version 1.4.0 — Gatekeeper + Worker Architecture

---

## What is this?

Cozeevo PG Accountant lets a PG owner manage their entire business through WhatsApp:

- **Log payments** — "Raj paid 15000 upi" → instantly recorded
- **Check dues** — "who hasn't paid March?" → list of defaulters
- **Tenant details** — "show Arjun's account" → full balance breakdown
- **Add expenses** — "maintenance 5000 cash" → logged under correct category
- **Monthly report** — revenue, occupancy, outstanding dues
- **Tenant onboarding** — 12-step KYC form over WhatsApp (no paperwork)
- **Tenant checkout** — 5-step checklist: keys, damage, dues, deposit refund
- **Room enquiry bot** — leads get pricing, availability, and can book visits
- **Tenant self-service** — tenants check their own balance, payments, and raise complaints

Everything runs on **free/low-cost infrastructure** — no per-message fees, no Twilio.

---

## Stack

| Component | Technology |
|-----------|-----------|
| API | FastAPI (Python 3.11) on port 8000 |
| Database | Supabase PostgreSQL (cloud) |
| WhatsApp | Meta Cloud API (free) |
| Automation | n8n (Docker, port 5678) — thin webhook pipe only |
| AI / LLM | Ollama llama3.2 (local, free) |
| Intent Detection | Regex rules (97% free) + Ollama fallback (~3%) |

---

## 6-Tier Role System

Every caller is automatically identified by their phone number:

| Role | How identified | What they can do |
|------|---------------|-----------------|
| `admin` | `authorized_users` table, role=admin | Everything — add users, full CRUD |
| `power_user` | `authorized_users` table, role=power_user | Full business access |
| `key_user` | `authorized_users` table, role=key_user | Log payments + view assigned tenants |
| `tenant` | Phone in `tenants` table | Read-only: balance, payments, complaints |
| `lead` | Unknown phone number | Room enquiry + pricing + visit booking |
| `blocked` | Rate limit exceeded (10/10min, 50/day) | No reply — silently ignored |

---

## Worker Architecture (Gatekeeper Pattern)

```
WhatsApp Message
      │
      ▼
FastAPI chat_api.py
      │ detect_intent() — 97% regex rules
      ▼
gatekeeper.route(role, intent)
      │
      ├── admin/power_user/key_user + financial intent ──► AccountWorker
      │      PAYMENT_LOG, QUERY_DUES, QUERY_TENANT, ADD_EXPENSE,
      │      QUERY_EXPENSES, REPORT, RENT_CHANGE, RENT_DISCOUNT,
      │      VOID_PAYMENT, ADD_REFUND, QUERY_REFUNDS
      │
      ├── admin/power_user/key_user + operational intent ──► OwnerWorker
      │      ADD_TENANT, START_ONBOARDING, CHECKOUT, RECORD_CHECKOUT,
      │      QUERY_OCCUPANCY, QUERY_VACANT_ROOMS, REMINDER_SET, etc.
      │
      ├── tenant ──────────────────────────────────────────► TenantWorker
      │      MY_BALANCE, MY_PAYMENTS, MY_DETAILS, COMPLAINT_REGISTER
      │
      └── lead / unknown ──────────────────────────────────► LeadWorker
             ROOM_PRICE, AVAILABILITY, VISIT_REQUEST, GENERAL
```

See [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) for the full data flow diagram.

---

## Accounting & P&L Tools

Standalone Python scripts for bookkeeping from bank statements — no WhatsApp required.

| Script | Run | Output |
|--------|-----|--------|
| Extract PDF → Excel | `python scripts/bank_statement_extractor.py` | `*_extracted.xlsx` |
| Monthly P&L report | `python scripts/pnl_report.py` | `PnL_Report.xlsx` |
| Review unclassified | `python scripts/check_others.py` | Console list |

**How it works:**
1. Export YES Bank statement as PDF → run `bank_statement_extractor.py` → get clean Excel
2. Run `pnl_report.py` → get month-by-month P&L with 15 expense categories
3. Run `check_others.py` to see any unclassified transactions and reclassify them

**Classification rules** live in `scripts/pnl_report.py` → `EXPENSE_RULES` (keyword-based, ordered, first match wins). Add new rules there — no code changes needed anywhere else.

> **Roadmap:** These scripts will evolve into the `finance/` reconciliation engine — a standalone Python package that handles multi-source UPI + bank statement deduplication and feeds a FinancialWorker on the WhatsApp bot. See [FINANCIAL_VISION.md](FINANCIAL_VISION.md).

---

## Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed locally (`ollama pull llama3.2`)
- Docker Desktop (for n8n)
- Supabase account (free tier works)
- Meta WhatsApp Business account (free — [developers.facebook.com](https://developers.facebook.com))

### 1. Clone and install

```bash
git clone https://github.com/cozeevoemp1-ctrl/cozeevo-pg-accountant.git
cd cozeevo-pg-accountant
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure `.env`

```env
# Supabase
DATABASE_URL=postgresql+asyncpg://postgres:[password]@db.[ref].supabase.co:5432/postgres
SUPABASE_URL=https://[ref].supabase.co
SUPABASE_KEY=your-anon-key

# Meta WhatsApp Cloud API
META_WHATSAPP_TOKEN=your-access-token
PHONE_NUMBER_ID=your-phone-number-id
VERIFY_TOKEN=pg-accountant-verify

# LLM (local Ollama — free)
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

### 3. Run the database migrations

```bash
python src/database/migrate_all.py
```

### 4. Start the API

```bash
# Windows
START_API.bat

# Or directly
uvicorn main:app --reload --port 8000
```

Test: `http://localhost:8000/healthz` → `{"status":"ok"}`

### 5. Start n8n and connect WhatsApp

See [QUICKSTART.md](QUICKSTART.md) for the full local setup guide (Docker, ngrok, Meta webhook config).

---

## WhatsApp Commands

### Admin / Power User

```
# Payments
Raj paid 15000 upi             → log payment
void payment 42                → void a transaction

# Dues & Reports
who hasn't paid                → defaulters this month
Raj balance                    → tenant account details
monthly report                 → full monthly summary
expenses this month            → expense breakdown

# Rent
change rent for room 205 to 12000   → rent change from next month
give Raj 500 discount               → one-time discount

# Tenant management
add tenant Arjun 9876543210 room 204  → add new tenant
start onboarding for Arjun 9876543210 → begin 12-step KYC
record checkout Arjun                  → begin checkout checklist
who is checking out this month         → upcoming checkouts

# Operations
vacant rooms                   → empty rooms
occupancy                      → current occupancy %
rules                          → show PG house rules
help                           → full command list
```

### Tenant

```
my balance                     → pending rent + dues
my payments                    → last 6 payments
my details                     → room number, check-in date
water problem                  → raise plumbing complaint
rules                          → PG house rules
```

### Lead (unknown number)

```
price / rent                   → room pricing
available rooms                → what's available
single room                    → single room details
visit / tour                   → book a visit
```

---

## Database (21 Tables)

```
L0 — Permanent:    investment_expenses   pg_contacts
L1 — Master:       properties  rooms  rate_cards  tenants  staff  food_plans  expense_categories
L2 — Tenancy:      tenancies
L3 — Transactions: rent_schedule  payments  refunds  expenses
L4 — Bot:          leads  rate_limit_log  whatsapp_log  conversation_memory
L5 — Operational:  vacations  reminders  onboarding_sessions  checkout_records  pending_actions
L6 — Access:       authorized_users
```

Key design principles:
- `rent_schedule` ≠ `payments` — enables "who hasn't paid?" queries
- `is_void` flag on payments/expenses — never hard-delete financial records
- SHA-256 deduplication on all imports
- `room_number` as TEXT — handles "G15", "508/509", double rooms

---

## Multi-PG / SaaS

Each PG customer gets their own isolated instance:
- Own Supabase project (isolated DB)
- Own WhatsApp Business number
- Own `.env` config
- Same codebase — config-driven

No shared state between instances.

---

## Cloud Deployment

Target: Hostinger VPS KVM 1 (~$5/month, Ubuntu 22.04)
- FastAPI runs as a systemd service
- n8n runs in Docker
- Supabase stays as cloud DB (no migration needed)
- SSL via nginx + certbot

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full cloud setup guide.

---

## Project Structure

```
├── src/
│   ├── database/
│   │   ├── models.py              # 21-table SQLAlchemy ORM
│   │   ├── db_manager.py          # CRUD operations
│   │   ├── seed.py                # Initial master data
│   │   └── migrate_all.py         # Idempotent migration script
│   ├── whatsapp/
│   │   ├── chat_api.py            # FastAPI endpoint — main entry point
│   │   ├── role_service.py        # 6-tier role detection + phone normalize
│   │   ├── intent_detector.py     # Rules-based intent detection (97% free)
│   │   ├── gatekeeper.py          # Smart router: (role, intent) → worker
│   │   └── handlers/
│   │       ├── account_handler.py # AccountWorker — 11 financial intents
│   │       ├── owner_handler.py   # OwnerWorker — operational intents
│   │       ├── tenant_handler.py  # TenantWorker + 12-step KYC onboarding
│   │       ├── lead_handler.py    # LeadWorker — room enquiry bot
│   │       └── _shared.py         # Shared fuzzy-search helpers
│   ├── services/
│   │   └── property_logic.py      # All financial math (dues, prorate, balance)
│   └── llm_gateway/
│       └── claude_client.py       # LLM client (Ollama/Groq/Anthropic)
├── workflows/
│   └── WA-01-whatsapp-router.json # n8n workflow — import this
├── main.py                        # App entry point
├── START_API.bat                  # Windows quick-start
├── docker-compose.yml             # n8n container
├── BRAIN.md                       # Full architecture reference
├── QUICKSTART.md                  # Local setup guide
└── DEPLOYMENT.md                  # Cloud deployment guide
```

---

## Documentation

| File | Purpose |
|------|---------|
| [BRAIN.md](BRAIN.md) | Complete architecture reference — read first |
| [QUICKSTART.md](QUICKSTART.md) | Local setup (Docker, n8n, WhatsApp) |
| [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | Data flow diagrams |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Cloud deployment (Hostinger VPS) |
| [DATA_STRATEGY.md](DATA_STRATEGY.md) | DB load strategy, dedup guarantees |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

---

## License

Private — Cozeevo. All rights reserved.
