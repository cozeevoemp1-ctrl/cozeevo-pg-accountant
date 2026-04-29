
# BRAIN.md — PG Accountant Architecture Reference

> Read this file at the start of every session. It is the ground truth for the system.
> Consolidated from ARCHITECTURE.md + SYSTEM_ARCHITECTURE.md on 2026-03-30.
> For detailed DB schema, see DATA_MODEL.md.
> For detailed floor-by-floor room layouts, see MASTER_DATA.md.
> Last updated: 2026-03-30

---

## 1. System Overview

**Product:** Cozeevo PG Accountant — AI-powered bookkeeping + WhatsApp bot + Owner PWA for a PG business.
**Stack:** Python 3.11 · FastAPI · Next.js 15 · Supabase (PostgreSQL + Auth) · Groq llama-3.3-70b-versatile · APScheduler · Meta WhatsApp Cloud API

> **Note on LangGraph:** `src/agents/langgraph_router.py` exists (v1.0 artifact) but is NOT wired into the WhatsApp flow.
> The Gatekeeper+Worker architecture + PendingAction state machine replaces it. LangGraph is not needed here —
> our business logic is deterministic rules, not multi-step AI reasoning chains.

**Future goal:** Multi-tenant SaaS — same codebase, each PG gets its own Supabase project + WhatsApp number.

**Current phase:** **LIVE on VPS** — Hostinger KVM 1 (187.127.130.194).
- **api.getkozzy.com** — FastAPI (port 8000), WhatsApp bot + REST API
- **app.getkozzy.com** — Next.js PWA (port 3001, `kozzy-pwa.service`), Owner + staff mobile app

---

## 2. Architecture & Component Diagram

```
  WhatsApp User                Owner / Staff (browser)
       |                              |
       | Meta Cloud API               | HTTPS app.getkozzy.com
       v                              v
  +----------------------+    +-------------------------+
  | nginx (SSL)          |    | nginx (SSL)             |
  | api.getkozzy.com     |    | app.getkozzy.com        |
  +----------+-----------+    +-----------+-------------+
             | proxy_pass :8000           | proxy_pass :3001
             v                            v
  +--------------------------------------------------------+    +----------------------------+
  |  FastAPI (port 8000, pg-accountant.service)            |    | Next.js PWA (port 3001,    |
  |                                                        |    | kozzy-pwa.service)         |
  |  webhook_handler.py                                    |    |                            |
  |  +- GET /webhook/whatsapp  (Meta verification)         |    | Pages:                     |
  |  +- POST /webhook/whatsapp (receive messages)          |    | / Home (KPI tiles)         |
  |  +- Voice -> Groq Whisper transcription                |    | /payment/new               |
  |  +- Bank PDF -> parse + classify                       |    | /checkin/new               |
  |       |                                                |    | /checkout/new              |
  |       v                                                |    | /onboarding/new            |
  |  chat_api.py (main brain)                              |    | /tenants                   |
  |  +- 1. Rate limit + role_service.py                    |    | /reminders                 |
  |  +- 2. Load chat history (last 5 msgs)                 |    | /collection/breakdown      |
  |  +- 3. Check pending actions                           |    |                            |
  |  +- 4. intent_detector.py (regex, 97% accuracy)        |    | Auth: Supabase email+pwd   |
  |  +- 5. Follow-up detection (pronouns)                  |    | API:  /api/v2/app/* (JWT)  |
  |  +- 6. AI fallback (Groq) if UNKNOWN                   |    +----------------------------+
  |  +- 7. gatekeeper.py -> route to handler               |
  |       |                                                |
  |       +-- account_handler.py  (financial)               |
  |       +-- owner_handler.py    (operational)             |
  |       +-- tenant_handler.py   (disabled -> None)        |
  |       +-- lead_handler.py     (disabled -> None)        |
  |       +-- _shared.py          (fuzzy search, pending)   |
  |                                                        |
  |  Also:                                                 |
  |  +- /api/v2/app/* (JWT endpoints for PWA)              |
  |  +- gsheets.py           -> Google Sheets read/write    |
  |  +- finance_handler.py   -> bank statement processing   |
  |                                                        |
  +---------------+----------------------------------------+
                  |
                  v
  +----------------------------------------+
  | Supabase PostgreSQL (26 tables)        |
  | tenants, tenancies, payments,          |
  | rent_schedule, rooms, complaints,      |
  | chat_messages, activity_log, ...       |
  +----------------------------------------+
  | Supabase Auth                          |
  | user_metadata.role: admin/staff/tenant |
  +----------------------------------------+
```

**Note:** n8n was evaluated but not used. Meta webhooks go directly to FastAPI via nginx reverse proxy. n8n workflow file (`workflows/`) kept for reference only.

---

## 3. Request Lifecycle

### Phase 1: Reception
1. Meta sends POST to `/webhook/whatsapp`
2. `webhook_handler.py` verifies HMAC signature
3. Extract message from nested Meta JSON
4. Voice? -> Groq Whisper transcription
5. Bank PDF? -> save + parse in background

### Phase 2: Processing (chat_api.py)
6. **Rate limit** — 10/10min, 50/day per phone
7. **Role detection** — authorized_users -> tenants -> lead
8. **Load chat history** — last 5 messages for context
9. **Check pending actions** — disambiguation, clarification, confirmation
10. **Intent detection** — learned rules -> 50+ regex patterns -> AI fallback
11. **Follow-up detection** — pronoun patterns re-route to QUERY_TENANT
12. **Route** via gatekeeper -> correct handler

### Phase 3: Handling
13. Handler executes (DB read/write, calculations)
14. If ambiguous -> save pending action, ask user to clarify
15. If clear -> execute and return reply

### Phase 4: Response
16. Log to whatsapp_log + chat_messages
17. Send reply via Meta Graph API (background task)
18. Return 200 OK

---

## 4. Database Schema — 26 Tables (Supabase PostgreSQL)

> For complete column-level schema, ERD, enums, and constraints, see `docs/DATA_MODEL.md`.

### Layer 0 — Investment & Contacts (permanent)
`investment_expenses`, `pg_contacts`

### Layer 1 — Master Data (changes rarely, owner approval needed)

| Table | Key columns | Notes |
|-------|------------|-------|
| `properties` | id, name, address, total_rooms, wifi_floor_map (JSONB) | "Cozeevo THOR", "Cozeevo HULK". wifi_floor_map: `{"thor": {"G": [{ssid,password},...], "1": [...], ...}, "hulk": {...}}` — seeded via `src/database/seed_wifi.py` |
| `rooms` | id, property_id, room_number (TEXT), room_type, max_occupancy, is_charged, is_staff_room | room_number is TEXT. is_charged=False for owner-free rooms (G05, G06 THOR). is_staff_room skips room from tenant occupancy. |
| `rate_cards` | id, room_id, effective_from, effective_to (NULL=active), monthly_rent, daily_rate | Price history — new row when rent changes |
| `tenants` | id, name, phone (UNIQUE), gender, id_proof_type | phone = WhatsApp identity key |
| `staff` | id, property_id, room_id, name, phone, role, salary, date_of_birth, aadhar_number, kyc_document_url, kyc_verified, join_date, exit_date, active | Lokesh, Lakshmi etc. kyc_verified=False until Aadhar/ID photo uploaded to Supabase Storage `kyc-documents/staff/`. |
| `food_plans` | id, name, includes_lunch_box, monthly_cost | veg/non-veg/egg/none |
| `expense_categories` | id, name, parent_id | Electricity, Water, Salary, etc. |

### Layer 2 — Tenancy (the contract)

| Table | Key columns | Notes |
|-------|------------|-------|
| `tenancies` | id, tenant_id, room_id, stay_type (monthly/daily), status, checkin_date, checkout_date, agreed_rent, security_deposit, booking_amount | One row per tenant-room-period |

### Layer 3 — Transactions (money trail)

| Table | Key columns | Notes |
|-------|------------|-------|
| `rent_schedule` | id, tenancy_id, period_month (DATE, 1st of month), rent_due, status | "What's owed" — separate from payments |
| `payments` | id, tenancy_id, amount, payment_date, payment_mode (cash/upi/bank/cheque), for_type, period_month, is_void | "What's paid" — never delete, use is_void |
| `refunds` | id, tenancy_id, amount, refund_date, status (pending/processed/cancelled), reason, notes | Security deposit returns. Created automatically at RECORD_CHECKOUT. Finalised when staff says "process". |
| `expenses` | id, property_id, category_id, amount, expense_date, is_void | Operational costs |

### Layer 4 — Leads & Bot

| Table | Key columns | Notes |
|-------|------------|-------|
| `leads` | id, phone (UNIQUE), name, interested_in, converted | Unknown numbers enquiring about rooms |
| `rate_limit_log` | id, phone, window_start, message_count, day_count | Anti-spam — 10/10min, 50/day |
| `whatsapp_log` | id, direction, from_number, intent, linked_entity_id | Audit trail — never deleted |
| `conversation_memory` | id, phone, message_text, intent, embedding (pgvector) | Semantic memory — future AI learning |

### Layer 5 — Operational

| Table | Key columns | Notes |
|-------|------------|-------|
| `vacations` | id, tenancy_id, from_date, to_date, affects_billing | Tenant away periods |
| `reminders` | id, tenancy_id, reminder_type, remind_at, status | Rent due / checkout alerts |
| `onboarding_sessions` | id, tenant_id, tenancy_id, step, collected_data (JSON), expires_at, completed | Step-based KYC form. Steps: ask_dob -> ask_father_name -> ask_father_phone -> ask_address -> ask_email -> ask_occupation -> ask_gender -> ask_emergency_name -> ask_emergency_relationship -> ask_emergency_phone -> ask_id_type -> ask_id_number -> done. 48-hr TTL. |
| `checkout_records` | id, tenancy_id (UNIQUE), cupboard_key_returned, main_key_returned, damage_notes, other_comments, pending_dues_amount, deposit_refunded_amount, deposit_refund_date, actual_exit_date, recorded_by | Offboarding checklist — one row per tenancy |
| `pending_actions` | id, phone, action_type, context (JSON), expires_at | Multi-step flow state — 30min expiry |

### Layer 6 — Access Control

| Table | Key columns | Notes |
|-------|------------|-------|
| `authorized_users` | id, phone (UNIQUE), name, role, property_id, active | Dynamic role registry |

**Key design decisions:**
- `rent_schedule` != `payments` — enables "who hasn't paid March?" queries
- `room_number` as TEXT — handles "G15", "508/509", "G20"
- `rate_cards` separate — handles rent changes over time (Feb->May price changes in Excel)
- `is_void` on payments/expenses — never hard-delete financial records
- `payment_mode` column — replaces messy Cash/UPI split columns in old Excel

---

## 5. WhatsApp Bot — Role System

| Role | Identified by | Permissions |
|------|--------------|-------------|
| `admin` | Phone in `authorized_users` with role=admin | EVERYTHING — add/remove users, full CRUD |
| `power_user` | Phone in `authorized_users` with role=power_user | Full business access via WhatsApp — all tenants, payments, reports |
| `key_user` | Phone in `authorized_users` with role=key_user | Scoped — log payments + view assigned tenants only |
| `receptionist` | Phone in `authorized_users` with role=receptionist | Ops + finance (no reports) |
| `tenant` | Phone in `tenants` table | Read-only — own balance, payment history only |
| `lead` | Unknown phone (none of the above) | Room price enquiry + sales chat only |
| `blocked` | Rate-limit exceeded | Ignored, no reply |

**Seeded users:**
- Admin: +917845952289 (Kiran)
- Power user: +917358341775 (partner)

**Anti-spam:** 10 messages / 10-minute window, 50 messages / day — enforced for ALL callers including admin.

---

## 6. WhatsApp Intents

### Admin / Power User intents
| Intent | Trigger phrases |
|--------|----------------|
| START_ONBOARDING | "start onboarding for Ravi 9876543210", "begin kyc", "checkin for [name]" |
| RECORD_CHECKOUT | "record checkout", "offboard", "keys returned", "mark checkout complete" — 5-step form: keys -> damage -> dues -> deposit refund -> creates CheckoutRecord + Refund(pending) |
| CONFIRM_DEPOSIT_REFUND | Auto-created by 9am checkout alert. Reply: "process" (confirm refund), "deduct XXXX" (adjust maintenance), "deduct XXXX process" (adjust+confirm). Creates Refund(processed). |
| PAYMENT_LOG | "Raj paid 15000 upi", "received 12500 cash from room 201" |
| QUERY_DUES | "who hasn't paid", "pending rent", "dues list" |
| QUERY_TENANT | "Raj balance", "room 201 status" |
| ADD_TENANT | "add tenant", "new tenant" |
| CHECKOUT | "Raj checkout", "vacate room 201" |
| ADD_EXPENSE | "electricity 4500", "paid maintenance 2000" |
| REPORT | "monthly report", "march summary" |
| ADD_PARTNER | "add partner +91..." |
| REMINDER_SET | "remind Raj about rent" |
| HELP | "help", "commands" |

### Tenant intents (read-only)
| Intent | Trigger phrases |
|--------|----------------|
| MY_BALANCE | "my balance", "how much pending" |
| MY_PAYMENTS | "my payments", "payment history" |
| MY_DETAILS | "my details", "my room" |

### Lead intents (unknown numbers)
| Intent | Trigger phrases |
|--------|----------------|
| ROOM_PRICE | "price", "rent", "how much" |
| AVAILABILITY | "available", "vacancy" |
| ROOM_TYPE | "single", "double", "triple", "premium" |
| VISIT_REQUEST | "visit", "tour", "see the room" |
| GENERAL | anything else |

---

## 7. Intent Detection Pipeline

```
Message -> Learned Rules (JSON) -> Regex Patterns (50+) -> AI Fallback (Groq)
                                                              |
                                         +--------------------+
                                         |                    |
                                    confidence            UNKNOWN
                                    >= 0.70?                  |
                                    |   |                Save to
                                   Yes  No              pending_learning
                                    |   |
                                Route  SYSTEM_HARD_UNKNOWN
                                    |  "Could you rephrase?"
                                    v
                               gatekeeper.route()
```

**Accuracy:** 97% on 177-test evaluation suite. AI costs near zero.

---

## 8. Pending Actions State Machine

| State | Trigger | User Reply | Resolution |
|-------|---------|------------|------------|
| INTENT_AMBIGUOUS | 2+ regex matches | Pick number | Re-route chosen intent |
| AWAITING_CLARIFICATION | Missing month/name | Provide data | Merge + re-route |
| CONFIRM_PAYMENT_LOG | Payment details shown | Yes/No | Log or cancel |
| CONFIRM_ADD_EXPENSE | Expense shown | Yes/No | Log or cancel |
| Multi-step form | Onboarding/checkout | Answer each step | Progress through form |

- **Expiry:** 30 minutes
- **`__KEEP_PENDING__`:** Handler reply prefix = keep pending alive for next turn

---

## 9. Chat History & Follow-up Detection

**Storage:** `chat_messages` table — all inbound/outbound messages, never deleted.

**Context:** Last 5 messages loaded per request for AI context.

**Follow-up:** When intent=UNKNOWN and message contains pronouns ("how much", "his payments", "uska"):
1. Extract room/name from last bot response
2. Re-route as QUERY_TENANT with injected context
3. Example: "Raj balance" -> bot responds -> "his payments" -> auto-routes to Raj's payment history

---

## 10. Error Handling

| Scenario | Response |
|----------|----------|
| Rate limit exceeded | Silent (skip=True, no reply) |
| Low confidence (<0.70) | "Could you rephrase? Type *help* for options." |
| Handler exception | "Sorry, something went wrong. Please try again." |
| Voice transcription fails | "Couldn't understand voice note. Please type instead." |
| DB unreachable | App won't start (fails at lifespan init) |
| Groq API fails | Fall back to UNKNOWN, log error |
| Pending expired (>30min) | Treat as fresh message |

---

## 11. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /webhook/whatsapp | Meta Cloud API webhook verification |
| POST | /webhook/whatsapp | Meta Cloud API direct webhook |
| POST | /api/ingest/upload | Upload CSV/PDF for ingestion |
| POST | /api/ingest/scan | Scan data/raw/ for new files |
| POST | /api/reconcile | Run reconciliation |
| POST | /api/report/dashboard | Generate HTML dashboard |
| GET | /api/entities/pending | List pending master-data approvals |
| POST | /api/entities/{id}/approve | Approve pending entity |
| POST | /api/entities/{id}/reject | Reject pending entity |
| GET | /dashboard/{filename} | Serve HTML dashboard file |
| GET | /healthz | Health check |

---

## 12. Key Files

| File | Purpose |
|------|---------|
| `main.py` | App entry point, routers, middleware |
| `src/whatsapp/webhook_handler.py` | Meta webhook, media download, voice transcription |
| `src/whatsapp/chat_api.py` | Main pipeline — rate limit, role, intent, route, log |
| `src/whatsapp/role_service.py` | Role detection + rate limiting |
| `src/whatsapp/intent_detector.py` | 50+ regex patterns, entity extraction, AI fallback |
| `src/whatsapp/gatekeeper.py` | (role, intent) -> handler routing |
| `src/whatsapp/handlers/account_handler.py` | 13 financial intents |
| `src/whatsapp/handlers/owner_handler.py` | 28 operational intents |
| `src/whatsapp/handlers/tenant_handler.py` | Tenant self-service (disabled) |
| `src/whatsapp/handlers/lead_handler.py` | Sales conversation (disabled) |
| `src/whatsapp/handlers/_shared.py` | Fuzzy search, disambiguation, pending helpers |
| `src/integrations/gsheets.py` | Google Sheets read/write |
| `src/database/models.py` | 26 ORM table definitions |
| `src/database/db_manager.py` | DB Manager + CRUD |
| `src/database/seed.py` | Seed data (users, properties, food, categories) |
| `src/database/excel_import.py` | Excel import script |
| `src/database/migrate_all.py` | Master migration (idempotent, append only) |
| `src/scheduler.py` | 9 jobs — rent reminders (day-1, day+2), prep reminders (9am/2pm), nightly sheet audit, checkout deposit alerts |
| `src/llm_gateway/claude_client.py` | LLM client (Ollama/Groq/Anthropic) |
| `src/reports/reconciliation.py` | Reconciliation engine |
| `scripts/` | Diagnostic scripts (occupancy, empty rooms, payment breakdown, deposit check) |

### Worker Architecture

```
chat_api.py
    |
    v detect_intent()
    |
    v route() <- gatekeeper.py
    |
    +--- OWNER_ROLES + FINANCIAL_INTENTS --> AccountWorker (account_handler.py)
    |         PAYMENT_LOG, QUERY_DUES, QUERY_TENANT, ADD_EXPENSE,
    |         QUERY_EXPENSES, REPORT, RENT_CHANGE, RENT_DISCOUNT,
    |         VOID_PAYMENT, ADD_REFUND, QUERY_REFUNDS
    |
    +--- OWNER_ROLES + operational intents --> OwnerWorker (owner_handler.py)
    |         ADD_TENANT, START_ONBOARDING, CHECKOUT, NOTICE_GIVEN,
    |         RECORD_CHECKOUT, COMPLAINT_REGISTER, QUERY_ROOMS, etc.
    |
    +--- role=tenant --> TenantWorker (tenant_handler.py)
    |
    +--- role=lead/unknown --> LeadWorker (lead_handler.py)

Both AccountWorker and OwnerWorker share:
    _shared.py  -> fuzzy tenant search, disambiguation helpers
```

**Design rules:**
- Workers are unaware of each other
- `_shared.py` is pure DB helpers — no business logic, no HTTP calls
- `resolve_pending_action` stays in owner_handler (imported by chat_api) — no circular imports
- `_do_*` functions live in account_handler, imported back by owner_handler for pending action resolution

### Planned: LedgerWorker

```
ledger_handler.py (thin adapter) --> finance/ package
  (fully self-contained, zero imports from src/)
  extractors/ -> parsers/ -> matching/ -> categorization/ -> output/ -> config/
```

**`finance/` package has zero imports from `src/`** — fully standalone, callable from CLI or WhatsApp.

---

## 13. AI Usage Policy

| Task | Method | Cost |
|------|--------|------|
| Intent detection (97% of cases) | Regex rules in `intent_detector.py` | Free |
| Intent detection (ambiguous ~3%) | Groq llama-3.3-70b (cloud) | Low |
| Merchant categorization (known) | Rules | Free |
| Merchant categorization (unknown ~3%) | Ollama/Groq/Claude | Low/Free |
| Lead conversation (natural chat) | Ollama/Groq | Free/Low |
| Reporting, dedup, reconciliation | Python only | Free |

**LLM_PROVIDER=groq** (current production) — can switch to `ollama` (local, free) or `anthropic` (paid) in `.env`.
**No LangGraph** — Gatekeeper+Worker is the agent architecture. PendingAction is the state machine.

---

## 14. Runtime Stack

| Component | Technology | Port |
|-----------|-----------|------|
| API | FastAPI + Uvicorn | 8000 |
| DB | Supabase PostgreSQL (asyncpg) | cloud |
| LLM | Groq llama-3.3-70b-versatile | cloud |
| Reverse Proxy | nginx + Let's Encrypt SSL | 443 |
| WhatsApp | Meta Cloud API (free) | -- |
| Scheduler | APScheduler (4 jobs) | in-process |

---

## 15. Data Flow: File Ingestion

```
data/raw/file.csv
      |
      v
 Dispatcher --detect source--> PhonePeParser | PaytmParser | BankParser | CSVParser
      |
      v
 BaseParser.normalize()
      |
      v
 batch_deduplicate() -- SHA-256(date + amount + upi_ref) per row
      |
      v
 classify_batch() <-- Rules Engine (97%)
      | confidence < 0.70
      v
 Ollama classify_merchant() (~3%)
      |
      v
 upsert_transaction() -- skip duplicates via unique_hash
```

---

## 15b. Data Sync Policy — DB / Sheet / Dashboard

**Rule: DB is the single source of truth. All changes go through the bot.**

```
WhatsApp Bot (only entry point for changes)
    |
    v
Supabase DB  ──write-through──>  Google Sheet (read-only mirror)
    |                                    |
    v                                    v
Dashboard (reads DB)            Kiran views (read-only)
```

**Why not sync Sheet→DB?**
- Apps Script on-edit triggers fail silently (quota, auth expiry, no retry)
- Two-way sync creates merge conflicts (bot + manual edit at same time)
- No audit trail for manual Sheet edits

**How it works:**
1. Bot updates DB first (with audit_log entry + rent_revision if applicable)
2. Bot mirrors change to Sheet via `gsheets.update_tenant_field()`
3. Sheet is a read-only view — protect tabs via Google Sheets permissions
4. Dashboard reads from DB — always in sync after bot changes
5. If someone needs to change data, they message the bot

**What gets audited (audit_log table):**
- Every field change: who (phone), what (field, old→new), when, which room
- Rent changes also tracked in rent_revisions with effective dates
- Source: whatsapp / dashboard / system / import

**Planned rent increase at onboarding (2026-04-28):**
- Two nullable columns on `onboarding_sessions`: `future_rent`, `future_rent_after_months`
- Formula: `effective_date = 1st of (checkin_month + N)` — current month counts as month 1
- At approval: backend pre-inserts a `rent_revision` row; monthly rollover applies it automatically — no manual step
- Surfaces end-to-end: PWA form preview (month names), tenant HTML form (room card + agreement), WhatsApp messages (create + approval fallback)
- `future_rent=0` skips — revision is NOT inserted

**Premium bed rule (CRITICAL — do not change):**
- Premium sharing = 1 person books BOTH beds in a double room
- Premium tenant = 2 beds occupied, second bed CANNOT be sold
- Vacant beds = total_beds - regular_count - (premium_count * 2) - noshow_count - daywise_count
- Room-by-room: premium room = 0 free beds

**Day-wise tenants and the DAY WISE tab (CRITICAL — read before touching day-wise logic):**

Day-wise (short-stay) tenants use `stay_type=daily` and live in the **DAY WISE** sheet tab — NOT in any monthly tab (April 2026 etc.). This is a separate tab with its own column structure (`scripts/sync_daywise_from_db.py` defines `HEADERS`; `DAY_WISE_HEADERS` in `gsheets.py` is a subset used for new-row appends).

Key rules:
- `_find_tenant_tab()` searches ONLY monthly tabs — will always miss day-wise tenants
- Every mutation function that calls `_find_tenant_tab()` must fall back to DAY WISE (pattern: `_record_daywise_checkout_sync`)
- All API endpoints (checkin, payments, tenants PATCH) check `tenancy.stay_type == daily` and call `trigger_daywise_sheet_sync()` instead of `trigger_monthly_sheet_sync()`
- `trigger_daywise_sheet_sync()` fires `scripts/sync_daywise_from_db.py --write` in background — rebuilds entire DAY WISE tab from DB
- **Bot handlers** (owner_handler.py) still have this gap for void_payment, notes, rent change via WhatsApp — use `trigger_daywise_sheet_sync()` manually after any bot-initiated day-wise mutation

**Sheet protection (completely non-editable):**
- Sheet is view-only + filters. Nobody edits it — not even Kiran.
- Run `lockAllSheets()` from Apps Script menu (Cozeevo → Lock All Sheets)
- Only the bot's service account (`pg-accountant@pg-accountant-whatsapp.iam.gserviceaccount.com`) can write
- All humans: view + filter only. No editing, no manual overrides.
- If data is wrong, fix it via WhatsApp bot → DB updates → Sheet mirrors automatically

**If bulk correction is needed:**
- Use `scripts/clean_and_load.py` to re-import from Excel → Sheet → DB
- Never edit the Sheet directly

---

## 16. Deduplication

```
unique_hash = SHA-256(date + amount + upi_reference)    # if UPI ref available
           OR SHA-256(date + amount + merchant + source) # fallback
           OR SHA-256(date + amount + description[:40])  # last resort
```

---

## 17. Real Property Master Data

**Last verified:** 2026-03-23 by Kiran (owner confirmation)
**Two properties:** Cozeevo THOR + Cozeevo HULK (166 total rooms)
**PG business name:** Cozeevo Co-living. Platform brand: Kozzy / getkozzy.com. Bot name: Cozeevo Help Desk.

> For detailed floor-by-floor room layouts, see `docs/MASTER_DATA.md`.

### Staff Rooms (excluded from occupancy/revenue counts)

> **Live source of truth:** `rooms.is_staff_room = True` in DB. Run `show staff rooms` on bot for current state.
> Update this table and MASTER_DATA.md whenever a room is permanently added or removed as staff quarters.

| Room | Property | Beds | Notes |
|------|----------|------|-------|
| G05  | THOR | 3 | Staff quarters (permanent) |
| G06  | THOR | 2 | Staff quarters (permanent) |
| 107  | THOR | 2 | Staff quarters (permanent) |
| 108  | THOR | 2 | Staff quarters (permanent) |
| 701  | THOR | 1 | Staff quarters (permanent) |
| 702  | THOR | 1 | Staff quarters (permanent) |
| G12  | HULK | 3 | Staff quarters (permanent) |
| G20  | HULK | 1 | Staff quarters (temporary — until April 2026 end, returns to revenue May 2026) |

> Changed 2026-04-26: 114 + 618 moved staff→revenue (paying tenants). G20 temp staff until Apr end.

### Revenue Summary

| Property | Revenue Rooms | Single (1 bed) | Double (2 bed) | Triple (3 bed) | Total Beds |
|---|---|---|---|---|---|
| THOR | 78 | 14 | 61 | 3 | **145** |
| HULK | 80 | 13 | 65 | 2 | **149** |
| **Total** | **158** | **27** | **126** | **5** | **294** |

> 295 from May 2026 when G20 returns to revenue.

### Bed Count Formula
```
Total Revenue Beds = SUM(max_occupancy) for all non-staff rooms
                   = (single rooms x 1) + (double rooms x 2) + (triple rooms x 3)
                   = 27 + 252 + 15
                   = 294  (295 from May 2026)
```

---

## 18. Multi-PG / SaaS Path

Each PG customer gets:
- Own Supabase project (isolated DB)
- Own WhatsApp Business number
- Own `.env` config file
- Same codebase, config-driven

No shared state between instances.

---

## 19. Local Setup Checklist

- [x] Python dependencies installed (`pip install -r requirements.txt`)
- [x] `.env` configured (Supabase URL, ADMIN_PHONE, WHATSAPP_TOKEN)
- [x] Supabase tables created via `init_db()`
- [x] Seed data loaded (`src/database/seed.py`)
- [x] Excel data imported (`src/database/excel_import.py`)
- [x] WhatsApp webhook URL set in Meta Developer Console -> nginx -> FastAPI
- [x] End-to-end test: send WhatsApp message -> get reply
