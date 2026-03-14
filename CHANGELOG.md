# Changelog

All notable changes to PG Accountant will be documented here.

## [1.4.0] — 2026-03-14

### Added
- **`src/whatsapp/gatekeeper.py`**: Smart router — maps `(role, intent)` → correct worker. Replaces flat `if role == "admin"` chain in `chat_api.py`. Owner-role users go to AccountWorker for financial intents, OwnerWorker for operational.
- **`src/whatsapp/handlers/account_handler.py`** (1,058 lines): AccountWorker — dedicated accounting persona. Owns 11 financial intents: `PAYMENT_LOG`, `QUERY_DUES`, `QUERY_TENANT`, `ADD_EXPENSE`, `QUERY_EXPENSES`, `REPORT`, `RENT_CHANGE`, `RENT_DISCOUNT`, `VOID_PAYMENT`, `ADD_REFUND`, `QUERY_REFUNDS`. Uses `Rs.` prefix, full due/paid/balance breakdowns, `property_logic.py` for all math.
- **`src/whatsapp/handlers/_shared.py`** (212 lines): 8 shared DB helpers used by both workers: fuzzy tenant search, disambiguation, room overlap check, pending action save. Extracted verbatim from owner_handler — zero logic change.

### Changed
- **`src/whatsapp/handlers/owner_handler.py`**: 2,595 → 1,434 lines. Financial handlers moved to `account_handler.py`. Shared helpers moved to `_shared.py`. Now operational intents only. Imports `_do_*` functions back from account_handler for `resolve_pending_action`.
- **`src/whatsapp/chat_api.py`**: 3-branch routing block replaced with single `reply = await route(intent, intent_result.entities, ctx, message, session)`.

---

# Changelog

All notable changes to PG Accountant will be documented here.

## [1.3.0] — 2026-03-13

### Added
- **`investment_expenses` table** (`models.py`, `migrate_investment_data.py`): L0 permanent table. 131 rows imported from "White Field PG Expenses" consolidated sheet. Tracks Whitefield PG setup/construction spending by investor (Chandrasekhar, Prabhakaran, Jitendra, Ashokan, Narendra, Kiran Kumar). Total: Rs 2.05 Cr. Dedup via SHA-256(sno+purpose+amount+paid_by). Individual person sheets (ASHOKAN/JITENDRA/NARENDRA/OUR SIDE) skipped — they are subsets of the consolidated sheet.
- **`pg_contacts` table** (`models.py`, `migrate_investment_data.py`): L0 permanent table. 62 contacts imported from Contacts.xlsx. Owner+staff visible only (not accessible to tenants/leads). Auto-categorized into 17 categories (plumber, electrician, carpenter, furniture, food_supply, decor, etc.). Dedup via SHA-256(name+phone+contact_for).
- **Migration + import script** (`src/database/migrate_investment_data.py`): Single idempotent script — creates both tables and imports from both Excel files. Safe to re-run: ON CONFLICT DO NOTHING on unique_hash.

---

## [1.2.0] — 2026-03-13

### Added
- **PAN Card ID proof** (`tenant_handler.py`): Added PAN Card, Voter ID, Ration Card as accepted ID proof types alongside Aadhar/Passport/Driving License.
- **Extended onboarding — 12 steps** (`tenant_handler.py`): Registration form fully digitized. New steps: DOB, father name, father phone, home address, email (skippable), occupation (skippable), emergency relationship. Total: 12 questions matching physical Cozeevo registration form.
- **7 new Tenant columns** (`models.py` + migrated): `father_name`, `father_phone`, `date_of_birth`, `permanent_address`, `email`, `occupation`, `emergency_contact_relationship`. All live in Supabase.
- **RULES intent** (`intent_detector.py`, `tenant_handler.py`, `owner_handler.py`): All 19 PG rules from the physical document. Available to tenants and owners. Trigger: "rules", "regulations", "pg rules", "house rules", "policy".
- **Master migration script** (`src/database/migrate_all.py`): Single idempotent script for all scenarios. Flags: `--seed` (add baseline data), `--status` (read-only check).
- **Data strategy guide** (`DATA_STRATEGY.md`): Documents load strategy for 6 scenarios — fresh install, test->prod, new PG customer, delta load, test reset, seed fix. Includes anti-duplicate guarantee table and pre-deployment checklist.

### Changed
- `tenant_handler._ONBOARDING_QUESTIONS`: Updated `ask_id_type` prompt to show all 4 options.
- `owner_handler._help`: Updated menu to show onboarding + checkout + rules commands.

---

## [1.1.0] — 2026-03-13

### Added
- **Phone normalization** (`role_service._normalize`): WhatsApp sends `+917845952289`, DB stores `7845952289`. Strips `+91`/`91` prefix for Indian 10-digit numbers automatically.
- **Hot water / plumbing keywords** (`tenant_handler.py`): `hot water`, `geyser`, `heater`, `shower` now map to `plumbing` complaint category.
- **Complaint description passthrough** (`chat_api.py`): Raw message injected into `entities["description"]` before routing so complaint text reaches handlers instead of generic placeholder.
- **START_ONBOARDING intent** (`intent_detector.py`): Owner triggers "start onboarding for [name] [number]" → creates tenant record + OnboardingSession with 48-hour TTL.
- **Tenant KYC onboarding flow** (`tenant_handler.py`, `chat_api.py`): Step-by-step WhatsApp form: gender → emergency contact name → emergency contact phone → ID type → ID number. Data saved to `Tenant` record on completion.
- **RECORD_CHECKOUT intent** (`intent_detector.py`): Owner triggers checkout form via "record checkout", "offboard", "keys returned", etc.
- **Offboarding checklist flow** (`owner_handler.py`): Multi-step form: cupboard key → main key → damage notes → pending dues → deposit refund amount + date. Creates `CheckoutRecord`, marks `Tenancy.status = exited`.
- **OnboardingSession ORM model** (`models.py`): New L3 table `onboarding_sessions` — step-based JSON state machine, 48-hour TTL, foreign key to tenants + tenancies.
- **CheckoutRecord ORM model** (`models.py`): New L3 table `checkout_records` — captures key returns, damages, dues, deposit refund date, exit date.
- **Migration script** (`src/database/migrate_onboarding_checkout.py`): Creates both new tables. **Already run successfully.**

### Changed
- `role_service._normalize()` rewritten to correctly handle all Indian phone format variants.
- `intent_detector._OWNER_RULES`: `START_ONBOARDING` and `RECORD_CHECKOUT` added at top (highest priority).
- `owner_handler.resolve_pending_action()`: Extended to handle `RECORD_CHECKOUT` multi-step flow.
- `chat_api.py`: Added step 2a — checks active `OnboardingSession` before normal intent detection, intercepting onboarding answers correctly.

---

## [1.0.0] — 2025-03-10

### Added
- Full project scaffold with 40+ source files
- Database layer: SQLAlchemy ORM (transactions, customers, vendors, employees, properties, categories)
- Monthly aggregation table for fast reporting
- Pending entity approval queue (user must confirm new master data)
- Parsers: CSV (generic), PDF (pdfplumber), PhonePe, Paytm, UPI, HDFC/SBI/ICICI bank statements
- File auto-dispatcher (detects source from filename / content sniff)
- Rules engine: deterministic keyword + regex categorization (97% coverage)
- Deduplication via SHA-256 hash (unique_hash column + batch dedup)
- Merchant normalizer for Indian payment apps
- LangGraph reasoning router (max 2 iterations, 30s timeout)
- Rules-based intent detector (97% WhatsApp messages handled without AI)
- Claude API gateway (classify_merchant, detect_intent, suggest_entity)
- All prompts centralized in prompts.py
- Interactive VS Code terminal approval via questionary
- Reconciliation engine: daily / weekly / monthly with rent + salary tracking
- Report generator: text summary, CSV, Excel (openpyxl), HTML dashboard
- Jinja2 HTML dashboard with Chart.js (auto-deletes after 24h)
- WhatsApp webhook handler (FastAPI + Twilio)
- n8n workflow generator (WhatsApp, ingestion, reconciliation workflows)
- n8nMCP REST API client (create, activate, deploy workflows)
- CLI commands: ingest-file, run-reconciliation, generate-report, start-api, configure-workflow
- Docker Compose setup (API + n8n + Redis)
- Full documentation: README.md, SYSTEM_ARCHITECTURE.md, BRAIN.md
