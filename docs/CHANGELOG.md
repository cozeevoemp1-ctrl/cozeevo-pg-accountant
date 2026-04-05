# Changelog

All notable changes to PG Accountant will be documented here.

## [1.16.0] — 2026-04-05 — Image-Based Check-in + Haiku Intent Fallback

### Added
- **Image-based tenant check-in** — upload registration form photo, Claude Haiku extracts all fields
- **form_extractor.py** — vision extraction with training data collection for future Groq fine-tuning
- **Interactive edit flow** — "edit name Kanchan Sharma" to correct any extracted field
- **Room validation on check-in** — full rooms show occupants with checkout option ("1 today")
- **Gender mismatch warning** — warns when adding male tenant to female-occupied room
- **Sharing type confirmation** — asks double/premium for multi-bed rooms
- **Document collection flow** — after check-in, collects ID proofs + signed rules page
- **15 new TENANTS Sheet columns** — DOB, father, address, emergency, email, occupation, education, office, ID proof, food, notes
- **3 new DB columns** — educational_qualification, office_address, office_phone
- **New DocumentTypes** — reg_form, rules_page (archived per tenant)
- **Duplicate-log prevention** — message after successful log treated as query, not re-log
- **Claude Haiku as intent fallback** — replaces Groq for UNKNOWN intents (much better accuracy)
- **Expanded intent list** — complaints, vacation, room status, expense queries now recognized
- **38 edge case tests** for the full check-in flow

### Changed
- ANTHROPIC_API_KEY now used for two features: form extraction + intent fallback
- Intent detection falls back to Haiku (~$0.0005/call) instead of Groq for unrecognized messages
- ADD_TENANT prompt now offers image upload option

### Added (continued — same session)
- **Checkout form extraction** — photo upload extracts name, room, date, refund details, verification checklist
- **Refund Amount column** in Sheet (col 17, KYC shifted to 18-32)
- **Receipt slip archiving** — auto-prompts after payment confirm AND checkout refund
- **COLLECT_RECEIPT handler** — saves receipt photos tagged to tenant/payment
- **Image + expense keyword routing** — photo with "EB bill" always routes to ADD_EXPENSE
- **"log EB bill" regex fix** — routes to ADD_EXPENSE instead of ACTIVITY_LOG
- **_save_pending import fix** in LOG_EXPENSE_STEP handler
- **"eb" alone** maps to electricity category (no need for "eb bill")

### Architecture
- Haiku vision: called once per form photo (check-in or checkout), no API for edits
- Haiku intent fallback: called only for UNKNOWN intents (~$0.0005/call)
- Training pairs saved to data/form_training/ for future Groq fine-tuning
- All documents tagged to tenant_id/tenancy_id in documents table
- Receipt slips saved under data/documents/receipts/YYYY-MM/

## [1.15.0] — 2026-04-02/03 — Reminder System + Payment Flow Fixes + Sheet Sync

### Added
- **Reminder system via official WhatsApp number** — 85488 84466 sends template-based rent reminders
- **`src/whatsapp/reminder_sender.py`** — template + text sending, auto-fallback to bot number
- **`src/api/reminder_router.py`** — endpoints: preview-rent, preview-all-tenants, blast-rent-reminder, send-custom, send-bulk
- **Meta Message Templates** — `rent_reminder` and `general_notice` approved and working
- **GSheets void_payment()** — voids now sync to Sheet (subtract amount, update status/notes)
- **Void payment picker** — when no current month payment, shows list of recent payments to choose from
- **CONFIRM_PAYMENT_ALLOC mode correction** — replies like "upi" or "no she paid upi" now update payment mode

### Fixed
- **GSheets payment write-back was broken** — `ctx.name` → `ctx_name` (every bot payment was silently failing)
- **GSheets method validation** — `Cash` rejected, now lowercased before validation
- **Excel import silently skipping tenants** — missing room → UNASSIGNED, missing date → fallback
- **Payment mode defaulting to CASH** — no longer hardcoded, uses explicit fallback
- **"Suggested allocation" noise** — single-month payments now show simple confirmation
- **Void defaulting to most recent payment** — now defaults to current month, prevents accidental old-month voids

### Architecture
- Two WhatsApp numbers: +1 55 (bot) + 84466 (official, reminders only)
- 84455 remains regular WhatsApp Business app for manual chatting
- Scheduler sends reminders on 1st/15th via official number when configured

### Config
- New env vars: `REMINDER_WHATSAPP_TOKEN`, `REMINDER_WHATSAPP_PHONE_NUMBER_ID`

## [1.14.0] — 2026-04-01 — Sheet Dashboard Auto-Refresh + Full April Reload

### Fixed
- **Sheet dashboard not auto-updating** — Apps Script `onEdit` doesn't fire on API writes. Added `_refresh_summary_sync()` in gsheets.py that recalculates per-row Total Paid, Balance, Status AND summary rows 2-3 after every bot write.
- **Previous month dues not carried forward** — APRIL 2026 was in old 15-column format without Prev Due column. Upgraded to new 17-column format with Phone, Prev Due, Entered By.
- **No-shows missing from April** — reload script was excluding NO SHOW entries. Fixed to include April no-shows (18 total).
- **Stale NO-SHOW events** — tenants who changed from NO SHOW to CHECKIN in Excel kept stale NO-SHOW event in sheet. Excel now overrides.
- **Missing tenants in TENANTS master** — 14 tenants added (new bookings, no-shows with empty IN/OUT).

### Added
- **`_refresh_summary_sync()`** — Python-side mirror of Apps Script `updateMonthSummary`. Per-row recalc + summary rows. Called after payment, add_tenant, checkout, notice.
- **Entered By column (Q)** — audit trail showing who logged each payment (from `ctx.name` in WhatsApp handler).
- **Notes carry-forward** — permanent DB comments + March notes loaded into April Notes column. Apps Script `createMonthTab` updated to carry forward prev month notes when dues exist.
- **`scripts/reload_april.py`** — full reload script: Excel + DB notes + March Sheet + existing payments → 17-column April tab.
- **DB payment reader** in reload script — ensures real payments survive reloads.

### Changed
- Monthly tab format: 15 → 17 columns (added Phone, Prev Due, Entered By)
- Apps Script `createMonthTab`: 16 → 17 columns, notes carry-forward
- Apps Script summary rows: lastCol P → Q

### Sheet State (April 2026)
- 225 rows (207 checked-in + 18 no-show)
- 225 beds occupied (189 regular + 18 premium × 2)
- 48 vacant, 77.3% occupancy
- 25 tenants with prev dues from March
- 106 tenants with permanent notes

### Files changed
gsheets.py, account_handler.py, gsheet_apps_script.js, reload_april.py (new)

---

## [1.13.0] — 2026-04-01 — Overpayment Fix + Role Simplification

### Fixed
- **Overpayment false positive** — payment was added to session before `prev_paid` query, causing double-counting on first payment of a new month (when rent_schedule auto-generates + flushes). Moved payment creation after prev_paid query.
- **Golden test leaks** — updated "Artha" bot name references to "Cozeevo" in test suite (G091, G097, G098)
- **Receptionist migration** — fixed `_add_receptionist_role` in migrate_all.py (was using wrong enum type name `user_role` instead of `userrole`)

### Changed
- **Simplified to 3 roles:** admin (Kiran — full L0 access), owner (Lakshmi, Prabhakaran — all except L0), receptionist (Sathyam — payments + queries, no financial reports/expenses/voids/refunds)
- **Removed** `power_user` and `key_user` roles from enum, all code, and DB
- **Removed** test users (TestKeyUser, Test Receptionist) from authorized_users
- **Expanded receptionist blocked list:** REPORT, BANK_REPORT, BANK_DEPOSIT_MATCH, QUERY_EXPENSES, ADD_EXPENSE, VOID_EXPENSE, ADD_REFUND, QUERY_REFUNDS, VOID_PAYMENT, RENT_CHANGE, RENT_DISCOUNT

### Files changed (15)
account_handler, gatekeeper, models, role_service, intent_detector, chat_api, _shared, webhook_handler, claude_client, scheduler, v2/chat_api_v2, v2/supervisor, owner_handler, migrate_all, seed

---

## [1.12.0] — 2026-03-31 — Bug Fixes, Corrections, Receptionist Test Suite

### Fixed
- **Payment confirmation crash** — `UnboundLocalError` on `_do_log_payment_by_ids` in `resolve_pending_action` (lazy import fix)
- **"paied" typo** not matching PAYMENT_LOG intent
- **"pending dues"** not matching QUERY_DUES intent

### Added
- **Month correction mid-flow** — "no for february", "no january" during payment confirmation
- **Amount+month combo correction** — "no 14000 for february" during payment confirmation
- **Hindi affirmative keywords** — "theek hai", "thik hai", "sahi hai" now recognized as confirmation
- **Sathyam (7993273966)** added as receptionist in authorized_users + staff table
- **8548884455 (Business Number)** added as admin in authorized_users
- **Prabhakaran (9444296681)** added to Meta WhatsApp test number list
- **102-case E2E receptionist test suite** (96/102 passing)
- **25-case correction workflow test suite** (25/25 passing)
- **Bank P&L report** — `scripts/full_pnl_view.py` for investment vs operating expense breakdown

### Diagnosed
- **Prabhakaran bot not responding** — Meta error 131030 (recipient not in allowed list). App still uses test number (+1 555 192 0467), not real business number. Messages reach bot but replies blocked by Meta.

---

## [1.11.0] — 2026-03-30 — Payment Flow Rework + Notes Architecture + Doc Consolidation

### Added
- **Payment dues snapshot** — both quick payment ("Raj paid 8000 cash") and step-by-step ("collect rent") now show full dues breakdown (per-month amounts, status, notes) before confirmation
- **Smart month allocation** — oldest-first allocation when tenant owes across multiple months, receptionist can override ("all to march" or "feb 3000 march 5000")
- **Two-tier notes system** — `tenancy.notes` (permanent agreements) + `rent_schedule.notes` (monthly status), both synced to DB + Google Sheet with retry (3 attempts)
- **Notes carry-over** — monthly notes auto-copied to next month's rent_schedule when generated
- **UPDATE_TENANT_NOTES intent** — separate workflow to edit permanent tenant notes ("update agreement for Raj")
- **Import reclassification** — `--preview-notes` flag on excel_import to classify Excel comments as permanent/monthly/ambiguous before import
- **5 new workflow tests** — payment snapshot, allocation confirm/cancel, collect rent snapshot, tenant notes CRUD

### Changed
- **Doc consolidation** — 20 docs → 12 (8 core + 4 planning/business). Merged ARCHITECTURE.md + SYSTEM_ARCHITECTURE.md into BRAIN.md. Merged DATA_STRATEGY.md into EXCEL_IMPORT.md. Moved PRICING/PRD/ROADMAP/FINANCIAL_VISION to subfolders.
- **BRAIN.md accuracy fixes** — table count 21→26, beds ~295→291, staff rooms 8→9, n8n references removed

### Fixed
- **rent_schedule auto-generation** — when payment logged for month without rent_schedule, row is now created with carry-over notes from previous month

---

## [1.10.0] — 2026-03-29 — Workflow Enhancements + 30 Tests

### Added
- **ADD_TENANT: food_preference step** — veg/non-veg/egg asked after gender, saved to DB
- **CHECKOUT: exit date collection** — receptionist enters actual exit date (was hardcoded to today)
- **CHECKOUT: deposit forfeiture** — notice after 5th = deposit forfeited with clear message to receptionist
- **LOG_EXPENSE: receipt photo** — asks for photo after description, allows skip
- **NOTICE QUERY: enhanced** — shows count, deposit/refund per tenant, forfeiture status
- **Intent: "how many notices"** — routes to QUERY_EXPIRING
- **30 workflow tests** — tests/test_workflow_flows.py covering all flows with edge cases

### Fixed
- **Payment+month intent clash** — "Raj paid 15000 upi march" now routes to PAYMENT_LOG (was REPORT)
- **Checkout Sheet update** — exit date passed to Google Sheet (was always today)
- **Media fields in pending** — media_id/type/mime now passed through resolve_pending_action

---

## [1.9.0] — 2026-03-29 — Excel Import Pipeline + Onboarding + Doc Cleanup

### Added
- **Excel import pipeline** — single parser (`clean_and_load.py :: read_history()`), DB import calls it. 283/283 rows, 0 skipped. DB == Sheet financials verified.
- **Onboarding system** — media intake (ID photo + selfie), admin approval flow (yes/no), food preference step, 15 steps total.
- **Deposit tracking** — ask advance paid, show remaining balance in tenant queries.
- **Smart activity/expense queries** — Groq-powered natural language answers from logs and expense records.
- **April tab** — with formulas (Total Paid = Cash+UPI, Balance = Rent-Paid, Status = IF).
- **Gender-based bed search** — find rooms with female/male occupant + empty bed.
- **Monthly/yearly reports** — cash/UPI/expenses/deposits breakdown + vacant beds by building.
- **Help menu** — example queries for every service.
- **Receptionist cheat sheet** — `docs/RECEPTIONIST_CHEAT_SHEET.md`.
- **1519 unit tests** — all passing.

### Fixed
- **No-show logic** — appear in EVERY month until checkin (was only checkin month). Per-month bed count.
- **Room lookup** — DB building is truth, Excel BLOCK ignored. UNASSIGNED dummy room for May no-shows.
- **Payment extraction** — uses `clean_num()` not `sn()`, handles messy cells like `19500/6500`.
- **Payments without rent status** — created even when rent status column is blank.
- **Name search precision** — exact first-word match before substring (Arun no longer matches Tarun).
- **Phone normalization** — +91 mismatch between pending and ctx.phone in onboarding approval.

### Docs
- Deleted stale: QUICKSTART.md, SHEET_WORKFLOW.md
- Removed n8n refs from DEPLOYMENT.md, SYSTEM_ARCHITECTURE.md, INTEGRATIONS.md
- Created `docs/EXCEL_IMPORT.md` — single workflow doc for Excel → Sheet → DB
- Updated CLAUDE.md — current architecture, data flow, docs index, end-of-day checklist
- Created global `~/.claude/CLAUDE.md` — behavioral rules for all projects

---

## [1.7.0] — 2026-03-15 — VPS Live + Bot Improvements

### Deployed
- **Bot live on VPS** — Hostinger KVM 1 (187.127.130.194). Domain: `api.getkozzy.com`. nginx reverse proxy. SSL via Let's Encrypt. systemd service `pg-accountant` (auto-restart).
- **LLM switched from Ollama → Groq** — `llama-3.3-70b-versatile` (cloud, free). n8n skipped entirely — Meta webhooks go directly to nginx → FastAPI.
- **Permanent WhatsApp token** — updated in `/opt/pg-accountant/.env`.

### Added
- **Bot identity: Artha** — `BOT_NAME = "Artha"` in `_shared.py`. First-time users get full intro. Returning users get short tagline every greeting.
- **Time-based greetings (IST)** — `time_greeting()`: Good morning (5–12), Good afternoon (12–17), Good evening (17+). "Good night" removed — night is a farewell only.
- **WiFi password intent** — `GET_WIFI_PASSWORD` + `SET_WIFI` intents. Tenants see floor-specific WiFi. Owners see all. Leads blocked.
- **WiFi data seeded** — `src/database/seed_wifi.py` stores full Thor + Hulk WiFi credentials in `properties.wifi_floor_map` JSONB. Thor: G/1–6/TOP/WS/GYM. Hulk: G/1–6.
- **Expense category auto-extraction** — `intent_detector._extract_entities()` extracts `category` from message for `ADD_EXPENSE` intent (electricity, water, internet, salary, plumbing, groceries, diesel, cleaning, security).

### Fixed
- `seed_wifi.py`: corrected import to use `get_session` + `init_engine`.

---

## [1.6.0] — 2026-03-14 — Accounting & P&L Scripts

### Added
- `scripts/bank_statement_extractor.py` — PDF bank statement extractor using word-coordinate layout parsing (fixes pdfplumber multi-line cell bug). Extracts transactions with UPI metadata: UTR, payer/payee UPI IDs, transaction type, keyword-based category. Outputs enriched Excel.
- `scripts/pnl_report.py` — Month-by-month P&L classifier. Keyword-based `EXPENSE_RULES` (15 categories, 100+ sub-rules) + `INCOME_RULES`. `MANUAL_ENTRIES` / `MANUAL_INCOME_ENTRIES` stubs for confirmed manual additions. Outputs `PnL_Report.xlsx` (Dec 2025–Mar 2026).
- `scripts/check_others.py` — Diagnostic: lists all unclassified transactions (Other Expenses) so owner can review and reclassify.
- `scripts/simple_pnl.py` — Lightweight P&L export (same rules, no formatting).
- `scripts/detailed_expense_report.py`, `scripts/export_salary_to_excel.py`, `scripts/validate_jan.py` — supporting utilities.

### Classification Rules Established
- `chandan865858` UPI → Maintenance & Repairs / Plumbing
- `sunilgn8834@okaxis` / "Dg rent" → Fuel & Diesel / DG Rent Generator (not Property Rent)
- Bharathi RTGS Rs 5L → Advance / Recoverable (recoverable hand loan, not an operating expense)
- Sri Lakshmi Chandrasekhar keyword tightened to `"lakshmi chandrasekhar"` — prevents `chandrasekhar1996krish` UPI payments being misclassified as Property Rent
- `MANUAL_ENTRIES = []` — never populated by assumption; only add with user-confirmed exact amounts

---

## [1.5.0] — 2026-03-14

### Added
- **`rooms.is_charged` + `rooms.is_staff_room` columns** (`models.py`): G05/G06 (THOR) marked `is_charged=False` (building owner gives free). Staff rooms excluded from tenant occupancy/vacancy counts.
- **Canonical room migration** (`src/database/migrate_rooms.py`): Upserts 166 canonical rooms across THOR + HULK. Deactivates non-canonical Room records from old Excel import.
- **Deposit tracking end-to-end**: `refunds` table now actively used. `RECORD_CHECKOUT` creates `Refund(status=pending)` on form completion. Staff confirms via WhatsApp "process" reply.
- **`CONFIRM_DEPOSIT_REFUND` intent** (`owner_handler.py`): Handles staff reply to checkout alert. Supports `process`, `deduct XXXX`, `deduct XXXX process`. Creates `Refund(status=processed)` + updates `CheckoutRecord.deposit_refunded_amount`.
- **Daily 9am checkout alert job** (`src/scheduler.py`): `_checkout_deposit_alerts()` — scans for `expected_checkout = today`, calculates deposit held + outstanding dues, sends settlement summary to assigned staff + all admin/power_user phones, creates `PendingAction(CONFIRM_DEPOSIT_REFUND)` per recipient.
- **Data verification scripts** (`scripts/`):
  - `occupancy_today.py` — current bed/room snapshot with THOR/HULK breakdown and occupancy %
  - `empty_rooms.py` — floor-wise empty/partial/full rooms, no-show bookings, exports CSV
  - `payment_breakdown.py` — payments by mode (cash/UPI/bank/cheque) and for_type (rent/deposit/booking)
  - `deposit_check.py` — 4 views: deposits received in period, by checkin date, total held, advance deposits

### Fixed
- **`resolve_pending_action` structural bug** (`owner_handler.py`): `RECORD_CHECKOUT` Q2–Q5 text-reply steps (yes/no/amount) were unreachable — function returned `None` before the step code. Fixed by moving all multi-step text flows before the numeric-choice guard.
- **17 future no_show tenancies** corrected to `active` — they had future checkin dates and paid deposits, not real no-shows.

### Changed
- `src/scheduler.py`: 4 → 5 jobs. New `checkout_deposit_alerts` runs at 09:00 IST daily.
- Net deposit formula: `SUM(payments.amount WHERE for_type='deposit') - SUM(refunds.amount WHERE status='processed')` = deposits currently held as liability.

---

## [1.4.0] — 2026-03-14

### Added
- **`src/whatsapp/gatekeeper.py`**: Smart router — maps `(role, intent)` → correct worker. Replaces flat `if role == "admin"` chain in `chat_api.py`. Owner-role users go to AccountWorker for financial intents, OwnerWorker for operational.
- **`src/whatsapp/handlers/account_handler.py`** (1,058 lines): AccountWorker — dedicated accounting persona. Owns 11 financial intents: `PAYMENT_LOG`, `QUERY_DUES`, `QUERY_TENANT`, `ADD_EXPENSE`, `QUERY_EXPENSES`, `REPORT`, `RENT_CHANGE`, `RENT_DISCOUNT`, `VOID_PAYMENT`, `ADD_REFUND`, `QUERY_REFUNDS`. Uses `Rs.` prefix, full due/paid/balance breakdowns, `property_logic.py` for all math.
- **`src/whatsapp/handlers/_shared.py`** (212 lines): 8 shared DB helpers used by both workers: fuzzy tenant search, disambiguation, room overlap check, pending action save. Extracted verbatim from owner_handler — zero logic change.

### Changed
- **`src/whatsapp/handlers/owner_handler.py`**: 2,595 → 1,434 lines. Financial handlers moved to `account_handler.py`. Shared helpers moved to `_shared.py`. Now operational intents only. Imports `_do_*` functions back from account_handler for `resolve_pending_action`.
- **`src/whatsapp/chat_api.py`**: 3-branch routing block replaced with single `reply = await route(intent, intent_result.entities, ctx, message, session)`.

---

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
