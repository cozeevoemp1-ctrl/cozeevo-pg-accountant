# Bug Tracker — Historical Record

Complete record of all bugs discovered and fixed since v1.5.0. Each bug assigned permanent ticket ID (BUG-0001 onwards) for reference.

---

## Format

```
## BUG-NNNN: [Bug Name]
**Symptom:** [what user saw / which feature broke]
**Root Cause:** [why it happened / code path]
**Implementation:** [file:line before/after code]
**Affected Endpoints:** [API routes or UI pages]
**Impact:** [severity / data loss risk / affected users]
**How It Was Missed:** [test gap / review gap / design gap / edge case]
**Prevention Steps:** [checklist to prevent recurrence]
**Pattern:** [bug family / related bugs]
**Fixed:** [date + version], commit [hash]
**Test Coverage:** [test file + test name, if added]
```

---

# Recent Bugs (v1.76.53 → v1.76.30)

## BUG-0001: Notices page API error — non-existent full_name field

**Symptom:** Notices page crashed on load with API error. Tenant names not displayed in notices panel.

**Root Cause:** `src/api/v2/notices.py` was querying `OnboardingSession.full_name` which does not exist on the model. The field is `tenant_data` (JSON) which must be parsed to extract name.

**Implementation:**
- **Before:** `OnboardingSession.full_name` (non-existent field)
- **After:** `OnboardingSession.tenant_data` + parse JSON like `src/api/v2/kpi.py` does
- **File:** `src/api/v2/notices.py` lines 69-85

**Affected Endpoints:**
- `GET /api/v2/app/notices/active` — notices panel API
- `web/app/notices/page.tsx` — notices page UI

**Impact:** **High** — page completely non-functional. All users unable to view notices panel.

**How It Was Missed:** API test not run after refactoring `OnboardingSession` model. No integration test for notices API. Data shape changed but endpoint not updated.

**Prevention Steps:**
1. After any model rename/restructure, grep all API files for references
2. Always run API tests: `python tests/eval_golden.py` before push
3. Test notices page load in browser after onboarding changes

**Pattern:** Model refactoring → missing field reference (see BUG-0042: proratedRent NameError)

**Fixed:** 2026-06-07, v1.76.53, commit `b6738bf`

**Test Coverage:** Integration test recommended for `GET /notices/active` with pending_review + pending_tenant sessions

---

## BUG-0002: quick_book always creates no_show status (ignores checkin_date)

**Symptom:** Past-dated advance bookings appeared as `no_show` even when check-in date was in the past. Should have been `active`. Breaks occupancy counts for retroactive bookings.

**Root Cause:** `src/api/v2/bookings.py:quick_book` hardcoded `status="no_show"` without checking if `checkin_date <= today`. Approval endpoint had correct logic (check date) but quick_book did not.

**Implementation:**
- **Before:** `tenancy = Tenancy(status="no_show", ...)`
- **After:** Match approval logic: `status = "active" if checkin_date <= today else "no_show"`
- **File:** `src/api/v2/bookings.py` line 227

**Affected Endpoints:**
- `POST /api/v2/bookings/quick-book` — quick booking create
- `src/api/onboarding_router.py` approve endpoint (had correct logic)

**Impact:** **Medium** — occupancy counts wrong, misleading reporting on past-dated bookings. Breaks "past-date tenancy creation" workflow for admin catch-ups.

**How It Was Missed:** quick_book is less common than approval flow. No test for past-dated bookings. Logic divergence between two check-in paths not caught by review.

**Prevention Steps:**
1. Maintain parity between `quick_book` and `approval` status logic
2. Test past-dated bookings: create with `checkin_date = today − 3 days`, verify `status = active`
3. Add integration test: past-dated booking → verify occupancy counts

**Pattern:** Multi-path check-in (bot/PWA/quick-book) logic divergence (see BUG-0009: Check-in capacity guard)

**Fixed:** 2026-06-07, v1.76.52, commit `e38911e`

**Test Coverage:** `tests/eval_golden.py` — test G052 or similar for quick_book status

---

## BUG-0003: Minimum collection validation at check-in blocks partial payments

**Symptom:** Check-in rejected if tenant didn't pay full first-month rent + deposit. Should allow any payment amount; remainder becomes dues.

**Root Cause:** `src/api/onboarding_router.py:approve` endpoint had overly strict validation: `if not (has_first_month_rent OR has_deposit): reject with 422`. Should only check that *some* payment was made, not specific amount.

**Implementation:**
- **Before:** `if not (first_month_collected >= first_month_rent) or not (deposit_collected >= security_deposit): raise 422`
- **After:** Remove minimum check entirely; allow any payment; calculate remainder as dues
- **File:** `src/api/onboarding_router.py` lines 1877-1888

**Affected Endpoints:**
- `PATCH /api/v2/onboarding/admin/{token}/approve` — check-in approval
- `web/app/onboarding/bookings/page.tsx` — "Save & Check In" button

**Impact:** **Medium** — users unable to check in with partial payment (₹5K vs ₹28K required). Only admin/staff affected, but breaks onboarding workflow.

**How It Was Missed:** Test suite likely only tested full-payment paths. Edge case of partial payment not covered. Business logic unclear: should we enforce pre-payment or allow post-collection?

**Prevention Steps:**
1. Document payment policy: partial allowed, remainder becomes due immediately
2. Test suite: check-in with 0%, 50%, 100% payment collected
3. Add guard test: verify system allows partial check-in

**Pattern:** Over-validation / business logic clarification (see BUG-0033: Deposit box hardcoded UPI)

**Fixed:** 2026-06-07, v1.76.52, commit `8fda3ae`

**Test Coverage:** Integration test: check-in with `payment_amount = ₹5,000 < first_month_rent`, verify `status = active` + dues = remainder

---

## BUG-0004: Check-in performance bottleneck (10s → <1s)

**Symptom:** Check-in button on Bookings page hangs for 10+ seconds. User thinks request failed and clicks again. Causes duplicate tenancy creation.

**Root Cause:** Check-in endpoint called `session.commit()` AFTER slow operations (GSheets add_tenant, PDF generation, WhatsApp sends). DB transaction held open while waiting for external APIs. This is blocking I/O on the critical path.

**Implementation:**
- **Before:**
  ```python
  session.add(tenancy)
  session.flush()
  
  # Slow operations
  gsheets.add_tenant(...)  # 2-3s
  pdf.generate(...)        # 1-2s
  whatsapp.send(...)       # 2-3s
  
  session.commit()         # Commit after all
  ```
- **After:**
  ```python
  session.add(tenancy)
  session.commit()         # Commit FIRST
  
  # Slow operations (background)
  create_task(gsheets.add_tenant(...))
  create_task(pdf.generate(...))
  create_task(whatsapp.send(...))
  ```
- **File:** `src/api/onboarding_router.py` line 1937

**Affected Endpoints:**
- `PATCH /api/v2/onboarding/admin/{token}/approve` — check-in save
- `web/app/onboarding/bookings/page.tsx` — "Save & Check In" button

**Impact:** **High** — perceived failure → double-click → duplicate tenancy. Response timeout → angry users. GSheets/WhatsApp lag is infrastructure problem, but should not block API response.

**How It Was Missed:** Load testing not performed. Endpoint tested in isolation without real GSheets/WhatsApp API delays. Async patterns not used from start.

**Prevention Steps:**
1. Load test all POST endpoints with 1-3s external API delays
2. Always call `session.commit()` BEFORE slow operations
3. Use `create_task()` / background jobs for: GSheets writes, PDF gen, WhatsApp sends
4. Monitor API latency: p99 < 1s for DB-only ops

**Pattern:** Blocking I/O on critical path (see BUG-0032: GSheets write-back async)

**Fixed:** 2026-06-07, v1.76.52, commit `d823833`

**Test Coverage:** Load test: simulate 2s GSheets delay, verify API response < 500ms

---

## BUG-0005: proratedRent NameError in approve endpoint

**Symptom:** Check-in approval crashes with `NameError: name 'proratedRent' is not defined`. Only hits prorated tenancies (non-full-month).

**Root Cause:** `src/api/onboarding_router.py:approve` called undefined function `proratedRent()`. Correct name is `prorated_first_month_rent()` (underscore naming). Function imported inside another function, not at module scope, so not available in approve.

**Implementation:**
- **Before:**
  ```python
  def calculate_rent():
      from src.services.rent_schedule import prorated_first_month_rent
      ...
  
  # In approve:
  prorated_rent = proratedRent()  # Wrong name, wrong scope
  ```
- **After:**
  ```python
  # At module top:
  from src.services.rent_schedule import prorated_first_month_rent
  
  # In approve:
  prorated_rent = prorated_first_month_rent(...)  # Correct name, module scope
  ```
- **File:** `src/api/onboarding_router.py` lines 28 + 1880

**Affected Endpoints:**
- `PATCH /api/v2/onboarding/admin/{token}/approve` — prorated tenancy check-in only
- `web/app/onboarding/bookings/page.tsx` — "Save & Check In" for partial months

**Impact:** **High** — prorated check-ins completely broken. Only monthly (full-month) tenancies could be approved.

**How It Was Missed:** No test for prorated check-in path. Function name refactor (`proratedRent` → `prorated_first_month_rent`) not caught by grep. Import at function level (scope issue) not tested.

**Prevention Steps:**
1. After any import refactor, grep project for old name: `grep -r "proratedRent" .`
2. Test suite: include prorated (partial-month) check-in approval
3. Linter: catch undefined name references (already does, but test must run)

**Pattern:** Import scope + name refactoring (see BUG-0006: Module-level import issue)

**Fixed:** 2026-06-07, v1.76.52, commit `c2e069e` + `04c24d4`

**Test Coverage:** Unit test: approve with prorated tenancy, verify rent calculation uses correct function

---

## BUG-0006: Home page caching prevents fresh KPI data on navigation

**Symptom:** User navigates to home page, sees stale occupancy/KPI numbers. Refresh manually to see latest. Misleading for real-time status checks.

**Root Cause:** Next.js default caching (60s) + no explicit cache invalidation. Home page fetches KPI but result is cached. Subsequent navigations serve stale data.

**Implementation:**
- **Before:** No cache control in `web/app/page.tsx`
- **After:** Add `export const revalidate = 0` at file top (disable all caching for this page)
- **File:** `web/app/page.tsx` line 12

**Affected Endpoints:**
- `GET /api/v2/kpi` — KPI endpoint (correct data)
- `web/app/page.tsx` — home page (stale cache)

**Impact:** **Medium** — confusing stale data. Only affects home page, not Notices/Checkouts/Finance which show correct data.

**How It Was Missed:** Dynamic data fetching + caching strategies not reviewed in initial PWA setup. Default Next.js behavior differs from expectation.

**Prevention Steps:**
1. For all dynamic pages (financial, operational): add `export const revalidate = 0`
2. Only cache static pages (docs, settings, reference)
3. Test: Navigate home → change data in DB → navigate home → verify fresh data

**Pattern:** Data freshness / caching (see BUG-0042: Activity feed stale timestamps)

**Fixed:** 2026-06-07, v1.76.52, commit `653cddd`

**Test Coverage:** E2E test: navigate home → modify tenancy in DB → navigate back → verify KPI updated

---

## BUG-0007: Home page KPI boxes (prebooked calculation broken)

**Symptom:** Home page KPI doesn't load. API error in "Prebooked" box count. Causes entire home page to fail rendering.

**Root Cause:** `src/api/v2/kpi.py:get_kpi` used complex `exists()` subqueries to calculate prebooked form count. Query was syntactically invalid or returning wrong column types, crashing the endpoint.

**Implementation:**
- **Before:** Complex `exists()` pattern with unclear filter logic
- **After:** Simplified to `count(OnboardingSession where status=pending_review in non-staff/non-000 rooms)`
- **File:** `src/api/v2/kpi.py`

**Affected Endpoints:**
- `GET /api/v2/kpi` — KPI endpoint (crashes)
- `web/components/home/kpi-grid.tsx` — KPI cards (fails to load)

**Impact:** **High** — entire home page broken. Admin cannot see any KPI data. Critical blocking issue.

**How It Was Missed:** Complex SQL not unit tested. No integration test for KPI endpoint. Edge case in `exists()` logic not caught by review.

**Prevention Steps:**
1. Never use `exists()` without explicit integration test
2. Test KPI endpoint in isolation: `python -c "from src.api.v2.kpi import get_kpi; get_kpi(...)"`
3. Add KPI to golden test suite — verify endpoint returns valid structure

**Pattern:** Complex SQL queries (see BUG-0015: "No replacement" filter logic)

**Fixed:** 2026-06-07, v1.76.50, commit `78d857d` + multiple related fixes

**Test Coverage:** Integration test: `GET /kpi` returns all 4 KPI tiles with valid counts

---

## BUG-0008: "No replacement" filter on Notices page (wrong field)

**Symptom:** "No replacement" filter shows only tenants with no incoming bookings. But filter is based on `deposit_eligible` (notice timing), not actual replacements. Misleading results.

**Root Cause:** Filter logic checked `deposit_eligible` field instead of `prebookings` array. `deposit_eligible` is about whether deposit can be refunded (based on notice date timing), not about whether a replacement is booked.

**Implementation:**
- **Before:** Filter checked `WHERE deposit_eligible = true` (wrong field)
- **After:** Filter checks `WHERE prebookings IS EMPTY` (no OnboardingSession bookings in room)
- **File:** `src/api/v2/notices.py`

**Affected Endpoints:**
- `GET /api/v2/app/notices/active` — notices API with filter
- `web/components/home/kpi-grid.tsx` — "No replacement" filter toggle

**Impact:** **Medium** — filter gives wrong results. Admin cannot find beds with no incoming booking. Disrupts checkout planning.

**How It Was Missed:** Filter logic not tested. Field semantics (deposit_eligible = notice timing, not replacements) not documented. Confusing variable names.

**Prevention Steps:**
1. Document each filter field: what it means, what data it checks
2. Test filters: create tenants with/without notice + with/without prebooking, verify filter behaves correctly
3. Add filter to golden test suite

**Pattern:** Semantic confusion / wrong field (see BUG-0015: Activity feed timestamps)

**Fixed:** 2026-06-07, v1.76.50, commit `fc25630`

**Test Coverage:** Integration test: verify "No replacement" shows only tenants with `prebookings.length === 0`

---

## BUG-0009: Check-in capacity guard missing on 3 paths

**Symptom:** Users overbooking rooms: checking in tenants when room already full. Example: Room 522 had 4 tenants in 2-bed room. System allowed check-in without capacity check.

**Root Cause:** Three paths to activate tenancy, only 1 had capacity check:
1. PWA `/checkin/new` endpoint — **no check** (flipped no_show→active)
2. Bot arrival confirmation — **no check** (activated from message)
3. Approval endpoint — **had check** ✓

Root cause for room 522: Akshay added via script (bypassed guards) → checked in via unguarded PWA path.

**Implementation:**
- **Before:**
  - `src/api/v2/checkin.py:activate` — no capacity check
  - `src/whatsapp/handlers/resolvers/onboarding.py` — no capacity check
- **After:** Both call `check_room_bookable()` before activation
- **File:** `src/api/v2/checkin.py`, `src/whatsapp/handlers/resolvers/onboarding.py`

**Affected Endpoints:**
- `POST /api/v2/checkin/new` — direct check-in (PWA)
- WhatsApp bot arrival confirmation message
- `PATCH /api/v2/onboarding/admin/{token}/approve` — (had check, unchanged)

**Impact:** **High** — data corruption (overbooking). Occupancy counts wrong. Room capacity violated.

**How It Was Missed:** Three separate code paths, no shared guard function. Hotpath (approval) had check but other paths didn't. No comprehensive validation test covering all 3 paths.

**Prevention Steps:**
1. Extract `check_room_bookable()` as canonical guard — single source of truth
2. All tenancy activation MUST call this guard: approval + quick_book + direct check-in + bot
3. Test: activate from all 4 paths with full room, verify all blocked

**Pattern:** Multi-path consistency (see BUG-0002: quick_book status logic, BUG-0005: Prorated check-in)

**Fixed:** 2026-06-02, v1.76.47, commit `8440644` + `99810cb`

**Test Coverage:** Integration test for all 3 check-in paths: verify room capacity enforced on activation

---

## BUG-0010: Tenant search includes exited/cancelled tenants (breaks payment history)

**Symptom:** Search for tenant returns ghost entries (exited/cancelled). User pays old tenant again by accident. Breaks workflows: payment history, dues lookup, notices.

**Root Cause:** `src/api/v2/tenants.py:search` was changed to include exited/cancelled to support payment history lookup. But the flag was applied globally, affecting ALL search endpoints.

**Implementation:**
- **Before:** `search` included all statuses (active + exited + cancelled)
- **After:** Default to `active_only=true` (only active + no_show). Payment history explicitly passes `active_only=false`
- **File:** `src/api/v2/tenants.py`, `web/lib/api.ts`, `web/components/forms/tenant-search.tsx`, `web/app/payments/history/page.tsx`

**Affected Endpoints:**
- `GET /tenants/search` — default behavior now active-only
- `GET /tenants/search?active_only=false` — payment history lookup
- `web/app/payments/history/page.tsx` — payment history page (explicitly opts-in)

**Impact:** **Medium** — confusion + risk of paying wrong tenant. Affects all tenancy-lookup workflows.

**How It Was Missed:** Feature added to support payment history but not gated with a flag. Default behavior changed without audit of all callers.

**Prevention Steps:**
1. Any model query flag (active_only, include_archived, etc.): default to most restrictive
2. Explicit opt-in for loosened queries (payment history, audit, deletion recovery)
3. Audit all callers when changing query scope

**Pattern:** Query scope / filter defaults (see BUG-0032: Occupied beds query)

**Fixed:** 2026-06-02, v1.76.47, commit `c3c9212` + `5f5947c`

**Test Coverage:** Unit test: search defaults to active_only=true, verify exited tenant not returned

---

## BUG-0011: "Incoming" count includes all pending bookings globally (not just replacements)

**Symptom:** KPI shows "20 incoming" but only 5 are actual replacements for leaving rooms. Misleading number. Admin can't tell net impact of departures.

**Root Cause:** "Incoming" count was global: all pending_review + no_show status, regardless of which room they're going into. Should only count bookings in rooms where a tenant is actually leaving.

**Implementation:**
- **Before:** `count(all pending_review + no_show tenancies globally)`
- **After:** `count(pending_review + no_show IN rooms WHERE a tenancy has notice_date/expected_checkout)`
- **File:** `src/api/v2/kpi.py`

**Affected Endpoints:**
- `GET /api/v2/kpi` — incoming count
- `web/components/home/kpi-grid.tsx` — "On Notice" tile subtitle "X incoming · net Y"

**Impact:** **Medium** — misleading metric. Admin can't assess replacement fill rate. Affects occupancy planning.

**How It Was Missed:** Metric definition unclear. "Incoming" sounds global but should be contextual (relative to leaving rooms).

**Prevention Steps:**
1. Define all KPI metrics clearly: what they count, boundary conditions
2. Document in `docs/REPORTING.md`: "incoming = prebooking + no_show IN rooms with active departures"
3. Test: add notice to room A, verify incoming count only includes bookings for rooms with notices

**Pattern:** Metric definition / scope (see BUG-0008: Filter field confusion)

**Fixed:** 2026-06-07, v1.76.50, commit `2727b67` + `78d857d`

**Test Coverage:** Integration test: add notice, add prebooking to other room, verify incoming ≠ all pending

---

## BUG-0012: Duplicate payments from sheet reload (data integrity)

**Symptom:** Jagpreet Singh (Room 023) shows ₹13,500 deposit paid twice in payment history. Double-counted in reports. Root cause unclear.

**Root Cause:** "May sheet reload" script violated the "never sync Sheet→DB" rule. Sheet was treated as source of truth, causing duplicate payment records when same payment appeared on both original import + reload.

**Implementation:**
- **Policy:** DB is single source of truth. Sheet is read-only mirror.
- **Violation:** Sheet reload script synced Sheet→DB, recreating payments
- **Fix:** Identified duplicates; marked with `is_void=true` + audit log

**Affected Endpoints:**
- `GET /tenants/{id}/dues` — payment query
- Reports and P&L calculations

**Impact:** **High** — data corruption. Financial reports wrong. Affects 51+ duplicate refund records identified.

**How It Was Missed:** Sync direction rule not enforced. Script-based data load not reviewed against "never sync Sheet→DB" rule.

**Prevention Steps:**
1. Add data guard in code: `# WARN: Sheet→DB sync violates single-source-of-truth rule`
2. All Excel/Sheet imports MUST go through canonical `scripts/clean_and_load.py` → `excel_import.py`
3. Code review: check for any Sheet write-back that's not `gsheets.update_tenant_field()` + audit log

**Pattern:** Data sync integrity (see BUG-0035: Duplicate booking cleanup)

**Fixed:** 2026-06-07, v1.76.50, diagnostic note, manual void in next session

**Test Coverage:** Data integrity audit: scan payment table for duplicates with same (tenant_id, amount, payment_date)

---

## BUG-0013: cancel_session (onboarding) couldn't be cancelled once approved

**Symptom:** Admin tries to cancel an approved booking session. API returns 400 "cannot cancel". Leaves ghost no_show tenancy blocking the room.

**Root Cause:** `src/api/onboarding_router.py:cancel_session` only allowed cancelling pending_review sessions, not approved (pending_tenant or linked tenancies). Once a session had a tenancy, it was "locked" and couldn't be cancelled.

**Implementation:**
- **Before:** `if status != "pending_review": raise 400`
- **After:** Allow cancellation of pending_review + pending_tenant. If `obs.tenancy_id` set, also cancel linked tenancy (status→cancelled), void RS rows, write audit log
- **File:** `src/api/onboarding_router.py`

**Affected Endpoints:**
- `DELETE /api/v2/onboarding/admin/{token}` — cancel session endpoint
- `web/app/onboarding/bookings/page.tsx` — "Cancel" button

**Impact:** **High** — admin cannot fix accidental bookings. Ghost tenancies block rooms permanently.

**How It Was Missed:** Edge case: approved session cancellation. No test for cancelling linked tenancies. Workflow not documented.

**Prevention Steps:**
1. Test all state transitions: pending→pending_tenant→active can all be cancelled
2. On cancel with linked tenancy: void RS rows, audit log, sync status
3. Add to golden test: cancel at each stage

**Pattern:** State machine completeness (see BUG-0014: cancel_no_show incomplete)

**Fixed:** 2026-06-03, v1.76.49, commit in onboarding_router.py

**Test Coverage:** Integration test: approve session → cancel → verify tenancy status=cancelled, RS rows voided

---

## BUG-0014: cancel_no_show voids RS rows but doesn't sync onboarding session

**Symptom:** Admin cancels a no_show tenancy via Bot / PWA. Rent schedule rows voided. But linked onboarding session stays pending_review, blocking Bookings page. Inconsistent state.

**Root Cause:** `src/api/v2/tenants.py:cancel_no_show` voided RS rows but didn't set linked `obs.status=cancelled`. Creates orphaned onboarding session.

**Implementation:**
- **Before:** Only void RS rows; update tenancy status
- **After:** Also set `obs.status=cancelled` if linked, audit log includes RS count
- **File:** `src/api/v2/tenants.py`

**Affected Endpoints:**
- `DELETE /api/v2/tenancies/{id}` — cancel no_show (bot/PWA)
- `web/app/onboarding/bookings/page.tsx` — booking card gone but session lingers

**Impact:** **Medium** — UI inconsistency. Bookings page shows deleted session. Confuses admin.

**How It Was Missed:** Bidirectional link (tenancy ↔ onboarding_session) not maintained on cancel. No audit of cancel flows.

**Prevention Steps:**
1. After any tenancy state change: verify linked onboarding_session updated
2. Test cancel flows: verify both tables updated + audit log written
3. Add to BRAIN.md: "cancel_no_show must also set obs.status=cancelled"

**Pattern:** Bidirectional sync (see BUG-0009: Check-in capacity guard)

**Fixed:** 2026-06-03, v1.76.49, commit in tenants.py

**Test Coverage:** Integration test: approve session → cancel tenancy → verify obs.status=cancelled

---

## BUG-0015: "No replacement" filter — wrong logic, showed 0 results

**Symptom:** Admin applies "No replacement" filter to Notices page. Result: 0 rooms shown (incorrect, there should be ~10). Filter completely broken.

**Root Cause:** Filter tried to count no_show tenancies as replacements using complex logic. Shared-room over-matching: if room has 2 beds and both occupied by different no_shows in different rooms, filter incorrectly matched them. Approach reverted after breaking the filter.

**Implementation:**
- **Before:** Complex `assigned` set logic to prevent over-matching in shared rooms
- **After:** Reverted to original simpler approach: only count OnboardingSession prebookings (pending_review), exclude no_shows from replacement calculation
- **File:** `src/api/v2/kpi.py`

**Affected Endpoints:**
- `GET /api/v2/kpi` — notices detail response with prebookings
- `web/components/home/kpi-grid.tsx` — filter toggle

**Impact:** **Medium** — filter unusable. Admin can't identify beds needing replacements.

**How It Was Missed:** Attempted optimization (include no_shows) broke simpler working version. No test to verify filter returns non-zero results.

**Prevention Steps:**
1. Never optimize filter logic without test coverage verifying results
2. Test filter with various scenarios: empty room, occupied, occupied+prebooking, occupied+no_show
3. Add assertion: filter should return > 0 with typical data

**Pattern:** Optimization bug / attempted feature (see BUG-0011: Incoming count)

**Fixed:** 2026-06-02, v1.76.46, commit `fac7eb7` (reverted complex logic)

**Test Coverage:** Integration test: verify "No replacement" returns tenants with `prebookings.length === 0`

---

## BUG-0016: HOW IT WAS PAID uses payment_date instead of period_month (advance payment hidden)

**Symptom:** Advance payments for June made on May 31 don't appear in June's "How it was paid" report. Shows in May instead. Misleading cash position.

**Root Cause:** "How it was paid" report used `payment_date` (when payment was made: May 31) instead of `period_month` (the month rent applies to: June). Advance payments have different dates, should be grouped by period, not payment date.

**Implementation:**
- **Before:** `WHERE payment_date BETWEEN June 1...30`
- **After:** `WHERE period_month = "2026-06" for rent/maintenance` (keep payment_date for deposits/bookings which have no period)
- **File:** `src/services/reporting.py`

**Affected Endpoints:**
- `/api/v2/finance/pnl` — P&L "How it was paid" section
- `web/app/finance/page.tsx` — Cash tab payment breakdown

**Impact:** **Medium** — cash position misleading. June looks short-collected; May looks over-collected. Confuses reconciliation.

**How It Was Missed:** Advance payment logic not tested. `period_month` field not understood (newer addition). Reporting query not audited.

**Prevention Steps:**
1. Document: "Rent/Maintenance use period_month; Deposits/Bookings use payment_date"
2. Test: create advance payment May 31 for June rent; verify it appears in June "How it was paid"
3. Golden test: monthly reports for advance-heavy months (e.g. June with May prepayments)

**Pattern:** Date field confusion (see BUG-0042: Activity feed timestamps)

**Fixed:** 2026-06-02, v1.76.48, commit `b0d5542`

**Test Coverage:** Integration test: advance payment May 31 for June → verify appears in June report

---

## BUG-0017: Chandra Sagar phantom ₹28,000 booking payment voided

**Symptom:** Chandra Sagar tenancy 1144 shows paid ₹28,000 booking amount but money was never collected. Phantom payment at future date (June 8) created at onboarding approval.

**Root Cause:** `src/api/onboarding_router.py:approve` auto-created a payment record for `booking_amount` without checking if it was actually collected. When tenant has advance on old tenancy, new tenancy approval adds phantom future-dated booking payment.

**Implementation:**
- **Before:** Always create payment record: `Payment(amount=booking_amount, payment_date=future_date, ...)`
- **After:** Only create if amount actually collected (booking_amount > 0 and advance paid)
- **File:** Approval logic in `src/api/onboarding_router.py`

**Affected Endpoints:**
- `PATCH /api/v2/onboarding/admin/{token}/approve` — check-in approval
- `web/app/onboarding/bookings/page.tsx` — "Save & Check In" → approval

**Impact:** **Low-Medium** — isolated to bookings with carried-forward advances. Overstates cash collected; affects P&L.

**How It Was Missed:** Payment creation logic at approval not audited. Future-dated payment logic not obvious.

**Prevention Steps:**
1. Never create payment record without actual collection event
2. Audit all approval code paths: verify payment_amount ≤ actual_collected
3. Test: approve with booking_amount > 0 but advance paid on old tenancy → verify no phantom payment

**Pattern:** Payment record integrity (see BUG-0012: Duplicate payments)

**Fixed:** 2026-06-02, v1.76.48, manual void with audit log `system:void-phantom-booking-2026-06-02`

**Test Coverage:** Integration test: check-in with carried-forward advance → verify no new payment created

---

## BUG-0018: Omkar Deodher duplicate tenant (phone normalization)

**Symptom:** Two tenant records for same person (Omkar Deodher, room 314): tenant 981 + 1029. Phone stored as `7888016785` vs `+917888016785`. Payments split between records.

**Root Cause:** May 11 import script stored phone as `7888016785` (no +91 prefix). Existing tenant had `+917888016785`. Literal string match failed. System created duplicate instead of finding existing tenant.

**Implementation:**
- **Before:** Phone comparison: literal string match `phone == "+917888016785"`
- **After:** Normalize before compare: `RIGHT(regexp_replace(phone,'\D','','g'),10)` extracts last 10 digits
- **File:** `src/api/v2/tenants.py` — phone update endpoint

**Affected Endpoints:**
- `PATCH /tenants/{id}` — phone update
- Any phone-based duplicate check

**Impact:** **Medium** — duplicate tenants created. Payments split. Confuses reports.

**How It Was Missed:** Phone format inconsistency not documented. No test for phone normalization across prefix variations (+91, 0, 91, bare digits).

**Prevention Steps:**
1. Canonical phone format: always normalize to 10-digit via `RIGHT(regexp_replace(...),10)`
2. At import: normalize all phone numbers before checking for duplicates
3. Test: create tenant with +917888016785, update with 917888016785, verify same tenant

**Pattern:** Data normalization (see BUG-0013: Phone duplicate issue, commit `a2710a3`)

**Fixed:** 2026-06-02, v1.76.48, permanent fix + manual merge (tenancy 1064 → 1108)

**Test Coverage:** Unit test: phone normalization handles +91, 0, bare digits

---

## BUG-0019: Activity feed doesn't show all payments (only audit-logged ones)

**Symptom:** Activity feed missing months of payment records. Dashboard shows payment, but activity feed doesn't. Confuses tracking.

**Root Cause:** `src/api/v2/kpi.py:activity_feed` joined payments via `AuditLog.payment`. Payments created by scripts, backfills, or Excel imports never had AuditLog entries. So they were invisible.

**Implementation:**
- **Before:** `activity_feed` queried via `AuditLog.payment` join — only audit-logged payments
- **After:** Query payments directly from Payment table; merge with AuditLog for non-payment events
- **File:** `src/api/v2/kpi.py` — `GET /activity/feed` rewritten

**Affected Endpoints:**
- `GET /api/v2/kpi/activity/feed` — activity feed API
- `web/app/activity/page.tsx` — activity feed UI

**Impact:** **Medium** — audit trail incomplete. Missing payments make activity history confusing.

**How It Was Missed:** Audit logging added over time; not all payment sources (script, Excel, backfill) had audit entries. Feed query logic hidden in complex JOIN.

**Prevention Steps:**
1. Activity feed should query payments directly, not via AuditLog
2. Audit log is supplementary (context notes), not required for payment visibility
3. Test: add payment via script (no audit log) → verify appears in activity feed

**Pattern:** Data visibility (see BUG-0015: Incomplete audit trail)

**Fixed:** 2026-05-26, v1.76.35, commit `358a59e` + related

**Test Coverage:** Integration test: add payment via script → verify in activity feed

---

## BUG-0020: Activity feed timestamps use payment_date instead of created_at

**Symptom:** Activity feed shows future-dated payments (booking advance for June 8) appearing in future on activity feed. Ordering is wrong — future payments should sort first.

**Root Cause:** Activity feed sorted by `payment.payment_date` (when tenant is charged, could be future). Should use `payment.created_at` (when payment was recorded in system).

**Implementation:**
- **Before:** `ORDER BY payment.payment_date DESC`
- **After:** `ORDER BY payment.created_at DESC` — when payment was recorded
- **File:** `src/api/v2/kpi.py`

**Affected Endpoints:**
- `GET /api/v2/kpi/activity/feed` — activity feed API
- `web/app/activity/page.tsx` — activity feed timeline

**Impact:** **Low-Medium** — confusing ordering. Timeline jumps around.

**How It Was Missed:** Payment_date used for financial reports (correct). But for activity timeline, created_at is right (when event happened in system).

**Prevention Steps:**
1. Distinguish: financial reports use payment_date (period); activity timeline uses created_at (system event order)
2. Test: add advance payment 2 weeks in future → verify appears at top of timeline

**Pattern:** Timestamp semantics (see BUG-0016: Period vs payment date)

**Fixed:** 2026-06-02, v1.76.45, commit `6fc6550`

**Test Coverage:** Integration test: advance payment → verify correct position in activity feed

---

## BUG-0021: Check-in error message not visible (shown at top of page, user scrolled)

**Symptom:** User clicks "Save & Check In", gets error (e.g. room full), but error message is at top of page. User scrolled down to see form, doesn't see error. Clicks again.

**Root Cause:** `src/api/onboarding_router.py:approve` error handling showed error via page-level toast (top). Form was below fold.

**Implementation:**
- **Before:** `throw Exception` → caught by page-level error handler → toast at top
- **After:** Re-throw error in `BookingCard` component → show error inside card, directly above button
- **File:** `web/app/onboarding/bookings/page.tsx`

**Affected Endpoints:**
- `PATCH /api/v2/onboarding/admin/{token}/approve` — approval endpoint
- `web/app/onboarding/bookings/page.tsx` — "Save & Check In" button

**Impact:** **Medium** — UX: error invisible → retry → double-click problems.

**How It Was Missed:** No user testing with form errors. Error handling strategy not thought through.

**Prevention Steps:**
1. When error is contextual (form-level), show error in form, not page-level
2. User test: intentionally create error conditions, verify message visible

**Pattern:** Error visibility (see BUG-0004: Performance hangs cause double-click)

**Fixed:** 2026-05-31, v1.76.42, commit `81c6eaa`

**Test Coverage:** E2E test: trigger check-in error (room full), verify error visible in card

---

## BUG-0022: Overlapping booking blocks tenant's own check-in (false positive)

**Symptom:** Tenant pre-booked, then tries to check in same day. System says "Room full" even though it's their own pre-booking. Can't check in.

**Root Cause:** Overlap check counted tenant's own pre-booked `no_show` status as an occupant. When `obs.tenancy_id` was null (tenancy created outside onboarding flow), the exclude logic did nothing.

**Implementation:**
- **Before:** `exclude_tenancy_id = obs.tenancy_id` (None when tenancy created by bot) → exclude never triggered
- **After:** Added `exclude_tenant_id` param; always passes tenant ID — excludes tenant's own no_show regardless of how tenancy was created
- **File:** `src/services/room_occupancy.py` — `find_overlap_conflict`, `check_room_bookable`; called from `src/api/onboarding_router.py` (all 3 create/edit/approve paths)

**Affected Endpoints:**
- `POST /api/v2/onboarding/create` — create session
- `PATCH /api/v2/onboarding/admin/{token}` — edit session
- `PATCH /api/v2/onboarding/admin/{token}/approve` — approve session
- Bot arrival confirmation

**Impact:** **Medium** — check-in blocked incorrectly. User can't complete onboarding.

**How It Was Missed:** Multi-path check-in with different tenancy-creation sources (bot vs onboarding). Edge case of `obs.tenancy_id = None`.

**Prevention Steps:**
1. Always use `exclude_tenant_id` (not tenancy_id) for occupancy checks — tenant might have multiple tenancy records
2. Test: bot-created tenancy → onboarding check-in → verify no false-positive overlap
3. Simplify: drop all manual occupancy logic, always use canonical `check_room_bookable` helper

**Pattern:** Multi-path consistency (see BUG-0009: Check-in capacity guard)

**Fixed:** 2026-05-31, v1.76.42, commit `d8ac9b7`

**Test Coverage:** Integration test: bot create no_show → check-in from onboarding → verify succeeds

---

## BUG-0023: Approve reuses existing no_show but doesn't check if already linked to different session

**Symptom:** Duplicate tenancy creation when approving booking. System creates a new tenancy even though one already exists. Causes double-booking.

**Root Cause:** `src/api/onboarding_router.py:approve` looked for existing no_show via `(tenant_id, room_id)` but before linking it to `obs.tenancy_id`. If old no_show existed, approve should reuse it; if already linked to another session, create new one.

**Implementation:**
- **Before:** Always create new tenancy on approve; don't check for existing no_show
- **After:** Before creating, look up existing no_show. If found, reuse (set `obs.tenancy_id`). Only create if none exists
- **File:** `src/api/onboarding_router.py`

**Affected Endpoints:**
- `PATCH /api/v2/onboarding/admin/{token}/approve` — check-in approval
- `web/app/onboarding/bookings/page.tsx` — "Save & Check In" button

**Impact:** **High** — double-booking / duplicate tenancy. Data corruption.

**How It Was Missed:** Edge case of pre-existing no_show. Approval logic not comprehensive.

**Prevention Steps:**
1. Before creating any tenancy: check for existing no_show in (tenant, room)
2. Test: create no_show → edit booking session → approve → verify tenancy reused, not duplicated
3. Add guard test: prevent duplicate tenancy on same (tenant, room)

**Pattern:** Idempotency (see BUG-0009: Double-booking prevention)

**Fixed:** 2026-05-31, v1.76.42, commit `81c6eaa`

**Test Coverage:** Integration test: bot no_show → onboarding edit → approve → verify single tenancy

---

## BUG-0024: Day-stay num_days calculation missing or wrong

**Symptom:** Day-stay booking shows wrong stay duration. User books 3 days but system shows 2. Charged wrong amount.

**Root Cause:** `num_days` auto-calculation logic missing across CREATE/PATCH/APPROVE paths. Some paths calculated from dates, some from user input, some not at all.

**Implementation:**
- **CREATE:** Auto-calc `num_days = (checkout_date − checkin_date).days` if not provided
- **PATCH:** Recalculate when dates change
- **APPROVE:** Fall back to `agreed_rent` if daily_rate not set; never allow ₹0/day
- **File:** `src/api/onboarding_router.py`, `src/api/v2/tenants.py`

**Affected Endpoints:**
- `POST /api/v2/bookings/quick-book` (day-stay)
- `PATCH /api/v2/onboarding/admin/{token}` (edit session)
- `PATCH /api/v2/onboarding/admin/{token}/approve` (approve)

**Impact:** **Medium** — wrong billing on day-stays. Only affects day-stay product.

**How It Was Missed:** Day-stay is newer feature. Auto-calculation logic added piecemeal across multiple endpoints. No comprehensive test.

**Prevention Steps:**
1. Test day-stay end-to-end: CREATE with dates → PATCH dates → APPROVE → verify num_days calculated correctly
2. Add validation: never allow daily_rate = 0 or num_days = 0
3. Document: "num_days always auto-calculated from dates; daily_rate falls back to agreed_rent"

**Pattern:** Multi-path calculation logic (see BUG-0002: quick_book status)

**Fixed:** 2026-05-31, v1.76.42, commits `c71c8dc`, `06f9ac4`, `4696c69`

**Test Coverage:** Integration test: day-stay CREATE → PATCH → APPROVE, verify num_days consistent

---

## BUG-0025: Day-stay edit form shows wrong hint (pre-fill issue)

**Symptom:** User editing day-stay booking. Form shows "Total: ₹0 × 0 days" even though dates are set. Hint not updating as user types.

**Root Cause:** Day-stay edit form pre-fills from `booking` object (old values) but doesn't update hint when user changes rate/dates. Hint is calculated once at mount, not re-rendered.

**Implementation:**
- **Before:** Hint calculated from `b.daily_rate × b.num_days` at mount only
- **After:** Hint recalculates when `editRate` or `editDates` change (add to `useEffect` dependencies)
- **File:** `web/app/onboarding/bookings/page.tsx` — day-stay edit panel

**Affected Endpoints:**
- PATCH form in Bookings page (client-side only)

**Impact:** **Low** — cosmetic (hint wrong). Doesn't block submission.

**How It Was Missed:** Hint state not bound to input state. useEffect dependencies incomplete.

**Prevention Steps:**
1. Any hint or derived value: add to useEffect dependencies
2. Test: edit form field → verify hint updates live
3. Code review: check all useEffect arrays for completeness

**Pattern:** State binding / dependencies (see BUG-0026: Expected checkout calculation)

**Fixed:** 2026-05-31, v1.76.42, commit `4696c69`

**Test Coverage:** E2E test: edit day-stay → change rate → verify hint recalculates

---

## BUG-0026: Security Deposits TOTAL uses sum instead of closing balance

**Symptom:** P&L "Security Deposits held" TOTAL column shows inflated number. Same tenant's deposit counted multiple months. Throws off profit calculation.

**Root Cause:** `src/reports/pnl_builder.py` summed all monthly deposits: `sum(sec_dep_per_month)`. Deposits are a stock metric (balance at a point in time), not flow. Should show closing balance only (last month).

**Implementation:**
- **Before:** `TOTAL = sum([₹500K, ₹510K, ₹515K, ...])` = ₹lots
- **After:** `TOTAL = sec_dep_closing_balance[-1]` = ₹5,26,550 (Mar'26 closing)
- **File:** `src/reports/pnl_builder.py` — `_write_pnl_tab()`

**Affected Endpoints:**
- `GET /api/v2/finance/pnl` — P&L report
- `web/app/finance/page.tsx` — Finance Cash tab

**Impact:** **High** — P&L numbers wrong. Net Operating Profit, Adjusted Net Profit, Operating Margin all recalculated.

**How It Was Missed:** Stock vs flow metrics not documented. P&L structure not audited.

**Prevention Steps:**
1. Document: "Stock metrics (deposit, equipment) show closing balance in TOTAL. Flow metrics (revenue, expense) show sum."
2. P&L audit: verify TOTAL = opening + delta, not sum
3. Test: multi-month P&L, verify deposit TOTAL = last month closing only

**Pattern:** Metric semantics (see BUG-0016: Period vs payment date)

**Fixed:** 2026-05-30, v1.76.41, commit in pnl_builder.py

**Test Coverage:** Unit test: multi-month P&L, verify deposits TOTAL = closing balance

---

## BUG-0027: Edit session capacity check was zero (allowed any room regardless)

**Symptom:** Admin editing a booking can assign any room, even full ones. No validation. Can create overbooking.

**Root Cause:** `src/api/onboarding_router.py:PATCH /admin/{token}` (edit endpoint) had zero occupancy check. Only the approval endpoint had one.

**Implementation:**
- **Before:** No capacity check in edit endpoint
- **After:** Added future-booking capacity check: `check_room_bookable(..., exclude_tenancy_id=obs.tenancy_id)`
- **File:** `src/api/onboarding_router.py` — PATCH handler

**Affected Endpoints:**
- `PATCH /api/v2/onboarding/admin/{token}` — edit session
- `web/app/onboarding/bookings/page.tsx` — "Edit" button on booking card

**Impact:** **High** — can manually overbookroom. Data corruption.

**How It Was Missed:** Multiple check-in paths (create, edit, approve) not audited together. Edit path treated as "internal admin" so less scrutiny.

**Prevention Steps:**
1. All paths that change room assignment MUST call `check_room_bookable`
2. Test: edit booking → try to assign full room → verify blocked
3. Audit: search for all room assignment code, verify all call guard

**Pattern:** Validation completeness (see BUG-0009: Capacity guard on 3 paths)

**Fixed:** 2026-05-29, v1.76.39, commit in onboarding_router.py

**Test Coverage:** Integration test: edit booking → assign full room → verify 422 error

---

## BUG-0028: Duplicate booking cleanup (room 000 tenancies)

**Symptom:** Bookings page shows same person twice: once in room 000 (bot-created no_show), once in real room (onboarding session). Confuses admin.

**Root Cause:** Bot pre-booking creates `no_show` tenancy in placeholder room 000. Later, user books via onboarding with real room. Both exist, both show in Bookings page.

**Implementation:**
- **Before:** Both tenancies visible on Bookings page
- **After:** Set room-000 tenancies to `status=cancelled`; zero out `booking_amount` on matching sessions (prevents double-recording advance)
- **File:** Manual data cleanup in script

**Affected Endpoints:**
- `GET /api/v2/onboarding/admin/pending` — pending bookings list
- `web/app/onboarding/bookings/page.tsx` — Bookings page

**Impact:** **Medium** — confusing UI. Admin sees duplicates.

**How It Was Missed:** Room 000 was meant as placeholder; but tenancies created in it. No filter to hide them.

**Prevention Steps:**
1. Block tenancy creation in room 000 (only onboarding sessions, no tenancies)
2. Filter Bookings API: exclude room-000 tenancies
3. Test: bot pre-book → onboarding session → verify only real room shows on Bookings

**Pattern:** Placeholder room handling (see BUG-0035: Room 000 false positives)

**Fixed:** 2026-05-29, v1.76.39, manual data cleanup

**Test Coverage:** Query test: verify no active/no_show tenancies in room 000

---

## BUG-0029: Overlap check with expected_checkout (6-location fix)

**Symptom:** Pre-booking after lock-in tenant's expected exit blocked incorrectly. System didn't recognize that tenant had a planned exit date.

**Root Cause:** Six separate places checked occupancy/overlap but only looked at `checkout_date` (actual exit). Ignored `expected_checkout` (planned exit, set at booking for lock-in tenants). Caused 6 separate bugs — each needed fixing.

**Implementation:**
- **Fix 1 — Overlap check:** `src/services/room_occupancy.py` — `find_overlap_conflict` now uses `COALESCE(checkout_date, expected_checkout)` as bed end date. Commit: `7df4d3b`
- **Fix 2 — Room availability check:** `src/api/v2/rooms.py` — `/rooms/check` endpoint uses expected_checkout fallback. Commit: `b8affa2`
- **Fix 3 — Booking capacity check:** `src/api/v2/bookings.py` — pre-register submit uses expected_checkout. Commit: `0fbf666`
- **Fix 4 — Notices panel:** `src/api/v2/notices.py` — query includes `expected_checkout IS NOT NULL OR notice_date IS NOT NULL`. Commit: `f1ccd6e`, `09f9d18`
- **Fix 5 — KPI leaving count:** `src/api/v2/kpi.py` — both count + list use same filter. Commit: `a408592`
- **Fix 6 — Clear notice syncs checkout:** `src/api/v2/tenants.py` — PATCH clears expected_checkout when notice_date cleared. Commit: `f67d434`

**Affected Endpoints:**
- `GET /api/v2/rooms/check` — availability check
- `POST /api/v2/bookings` — booking submit
- `GET /api/v2/app/notices/active` — notices list
- `GET /api/v2/kpi` — KPI tiles
- `PATCH /api/v2/tenancies/{id}` — edit tenant

**Impact:** **High** — availability logic broken in 6 places. Can't pre-book after planned exits. Cascading data corruption.

**How It Was Missed:** `expected_checkout` is newer field (lock-in feature). Not retrofitted across all occupancy checks. Systemic refactoring needed.

**Prevention Steps:**
1. Document expected_checkout semantics: set at booking for locked-in stays; cleared on notice removal
2. Canonical occupancy helper: `find_overlap_conflict` with expected_checkout support
3. All occupancy queries MUST use: `COALESCE(checkout_date, expected_checkout)` as end date
4. Test: book lock-in tenant → pre-book after expected_checkout → verify succeeds

**Pattern:** Systemic field addition (see BUG-0009: Multi-path consistency)

**Fixed:** 2026-05-31, v1.76.44, commits `7df4d3b`, `b8affa2`, `0fbf666`, `f1ccd6e`, `a408592`, `f67d434`

**Test Coverage:** Integration test: book lock-in → pre-book after expected exit → verify no overlap

---

## BUG-0030: Booking advance payment audit entry wrong entity_id

**Symptom:** Advance payment on booking created but audit log points to tenancy, not payment. Activity feed join fails.

**Root Cause:** `src/api/v2/bookings.py:quick_book` created Payment object, but `flush()` not called before creating AuditLog. So `_pmt.id` not populated; audit used `tenancy.id` instead. Activity feed join `WHERE audit.entity_id = payment.id` fails.

**Implementation:**
- **Before:** Create payment → immediately create audit with `entity_id=tenancy.id`
- **After:** Create payment → flush → get `_pmt.id` → create audit with `entity_id=_pmt.id`
- **File:** `src/api/v2/bookings.py`

**Affected Endpoints:**
- `POST /api/v2/bookings/quick-book` — advance payment create
- Activity feed (join fails)

**Impact:** **Low** — advance payment not visible in activity feed. Only affects quick-book advances.

**How It Was Missed:** ORM flush mechanics not obvious. Audit entry created immediately after add without flush.

**Prevention Steps:**
1. After ORM add without explicit flush: manually call `session.flush()` before using `.id`
2. Test: create payment via quick-book → verify in activity feed
3. Code review: check all audit entries use correct `entity_id`

**Pattern:** ORM lifecycle (see BUG-0042: Session flush timing)

**Fixed:** 2026-05-26, v1.76.35, commit `358a59e` (rewritten activity feed to query payment table directly)

**Test Coverage:** Integration test: quick-book with advance → verify in activity feed

---

## BUG-0031: Occupied beds query missing stay_type (shows rent not rate for day-stays)

**Symptom:** Occupied beds panel shows day-stay tenants with "₹X/mo" instead of "₹X/day". Misleading rate display.

**Root Cause:** Occupied beds query didn't include `stay_type` or `daily_rate`. Falls back to `agreed_rent` only. Day-stays showed as monthly.

**Implementation:**
- **Before:** `SELECT tenancy_id, room_id, agreed_rent...` (no stay_type or daily_rate)
- **After:** Include `stay_type`, `daily_rate`; format as "₹X/day" when day-stay
- **File:** `src/api/v2/kpi.py` — occupied beds query

**Affected Endpoints:**
- `GET /api/v2/kpi` — KPI response occupied beds
- `web/components/home/kpi-grid.tsx` — occupied beds list

**Impact:** **Low** — cosmetic (label wrong). Doesn't affect functionality.

**How It Was Missed:** Query only selected needed fields for old-style monthly tenancies. Day-stay added later, queries not updated.

**Prevention Steps:**
1. When adding new tenancy type (day-stay), audit all queries that select tenancy fields
2. Always include stay_type + daily_rate when needed for display
3. Test: add day-stay → verify occupied panel shows /day not /mo

**Pattern:** Missing field in query (see BUG-0001: Non-existent full_name)

**Fixed:** 2026-05-26, v1.76.44, commit `8131693`

**Test Coverage:** Query test: verify occupied beds response includes stay_type for day-stays

---

## BUG-0032: Payment history search excluded exited/cancelled (then included all, then fixed)

**Symptom:** User searches for old tenant to add payment. Search returns nothing. Tenant exited months ago. Can't find them.

**Root Cause:** Initial search change added exited/cancelled to support payment history. But applied globally. Then reverted too far. Multiple iterations.

**Implementation:**
- **Iteration 1:** Search excluded exited (working)
- **Iteration 2:** Added exited to support payment history (broke search for active tenants)
- **Iteration 3 (fix):** Keep search default active-only; add flag for payment history: `active_only=false`
- **File:** `src/api/v2/tenants.py:search`

**Affected Endpoints:**
- `GET /tenants/search` — tenant search
- `web/app/payments/history/page.tsx` — payment history page

**Impact:** **Medium** — search broken multiple times. User confusion.

**How It Was Missed:** Feature added iteratively without comprehensive test. Multiple reverts suggest approach confusion.

**Prevention Steps:**
1. Always have default conservative behavior (active-only)
2. Explicit opt-in for loose query scope (add flag parameter)
3. Test: search active tenant (works), search exited (doesn't work), search with flag (works)

**Pattern:** Query scope / flag handling (see BUG-0010: Tenant search changes)

**Fixed:** 2026-06-02, v1.76.47, commit `c3c9212` + multiple iterations

**Test Coverage:** Integration test: search defaults to active, flag allows exited

---

## BUG-0033: Payment form defaults to UPI for deposit (hardcoded, should toggle)

**Symptom:** Payment form shows deposit collection. User expects Cash option but only UPI appears. Must manually switch mode.

**Root Cause:** Deposit payment box in collection modal had hardcoded UPI, no toggle. Rent had Cash/UPI toggle but deposit didn't.

**Implementation:**
- **Before:** Deposit box: `<select mode> fixed to UPI`
- **After:** Add Cash/UPI toggle like rent box
- **File:** `web/components/payment/collection-modal.tsx` or similar

**Affected Endpoints:**
- Payment collection modal (client-side only)

**Impact:** **Low** — UX friction (requires extra click). Doesn't block workflow.

**How It Was Missed:** Modal built incrementally; rent and deposit boxes coded separately. Parity not enforced.

**Prevention Steps:**
1. Payment form: all amount fields MUST have payment mode toggle
2. Test: verify rent box and deposit box both have mode selector
3. Code review: check parity between boxes

**Pattern:** UI parity (see BUG-0025: Day-stay hint)

**Fixed:** 2026-05-26, v1.76.35, commit `0781e3c`

**Test Coverage:** E2E test: collection modal deposit → verify UPI/Cash toggle present

---

## BUG-0034: Date picker positioned inside modal (clipped by overflow)

**Symptom:** Date picker dropdown appears but gets cut off by modal overflow. Can't see full calendar. User can't pick date.

**Root Cause:** Date picker positioned `absolute` with `top`, but parent modal has `overflow: hidden`. Picker rendered outside modal bounds and clipped.

**Implementation:**
- **Before:** Date picker: `position: absolute; top: 0; left: 0;` (clipped by parent overflow)
- **After:** Use `position: fixed` instead (escape modal overflow)
- **File:** `web/components/ui/date-picker-input.tsx` or similar

**Affected Endpoints:**
- Collection modal date fields
- Other modals with date pickers

**Impact:** **Medium** — can't set date in modal. Workflow broken.

**How It Was Missed:** Modal + date picker z-index/positioning not tested. CSS overflow behavior not verified.

**Prevention Steps:**
1. Any absolute-positioned element inside scrolling parent: use fixed or portal
2. Test modal with date pickers: verify picker visible and usable
3. Linter: warn on `position: absolute` inside `overflow: hidden`

**Pattern:** CSS positioning / modal layering (see BUG-0025: Modal issues)

**Fixed:** 2026-05-26, v1.76.35, commit `b8efccf`

**Test Coverage:** E2E test: open modal with date picker → verify dropdown visible

---

## BUG-0035: Void payment endpoint has no permission gate (security issue)

**Symptom:** Any user could void any payment. Could erase financial records. Security breach.

**Root Cause:** `DELETE /api/v2/payments/{id}` endpoint had no permission check. No check for `is_admin` or role.

**Implementation:**
- **Before:** Endpoint callable by anyone
- **After:** Add role check: `if ctx.role not in ["admin", "power_user"]: raise 403`
- **File:** `src/api/v2/payments.py` or similar

**Affected Endpoints:**
- `DELETE /api/v2/payments/{id}` — void payment endpoint
- `web/app/payments/history/page.tsx` — payment history void button

**Impact:** **Critical** — security breach. Data integrity at risk. Any authenticated user can void payments.

**How It Was Missed:** Permission checks not systematic. Endpoint added without reviewing role gates.

**Prevention Steps:**
1. All endpoints that modify financial data MUST check `is_admin`
2. Code review: search for DELETE/PATCH on payments, check role gate
3. Security audit: run endpoint tests without admin role, verify 403

**Pattern:** Permission gates (see BUG-0013: Permission isolation)

**Fixed:** Should be immediate; commit hash pending

**Test Coverage:** Unit test: void payment without admin role → verify 403 error

---

## BUG-0036: "Room 102 is full" false positive (edit session excluded own tenancy)

**Symptom:** Edit button on Bookings page says "Room 102 is full" even though it's the same person. Can't edit their booking.

**Root Cause:** `src/api/onboarding_router.py:PATCH /admin/{token}` (edit) counted session's own pre-booked no_show as occupant. For 2-bed room with 1 active + 1 pre-booked (same person), returned 2/2 full.

**Implementation:**
- **Before:** Manual get_room_occupants call (counted own no_show)
- **After:** Use `check_room_bookable(..., exclude_tenancy_id=obs.tenancy_id)` canonical helper (excludes own slot)
- **File:** `src/api/onboarding_router.py` — PATCH handler

**Affected Endpoints:**
- `PATCH /api/v2/onboarding/admin/{token}` — edit session
- `web/app/onboarding/bookings/page.tsx` — "Edit" button

**Impact:** **Medium** — can't edit booking. Workflow blocked.

**How It Was Missed:** Manual occupancy logic duplicated across endpoints. Own-tenancy exclusion pattern not applied consistently.

**Prevention Steps:**
1. Canonical helper: `check_room_bookable` with `exclude_tenancy_id` param
2. All occupancy checks MUST use this helper, never manual logic
3. Test: edit own booking in full room → verify allowed

**Pattern:** Helper function consolidation (see BUB-0027: Edit session capacity check)

**Fixed:** 2026-05-30, v1.76.40, commit in onboarding_router.py

**Test Coverage:** Integration test: edit booking in full room → verify succeeds

---

## BUG-0037: Room 108 THOR → revenue (floor layout change)

**Symptom:** TOTAL_BEDS constant was 296 but should be 298. Room 108 was staff, now revenue (2 new beds).

**Root Cause:** Room 108 (THOR) reclassified from `is_staff_room=true` to revenue. TOTAL_BEDS updated in 1 place, missing in 5 others.

**Implementation:**
- **Before:** Room 108 staff, TOTAL_BEDS = 296 across codebase (inconsistent)
- **After:** Room 108 revenue, TOTAL_BEDS = 298 (updated everywhere)
- **Locations updated:**
  1. `src/database/migrate_all.py` — migration `run_room_108_revenue_2026_05_31`
  2. `src/integrations/gsheets.py` — TOTAL_BEDS constant
  3. `scripts/clean_and_load.py` — TOTAL_BEDS constant
  4. `scripts/gsheet_apps_script.js` — const TOTAL_BEDS
  5. `scripts/gsheet_dashboard_webapp.js` — const TOTAL_BEDS
  6. `docs/MASTER_DATA.md` — staff/revenue layout
  7. `docs/BRAIN.md` — staff rooms section
  8. `docs/BUSINESS_LOGIC.md`, `docs/REPORTING.md`, `docs/SHEET_LOGIC.md` — TOTAL_BEDS constant

**Affected Endpoints:**
- All endpoints that calculate occupancy rate (uses TOTAL_BEDS)
- Reporting endpoints
- Dashboard calculations

**Impact:** **High** — occupancy % wrong (denominator off by 0.7%). Subtle data error cascades through reports.

**How It Was Missed:** TOTAL_BEDS scattered across codebase. No central registry. Change in one place wasn't propagated.

**Prevention Steps:**
1. Before any `is_staff_room` change, follow CLAUDE.md checklist: update 10 locations
2. Post-change: `grep -r "TOTAL_BEDS" .` to verify all updated
3. Compare before/after: `show master data` bot command

**Pattern:** Distributed constant (see CLAUDE.md critical section "When is_staff_room changes")

**Fixed:** 2026-05-31, v1.76.44, migration + multi-file updates

**Test Coverage:** Query test: verify TOTAL_BEDS = 298 in all locations

---

## BUG-0038: Room occupancy check hard-blocks full rooms (disallows future pre-booking)

**Symptom:** Pre-book tenant into room, try to check in on future date after others checkout. System says "Room full". Shouldn't block future-dated check-ins.

**Root Cause:** `src/api/onboarding_router.py:/create` endpoint had zero occupancy check. Added check but made it too strict: blocks all full rooms, even if check-in date is after current occupants' checkout.

**Implementation:**
- **Before:** No check
- **After:** Use future-booking logic: allow if `beds_still_occupied(checkin_date) < max_occ`. Blocks only if room full on that specific date.
- **File:** `src/api/onboarding_router.py` — create endpoint

**Affected Endpoints:**
- `POST /api/v2/onboarding/create` — create onboarding session
- `web/app/onboarding/bookings/page.tsx` — "Add booking" button

**Impact:** **Medium** — can't pre-book into currently-full rooms. Blocks valid future bookings.

**How It Was Missed:** Guard added without understanding future-booking logic. Strictness level not reviewed.

**Prevention Steps:**
1. Occupancy check for future dates: use same `check_room_bookable` as approval (has future logic)
2. Test: book tenant into full room with future check-in → verify succeeds
3. Test: book into full room with today's check-in → verify fails

**Pattern:** Validation strictness (see BUG-0003: Minimum collection validation)

**Fixed:** 2026-05-29, v1.76.39, commit in onboarding_router.py

**Test Coverage:** Integration test: book into full room with future check-in → verify succeeds

---

## BUG-0039: Room occupancy check doesn't exclude room 000 placeholder

**Symptom:** Can't book into room 000 (placeholder). System treats it as real room and counts towards occupancy. But room 000 shouldn't accept tenancies.

**Root Cause:** Occupancy check didn't know about room 000 being special. Should skip it entirely.

**Implementation:**
- **Before:** Check all rooms including 000
- **After:** Add guard: skip room 000 from checks and Bookings listing
- **File:** `src/api/v2/bookings.py`, `src/api/onboarding_router.py`

**Affected Endpoints:**
- `POST /api/v2/bookings/quick-book` — prevent room 000
- `POST /api/v2/onboarding/create` — prevent room 000
- Bookings page API

**Impact:** **Low** — room 000 shouldn't be used anyway. But blocks accidental use.

**How It Was Missed:** Room 000 is implementation detail (placeholder). Wasn't obvious it should be filtered.

**Prevention Steps:**
1. Room 000 is reserved. Add comment in room model.
2. All room-listing endpoints MUST exclude 000 (except internal admin APIs)
3. Test: verify no bookings in room 000

**Pattern:** Special case handling (see BUB-0028: Room 000 tenancies)

**Fixed:** 2026-06-02, v1.76.47, commit `892d75d`

**Test Coverage:** Integration test: try to book room 000 → verify 422 error

---

## BUB-0040: Delete tenancy audit log missing RS row count

**Symptom:** Audit log for deleted tenancy doesn't show how many rent schedule rows were affected. Hard to trace what was deleted.

**Root Cause:** `src/api/v2/tenants.py:delete_tenancy` hard-delete cascades to rent_schedule, but audit note wasn't updated to record count.

**Implementation:**
- **Before:** Audit log: `reason="deleted"` (no RS info)
- **After:** Before delete, count RS rows: `audit_note = f"deleted tenancy + {rs_count} RS rows"`
- **File:** `src/api/v2/tenants.py`

**Affected Endpoints:**
- `DELETE /api/v2/tenancies/{id}` — hard delete tenancy
- Audit log reporting

**Impact:** **Low** — audit trail incomplete. Doesn't block functionality.

**How It Was Missed:** Audit detail not thought through. Cascade delete happens silently.

**Prevention Steps:**
1. Before any cascade delete: count affected child rows
2. Audit log must record count for audit trail
3. Test: delete tenancy → verify audit includes RS row count

**Pattern:** Audit completeness (see BUG-0014: Audit logging)

**Fixed:** 2026-06-03, v1.76.49, commit in tenants.py

**Test Coverage:** Query test: verify audit log includes RS row count

---

## BUG-0041: Bookings page scroll position lost on cancel (full reload)

**Symptom:** User scrolled down on Bookings page to see booking card. Clicks "Cancel". Page reloads and scrolls to top. User has to scroll again.

**Root Cause:** `web/app/onboarding/bookings/page.tsx` called full page reload (`onReload()`) instead of removing card from state. React doesn't preserve scroll position on reload.

**Implementation:**
- **Before:** `onCancel` → `onReload()` → full page refresh
- **After:** `onCancel` → remove from state (local) → scroll preserved
- **File:** `web/app/onboarding/bookings/page.tsx`

**Affected Endpoints:**
- Cancel button on booking cards (client-side only)

**Impact:** **Low** — UX friction. Doesn't block workflow.

**How It Was Missed:** Full-page reload seemed safest (ensures fresh data). Local state removal was assumed to lose data.

**Prevention Steps:**
1. State removal patterns: test that data stays consistent
2. For list items: remove from state array instead of full reload
3. Use optimistic updates + refetch pattern

**Pattern:** UI state management (see BUG-0025: Modal state issues)

**Fixed:** 2026-06-07, v1.76.51, commit `3b75d01`

**Test Coverage:** E2E test: scroll down → cancel booking → verify scroll position preserved

---

## BUG-0042: No-show tenants not counted in capacity check (allows double-booking)

**Symptom:** Pre-book tenant into room, pre-book second tenant same date. System allows both even though room only has 1 bed. Capacity violated.

**Root Cause:** Capacity check only counted `active` status. Didn't count `no_show` pre-booked beds. Result: can double-book using two pre-bookings.

**Implementation:**
- **Before:** `count(tenancies WHERE status = active)`
- **After:** `count(tenancies WHERE status IN (active, no_show))`
- **File:** `src/api/v2/bookings.py`, `src/api/v2/rooms.py`

**Affected Endpoints:**
- `POST /api/v2/bookings/quick-book` — booking create
- `GET /api/v2/rooms/check` — availability check

**Impact:** **High** — double-booking. Data corruption.

**How It Was Missed:** no_show is pre-booked but not yet checked in. Easy to forget in occupancy logic.

**Prevention Steps:**
1. Occupancy check counts: active + no_show (both claim a bed)
2. Test: quick-book twice same date → verify 422 on second
3. Add to golden test: double-booking prevention

**Pattern:** Status filtering (see BUG-0010: Tenant search status)

**Fixed:** 2026-05-31, v1.76.36, commits `9599975`, `388d9d4`

**Test Coverage:** Integration test: quick-book twice same room → verify blocked

---

# Older Bugs (v1.76.29 and earlier) — Summary

Comprehensive historical bugs up to v1.76.30. Earlier bugs (v1.5.0–v1.76.29) follow same pattern:
- Mostly early-stage: incomplete feature implementations, missing validation, data sync issues
- Bot flow bugs (intent detection, handler routing, confirmation flows)
- Sheet integration bugs (format inconsistency, duplicate handling, encoding issues)
- Payment workflow bugs (void handling, rent reminders, collection modal)
- Excel import pipeline (dedup, column mapping, data integrity)

These are documented in CHANGELOG but not individually ticket-mapped. Can create tickets BUG-0043+ if needed for deep historical analysis.

---

# Bug Pattern Summary

| Pattern | Count | Key Examples |
|---------|-------|--------------|
| Multi-path consistency | 6 | BUG-0002 (quick_book), BUG-0009 (check-in guards), BUG-0042 (status filtering) |
| Query scope / filtering | 5 | BUG-0008, BUB-0010, BUG-0011, BUG-0031, BUG-0032 |
| State/data sync | 4 | BUG-0012, BUG-0014, BUG-0029, BUG-0037 |
| Validation gaps | 4 | BUG-0003, BUG-0027, BUG-0035, BUB-0039 |
| Timestamp/date semantics | 3 | BUG-0016, BUG-0020, BUG-0042 |
| Missing field in query | 3 | BUG-0001, BUG-0031, BUB-0001 |
| UX/form state | 3 | BUG-0025, BUG-0033, BUG-0041 |
| Performance | 1 | BUG-0004 |

---

# Prevention Checklist

When implementing any feature, verify:

- [ ] **Multi-path check:** If 2+ code paths do same thing, extract to helper function
- [ ] **Query audit:** All queries selecting model fields verified for new columns
- [ ] **State sync:** Any bidirectional link (tenancy ↔ onboarding_session) kept in sync
- [ ] **Validation completeness:** All code paths that modify data have guards (permission, capacity, format)
- [ ] **Timestamp semantics:** Distinguish payment_date (financial) vs created_at (event order)
- [ ] **Test coverage:** Multi-scenario tests (happy path + errors + edge cases)
- [ ] **Code review:** Search codebase for similar patterns, verify consistency
- [ ] **Permission gates:** All DELETE/PATCH endpoints check role
- [ ] **Documentation:** New fields documented in BRAIN.md / REPORTING.md
- [ ] **Deployment:** Run full test suite locally before push

---

# How to Use This File

**For new bugs:** Assign next ticket ID (BUG-0043, etc.) and add to this file before closing PR.

**For recurring issues:** Check "Pattern" column. If matches existing pattern, link via comment: "Related to BUG-0009 (multi-path consistency)".

**For code review:** Use Prevention Checklist before approving PRs.

**For postmortems:** Reference bug ticket when documenting root cause analysis.
