# System Architecture — PG Accountant
> Last updated: 2026-03-14

## Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          PG ACCOUNTANT SYSTEM                                 │
│                                                                                │
│  INPUT                    PROCESSING                   OUTPUT                  │
│  ─────                    ──────────                   ──────                  │
│                                                                                │
│  WhatsApp Message ──────► FastAPI Brain ─────────────► WhatsApp Reply         │
│                               │                                                │
│  CSV / PDF / Excel ─────► File Dispatcher ──────────► Supabase (PostgreSQL)  │
│                               │                                                │
│                           Rules Engine (97%)         Reports                   │
│                           Ollama LLM   (~3%)         • Text Summary            │
│                           Approval Queue             • HTML Dashboard           │
│                                                                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: WhatsApp Message (Full Path)

```
WhatsApp User
      │
      ▼
Meta Cloud API (free — no Twilio)
      │ webhook POST
      ▼
n8n (Docker, port 5678) — thin pipe only
      │ POST /api/whatsapp/process
      ▼
FastAPI chat_api.py (port 8000)
      │
      ├── 0. !learn command intercept (admin only)
      │
      ├── 1. Rate limit check (10/10min, 50/day)
      │        └── blocked? → skip, no reply
      │
      ├── 2. get_caller_context() → role (admin/power_user/key_user/tenant/lead/blocked)
      │
      ├── 2a. Active OnboardingSession? → handle_onboarding_step() (tenant KYC)
      │
      ├── 2b. Active PendingAction? → resolve_pending_action() (multi-step flows)
      │
      ├── 3a. detect_intent() — regex rules (97% coverage, free)
      │          └── confidence < 0.85 → Ollama llama3.2 (AI fallback, ~3%)
      │
      ├── 3b. Low-confidence gate → ask user to rephrase
      │
      ▼
 gatekeeper.route()
      │
      ├── OWNER_ROLES + FINANCIAL_INTENTS ──► AccountWorker (account_handler.py)
      │        PAYMENT_LOG, QUERY_DUES, QUERY_TENANT, ADD_EXPENSE, QUERY_EXPENSES,
      │        REPORT, RENT_CHANGE, RENT_DISCOUNT, VOID_PAYMENT, ADD_REFUND, QUERY_REFUNDS
      │
      ├── OWNER_ROLES + operational intents ──► OwnerWorker (owner_handler.py)
      │        ADD_TENANT, START_ONBOARDING, UPDATE_CHECKIN, CHECKOUT, SCHEDULE_CHECKOUT,
      │        NOTICE_GIVEN, RECORD_CHECKOUT, LOG_VACATION, COMPLAINT_REGISTER,
      │        QUERY_VACANT_ROOMS, QUERY_OCCUPANCY, QUERY_EXPIRING, QUERY_CHECKINS,
      │        QUERY_CHECKOUTS, ROOM_STATUS, REMINDER_SET, SEND_REMINDER_ALL,
      │        ADD_PARTNER, RULES, HELP
      │
      ├── role=tenant ──────────────────────► TenantWorker (tenant_handler.py)
      │        MY_BALANCE, MY_PAYMENTS, MY_DETAILS, COMPLAINT_REGISTER, RULES
      │
      └── role=lead/unknown ────────────────► LeadWorker (lead_handler.py)
               ROOM_PRICE, AVAILABILITY, ROOM_TYPE, VISIT_REQUEST, GENERAL
      │
      ▼
      4. Log to whatsapp_log + session.commit()
      │
      ▼
      5. Return reply → n8n → Meta Cloud API → WhatsApp User
```

---

## Worker Architecture (Gatekeeper Pattern)

```
                    ┌─────────────────────────────┐
                    │       gatekeeper.py          │
                    │  The only file that knows    │
                    │  which worker handles what   │
                    └──────────────┬──────────────┘
                                   │
          ┌────────────────────────┼──────────────────────┐
          │                        │                       │
          ▼                        ▼                       ▼
 AccountWorker              OwnerWorker             TenantWorker / LeadWorker
 account_handler.py         owner_handler.py        tenant_handler.py
 (financial intents)        (operational intents)   lead_handler.py
          │                        │
          └──────────┬─────────────┘
                     ▼
               _shared.py
         (fuzzy search, disambiguation,
          pending action helpers)
```

**Design rules:**
- Workers are unaware of each other
- `_shared.py` is pure DB helpers — no business logic, no HTTP calls
- `resolve_pending_action` stays in owner_handler (imported by chat_api) — no circular imports
- `_do_*` functions live in account_handler, imported back by owner_handler for pending action resolution

---

## Database Design (21 Tables)

```
L0 — Investment & Contacts (permanent)
     investment_expenses   pg_contacts

L1 — Master Data (changes rarely)
     properties   rooms   rate_cards   tenants   staff   food_plans   expense_categories

L2 — Tenancy (the contract)
     tenancies

L3 — Transactions (money trail — never delete, use is_void)
     rent_schedule   payments   refunds   expenses

L4 — Leads & Bot
     leads   rate_limit_log   whatsapp_log   conversation_memory

L5 — Operational (multi-step flows)
     vacations   reminders   onboarding_sessions   checkout_records
     pending_actions

L6 — Access Control
     authorized_users
```

**Key design decisions:**
- `rent_schedule` ≠ `payments` — enables "who hasn't paid March?" queries
- `room_number` as TEXT — handles "G15", "508/509", "G20"
- `rate_cards` separate — handles rent changes over time
- `is_void` on payments/expenses — never hard-delete financial records
- `payment_mode` column — cash/upi/bank/cheque

---

## Data Flow: File Ingestion

```
data/raw/file.csv
      │
      ▼
 Dispatcher ──detect source──► PhonePeParser | PaytmParser | BankParser | CSVParser
      │
      ▼
 BaseParser.normalize()
      │
      ▼
 batch_deduplicate() — SHA-256(date + amount + upi_ref) per row
      │
      ▼
 classify_batch() ◄── Rules Engine (97%)
      │ confidence < 0.70
      ▼
 Ollama classify_merchant() (~3%)
      │
      ▼
 upsert_transaction() — skip duplicates via unique_hash
```

---

## AI Usage Policy

| Task | Method | Cost |
|------|--------|------|
| Intent detection (97% of cases) | Regex rules | Free |
| Intent detection (ambiguous ~3%) | Ollama local llama3.2 | Free |
| Merchant categorization (unknown) | Ollama/Groq | Free/Low |
| Lead conversation (natural chat) | Ollama/Groq | Free/Low |
| Reporting, dedup, reconciliation | Python only | Free |

**LLM_PROVIDER=ollama** (default) — switch to `groq` or `anthropic` in `.env`.

---

## n8n Integration (WA-01-whatsapp-router.json)

```
Meta Cloud API webhook
       │
       ▼
  n8n: WhatsApp Trigger → Extract Message → Is Text? → Call FastAPI → Should Reply? → Send Reply
       │ POST /api/whatsapp/process
       │ Body: { phone, message, message_id }
       │ n8n Variable: FASTAPI_URL = http://host.docker.internal:8000
       ▼
  FastAPI returns: { reply, intent, role, confidence, skip }
```

---

## Multi-PG / SaaS Path

Each PG customer gets:
- Own Supabase project (isolated DB)
- Own WhatsApp Business number
- Own `.env` config file
- Same codebase, config-driven

No shared state between instances.

---

## Runtime Stack

| Component | Technology | Port |
|-----------|-----------|------|
| API | FastAPI + Uvicorn | 8000 |
| DB | Supabase PostgreSQL (asyncpg) | cloud |
| LLM | Ollama llama3.2 | 11434 |
| Automation | n8n (Docker) | 5678 |
| WhatsApp | Meta Cloud API (free) | — |
