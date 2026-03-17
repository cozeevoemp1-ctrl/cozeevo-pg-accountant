
# BRAIN.md — PG Accountant Architecture Reference

> Read this file at the start of every session. It is the ground truth for the system.
> Last updated: 2026-03-15 (session 4)

---

## 1. System Overview

**Product:** Cozeevo PG Accountant — AI-powered bookkeeping + WhatsApp bot for a PG business.
**Stack:** Python 3.11 · FastAPI · Supabase (PostgreSQL) · Groq llama-3.3-70b-versatile · APScheduler · Meta WhatsApp Cloud API

> **Note on LangGraph:** `src/agents/langgraph_router.py` exists (v1.0 artifact) but is NOT wired into the WhatsApp flow.
> The Gatekeeper+Worker architecture + PendingAction state machine replaces it. LangGraph is not needed here —
> our business logic is deterministic rules, not multi-step AI reasoning chains.

**Future goal:** Multi-tenant SaaS — same codebase, each PG gets its own Supabase project + WhatsApp number.

**Current phase:** **LIVE on VPS** — Hostinger KVM 1 (187.127.130.194), domain api.getkozzy.com, SSL active, Meta webhook configured.

---

## 2. Architecture

```
WhatsApp User
      ↓
Meta Cloud API  (free — no Twilio)
      ↓  webhook POST
nginx (api.getkozzy.com, Let's Encrypt SSL)
      ↓  proxy_pass
FastAPI Brain (port 8000, systemd service) — all logic lives here
      ↓
Supabase (PostgreSQL)  — cloud DB, always on
```

**Note:** n8n was evaluated but skipped entirely. Meta webhooks go directly to FastAPI via nginx reverse proxy. n8n workflow file (`workflows/`) kept for reference only.

---

## 3. Database Schema — 21 Tables (Supabase PostgreSQL)

### Layer 1 — Master Data (changes rarely, owner approval needed)

| Table | Key columns | Notes |
|-------|------------|-------|
| `properties` | id, name, address, total_rooms, wifi_floor_map (JSONB) | "Cozeevo THOR", "Cozeevo HULK". wifi_floor_map: `{"thor": {"G": [{ssid,password},...], "1": [...], ...}, "hulk": {...}}` — seeded via `src/database/seed_wifi.py` |
| `rooms` | id, property_id, room_number (TEXT), room_type, max_occupancy, is_charged, is_staff_room | room_number is TEXT. is_charged=False for owner-free rooms (G05, G06 THOR). is_staff_room skips room from tenant occupancy. |
| `rate_cards` | id, room_id, effective_from, effective_to (NULL=active), monthly_rent, daily_rate | Price history — new row when rent changes |
| `tenants` | id, name, phone (UNIQUE), gender, id_proof_type | phone = WhatsApp identity key |
| `staff` | id, property_id, name, phone, role, active | Lokesh, Lakshmi, Kiran, Chandra etc. |
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
| `onboarding_sessions` | id, tenant_id, tenancy_id, step, collected_data (JSON), expires_at, completed | Step-based KYC form. Steps: ask_dob → ask_father_name → ask_father_phone → ask_address → ask_email → ask_occupation → ask_gender → ask_emergency_name → ask_emergency_relationship → ask_emergency_phone → ask_id_type → ask_id_number → done. 48-hr TTL. |
| `checkout_records` | id, tenancy_id (UNIQUE), cupboard_key_returned, main_key_returned, damage_notes, other_comments, pending_dues_amount, deposit_refunded_amount, deposit_refund_date, actual_exit_date, recorded_by | Offboarding checklist — one row per tenancy |

### Layer 6 — Access Control

| Table | Key columns | Notes |
|-------|------------|-------|
| `authorized_users` | id, phone (UNIQUE), name, role, property_id, active | Dynamic role registry |

**Key design decisions:**
- `rent_schedule` ≠ `payments` — enables "who hasn't paid March?" queries
- `room_number` as TEXT — handles "G15", "508/509", "G20"
- `rate_cards` separate — handles rent changes over time (Feb→May price changes in Excel)
- `is_void` on payments/expenses — never hard-delete financial records
- `payment_mode` column — replaces messy Cash/UPI split columns in old Excel

---

## 4. WhatsApp Bot — Role System (4 tiers)

| Role | Identified by | Permissions |
|------|--------------|-------------|
| `admin` | Phone in `authorized_users` with role=admin | EVERYTHING — add/remove users, full CRUD |
| `power_user` | Phone in `authorized_users` with role=power_user | Full business access via WhatsApp — all tenants, payments, reports |
| `key_user` | Phone in `authorized_users` with role=key_user | Scoped — log payments + view assigned tenants only |
| `tenant` | Phone in `tenants` table | Read-only — own balance, payment history only |
| `lead` | Unknown phone (none of the above) | Room price enquiry + sales chat only |
| `blocked` | Rate-limit exceeded | Ignored, no reply |

**Seeded users:**
- Admin: +917845952289 (Kiran)
- Power user: +917358341775 (partner)

**Anti-spam:** 10 messages / 10-minute window, 50 messages / day — enforced for ALL callers including admin.

---

## 5. WhatsApp Intents

### Admin / Power User intents
| Intent | Trigger phrases |
|--------|----------------|
| START_ONBOARDING | "start onboarding for Ravi 9876543210", "begin kyc", "checkin for [name]" |
| RECORD_CHECKOUT | "record checkout", "offboard", "keys returned", "mark checkout complete" — 5-step form: keys → damage → dues → deposit refund → creates CheckoutRecord + Refund(pending) |
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

## 6. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/whatsapp/process | Main WhatsApp brain — called by n8n |
| GET | /webhook/whatsapp | Meta Cloud API webhook verification |
| POST | /webhook/whatsapp | Meta Cloud API direct webhook (fallback) |
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

## 7. Key Files

| Purpose | File |
|---------|------|
| ORM Models (21 tables) | `src/database/models.py` |
| DB Manager + CRUD | `src/database/db_manager.py` |
| Seed data (users, properties, food, categories) | `src/database/seed.py` |
| Excel import script | `src/database/excel_import.py` |
| Master migration (idempotent) | `src/database/migrate_all.py` |
| Supabase RLS policies | `src/database/rls_policies.sql` |
| WhatsApp process endpoint | `src/whatsapp/chat_api.py` |
| Webhook handler (Meta verification) | `src/whatsapp/webhook_handler.py` |
| Role detection + rate limiting | `src/whatsapp/role_service.py` |
| Intent detection (rules-based) | `src/whatsapp/intent_detector.py` |
| **Gatekeeper router (role+intent → worker)** | **`src/whatsapp/gatekeeper.py`** |
| **AccountWorker — all financial intents** | **`src/whatsapp/handlers/account_handler.py`** |
| OwnerWorker — operational intents only | `src/whatsapp/handlers/owner_handler.py` |
| **Shared fuzzy-search helpers** | **`src/whatsapp/handlers/_shared.py`** |
| Tenant handlers + onboarding flow | `src/whatsapp/handlers/tenant_handler.py` |
| Lead conversation handlers | `src/whatsapp/handlers/lead_handler.py` |
| LangGraph router (NOT active — v1.0 artifact) | `src/agents/langgraph_router.py` |
| Business scheduler (5 jobs — rent reminders, recon, backup, checkout alerts) | `src/scheduler.py` |
| Diagnostic scripts (occupancy, empty rooms, payment breakdown, deposit check) | `scripts/` |
| LLM client (Ollama/Groq/Anthropic) | `src/llm_gateway/claude_client.py` |
| Reconciliation engine | `src/reports/reconciliation.py` |
| n8n workflow | `workflows/WA-01-whatsapp-router.json` |
| App entry point | `main.py` |

### Worker Architecture (2026-03-14)

```
chat_api.py
    │
    ▼ detect_intent()
    │
    ▼ route() ← gatekeeper.py
    │
    ├─── OWNER_ROLES + FINANCIAL_INTENTS ──► AccountWorker (account_handler.py)
    │         PAYMENT_LOG, QUERY_DUES, QUERY_TENANT, ADD_EXPENSE,
    │         QUERY_EXPENSES, REPORT, RENT_CHANGE, RENT_DISCOUNT,
    │         VOID_PAYMENT, ADD_REFUND, QUERY_REFUNDS
    │
    ├─── OWNER_ROLES + operational intents ──► OwnerWorker (owner_handler.py)
    │         ADD_TENANT, START_ONBOARDING, CHECKOUT, NOTICE_GIVEN,
    │         RECORD_CHECKOUT, COMPLAINT_REGISTER, QUERY_ROOMS, etc.
    │
    ├─── role=tenant ──────────────────────► TenantWorker (tenant_handler.py)
    │
    └─── role=lead/unknown ────────────────► LeadWorker (lead_handler.py)

Both AccountWorker and OwnerWorker share:
    _shared.py  → fuzzy tenant search, disambiguation helpers
```

**File sizes after refactor:**
| File | Lines |
|------|-------|
| `owner_handler.py` | ~1,434 (was 2,595) |
| `account_handler.py` | ~1,058 (new) |
| `_shared.py` | ~212 (new) |
| `gatekeeper.py` | ~46 (new) |
| `chat_api.py` | ~253 (was 259) |

---

## 8. AI Usage Policy

| Task | Method | Cost |
|------|--------|------|
| Intent detection (97% of cases) | Regex rules in `intent_detector.py` | Free |
| Intent detection (ambiguous) | Ollama local (llama3.2) | Free |
| Merchant categorization (known) | Rules | Free |
| Merchant categorization (unknown ~3%) | Ollama/Groq/Claude | Low/Free |
| Lead conversation (natural chat) | Ollama/Groq | Free/Low |
| Reporting, dedup, reconciliation | Python only | Free |

**LLM_PROVIDER=ollama** (default, local, free) — switch to `groq` (free cloud) or `anthropic` (paid) in `.env`.
**No LangGraph** — Gatekeeper+Worker is the agent architecture. PendingAction is the state machine.

---

## 9. n8n Workflow — WA-01-whatsapp-router.json

5 nodes (lean pipe):
1. **WhatsApp Trigger** — receives Meta Cloud API messages
2. **Extract Message** (Code node) — extracts phone, message, skip=true for non-text
3. **Is Text?** (IF) — drops media messages
4. **Call FastAPI Brain** (HTTP POST) → `{{ $vars.FASTAPI_URL }}/api/whatsapp/process`
   - Body: `{"phone": "+{{ phone }}", "message": "{{ message }}", "message_id": "{{ id }}"}`
   - Timeout: 15s
5. **Should Reply?** (IF) — checks `skip=false` and `reply` not empty
6. **Send Reply** (WhatsApp node) → sends `reply` text back to sender

**n8n Variable required:** `FASTAPI_URL` = `http://host.docker.internal:8000` (local) or VPS URL (cloud)

---

## 10. Deduplication

```
unique_hash = SHA-256(date + amount + upi_reference)    # if UPI ref available
           OR SHA-256(date + amount + merchant + source) # fallback
           OR SHA-256(date + amount + description[:40])  # last resort
```

---

## 11. Current Runtime Status (2026-03-14)

| Component | Status | Notes |
|-----------|--------|-------|
| Supabase DB | **Live** | 21 tables. Excel data: 234 tenants, 292 tenancies, 929 rent_schedule, 705 payments |
| FastAPI | **Needs restart** | Restart `START_API.bat` to pick up all 2026-03-14 changes |
| Ollama | **Running** | llama3.2 at http://localhost:11434 |
| APScheduler | **5 jobs** | rent_reminder_early, rent_reminder_late, daily_reconciliation, weekly_backup, checkout_deposit_alerts |
| n8n | **Not running** | Needs Docker Desktop installed |
| Docker | **Not installed** | Install from docker.com |
| WhatsApp Meta API | **Credentials configured** | Token + Phone ID in .env, webhook not yet pointed |

### Recently completed (2026-03-14 session 3)
- **Deposit tracking + checkout flow fixes:**
  - `rooms.is_charged` field: G05 and G06 (THOR) marked is_charged=False (owner-free rooms)
  - `rooms.is_staff_room` field: staff rooms excluded from tenant occupancy/vacancy counts
  - `refunds` table now actively used: `RECORD_CHECKOUT` creates `Refund(status=pending)` on completion
  - `CONFIRM_DEPOSIT_REFUND` intent: 9am daily scheduler job alerts staff on checkout day
  - Staff WhatsApp replies: `process` / `deduct XXXX` / `deduct XXXX process` finalise the refund
  - `resolve_pending_action` structural fix: RECORD_CHECKOUT text-reply steps (Q2–Q5) now correctly intercepted before numeric check
  - `scheduler.py`: 5th job `_checkout_deposit_alerts` — daily 9am, checks expected_checkout=today
  - Deposit query clarity: deposits split by payment_date (when received) vs for whom (by checkin_date) vs total held (active tenants)

- **Data verification scripts (`scripts/`):**
  - `occupancy_today.py` — current bed/room snapshot, breakdown by THOR/HULK
  - `empty_rooms.py` — floor-wise empty rooms + partial rooms, exports CSV
  - `payment_breakdown.py` — payments by mode (cash/UPI/bank/cheque) and for_type (rent/deposit/booking)
  - `deposit_check.py` — 4 views: received in month, by checkin date, total held, advance payments

### Completed (2026-03-14 session 2)
- **Gatekeeper + AccountWorker Architecture** refactor:
  - `gatekeeper.py` — smart router replacing flat if/elif chain in chat_api.py
  - `account_handler.py` — AccountWorker owning all 11 financial intents
  - `_shared.py` — 8 shared fuzzy-search/disambiguation helpers
  - `owner_handler.py` slimmed from 2,595 → 1,434 lines (operational only)
  - `chat_api.py` updated to use `route()` from gatekeeper

### Completed (2026-03-13 session 2)
- PG Rules & Regulations (19 rules) → RULES intent in both tenant + owner handlers
- Registration Form fields → 7 new Tenant columns + 12-step onboarding (DOB, father, address, email, occupation added)
- PAN Card added as ID proof option (+ Voter ID, Ration Card)
- Master migration script: `src/database/migrate_all.py` (idempotent, all scenarios)
- Data strategy guide: `DATA_STRATEGY.md`

---

## 12. Local Setup Checklist

- [x] Python dependencies installed (`pip install -r requirements.txt`)
- [x] `.env` configured (Supabase URL, ADMIN_PHONE, WHATSAPP_TOKEN)
- [x] Supabase tables created via `init_db()`
- [x] Seed data loaded (`src/database/seed.py`)
- [x] Excel data imported (`src/database/excel_import.py`)
- [ ] Docker Desktop installed (for n8n)
- [ ] n8n running: `docker-compose up -d`
- [ ] WA-01 workflow imported into n8n
- [ ] `FASTAPI_URL` variable set in n8n → `http://host.docker.internal:8000`
- [ ] WhatsApp webhook URL set in Meta Developer Console → n8n webhook URL
- [ ] End-to-end test: send WhatsApp message → get reply

---

## 13. Cloud Deployment Plan (after local testing)

**Target:** Hostinger VPS KVM 1 (~$5/month)
- Runs: FastAPI (systemd) + n8n (Docker)
- DB stays on Supabase (no migration needed)
- WhatsApp webhook → VPS public IP

**Future SaaS path:** Each PG gets their own:
- Supabase project (isolated DB)
- WhatsApp Business number
- `.env` config
- Same codebase, different config

---

## 14. Changelog

| Date | Change |
|------|--------|
| 2026-03-10 | Initial scaffolding — generic 8-table schema, Twilio, SQLite |
| 2026-03-10 | LLM switched from Anthropic to Ollama (rate limit issue) |
| 2026-03-10 | FastAPI verified working locally |
| 2026-03-12 | **Major rebuild**: 19-table schema from Excel analysis |
| 2026-03-12 | Database switched: SQLite → Supabase (PostgreSQL) |
| 2026-03-12 | WhatsApp switched: Twilio → Meta Cloud API (free) |
| 2026-03-12 | 4-tier role system: admin/power_user/key_user/tenant/lead/blocked |
| 2026-03-12 | Excel data imported: 234 tenants, 292 tenancies, 929 rent_schedule, 705 payments |
| 2026-03-12 | Docs overhauled: local-first approach, Hostinger cloud plan, SaaS future |
| 2026-03-13 | Phone normalization: `+91XXXXXXXXXX` → `XXXXXXXXXX` in `role_service._normalize()` |
| 2026-03-13 | Hot water / geyser / heater / shower added to plumbing complaint keywords |
| 2026-03-13 | Complaint raw message passthrough in `chat_api.py` (`entities["description"]`) |
| 2026-03-13 | New intent START_ONBOARDING: owner triggers tenant KYC via WhatsApp |
| 2026-03-13 | New intent RECORD_CHECKOUT: owner-driven digital offboarding checklist |
| 2026-03-13 | New ORM tables: `onboarding_sessions` + `checkout_records` (migrated to Supabase) |
| 2026-03-13 | Tenant KYC flow: 12-step WhatsApp form (full registration form) saves to Tenant |
| 2026-03-13 | Checkout flow: 5-step form creates CheckoutRecord + marks Tenancy as exited |
| 2026-03-14 | **Gatekeeper** (`gatekeeper.py`): smart router — (role, intent) → worker. Replaces flat if/elif in chat_api.py |
| 2026-03-14 | **AccountWorker** (`account_handler.py`): dedicated accounting persona for 11 financial intents |
| 2026-03-14 | **Shared helpers** (`_shared.py`): 8 fuzzy-search helpers extracted from owner_handler — used by both workers |
| 2026-03-14 | `owner_handler.py` trimmed from 2,595 → 1,434 lines — operational intents only |
| 2026-03-14 | `rooms.is_charged` + `rooms.is_staff_room` fields added — G05/G06 THOR marked free, staff rooms excluded from occupancy |
| 2026-03-14 | Canonical room migration: `migrate_rooms.py` — upserts 166 rooms, deactivates non-canonical |
| 2026-03-14 | **Deposit tracking**: `refunds` table now used. RECORD_CHECKOUT creates Refund(pending). Staff confirms via "process" |
| 2026-03-14 | **9am checkout alerts**: `_checkout_deposit_alerts` scheduler job — sends deposit summary to staff, creates CONFIRM_DEPOSIT_REFUND PendingAction |
| 2026-03-14 | `resolve_pending_action` structural fix: RECORD_CHECKOUT text steps (Q2–Q5 yes/no) now work correctly |
| 2026-03-14 | Data verification scripts: `occupancy_today.py`, `empty_rooms.py`, `payment_breakdown.py`, `deposit_check.py` |
| 2026-03-14 | Data fixes: 17 future no_show tenancies corrected to active. 9 real no-shows identified (past checkin, never arrived) |

---

## 15. Real Property Master Data Structure

**Last verified:** 2026-03-17 by Kiran
**Two properties:** Cozeevo THOR + Cozeevo HULK (83 rooms each, ~166 total)
**PG business name:** Cozeevo Co-living. Platform brand: Kozzy / getkozzy.com. Bot name: Artha.

### Staff Rooms (excluded from occupancy/revenue counts)
| Room | Property | Type | Notes |
|------|----------|------|-------|
| G05  | THOR | Single | Staff |
| G06  | THOR | Double | Staff |
| 107  | THOR | Double | Staff |
| 108  | THOR | Double | Staff |
| 114  | THOR | — | Staff (extra, non-standard) |
| 701  | THOR | Single | Staff, 7th floor |
| G12  | HULK | Triple | Staff |
| 702  | HULK | Single | Staff, 7th floor |

### Property 1: Cozeevo THOR
- **Ground Floor (G01–G10):**
  - **Single:** G01, G10
  - **Double:** G02, G03, G04
  - **Triple:** G07, G08, G09
  - **Staff (excluded):** G05, G06
- **Floor 1 (101–112 + extras):**
  - **Single:** 101, 112
  - **Double:** 102, 103, 104, 105, 106, 109, 110, 111
  - **Staff (excluded):** 107, 108, 114
- **Floors 2–6 (12 revenue rooms each, e.g. 201–212...):**
  - **Single:** `x01` and `x12` on every floor
  - **Double:** All remaining rooms (`x02` to `x11`)
- **Floor 7:** 701 = Staff only (excluded)

**THOR revenue rooms: ~78 rooms, ~145 beds**

### Property 2: Cozeevo HULK
- **Ground Floor (G11–G20):**
  - **Single:** G11, G20
  - **Double:** G15, G16, G17, G18, G19
  - **Triple:** G13, G14
  - **Staff (excluded):** G12
- **Floors 1–6 (12 revenue rooms each, e.g. 101–112...):**
  - **Single:** `x01` and `x12` on every floor
  - **Double:** All remaining rooms (`x02` to `x11`)
- **Floor 7:** 702 = Staff only (excluded)

**HULK revenue rooms: ~81 rooms, ~150 beds**

### Totals (revenue only, staff excluded)
| | Rooms | Beds |
|--|--|--|
| THOR | ~78 | ~145 |
| HULK | ~81 | ~150 |
| **Total** | **~159** | **~295** |

*Exact totals to be confirmed when DB max_occupancy values are verified against physical count.*

### Current Occupancy (from Untitled spreadsheet.xlsx, 2026-03-17)
| | THOR | HULK | Total |
|--|--|--|--|
| Active tenants (beds occupied) | 112 | 73 | **185** |
| Rooms with ≥1 tenant | ~78 | ~47 | **~125** |
| Occupancy by beds | 112/145 = **77%** | 73/150 = **49%** | 185/295 = **63%** |
| Occupancy by rooms | ~96% | ~57%  | **~77%** |

Pending bookings (room TBD, arriving May): Prasad Vadlamani, Aravind, Santhosh (all HULK)
