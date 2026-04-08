# Kozzy AI Platform — System Specification

> **One document to understand, rebuild, or clone the entire platform.**
> Last updated: 2026-04-08

---

## 1. What This Is

**Kozzy** is a white-label WhatsApp-based PG (paying guest) management platform. Each PG gets a fully autonomous AI assistant that handles accounting, operations, tenant management, and natural conversation — configured entirely through database, zero code changes per PG.

**First tenant:** Cozeevo Co-living (THOR + HULK buildings, Chennai).
**Bot name:** Cozeevo Help Desk.
**Domain:** api.getkozzy.com

### Stack
| Layer | Tech |
|---|---|
| API | FastAPI (Python 3.11) |
| Database | Supabase (PostgreSQL) |
| LLM | Groq (Llama 3.3 70B) — free tier |
| AI Framework | PydanticAI (structured output, agents, tools) |
| Messaging | Meta WhatsApp Cloud API v18.0 (direct webhook, no Twilio/n8n) |
| Hosting | Hostinger VPS ($5/mo), nginx + systemd + SSL |
| Sheets | Google Sheets API (fire-and-forget write-back) |

---

## 2. Architecture

```
WhatsApp message (Meta webhook)
  -> nginx (SSL termination, reverse proxy)
  -> FastAPI :8000
      -> chat_api.py (rate limit, dedup by msg_id)
      -> role_service.py (phone -> role lookup from pg_config + authorized_users)
      -> Check PendingAction (30-min TTL disambiguation state)
          -> If pending: resolve confirm/correction/selection
          -> If no pending:
              -> intent_detector.py (regex — fast, free)
                  -> Match -> execute via gatekeeper
                  -> No match -> ConversationAgent (PydanticAI)
                      -> Classifies intent OR converses naturally
                      -> Confidence routing (>0.9 / 0.6-0.9 / <0.6)
                      -> Background LearningAgent saves to intent_examples
      -> gatekeeper.py (role + intent -> handler)
          -> account_handler.py (financial: payments, dues, reports, expenses)
          -> owner_handler.py (operational: tenants, rooms, complaints, contacts)
          -> tenant_handler.py (self-service: balance, payments, details)
          -> lead_handler.py (sales: pricing, availability, visits)
      -> WhatsApp reply sent
```

### Data Flow
```
PG Owner's Excel (offline records)
  -> scripts/clean_and_load.py (THE parser — read_history())
      -> Google Sheet (monthly tabs + TENANTS tab)
      -> src/database/excel_import.py -> Supabase DB
  ONE parser. Never duplicate.
```

---

## 3. Multi-Tenant Model (pg_config)

Every PG is configured through one row in `pg_config`. The platform reads ALL PG-specific data from this table — nothing hardcoded.

### pg_config table

| Column | Type | What it drives |
|---|---|---|
| id | UUID PK | Foreign key for all per-PG tables |
| pg_name | TEXT | "Cozeevo Co-living" — display name |
| brand_name | TEXT | "Cozeevo Help Desk" — bot identity in conversations |
| brand_voice | TEXT | Personality injected into AI system prompt (tone, style, greeting) |
| buildings | JSONB | [{name, floors, type (male/female/mixed), room_prefix}] |
| rooms | JSONB | [{number, building, floor, beds, type (single/double/triple)}] |
| staff_rooms | JSONB | Room numbers excluded from revenue (e.g. ["G05","G06","107"]) |
| staff | JSONB | [{name, role, phone}] |
| admin_phones | JSONB | ["+917845952289"] — admin detection, replaces hardcoded list |
| pricing | JSONB | {sharing_3: 7500, sharing_2: 9000, single: 12000, ...} |
| bank_config | JSONB | {bank_name, account_format, statement_columns, upi_id_patterns} |
| expense_categories | JSONB | ["Electricity","Salary","Plumbing",...] |
| custom_intents | JSONB | PG-specific intents beyond defaults (optional) |
| business_rules | JSONB | {proration, checkout_notice_days, deposit_months, billing_cycle, ...} |
| whatsapp_config | JSONB | {phone_number_id, waba_id, token_env_key, verify_token} |
| gsheet_config | JSONB | {sheet_id, service_account_key, tab_structure} |
| timezone | TEXT | "Asia/Kolkata" |
| is_active | BOOLEAN | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### Onboarding a new PG
1. INSERT one row into `pg_config`
2. Register admin phones in `authorized_users` with `pg_id`
3. Set up WhatsApp number (Meta Business API)
4. Done — bot works immediately, learns from day 1

**Zero code changes. Zero new files. Zero deployment.**

---

## 4. Database Schema

### Table Hierarchy (7 layers)

**L0 — Platform Config (never wipe)**
- `pg_config` — master config per PG (see above)

**L0 — Master Data (per PG, never wipe)**
- `properties` — buildings (FK: pg_id)
- `rooms` — room_number TEXT (handles "G15","508/509"), max_occupancy, is_staff_room
- `rate_cards` — pricing tiers
- `staff` — PG staff
- `food_plans`, `expense_categories`
- `pg_contacts` — vendor/service contacts (plumber, electrician)
- `authorized_users` — role registry (admin/owner/receptionist), FK: pg_id
- `learned_rules` — auto-generated regex from learning flywheel
- `documents`, `investment_expenses`

**L1 — Tenant Master (re-importable)**
- `tenants` — phone=UNIQUE, name, gender, DOB, KYC fields, emergency contact
- `tenancies` — one row per stay: tenant_id + room_id + dates + billing terms
  - status: active / exited / no_show / cancelled
  - sharing_type: single / double / triple / premium
  - agreed_rent, security_deposit, billing_cycle (standard/custom), cycle_start_day

**L2 — Financial (never hard-delete, use is_void)**
- `rent_schedule` — what's owed per month: (tenancy_id, period_month) UNIQUE
  - effective_due, status (pending/partial/paid), due_date
- `payments` — received money: amount, mode (cash/upi/bank_transfer/cheque), is_void
  - unique_hash (SHA-256 dedup)
- `refunds` — deposit refunds with reason
- `expenses` — operating costs with category, is_void
- `daywise_stays` — short-term guests (1-10 days), separate from tenancy chain

**L3 — Operational**
- `pending_actions` — disambiguation state machine (30-min TTL)
  - phone, intent, action_data (JSON), choices (JSON), expires_at, resolved
- `complaints` — register/update/query cycle
- `activity_log`, `chat_messages`, `whatsapp_log`
- `leads`, `vacations`, `reminders`
- `onboarding_sessions`, `checkout_records`

**L4 — Access Control**
- `authorized_users` — phone UNIQUE, role enum, pg_id FK

**L5 — AI / Learning**
- `intent_examples` — self-learning examples per PG (see Section 6)
- `classification_log` — audit trail per PG (see Section 6)
- `conversation_memory` — pgvector semantic search (future)
- `conversation_history` — chat window for LLM context

**L6 — Bank**
- `bank_uploads` — uploaded statement files
- `bank_transactions` — parsed rows, SHA-256 dedup, category, tenant_match

### Key Constraints
- `tenants.phone` UNIQUE
- `authorized_users.phone` UNIQUE
- `(tenancy_id, period_month)` UNIQUE on rent_schedule
- `bank_transactions.unique_hash` UNIQUE
- `period_month` always 1st of month (2026-03-01, never mid-month)
- `room_number` is TEXT (handles G15, 508/509, G20)
- `is_staff_room=True` excluded from ALL revenue/occupancy calculations
- Premium is a tenancy attribute, not room — 1 person gets max_occupancy beds

---

## 5. Intent System

### Detection Pipeline
1. **Regex** (97% of messages) — pattern matching in `intent_detector.py`
2. **ConversationAgent** (3% fallback) — PydanticAI agent with few-shot examples
3. **Learning** — every LLM classification feeds back into `intent_examples`

### Intent Catalog (69 intents)

**Financial (admin/owner only):**
PAYMENT_LOG, QUERY_DUES, QUERY_TENANT, ADD_EXPENSE, QUERY_EXPENSES, VOID_PAYMENT, VOID_EXPENSE, ADD_REFUND, QUERY_REFUNDS, REPORT, BANK_REPORT, BANK_DEPOSIT_MATCH

**Operational (admin/owner/receptionist):**
ADD_TENANT, START_ONBOARDING, CHECKOUT, RECORD_CHECKOUT, SCHEDULE_CHECKOUT, NOTICE_GIVEN, UPDATE_CHECKIN, UPDATE_CHECKOUT_DATE, ROOM_TRANSFER, RENT_CHANGE, RENT_DISCOUNT, DEPOSIT_CHANGE, QUERY_VACANT_ROOMS, QUERY_OCCUPANCY, ROOM_LAYOUT, ROOM_STATUS, COMPLAINT_REGISTER, COMPLAINT_UPDATE, QUERY_COMPLAINTS, SEND_REMINDER_ALL, REMINDER_SET, LOG_VACATION, ACTIVITY_LOG, QUERY_ACTIVITY, ADD_CONTACT, QUERY_CONTACTS, UPDATE_TENANT_NOTES, GET_TENANT_NOTES, GET_WIFI_PASSWORD, SET_WIFI, ADD_PARTNER, QUERY_EXPIRING, QUERY_CHECKINS, QUERY_CHECKOUTS, RULES, HELP

**Tenant (self-service, read-only):**
MY_BALANCE, MY_PAYMENTS, MY_DETAILS, HELP

**Lead (enquiry):**
ROOM_PRICE, AVAILABILITY, ROOM_TYPE, VISIT_REQUEST, GENERAL

**Receptionist blocked from:** REPORT, BANK_REPORT, RENT_CHANGE, VOID_PAYMENT, VOID_EXPENSE, ADD_REFUND, RENT_DISCOUNT, DEPOSIT_CHANGE, ADD_PARTNER

### Entity Extraction
- **Amount:** supports k suffix ("15k" = 15000), strips commas
- **Name:** titlecase normalization
- **Room:** bare number or "room X" format, partial match
- **Month:** keyword extraction ("march", "this month", "last month")
- **Mode:** cash/upi/gpay/bank_transfer

### Pending State Machine
- `INTENT_AMBIGUOUS` — 2+ regex matches, show numbered list, user picks
- `AWAITING_CLARIFICATION` — missing field (name, month, amount), ask once
- `CONFIRM_*` — payment/expense/contact/tenant confirmation (Yes/No)
- Multi-step forms: onboarding (14 KYC fields), checkout (checklist)
- 30-minute TTL, auto-expire
- Correction mid-flow updates pending in-place (no new record)
- `__KEEP_PENDING__` protocol: handler returns this to keep pending alive

---

## 6. AI Agent System (PydanticAI)

### ConversationAgent (the brain)

Single PydanticAI agent handles ALL non-regex messages:
- **Classifies** intents using few-shot examples from this PG's `intent_examples`
- **Converses** naturally — greetings, small talk, "who are you?", thanks
- **Shows options** when medium confidence (0.6-0.9)
- **Asks clarification** when low confidence (<0.6)
- **Handles corrections** mid-flow ("no, it was 12000")
- **Extracts entities** from natural language

**System prompt built dynamically from pg_config:**
```
You are {pg_config.brand_name}, an AI assistant for {pg_config.pg_name}.
{pg_config.brand_voice}

Buildings: {pg_config.buildings}
Available intents for {role}: {intents}

Recent examples of how users at this PG talk:
{top_k_examples from intent_examples WHERE pg_id = this_pg}

Chat history: {recent_messages}
Pending action: {pending_context}
```

**Tools available:**
- `search_similar_examples(message)` — similarity search in intent_examples
- `get_tenant_context(name_or_room)` — tenant/room lookup
- `get_room_info(room_number)` — vacancy, current tenant, pricing

**Response model:**
```python
class ConversationResult(BaseModel):
    action: str          # "classify", "ask_options", "clarify", "converse", "correct"
    intent: str | None
    confidence: float
    entities: dict
    options: list[str] | None
    correction: dict | None
    reply: str | None
    reasoning: str
```

### Confidence Routing

| Confidence | Action | Learning |
|---|---|---|
| >0.9 | Execute silently | Auto-confirmed if no correction |
| 0.6-0.9 | Show options ("Did you mean: 1. X 2. Y") | Saved as user_selection |
| <0.6 | Ask explicitly | Saved as user_clarification |
| Any + correction | Re-route | Saved as user_correction (highest value) |
| Conversation | Reply naturally | Logged, no intent_example |

### LearningAgent (the memory)

Background async agent, per PG, never talks to users:
- Logs every classification to `classification_log`
- Saves confirmed examples to `intent_examples` (scoped by pg_id)
- Finds patterns in misclassifications (3+ similar = high-quality pattern)
- Prunes contradictory examples (soft delete)
- Rate limited: max 1 Groq call per 10 seconds

**Each PG learns independently.** PG A's vocabulary doesn't affect PG B.

### Learning Flywheel
```
Day 1:   Default intents only. No PG-specific knowledge.
Week 1:  50-100 examples. Few-shot prompts improving.
Month 1: 500+ examples. Most phrasings covered. Options shown rarely.
Over time: Bot becomes expert at THIS PG's communication style.
```

### BankParserAgent

Per-PG bank statement processing using `pg_config.bank_config`:
- Column mapping from config (not hardcoded)
- UPI pattern matching from config
- Expense categories from `pg_config.expense_categories`
- Tenant matching against this PG's tenant list
- SHA-256 dedup on bank_transactions

---

## 7. Financial Logic

### Dues Calculation (LOCKED — 3 conditions)
1. `tenancy.status = 'active'`
2. `checkin_date < month_start` (strict less-than)
3. `rent_schedule.period_month = target_month` (single month only, never cumulative)

**Outstanding:** `effective_due - SUM(payments WHERE is_void=False)`

### Payment Processing
1. Identify tenant (fuzzy search)
2. Resolve target month (explicit or auto-detect)
3. Check duplicate (24hr window)
4. Create Payment record
5. Update RentSchedule status (pending/partial/paid)
6. Google Sheet write-back (async, fire-and-forget)

**Allocation:** Oldest-first across months. Override syntax: "all to march" or "feb 3000 march 5000"

### Billing Cycles
- **Standard** (1st-to-1st): first month prorated. `prorated = INT(rent * days_remaining / days_in_month)`
- **Custom** (e.g. 6th-to-6th): first month full, no proration

### Proration Rules
| Scenario | Prorated? |
|---|---|
| New checkin mid-month (standard cycle) | YES |
| New checkin mid-month (custom cycle) | NO |
| Normal checkout | NO — full month charged |
| Early exit | NO — full month charged |
| Overstay (extra days after checkout) | YES — extra days only |

### Void/Refund
- **NEVER hard-delete** financial records — set `is_void=True`
- Recalculate RentSchedule status from remaining non-void payments
- Checkout settlement: `net_refund = deposit - outstanding_rent - maintenance - damages`

### Occupancy
- `occupied_beds = SUM(IF premium THEN room.max_occupancy ELSE 1)` WHERE active + no_show, excluding staff rooms
- `total_beds = SUM(max_occupancy)` WHERE `is_staff_room=False` (currently 291)
- `vacancy = total - occupied - no_show`
- `occupancy_pct = ROUND(occupied / total * 100, 1)`

### P&L Report
- Months as columns, categories as rows
- Income: Rent (from payments), Deposits, Day-wise stays
- Expenses: 18 categories classified by keyword rules (first match wins, Non-Operating first)
- Source: Bank statement Excel (primary), payments table (fallback for income)

### Expense Categories (configurable per PG via pg_config)
Default: Electricity, Water, Salaries, Food, Furniture, Maintenance, IT/Internet, Gas, Property Rent, Police/Govt, Marketing, Shopping, Bank Charges, Housekeeping, Security, Insurance, Legal, Other

---

## 8. Role System

### Roles (from authorized_users + tenant lookup)
| Role | How detected | Capabilities |
|---|---|---|
| admin | phone in pg_config.admin_phones | Everything |
| owner/power_user | phone in authorized_users | Everything except system config |
| receptionist | phone in authorized_users, role=receptionist | Operational only, blocked from financial reports |
| tenant | phone matches tenants table | Read-only: balance, payments, details |
| lead | unknown phone (default) | Enquiry: pricing, availability, visits |
| blocked | flagged in authorized_users | Nothing |

### Rate Limiting
- All roles: 10 msgs/10min, 50/day
- Admin/owner: bypass rate limit
- Stored in `rate_limit_log` (10-min granularity)

---

## 9. Integrations

### WhatsApp (Meta Cloud API v18.0)
- Direct webhook: `POST /webhook/whatsapp` (no n8n, no Twilio)
- Verification: `GET /webhook/whatsapp` with verify_token
- Dedup: Meta sends 4-5 duplicate POSTs per message — in-memory msg_id cache (60s TTL)
- Voice: media download + Groq Whisper transcription (multilingual)
- Config per PG: `pg_config.whatsapp_config`

### Google Sheets
- Fire-and-forget async write-back on payment log
- Sheet structure: TENANTS tab + monthly tabs (payment tracking)
- Config per PG: `pg_config.gsheet_config`
- Service account credentials in `credentials/gsheets_service_account.json`

### Supabase (PostgreSQL)
- Async via SQLAlchemy + asyncpg, pool_size=10
- Idempotent migration system (`migrate_all.py`, append-only)
- All tables per PG via pg_id foreign key

### Groq LLM
- Model: llama-3.3-70b-versatile
- Used for: intent fallback (~3%), conversation, merchant classification
- Rate limit: 30 req/min, 14,400 req/day (free tier)
- PydanticAI wraps all calls with structured output + retries

### Bank Statement Processing
- Formats: PDF (pdfplumber/pymupdf), Excel (openpyxl), CSV
- Parse -> classify (keyword rules from pg_config.expense_categories) -> dedup SHA-256 -> save
- Deposit matching: amount within 10%, date within 45 days of checkin, name in description

---

## 10. Key Helpers (_shared.py)

These are the core utilities used across all handlers:

| Function | What it does |
|---|---|
| `_find_active_tenants_by_name()` | Prefix + substring ilike search with dedup |
| `_find_active_tenants_by_room()` | Room number partial match |
| `_find_similar_names()` | Difflib fuzzy matching (cutoff 0.55-0.62) for typos |
| `_save_pending()` | Save PendingAction with 30-min TTL, expire old ones |
| `build_dues_snapshot()` | Complete tenant dues: pending/partial months, total outstanding |
| `compute_allocation()` | Allocate payment oldest-first across months |
| `parse_allocation_override()` | Parse "all to march" or "feb 3000 march 5000" |
| `is_affirmative() / is_negative()` | Multilingual yes/no (Hindi + English) |
| `bot_intro()` | Role-specific greeting with daily rotation |
| `is_first_time_today()` | Check if phone messaged today (IST-based) |

---

## 11. Deployment

### Infrastructure
- **VPS:** Hostinger KVM 1 ($5/mo, Ubuntu 22.04, 1 vCPU, 1GB RAM)
- **Domain:** api.getkozzy.com (SSL via Let's Encrypt)
- **Process:** systemd service → uvicorn main:app --host 0.0.0.0 --port 8000
- **Proxy:** nginx → :8000 (/webhook/*, /api/*, /healthz)

### Deploy command
```bash
cd /opt/pg-accountant && git pull && pip install -r requirements.txt && python -m src.database.migrate_all && systemctl restart pg-accountant
```

### Environment variables
| Variable | Required | Description |
|---|---|---|
| DATABASE_URL | Yes | Supabase PostgreSQL connection string |
| WHATSAPP_TOKEN | Yes | Meta API access token |
| WHATSAPP_PHONE_NUMBER_ID | Yes | Meta phone number ID |
| GROQ_API_KEY | Yes | Groq API key (free) |
| LLM_PROVIDER | No | "groq" (default) / "ollama" / "anthropic" |
| GSHEETS_SHEET_ID | No | Google Sheet ID for write-back |
| TEST_MODE | No | "1" enables test endpoints |
| USE_PYDANTIC_AGENTS | No | "true" to enable new agent system |
| DEFAULT_PG_ID | No | UUID of default PG (Cozeevo) |

### Multi-PG deployment
Each PG on same VPS, same FastAPI instance. Routing by phone number → pg_id lookup. Separate WhatsApp numbers per PG (Meta Business API). Separate Supabase project optional (or shared DB with pg_id scoping).

---

## 12. Testing

### Golden Test Suite
- 115 test cases across all intent groups
- Run: `python tests/eval_golden.py` (requires API running + TEST_MODE=1)
- Single test: `python tests/eval_golden.py --id G001`
- Threshold: Regex 76.5%, Haiku 94.8%, Groq ~90%

### Test SOP
1. Start API locally: `venv/Scripts/python main.py`
2. Set `TEST_MODE=1` in .env
3. Run golden suite
4. Show results to Kiran BEFORE pushing
5. Test on VPS after deploy (local pass != VPS pass if migrations not run)

---

## 13. Import Workflow (Cozeevo-specific)

### Excel → Sheet → DB
```bash
# 1. Parse Excel, write to Google Sheet
python scripts/clean_and_load.py

# 2. Drop existing L1+L2 data
python -m src.database.wipe_imported --confirm

# 3. Import to DB
python -m src.database.excel_import --write

# 4. Run migrations (if new tables)
python -m src.database.migrate_all
```

### Single parser rule
`scripts/clean_and_load.py::read_history()` is THE ONLY parser. DB import uses it via `excel_import.py`. Never duplicate parsing logic.

### April-specific importers
- `scripts/import_april.py` — April monthly payments (drop-and-reload)
- `scripts/import_daywise.py` — Day-wise short stays (both Excel files, SHA-256 dedup)

---

## 14. File Map

### Core (touch frequently)
| File | Purpose |
|---|---|
| `src/whatsapp/chat_api.py` | Webhook + pending state + message orchestration |
| `src/whatsapp/intent_detector.py` | Regex intent patterns + AI fallback routing |
| `src/whatsapp/gatekeeper.py` | Role+intent → handler routing |
| `src/whatsapp/role_service.py` | Phone → role lookup + rate limiting |
| `src/whatsapp/handlers/account_handler.py` | Financial intents |
| `src/whatsapp/handlers/owner_handler.py` | Operational intents |
| `src/whatsapp/handlers/tenant_handler.py` | Tenant self-service |
| `src/whatsapp/handlers/lead_handler.py` | Lead/sales |
| `src/whatsapp/handlers/_shared.py` | Fuzzy search, dues, allocation, formatting |
| `src/database/models.py` | All ORM models |
| `src/database/migrate_all.py` | Migration runner (APPEND ONLY) |

### AI (new agent system)
| File | Purpose |
|---|---|
| `src/llm_gateway/agents/conversation_agent.py` | ConversationAgent (PydanticAI) |
| `src/llm_gateway/agents/learning_agent.py` | LearningAgent (background) |
| `src/llm_gateway/agents/bank_parser_agent.py` | BankParserAgent (per-PG) |
| `src/llm_gateway/agents/models.py` | Pydantic response models |
| `src/llm_gateway/agents/tools/` | Agent tools (search_examples, get_context) |
| `src/llm_gateway/claude_client.py` | Legacy LLM client (fallback) |
| `src/llm_gateway/prompts.py` | Legacy prompt templates |

### Scripts (run manually)
| File | Purpose |
|---|---|
| `scripts/clean_and_load.py` | Excel parser + Sheet writer (THE parser) |
| `scripts/import_april.py` | April payment importer |
| `scripts/import_daywise.py` | Day-wise short-stay importer |

### Config
| File | Purpose |
|---|---|
| `.env` | Environment variables (gitignored) |
| `CLAUDE.md` | AI assistant instructions |
| `requirements.txt` | Python dependencies |

### DO NOT TOUCH
- `migrate_all.py` — append only, never remove existing migrations
- Live VPS DB — test locally first
- Financial records — use is_void, never delete
