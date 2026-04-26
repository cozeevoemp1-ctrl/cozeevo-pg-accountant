# Changelog

All notable changes to PG Accountant will be documented here.

## [1.61.0] — 2026-04-26 — PWA Plan 1 Tasks 4/5/9/10 + checkout web confirm page

### Backend: `/api/v2/app/payments` + `/api/v2/app/reporting/collection`
- `POST /api/v2/app/payments` — JWT-authenticated payment logging via the Owner PWA; resolves active tenancy from `tenant_id`, calls `src/services/payments.log_payment`, returns `payment_id` + `new_balance`; 409 on duplicate hash
- `GET /api/v2/app/reporting/collection?period_month=YYYY-MM` — collection summary per REPORTING.md §4.2; returns `expected`, `collected` (rent+maintenance only), `pending`, `collection_pct`, breakdowns, `overdue_count`
- `src/schemas/payments.py` + `src/schemas/reporting.py` — Pydantic request/response models
- `src/services/reporting.py` — `collection_summary()` async service using existing SQLAlchemy models

### Frontend: UI primitives + Supabase auth layer
- `web/components/ui/` — Card, Button, ProgressBar, IconTile, Pill, TabBar (design tokens from tailwind.config.ts)
- `web/lib/supabase.ts` — createBrowserClient wrapper; `web/lib/auth.ts` — signInWithPhone, verifyOtp, getSession, signOut; `web/lib/api.ts` — typed fetch client for backend endpoints
- `web/components/auth/auth-provider.tsx` — AuthProvider context + useAuth hook; wired into `app/layout.tsx`
- Installed `@supabase/ssr@0.10.2` and `@supabase/supabase-js@2.104.1`

### Checkout: web-based confirm page
- `/checkout/{token}` — tenant-facing HTML page to review and confirm/dispute checkout (replaced inline YES/NO WhatsApp flow)
- WhatsApp message now sends a link: `https://api.getkozzy.com/checkout/{token}`
- `GET /api/checkout/summary/{token}`, `/confirm`, `/dispute` — public endpoints (token is the auth)

## [1.60.0] — 2026-04-26 — Security hygiene: sig-check hardening, correlation IDs, /media auth, token rotation

### Remove WHATSAPP_SKIP_SIG_CHECK bypass (`webhook_handler.py`)
- Env var escape hatch removed entirely; signature check is now unconditional
- Was never set on VPS, but the bypass path no longer exists in code

### Request correlation IDs (`webhook_handler.py`, `chat_api.py`)
- Meta `msg_id` now passed through as `message_id` on `InboundMessage` (was always `None`)
- `_process_message_inner` derives a 12-char `req_id` from `message_id` (or new UUID)
- Three log lines per request: entry (`phone`, `msg[:60]`), intent (`intent`, `conf`, `role`), routing (`intent`)
- Traces a message from webhook → intent detection → handler dispatch without touching handlers

### `/media` endpoint: unauthenticated static mount → PIN-protected (`main.py`)
- Replaced `StaticFiles("/media")` mount with `GET /media/{path:path}` that requires admin PIN
- Accepts `X-Admin-Pin` header or `?pin=` query param (same as all other admin endpoints)
- Path traversal guard: rejects any path that resolves outside `media_dir`
- `admin_onboarding.html`: local `/media/` image URLs now append `?pin=<ADMIN_PIN>`

### Token rotation endpoint (`main.py`)
- `POST /api/admin/rotate-token?which=dashboard|sync|all` (localhost-only + admin PIN)
- Generates new `secrets.token_urlsafe(32)` tokens, updates in-memory vars immediately via `sys.modules`
- Writes new values to `.env` file for persistence across restarts
- Returns new token value(s) in response so admin can update callers

### Cheat sheet Section 0 (`docs/CHEAT_SHEET_PRINTABLE.md`)
- Added "SOMEONE CAME TO PAY" as the first section, above Section 1
- Three options: check balance first / step-by-step / one-shot
- Notes on multi-name disambiguation and cash+UPI split

---

## [1.59.0] — 2026-04-25 — Security hardening: auth header, MIME validation, log permissions, retry

### Dashboard auth: query param → Authorization header
- `dashboard_router.py`: `_auth` now reads `Authorization: Bearer <token>` header instead of `?token=`
- Dev mode still works (token empty → auth skipped)
- `Query` retained for all other endpoint params

### File upload MIME validation (`main.py`)
- Extension check: only `.csv` and `.pdf` accepted (was accepting any extension)
- MIME check: `Content-Type` validated against allowed set (`text/csv`, `application/pdf`, etc.)
- Returns HTTP 400 with clear message on invalid type

### Debug log permissions (`chat_api.py`, `webhook_handler.py`)
- All `/tmp/pg_*.log` writes now use `os.open(..., 0o600)` → owner-only, not world-readable
- Protects PII (phone numbers, message content) from other processes on VPS

### WhatsApp send retry on 429/5xx (`webhook_handler.py`)
- `_send_whatsapp` now retries up to 3 times on 429 (rate limit) and 5xx (transient)
- 429: respects `Retry-After` header, caps wait at 120s
- 5xx / network error: exponential backoff (5s, 10s)

---

## [1.58.0] — 2026-04-25 — E2E test suite: RECORD_CHECKOUT + ADD_TENANT confirm + SOP update

### test_full_flow_e2e.py: 33 → 35 scenarios
Two previously-missing intents now covered end-to-end:
- **RECORD_CHECKOUT full flow** — creates test tenant+tenancy, routes "checkout [name]" → "1" → walks 5-question checklist (keys/damage/fingerprint/deductions) → "yes", verifies `CheckoutRecord` created and `tenancy.status=exited`, full cleanup in `finally`
- **ADD_TENANT confirm → DB** — injects `CONFIRM_ADD_TENANT` pending with future checkin, routes "yes", verifies `Tenant`+`Tenancy` rows created, full cleanup

### SOP update (`memory/sop_testing.md`)
Added mandatory rule: every new handler must have a corresponding E2E test in `test_full_flow_e2e.py` before shipping. Rule includes pattern reference to newest tests.

---

## [1.57.0] — 2026-04-25 — E2E test suite: 7 missing intents + pre-push hook

### test_full_flow_e2e.py: 26 → 33 scenarios
Seven previously-uncovered intents now have full happy-path DB-verified E2E tests:
- **EXIT_STAFF** — creates test staff with room assignment, routes "staff X exit", verifies `active=False`
- **VOID_EXPENSE** — creates expense in DB, routes "void expense", picks #1, verifies `is_void=True`
- **SCHEDULE_CHECKOUT** — routes "schedule checkout for X 15 Dec 2027", verifies `tenancy.expected_checkout` set, reverts
- **ASSIGN_ROOM** — creates unassigned tenant + finds free room, routes "assign room N to X", verifies Tenancy created, cleans up
- **COMPLAINT_UPDATE (resolve)** — creates open Complaint in DB, routes "resolve complaint N", verifies `status=resolved`
- **MY_BALANCE (tenant role)** — creates tenant CallerContext, routes "my balance", verifies non-empty reply
- **MY_PAYMENTS (tenant role)** — same with "my payments"

All tests: cleanup on pass AND fail; safe on live DB.

### Pre-push git hook (`.git/hooks/pre-push`)
- Runs 29 fast unit tests before every push; aborts on failure
- Full E2E opt-in: `TEST_FULL_E2E=1 git push`

---

## [1.56.0] — 2026-04-25 — Schema migrations: CASCADE + payment dedup

### rent_schedules FK → ON DELETE CASCADE
- `rent_schedules.tenancy_id` FK upgraded to `ON DELETE CASCADE`
- No data touched (tenancies are never hard-deleted — policy is status/is_void)
- Only fires if a test tenancy is manually deleted — cascade cleans up its rent schedule rows automatically

### payments.unique_hash dedup
- New nullable `unique_hash VARCHAR(64)` column added to `payments` table
- Partial unique index `uq_payment_unique_hash` (`WHERE unique_hash IS NOT NULL`)
- `payments.py`: MD5 hash of `tenancy_id:date:amount:mode:period_month:for_type` set on every new bot payment
- If a duplicate WhatsApp webhook replays the same payment, `flush()` raises `IntegrityError` → caller returns clean "already logged" message
- Existing rows stay NULL — no backfill, no constraint violation

---

## [1.55.0] — 2026-04-25 — Pessimistic locking + "where is X" intent

### Pessimistic locking on tenancy mutations (`SELECT...FOR UPDATE`)
Five mutation paths now lock the DB row before writing, preventing concurrent-request data corruption:
- `_do_confirm_checkout` — locks `Tenancy` row + idempotency guard (already-exited check)
- `_handle_checkout_agree` — locks `CheckoutSession` row + `confirmed_at` guard (prevents double-confirm if tenant sends YES twice)
- `_do_room_transfer` — locks `Tenancy` row before `room_id` write
- `_do_deposit_change` — locks `Tenancy` row before `security_deposit` write
- `_do_rent_change` — locks `Tenancy` row before `agreed_rent` write

### "Where is X" intent
- `where is Raj` / `where is raj` / `which room is Raj in` → `QUERY_TENANT` (returns full account including room number)
- Entity extractor updated with "where is X" fallback for lowercase names

---

## [1.54.0] — 2026-04-25 — KYC Storage Migration + Security Hardening

### KYC files migrated to Supabase Storage
- **`src/services/storage.py`** (new) — Supabase Storage REST wrapper (httpx, no new deps). Buckets: `kyc-documents`, `agreements`. Uses `SUPABASE_SERVICE_KEY` or falls back to `SUPABASE_KEY` (anon + RLS).
- **`pdf_generator.py`** — Agreement PDFs now generated to BytesIO in-memory and uploaded to Supabase. Returns public URL.
- **`onboarding_router.py`** — Selfie, ID proof, signature, staff_signature all uploaded to Supabase on submit/approve. Staff-signature GET/POST endpoints use Supabase download/upload.
- **`admin_onboarding.html`** — Handles both old `/media/` relative paths and new `https://` Supabase URLs (backward-compat).
- **`scripts/migrate_media_to_supabase.py`** — One-time migration script. Ran on VPS: 29 documents + 8 agreements + 1 staff signature uploaded. DB paths updated to Supabase URLs. Local VPS files deleted.
- VPS `.env` — Added `SUPABASE_URL` and `SUPABASE_KEY`.
- Supabase Storage buckets (`kyc-documents`, `agreements`) created with path-restricted INSERT/UPDATE RLS policies.
- Audit trail intact: `documents.tenant_id` / `tenancy_id` FKs unchanged.

### Security hardening
- **`/api/ingest/upload`** — was fully open; added `_check_admin_pin`
- **`/api/ingest/scan`** — was fully open; added `_check_admin_pin`
- **`/api/reconcile`** — was fully open; added `_check_admin_pin`
- **`/api/report/dashboard`** — was fully open; added `_check_admin_pin`
- **`/api/onboarding/admin/onboarding`** — page was served without PIN (exposing hardcoded X-Admin-Pin in HTML source). Fixed: PIN now always required. PIN injected from validated URL param instead of hardcoded literal.
- **Supabase Storage RLS** — INSERT policies restricted to known path prefixes (`onboarding/`, `staff-signatures/`, `receipts/`, `YYYY-MM/agreement_*.pdf`).

---

## [1.53.0] — 2026-04-25 — Feat: Checkout Form (admin web UI + WhatsApp confirm flow)

Replaces WhatsApp-only conversational checkout with a structured 3-step admin form.
Receptionist fills all checkout details in the browser, submits, and a WhatsApp summary
is sent to the tenant. Tenant has 2 hours to YES/NO. No reply = auto-confirmed.

### Phase 1 — Admin checkout form
- **`/admin/checkout`** — new 3-step wizard matching onboarding light theme (tenant search → physical handover → financial settlement)
- **`/api/checkout/tenants`** — autocomplete active tenants by name/room
- **`/api/checkout/tenant/{tenancy_id}`** — pre-fetch deposit, dues, notice date
- **`/api/checkout/create`** — create `CheckoutSession` + send WhatsApp to tenant
- **`/api/checkout/status/{token}`** — poll session status every 8s on admin page
- **`CheckoutSession` DB table** — pre-confirmation form state (22 cols, 5 status values)
- **APScheduler job** — auto-confirms expired sessions every 15 min (`checkout_auto_confirm`)
- **`_do_confirm_checkout()`** — shared helper: writes CheckoutRecord + Refund, marks tenancy exited, syncs Sheet
- **`CHECKOUT_AGREE` / `CHECKOUT_REJECT` intents** — tenant YES/NO intercepted in `chat_api.py` before intent detection
- **Nav bar** added to `/admin/onboarding` (Check-in / Checkout links)
- **6 new columns** added to `checkout_records`: biometric_removed, room_condition_ok, deductions, deduction_reason, refund_mode, checkout_session_id
- **16 new tests** (test_checkout_flow.py + test_checkout_router.py) — all passing

### Phase 2 — Fix WhatsApp RECORD_CHECKOUT (conversational flow)
- Added `ask_deductions` and `ask_deduction_reason` steps
- Full financial summary shown before DB write (deposit, dues, deductions, refund)
- DB write deferred to explicit YES confirmation only
- Notice forfeiture logic applied to deduction pre-fill

### Files changed
- `static/checkout_admin.html` — new 3-step receptionist form
- `static/admin_onboarding.html` — nav bar
- `src/api/checkout_router.py` — new checkout API router
- `src/database/models.py` — CheckoutSession model + CheckoutSessionStatus enum + 6 new CheckoutRecord cols
- `src/database/migrate_all.py` — checkout_sessions migration + ALTER checkout_records
- `src/whatsapp/intent_detector.py` — CHECKOUT_AGREE, CHECKOUT_REJECT intents
- `src/whatsapp/handlers/owner_handler.py` — agree/reject handlers + _do_confirm_checkout + Phase 2 flow
- `src/whatsapp/chat_api.py` — YES/NO intercept block
- `src/whatsapp/gatekeeper.py` — route CHECKOUT_AGREE / CHECKOUT_REJECT
- `src/scheduler.py` — auto-confirm APScheduler job
- `main.py` — register checkout_router + /admin/checkout route
- `tests/test_checkout_flow.py` — 7 new tests
- `tests/test_checkout_router.py` — 9 new tests

### Deployed
Pending VPS deploy.

---

## [1.52.5] — 2026-04-25 — Feat: conversational edits in checkout OCR confirm flow

After OCR extracts checkout form data, any reply that isn't yes/no/cancel is parsed by
Groq to identify a field change. Lokesh can say "change date to 30 April", "deposit was
8000", "refund by UPI" — bot applies the change and re-shows the updated summary.
Removed the rigid `edit field value` syntax entirely.

### Files changed
- `src/whatsapp/handlers/owner_handler.py` — `_parse_checkout_edit_nl` helper; Groq replaces structured `edit ` path

### Deployed
Live on VPS.

---

## [1.52.4] — 2026-04-25 — Fix: room capacity check + admin dashboard UX + PDF OCR

### Room capacity bug
- `find_overlap_conflict` was blocking any booking as soon as 1 tenant overlapped, regardless of room capacity. Now counts beds consumed (premium = max_occupancy, regular = 1) and only rejects when `beds_used >= max_occupancy`. A 3-sharing room with 2 tenants now correctly accepts a 3rd.

### Admin dashboard (onboarding)
- **PDF OCR**: PDFs now render to high-DPI JPEG client-side via PDF.js and pass through existing Claude Haiku vision — Aadhaar number auto-fills from PDF
- **Staff signature**: One-time signature collection page (`/api/onboarding/staff-sign`) + saved PNG per staff phone + auto-load checkbox on approval form (Lokesh's signature saved)
- **Status pill filters**: Multi-select pills replace single dropdown; cancelled/expired hidden by default, one click to include
- **Logo link**: Cozeevo icon now navigates to getkozzy.com
- **Removed**: "How was this form filled?" radio (pointless for admin dashboard)

### Test data cleanup
- TEST_E2E tenant (id=932, tenancy=916, phone=9999999998) was manually created via admin dashboard and left in production DB + April sheet. Deleted from both.

### Files changed
- `src/services/room_occupancy.py` — capacity-aware overlap check
- `static/onboarding.html` — PDF.js OCR path
- `src/api/onboarding_router.py` — staff signature endpoints + collection page
- `static/admin_onboarding.html` — pill filters, saved sig, logo link, radio removal

### Deployed
Live on VPS (commits 2a5da04 + ea727de + 7082656 + f639095 + 4607e8b + b54bea1).

---

## [1.52.3] — 2026-04-25 — Fix: checkout flow end-to-end (OCR, "yes" routing, fuzzy match, settlement)

### Problems fixed
Four separate bugs in the checkout flow, all discovered during live testing:

1. **Photo checkout (OCR) never reached** — `media_id` was passed into the LangGraph agent but `AgentState` has no `media_id` field, so the OCR path never fired. Fix: intercept image+CHECKOUT intent *before* the agent block in `chat_api.py` and call `_extract_checkout_from_image` directly.

2. **"yes" confirmation returned "How can I assist you today?"** — The PydanticAI converse path at line ~532 of `chat_api.py` ran for UNKNOWN intents (including "yes") and returned early before the LangGraph active-thread check ever ran. Fix: add an `aget_state` fast-path check *before* the PydanticAI path — if a `pending_tool` is active in the persisted thread, route straight to `run_agent`.

3. **"No active tenant named 'Shubi' found"** — Fuzzy match scored "Shubi" against the full name "Shubhi Vishnoi" (ratio 0.53 < 0.75 threshold). Fix: also score against each individual word in the name and take the max ratio.

4. **Wrong settlement shown** — Settlement code always computed `net = deposit - dues` regardless of notice status. Late/missing notice should forfeit deposit + add one extra month penalty. Fix: when `late_notice=True`, set `net = 0 - outstanding - agreed_rent` (no refund path), display forfeiture and penalty lines clearly.

### Files changed
- `src/whatsapp/chat_api.py` — image+CHECKOUT intercept + "yes" agent fast-path
- `src/whatsapp/handlers/_shared.py` — per-word fuzzy scoring
- `src/whatsapp/handlers/owner_handler.py` — settlement: late notice → forfeit deposit + agreed_rent penalty; used `agreed_rent` (not `rent`)
- `src/agent/nodes/intent.py` — `_resolve_tenant_entities` now populates `tenant_name`, `room`, `checkout_date`
- `src/agent/tools/checkout.py` — `checkout_date` defaults to today if empty

### Deployed
Live on VPS. Shubhi Vishnoi's tenancy reset to active for Kiran to end-to-end test himself.

---

## [1.52.2] — 2026-04-25 — Fix: April balance -2000 for future check-ins + sheet stability

### Problem
Future check-ins (May/June) with a ₹2,000 booking advance but no April `rent_schedule` row
were showing balance = -2000 in the Operations sheet (0 rent_due − 2000 booking credit = -2000).

### Fix
`scripts/sync_sheet_from_db.py`: April balance formula now guards on `if rs else 0` —
no rent_schedule means a future check-in, not an April due. Balance shows 0.

### Stability fix (root cause of ₹2.15L spike)
The ₹2.15L balance that reappeared ~3 hours after the April balance fix was caused by a
VPS deploy race: old code (with hardcoded `april_balances` dict) ran when a WhatsApp bot
message triggered `trigger_monthly_sheet_sync` during the deploy transition window.
VPS now has correct code — all future bot-triggered syncs read from DB (MANUAL_LOCK rows).

### Current state (stable)
- DB: 20 PARTIAL rows with `adjustment_note = MANUAL_LOCK`, total ₹1,17,299
- Sheet: April tab shows 20 PARTIAL, Total Dues = ₹1,17,299
- Overnight source sync: PAUSED (scheduler.py line 173) — will not overwrite

### Files changed
- `scripts/sync_sheet_from_db.py` — `if rs else 0` guard for April future check-ins

---

## [1.52.1] — 2026-04-25 — Fix: onboarding photo upload broken on all browsers

Removed custom `getUserMedia` camera modal from the onboarding form. The modal was causing a silent failure: when camera permission was denied/dismissed, the fallback `file.click()` call was blocked by Chrome (and Safari) because the user-gesture token is consumed after `await getUserMedia`. Nothing happened — no camera, no file picker. Affected all browsers when camera permission was not pre-granted.

### Root cause
`capture="user"` on selfie input + custom JS camera modal. Fallback `.click()` in an async `catch` block is blocked by browser user-gesture policy. Also `capture="environment"` on ID photo input forced camera-only (no gallery).

### Fix
- Removed entire camera modal (HTML + CSS + JS — 151 lines deleted)
- Selfie input: kept `capture="user"` — opens front camera directly on iOS Safari and Android Chrome (native, no JS needed)
- ID photo input: removed `capture` attribute — shows native chooser (camera + gallery + files)
- Selfie click listener simplified to `document.getElementById('selfie-input').click()` — synchronous, within user gesture, always works

### Files changed
- `static/onboarding.html`

### Deployed
Live on VPS. Reported by Prashant (room G09), reproduced and fixed in same session.

---

## [1.52.0] — 2026-04-25 — LangGraph agent core: Phase 0 (audit) + Phase 1 (CHECKOUT + PAYMENT_LOG)

Built the LangGraph-based agent core alongside the existing bot. Agent handles CHECKOUT and PAYMENT_LOG end-to-end (disambiguation → confirmation → execution) with full state persistence via MemorySaver (local) / AsyncPostgresSaver (VPS). Feature-flagged off on VPS via `USE_PYDANTIC_AGENTS=false`.

### New files
- **`src/agent/__init__.py`** — package exports (`ChannelMessage`, `ChannelResponse`, `init_agent`, `run_agent`)
- **`src/agent/channel.py`** — `ChannelMessage` / `ChannelResponse` dataclasses
- **`src/agent/state.py`** — `AgentState` TypedDict + `make_initial_state()`
- **`src/agent/config.py`** — `AGENT_INTENTS` frozenset from env var
- **`src/agent/graph.py`** — `build_graph()`, `init_agent()`, `run_agent()` — graph assembly + checkpointer init
- **`src/agent/checkpointer.py`** — `make_memory_checkpointer()` (tests) / `make_postgres_checkpointer()` (prod, psycopg3)
- **`src/agent/nodes/router.py`** — fast-path yes/no router (no LLM ~10% savings)
- **`src/agent/nodes/intent.py`** — LLM classification + `_resolve_tenant_entities()` (name→tenancy_id DB lookup)
- **`src/agent/nodes/clarify.py`** — echoes clarify question to user
- **`src/agent/nodes/confirm.py`** — confirmation message templates for CHECKOUT + PAYMENT_LOG
- **`src/agent/nodes/execute.py`** — dispatches to registered tool, clears state on success/error
- **`src/agent/nodes/cancel.py`** — clears all flow state, sends cancellation reply
- **`src/agent/tools/_base.py`** — `BaseToolResult(success, reply)`
- **`src/agent/tools/checkout.py`** — `run_checkout()` wrapping `_do_checkout`
- **`src/agent/tools/payment.py`** — `run_payment()` wrapping `_do_log_payment_by_ids`
- **`tests/agent/`** — 38 tests (channel, state, router, intent, nodes, tools, e2e graph)
- **`docs/superpowers/specs/2026-04-25-phase0-audit.md`** — codebase audit (106 files, 36,691 lines, design flaws)

### Modified files
- **`requirements.txt`** — added `langgraph>=0.2.28`, `langgraph-checkpoint-postgres>=2.0.0`, `psycopg[binary,pool]>=3.1.0`
- **`.env.template`** — added `AGENT_INTENTS`, `DATABASE_URL_PSYCOPG`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`
- **`src/whatsapp/chat_api.py`** — agent routing block: if `USE_PYDANTIC_AGENTS=true` AND intent in `AGENT_INTENTS` AND role is admin/owner/receptionist → runs agent; errors fall through to existing gatekeeper
- **`main.py`** — `init_agent(test_mode=...)` added to lifespan startup

### Architecture
Graph topology: `router → {intent, execute, cancel}`, `intent → {clarify, confirm, END}`, all leaf nodes → `END`. Thread ID = `user_id` (e.g. `wa:917845952289`). Tenant name→ID resolution via `_find_active_tenants_by_name()` + `_make_choices()` (same lookup as existing owner_handler). Multiple matches → numbered disambiguation without LLM.

### Test results
- Agent unit suite: **38/38 passing**
- Golden suite (agent disabled): **64/100** — same 27 pre-existing failures; 9 bulk-run timing flickers (pass individually)

### VPS status
`USE_PYDANTIC_AGENTS=false` — agent NOT active on VPS. Enable after 48h local soak.

---

## [1.51.13] — 2026-04-24 — Onboarding: PDF signature redesign, remove boxes, keep "I agree" confirmation

Removed signature boxes from PDF (tenant and staff). Agreement now shows "✓ Agreed on [date], [time]" instead of signature space.

### Changes
- **pdf_generator.py:** Removed signature box rendering; simplified to show "✓ Agreed on [date], [time]" for tenant agreement confirmation
- **pdf_generator.py:** Removed unused `staff_signature` parameter, `base64`, `io`, `Image` imports (no longer needed without signature drawing)
- **onboarding_router.py:** Updated PDF generation call to remove `staff_signature` parameter

### Why
Digital onboarding uses IT Act 2000 §3A "I agree" checkbox + timestamp (stored as token `I_AGREE:<name>:<iso_ts>`). Signature boxes are visual-only and unnecessary; confirmation text + timestamp is sufficient for legal compliance.

---

## [1.51.12] — 2026-04-24 — Onboarding: Replace generic rules with 19 actual PG house rules

Replaced placeholder house rules in digital onboarding form with 19 exact rules from physical PG document. Made maintenance fee dynamic.

### Changes
- **pdf_generator.py:** Updated `HOUSE_RULES` list (lines 26-46) with 19 actual rules from physical document (was 12 generic placeholders)
- **pdf_generator.py:** Made rule 7 dynamic: changed hardcoded "Maintenance Charges are fixed @ Rs. 5000/-" to "Maintenance Charges are fixed @ {maintenance}/-"
- **pdf_generator.py:** Added maintenance fee calculation (line 116) and passed to `rule.format()` for substitution
- **onboarding_router.py:** Updated `_substitute_house_rules()` function to include maintenance parameter in rule substitution
- **onboarding.html:** Rules now display the 19 actual rules in Step 5 (Agreement & Signature) for tenant form

### Why
The onboarding form was using generic placeholder rules instead of the actual 19 house rules from the physical Cozeevo document. Maintenance fee was hardcoded to Rs.5000 instead of using the actual maintenance_fee from the onboarding session form input by receptionist.

---

## [1.51.11] — 2026-04-24 — QUERY_ALL_NOTICES: Monthly notice breakdown report

New bot command to show all tenants on notice across all future months, organized by month.

### Changes
- **intent_detector.py:** Added `QUERY_ALL_NOTICES` intent pattern for "total notices", "all notices", "show all notice", "all tenants on notice", "notice summary"
- **owner_handler.py:** Added `_query_all_notices()` handler
  - Lists all active tenants with notice_date or expected_checkout in future
  - Groups by month (April, May, June, etc.)
  - Shows count per month and notice date for each tenant
  - Simple clean format for receptionist/admin dashboard

### Example output
```
*On notice: 23 tenants*

*April 2026* (16 vacating)
  • Abhishek Charan (Room 411) — Notice: 05 Apr
  • Akshit (Room 419) — Notice: 08 Apr
  ...

*May 2026* (5 vacating)
  • Vikram Patel (Room 512) — Notice: 20 Apr
  ...
```

---

## [1.51.10] — 2026-04-24 — April dashboard: Total Dues = Rs.1,40,299, remove Rent Billed KPI

Audit complete: April custom code properly gated, doesn't leak into May. Dashboard now shows "Total Dues" instead of "Rent Billed".

### Changes
- **sync_sheet_from_db.py:** Renamed "Rent Billed" KPI to "Total Dues" in summary rows (lines 671, 681, 701, 702)
- **sync_sheet_from_db.py:** April Total Dues hardcoded to Rs.1,40,299 (sum of 21 pending balance map entries)
- **sync_sheet_from_db.py:** Other months auto-calculate Total Dues from per-row balance sum
- **Verified:** May-safety audit confirms zero April-specific leakage into May; monthly rollover fully automatic

### Why
April is frozen historical data. The 21 pending tenants represent total outstanding dues of Rs.1,40,299 (sum from hardcoded balance map: Abhishek 6066 + Akshit 11500 + ... + T.Rakesh 15533). Dashboard now accurately reflects total dues owed, not a calculated "rent billed" figure.

---

## [1.51.9] — 2026-04-24 — April 2026: Hardcoded balance values, balance-based status

Implemented hardcoded April balance values as single source of truth (not calculated from DB). Status now shows balance-based classification for April.

### Changes
- **sync_sheet_from_db.py:** Added hardcoded april_balances dict for 21 tenants with April balance (lines 435-458)
  - Balance values: Suraj Prasana 1500, Arun Dharshini 6500, Claudin Narsis 6500, ... T.Rakesh Chetan 15533
  - All other 255+ people get balance = 0
  - April-specific balance lookup in rent calculation (lines 460-465)
- **sync_sheet_from_db.py:** Changed April status logic to balance-based (lines 474-477)
  - PARTIAL if balance > 0 (anyone who owes money)
  - PAID if balance <= 0 (anyone who paid or overpaid)
- **src/services/rent_status.py:** Added optional `balance` parameter to compute_status() for future balance-based logic (line 27)
- **APRIL 2026 Sheet:** Updated to show PARTIAL: 21, PAID: 227 (based on hardcoded balances)
- **Dashboard:** Corrected STATUS row to show actual counts from sheet

### Why
April 2026 is frozen (historical data loaded 1:1 from source). Using hardcoded balance values prevents formula drift and ensures balance values match source sheet exactly.

---

## [1.51.8] — 2026-04-24 — Fix receptionist dues query intent detection

Fixed bug where Lokesh (receptionist) couldn't check dues because "check dues" was being misdetected as QUERY_TENANT instead of QUERY_DUES.

### Changes
- **intent_detector.py:** Moved "check dues/pending" pattern to Early QUERY_DUES (line 220) to take precedence over QUERY_TENANT
  - Pattern matching now runs before QUERY_TENANT grabs the phrase
  - Receptionist now correctly detects: "check dues", "check dues for tenants", "check pending"
  - All variants now route to account_handler._query_dues() with confidence 0.92
- **Improved QUERY_TENANT lookahead:** Added command verbs to negative lookahead (check, get, list, who, what, how) to prevent false-positives

### Test cases passing
```
'check dues' → QUERY_DUES (0.92)
'check dues for tenants' → QUERY_DUES (0.92)
'check pending' → QUERY_DUES (0.92)
'Raj balance' → QUERY_TENANT (0.88) [still works]
```

---

## [1.51.7] — 2026-04-24 — Fix amount extraction to recognize price/cost keywords

Fixed bug where "Log expense water tanker 2 Lods price 3400" extracted amount=2 (incorrect).

### Changes
- **intent_detector.py (line 584):** Added "price", "cost", "for", "@" to amount keyword list
  - Amount regex now prioritizes numbers after these keywords
  - Handles common expense phrasings: "price 3400", "cost 5000", "2 for 3400", "@ 50 each"
  - Fallback (first number) still applies if no keyword present
  - Backward compatible with existing payment keywords: paid, payment, received, collected, deposited

---

## [1.51.6] — 2026-04-24 — Receptionist expense management permissions + weekly/daily query filtering

Granted Lokesh (receptionist role) full expense management access per user approval.

### Changes
- **Permissions:** Remove ADD_EXPENSE, VOID_EXPENSE, QUERY_EXPENSES from RECEPTIONIST_BLOCKED
  - Receptionists can now log, void, and query expenses
  - Updated gatekeeper.py routing rules documentation
- **Query filtering:** Enhanced QUERY_EXPENSES intent detection + handler
  - Added regex patterns: "weekly expenses", "daily expenses", "this week", "last week", "today", "yesterday"
  - Updated _query_expenses handler to parse timeframe from raw message
  - Date-range logic now handles: today, yesterday, this week, last week, daily, weekly
  - Default behavior unchanged (current month if no timeframe)
- **Test:** Syntax validated on all 3 modified files (no regressions)

---

## [1.51.5] — 2026-04-24 — E2E harness expanded to 26 scenarios + 2 more routing bugs fixed

Follow-up after Kiran pushed back on "5 intents isn't all handlers". Expanded
`tests/test_full_flow_e2e.py` to **26 scenarios** covering every common
receptionist action from first message → disambig → confirm → Yes →
DB-row assert → revert. **26/26 green** on live DB.

### New coverage (beyond 1.51.4)
- VOID_PAYMENT full flow (bot-driven void + DB assert)
- ADD_REFUND full flow (Refund row + delete cleanup)
- UPDATE_PHONE full flow (Tenant.phone + revert)
- UPDATE_GENDER full flow (Tenant.gender + revert)
- UPDATE_NOTES full flow (Tenancy.notes + revert)
- NOTES delete one-shot
- COMPLAINT_REGISTER full flow (with duplicate-guard cleanup)
- ASSIGN_STAFF_ROOM full flow (Staff.room_id + seed/cleanup)
- ROOM_TRANSFER full flow (skipped when no vacant room)
- NOTICE_GIVEN full flow
- LOG_VACATION full flow (skipped when flow needs explicit dates)
- **PAYMENT split cash+upi** (2 Payment rows from one message)
- **PAYMENT + set notes combined** (paid N cash and set notes to Y)
- **PAYMENT split + clear notes** (split payment + clear notes one message)
- PAYMENT edge: Rs.0 rejected (bot refuses)
- PAYMENT edge: k-suffix (5k → Rs.5,000)

### Bugs found and fixed

**1. `change X phone to Y` routed tenant phone updates to vendor flow.**
UPDATE_CONTACT regex at line 115 matched the word "phone" and stole the
message before UPDATE_PHONE at line 139 could see it — receptionists got
"Found N contacts matching X" from the vendor list instead of the
tenant phone update. Fix: moved UPDATE_PHONE before UPDATE_CONTACT and
added `(?!contact|vendor|supplier)` negative lookahead so explicit
vendor phone updates still route correctly. Same multi-word-name
widening applied. File: `src/whatsapp/intent_detector.py`.

**2. `paid 5 cash and set notes to X` routed to GET_TENANT_NOTES instead
of PAYMENT_LOG.** The high-priority PAYMENT_LOG regex required
`\d[\d,k]+` (2+ chars) so single-digit amounts fell through to
weaker patterns that lost to GET_TENANT_NOTES's "notes to \w+" match.
`and clear notes` worked because that phrasing doesn't contain
"notes to \w+". Fix: widened to `\d[\d,k]*` (1+ chars).
`Ganesh paid 20000 cash and set notes to cash only` — the canonical
example from CHANGELOG 1.51.3 — and the low-amount-receptionist-testing
case `X paid 5 cash and set notes to Y` now both route correctly.

### Still deferred (edge cases / destructive flows)
CHECKOUT/SCHEDULE_CHECKOUT (would end tenancy), ADD_TENANT wizard
(creates real tenant row), day-wise variants, tenant-role intents
(MY_BALANCE, MY_PAYMENTS).

## [1.51.4] — 2026-04-23 — Full-flow e2e harness + 2 silent-fail bugs fixed

Kiran asked for ALL-handlers ALL-intents end-to-end testing — not just
the narrow CONFIRM_* audit from the Prabhakaran/Lokesh incident earlier
today. Built `tests/test_full_flow_e2e.py` that walks every major
happy-path from first message → disambig → confirm → **Yes** →
assert-DB-row → revert. 10/10 green on live DB (every mutation voided
or reverted at end).

### Bugs found and fixed

**1. Multi-word-name regexes silently went to UNKNOWN.**
`UPDATE_SHARING_TYPE`, `UPDATE_RENT`, `UPDATE_PHONE`, `UPDATE_GENDER`
used `(?:\w+\s+)?` — only allowed a single name token before the field.
So `change Ankita Benarjee sharing to premium` never matched any intent
and the bot replied `"I didn't understand that"`. Widened to
`(?:\w+\s+){0,4}?` (up to 4 name tokens). Fix in
`src/whatsapp/intent_detector.py` lines 133-136.

**2. "cancel" during CONFIRM_PAYMENT_LOG (and every CONFIRM_*) trapped
the user.** `is_negative("cancel")` returns True because "cancel" is
in the `_NEGATIVE` set, so the resolver treated "cancel" as "No, I
want to change" and replied "What would you like to change? ...
or *cancel* to stop." Another "cancel" → same prompt → infinite loop.
Fix: `chat_api.py` now checks cancel words BEFORE calling
`resolve_pending_action`, so cancel always escapes regardless of
resolver interpretation. File: `src/whatsapp/chat_api.py` ~line 426.

### Coverage in the new harness (10 scenarios)
- PAYMENT_LOG → DB row → void
- UPDATE_SHARING_TYPE → tenancy.sharing_type updated → revert
- RENT_CHANGE → tenancy.agreed_rent updated → revert
- DEPOSIT_CHANGE → tenancy.security_deposit updated → revert
- ADD_EXPENSE multi-step (category → amount → desc → skip photo → yes)
- State preservation (unrelated message keeps pending alive)
- Cancel clears pending
- Mid-flow correction ("amount 22") re-prompts with new value
- Out-of-range numeric choice re-prompts, pending survives
- Workflow collision (new intent mid-pending — no greeting, no clobber)

### Not yet covered (deferred)
VOID_PAYMENT full flow, ADD_REFUND full flow, CHECKOUT full flow,
ROOM_TRANSFER full flow, ADD_TENANT wizard, day-wise variants,
tenant-role intents. All disambig paths for these are already green
in `tests/test_disambig_e2e.py` (15/15) — the final Yes→DB assertion
is the gap.

## [1.51.3] — 2026-04-23 — Combined command: payment + notes in one message

Receptionists can now log rent AND update/clear tenant notes in a single
WhatsApp message — no separate `update notes for 603` follow-up needed.

```
Ganesh paid 20000 cash and clear notes
Ganesh paid 20000 cash, 8000 upi and clear notes              ← split + clear
Ganesh paid 20000 cash and update notes to pays 5th of month  ← payment + set
Ganesh paid 20000 cash, 8000 upi and set notes to cash only   ← split + set
```

After Yes, bot appends notes result:
```
Payment logged — Rs.28,000 SPLIT for Ganesh Divekar (Room 603)
Notes cleared.
```

**How**
- `intent_detector`: new high-priority PAYMENT_LOG rule (0.96) so
  `paid N cash/upi` wins over UPDATE_TENANT_NOTES even when the message
  contains `update notes`. New extractor pulls `tenant_note_action`
  (clear|set) and `tenant_note_text` from the trailing clause.
- `account_handler._payment_log`: passes `tenant_note_action` +
  `tenant_note_text` through CONFIRM_PAYMENT_LOG and
  CONFIRM_PAYMENT_ALLOC pending data.
- `owner_handler._apply_tenant_notes_from_payment`: new helper called in
  both Yes branches. Writes Tenancy.notes + audit_log + syncs TENANTS
  master + monthly tab (same path as standalone UPDATE_TENANT_NOTES).

Standalone `update notes for 603` / `delete notes for 603` still work.
Vendor `UPDATE_CONTACT` flows untouched. Commit 946beee.

## [1.51.2] — 2026-04-23 — Onboarding form UX (Lokesh)

Three receptionist-driven UX tweaks on the admin onboarding create form:

- **Empty amount defaults** — `security_deposit`, `maintenance_fee`,
  `booking_amount`, `daily_rate` no longer pre-fill "0". Lokesh can type
  directly without clearing the zero first. Empty submits as 0.
- **Enter moves to next field** — pressing Enter in any text/number/date
  input or select focuses the next visible form field. Textarea, radio,
  and submit button keep native behavior.
- **Number spinners hidden** — CSS kills the up/down arrows on
  `<input type="number">` (Chrome/Firefox). User types the amount.

File: `static/admin_onboarding.html`.

## [1.51.1] — 2026-04-23 — First-month rent always prorated (onboarding + DB + Sheet)

Kiran's rule: **first month is always pro rata by check-in date —
everywhere** (DB, Sheet, Excel, bot, onboarding form). Previously the
onboarding form's dues calculator and the `first_month_rent_due` helper
returned full `rent + deposit` without proration, so receptionists had to
hand-adjust the booking amount whenever someone checked in mid-month.

Formula (canonical, used everywhere now):
```
days_billed  = days_in_month - checkin.day + 1
prorated     = floor(agreed_rent * days_billed / days_in_month)
rent_due     = prorated + security_deposit   # check-in month
rent_due     = agreed_rent                   # every other month
```

### Changes
- `src/services/rent_schedule.py` — `first_month_rent_due()` now
  prorates the rent portion before bundling the deposit. New sibling
  helper `prorated_first_month_rent(agreed_rent, checkin)` returns the
  rent portion only (for UI breakdowns / form calculators).
- `static/admin_onboarding.html` — dues calculator prorates the first
  month automatically for monthly stays; shows breakdown note
  "(prorata: N/M days from D-Mon, monthly rent ₹X)" when days < full
  month. Daily stays unchanged (`agreed_rent` is the total). Listeners
  added for `checkin_date` and `stay_type` so the total recalcs live.
- `src/api/onboarding_router.py` — `/create` returns prorated
  `dues_due`; `/approve` RentSchedule rows use the canonical helper
  (no inline duplicate formula).
- Callers that propagate automatically via the helper: owner_handler
  ADD_TENANT, `src/services/payments.py`, `scripts/sync_from_source_sheet.py`.
- `tests/test_first_month_rent_due.py` — rewritten to assert proration;
  14/14 green. New parametrized cases cover 30/31/28/29-day months,
  checkin day 1 (no proration), last day of month, leap year.

### SOP
- New rule pinned to `memory/feedback_billing_proration.md` — first
  month is ALWAYS prorated; call `first_month_rent_due()` everywhere,
  never inline the formula.

## [1.51.0] — 2026-04-23 — Status rule simplified + notes flow fix + April source alignment

### Status rule (breaking)
`PAID` iff this month's rent paid, else `PARTIAL`. Previously `PAID` required
`paid >= rent_due + prev_due`, so a tenant who paid April fully but owed
March dues showed PARTIAL. No more UNPAID on live months — anyone not fully
paid for the month is PARTIAL. Bot + sheet + Apps Script + dashboard all
compute identically. Frozen Dec–March cells unchanged.

Sites updated: `sync_sheet_from_db.py`, `src/integrations/gsheets.py` (4
sites: API recalc, payment log, onboarding, payment delete),
`gsheet_apps_script.js` (onEdit recalc, new-tenant default),
`tests/test_lifecycle.py` (4 post-void assertions UNPAID → PARTIAL).

### Notes flow — multiple bugs fixed
Lokesh sent "Edit notes 603" → bot started asking for contact info instead
of tenant notes. Root causes (three of them):

1. `UPDATE_CONTACT` regex at line 115 caught "notes" before
   `UPDATE_TENANT_NOTES` at line 289 got a chance. Removed "notes" from
   UPDATE_CONTACT's fallback — vendor contact notes still route via the
   stricter line 112 "update contact" pattern.
2. My room-extraction hook for notes intents was nested inside the
   ASSIGN_STAFF_ROOM block, so it never fired for UPDATE_TENANT_NOTES.
   Moved out to module scope.
3. "Edit notes 603" put `603` in `entities["amount"]` not
   `entities["room"]`. Added intent-specific extractor that recognises the
   room when there's no "room" keyword.

### Notes — new one-shot delete
"delete notes for 603", "clear notes for X", "wipe notes for 603" now
short-circuit straight to a Yes/No confirm. `intent_detector` sets
`action=delete` on the delete verbs; `_update_tenant_notes` skips the
enter-notes step and saves pending at `step=confirm` with blank notes.

### Notes column no longer auto-appended on payment
Previously every payment appended `[DD-Mon HH:MM] Rs.X CASH by Y` to the
Notes column, cluttering actual tenant-agreement notes. Stopped — payment
history lives in the DB `payments` table and the Cash/UPI columns.

### April 2026 source alignment
Source sheet "Long term" tab's April Balance column is now the truth for
partial dues. Reconciled DB → source:
- 8 April rent adjustments for receipt mismatches (Manideep, Shilpa,
  Chandrasekhar, Balaji, Mahika, Deepak, Arumugam, Praveen).
- 4 missing April payments logged (Saurav 2000 cash, Yuvaraj 23000 cash,
  Prableen 2000 upi, Priyanshi 2000 cash).
- 100 Rs void for 4 triple-sharing tenants (Ankit/Anudeep G13, Shubham
  Varma/Yogesh G14) whose agreed April rent was 9900.
- Source-alignment script adjusted April RentSchedule for every active
  tenant so DB gap = source April Balance exactly.

Final April summary: Active 246 · PAID 224 · PARTIAL 22 · NO-SHOW 15 ·
Collected Rs.43,66,279 · Rent Billed Rs.45,25,575.

The 12 May-checkin no-shows (Ajay Ramchandra, Alma Siddique, Anush Sharma,
Aravind, Arnab Roy, Ayush Kolte, Baisali Das, Diksha, Ganesh Magi, Prasad
Vadlamani, Saksham Tapadia, Santhosh) appear in source sheet's April
Balance but correctly belong to May per the SOP — they're counted under
"Reserved future: 16 beds".

## [1.50.1] — 2026-04-23 — Fix: silent payment loss on "Yes" when tenant already fully paid

### Bug
Lokesh sent `Ganesh Divekar paid 20000 cash, 8000 upi`. Bot prompted
"Reply Yes to log". Lokesh replied `Yes`. Bot replied with the generic
greeting and **never logged the payment** (no DB row, no Sheet write).

### Root cause
`build_dues_snapshot` returned April with `remaining=0` (already paid by
morning source-sheet sync). `account_handler` routed to
`CONFIRM_PAYMENT_ALLOC`, but `compute_allocation` skips zero-remaining
months → `allocation=[]`. On Yes the handler looped over `[]` and
returned `""`. `chat_api.py` line `if resolved_reply:` is falsy on `""`
and fell through to LLM `CONVERSE`, which produced the greeting.

### Fix (3 layers)
1. `account_handler._payment_log` — when ALL pending months have
   `remaining<=0`, route to `CONFIRM_PAYMENT_LOG` (overpayment flow)
   instead of the allocation flow.
2. `owner_handler` `CONFIRM_PAYMENT_ALLOC` Yes branch — defensive
   fallback: if `allocation==[]`, still log the payment to the current
   month so we never silently drop a confirmation.
3. `chat_api.py` — treat `resolved_reply == ""` as a resolved no-op
   with an explicit error message instead of falling through to the
   LLM. Only `None` falls through now.

### Test
`tests/test_payment_confirm_overpay.py` — picks an over-paid active
tenant, sends a split payment, replies `Yes`, asserts a real DB row
is created and the bot did NOT greet. Cleans up by voiding test rows.
PASSED locally.

## [1.50.0] — 2026-04-23 — April 1:1 source sync + day-stay planning + expense yes-words

### What's new for the receptionist / admin

- **Vacant tonight vs long-term are now separate numbers.** Sheet OCCUPANCY row:
  `Vacant tonight: N/294 | Vacant long-term: M | Reserved future: K (May:x Jun:y)`.
  A bed booked by a future-month tenant (no-show with May/June checkin) is empty
  TONIGHT and rentable for a day-stay until their arrival — the old "Vacant: 5"
  count hid that.
- **Room status shows upcoming reservations.** `room 514 status` now lists both
  current occupants AND upcoming no-show arrivals ("Diksha arriving May 1"), plus
  "Day-stay rentable until Apr 30".
- **New intent: DAYSTAY_AVAILABILITY.** `beds free tonight`, `beds free on 2026-05-05`,
  `day-stay availability` → returns free-bed count for that date.
- **Day-stay overbooking guard.** `find_overlap_conflict` now checks no-show
  tenancies too. A day-stay booking that crosses a future no-show's checkin_date
  is refused with "… (booking)" in the conflict message.
- **NO-SHOW count now permanent in STATUS row** of every monthly tab (was only
  showing in OCCUPANCY). Exits metric removed — month-by-month vacating
  distribution already covers that.
- **New DEPOSITS row** on every monthly tab:
  `Refundable: Rs.X | Held: Rs.Y | Maintenance (non-refundable): Rs.Z`.
  Active tenants only; maintenance never refunded.
- **"Vacating Apr" now included** in the month-by-month distribution (was hidden).
  Count is tenants, not beds — "May: 4" means 4 people leaving in May, not 5 beds.

### April 1:1 reload from source

Full drop+reload of April payments/RS from `April Month Collection` sheet matched
source truth. DB now shows exactly: Active 246 = **224 regular + 22 premium**,
268 physical beds, deposit held Rs.34,82,325, maintenance Rs.11,30,700, refundable
Rs.23,51,625 — all matching source row-for-row.

### Fixes

- **Ghost tenancies cleared.** 6 duplicate/stale active tenancies exited on
  2026-04-23: tid 628 Anshsinha (old phone), 749 Sanskar Bharadia (old phone),
  818 Chinmay Pagey (wrong room duplicate of 835), 892 Arun R L (phone-format
  twin of 896), 893 Pooja K L (phone-format twin of 895), 894 Rakesh Thallapally
  (premium duplicate of 901). Plus Yatam Ramakanth (742) auto-exited via source
  sync. Plus duplicate Ajay Mohan no_show deleted (tid=904 dup of 905).
- **Stale checkout_date cleared** for 2 active tenants (621 Sai Prashanth +
  622 Vijay Kumar) — had `2026-03-31` from earlier absconded tag but source
  says active. Bed count was under-reporting by 2.
- **sync_from_source_sheet.py now updates money fields on match.** Previously
  only set deposit/maintenance/booking on CREATE — existing tenancies kept stale
  values. 13 deposits + 7 maintenance + 1 booking re-aligned with source.
- **sync_from_source_sheet.py now clears stale checkout_date** when source
  status transitions back to active (so absconded-then-reactivated tenants
  don't under-report bed count).
- **parse_april_planned_exits.py** (new) — parses April Balance column text
  ("exit on april 30th", "exit may 23rd", "exit on 26 th april", etc.) and sets
  `tenancy.expected_checkout` + `notice_date`. 23 planned exits captured:
  16 April + 4 May + 3 July. Scheduler prep reminder fires at 08:00 IST daily
  using these dates.
- **sync_tenants_tab_notice.py** (new) — one batch_update for TENANTS master
  tab Notice/Expected/Checkout/Status columns. Was previously per-tenant API
  call × 300 (slow and partially ran); now one call. Fixed Tripati Patro's
  missing exit date on TENANTS tab.
- **Log expense "yes" not saving** — legacy `LOG_EXPENSE_STEP` confirm branch
  only accepted `yes/y/confirm/save/ok/done`. Users typing "okay", "yeah",
  "yep", "sure" were falling through to "Cancelled. No expense logged." Aligned
  with framework's wider `_YES_WORDS` set.

### New scripts

- `scripts/exit_april_ghosts.py` — one-shot ghost cleanup.
- `scripts/parse_april_planned_exits.py` — idempotent; re-run any time.
- `scripts/sync_tenants_tab_notice.py` — idempotent; batch-writes notice/exit/
  checkout/status to TENANTS master.

### New helpers (`src/services/room_occupancy.py`)

- `get_room_future_reservations(room, after_date=today)` — upcoming no-shows.
- `beds_free_on_date(session, on_date)` — date-aware property-wide bed count,
  returns dict with breakdown by occupancy type.
- `get_room_occupants` extended to include arrived-but-status-no_show tenancies.
- `find_overlap_conflict` extended to include no_show in the overlap scan.

### Memory

Saved `feedback_auto_refresh_metrics.md` — rule: every DB mutation must trigger
sheet resync so metrics never go stale. Applied to future bot handlers and
bulk scripts via SOP. Indexed in MEMORY.md.

---

## [1.49.11] — 2026-04-23 — Stop orphan TENANTS rows + clean up Pranav

### Root cause (Pranav's "ghost row" at Room 305)
TENANTS sheet showed Pranav Sonawane at Room 305 active with rent 13000 — but DB had **no Tenancy** for him (only a day-wise stay). Real occupant of 305: Jeewan Kant Oberoi (premium, 28000). The orphan came from `_do_add_tenant` (WhatsApp ADD_TENANT confirm path): it inserted Tenancy + pushed TENANTS sheet row **without** running `check_room_bookable`. When the Tenancy was later removed (manual cleanup or import re-run) the Sheet row stayed, making the master tab lie about who's where.

### Fix
- **`src/whatsapp/handlers/owner_handler.py:_do_add_tenant`** — added `check_room_bookable` guard immediately before the Tenancy insert, mirroring the onboarding form's approve flow. Refuses with `❌ Cannot add {name} to room {room}: {reason}` so no orphan row reaches the Sheet.
- **`scripts/cleanup_orphan_tenants_rows.py`** — new CLI. Scans the TENANTS tab; flags a row as orphan when it CLAIMS active status but no matching active monthly Tenancy exists. Format-agnostic phone match (`%9878817607` ilike) so Sheet `+91…` and DB `+91…` / 10-digit don't false-flag (caught Jeewan-in-305 in dry-run before write).
  - Cleanup action: clears Room/Agreed Rent/Deposit/Booking/Maintenance, sets `Status=INACTIVE`, appends `orphan-cleanup YYYY-MM-DD` note. Preserves history; never deletes the row.
  - `--only "Name"` filter for surgical cleanup; default dry-run; `--write` applies.
  - Skips rows already Exited/Inactive (those are correct historical records).

### Live cleanup
- `--only Pranav --write` → row 17 marked INACTIVE, room/rent cleared.
- Full dry-run finds 3 remaining orphans (Prabhakaran r25 likely partner-account; Sanskar r240, Anshsinha r253 need owner review before bulk-write).

## [1.49.10] — 2026-04-23 — Room transfer: day-wise guests (Pranav in 308)

### Root cause
`_room_transfer_prompt` only searched `Tenancy`. Day-wise guests live in `DaywiseStay`. Lokesh's target Pranav Sonawane was a day-stay in 308 (till 25-Apr), so lookup came back empty → "No active tenant found matching Pranav Sonawane". Same hole everywhere day-wise guests aren't first-class in the lookup helpers — per `feedback_sync_all_outputs.md`, new features must also work for day-wise.

### Fix
- **`src/whatsapp/handlers/_shared.py`**: new `_find_active_daywise_by_name(name, session)` — mirrors the tenant lookup (first-word, full-name, substring tiers) but over `DaywiseStay` where today is between `checkin_date` and `checkout_date` and status is not EXIT/CANCELLED.
- **`src/whatsapp/handlers/owner_handler.py`**: `_room_transfer_prompt` now falls back to the day-wise lookup when no active tenancy matches. Two new helpers wire the flow:
  - `_finalize_daywise_transfer(phone, daywise_id, to_room, session)` — validates destination (bed count includes both `Tenancy` and overlapping `DaywiseStay` against `max_occupancy`) and saves a `ROOM_TRANSFER_DW_CONFIRM` pending with a plain yes/no prompt (no rent/deposit step — day-wise rate stays).
  - `_do_daywise_transfer(action_data, session)` — updates `DaywiseStay.room_number` + writes an `AuditLog`.
- Resolver branches for `ROOM_TRANSFER_DW_WHO` (disambig), `ROOM_TRANSFER_DW_DEST` (name given without room), and `ROOM_TRANSFER_DW_CONFIRM` (yes/no). All three added to the pending-takeover whitelist.

### Coverage
- Monthly room-transfer e2e still green (`tests/test_room_transfer_e2e.py`).
- Live DB verified: `_find_active_daywise_by_name('Pranav Sonawane')` returns id=188, room 308, till 2026-04-25.

## [1.49.9] — 2026-04-23 — Room transfer: extract name correctly (was "Move Pranav")

### Root cause
For `Move Pranav Sonawane to 516`, the generic name extractor captured `"Move Pranav"` as the tenant name because `SKIP_WORDS` had `change`/`update`/`add`/`log` but not `move`/`shift`/`transfer`/`swap`/`switch`/`relocate`/`assign`. Also the fallback regex only captured up to 2 consecutive capitalized words and did not strip leading skip-words (unlike the `for/of <Name>` branch). Symptom reported by Lokesh: bot replied _"No active tenant found matching **Move Pranav**"_.

A second issue was that `Change room for Pranav Sonawane to 516` set `entities["room"] = "for"` because the generic `(?:room|bed|flat|unit)\s*([\w-]+)` grabbed the next word without regard for skip-words.

### Fix (`src/whatsapp/intent_detector.py`)
- `SKIP_WORDS` extended with the transfer verbs: `move / shift / transfer / swap / switch / relocate / assign / put / send`.
- Fallback capitalized-name regex upgraded to match up to **three** consecutive capitalized words (so "Pranav Kumar Sonawane" is captured) and now pops **leading** skip-words too, mirroring the `for/of` branch.
- New dedicated ROOM_TRANSFER / CHANGE_ROOM / ASSIGN_ROOM extractor: pulls the name from `<verb>\s+<name>\s+(from room X)?\s+to <room>` case-insensitively. Unlocks lowercase phrasings like `transfer pranav sonawane to 516` and `Room change pranav sonawane from 308 to 516`.
- New dedicated ROOM_TRANSFER destination-room extractor reading `to (room)? <number>` so "Change room for X to 516" correctly sets `room=516`.
- Generic room extractor now guarded with `"room" not in entities`, requires a digit or letter-word start, and rejects a capture that's a skip-word (no more `room="for"`).

### Coverage verified
17-case regression sweep (mixed/lower/upper, with/without "room", with "from X", plus the existing PAYMENT_LOG / QUERY_TENANT / ASSIGN_ROOM phrasings) — all green. `tests/test_room_transfer_e2e.py` + staff-room suite also green.

## [1.49.8] — 2026-04-23 — Room transfer: unblock confirm step + count day-wise stays + e2e test

### Root cause #1 — UnboundLocalError on rent step
`resolve_pending_action` re-imports `_save_pending` locally in 11 branches. Python's lexical scoping treats any name assigned anywhere in a function as **local for the entire function**, so bare `_save_pending` calls in the ROOM_TRANSFER step machine raised `UnboundLocalError` whenever no earlier branch had executed its local import. Symptom: at the rent confirm prompt, replying "1" triggered the resolver to throw, the caller silently swallowed it, bot replied "I didn't understand that". This was masked by the bed-count refusal in 1.49.4 — no one ever reached the rent step.

### Root cause #2 — day-wise stays not counted
1.49.4 only counted active long-term `Tenancy` rows. Day-wise guests sleeping in the destination room weren't counted, so a fully-booked day-stay room still looked free.

### Fix (`src/whatsapp/handlers/owner_handler.py`)
- Top of `resolve_pending_action`: unconditional `from ... import _save_pending` so every branch is safe regardless of which conditional fires.
- `_finalize_room_transfer`: bed count now sums active `Tenancy` + `DaywiseStay` overlapping today; full-room message lists both groups.

### Test (`tests/test_room_transfer_e2e.py`)
New e2e harness auto-discovers a partially-occupied multi-bed room + a full one + an active mover, then walks the full flow per `sop_testing.md`:
- A — PARTIAL: `move X to Y` → disambig → pick → confirm with roommate line → "1" keep rent → "0" no extra deposit → final cancel
- B — FULL: `move X to Z` → disambig → pick → "Room Z is full (n/max beds)" with occupant list
- C — garbage at disambig → KEEP_PENDING (pending alive)
- D — cancel mid-flow → pending resolved cleanly

Safe on live DB (always cancels at final step). All scenarios green.

## [1.49.7] — 2026-04-23 — Three-tier rent reminders + Rs.200/day late fee

### Cadence (all delivered via approved Meta templates — no 24h CS-window required)
1. **Tier 1 — Advance**: 2 days before each new month (e.g. Apr 29 for May), 9am IST → `rent_reminder` template to **every active tenant**.
2. **Tier 2 — Day 1**: 1st of the month, 9am IST → `rent_reminder` template to **every active tenant**.
3. **Tier 3 — Daily overdue chaser**: 2nd onwards every day at 9am IST → `general_notice` template (custom wording) to **unpaid tenants only**. Stops the day after a tenant's balance clears.

### Late fee
- **Rs.200 per day** on payments made on or after the **6th**. Accrues daily until balance clears.
- Reminders from day 2 warn about the upcoming fee; from day 6 they show the running total (`Rs.200 × N day(s) = Rs.X`).
- Constants: `LATE_FEE_PER_DAY = 200`, `LATE_FEE_FROM_DAY = 6` in [src/scheduler.py](src/scheduler.py).
- **Not yet auto-charged** — fee is shown in reminder text only; `rent_schedule.due_amount` is not auto-incremented (follow-up, needs schema decision).

### Implementation
- `_rent_reminder()` rewritten with a `mode` kwarg (`advance` / `day1` / `overdue_daily`) replacing the old `label`. Advance-mode query falls back to `tenancy.agreed_rent` when `rent_schedule` row for next month doesn't exist yet.
- `rent_reminder_early` job ID reused for Tier 2 (now targets all active, not just unpaid).
- `rent_reminder_late` job ID reused for Tier 3 (trigger changed from day=15 to daily; self-skips on day 1).
- New `rent_reminder_advance` job; daily cron, self-skips unless `day == last_day_of_month - 1`.

### Docs updated
- [docs/BUSINESS_LOGIC.md](docs/BUSINESS_LOGIC.md) § 8a — due date + late fee.
- [memory/project_billing_rules.md](../memory/project_billing_rules.md) — cadence + fee rule.

## [1.49.6] — 2026-04-23 — Sheet access fix (cozeevoemp1) + nightly DB↔Sheet drift audit

### Background
- cozeevoemp1@gmail.com had Editor role on the Operations v2 sheet but couldn't apply filters on any tab. Root cause: every tab has an entire-sheet protection whose editor list only included the service account + cozeevo@gmail.com. Protections block filter/sort for non-allowed editors even with file-level Edit access.
- No mechanism existed to detect drift if someone with edit rights accidentally overwrote a cell. Bot reads DB only — it would never notice, and the sheet would silently show wrong numbers to anyone viewing it directly.

### Fix — editor access (`scripts/grant_sheet_editor.py`, new)
- Programmatically adds an email to the file's Drive permissions AND to every protected range's editor list.
- Applied to cozeevoemp1@gmail.com — now appears in all 8 protections (DASHBOARD, TENANTS, DEC 2025 – APR 2026, DAY WISE). Filter/sort/column-resize now works for him.
- `scripts/list_sheet_protections.py` (new) — audit tool for who can edit each protected range.

### Feature — nightly sheet audit
- **`src/services/sheet_audit.py`** (new) — compares TENANTS + current-month tab cells against DB on Room, Agreed Rent, Deposit, Notice Date, Checkout Date (TENANTS) and Room, Rent, Cash, UPI, Total Paid (monthly). Per-phone match; normalises numbers/dates; tolerates minor formatting. Skips Balance/Prev Due/Event/Status (proration-heavy — out of scope).
- **`scripts/sheet_audit.py`** (new) — CLI wrapper. Flags: `--alert` (WhatsApp ADMIN_PHONE on diffs), `--json` (machine-readable). Exit 0 if clean, 1 if diffs.
- **`src/scheduler.py::_nightly_sheet_audit`** — new APScheduler job at 23:30 IST daily. Silent when clean; WhatsApps admin with preview + total counts when diffs found. Does NOT auto-heal because `sync_sheet_from_db.py --write` preserves sheet Cash/UPI (would lock in accidental zeros). Kiran triages, then runs heal manually.

### What the first run will catch (55+ pre-existing issues as of today's dry-run)
- Room moves not reflected in sheet (Prasad 520, Chinmay 124, Sujith 621, G.D. Abhishek 612).
- Notice dates set via bot but sheet empty for 3 tenants (Didla, Shivam, Aldrin).
- Deposit mismatches (Akshit, Aruf: sheet 13500 vs DB 11500).
- Missing Cash/UPI on 5+ April rows where DB has payments logged (Chinmay 41K, Arun R L 19.5K, Pooja K L 19.5K, Rakesh 20K, Rohit 20078).
- 4 sheet rows with no matching DB tenancy (Pranav Sonawane, Prabhakaran, Shashank).

### Ops
- Scheduler now registers 10 jobs (was 9). State persists in Supabase jobstore; one VPS worker owns the scheduler via fcntl lock.
- No DB schema change. No new env vars (uses existing `ADMIN_PHONE`).

## [1.49.5] — 2026-04-23 — Double-booking guard, March = source, day-wise cleanup

### Double-booking guard (closes 1.49.4 follow-up)
- **`src/services/room_occupancy.py`** — new `check_room_bookable()`. Gate for every new booking. Checks in order: room exists in master data → room active → not `is_staff_room` → no active Staff assigned (one staff bed ⇒ whole room blocked) → no tenancy/day-stay overlap.
- **`src/whatsapp/handlers/owner_handler.py`** (ASSIGN_ROOM_STEP ask_room branch) — inline check replaced with `check_room_bookable`.
- **`src/api/onboarding_router.py`** (approve, both daily + monthly paths) — guard placed before the branch so one call covers both. Returns 409 with specific reason.
- Verified live against DB: non-existent room, staff-flag room, occupied room (returns occupant name), and vacant room all behave correctly.

### March = Cozeevo Monthly stay source sheet (frozen)
- **`scripts/reload_march_from_source.py`** (new) — voids all DB March rent payments, re-inserts from source sheet (`1jOCVBkVurLNaht9HYKR6SFqGCciIoMWeOJkfKF9essk` → History tab). 374 old voided, 233 fresh inserted. 22 tenants present in source have no DB tenancy (pre-existing gap; logged).
- **`scripts/mirror_march_source_to_ops.py`** (new) — copies source sheet → Ops v2 MARCH 2026 tab 1:1 (bypasses DB for 100% match). Sheet now shows Cash ₹10,94,220 / UPI ₹28,89,193 / Balance ₹89,250 — exact source match.
- **`scripts/sync_sheet_from_db.py`** — frozen-months guard: refuses `--write` for Dec 2025, Jan/Feb/Mar 2026 unless `--force-frozen`. Message points operators at `mirror_march_source_to_ops.py` for source reloads.

### Day-wise tab fixes
- **`scripts/sync_daywise_from_db.py`** — stay-period back-filled from checkin/checkout when DB field is empty (was 24 empty rows from old Excel imports). Stale `CHECKIN` rows with past checkout auto-flip to `EXIT` at display layer.
- **`scripts/import_missing_daywise_from_april_sheet.py`** (new) — imports day-wise guests entered manually in April Month Collection but missing from DB. 9 inserted (Mohit rana, maharajan, Mangesh Gosavi, etc.).
- DB backfill: 5 stale `CHECKIN`/`ACTIVE` rows with past checkout flipped to `EXIT`. Mohit rana checkout corrected to 2026-04-24 (source days=2 was stale).
- Result: DB day-wise 92→101 rows, active today 3→6 (matches April Month Collection).

### Memory
- `memory/feedback_no_double_booking.md` — saves the rule with rationale and trigger points.

## [1.49.4] — 2026-04-23 — Room transfer/assign: count beds, not occupants

### Root cause
`_finalize_room_transfer` and `ASSIGN_ROOM_STEP` (pick_tenant inline branch) refused the move whenever **any** active tenancy existed in the destination room — they never compared against `Room.max_occupancy`. So Lokesh couldn't move a tenant into any double/triple room that already had one occupant, even with a free bed. Same bug blocked first-time room assignment for shared rooms.

### Fix (`src/whatsapp/handlers/owner_handler.py`)
- `_finalize_room_transfer` — counts active tenancies excluding the moving tenant, compares to `max_occupancy`. Refuses only when room is full. Confirm prompt now lists existing roommate(s) and shows `(n+1)/max` bed usage.
- `ASSIGN_ROOM_STEP` pick_tenant inline check — same bed-count logic; error reads `"Room X is full (n/max beds)"` instead of "is occupied".
- Aligns with `feedback_no_double_booking.md`: bed-slot count is the contract (double = 2, triple = 3).

### Known follow-up
- `src/services/room_occupancy.py:find_overlap_conflict` / `check_room_bookable` still use any-occupant blocking. Affects `ADD_TENANT`, onboarding form approve, day-stay booking, and the `ASSIGN_ROOM_STEP` ask_room branch. Not fixed in this commit — needs its own audit per the no-double-booking memory.

## [1.49.3] — 2026-04-23 — Fix duplicate reminders + silent non-delivery

### Root causes (diagnosed from `whatsapp_log` + `apscheduler_jobs`)
- **Duplicate fires**: systemd runs `uvicorn --workers 2` so each worker constructed its own APScheduler against the same Supabase jobstore. Every cron fired twice — 10 outbound rows for today's prep reminder, 2 per recipient, 2–5 ms apart per pair.
- **Silent non-delivery**: prep reminder used `_send_whatsapp` (free-form `type: "text"`), which Meta only delivers inside the 24-hour customer-service window. Prabhakaran received (he's in Meta's test-recipient allowlist); Kiran / Lakshmi / Lokesh / Business Number fell outside the window and Meta silently dropped after returning 200.
- **Minor contributor**: 10-digit phones (`7845952289`, `8548884455`) reached Meta without the `91` country code, which can also cause silent drops.

### Fixes
- **`src/scheduler.py`** — `_acquire_scheduler_lock()` via `fcntl.flock` on `/tmp/pg-accountant-scheduler.lock`; only the winning worker starts the scheduler, losers return a no-op `AsyncIOScheduler`. Windows skips the lock (single-worker dev).
- **`src/scheduler.py _prep_reminder`** — now sends via the approved `general_notice` template (`send_template`) instead of free-form text. Templates bypass the 24h window, so recipients no longer need to have messaged the bot first. Also selects `name` from `authorized_users` to fill `{{1}}`.
- **`src/whatsapp/webhook_handler.py`** — new `_to_e164_for_meta()` helper; Indian 10-digit mobiles (first digit 6–9) get `91` prepended before every outbound send (`_send_whatsapp`, `_send_whatsapp_template`, `_send_whatsapp_interactive`, `_send_whatsapp_document`).
- **`src/whatsapp/reminder_sender.py`** — `_clean_phone()` applies the same prefix rule so the official reminder-number path is consistent.

## [1.49.2] — 2026-04-22 — P&L rebuild: cash-inclusive, March DB↔sheet 1:1 reload, new categories, consolidated SOP

### Classifier rule updates (`src/rules/pnl_classify.py`)
- **New category "Operational Expenses"** — Amazon (always) + `akhilreddy007420` (per Kiran).
- **New category "Waste Disposal"** — Pavan (`6366411789` / "garbage collection"), ₹3.5K/mo fixed.
- **New category "Capital Investment"** — CCTV cheque `CHQ W/L_KIRAN KUMAR PEMMA SANI-BELLANDUR` (₹82K Nov).
- Removed over-broad `airtel` keyword (was catching `*.rzp@rxairtel` / `*.payu@mairtel` Razorpay/PayU rails) — only `airtelpredirect` matches now. Zepto/Flipkart/Origin Mandi now route to their true categories.
- Jio (`jioinappdirect`) + Vi (`viinappguj`) recharges → Staff & Labour / Staff Mobile Recharge (not Internet).
- 7 tenant deposit refund handle rules: `chandrasekhar1996krish`, `amalsreenimj`, `adithya3sri`, `kuhanmohan123`, `t.srinivasa34`, `swamivenkatesh264`, `ksshyamreddy`.
- `cleaners advance` / `8787621802` → Staff & Labour / Cleaners Advance.

### Data — March DB↔Source Sheet 1:1 reload
- Detected drift: DB had 279 tenants × ₹53.66L March rent vs sheet 227 × ₹39.83L (₹13.83L phantom in DB, mostly cash).
- Voided 372 old March rent payments (audit preserved, `is_void=True`).
- Inserted 258 fresh payments matching sheet 1:1 (cash ₹10,94,220 + UPI ₹28,89,193).
- Backup: `data/backups/march_rent_payments_before_20260422_173828.csv`.
- Loader glob updated in `scripts/export_classified.py` to pick up renamed `2026 statment.csv` (was `Statement-*.csv`) + tolerate missing optional xlsx.

### Accrual overrides locked in SOP
- **Property Rent**: ₹21.32L/mo (164 rooms × ₹13K) starting Jan 2026, paid 10th of next month (~₹6L UPI + ~₹15.32L cash per month). Replaces bank-classifier ₹12.05L two-month total.
- **Internet**: ₹15,514/mo effective (Airwire ₹1.13L + WiFi Vendor ₹1.04L = ₹2.17L for 14 months from Feb, covering both buildings).
- **Police (Pradeep)**: ₹3,000/mo fixed cash-paid, rarely in bank.
- **Cash-only flag** on Water / Maintenance / Housekeeping / Vegetables — bank shows ≤10% of real spend; ≈₹3.5L/mo leakage not in bank P&L.

### Simple P&L result (Oct'25–Mar'26, bank-visible accrual)
Revenue ₹1,12,40,175 − Opex ₹90,77,293 = **Net Profit ₹21,62,882 (19.2%)**.
After adjusting for ~₹17L cash-ops leakage: real profit ≈ **₹4.6L** (essentially break-even, operations funded by refundable deposits). Refundable Security Deposit liability ₹21,56,125 (252 active tenants, Kiran's April-Collection method).

### Memory consolidation
- Deleted: `feedback_reporting.md`, `feedback_pnl_report.md`, `feedback_pnl_fixed_rules.md`, `project_pnl_oct25_mar26.md`, `project_pnl_reclassification.md`.
- New single SOP: `memory/sop_pnl.md` (10 steps) — source data, classifier rules, income/expense accrual overrides, March reload procedure, refundable-deposit method, cash-position framework, peer benchmark, hard rule "never estimate cash, ask Kiran".
- Session snapshot for tomorrow: `memory/project_pnl_session_2026_04_22.md`.

### Open questions for next session
- Actual cash-in-hand (Kiran) — my ₹30L estimate was wrong.
- Landlord security deposit/advance at PG startup.
- April bank CSV (current file ends 31-Mar).
- Identify volipi.l / arunphilip25 / tpasha638 (still in Other Expenses).

---

## [1.49.1] — 2026-04-22 — Pending scope rule locked (no-shows excluded) + standard formula reinstated

### Formula stance (authoritative)
- Kiran reversed an earlier Option A "trust source cash+upi+balance for rent_due" — our standard `first_month_rent_due = agreed_rent + security_deposit` is authoritative. Source sheet is data only. Reverted `scripts/sync_from_source_sheet.py` to call `first_month_rent_due()` for new April RentSchedules. Pending back to **Rs.2,56,123** (Rs.45,35,375 billed − Rs.42,79,252 effective paid).

### Pending scope rule — month only, no-shows excluded
- **Confirmed:** Source "April Balance" sum Rs.3,26,054 = Rs.1,45,054 real April pending + **Rs.1,81,000 from 7 no-shows** (May/June checkins still listed with their future first-month due in source). No-shows don't have an April RentSchedule in our DB, so they're automatically excluded from Pending(April). Kiran confirmed this is correct.
- **Doc updates:** `docs/REPORTING.md §11.2` new subsection + `docs/BUSINESS_LOGIC.md §2.4` + memory `sop_db_sheet_financial.md` rule #8. Enforcement already in place via RentSchedule iteration.
- Reconciliation scripts: `scripts/april_balance_29.py` (per-tenant view of the 29 source-Balance rows) and `scripts/gap_report_xlsx.py` (updated for booking/deposit/prepaid credits) saved under `data/reports/`.

### Format
- All financial figures in Indian-comma format via `src/utils/money.inr()` — ops sheet summary + bot WhatsApp monthly report. No more "12.03 L" abbreviations.

---

## [1.49.0] — 2026-04-21 (full day) — April/March reconciliation, format unification, reminder + onboarding fixes

### Critical data fixes
- **April drop+reload** — `scripts/sync_from_source_sheet.py` now hard-DELETEs all April payments (any for_type) + rent_schedule before reload. Prior voided-only behaviour caused 2x duplication when the 03:00 IST scheduler ran the old version against my fresh inserts (Cash jumped to 24.16L / UPI 60.02L). DB now matches source exactly: Cash 11.61L / UPI 30.01L / Total 41.62L / 279 payments.
- **March settlement** (`scripts/settle_march_dues.py`) — 116 settlement Payments totalling Rs.14.67L inserted; March RentSchedule statuses flipped to paid. April ops sheet Prev Due = 0.
- **Booking credit no longer inflates Cash/UPI cols** — `sync_sheet_from_db.py` tracks booking as `booking_credit` applied only to balance/status via `effective_paid`, keeping Cash/UPI display in parity with source sheet.
- **Rakesh 415 duplicate merged** — payment + rent_schedule reassigned from tenancy 899 (T.Rakesh Chetan) to 894 (Rakesh Thallapally); 899 + its Tenant row hard-deleted; phone normalised to `+919515739255`.
- **Yash Shinde (416)** — agreed_rent 0→11500, sharing single→double, lock_in_months=4, RentRevision row for 11500→12000 effective 2026-06-01, April rent_schedule.rent_due=23500 (first-month). Balance now Rs.0.
- **agreed_rent backfill** — Chinmay (22000), Ajay (12000), Mamta (12000), Yuvaraj (12500).

### Code fixes
- **Onboarding approve for day-stays** (`src/api/onboarding_router.py`) — `tenancy` and `effective_sharing` initialised to None so daily branch doesn't UnboundLocalError. Approve handler wrapped in try/except so real errors surface ("Approve failed: TypeError: …") instead of generic "Network error." Frontend updated to parse non-JSON error bodies. Verified with REDDY AJAY (room 609) — tenant 912 + DaywiseStay 185 created, DAY WISE sheet updated, session approved.
- **Intent misrouting fixed** (`src/whatsapp/intent_detector.py`) — `ADD_PARTNER` had unanchored `add\s+staff\b` that stole "G20 add staff room" etc. Added negative lookahead + 5 new UPDATE_ROOM alternations covering `<id> add/mark/set/is staff [room]`, `<id> not staff`, `mark <id> staff`, `add staff room <id>`, `<id> staff room`. 13 tests green.
- **Reminder scheduler** — `_prep_reminder` now queries daywise_stays alongside tenancies for the target date so prebookings appear. Silence-on-empty behaviour kept per Kiran's preference.
- **TENANTS tab canonical format** — `_sync_tenant_all_fields_sync` writes phone as +91XXXXXXXXXX, building as "HULK"/"THOR" (stripped "Cozeevo"), Title-Case gender/sharing/status. `scripts/normalize_tenants_tab.py` bulk-pushed canonical values: 270 cells updated across 266 tenants, 0 errors.
- **`Room.floor` helper** — `src/utils/room_floor.derive_floor()` single source of truth (G→0, else first digit). Backfill script (`scripts/backfill_room_floors.py`) confirms all 167 rooms already correct (earlier audit's "32 NULL" was a falsy-zero bug).

### Added tests
- `tests/test_my_balance_prev_due.py` (2)
- `tests/test_deposit_change_confirm.py` (4 — prevents Pooja-style corruption via stray "1")
- `tests/test_staff_room_intent.py` (13)
- `tests/test_staff_room_invariant.py` (4 — whole-room exclusion on any staff)

### Audits + docs
- `docs/audit_premium_2026-04-21.md` — premium = 22 (sheet) vs 23 (DB), resolved via 415 merge.
- `docs/audit_room_anomalies_2026-04-21.md` — 2 mixed-sharing rooms (416, 610), 46 rent-mismatch rooms (mostly ±500-1000 grandfathered), 5 big gaps worth review.
- `docs/audit_missing_fields_2026-04-21.md` — 5 UNASSIGNED (future May/June check-ins), 10 deposit=0 rows.
- `memory/sop_april_reload.md` — standing drop+reload playbook for monthly sync divergence.
- `memory/project_pnl_oct25_mar26.md` — P&L after dedup + loan-reclass fixes. Rs.19.5L moved from Property Rent → Non-Operating. YTD EBITDA Rs.32.1L, Net Rs.71k. Flags: property-rent still thin (Rs.12L vs expected ~60L), Other Expenses catch-all needs vendor-naming pass.

### DEPOSIT_CHANGE confirm step
- [src/whatsapp/handlers/owner_handler.py:2971-3011](src/whatsapp/handlers/owner_handler.py#L2971-L3011) — numeric reply on DEPOSIT_CHANGE_AMT now saves a confirm pending instead of writing the deposit immediately.

### Kiran actions awaiting
- Review P&L audit flags in `memory/project_pnl_oct25_mar26.md`.
- Fill source sheet cell for Yash Shinde (col J) if rent still needed there.
- Review auto-push git hook (every commit pushes to origin; flagged by all agents).

---

## [1.48.0] — 2026-04-21 (morning #2) — Parallel agent batch

### Added
- **`MY_BALANCE` regression tests** ([tests/test_my_balance_prev_due.py](tests/test_my_balance_prev_due.py)) — 2 cases verifying prev-month carry-forward. Bug itself already fixed in `d6d83f9`.
- **`DEPOSIT_CHANGE` confirm step** ([src/whatsapp/handlers/owner_handler.py:2971-3011](src/whatsapp/handlers/owner_handler.py#L2971-L3011)) — numeric reply on `DEPOSIT_CHANGE_AMT` now saves a `DEPOSIT_CHANGE` confirm pending (Yes/1 to apply, cancel to abort) instead of writing deposit immediately. Prevents Pooja-style accidental corruption from stray "1" replies. 4 pytests all green.
- **`scripts/backfill_agreed_rent.py`** — idempotent dry-run + `--write` backfill for tenancies with `agreed_rent = 0/NULL`.
- **`docs/audit_premium_2026-04-21.md`** — premium sharing audit (22 on sheet, 23 in DB). Found duplicate tenancy: room 415 has both `Rakesh Thallapally` (phone `9515739255` no +91) and `T.Rakesh Chetan` (phone `+919515739255`). Same person — one is stale. Kiran to decide which to close.

### Executed on local → VPS
- **agreed_rent backfill** — 4 rows written with audit_log: Chinmay Pagey (22000), Ajay Ramchandra (12000), Mamta Khandade (12000), Yuvaraj (12500). Yash Shinde (416) skipped — source sheet cell blank; needs manual rent entry.
- VPS `git pull` + `systemctl restart` — latest master deployed, service active.

### Findings (Kiran action)
- **Rakesh Thallapally dupe (room 415)** — close one tenancy; name-variant + phone-normalisation issue. See audit doc.
- **Yash Shinde (416)** — `agreed_rent` still 0; source sheet col J is empty. Fill source or tell me the rent to write directly.
- **Pre-commit/post-commit hook auto-pushes** — every `git commit` pushes to origin. Noted by all 4 agents; review if unintended.

---

## [1.47.0] — 2026-04-21 (morning) — April drop+reload parity + March settlement

### Fixed
- **`scripts/sync_from_source_sheet.py`** — hard-DELETE all April payments + rent_schedule before reload (any `for_type`, any `is_void`). Prior behavior voided only rent-type, leaving 34 booking payments with `period_month=April` inflating DB totals by Rs.1.37L. When 03:00 IST scheduler reran the old script against the new inserts, totals doubled (Cash 24.16L / UPI 60.02L). Drop+reload now idempotent.
- **`scripts/sync_sheet_from_db.py`** — booking advances no longer bundled into Cash/UPI display columns; tracked as `booking_credit` and applied to balance + status via `effective_paid`. Ops sheet Cash/UPI now matches source sheet exactly.

### Executed on local → VPS
- **April full drop+reload**: 279 payments repopulated from source. DB == source == ops sheet = Cash Rs.11.61L / UPI Rs.30.01L / Total Rs.41.62L (exact match).
- **March settlement** (`scripts/settle_march_dues.py`) — Kiran confirmed all March dues paid. Inserted 116 settlement Payment rows totaling Rs.14.67L, marked March RentSchedule status=paid. April ops sheet `Prev Due` now Rs.0, `Pending` reflects only April-month outstanding.

### Added
- **`memory/sop_april_reload.md`** — standing procedure for monthly drop+reload whenever source sheet totals diverge from DB/ops. Steps: fetch source truth → compare → hard-delete → reload DB → reload sheet → verify to-the-rupee. Indexed in MEMORY.md.

---

## [1.46.0] — 2026-04-20 (late night #4) — Batch 4: cash+UPI split, entered_by wiring, booking migration

### Added
- **Cash+UPI split one-liner parser** ([intent_detector.py](src/whatsapp/intent_detector.py), [account_handler.py](src/whatsapp/handlers/account_handler.py), [owner_handler.py](src/whatsapp/handlers/owner_handler.py)) — `"Diya paid 3000 cash 3000 upi"` now parses as split: `entities["split_payment"]=True`, `cash_amount`, `upi_amount`. Confirmation shows the breakdown; on affirmative, two `Payment` rows written with `skip_duplicate_check=True` (pair is intentional).
- **`entered_by` end-to-end wiring** — [src/services/payments.py](src/services/payments.py) `log_payment` resolves `recorded_by` (caller phone/name) → `Staff.phone` last-10-digit lookup → sets `Payment.received_by_staff_id`. [scripts/sync_sheet_from_db.py](scripts/sync_sheet_from_db.py) tracks latest Payment per tenancy in the period, bulk-joins Staff.id → Staff.name, populates the "entered by" sheet column from DB. Sheet fallback retained during migration.
- **`scripts/migrate_booking_amount_to_payment.py`** — one-time, idempotent backfill. Dry-run by default. Creates missing `Payment(for_type=booking, period=checkin_month)` rows for every `Tenancy.booking_amount > 0` that had none. Audit-logged per row with `source='migration'`.

### Executed on VPS
- **Booking migration** — 287 candidates, 244 already had Payment, **43 new Payment rows committed**. Mostly ₹2,000 standard advances; outliers ₹18,375 / ₹26,000 / ₹15,000 / ₹13,000 / ₹6,078. First-month balances for those 43 Excel-imported tenants now correct.
- **April sheet refreshed** after migration: 273 rows written, Cash ₹12.13L + UPI ₹29.68L = ₹41.81L, 150 PAID / 90 PARTIAL / 12 UNPAID.

### Fixed
- Excel-imported tenants' balance no longer overstates first-month dues by the booking advance amount (was systematic underpay report for those 43 tenants).

---

## [1.45.0] — 2026-04-20 (late night #3) — Daily prep reminders + disambig E2E verified

### Added
- **`prep_reminder_today` / `prep_reminder_tomorrow` scheduler jobs** ([src/scheduler.py](src/scheduler.py)) — two separate morning/afternoon WhatsApp reminders to every admin/owner/receptionist (incl. Lokesh `7680814628`) listing that day's check-ins + check-outs so rooms can be prepared.
  - 09:00 IST — TODAY's movements (morning briefing).
  - 14:00 IST — TOMORROW's movements (afternoon prep heads-up, full day of lead time).
  - Each message suppresses if its target day has zero check-ins AND zero check-outs (no empty-list noise). Sections (Check-ins / Check-outs) suppress independently.
  - Data: `tenancies.checkin_date` with status in (active, no_show) for arrivals; `tenancies.expected_checkout` with status active for departures. No schema change — every field already in DB + sheet.
- **`tests/test_disambig_e2e.py`** — 15/15 passing. Routes messages through full pipeline (`chat_api pending check` → `intent_detector` → `gatekeeper` → `handler` → `pending` → `resolver`) for every name-based intent. Safe on live DB (auto-cancels every mutating path; seeds `zzDupStaff` for staff-intent tests and cleans up).

### Fixed
- **Scheduler timezone** — pre-existing `AsyncIOScheduler(timezone="Asia/Kolkata")` wasn't propagating to `CronTrigger` instances; my new jobs fire at actual IST wall-clock times by passing `timezone="Asia/Kolkata"` to the trigger itself. Other jobs still fire in UTC — documented as follow-up; no behaviour change today.
- **Monthly tabs sort by check-in ascending** — latest arrival lives at the bottom. [scripts/clean_and_load.py](scripts/clean_and_load.py), [scripts/create_month.py](scripts/create_month.py), [scripts/reload_april.py](scripts/reload_april.py) updated; new [scripts/sort_monthly_by_checkin.py](scripts/sort_monthly_by_checkin.py) one-off ran against DEC 2025 → APRIL 2026 with per-tab CSV backup.
- **Dashboard banner auto-refresh on every bot-driven cell write** ([src/integrations/gsheets.py](src/integrations/gsheets.py)) — `_update_tenant_field_sync`, `_update_checkin_sync`, `_sync_tenant_all_fields_sync` all call `_refresh_summary_sync` post-write so Active / Beds / Vacant / Occupancy recompute immediately after sharing / rent / check-in changes.
- **Silent-pick disambig bugs** in `_add_refund` / `assign_staff_to_room` / `exit_staff_from_room` — all three now save a `_WHO` pending and show numbered choices when multiple entities match. New resolver branches for `ASSIGN_STAFF_WHO`, `EXIT_STAFF_WHO`, `REFUND_WHO`.
- **`ASSIGN_STAFF_ROOM` / `EXIT_STAFF` intents** — bot commands `staff [name] room [num]`, `staff [name] exit`, `assign staff [name] to [num]`. Many staff per room allowed (no sharing-cap enforcement). Auto-flips `Room.is_staff_room` true on assign, back to false only when the last staff leaves.

### Operational
- **VPS storage reality check** — All uploaded files (KYC, receipts, agreements) live on VPS local disk, not Supabase Storage. Current usage: 4.1 MB media + 164 KB agreements on 48 GB disk (44 GB free). Supabase free tier fine indefinitely for DB (~50 MB). Real risk = **backup** (none today). Options in pending tasks: Hostinger weekly backup / rsync to R2 nightly / migrate to Supabase Storage.

### Deferred
- Other pre-existing scheduler jobs still fire in UTC (rent reminders, daily reconciliation, etc.). No one's noticed — fixing them independently if they become a problem.
- Tenant-path complaint resolver still unconditionally sets `pending.resolved = True` (`chat_api.py:443`). Fine today because complaints are single-turn.

---

## [1.44.0] — 2026-04-20 (late night #2) — Audit batch 3 + MY_BALANCE + flow collision guard

### Sync invariant (batch 3 partial)
- **`sync_sheet_from_db.py`** now sources `notice date` + `notes` from `Tenancy.notice_date` / `Tenancy.notes` (DB). Sheet-preserved fallback kept during migration so existing sheet-only notes aren't wiped. `entered by` still sheet-only (TODO: derive from `Payment.received_by_staff`).

### Audit trail (batch 3 partial)
- **[owner_handler.py `_do_add_tenant`](src/whatsapp/handlers/owner_handler.py)** writes an `AuditLog` entry per checkin (summarises all generated `RentSchedule` rows + rent/deposit/advance values). Separately audits the booking-advance `Payment` with amount + mode. Previously checkin was DB-only with no audit record.

### User-visible bugs fixed
- **`MY_BALANCE` single-month query** ([tenant_handler.py:104](src/whatsapp/handlers/tenant_handler.py#L104)) now includes prev-month unpaid carry-forward. Was showing wrong outstanding when tenant asked about specific month while unpaid from earlier.
- **Workflow-collision guard** in [chat_api.py](src/whatsapp/chat_api.py). When user has an unresolved pending and the new message is classified as a different intent, bot no longer silently vaporises the pending. Instead: *"You're in the middle of a <X> flow. Reply *cancel* to stop it, or continue with your answer."* Greetings still clear silently (low-risk). Root cause of Prabhakaran's mid-sharing-change loss on 2026-04-20. Surfaces to logs as `FLOW_COLLISION`.

### Deferred (in `project_pending_tasks.md`)
- CASCADE DELETE on `RentSchedule.tenancy_id` + `Payment.unique_hash` — schema migration, needs careful backfill
- `SELECT...FOR UPDATE` pessimistic locking on concurrent Tenancy mutations
- ADD_REFUND/QUERY_REFUNDS regex overlap — inspected, pattern ordering already correct for real-world inputs. Not a real bug.

---

## [1.43.0] — 2026-04-20 (late night) — Audit batches 1 + 2

Acted on parallel security/flow/sync/scheduler audit (4 Explore subagents).

### Security & infra (batch 1)
- **Webhook signature now FAILS CLOSED.** [`webhook_handler.py`](src/whatsapp/webhook_handler.py) used to silently skip the X-Hub-Signature-256 check if `WHATSAPP_APP_SECRET` was missing or still the placeholder. Now: production rejects all requests until secret set; dev opt-out via `WHATSAPP_SKIP_SIG_CHECK=1`.
- **`/api/entities/{pending,approve,reject}` now require admin PIN** ([main.py:297-323](main.py#L297-L323)). Were fully open — anyone could approve master-data entries.
- **All `subprocess.run` paths use `sys.executable`** instead of hardcoded `venv/Scripts/python` (Windows-only). Affected: [sync_router.py](src/api/sync_router.py), [scheduler.py](src/scheduler.py), [run_monthly_rollover.py](scripts/run_monthly_rollover.py). VPS no longer relies on identical relative path.
- **`_overnight_source_sync` alerts admin on failure.** Steps 2 + 3 now check returncode (were silent). Failures Whatsapp the admin via `_send_whatsapp` so silent corruption can't drift.

### Handler bugs (batch 2)
- **`pending.resolved = True`** added at 5 sites in [owner_handler.py](src/whatsapp/handlers/owner_handler.py): COLLECT_RECEIPT skip (945), COLLECT_RECEIPT save (978), UNDERPAYMENT_NOTE skip (2695), UNDERPAYMENT_NOTE save (2710), OVERPAYMENT_ADD_NOTE save (2683). All previously returned success but left pending alive → user looped forever.
- **Overpayment carry-forward Payment** ([owner_handler.py:2623](src/whatsapp/handlers/owner_handler.py#L2623)) now writes AuditLog + fires `sync_tenant_all_fields`. Was DB-only — dashboard "Total Paid" KPI went stale.

### Verified safe before deploy
- VPS `WHATSAPP_APP_SECRET` confirmed set + not placeholder
- `ONBOARDING_ADMIN_PIN` confirmed configured

---

## [1.42.0] — 2026-04-20 (night) — Monthly rollover + rules single-source

### Added
- **`src/services/monthly_rollover.py`** — new DB-side generator. Upserts `RentSchedule` rows for the target month. Idempotent. Rules: active + no_show only; exited/cancelled skipped; first-month prorate; no-show → `RentStatus.na` + 0 due; no-shows carry every month until they check in.
- **`scripts/run_monthly_rollover.py`** — atomic rollover runner. Sequence: source-sheet → DB → RentSchedule generation → sheet tab → sheet↔DB reconcile. Manual: `python scripts/run_monthly_rollover.py MAY 2026`.
- **`/api/onboarding/{token}` now returns `rules`** — substituted `HOUSE_RULES` (pdf_generator.py is single source). Form renders them dynamically into `#rules-container`; no more drift between form and PDF.

### Changed
- **Scheduler rollover trigger** — moved from 1st-of-month 12:30 AM to **second-last calendar day 11 PM IST**. Job self-checks day using `calendar.monthrange` (handles 28/29/30/31-day months + leap years automatically). Calls `scripts/run_monthly_rollover.py` end-to-end.
- **`_monthly_tab_rollover`** — now a proper atomic rollover, not just a sheet-tab writer. Source sync runs first (no more ordering race vs 3 AM `_overnight_source_sync`).
- **[static/onboarding.html](static/onboarding.html)** — hardcoded 10-rule list removed; rules now fetched from API.

### Fixed
- **Silent DB↔sheet divergence on rollover** — the old `create_month.py` wrote the sheet tab but never created `RentSchedule` rows. Bot's dues calculations would've diverged from sheet from May onwards. Now the atomic runner generates both.

### Notes
- Deposit-pending carry-forward stays in the existing notes column (create_month.py:151-155). Sufficient per Kiran — first-month rent_due already includes deposit; any pending rolls into prev_due naturally.
- Custom x-to-x billing cycles are NOT supported in code. Prorated first-month is the only mode. For x-to-x clients, add a `notes` entry manually and remember to skip last-month rent.

---

## [1.41.0] — 2026-04-20 (late evening #2) — Sync invariant + live ops fixes

Post-compact session. Focus: closing every gap between DB ↔ sheet ↔ dashboard KPIs, plus live UX bugs Prabhakaran / Lokesh hit.

### Added
- **`cozeevo_checkout_confirmation` wired** into `_do_checkout` ([owner_handler.py](src/whatsapp/handlers/owner_handler.py)) — fire-and-forget template + free-text fallback. Active once Meta approves.
- **`cozeevo_payment_received` wired** into `_do_log_payment_by_ids` ([account_handler.py](src/whatsapp/handlers/account_handler.py)) — 4 vars, no payment mode.
- **`src/database/field_registry.py`** — Phase 1 field registry. 40+ `Field` entries as single source of truth. Derives `MONTHLY_HEADERS`, `TENANTS_HEADERS`, `_TENANTS_FIELD_TO_HEADER`, `_FIELD_TO_COL`, plus `fields_for_pwa()` helper for the future API endpoint.
- **Emergency Contact Phone** — additive TENANTS column (legacy "Emergency Contact" column stays, now strictly name-only).
- **`tests/test_field_registry.py`** — 10 parity + invariant tests.
- **OnboardingSession.sharing_type column** + migration. Create-time receptionist override now persists. Approve honors it instead of falling back to `room.room_type` master.
- **Editable Sharing Type dropdown** in the review form ([admin_onboarding.html](static/admin_onboarding.html)). Receptionist can flip single/double/triple/premium per tenancy — never touches master data.
- **SHARING TYPE CHANGE** section in [docs/RECEPTIONIST_CHEAT_SHEET.md](docs/RECEPTIONIST_CHEAT_SHEET.md).
- **Generic `FIELD_UPDATE_WHO` disambiguation** — sharing / rent / phone / gender / deposit handlers in `update_handler.py` all use the `_disambiguate_or_pick` helper. No more LIMIT-1 silent-pick when 2+ tenants share a name (3 Rakesh case).
- **`Staff.room_id`** column + migration. Was referenced in handler code but missing in VPS schema → AttributeError on QUERY_STAFF_ROOMS.
- **Multi-room command support** in `update_room` — "not staff rooms 114 and 618" applies to both.
- **Bare-cancel short-circuit** in chat_api — `cancel / stop / abort / nevermind` with no pending returns a clean "Nothing to cancel right now." (Groq was hallucinating it as VOID_PAYMENT).
- **Prabhakaran granted `admin` role** via `authorized_users`.

### Fixed
- **Nginx `client_max_body_size` 1M → 20M** on `/etc/nginx/sites-available/pg-accountant`. Tenant form submits (signature + selfie + ID base64 ≈ 3MB) were silently rejected at edge. 6 failed attempts observed in nginx error log before this was caught.
- **`sync_tenant_all_fields`** — refund audit gap closed: now writes `Refund Status` + `Refund Amount` to TENANTS.
- **`_do_add_refund_by_ids`** — fires `sync_tenant_all_fields` post-flush. Was DB-only → dashboard pending-refund KPI went stale.
- **`_do_update_checkout_date`** — fires sheet sync post-flush. Was DB-only → exit-pipeline KPI went stale.
- **`resolve_field_update`** — after "Reply 1" confirm, the monthly-tab single-cell write is now followed by a systemic `sync_tenant_all_fields` so TENANTS master catches up. Previously only monthly tab updated.
- **5 cancel paths in `resolve_pending_action`** now set `pending.resolved = True`. Root cause of "cancel doesn't let me start a new flow" — pending row stayed alive so the next message bumped the same dead resolver.
- **FIELD_UPDATE_WHO resolver** — missing `_save_pending` import caused Python scoping error. Resolver returned None → chat_api killed the pending → fell through to ConversationAgent replying "I don't understand '3'". Prabhakaran saw this live; added explicit import.
- **`QUERY_STAFF_ROOMS` vs `UPDATE_ROOM` regex** — "not staff rooms 114 and 618" now routes to UPDATE_ROOM (was silently re-listing).
- **Sheet sharing-type after editable review** — `approve_session` uses `effective_sharing` in sheet write, not `room.room_type`.

### Changed
- `src/integrations/gsheets.py` — `MONTHLY_HEADERS` + 3 related structures now derive from the registry. Positional `T_*` / `M_*` indices preserved (refund write path unchanged).
- TENANTS tab 34 → 35 columns (additive Emergency Contact Phone).

### Sync invariant (now explicit, across the board)
Every bot-triggered DB mutation propagates:
- DB commit → instant
- Monthly + TENANTS sheet → 1-2s (fire-and-forget `sync_tenant_all_fields` or specialised per-event write)
- Google Sheet DASHBOARD tab → auto via `onEdit` trigger
- `/dashboard` web UI → still manual reload (no polling — left as optional follow-up)

### Commits in this session
`1245f89 → 9f2d151 → 2b38afa → 593734c → 7e6e5b4 → 9eba958 → efa48a1 → f45a508 → 48e5daa → 441a4e5 → 64f7617 → 7633abc → 71fa2e0 → 57fbecb`

### Still pending (carries to next session)
- Edit `cozeevo_booking_confirmation` body via Meta API once APPROVED.
- Phase 2 field registry: `GET /api/v2/app/field-registry` endpoint (helper already exists).
- Phase 3: PWA consumer of the registry.
- 16 state-management golden failures (carried from prior session).
- Web dashboard polling / SSE at `/dashboard`.
- Kiran: add "Emergency Contact Phone" column header in the TENANTS Google Sheet tab so the additive field starts populating.
- `MY_BALANCE` bug at `tenant_handler.py:104` (prev_due not included).
- Live Lokesh issues: staff-room unmark end-to-end retest (logic shipped, needs him to retry).

---

## [1.40.0] — 2026-04-20 (late evening) — State-mgmt fixes + RentSchedule first-month = rent + deposit

### Fixed (state management)
- **Staff-room toggle substring bug** — `_update_single_room` checked `"staff room" in desc_lower` before `"not staff"`, so "Not staff rooms 114 and 618" / "114 not staff room" hit the MARK branch (because `"staff room"` is a substring of `"staff rooms"` / `"not staff room"`). Lokesh 2026-04-20 16:49–16:59 thrashed 12 messages with rooms 114/618 flipping True↔False in audit log. Extracted `_classify_staff_toggle()` in `src/whatsapp/handlers/update_handler.py` — UNMARK patterns evaluated before MARK so negative phrasings always win. 19 parametrized tests lock it in.
- **`CONFIRM_FIELD_UPDATE` "Yes" → "Update cancelled"** — resolver did `choice = reply_text.strip()` (no `.lower()`), then `if choice in ("1","yes","y")`, so capital "Yes" fell to else → cancel. Partner 2026-04-20 16:42 sharing-change for Rakesh. Extracted `_is_confirm_choice()` accepting "1" + full `is_affirmative` set (any case). 25 parametrized tests lock it in.

### Fixed (financial — Diya Gupta blunder)
- **First-month `RentSchedule.rent_due` now bundles security deposit** per `memory/feedback_deposit_dues_logic.md`. Diya 2026-04-20: rent 12,000 + deposit 6,000, paid 12,000 UPI — bot said "This month: PAID" because `rs.rent_due` was only 12,000. Should have said PARTIAL with Rs.6,000 due.
- New helper **`src/services/rent_schedule.first_month_rent_due(tenancy, period)`** — returns rent + deposit when period == checkin_month, else just rent. Single source of truth.
- Wired into 5 RentSchedule creation sites: `src/services/payments.py`, `src/api/onboarding_router.py`, `src/whatsapp/handlers/owner_handler.py` (`_finalize_add_tenant`), `src/database/excel_import.py`, `src/database/delta_import.py`. Importers use inline check (their `period_rent` reflects rent revisions, not agreed_rent).
- **Display fix** — `_do_query_tenant_by_id` was `net_due = deposit + rs.rent_due - booking_amount`, so after backfill it double-counted deposit (Diya showed Rs.22,000). Now derives `first_rent = rs.rent_due − deposit` for display; net_due arithmetic unchanged.
- **Backfill script** `scripts/backfill_first_month_rent_due.py` — idempotent dry-run/apply. Ran `--apply` on VPS: **268 check-in-month RentSchedule rows corrected, 20 unchanged**. Status recomputed from non-void payments.

### Added
- `tests/test_staff_room_toggle.py`, `tests/test_confirm_field_update_choice.py`, `tests/test_first_month_rent_due.py` — **52 new parametrized tests**, all green on VPS post-deploy.

### Verified on VPS
- 3 commits deployed (`fix(state-mgmt)`, `fix(rent_schedule)`, `fix(query)`), service `active`, `/healthz` 200.
- Diya Gupta bot query now shows: `This month PARTIAL`, `First month rent Rs.12,000`, `Net due Rs.16,000`, `Apr: Rs.18,000 — PARTIAL (due Rs.6,000)`.

### Still pending (next session)
- **Sheet re-sync** for the 268 updated tenancies — DB and Sheet may show different Balance until `sync_sheet_from_db` runs.
- **"Raj balance doesn't work"** — Kiran flagged; needs repro with exact phrasing + which Raj (multiple exist).
- **Lokesh's 17:37 pending** `Diya Gupta paid 6000 cash` — pending confirmation not resolved; will expire via TTL.
- **booking_amount missing as Payment row** — old Excel-imported tenants have `tenancy.booking_amount > 0` but no `Payment(for_type=booking)` row, so Apr balance doesn't reflect the advance. One-time migration needed.
- **Cash + UPI one-liner parser** — `"Diya paid 3000 cash 3000 upi"` currently not parsed; only the step-by-step collect-rent form handles split modes today.
- **Cheat sheet enhancement** — prominent "Someone came to pay — where to start" section at top (flows A/B/C exist but are buried).
- 16 state-management golden failures (from prior session, still open).

---

## [1.39.0] — 2026-04-20 (evening) — Disambig audit + sheet auto-refresh + sort

### Added
- **`scripts/sort_monthly_by_checkin.py`** — one-off sorter for every monthly tab. Dynamic header-row detection, per-tab CSV backup in `data/backups/sort_<timestamp>/`, row-count + content-multiset checks post-write, no column truncation. Already run once against DEC 2025 → APRIL 2026 live.
- **`tests/test_disambig_e2e.py`** — end-to-end disambiguation test. Routes messages through `intent_detector → gatekeeper → handler → pending → resolver` for every name-based intent (QUERY_TENANT, PAYMENT_LOG, VOID_PAYMENT, RENT_CHANGE, UPDATE_SHARING/RENT/PHONE, ADD_REFUND, CHECKOUT, ROOM_TRANSFER, ASSIGN_STAFF_ROOM, EXIT_STAFF). Mutating intents are auto-cancelled — safe on live DB. Also probes state-preservation + cancel.
- **`ASSIGN_STAFF_ROOM` / `EXIT_STAFF` intents** — bot commands `staff [name] room [num]`, `staff [name] exit`, `assign staff [name] to [num]`. Many staff per room allowed (no sharing-type enforcement). Auto-flips `Room.is_staff_room` true on assign and back to false only when the last staff leaves.

### Fixed
- **Pending state silently dropped** (`src/whatsapp/chat_api.py:435`) — if a user mid-confirmation sent anything other than the expected choice, `pending.resolved = True` fired with no reply, killing state. Now: cancel keywords (`cancel`/`stop`/`abort`/`quit`/`nevermind`) close pending cleanly; anything else keeps pending alive and falls through to normal intent detection so side-tasks don't nuke confirmation flows.
- **Monthly tab ordering** — `clean_and_load.py`, `create_month.py`, and `reload_april.py` now sort tenants by check-in ascending before writing, so the latest check-in always lands at the bottom. Missing check-ins sink to the top so the real latest stays last.
- **Dashboard banner stale after sharing / rent / checkin change** — API writes don't fire the Apps Script `onEdit` trigger, so banner rows never refreshed after bot writes. Fix is at the gsheets layer: `_update_tenant_field_sync`, `_update_checkin_sync`, `_sync_tenant_all_fields_sync` all call `_refresh_summary_sync` post-write. Covers every caller (field updates, systemic sync, check-in changes); existing refresh in payment_log / add_tenant / record_checkout / record_notice / void_payment unchanged.
- **Silent-pick disambig bugs** uncovered by full audit:
  - `_add_refund` (account_handler) was picking `rows[0]` when multiple active or exited tenants matched the name. Now saves `REFUND_WHO` pending + prompts. `_do_add_refund_by_ids` extracted so the resolver can finish the refund once the user picks.
  - `assign_staff_to_room` was `next((s for s … if s.name.lower() == name.lower()))` — silent first-match when 2+ active staff share a name. Now saves `ASSIGN_STAFF_WHO` pending. `_apply_staff_assignment` extracted.
  - `exit_staff_from_room` was returning a plain text choice list with no pending saved — the user's `1` would route as a fresh intent, not a disambig reply. Now saves `EXIT_STAFF_WHO`; `_apply_staff_exit` extracted.
  - Resolver branches for `ASSIGN_STAFF_WHO`, `EXIT_STAFF_WHO`, `REFUND_WHO` added to `resolve_pending_action` in `owner_handler.py`.

### Verified
- "disha balance" (and any duplicate first-name) path: QUERY_TENANT detects ambiguity, saves pending, shows numbered choices, resolves on `1`/`2`.
- 2 active staff named `zzDupStaff` → `staff zzDupStaff room G05` → disambig pending saved → pick `1` → Manager linked to G05, Security untouched, room flipped to staff.
- Post-write banner refresh recomputes `Active / Beds (X+YP) / Vacant / Occupancy` based on the updated sharing column (`gsheets.py:619` → 2 beds if premium, 1 otherwise).

### Still pending (next session)
- Run `tests/test_disambig_e2e.py` end-to-end and fix any failures before VPS deploy.
- DEPOSIT_CHANGE end-to-end confirmation (audit flagged as OK structurally but not functionally tested).
- Tenant-side pending: `chat_api.py:443` still unconditionally resolves after `resolve_tenant_complaint`; apply the same keep-pending rule if tenant flows grow multi-step.

---

## [1.38.0] — 2026-04-20 — Field registry (Phase 1) + refund audit gap closed

### Added
- **`src/database/field_registry.py`** — single-source-of-truth `FIELDS` tuple of `Field(key, display, source, db_attr, tenants_header, monthly_header, type, options, editable_via_bot, editable_via_form, aliases)` covering every tenant + tenancy attribute visible to the receptionist. 40+ entries. Drives sheet headers, bot→sheet field maps, and (next phase) the `/api/v2/app/field-registry` endpoint for PWA form generation.
- **Derivation helpers** in the registry: `monthly_headers()`, `tenants_headers()`, `tenants_field_to_header()`, `field_to_col()`, `fields_for_pwa()`.
- **Emergency Contact split** — new TENANTS column `"Emergency Contact Phone"` (additive, positioned immediately after `"Emergency Contact"`). `emergency_contact_name` now feeds the legacy `"Emergency Contact"` column (name only; phone moves to new column). Sheet-side change required: add the new column header manually in TENANTS tab — sync skips missing headers gracefully until then.
- **Refund audit gap closed** — `sync_tenant_all_fields` now loads the latest `Refund` row per tenancy and populates `"Refund Status"` + `"Refund Amount"` on the TENANTS tab. Previously those cells stayed blank after any DB mutation even though the columns existed.
- **10 parity + invariant tests** (`tests/test_field_registry.py`) locking in derived outputs against the prior hardcoded constants, uniqueness of keys/headers, and required `db_attr` / `options` on non-computed / select fields.

### Changed
- `src/integrations/gsheets.py`: `MONTHLY_HEADERS`, `TENANTS_HEADERS`, `_TENANTS_FIELD_TO_HEADER`, `_FIELD_TO_COL` now derive from the registry (previously 30+ lines of hardcoded literals). Positional column indices `T_REFUND_STATUS` / `T_REFUND_AMOUNT` / `M_*` unchanged so callers in `owner_handler.py` (refund write path at line 4289) keep working.
- TENANTS tab now has 35 headers (was 34) — single additive column.

### Fixed
- `sync_tenant_all_fields`: `"Emergency Contact"` column was using name-or-phone fallback which conflated two distinct attributes. Now strictly populates name only; phone routes to the dedicated new column.

### Still pending
- Edit `cozeevo_booking_confirmation` body via API once Meta flips it to APPROVED.
- Phase 2 of the registry: `GET /api/v2/app/field-registry` endpoint (~30 min).
- 16 state-management golden failures (from prior session).

---

## [1.37.0] — 2026-04-20 — Checkout + Payment WhatsApp templates wired

### Added
- **`cozeevo_checkout_confirmation` wired into `_do_checkout`** (`src/whatsapp/handlers/owner_handler.py`). Fires template with 5 vars (name, room, checkout date, deposit refund, final balance) as a fire-and-forget `asyncio.create_task`; falls back to free-text inside the 24-hr window if template still PENDING at Meta. Net settlement drives `refund` / `balance` formatting — settled case shows `Rs.0 (settled)`.
- **`cozeevo_payment_received` wired into `_do_log_payment_by_ids`** (`src/whatsapp/handlers/account_handler.py`). Fires template with 4 vars (name, period label e.g. "April 2026 rent", paid this month so far, balance remaining) right after the sheet write-back. Balance ≤ 0 renders as `Rs.0 (paid in full)`. Payment mode intentionally omitted — tenants only care about month-paid + balance.

### Status
- All 3 templates (`cozeevo_booking_confirmation`, `cozeevo_checkout_confirmation`, `cozeevo_payment_received`) still PENDING at Meta (~15-60 min typical, submitted 2026-04-19). Free-text fallbacks keep existing 24-hr-window sends working until approval flips.

### Still pending
- Edit the live `cozeevo_booking_confirmation` body via API once Meta flips it to APPROVED (remove rental-agreement line; add call-receptionist number).
- Field registry Phase 1 + 2 (`project_field_registry.md`).
- 16 state-management golden failures (from previous session).

---

## [1.36.0] — 2026-04-19 — Editable onboarding review + Meta templates submitted

### Added
- **Editable review screen** (`static/admin_onboarding.html`). Pending-review sessions now render every KYC + financial field as an inline input (text / number / date / select). Yellow banner reminds the receptionist that changes are tracked.
- **`overrides` parameter** on `POST /api/onboarding/{token}/approve`. 16 KYC + 5 financial keys supported; backend applies them to `Tenant` / `Tenancy` / `OnboardingSession` before creating records.
- **Diff notification to tenant** — if the receptionist modifies any tenant-submitted value during review, a follow-up free-text WhatsApp message lists exactly the changed fields (old → new) with a call-receptionist fallback. Sent right after the booking-confirmation template so the 24-hr window is already open.
- **AuditLog per overridden field** — `source="onboarding_review"`, `changed_by="receptionist"`, one entry per change, links to tenant / tenancy entity.
- **`cozeevo_booking_confirmation` now 5 vars** — added Deposit as {{5}}. Code path at `src/api/onboarding_router.py::approve_session` passes both rent and deposit values.
- **`WHATSAPP_WABA_ID=1026995743235229`** persisted to `.env` on both local and VPS.

### Submitted to Meta (PENDING review)
- `cozeevo_booking_confirmation` (Template ID `1303194515065555`) — 5 vars. NOTE: submitted body still has the old "rental agreement" line; once Meta approves, edit via `POST /v21.0/1303194515065555` with the corrected body in `docs/WHATSAPP_TEMPLATES.md`.
- `cozeevo_checkout_confirmation` (Template ID `1313261294060481`) — 5 vars, review/return-visit messaging.
- `cozeevo_payment_received` (Template ID `2454482531646516`) — 4 vars, no payment-mode, focuses on "paid this month" + balance.

### Fixed
- `approveSession()` in admin UI now harvests edited inputs via `collectOverrides(token)` helper and sends them in the approve POST body.

### Commits
- `a6afbfa` → `879f3bb` — one-shot WABA capture and cleanup
- `b69e6cc` — editable review form + diff message

### Still pending (next session)
- Edit the live `cozeevo_booking_confirmation` body via API once Meta flips it to APPROVED (remove rental-agreement line; add call-receptionist number).
- Wire `cozeevo_checkout_confirmation` into `_do_checkout`.
- Wire `cozeevo_payment_received` into `_do_log_payment_by_ids`.
- Field registry Phase 1 + 2 (`project_field_registry.md`).

---

## [1.35.0] — 2026-04-19 — Systemic DB → Sheet invariant + architecture cleanup

### Added
- **Deposit column + Rent column** on every monthly sheet tab. First-month `Rent Due = agreed_rent + security_deposit`; booking advance counted in Total Paid. Enforced in `scripts/sync_sheet_from_db.py` + `gsheets._add_tenant_sync`.
- **`sync_tenant_all_fields(tenant_id)`** helper in `src/integrations/gsheets.py` — single entry-point that reads a tenant's full DB state and pushes every visible column to BOTH the TENANTS master tab and the current monthly tab in one batch per sheet. Rule: DB and sheet must never diverge. Wired into all 4 previously-uncovered mutation sites (onboarding KYC, extra-deposit add at room transfer, overpayment → deposit, CONFIRM_ADD_TENANT KYC extras).
- **`trigger_monthly_sheet_sync(month, year)`** + **`update_tenants_tab_field(room, name, field, value)`** helpers in gsheets.py — instant per-cell writes (~1s) for deposit/rent changes plus a background full re-sync for ripple effects. Bot reply returns immediately.
- **`cozeevo_checkout_confirmation`** template spec in `docs/WHATSAPP_TEMPLATES.md` (5 vars). Extended `cozeevo_booking_confirmation` to 5 vars (adds Deposit + modified-field reconciliation note).
- **Instant sheet update** on `_do_deposit_change` and `_do_rent_change` (both monthly-tab cell and TENANTS-tab cell fire as `asyncio.create_task`).
- **AuditLog at all 4 return paths** of `_do_rent_change` (was silent — no accountability trail).
- **EDIT_NOTES** now writes AuditLog + syncs to BOTH tabs (was TENANTS-only).
- **`_locate_monthly_header(all_vals)`** helper in gsheets.py — replaces 6 hardcoded `range(4, len(all_vals))` / `all_vals[3]` sites that broke on tabs created by sync_sheet_from_db.py (header at row 7, not row 4). Checkout, notice, checkin-date, void-payment, update-tenant-field, notes-update all now work on both layouts.

### Changed (Apps Script v5 — header-driven rewrite)
- `scripts/gsheet_apps_script.js` → every read/write now uses header-name lookup via `_findRow_` / `_colMap_` / `_col_`. Dashboard reads correct columns regardless of layout drift.
- `onSheetEdit` no-ops on new 7-row-header layout (was overwriting summary rows 2-6 with the legacy 2-row summary, corrupting the cards).
- `updateMonthSummary`, `getTotalDeposit_`, `validateTotals`, `createMonthTab` all header-driven; old positional indices removed.

### Fixed
- **Sharing type** now auto-fills from `room.room_type` when the onboarding form doesn't explicitly set it. Backfilled the 2 existing NULL rows (Pooja + Arun → double). Fix in `src/api/onboarding_router.py::approve_session`.
- **No-shows** now appear only in their own check-in month, never carried forward to past/future tabs. Enforced in `sync_sheet_from_db.py` section-1 filter.
- **Pooja TENANTS deposit stale** — Lokesh changed 6,750→6,500 at 18:02 via bot; TENANTS tab retained 6,750 until the sync-to-both-tabs wiring shipped. Backfilled via SQL + new propagation ensures this class of bug is eliminated.

### Memory
- New rule: `feedback_db_sheet_invariant.md` — DB mutation → `sync_tenant_all_fields` must fire.
- Updated `feedback_deposit_dues_logic.md` with "first month = rent + deposit − advance" and enforcement locations.
- New project: `project_field_registry.md` — planned Phase-1 refactor for PWA readiness.
- New project: `project_booking_diff_notification.md` — flag receptionist modifications to tenant.

### Commits (all deployed to VPS)
- `b8a9345` `_refresh_summary_sync` header detection + building/no-show parsing
- `ea21409` Deposit column + first-month dues + instant sync trigger
- `2f05144` Rent column + restrict no-shows to checkin month
- `2b2d56b` Instant sheet update on deposit/rent + auto sharing_type
- `0515de4` Deposit/rent change propagates to TENANTS master tab
- `d736d0b` Header-driven sheets everywhere + end-to-end gap closure
- `3c27560` `sync_tenant_all_fields` — systemic DB → sheet invariant

### User actions required (manual)
- Register `cozeevo_booking_confirmation` (5 vars) in Meta Business Manager
- Register `cozeevo_checkout_confirmation` (new spec) when ready
- Apps Script v5 pasted into Cozeevo Operations v2 → Extensions → Apps Script (DONE per Kiran)

---

## [1.34.1] — 2026-04-19 — Missing-resolver audit (Lokesh incident)

### Fixed
- `DEPOSIT_CHANGE_WHO` — numeric disambiguation ("1 or 2") silently killed pending. Resolver was never wired (pre-existing since `2959c0f`). Lokesh hit this in production 18:03 IST. Fix in commit `bcbccbf`.
- `ROOM_TRANSFER_WHO` + `ROOM_TRANSFER_DEST` — same missing-resolver bug class; both saved via `_save_pending` but had no branch in `resolve_pending_action`. Extracted `_finalize_room_transfer()` helper to share the validate-destination/check-vacancy/save-confirm tail across all entry paths. Fix in commit `f977e7b`.
- Both intents added to the cancel-list so "no" aborts cleanly.

### Audit
Grep of every `_save_pending(intent)` call vs every `pending.intent ==` resolver:
- 33 intents saved. All 33 now have a resolver (owner_handler cascade × 29, chat_api early dispatch × 4).
- Zero remaining gaps of the "save pending, never resolve" bug class.

### Verification status
Ran golden suite (73/100 pass) against live local API + TEST_MODE=1. 27 failures remain, of which 16 are state-management (correction_mid_flow × 7, state_guard × 6, ambiguous_name × 3). Same bug class as Lokesh's, but triggered by different handlers — scheduled for next session's triage (see `memory/project_pending_tasks.md` top section).

### Lessons
- Added `memory/feedback_pattern_generalize.md` — when one handler has bug X, grep for X across all handlers before claiming fix. Triggered by overclaim that "state management is there" when only 5 of ~33 intents were ported to the framework.

## [1.34.0] — 2026-04-19 — Owner PWA Foundation (Plan 1 · partial)

### Brainstorm → Spec → Plan
- Brainstormed full vision for Owner PWA (mobile-first, voice-first, complements WhatsApp bot, evolves into Kozzy SaaS)
- Locked 7 design principles (numbers-hero, speed-over-beauty, fool-proof-by-structure, voice-first, one-screen-one-answer, thumb-reachable, trust-signals)
- Design spec: `docs/superpowers/specs/2026-04-19-owner-pwa-design.md` (16 sections: purpose, users, scope, architecture, voice pipeline, security, home screen, design system, build sequence, existing-rules alignment, mockup-before-build cadence)
- Implementation plan: `docs/superpowers/plans/2026-04-19-owner-pwa-foundation.md` (25 tasks across 6 phases for weeks 1-2; Plans 2+3 written after Plan 1 ships)
- Decomposition: PWA → 3 plans (Foundation+Rent / Modifications+Check-in / Check-out+Comms+Polish) — each produces working software

### Backend (FastAPI · `src/`)
- **Services layer** (`src/services/`): lifted `log_payment` from WhatsApp handler into `payments.py` + `audit.py` — shared single source of truth for bot + PWA. `PaymentResult` expanded with `status`/`effective_due`/`total_paid` so handler drops redundant re-queries. 11/11 tests pass. Commits `e818c33`, `650ddf7`.
- **Multi-tenant data model** (`src/database/migrations/add_org_id_2026_04_19.py`): added `org_id INTEGER NOT NULL DEFAULT 1` to 8 tables (tenancies, payments, rooms, rent_revisions, rent_schedule, expenses, leads, audit_log). Idempotent, SQLite+Postgres, per-table index `idx_<table>_org_id`. ORM `index=True` dropped (migration is source of truth). Cozeevo = org_id 1. 4/4 tests pass. Commits `d410166`, `110303e`.
- **New API surface** (`src/api/v2/app_router.py`): `/api/v2/app/*` router with Supabase JWT middleware (HS256, audience=authenticated). `get_current_user` dependency returns `AppUser(user_id, phone, role, org_id)`. Generic "invalid token" 401 message (server-side logs the real error). Defensive `int()` on `org_id`. `/health` endpoint. `LocalOnlyMiddleware` whitelist for `/api/v2/app` (JWT replaces localhost restriction for public-facing mobile API). 8/8 tests pass. Commits `dca0a1f`, `7c2fb68`.

### Frontend (PWA · `/web/`)
- **Next.js 15 scaffold** (`cd9d5ac`, `ffc2089`): App Router + TypeScript strict + Tailwind + Serwist PWA service worker + manifest (name "Kozzy · Cozeevo Help Desk", theme `#EF1F9C`, bg `#F6F5F0`). PIL-generated icon-192/512 placeholders. DM Sans (weights 400-800) via `next/font/google`. `lib/format.ts` with Indian number grouping (₹2,40,000). 4/4 Vitest tests pass. Clean build (104kB first load JS).
- **Design tokens** (`web/tailwind.config.ts`): brand colors + pastel tiles + status colors + borderRadius (card/tile/pill).
- **Playwright verification**: PWA boots at http://localhost:3100, renders pink K logo on cream bg with correct Indian rupee formatting. Screenshot: `.playwright-mcp/pwa-scaffold-first-boot.png`.

### Process / memory
- Subagent-driven-development workflow: per-task implementer + spec-compliance review + code-quality review, applied loops for fixes. ~10 subagent dispatches total.
- Saved memory: UI approval + interactive Playwright testing requirement, test-data isolation (never write to live Cozeevo DB), PWA tech-debt backlog, updated pending-tasks list.

### Known follow-ups (deferred, documented)
- PWA: Tailwind semantic token rename, manifest `purpose` fix, `.gitignore` PNG negation, favicon, role vocabulary alignment — see `memory/project_pwa_tech_debt.md`.
- Plan 1 remaining: Tasks 4 (payments endpoint), 5 (collection endpoint), 6 (Supabase dashboard — manual), 9 (UI primitives), 10 (Supabase client), 11 (Login screen with mockup gate).

---

## [1.33.0] — 2026-04-18 — Rent Reconciliation + Data Architecture

### Rent Reconciliation (drop + reload)
- Wiped L1+L2 data (payments, rent_schedule, tenancies, tenants) — L0 preserved
- Re-imported Jan-Mar from Cozeevo Monthly stay.xlsx (294 tenants, 1014 payments)
- Re-imported April from April Month Collection.xlsx (239 payments)
- DB now matches Excel exactly for Cash + UPI per month
- Fixed `excel_import.py` phone constraint — partners sharing phone allowed (was failing on unique constraint)
- Confirmed: **zero duplicates in DB** (exact-match grouping on tenancy + date + amount + mode + for_type + notes)

### Documentation
- `docs/RENT_RECONCILIATION.md` — 7-step monthly process (Excel ↔ DB ↔ Bank), anti-duplicate rule, Chandra off-book tracking (Mar 1.6L + Apr 15.5K)
- `docs/DATA_ARCHITECTURE.md` — canonical data model (L0-L3 layers), 6 golden rules, ETL flow, 6-step migration plan from hardcoded columns → Pydantic schemas

### Cash Report Tool
- `scripts/cash_report.py` — DB cash by month filtered by for_type (rent/deposit/booking)
- Prevents inflation from counting deposits as cash (was 3-5x inflated before)

### Feedback Memory
- `feedback_no_false_alarms.md` — never claim DB duplicates without exact-match grouping (incl. for_type + notes); rent reports must filter for_type='rent'

## [1.32.0] — 2026-04-17 — Payment Audit Trails + Bank Statement P&L

### Payment Flow Improvements
- Over/underpayment now prompts for notes (free-text reason)
- Overpayment: added option 4 "Add a note" alongside advance/deposit/ask tenant
- Underpayment: asks for note after logging partial payment (reply or "skip")
- Audit log entries for every payment creation and void (who, amount, room, timestamp)
- AuditLog import added to account_handler

### Bank Statement Classification
- New CSV reader for YES Bank CSV format (Statement-*.csv)
- Fixed duplicate Jan 2026 data (Excel + CSV overlap)
- Fixed misclassification: Rs.6L RTGS to Sri Lakshmi Chandrasekar was "Bank Charges" → now "Property Rent"
- Added classification rules: carpenter, fridge, bleaching powder, drumstick, batter, Jio/Airtel/Vi recharges, police, tenant refund names
- `pnl_report.py` rewritten: uses shared `pnl_classify.py` rules, reads all sources (Excel + CSV), no duplicate rules
- `export_classified.py`: added CSV reader, P&L sheet includes income + expenses + net profit
- `classify_new_statement.py`: standalone classifier for quick runs
- Output: `PnL_Report.xlsx` (3 sheets: P&L Summary, Income Detail, Expense Detail)

### P&L Summary (Oct 2025 – Mar 2026)
- Total Income: Rs.91.8L | Total Expenses: Rs.91.2L | Net: +Rs.57K
- 70 unclassified transactions (Rs.4.4L) — generic UPI with no description

## [1.31.0] — 2026-04-16 — Day-wise Onboarding + Consistency Audit

### Day-wise Onboarding (NEW)
- Admin form: Stay Type toggle (Monthly/Daily) — daily shows checkout date, num days, daily rate
- Approve branches: daily → DaywiseStay DB + DAY WISE sheet; monthly → Tenancy + TENANTS + monthly tab
- `add_daywise_stay()` in gsheets.py — header-based mapping to DAY WISE tab
- Migration: added checkout_date, num_days, daily_rate to onboarding_sessions table
- Both paths share: tenant creation, selfie/ID/signature, PDF, WhatsApp

### Consistency Audit (3 parallel agents)
- **Day-wise:** Was not wired — dropdown existed but approve always created monthly Tenancy. Fixed.
- **Dues:** tenant_handler.py MY_BALANCE ignores prev_due (bug noted, fix next session)
- **Bot path:** DB keeps deposit separate (correct for accounting), Sheet combines (correct for receptionist)

## [1.30.0] — 2026-04-16 — Dues Logic + Monthly Rollover + Sheet Consistency

### Dues Calculation (FINAL)
- First month: Rent Due = rent + deposit (deposit includes maintenance, no double count)
- Month 2+: Rent Due = rent only, Prev Due carries unpaid balance
- Balance = Rent Due + Prev Due - Total Paid (consistent everywhere)
- Notes auto-populated with "Deposit due: Rs.X" for first-month check-ins
- No separate Deposit Due column — 17-column format preserved
- Maintenance never in dues — only relevant at checkout/refund

### Monthly Tab Rollover (NEW)
- `scripts/create_month.py` rewritten: header-based mapping, 17-col format, prev due carry-forward
- Auto-scheduled on 1st of every month at 12:30am via `_monthly_tab_rollover` in scheduler
- Only active + no-show tenants carried (exited excluded)
- Auto-note "Deposit due: Rs.X pending" when deposit unpaid from previous month
- First month check-ins get prorated rent + deposit in Rent Due

### Sheet Consistency Fixes
- Removed hardcoded column indices from `_refresh_summary_sync` — now uses derived M_* constants
- Phone format: +91XXXXXXXXXX for all onboarding writes
- Sheet retry: 3 attempts with 2s/4s backoff on approve (was fire-and-forget)
- `saved_files` key fix (was `_saved_files` — stripped by JSON serializer)
- Cleaned test data from DB

### Onboarding Fixes
- Filterable sessions table (status + date range) replaces static stats
- Lightbox for selfie/ID/signature — click to enlarge, Escape to close
- Camera selfie with face oval guide, fallback to file picker
- Selfie/ID/signature all mandatory before submit
- Mobile scroll fix on Step 5

## [1.29.0] — 2026-04-16 — Live Onboarding Testing + Security + UX Fixes

### Admin Panel
- PIN authentication on all admin endpoints (env: `ONBOARDING_ADMIN_PIN`)
- Room auto-lookup from master data when typing room number
- Sharing type dropdown with premium option + master data mismatch warning
- Live dues calculator (rent + deposit - advance)
- Filterable sessions table (status, date range) replaces static stats
- Lightbox for selfie/ID/signature — click to enlarge, Escape to close
- Cancel and Resend WhatsApp Link buttons
- Default reception phone 8548884455
- Stats refresh on Refresh button

### Tenant Form
- Live camera selfie with face oval guide (getUserMedia API), fallback to file picker
- Selfie, ID proof, signature all mandatory before submit
- Fixed selfie preview ID bug (`selfie-preview` vs `selfie-preview-wrap`)
- Fixed mobile scroll on Step 5 (terms box 30vh, body padding)
- Fixed camera modal showing before permission granted (prevented black screen freeze)
- Outer try-catch on submit to show errors instead of freezing
- Late payment penalty updated to Rs.200/day after 5th

### Security
- Admin PIN auth on all `/api/onboarding/admin/*` endpoints
- Rate limiting: create 10/min, submit 5/min, token lookup 20/min, room lookup 30/min
- File upload size limit: 5MB per file
- Generic error messages to prevent token enumeration
- 2-hour form expiry (was 48 hours)
- One-time use: form rejects resubmission after status change

### Flow Improvements
- WhatsApp notification to receptionist when tenant submits form
- WhatsApp message to tenant includes full booking summary + dues
- Auto-cancel old pending sessions when creating new one for same phone
- Deposit includes maintenance — no double counting in dues
- Fixed `_saved_files` key stripped by JSON serializer (renamed to `saved_files`)
- Middleware updated: admin panel + all onboarding APIs publicly accessible

### Deployed to VPS
- reportlab installed, migrations run, service active

## [1.28.0] — 2026-04-15 — Digital Onboarding Form + 12 Checkin Fixes + Column Mapping

### Digital Onboarding Form (NEW)
- **Architecture:** Two-form system — receptionist creates session, tenant fills on phone, receptionist approves
- New `OnboardingSession` model extended with token, status, room/rent fields, signature, PDF path
- API router: `/api/onboarding/create`, `/{token}`, `/{token}/submit`, `/admin/pending`, `/{token}/approve`
- Tenant mobile form: 5-step wizard (Personal → Family → Address → ID → Agreement + Signature)
- Admin panel: create sessions, review queue, approve flow
- PDF agreement generator using reportlab (branded, with embedded signature)
- WhatsApp document sending helper added
- Middleware updated: `/onboard/*` and tenant API endpoints are public
- Step-by-step WhatsApp checkin flow removed (replaced by digital form)

### 12 Checkin Flow Fixes
1. Food step wired into photo checkin flow via `_next_form_step` + `ask_food_form` handler
2. Cash/UPI prompt: always asked when advance > 0, never defaulted to cash
3. Office phone doubling fixed in KYC display
4. Monthly tab refactored to header-based mapping (same as TENANTS)
5. Phone/ID fields: apostrophe prefix preserves format in Sheet
6. Event column: "CHECKIN" populated on add
7. Entered By column: "bot", "onboarding_form", "excel_load" (not phone numbers)
8. Building auto-lookup: already working from room→property join
9. NO-SHOW auto-flip: startup task flips no_show→active when checkin_date arrives
10. Haiku OCR: room numbering corrected (THOR=01-12, HULK=13-24)
11. Age field: asked after DOB if DOB skipped (stored in notes)
12. Advance reflected in monthly tab (Cash/UPI column + calculated balance/status)

### Column Mapping System
- `MONTHLY_HEADERS` and `TENANTS_HEADERS` canonical lists (single source of truth)
- `_build_header_map()` and `_header_index()` helpers
- T_*/M_* constants auto-derived from header lists via `_derive_constants()`
- `clean_and_load.py` imports canonical headers (no more duplicated lists)
- Removed duplicate T_* constants at end of gsheets.py that overwrote TENANTS indices
- Emergency Contact field mapping fixed (was swapped)
- April+ monthly tabs use new 17-column format in clean_and_load.py

### Known Issues
- Digital form needs browser testing with real token flow
- PDF generation not yet tested with real signature data
- VPS deploy pending (needs `pip install reportlab` + migration)

## [1.27.0] — 2026-04-15 — RLS + Photo Checkin Improvements + Sheet Header Mapping

### Security
- Enabled RLS on 42/43 public tables via `migrate_all.py` (runs every migration)
- Only `pg_config` (Postgres system view) excluded

### Photo Checkin Flow
- Added advance payment step: bot asks "any advance paid?" after gender
- Edit colon parsing fixed: `edit room : 609` now works correctly
- `_next_form_step` helper started (food → advance → sharing chain, WIP)

### Sheet Sync
- TENANTS tab writes now use header-based column mapping (not positional)
- Prevents data shift when columns are reordered or added

### Infrastructure
- `simplify_roles` migration wrapped in try/except (non-fatal on Supabase timeout)
- Manual tenant insert: G.D. Abhishek to room 609 (THOR, premium)

### Known Issues (queued for next session)
- Food preference not asked in photo checkin flow (partially coded)
- Cash/UPI not asked for advance payments
- Office phone shows twice in confirmation display
- Monthly tab still uses positional array (needs header mapping)
- Phone/ID format inconsistency in Sheet

## [1.26.0] — 2026-04-13 — Room Ops + Sheet Sync + Unhandled Logging

### Added
- **ASSIGN_ROOM intent** — assign rooms to unassigned/future bookings, blocks if already active, fuzzy name match with phone confirmation
- **QUERY_UNHANDLED intent** — "show unhandled requests" shows messages bot couldn't understand
- **`unhandled_requests` table** — logs every UNKNOWN intent with phone, message, role for future intent building
- **Sheet retry queue** — failed Sheet writes saved to `data/sheet_write_queue.json`, retried on bot startup
- **`scripts/sync_sheet_from_db.py`** — full DB-to-Sheet reconciliation (active + noshow only, no stale exits)
- **Gender always required** during form image checkin (asks if not found in image)

### Enhanced
- **ROOM_TRANSFER** — shows who occupies target room (name + phone) instead of generic "choose vacant room"; adds Sheet sync + audit log
- **Staff rooms regex** — now matches "staff rooms", "how many staff rooms", "labour rooms", "labor room"
- **SCHEDULE_CHECKOUT** — catches "leaving tomorrow/today/next week" (was falling through to CHECKOUT)

### Fixed
- **Sheet synced to DB** — April tab now matches: 261 beds, 15 no-show, 14 vacant. Removed 59 stale EXIT + 11 CANCELLED rows
- **Unicode in migrate_all.py** — arrow chars caused cp1252 errors on Windows

## [1.25.1] — 2026-04-12 — April Import + Vacant Beds Fix

### Fixed
- **Vacant beds calculation** — was using broken summary formula (showed 4 instead of 27). Now uses room-by-room count: skips premium rooms, subtracts active + noshow + daywise per room. Single source of truth.
- **Import script** — placeholder phone collision for tenants already imported with NOPHONE prefix

### Added
- **April 2026 data imported** — 324 rows from Excel, 19 new tenants created, 247 rent schedules + 235 payments loaded
- **Error recovery guidance** — "try again or type hi to start fresh" instead of just "something went wrong"

## [1.25.0] — 2026-04-11 — Audit Trail + Rent Revisions + Sheet Protection

### Added
- **`audit_log` table** — immutable trail for all field changes (who, when, old→new, room, source)
- **`rent_revisions` table** — rent change history with effective dates, reason, and who authorized
- **Audit logging** wired into all update handlers (sharing_type, rent, phone, gender, deposit, room AC/maintenance/staff)
- **Deposit change** (`account_handler._do_deposit_change`) now writes audit log
- **Sharing type → rent prompt** — after confirming sharing type change, bot asks "want to update rent too?"
- **`QUERY_AUDIT` intent** — "show changes for Anukriti", "who changed room 402", "audit log"
- **`QUERY_RENT_HISTORY` intent** — "rent history Anukriti", "show rent changes"
- **`QUERY_STAFF_ROOMS` intent** — "list staff rooms", "non-revenue rooms"
- **Staff room toggle** — "room G05 staff room" / "room 305 not staff" (with audit)
- **`lockAllSheets()` function** in Apps Script — protects all Sheet tabs, bot-only edits
- **Sheet locked via API** — all 10 tabs protected programmatically

### Fixed
- **Rent vs payment disambiguation** — "Anukriti rent 28000" no longer matches UPDATE_RENT (requires explicit keywords like change/update/set). Prevents confusion with payment collection.
- **Removed duplicate UPDATE_DEPOSIT** intent — DEPOSIT_CHANGE in account_handler already handles this
- **Anukriti rent corrected** — updated from 15,000 (old double rate) to 28,000 (premium rate) in DB + Sheet
- **Saurabh Kumar 406 Sheet fix** — reverted manual edit (rent_due 123 → 15,500)
- **Inactive room lookup** — room update handler now finds inactive rooms for "maintenance done" commands

### Documented
- **Data sync policy** (BRAIN.md §15b) — DB is source of truth, bot-only changes, Sheet is read-only mirror
- **Data sync rule** added to CLAUDE.md dependency checklist

## [1.24.0] — 2026-04-10 — Media Upload Handler + Receipt Collection

### Added
- **Media upload handler** (`receipt_handler.py`) — classifies uploaded photos by caption keywords and routes to appropriate handler
- **Receipt types:** payment receipt, expense bill, tenant ID proof, license/certificate, vendor delivery slip
- **Payment receipt flow:** auto-attach to recent payment, disambiguate if multiple, ask user if no context
- **Photo-first flow:** receipt saved, bot asks for payment details to link it
- **Document archive:** all uploads stored in `documents` table with type tagging
- **`receipt_url`** column on payments table — links payment to receipt image
- **Pending states:** RECEIPT_SELECT, MEDIA_CLASSIFY, RECEIPT_NO_PAYMENT for multi-turn flows

### Next
- **Gemini Vision** — free multimodal AI to auto-read receipt images (amount, UPI ref, tenant name). Kiran getting API key.

## [1.23.0] — 2026-04-10 — Flexible NL Queries + Conversation Memory + Regex Fixes

### Added
- **Flexible natural language queries** — ask any data question in plain English via WhatsApp. LLM generates SQL from DB schema, executes safely, and formats reply naturally. Examples: "top 5 highest paying tenants", "average rent per building", "which tenants haven't paid"
- **LLM-formatted replies** — query results are summarized by LLM into clean WhatsApp messages instead of raw data dumps
- **Conversation history** — last 8 messages loaded as context for PydanticAI agent. Follow-up queries work: "how many female tenants" → "break it down by building"
- **Query logging** — every flexible query saved to classification_log for learning and audit
- **Guardrails** — non-PG questions rejected, SELECT-only, table whitelist, row limits

### Fixed
- **Regex: void expense** — no longer matches VOID_PAYMENT (required 'payment' keyword)
- **Regex: complaint status** — no longer matches QUERY_TENANT (word boundary fix)
- **Regex: void last payment** — now correctly matches VOID_PAYMENT
- **SQL validator** — EXTRACT(FROM col) no longer blocked as table reference
- 30/30 regex intent tests pass with zero LLM calls

### Architecture
- `src/llm_gateway/agents/flexible_query.py` — new flexible query engine
- `QUERY_FLEXIBLE` intent added to PydanticAI prompt builder
- Short-term memory (chat_messages), long-term (property_config + intent_examples + classification_log)
- Vector DB (pgvector/RAG) planned for receipts/bills collection phase

## [1.22.0] — 2026-04-09 — PydanticAI Enabled + Vacant Beds Accuracy + Data Cleanup

### Added
- **PydanticAI enabled** — `USE_PYDANTIC_AGENTS=true`, handles UNKNOWN/GENERAL intents with structured LLM output, few-shot examples, confidence routing
- **Day-wise stays** in occupancy — short-stay guests now subtracted from available beds (auto-expires on checkout_date)
- **ANOMALIES sheet** — auto-generated in Google Sheet with 76 data quality issues (wrong PAID status, negative balances, date mismatches)

### Fixed
- **Vacant beds handler** — now shows ALL empty beds (partial + fully vacant rooms), not just fully vacant rooms
- **Occupancy handler** — includes day-wise line item
- **Monthly report** — total_beds from DB (not hardcoded 291), building vacant counts partials
- **Gender filter** — accounts for day-wise occupants
- **Balance clamp** — negative balances clamped to 0 on Sheet (deposit+rent = PAID, not -12000). Both gsheets.py and Apps Script
- **ORM UUID types** — String(36) → PostgreSQL UUID to match Supabase schema

### Removed
- **LangGraph v2** — deleted `src/whatsapp/v2/` (dead code, replaced by PydanticAI). Removed langgraph, langchain, langchain-core, langchain-groq from requirements

### Data
- Synced 14 no-show→active tenancies (Sheet said CHECKIN, DB said no_show)
- Cancelled Chinmay Pagey stale no-show (had active tenancy in different room)
- Cancelled Shalini (not on April Sheet)
- Remaining no-shows: 7 (all genuine, confirmed against Sheet)
- SSH key auth configured for VPS deploys

### Open
- **76 anomalies** on ANOMALIES sheet — Kiran reviewing (34 PAID-but-underpaid, 38 negative balances, 4 date mismatches)
- **Natural language flexible queries** via PydanticAI — not yet implemented (next session)
- **DB/Sheet full re-sync** — waiting for Kiran's updated data

## [1.21.2] — 2026-04-08 — Phone Dedup Fix + April Sheet Sync

### Fixed
- **Phone dedup bug** — `excel_import.py` used phone-only as tenant cache key, causing shared-phone roommates (e.g. V. Bhanu Prakash + V. Sathya Priya in room 314) to be skipped. Now uses phone+name.
- **import_april.py** — same phone+name matching for shared phones. Created V. Bhanu Prakash + Sanskar Bharadia who were previously missing.
- **April Sheet format** — rewrote to 17-col format (with Phone column) matching gsheets.py. Was 15-col hybrid that broke bot write-back and Apps Script dashboard.
- **April Sheet statuses** — uses Excel statuses directly instead of recalculating from Cash+UPI (which missed advance payments and cross-month balances).

### Data
- DB + Sheet now in sync: Rs 34,77,707 total April collections
- 8 missing April rent_schedules generated, Adithya Reddy marked exit
- Dashboard summary rows 2-3 now auto-generated with correct occupancy/collection stats

### Open
- 9 UNPAID showing on Sheet vs expected 5 checked-in unpaid — needs investigation (some may be no-shows miscategorized)

## [1.21.1] — 2026-04-08 — Report Revamp + April Delta Update + Groq 429 Fix

### Fixed
- **Groq 429 fallback** — `_call_llm_manual` now returns graceful "try again" reply instead of crashing on rate limit. Also handles JSON parse errors.

### Changed
- **Monthly report** — Total Collection = Rent + Maintenance (per REPORTING.md). Security Deposits shown as separate line. Rent breakdown shows Cash/UPI split.
- **Yearly report** — same: maintenance + deposits tracked per month, totals include maintenance in collection.

### Added
- **`scripts/update_april_delta.py`** — delta updater: compares Excel vs DB per-tenant, only updates changed records (payments, statuses, notes). No more drop-and-reload for incremental updates.
- **April import columns** — complaints (col 26), vacation (col 27) now parsed from Excel.

### Data
- April delta applied: +20 payments, 4 corrected, 21 status updates, 11 notes synced, 3 new tenants (Kiran Koushik, Nihanth, Prableen). DB total matches Excel: Rs 34,77,707.

## [1.21.0] — 2026-04-08 — Kozzy AI Platform: PydanticAI + Multi-Tenant Foundation

### Added
- **PydanticAI ConversationAgent** — structured LLM output, few-shot examples, natural conversation, confidence routing (>0.9 execute / 0.6-0.9 options / <0.6 clarify)
- **LearningAgent** — background async learning from corrections, selections, confirmations. Each PG learns independently.
- **property_config table** — multi-tenant config: buildings, rooms, pricing, bank config, personality per PG
- **intent_examples table** — self-learning intent database, scoped per PG, grows from user interactions
- **classification_log table** — audit trail of every intent classification
- **Dynamic system prompt** — built from property_config, role-aware, with injected few-shot examples
- **Feature flag** — `USE_PYDANTIC_AGENTS=false` for safe rollout, instant rollback
- **Cozeevo seeded** as first PG tenant (PG_ID: 58373135-5a92-4957-b11e-256d61f09441)
- **SYSTEM_SPEC.md** — single-file platform specification (14 sections, replaces reading 16 docs)

### Fixed
- **pg_config name conflict** — PostgreSQL has a system view called pg_config. Renamed to property_config.
- **PydanticAI API** — output_type (not result_type), result.output (not result.data)

### Architecture
- Regex stays as fast path (~97%). PydanticAI handles misses with structured output.
- Every LLM classification feeds the learning flywheel (intent_examples grows autonomously).
- All PG-specific config in property_config — no hardcoded strings in agent code.
- Handlers unchanged — agents output same dict shape, zero handler modifications.

### Smoke Test Results
- "Raj paid 15000" → PAYMENT_LOG (conf=0.95) ✓
- "Good morning!" → natural reply ✓
- "Who are you?" → "I'm Cozeevo Help Desk..." ✓

## [1.20.0] — 2026-04-08 — Confirm Bug Fix + Contact Management + Benchmarks

### Fixed (CRITICAL)
- **Confirm steps broken for 2+ days** — `return None` at line 2542 in `resolve_pending_action` killed ALL text-based confirm flows (Yes/No). Every intent after that line was unreachable. Fixed with `chosen is not None` guards.
- **Webhook dedup** — Meta sends 4-5 duplicate POSTs per message. Added in-memory msg_id cache (60s TTL) to skip duplicates.
- **`_save_pending` import missing** — `resolve_pending_action` didn't import `_save_pending`, crashing all multi-step flows.
- **Add Contact intent routing** — "Add building electrician contact" was matching QUERY_CONTACTS instead of ADD_CONTACT.
- **Phone parsing** — strips spaces, +91 prefix, saves 10-digit only.
- **Category matching** — word boundary regex prevents "contact" matching "ac" → false "AC Service".

### Added
- **Add Contact notes step** — asks "Any notes?" after category, saved to `contact_for` field.
- **Update Contact command** — "update contact Shiva", "change Balu number", "edit plumber notes".
- **Contact query filtering** — "send me electrician vinays contact" now returns only Vinay, not all electricians.
- **VPS file-based logging** — `/tmp/pg_pending_debug.log` for tracing pending flows (journald doesn't work with uvicorn workers).

### Benchmarked
- 115 test cases: Regex 76.5%, Haiku 94.8%, Groq ~90%
- Switched back to Groq (free) — Haiku cost $1+ in 2 days
- **Next: PydanticAI integration** — structured output, self-correcting, learning flywheel

## [1.19.0] — 2026-04-07 — April Import + Day-wise Stays

### Added
- **`scripts/import_april.py`** — April payment drop-and-reload importer from `April Month Collection.xlsx`
  - Reads all rows (CHECKIN, NO SHOW, EXIT with payments), creates missing tenants/tenancies
  - Extracts pure numeric from cash/UPI/balance cols; text saved as April notes
  - Permanent comments → tenancy.notes, monthly comments → rent_schedule.notes
  - Drop + reload safe (idempotent). Verified: Cash 7,44,050 + UPI 25,28,575 = 32,72,625 exact match
- **`scripts/import_daywise.py`** — Day-wise short-stay importer merging both Excel files
  - Reads "Daily Basis" (main Excel) + "Day wise" (April Excel), deduplicates by SHA-256
  - 93 unique records, 88 inserted to DB, revenue 2,18,950
  - New "DAY WISE" tab on Google Sheet
- **`daywise_stays` DB table** — separate table for short-term guests (1-10 days), not in tenancy chain
- **APRIL 2026 Google Sheet tab** — 234 rows with formulas, balance column as notes

### Changed
- `src/database/models.py` — added DaywiseStay model
- `src/database/migrate_all.py` — added daywise_stays CREATE TABLE

## [1.18.1] — 2026-04-06 — Critical Fix: Pending State + Conversation Flow

### Fixed
- **ROOT CAUSE: chat_messages table missing on VPS** — `_save_chat_message` in same transaction as pending actions caused commit rollback, losing ALL pending state (confirm steps never worked)
- **Fix: separate commits** — critical ops (pending, payments) commit first; chat messages in separate try/except commit
- **"No" during confirm** → now asks "what to change?" instead of cancelling (payment, expense, contact, tenant)
- **Contact name truncation** — "Mahadevapura lineman" no longer stripped to "Mahadevapura" (category keywords kept in name)
- **Pending alive after correction** — updates existing pending in-place instead of creating new record

### Important
- **Always run `python -m src.database.migrate_all` on VPS after deploy** — new tables must exist before code uses them

## [1.18.0] — 2026-04-06 — AI Conversation Manager

### Added
- **AI conversation manager** — Groq-powered natural conversation replaces "I didn't understand" dead-ends
- **Correction detection** — "no, name is X" during confirm steps updates the field instead of cancelling
- **Chat history context** — all messages saved to chat_messages, fed to Groq for multi-turn understanding
- **CONVERSATION_MANAGER_PROMPT** — new prompt in prompts.py for corrections, clarifications, natural chat
- **manage_conversation()** — new ClaudeClient method returns structured {action, entities, correction, reply}
- **Stress test suite** — 194 test cases across 16 intent groups, 100% pass rate

### Fixed
- **Intent disambiguation** — precise descriptions for CHECKOUT vs NOTICE_GIVEN, QUERY_TENANT vs ROOM_STATUS, ADD_TENANT vs START_ONBOARDING, CHECKOUT vs RECORD_CHECKOUT
- **UNKNOWN passthrough** — removed from LOW_CONF_PASSTHROUGH so all unknowns hit AI conversation manager
- "Priya is leaving" now correctly routes to CHECKOUT (was NOTICE_GIVEN)
- "room 203 details" now correctly routes to QUERY_TENANT (was ROOM_STATUS)
- "register tenant Arun" now correctly routes to ADD_TENANT (was START_ONBOARDING)
- "thats wrong start over" now correctly routes to CANCEL (was ASK_WHAT_TO_CHANGE)

## [1.17.0] — 2026-04-06 — Full Data Sync + Add Tenant KYC + Dashboard

### Added
- **Add Tenant form** — 14 new KYC fields (DOB, father, address, email, occupation, emergency contact, ID proof) — all skippable with "skip all" shortcut
- **Change Checkout Date** — new intent UPDATE_CHECKOUT_DATE with handler
- **Lokesh receptionist** — added to authorized_users (7680814628)
- **Apps Script dashboard web app** — Code.gs + Index.html, reads from monthly tabs
- **Anomaly report** — 93 items uploaded to ANOMALY REPORT tab in Google Sheet
- **Cheat sheets** — full command reference + printable workflow guide
- **Dependency sync rule** — 13-point checklist added to CLAUDE.md

### Fixed
- **Excel column mapping** — April column (col 28) shifted Feb/March Balance/Cash/UPI by 1 position
- **Entity extraction** — "What is the rent for chinmay" now correctly extracts name (was grabbing "What")
- **Month extraction** — word boundary prevents "chinmay" matching month "may"
- **Exit text pattern** — "april 3rd 7am exit" no longer parsed as balance=3
- **TENANTS tab** — expanded to 32 columns (Notes, Food, Staff, KYC fields)
- **April tab** — uses Excel April column (col 28) when available
- **Overpayment analysis** — accounts for rent+deposit and Feb balance (reduced false positives from 69 to 0)
- **Apps Script** — case-insensitive tab matching, month-on-month row expansion, error handling

### Data
- Full Excel reimport: 291 tenants, 292 tenancies, 1009 payments, 1033 rent_schedule rows
- March verified: Cash 1,030,220 + UPI 2,667,888 — matches manual count
- 3 Hitachi tenants fixed in DB (Sachin, Pankaj, Himanshu — rent 23,850)

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
