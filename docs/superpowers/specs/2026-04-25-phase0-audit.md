# Phase 0 Codebase Audit — 2026-04-25

Pre-migration audit. No code changed. Maps every file so Phase 1 (agent tool wrappers) knows what to preserve, wrap, and delete.

Total: **106 Python files** across `src/` + `services/` (including `__init__.py` files). 36,691 source lines.

---

## Section 1 — File Catalog

### `src/whatsapp/` — Bot core

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `chat_api.py` | ROUTER | 1205 | 12 | Entry point — rate-limit, dedup, pending resolution, LLM fallback. `_process_message_inner` is 771 lines — primary refactor target. |
| `intent_detector.py` | ROUTER | 893 | 4 | Regex intent classification (97% of traffic). `detect_intent()` + `_extract_entities()`. Unchanged in Phase 1. |
| `gatekeeper.py` | ROUTER | 73 | 1 | Routes (role, intent) → handler. Clean. Will gain agent path in Phase 1. |
| `role_service.py` | SERVICE | 178 | 3 | Phone → CallerContext (role, name). Pure DB lookup. Unchanged. |
| `webhook_handler.py` | SERVICE | 670 | 15 | `_send_whatsapp()`, `_send_whatsapp_template()`, `_fetch_media_bytes()`. Outbound WhatsApp API. Imported by many; do NOT refactor. |
| `media_handler.py` | UTILITY | 70 | 2 | `MEDIA_DIR` constant + `download_whatsapp_media()`. Thin wrapper. |
| `form_extractor.py` | UTILITY | 298 | 6 | Extracts structured data from free-text forms (checkin/checkout). |
| `response_formatter.py` | DEAD | 44 | 2 | `format_response()` and `format_help_message()` — zero imports found in active code. Superseded by handler-level formatting. |
| `reminder_sender.py` | SERVICE | 220 | 4 | `send_template()`, `send_reminder_text()`. Used by scheduler and reminder_router. |

### `src/whatsapp/handlers/` — Intent handlers

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `owner_handler.py` | HANDLER | 8117 | 77 | Operational intents. `resolve_pending_action` is 3554 lines — primary split target. Contains `_do_checkout`, `_do_add_tenant`, `_process_tenant_form`, `_query_vacant_rooms`. |
| `account_handler.py` | HANDLER | 2432 | 30 | Financial intents. `_single_month_report`, `_do_log_payment_by_ids`, `_payment_log` all >195 lines. Direct DB queries throughout. |
| `_shared.py` | UTILITY | 584 | 22 | Fuzzy search, disambiguation, choice formatting. Bot greeting templates. Accessed by both handlers. Mostly clean. |
| `tenant_handler.py` | HANDLER | 985 | 18 | Tenant self-service + onboarding stepper. `handle_onboarding_step` is 196 lines. |
| `update_handler.py` | HANDLER | 1025 | 19 | Field-level updates (rent, phone, gender, room). `resolve_field_update` is 122 lines. |
| `finance_handler.py` | HANDLER | 537 | 9 | Bank statement upload, P&L report, deposit match. `handle_deposit_match` 146 lines. Imported by `account_handler`. |
| `receipt_handler.py` | HANDLER | 724 | 15 | Media classification (receipt/expense/ID proof). `handle_receipt_upload` 133 lines. |
| `lead_handler.py` | HANDLER | 233 | 8 | Lead self-service (availability, pricing, visit booking). |
| `resolvers/onboarding.py` | HANDLER | 243 | 2 | Extracted from `resolve_pending_action` (Phase 2A, 2026-04-23). `resolve_approve_onboarding`, `resolve_confirm_checkin_arrival`. |

### `src/whatsapp/conversation/` — Pending-state framework

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `state.py` | SERVICE | 174 | 2 | `ConversationState` enum + `UserInput` dataclass + `parse()`. Clean API for structured input. |
| `memory.py` | SERVICE | 121 | 1 | `ConversationMemory` dataclass + `load()`. Loads pending + recent turns in one DB round-trip. |
| `router.py` | ROUTER | 114 | 3 | `@register` decorator dispatch table for (intent, state) pairs. Only 5 intents migrated so far. |
| `handlers/payment_log.py` | HANDLER | 158 | 4 | PAYMENT_LOG confirmation (new framework). Calls `_do_log_payment_by_ids`. |
| `handlers/checkout.py` | HANDLER | 113 | 3 | CHECKOUT confirmation (new framework). Calls `_do_checkout`. |
| `handlers/confirm_add_expense.py` | HANDLER | 100 | 2 | ADD_EXPENSE confirmation (new framework). Contains direct `session.execute` call. |
| `handlers/confirm_add_tenant.py` | HANDLER | 44 | 1 | ADD_TENANT confirmation stub (new framework). |
| `handlers/notice_void_overpay.py` | HANDLER | 88 | 6 | VOID overpayment notice confirmation (new framework). |

### `src/database/` — DB layer

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `models.py` | MODEL | 1376 | 0 | SQLAlchemy ORM — 26+ tables. Source of truth. Unchanged. |
| `migrate_all.py` | CONFIG | 1213 | 27 | Append-only migration runner. Do NOT modify existing entries. |
| `db_manager.py` | SERVICE | 213 | 16 | `get_db_session()`, async engine setup. |
| `validators.py` | SERVICE | 136 | 3 | Pre-write guards: `check_no_active_tenancy`, `check_tenancy_active`. |
| `field_registry.py` | SERVICE | 351 | 5 | Header lists + field metadata. Used by `gsheets.py`. |
| `excel_import.py` | SCRIPT | 513 | 12 | Excel → DB import. Run manually. Should live in `scripts/`. |
| `delta_import.py` | SCRIPT | 408 | 11 | Monthly delta import. Run manually. Should live in `scripts/`. |
| `dedup_check.py` | SCRIPT | 250 | 6 | Audit script for duplicate tenancies/payments. Run manually. Should live in `scripts/`. |
| `wipe_imported.py` | SCRIPT | 130 | 1 | Wipes L1+L2 data for re-import. Run manually. Should live in `scripts/`. |
| `seed.py` | SCRIPT | 142 | 1 | Seeds initial data. Run manually. |
| `seed_wifi.py` | SCRIPT | 176 | 1 | Seeds WiFi credentials. Run manually. |
| `schema.py` | MODEL | 148 | 0 | Pydantic response schemas (API layer). |
| `migrations/add_org_id_2026_04_19.py` | CONFIG | 71 | 1 | One-off migration (submodule). |

### `src/integrations/` — External APIs

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `gsheets.py` | SERVICE | 2384 | 50 | Google Sheets sync. All sheet write-back goes here. `_sync_tenant_all_fields_sync` (242 lines), `_add_tenant_sync` (230 lines), `_refresh_summary_sync` (196 lines). (50 top-level, ~5 nested) |

### `src/llm_gateway/` — LLM abstraction

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `claude_client.py` | SERVICE | 432 | 2 | Multi-provider LLM client (Ollama/Groq/Anthropic). Used for ~3% of traffic. Active in `chat_api`, `account_handler`, `owner_handler`. |
| `agents/conversation_agent.py` | SERVICE | 201 | 5 | PydanticAI agent — classifies intents + generates replies. Gated by `USE_PYDANTIC_AGENTS` flag. Will be Phase 1 primary entry point. |
| `agents/flexible_query.py` | SERVICE | 459 | 8 | Natural language DB query (freeform owner queries). Called from `chat_api`. |
| `agents/learning_agent.py` | SERVICE | 171 | 5 | Logs examples for few-shot retrieval. Called from `chat_api`. |
| `agents/models.py` | MODEL | 34 | 0 | `ConversationResult` Pydantic output model. |
| `agents/prompt_builder.py` | SERVICE | 127 | 1 | Builds system prompt from pg_config + examples. Used by `conversation_agent`. |
| `agents/tools.py` | SERVICE | 121 | 2 | `search_similar_examples()` — few-shot retrieval from DB. Used by `conversation_agent`. |
| `prompts.py` | SERVICE | 165 | 0 | Prompt string constants for `claude_client`. |

### `src/api/` — FastAPI routers

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `dashboard_router.py` | ROUTER | 557 | 10 | Web dashboard API. |
| `onboarding_router.py` | ROUTER | 1460 | 16 | Tenant onboarding form API. `_approve_session_impl` is 516 lines. |
| `reminder_router.py` | ROUTER | 234 | 6 | Manual reminder trigger API. |
| `sync_router.py` | ROUTER | 172 | 5 | DB → Sheet sync trigger API. |
| `v2/app_router.py` | ROUTER | 20 | 1 | PWA app router stub. |
| `v2/auth.py` | SERVICE | 56 | 1 | JWT auth for PWA. |

### `src/services/` — Business logic services

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `payments.py` | SERVICE | 281 | 5 | `log_payment()` — DB write + audit. Used by `account_handler`. |
| `room_occupancy.py` | SERVICE | 377 | 6 | `check_room_bookable()`, `beds_free_on_date()`, `get_room_future_reservations()`. |
| `occupants.py` | SERVICE | 244 | 7 | `find_occupants()`, `checkout_of()`. |
| `sheet_audit.py` | SERVICE | 471 | 15 | Sheet-vs-DB discrepancy checks. Called from scheduler. |
| `rent_schedule.py` | SERVICE | 54 | 2 | `prorated_first_month_rent()`, `first_month_rent_due()`. |
| `rent_status.py` | SERVICE | 42 | 1 | `compute_status()` — per-tenancy rent status. |
| `monthly_rollover.py` | SERVICE | 127 | 2 | `generate_rent_schedule_for_month()`. Called by `scripts/run_monthly_rollover.py`. |
| `audit.py` | SERVICE | 61 | 1 | `write_audit_entry()`. Used internally by `payments.py`. |
| `pdf_generator.py` | SERVICE | 165 | 2 | Generates tenant agreement PDFs. Used by `onboarding_router`. |

### `services/` (root-level, not under `src/`) — Core business logic

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `property_logic.py` | SERVICE | 185 | 9 | **Critical.** Rent proration, payment status, settlement calc, notice logic. Imported directly by handlers (`from services.property_logic import ...`). Not under `src/` — inconsistent placement. |

### `src/scheduler.py` — Cron jobs

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `scheduler.py` | SERVICE | 1031 | 14 | APScheduler jobs: rent reminders, checkout alerts, sheet audit. `_checkout_deposit_alerts` 154 lines. |

### `src/parsers/` — Bank statement parsers

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `dispatcher.py` | SERVICE | 82 | 2 | Routes file type → correct parser. |
| `bank_statement_parser.py` | SERVICE | 97 | 1 | Generic bank statement parser. |
| `base_parser.py` | SERVICE | 124 | 0 | Abstract base class. |
| `csv_parser.py` | SERVICE | 141 | 1 | CSV bank statement. |
| `pdf_parser.py` | SERVICE | 141 | 0 | PDF bank statement. |
| `phonepe_parser.py` | SERVICE | 102 | 0 | PhonePe-specific format. |
| `paytm_parser.py` | SERVICE | 117 | 0 | Paytm-specific format. |
| `upi_parser.py` | SERVICE | 81 | 0 | Generic UPI. |

### `src/rules/` — Classification rules

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `pnl_classify.py` | SERVICE | 226 | 1 | `classify_txn()` — used by `finance_handler`. |
| `merchant_rules.py` | SERVICE | 143 | 4 | Merchant name normalization. |
| `deduplication.py` | SERVICE | 106 | 5 | Transaction hash deduplication. |
| `categorization_rules.py` | SERVICE | 131 | 2 | Expense category classification. |

### `src/reports/` — Report generation

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `reconciliation.py` | SERVICE | 230 | 0 | Bank vs. rent reconciliation engine. Used from `main.py` admin endpoints. |
| `report_generator.py` | SERVICE | 128 | 0 | Generates HTML/Excel reports. |
| `excel_exporter.py` | SERVICE | 153 | 0 | Excel report export. |

### `src/dashboard/` — HTML dashboard

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `html_generator.py` | SERVICE | 216 | 1 | Generates HTML dashboard. |
| `cleanup.py` | UTILITY | 52 | 2 | Removes stale dashboard files. |

### `src/utils/` — Tiny utilities

| File | Category | Lines | Fns | Notes |
|---|---|---|---|---|
| `money.py` | UTILITY | 29 | 1 | `inr()` — formats Decimal as "Rs. 1,200". |
| `room_floor.py` | UTILITY | 29 | 1 | `floor_from_room()` — extracts floor from room number. |
| `inr_format.py` | UTILITY | 64 | 2 | Extended INR formatting helpers. |

---

## Section 2 — Design Flaws

### 2.1 Re-parsing in handlers (should use `conversation/state.py:parse()`)

The `state.py:parse()` function exists to centralize all text-to-structured-data conversion. These handler-level regex calls bypass it and duplicate its logic:

**`owner_handler.py` — 45+ inline regex calls** (sample):
- `owner_handler.py:983` — `re.search(r"\b(\d[\d,]+)\b", reply_text)` — amount extraction (duplicates `UserInput.parsed_amount`)
- `owner_handler.py:1143`, `1239`, `2156`, `2455` — same amount pattern repeated
- `owner_handler.py:3473`, `3703` — phone extraction from free text
- `owner_handler.py:4484-4485` — phone + room detection from positional form text
- `owner_handler.py:4461-4465` — field extraction from key:value form text
- `owner_handler.py:8039-8040` — `re.search(r"last\s+(\d+)\s+days?", raw)` — date range extraction

**`account_handler.py`**:
- `account_handler.py:1228` — `re.search(r'\b(20\d{2})\b', text)` — year extraction inside `_extract_year_from_text()`

**`update_handler.py`**:
- `update_handler.py:139` — amount extraction from description
- `update_handler.py:196` — phone extraction
- `update_handler.py:248/250` — gender detection
- `update_handler.py:916` — room number extraction

**`tenant_handler.py`**:
- `tenant_handler.py:74` — month name extraction (duplicated in several places)
- `tenant_handler.py:444-445` — date range patterns compiled at module level

**Impact:** Every disambiguation step re-parses the same reply rather than passing a `UserInput` struct.

---

### 2.2 Direct DB queries in handlers (should go through service layer)

Handler functions are making raw `session.execute()` / `session.scalar()` calls that should be in services:

**`owner_handler.py` — 98 direct DB query calls** (most concentrated in `resolve_pending_action`):
- `owner_handler.py:391-425` — room lookup + duplicate tenancy check inside checkin flow (should call `validators.check_no_active_tenancy` + `room_occupancy.check_room_bookable`). Note: `check_no_active_tenancy` is already imported at line 35 but never called — the inline check at lines 391–425 silently re-implements it.
- `owner_handler.py:799-801` — tenant lookup by phone (should be a service helper)
- `owner_handler.py:1265-1399` — expense category lookup, refund checks in checkout flow

**`account_handler.py` — 48+ direct DB query calls**:
- `account_handler.py:350-393` — duplicate payment check (should be `validators.check_no_duplicate_payment`)
- `account_handler.py:606-617` — payment lookup by ID (ad-hoc, not a service call)
- `account_handler.py:1802-1969` — `_single_month_report()` contains 18+ `session.scalar()` calls inline — all financial aggregation SQL; should be a dedicated report service
- `account_handler.py:2063-2132` — `_yearly_report()` repeats the same pattern

**`_shared.py` — 10 direct DB queries** (intentionally — this IS the shared DB helper layer; acceptable)

**`finance_handler.py`**:
- `finance_handler.py:220` — existing bank transaction dedup check inline
- `finance_handler.py:314-416` — pagination + tenant/income query inline

**`lead_handler.py`**:
- `lead_handler.py:45`, `164`, `220` — room/lead queries inline

**`conversation/handlers/confirm_add_expense.py:73`** — direct `session.execute` inside confirmation handler; breaks the service-layer contract of the new framework.

---

### 2.3 Functions > 80 lines (candidates for splitting)

Most critical:

| File | Function | Lines | Priority |
|---|---|---|---|
| `owner_handler.py` | `resolve_pending_action` | 3562 | CRITICAL — split into resolver modules (Phase 2A started) |
| `chat_api.py` | `_process_message_inner` | 771 | HIGH — merges rate-limit + pending + intent + LLM path |
| `onboarding_router.py` | `_approve_session_impl` | 520 | HIGH |
| `owner_handler.py` | `_do_add_tenant` | 233 | MEDIUM |
| `account_handler.py` | `_single_month_report` | 243 | MEDIUM — move DB queries to report service |
| `account_handler.py` | `_do_log_payment_by_ids` | 243 | MEDIUM — logic mixed with formatting |
| `gsheets.py` | `_sync_tenant_all_fields_sync` | 242 | MEDIUM |
| `onboarding_router.py` | `get_session_creation_form` | 331 | MEDIUM |
| `owner_handler.py` | `_process_tenant_form` | 191 | MEDIUM |
| `account_handler.py` | `_payment_log` | 195 | MEDIUM |
| `gsheets.py` | `_add_tenant_sync` | 230 | MEDIUM |
| `gsheets.py` | `_refresh_summary_sync` | 196 | LOW |
| `tenant_handler.py` | `handle_onboarding_step` | 196 | LOW |
| `scheduler.py` | `_checkout_deposit_alerts` | 154 | LOW |
| `owner_handler.py` | `_do_checkout` | 180 | LOW |
| `owner_handler.py` | `_query_vacant_rooms` | 158 | LOW |
| `account_handler.py` | `_do_rent_change` | 152 | LOW |

---

### 2.4 Duplicate logic across files

**Proration — 2 implementations:**
- `services/property_logic.py:41-76` — `calc_checkin_prorate()`, `calc_checkout_prorate()`, `_prorate()` (canonical)
- `owner_handler.py:4015` — `_calc_prorate(amount, day_of_month, days_in_month)` — local reimplementation. Should be deleted; calls already import `calc_checkin_prorate` from `property_logic`.

**Notice last-day — thin wrapper (acceptable):**
- `owner_handler.py:4010` — `_calc_notice_last_day()` is explicitly a "thin alias → services.property_logic.calc_notice_last_day". Acceptable; documents intent.

**`property_logic.py` placement inconsistency:**
- Lives at `services/property_logic.py` (root-level `services/`) NOT under `src/services/`.
- All three handlers import it as `from services.property_logic import ...` — works but inconsistent with the rest of the codebase which uses `from src.services.*`.

**Amount extraction — repeated across 10+ handler sites:**
- Pattern `re.search(r"\b(\d[\d,]+)\b", reply_text)` appears in `owner_handler.py` at lines 983, 1143, 1239, 2156, 2455 and in `update_handler.py:139`.
- All should use `UserInput.parsed_amount` from `conversation/state.py:parse()`.

**Phone normalization — called inline vs. via role_service:**
- `owner_handler.py` uses `_normalize_phone()` (imported from `role_service`) in most places, but also has inline `re.search(r'\d{7,15}', ...)` at lines 3473, 3703, 6837.

---

## Section 3 — Deletion Candidates

These files are confirmed DEAD (zero imports in `src/` and `main.py`) or confirmed as belonging in `scripts/` not `src/`:

### Confirmed DEAD (safe to delete after migration)

| File | Evidence |
|---|---|
| `src/whatsapp/response_formatter.py` | Zero imports found. `format_response()` and `format_help_message()` unused. Superseded by handler-level text formatting. |

### Misplaced scripts (should live in `scripts/`, not `src/`)

These are run manually via `python -m src.database.*` but have no callers in the application runtime. Move to `scripts/` or leave as-is — do NOT delete:

| File | Evidence |
|---|---|
| `src/database/excel_import.py` | No runtime imports; invoked as `python -m src.database.excel_import --write` |
| `src/database/delta_import.py` | No runtime imports; invoked manually |
| `src/database/dedup_check.py` | No runtime imports; audit script |
| `src/database/wipe_imported.py` | No runtime imports; destructive admin tool |
| `src/database/seed.py` | No runtime imports; one-time seed |
| `src/database/seed_wifi.py` | No runtime imports; one-time seed |

### Low-usage / stale (verify before deleting)

| File | Status | Notes |
|---|---|---|
| `src/api/v2/app_router.py` | VERIFY | Only 20 lines; `app_router` registered in `main.py:144` but router has minimal routes. PWA tech-debt per `project_pwa_tech_debt.md`. |
| `src/api/v2/auth.py` | VERIFY | Stub JWT auth for PWA. Used only by `app_router.py`. If PWA is deferred, both v2 files are dead. |
| `src/dashboard/html_generator.py` + `cleanup.py` | VERIFY | Used by `report_generator.py` which is used only from `main.py` admin endpoints. If those endpoints are removed, both die. |

### Internal duplication to clean up (not deletion, but consolidation)

| Item | Action |
|---|---|
| `owner_handler.py:4015 _calc_prorate()` | Delete — already imports canonical `calc_checkin_prorate` from `property_logic` |
| `services/property_logic.py` root placement | Move to `src/services/property_logic.py` and update 3 import sites (Phase 1 prerequisite) |

---

## Summary for Phase 1

**Wrap as tools (clean, single-responsibility):**
- `services/property_logic.py` — all functions are pure math, ideal tool candidates
- `src/services/payments.py:log_payment()` — confirmed clean service function
- `src/services/room_occupancy.py:check_room_bookable()`, `beds_free_on_date()`
- `src/services/occupants.py:find_occupants()`, `checkout_of()`
- `src/database/validators.py` — all 3 guard functions
- `src/services/rent_schedule.py:first_month_rent_due()`
- `src/whatsapp/handlers/account_handler.py:_do_log_payment_by_ids()` — already called by conversation framework
- `src/whatsapp/handlers/owner_handler.py:_do_checkout()` — already called by conversation framework

**Needs refactor before wrapping:**
- `account_handler.py:_single_month_report()` — 18+ inline DB queries must move to a report service first
- `owner_handler.py:resolve_pending_action` — must finish Phase 2A split before touching
- `chat_api.py:_process_message_inner` — agent path must be carved out cleanly

**Leave unchanged in Phase 1:**
- `src/database/models.py` — MODEL, unchanged
- `src/whatsapp/intent_detector.py` — regex works, only add agent fallback path
- `src/integrations/gsheets.py` — complex but stable; Phase 1 calls it via existing API
- `src/whatsapp/webhook_handler.py` — HTTP send layer, stable
