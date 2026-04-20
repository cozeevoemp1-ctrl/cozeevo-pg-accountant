# Changelog

All notable changes to PG Accountant will be documented here.

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
