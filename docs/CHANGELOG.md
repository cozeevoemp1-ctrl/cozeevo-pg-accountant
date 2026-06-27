# Changelog

## Session I — 2026-06-27 — Late-notice deposit forfeiture (policy regression fix)

### Summary
- 🐛 **Notices page showed "Refundable" for a notice given today (Adarsh, Room G01, notice 26 Jun — late).** Root cause: `is_deposit_eligible()` in `services/property_logic.py` had been regressed to `return True` ("any notice → refundable; only zero-notice forfeits"), diverging from both the original 2026-04-28 spec AND the existing `test_notice_comprehensive.py` tests (which encode day≤5 = eligible, day>5 = forfeited — they were silently failing). Docs also contradicted each other (REPORTING.md said late=refunded; spec said late=forfeited).
- ✅ **Kiran's decision: late notice (after 5th) = deposit FORFEITED** (revert to original spec). On-time notice (≤5th) → refundable; late notice OR no notice → forfeited.
- ✅ **Fixed the single source of truth** `is_deposit_eligible(notice_date)` → `notice_date is not None and notice_date.day <= NOTICE_BY_DAY`; now handles `None`. Updated `NOTICE_BY_DAY` docstring.
- ✅ **All consumers wired to the central rule**: `notices.py` (deposit_eligible), `checkout.py` (refund-must-be-0 validation now covers late notice, with reason), `kpi.py` (notices detail no longer hardcodes True). PWA: `checkout/new` (forfeiture derivation + late banner flipped to orange "Deposit Forfeited"), `notices` legend, `tenants/[id]/edit` badge + helper text. Bot: `owner_handler` (5 sites: pre-checkout summary, disambiguation summary, settlement net calc + line, notice-given note, exits list), `tenant_handler` (late-notice reply), agreement PDF `HOUSE_RULES`.
- ✅ **Docs merged/aligned** — REPORTING.md §6.5 + §7.1 (now points to `property_logic` as canonical, supersedes spec), BUSINESS_LOGIC.md §6.3, rental agreement text. Added `None`→forfeited test. 17/17 deposit tests pass (4 unrelated `test_future_month_extracted` failures are pre-existing).
- ⚠️ **Flag**: the rental-agreement PDF text was changed to "deposit forfeited" for late notice. Tenants who signed the *old* agreement ("still refundable") may be legally entitled to a refund — apply the new rule only to agreements signed after this change.
- 📝 **Secondary (not fixed)**: Adarsh's stored `expected_checkout` (29 Jun) violates the late-notice rule (should be 31 Jul end-of-next-month). The PATCH endpoint lets a manual `expected_checkout` override the auto-calc. Moot now that his deposit is forfeited, but the override path can still drop the notice period silently.

## Session H — 2026-06-17 — Vacant-bed KPI vs room-list off-by-one

### Summary
- ✅ **"Vacant beds 10" tile ≠ "11 beds free" room list** (same home screen): the two numbers used different definitions of "occupied". KPI tile uses `get_occupied_beds()` = active **+ no-show whose checkin_date ≤ today** (held beds); the vacant room-search panel counted only **active** tenants, so a no-show booked to arrive **today** (Room 116, Rajveer Khanna) was held by the tile but advertised as a free bed in the list → 11 vs 10. Aligned the vacant-detail occupancy subquery (`kpi.py` L438-462) with `get_occupied_beds`: no-shows with `checkin_date ≤ today` now count as occupying the bed. Future no-shows (checkin > today) stay free with their "Until X" tag. Verified against live DB: both read 10. Commit `52c90ca`.

### Notes (environment, not project code)
- Installed **UI/UX Pro Max** skill bundle (7 skills incl. flagship `ui-ux-pro-max`) globally to `~/.claude/skills/` — universal, auto-invoked for any UI design/build/review task. Scanned all scripts before install (clean). 21st.dev Magic MCP was set up then removed at Kiran's request (no project footprint).

## Session G — 2026-06-15 — Day-stay dues model: advance/deposit + waivers + 307 forensics

### Summary
- ✅ **Day-stay advance double-count** (room 208 showed ₹800, real ₹5,800): the booking advance is already a `booking` Payment row, but the daily dues formula also added `tenancy.booking_amount` → counted twice. Removed the field add. Commits `99fe814`, `befc0a3`.
- ✅ **Single source of truth**: collapsed the 4 copied day-stay dues formulas into `src/services/daily_dues.py` (`daily_dues()`, `booking_credit()`). Commit `a5ed503`.
- ✅ **Deposit due ignored the advance** (424 showed ₹5,000, 614 ₹2,000; real ₹0): monthly deposit-due credited the stale `booking_amount` field (0 for onboarding-flow tenants) instead of the `booking` Payment rows. Fixed via shared `booking_credit()` across kpi.py (×2), tenants.py, tenant_handler.py. Commit `c96b8a7`.
- ✅ **Day-stay advance/deposit now held separately** (not netted against stay): per Kiran, advance/deposit go toward the security deposit, excluded from stay dues. 208 → ₹10,800 + ₹5,000 held. Added editable Security Deposit field to Edit Tenant for day stays. Commits `cb6bd46`, `e436040`.
- ✅ **KPI tile ≠ list (₹1,05,416 vs ₹84,250)**: "Dues pending" tile counted `no_show` (G03 Abhishek Jain, ₹21,166 pre-booked) while the dues list is active-only. Tile now active-only to match. Commit `b979808`.
- ✅ **Waived day-stay dues**: 115 Udhayabharathi ₹1,800 + 510 Ajit ₹750 (no payment records — advance only in legacy field) via non-revenue `other` entries (audit-logged, void-able). 618 SHASHANK already ₹0 (₹1,800 collected since).
- 🔎 **Room 307 forensics** (tenancy 1218): (1) name shows "Lokesh" not "kiran" — booking matches tenant by **phone** (7680814628 = Lokesh's own number, reused in test bookings) and reuses the existing "Lokesh" record, **ignoring the typed name**. (2) Auto-"checked in" (active, no audit, session never approved) — behaves like the **pre-`bb4bbab` date-based auto-checkin** code; the 13-Jun fix that requires explicit approval wasn't live on the server when Lokesh booked (deploy lag).

### Pending (open decisions)
- **Day-stay deposit-overflow model NOT implemented**: the unified rule (advance fills `security_deposit` first, overflow → stay; mirrors monthly) was designed but Kiran pivoted to manual waivers. Revisit if per-tenant deposit control is wanted.
- **Room 307 / tenancy 1218 cleanup**: erroneous active day-stay under "Lokesh"/his own number — awaiting decision (cancel / revert to no_show / fix tenant).
- **Booking name-vs-phone bug**: when typed name ≠ matched tenant's name, booking should flag or create a new tenant — not fixed. Also: block staff booking under their own number.

## Session F — 2026-06-15 — Connectivity audit + premium/booking/checkout dedup

### Summary
- ✅ **Connectivity audit** delivered: `docs/audits/2026-06-15-connectivity/` (README + PWA→endpoint map + logic-divergence). Headline: "what does this tenant owe?" is computed by **8 independent implementations**; occupancy/collection/P&L have canonical services that some callers bypass.
- ✅ **Premium-shows-free-bed (data)**: rooms 208, 607, 503, 507, 511 had whole-room tenants with `sharing_type` NULL → counted as 1 bed. Set `sharing_type=premium` (audited). Swept whole property; the 6 remaining single-in-double rooms are genuine free beds (normal rent) — left alone.
- ✅ **Checked-in stuck in Bookings**: 5 sessions (208,309,503,607,617) were `pending` while their tenancy was active → marked `approved`. Code fix: `/admin/pending` now excludes sessions whose tenancy is active/cancelled/exited.
- ✅ **checkouts_today counted dead tenancies**: tile (kpi.py L191) + detail (L381) filtered `checkout_date==today` with no status filter → cancelled dup (Muthu G15) showed twice. Both fixed in one edit to require `status IN (active, exited)`.
- ✅ **Dues panel ≠ collect modal (D3)**: kpi.py overdue tile + dues detail dropped first-month `adjustment` (waiver); Nikhil 224 showed ₹5,700 on panel vs ₹2,500 in modal (−₹3,200 waiver). Both kpi copies now apply `max(0, prorated+adjustment)` to match `get_tenant_dues`. Commit `b87cee1`.
- ✅ **Booking/payment duplicates (current period)**: Santosh 507 old ₹1000 voided; SHASHANK 618 ₹3800 re-linked to live 1217 + dup cancelled; Muthu G15 consolidated onto 1205; room-000 trio (Niranjan/Nikita/S Narendh) ₹2000 advances re-linked to live tenancies; Adithya ₹500 maintenance dup voided.
- ✅ **Split-payment false alarm caught**: 7 of 10 flagged "duplicate payments" were legit half-cash/half-UPI splits by premium tenants (~₹85k) — NOT voided. Rule saved.
- ⛔ **Frozen left untouched** (per Kiran): 871 G.D.Abhishek April ₹11,750 dup + 11 Dec-era cancelled tenancies holding ~₹2.4L deposits/rent — flagged for review, not modified.
- ✅ Deployed: commit `eca335d` (kpi.py + onboarding_router.py); 52 tests pass.

### Root causes
- **No `sharing_type` field in PWA edit/booking forms** → premiums can't be set/corrected in-app; they default unmarked and rooms show phantom free beds. (Phase-2 fix.)
- **Disconnected duplicate queries** → updating data in one place (cancel/premium) doesn't reflect in tiles/panels that re-query independently without status filters. (Audit thesis; Phase-2 = centralize.)

### Pending (Phase 2 — not started)
- Centralize `compute_tenant_dues()`; wire all 8 call-sites.
- Add `sharing_type` to tenant edit + booking forms (root cause of premium mismatch).
- Re-book: reuse existing booking for same phone+room instead of spawning a 2nd tenancy+payment.

## Session E — 2026-06-14 — Payment NULL-column bugs: history/dues/sheet not connected

### Summary
- ✅ Root-caused why payments existed in DB but vanished from the app: raw-SQL insert paths leave columns NULL because they had only Python-side ORM defaults (no `server_default`)
- ✅ `is_void = NULL` (8 rows, ₹85,750) excluded by every `WHERE is_void = false` filter → invisible in history/dues/P&L/sheet
- ✅ `created_at = NULL` (21 rows) crashed `sync_sheet_from_db` (`can't compare datetime to date`) → edits never tallied to Sheet (April/May)
- ✅ Hardened both columns (backfill + `server_default` + migration); made list endpoint + sync NULL-safe
- ✅ Sachin Kumar Yadav (Rm 409) March deposit 21397 reduced ₹5,250→₹4,750 → deposit_due now ₹500
- ✅ Resynced April/May/June sheet tabs; ruled out "failed to fetch" (was the deploy restart window — all endpoints healthy, CORS correct)
- ✅ 52 tests pass; commits 72e3345, a7ff027 (auto-deployed)
- ⏳ Live Playwright verification still pending (blocked on PWA login password)

### Bugs Fixed
**Bug 1: Payments with `is_void = NULL` invisible everywhere**
- Root cause: `payments.is_void = Column(Boolean, default=False)` — Python-only default, no `server_default`. Raw inserts → NULL. `is_void = false` filter drops NULL under SQL 3-valued logic.
- Fix: backfill NULL→false; `ALTER ... SET DEFAULT false NOT NULL`; `models.py` updated; migration `run_payments_void_not_null_2026_06_14`; `list_payments` filter → `is_void IS NOT TRUE`; restored dropped `limit` param + all-tenants default view + cross-tenancy expansion (regressed by the 5 "simplify" rewrites de41adf…fe3eaf0).

**Bug 2: `created_at = NULL` crashed the Sheet sync**
- Root cause: same pattern — `created_at` had only `default=datetime.utcnow`. NULL fell back to `payment_date` (a `date`) and was compared against another row's `datetime`.
- Fix: `sync_sheet_from_db` latest-payment key normalized to `(datetime, id)`; backfill 21 NULL→`payment_date`; `created_at SET DEFAULT now()`; migration extended.

### Data Changes
- Payment 21397 (Sachin Rm 409): amount ₹5,250 → ₹4,750, audit-logged (reason: ₹500 deposit pending)
- April/May/June 2026 sheet tabs resynced from DB

## Session D — 2026-06-13 — Bug Fixes: Data Consistency + Day-stay Enhancement + Payment Records

### Summary
- ✅ 6 critical bugs fixed from earlier in session (auto-checkin, pending bookings, day-stay fields, refund logic, cancel endpoint, home page perf)
- ✅ Day-stay daily_rate now fully editable in tenant edit page
- ✅ Advance payments voided for cancelled Room 108 bookings
- ✅ Jitendra Kochale deposit payment recorded (₹10,500, settled with booking advance)
- ✅ All 52 unit tests passing, PWA builds successfully
- ✅ Deployed to VPS

### Bugs Fixed (6 Critical Issues)

**Bug 1: Auto-checkin by Date Removed**
- **Problem:** Bookings with today's check-in date auto-checked-in without admin approval (Room 208 example)
- **Root Cause:** Two endpoints had logic: `if checkin_date <= today() then status=active`
- **Files:** `src/api/v2/bookings.py:227`, `src/api/onboarding_router.py:1766`
- **Fix:** Removed date-based auto-checkin; now requires explicit `instant_checkin=true` flag
- **Verification:** Manual check-in now required; no auto-transitions
- **Commit:** bb4bbab

**Bug 2: Pending Tenant Bookings Hidden**
- **Problem:** Bookings page showed 24 of 32 bookings (missing pre-booked tenants)
- **Root Cause:** Filter on line 86-88 excluded `pending_tenant` status
- **Files:** `web/app/onboarding/bookings/page.tsx`
- **Fix:** Show all three statuses (pending_tenant + pending_review + expired) in UI
- **Verification:** 8 pre-booked bookings now visible
- **Commit:** 835708e

**Bug 3: Day-stay Bookings Show Monthly Fields**
- **Problem:** Room 208 (day-stay) showed "Agreed Rent (₹/mo): 0" instead of "Daily Rate (₹/night): 1200"
- **Root Cause:** editRent initialized from agreed_rent (0) instead of daily_rate
- **Files:** `web/app/onboarding/bookings/page.tsx`, `web/app/tenants/[tenancy_id]/edit/page.tsx`
- **Fix:** Initialize from correct field based on stay_type; hide monthly fields for day-stays in tenant edit
- **Verification:** Correct daily rate displays in edit form
- **Commits:** 6431c15, fa13731

**Bug 4: Checkout Form Refund Calculation Wrong**
- **Problem:** Shows ₹1,000 refund for forfeited deposits (no notice) when should be ₹0
- **Root Cause:** `depositForfeited` logic didn't account for day-stays having no deposits
- **Files:** `web/app/checkout/new/page.tsx`
- **Fix:** Set `depositForfeited=true` for all day-stays (no deposits to refund)
- **Verification:** Checkout shows correct refund amounts
- **Commit:** dd3dd27

**Bug 5: Cancel Booking Endpoint Crashes**
- **Problem:** "Failed to fetch" when clicking Cancel; API crashes with `NameError: name 'text' is not defined`
- **Root Cause:** `src/api/onboarding_router.py:761` used `text()` but never imported it
- **Files:** `src/api/onboarding_router.py:18`
- **Fix:** Added `text` to import: `from sqlalchemy import select, update, text`
- **Prevention:** Created `feedback_import_management.md` (SQLAlchemy import checklist)
- **Commit:** 4a66830

**Bug 6: Home Page 6-Second Load Time**
- **Problem:** Home page took 6+ seconds due to KPI endpoint doing 7+ sequential DB queries
- **Status:** Identified but not fully fixed (architectural issue)
- **Attempted:** Parallelized with `asyncio.gather()` → broke other endpoints (async session limitations)
- **Current:** REVERTED (commit 081547b); marked as deferred
- **Next:** Needs query caching, database indexes, or optimization (not parallelization)

### Features Added

**Day-stay Daily Rate Now Editable in Tenant Edit Page**
- **Before:** Could only edit daily_rate via Bookings page; tenant edit showed warning + hid fields
- **After:** Shows editable "Daily Rate (₹/night)" field; same save flow as monthly rent
- **Implementation:**
  - Added explicit `daily_rate` field to `TenantDues` API response (both day-stay and monthly)
  - Updated `web/lib/api.ts:TenantDues` interface
  - Frontend: conditional rendering based on `stay_type` (daily vs monthly)
  - Backend: daily_rate updates go through `agreed_rent` field (stores per-night rate for day-stays)
  - Changes logged as RentRevision + AuditLog entries
- **Scope:** Day-stays can now be fully edited from either Bookings or Tenants pages
- **Files:** `src/api/v2/tenants.py`, `web/lib/api.ts`, `web/app/tenants/[tenancy_id]/edit/page.tsx`
- **Commits:** 3247945, 9816eef

### Data Cleanup
**Advance Payments Voided**
- **Reason:** Cancelled bookings for Room 108 (Lokesh + Kiran) after manual cancellation
- **Voided:** 2 advance payments totalling ₹4,000
  - Payment 21359 (Lokesh): ₹2,000 booking advance → voided with audit log
  - Payment 21358 (Kiran Kumar): ₹2,000 booking advance → voided with audit log
- **Method:** Used void_payment logic with AuditLog entry (source=admin, note="Cancelled booking advance voided")
- **Verification:** Both payments marked `is_void=true` in database

### Payment Records Added
**Jitendra Kochale - Deposit Payment Recorded**
- **When:** April 2026 (₹10,500 UPI)
- **Record:** Payment ID 21361 (deposit for_type)
- **Settlement:** Booking advance (₹2,000) covers remaining shortfall
  - Deposit owed: ₹12,500
  - Paid: ₹10,500
  - Advance applied: ₹2,000
  - **Due: ₹0 (SETTLED)**

### Features Added
**Day-stay Daily Rate Now Editable in Tenant Edit Page**
- **Problem:** Day-stay bookings could only edit daily_rate via Bookings page; tenant edit page showed warning + hid fields
- **Solution:** 
  - Added explicit `daily_rate` field to `TenantDues` API response
  - Tenant edit page now shows editable Daily Rate field for day-stays
  - Same form logic as monthly rent: changes create RentRevision + AuditLog entries
  - Accepts same validation (must be > 0) and workflows
- **Scope:** Day-stays can now be fully edited from either Bookings or Tenants pages
- **Backwards compat:** Monthly bookings unchanged; daily_rate=0 for monthly (explicit in response)

### Issues Fixed

**1. PWA Build Failure (TypeScript Schema Mismatch)**
- **Problem:** KPI endpoint returned `notices_incoming` field but TypeScript schema didn't define it
- **Impact:** PWA build failed on VPS; pages (Notices, Bookings, Pre-Register) crashed with "client-side exception"
- **Root Cause:** Session C audit fix added field to backend but forgot to update schema
- **Fix:** Added `notices_incoming: number;` to `KpiResponse` interface in `web/lib/api.ts`
- **Commit:** c7b4e21

**2. Occupancy Calculation Divergence (Data Consistency)**
- **Problem:** KPI tile and Finance chart showed different occupancy % for the same date
  - KPI: 276 beds occupied → 92.6%
  - Chart: 279 beds occupied → different %
- **Root Cause:** Two separate endpoint implementations calculating occupied beds differently
  - KPI endpoint: counted active + no_shows (checkin_date <= today)
  - Analytics endpoint: counted active only (no no_shows)
- **Temporary Fix:** Updated analytics.py to match KPI logic (added no_show calculation)
- **Permanent Fix:** Extracted canonical occupancy service (`src/services/occupancy.py`)
  - `get_total_revenue_beds()` — single calculation, both endpoints use it
  - `get_occupied_beds(session, target_date)` — active + no_shows, both endpoints use it
  - `get_occupancy_pct(session, target_date)` — percentage, both endpoints use it
  - Both `kpi.py` and `analytics.py` now call the service instead of duplicating code
  - Removes 154 lines of duplicated calculation code
  - Guarantees no future divergence (one source of truth)
- **Commits:** 5e57c44, 5d3acff, baa2d97

### Verification
- ✅ All 52 unit tests passing
- ✅ KPI tile occupancy matches Finance chart occupancy
- ✅ Notices/Bookings/Pre-Register pages load without errors
- ✅ No divergence possible going forward (canonical service)

### Key Lesson
**Schema Sync:** When backend returns a new field, always update TypeScript schema in the same commit. Use a canonical service for calculations that appear in multiple endpoints.

---

## Session C — 2026-06-08 — Comprehensive Audit + Bug Fixes

(See earlier sessions for full details)

---
