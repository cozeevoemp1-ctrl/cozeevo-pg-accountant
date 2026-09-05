# Changelog

## Session AP — 2026-09-05 — Room 223 "cannot check in": diagnosis only, no code changed

Kiran: "why 223 is not able to check in?" — screenshot showed
`Cannot approve — status is approved` next to Save & Check In.

**Root cause: it had already checked in.** The first click succeeded; a deploy restart
landed on the very next request, so the list refresh failed and the card never left the
screen. The second click hit the idempotency guard, whose message reads like a failure.

Timeline (nginx + journald, UTC):
```
16:22:31  POST /api/onboarding/<tok>/approve        200   check-in written
16:22:32  GET  /api/onboarding/admin/pending        502   load() threw, card left stale
16:22:44  systemd Stopping/Started pg-accountant          restart window to 16:22:57
16:23:02  POST /api/onboarding/<tok>/approve        400   "Cannot approve — status is approved"
```

**Data verified clean — no duplicate.** Tenancy 1357 active (Ashfaaq Ahmed, room 223,
check-in 5 Sep), one RS row Sep ₹21,133, exactly three payments (₹5,000 booking +
₹6,633 rent + ₹2,000 deposit = ₹13,633), remaining ₹12,500 as shown in the UI.
Agreement PDF, selfie and ID proof all saved.

**Two defects filed in `docs/specs/current-issues.md` (open, awaiting approval to fix):**
1. `onboarding_router.py:1646` should return 200 "already checked in" instead of 400, and
   `bookings/page.tsx:126` should retry a failed post-approve `load()` rather than leaving
   a stale card that invites a second click.
2. The signed agreement PDF is sent as a free-form document 1s after the confirmation
   template — Meta rejects it with 131047 for any tenant who has never replied. Ashfaaq's
   PDF was never delivered and still needs re-sending manually.

**Fixed (`cc27b67`, live on VPS):**
- `src/api/onboarding_router.py` — an already-approved session now returns
  `200 {status: already_checked_in, tenant_id, tenancy_id}` instead of `400 Cannot approve`.
  Every other non-pending status still 400; unknown token still 404.
- `web/app/onboarding/bookings/page.tsx` — the card is removed from local state as soon as
  approve returns 200, so a failed post-approve reload can no longer leave a stale card
  that invites a second click.

Verified by calling `_approve_session_impl` against the real room-223 session: returns
`already_checked_in` / tenancy 1357 and writes nothing (payments still exactly 3).

**WhatsApp delivery (`fd7dd53`, `4fe6929`).** Meta's 24-hr window opens only when the
customer *replies* — a template does not open it. The agreement went out as a free-form
document 1s after the confirmation template, so it was dropped (131047) for every tenant
who had never messaged the bot: **52 of 64 check-ins in 60 days lost their agreement**;
2 received it; 10 had no PDF. New `src/services/tenant_delivery.py` checks the window
BEFORE sending (the rejection is asynchronous, so send-and-fallback is impossible) and
sends the PDF as an attachment or not at all. Kiran's rule: never a download link —
no storage/API URL in a customer's chat, ever. Also fixed: `_send_whatsapp_template`
returns False rather than raising, so all four link-send call sites were reporting a
phantom success and their free-form fallback was dead code.

**Tenant links moved to cozeevo.com (`fbd7e16`, applied live).** The form link was
`api.getkozzy.com/onboard/{token}` — an API hostname in a customer's hands. Now
`https://cozeevo.com/join/<token>`: DNS A → VPS, certbot cert, an nginx block that serves
`/join/`, `/api/onboarding/` and the logo and **404s everything else**, `BASE_URL` set and
verified in the running process. `/onboard/{token}` kept alive for links already sent.
Rule written into BRAIN §15a: cozeevo.com is the only hostname a customer ever sees.

**Parked:** the agreement PDF needs a document-header WhatsApp template to reach a
first-time tenant. Kiran parked it — do not build until he confirms. Ashfaaq (223) and
51 others remain undelivered. No schema or data changes this session.

## Session AO — 2026-09-05 — Room 621 Harshit: half-cancelled booking repaired; audit-trail rule

Kiran: "621 room booking is not shown anywhere — where is he?" He appeared only in the
"Awaiting check-in" tile, 62 days overdue, while physically living in Room 621 since 5 Jul.

**Root cause.** The booking was raised 17 Jul (back-dated to 5 Jul) with a ₹2,500 advance;
the onboarding link was never opened, so tenancy 1301 stayed `no_show`.
`scripts/_cleanup_2026_08_06.py` step F1 then cancelled onboarding session 279 as a "32-day
stale hold" (audit_log 2274) **without touching the tenancy** — and wrote no audit row against
it. Result: a paying resident invisible everywhere, billed nothing for two months, holding a
phantom bed in a double room (`room_occupancy.py:174` counts a past-dated `no_show` as occupied,
so 621 read 2/2 with only Kumar Satyam actually paying).

**Repair — `scripts/_fix_harshit_621_checkin.py`** (dry-run by default, `--write` to apply):
- Tenancy 1301 `no_show` → `active`, check-in 5 Jul unchanged.
- July rent schedule row **created** (₹23,693 = 27/31 prorated ₹12,193 + ₹14,000 deposit
  − ₹2,500 booking, via `first_month_rent_due()`); Aug + Sep rows `na`/₹0 → `paid`/₹14,000.
- Four payments back-entered per Kiran's account: 5 Jul ₹20,000 cash rent + ₹12,500 UPI deposit,
  ₹14,000 cash Aug, ₹14,000 cash Sep. **Aug/Sep dates default to the 5th** — exact days unknown,
  editable in the PWA.
- Onboarding session 279 `cancelled` → `pending_tenant`, fresh token, 7-day expiry — he has no
  KYC, no ID proof and no signed agreement on file after two months' residence.
- 11 audit_log rows written (2844–2852 + payments); Sheet resynced for Jul/Aug/Sep.

**Open:** ledger closes at **₹8,807 credit** — ₹60,500 collected vs ₹51,693 charged. Kiran said
"cleared all dues", so either the deposit is above ₹14,000, one amount is off, or he is prepaid
into October. Not adjusted — left visible rather than absorbed silently.

**Sweep:** Harshit was the only tenancy in this half-cancelled state. The 3 remaining overdue
no-shows (Balakrishna G13, Jainik 318, Vinayak 611) all have live sessions and are 1–4 days old.

**New rule — every write must be visible in the trail** (`docs/architecture/BRAIN.md` §15b,
memory `rules_audit_logs.md`): any DB change, including one-off fix scripts, must write
`audit_log` **and** surface in the activity feed. The feed filters on `field` — only
`agreed_rent, status, status+checkout_date, room_id, is_void, adjustment,
rent_schedule_one_off, sharing_type` render, so any other `field` is stored but invisible.
Never half-finish a state change across `onboarding_sessions` and `tenancies`.

**Stale ref found:** `CLAUDE.md` docs index points at `docs/BRAIN.md`; the file is
`docs/architecture/BRAIN.md`.

**Policy set for next session — spec 05 (specced, NOT built).** Kiran: "hereafter if any
booking is cancelled due to inactivity or not checked in it should show up in vacant beds,
it should not get stuck in awaiting, become stale."
`docs/specs/05-stale-booking-auto-release.md` + memory `rules_stale_bookings.md`.
Two-stage by design — warn operators at ~7 days, release at ~14 — because a real resident
whose check-in was never recorded is byte-identical to a genuine no-show, which is exactly
how Harshit would have been silently cancelled. Release reuses `cancel_no_show`
(`tenants.py:1198-1252`) extracted into `services/bookings.py::release_booking()`; vacant-beds
needs no change since `room_occupancy.py:62` already excludes `cancelled`. Booking advance is
never voided. 3 decisions open: grace period, auto vs manual button, advance handling.

## Session AN — 2026-09-05 — Booking terms / lock-in / stricter KYC (spec 04) — on `development`, NOT merged

Kiran: "does the note field on the booking form go to the customer?" — it did. "Notes (admin only)"
on the pre-book modal + pre-register page was stored in `onboarding_sessions.special_terms`, which
the agreement PDF prints under "Special Terms". Room 106 (Raghav Mittal) went out with "Lock in
period three months" as a special term while the same PDF's table said "Lock-in: 0 months" — the
forms had no lock-in input, so `lock_in_months` was always 0.

**Changes (`docs/specs/04-booking-terms-lockin-kyc.md`):**
- Three fields, three meanings: `lock_in_months` (structured), `special_terms` (customer-facing,
  form + PDF), NEW `admin_notes` column (internal only, never in the public token endpoint or PDF).
  Migration `run_add_onboarding_admin_notes_2026_09_05` applied to DB via txn pooler.
- `bookings.py` quick-book: `lock_in_months`, `special_terms`, `notes`→`admin_notes`.
- Pre-book modal (`kpi-grid.tsx`) + pre-register page: Lock-in select (shared `LOCK_IN_OPTIONS`),
  "Special terms (shown to customer)", "Notes (admin only, never shown to customer)".
- Bookings page: TERMS line (lock-in + special terms) above the NOTE line.
- `onboarding_router.py`: `_tenancy_notes_from_obs()` single source for tenancy/Sheet notes on
  approve (admin_notes + "Terms: …"), replaces 5 inline `obs.special_terms` sites; monthly
  tenancy now also gets notes (was never set).
- Customer form (`static/onboarding.html`): Special terms shown in room card + agreement card below
  lock-in; emergency phone == own phone rejected (client + server 400); Aadhaar BACK side is a
  required second upload (address is on the back) — OCR'd via `/extract-id`, stored as
  `saved_files.id_proof_back`, linked as `Document(id_proof)` on approve; Aadhaar OCR name must
  match the typed name — `src/utils/name_match.py` (12 tests) + identical JS mirror, enforced at
  Step 3 and at submit (400).
- `scheduler.py` check-in digest: notes = admin_notes | special_terms.
- KYC uploads are hard errors now: missing selfie/ID front (or Aadhaar back) → 400, storage
  failure → 502 "Could not save … submit again". Previously a failed upload was a log warning
  and the form still went through with the proof missing. Nothing is written to the session
  before the uploads succeed, so a failed submit leaves no partial state.
- Data fix: `scripts/_fix_106_lockin.py --write` → tenancy 1296 + session 273 `lock_in_months=3`,
  audit_log row. Tenant row is spelled "Raghad Mittal" (session says "Raghav") — left as is.

**Verified — 21/21 end-to-end smoke test** against a locally-run API on the live DB (WhatsApp sends
patched out, no approve step, test session + KYC files deleted afterwards): quick-book stores the
three fields separately; public `GET /api/onboarding/{token}` returns lock_in + special_terms and
leaks no admin_notes; served form contains the new markup; emergency-phone-equals-own → 400;
Aadhaar name mismatch → 400; Aadhaar without back side → 400; valid submit → 200 with selfie +
id_proof + id_proof_back all in storage; simulated storage outage → 502 (submit rejected).
Plus pytest 64/64, `tsc --noEmit` clean, `npm run build` clean.

**Shipped to production** 2026-09-05 — master `80793ee`, `api.getkozzy.com/healthz` confirms the
commit. Not yet exercised: the approve step (Documents rows for `id_proof_back`) — deliberately
skipped locally since it writes tenants/tenancies/Sheet. Check it on the next real check-in.

## Session AM — 2026-09-01 — Occupancy tab: avg rent KPI vs chart mismatch

Kiran: "why is the average rent different here (KPI ₹14,559) and in the chart (Sep '26 ₹14,550)?"

**Cause:** same formula (Σ agreed_rent / Σ beds, monthly only), two hand-written `WHERE` clauses in
`src/api/v2/analytics.py`. KPI card = `status=active` only. Chart's live-month point =
`_present_at(today)` = active OR on-notice (exited, checkout in future) OR **no_show** — the no_show
clause was copied from `get_occupied_beds` (where it's deliberate for bed *count*) into the rent
query, where it weights the average with rent nobody pays. Live diff: 5 no_shows (517/318/407/118
booked 1 Sep, 621 from Jul) in the chart only; Room 602 (on notice, checkout 30 Sep, ₹16k) in the
chart only because its status is already `exited`.

**Fix:** `current_avg_rent` now calls `_live_month_stats(session, today, total_beds)` — one query
path for both surfaces. `_present_at` drops the no_show clause (it is used only by the rent query;
occupancy counts still go through `services/occupancy.py` and still include no_shows). Verified by
calling `get_occupancy()` directly: KPI 14,566 == Sep '26 point 14,566. Jul/Aug live months shift
by a few rupees (no_shows removed); frozen Nov–Apr `VERIFIED_MONTHS` untouched.

## Session AL — 2026-09-01 — September rollover failure: session-pool exhaustion (EMAXCONNSESSION)

Kiran (1 Sep, home screen near-empty): "why has the app not rolled over? data looks corrupted."

**Symptom:** Sept collection card showed Rs.55.5k of Rs.71.5k / "Dues pending 2" for a 245-tenant
property. Not corruption — only 6 `rent_schedule` rows existed for 2026-09 (vs 278 for Aug).
The midnight monthly rollover job fired on time (00:00 IST) but its subprocess died before
creating any rows.

**Root cause (verified):** Supabase session-mode pooler (5432) caps the project at 15 concurrent
connections. `db_manager.init_engine` never set `pool_size`/`max_overflow`, so SQLAlchemy defaults
(5+10 per worker x 2 uvicorn workers) let the app grow to the full 15 under a traffic burst — and
the pool never shrinks, so all 15 slots stayed pinned from the Aug-30 restart onward
(`pg_stat_activity` showed all 15 backends idle, opened 09:55–14:06 UTC Aug 30, held ever since).
The rollover subprocess then couldn't get a single connection (`EMAXCONNSESSION`); so did
`daily_reconciliation` at 02:00. May–Aug rollovers worked only because peak concurrency hadn't
yet reached the cap — tenant/PWA growth crossed it this cycle. Compounding bug: scheduler logging
used printf-style `%s` with loguru (which silently drops args), so the failure logged as literal
`%s` with zero diagnostics.

**Permanent fix (edcc5f8 + 17a3722, deployed + verified):**
- `db_manager`: explicit app pool caps — `pool_size=2, max_overflow=2, pool_recycle=900` per
  worker (max 8 of 15 slots; 7 always free). App can never claim the whole quota again.
- `db_manager.script_database_url()` + `script_engine_kwargs()` + `init_db_for_script()`: one-off
  scripts route through the transaction-mode pooler (6543) with NullPool +
  `statement_cache_size=0` + `prepared_statement_cache_size=0` + uuid
  `prepared_statement_name_func` (all required — cache-size 0 alone still hit
  `DuplicatePreparedStatementError` on shared txn-mode backends, caught on first VPS run).
- Switched to these helpers: `run_monthly_rollover.py`, `sync_from_source_sheet.py`,
  `sync_sheet_from_db.py`, and every scheduler ad-hoc engine (reconciliation, backup, reminders,
  prep, checkout alerts). Scripts and app now draw from separate connection budgets — the
  conflict class is eliminated, not just made less likely.
- Fixed `%s`-style loguru calls in `scheduler.py` + `monthly_rollover.py`; rollover failure log
  now includes rc + stderr/stdout tail. (Same broken pattern remains in gsheets.py,
  onboarding_router.py, api/v2/* — logged as pending cleanup.)

**Recovery:** September backfilled via the fixed script itself (idempotent): 255 RS rows,
Rs.40.3L expected across 245 active tenancies; sheet tab + reconciliation done. Verified clean
end-to-end run ON the VPS with the live app running. `/healthz` = 17a3722.

**Also verified (Kiran's revert worry):** VPS HEAD == origin/master; session-AK fixes
(12872c0 onboarding-edit sync, 3c3c41a sharing-type confirmation, vacant-badge fix) all present
in deployed code. Nothing was reverted — the app only LOOKED broken because Sept RS rows were missing.

## Session AK — 2026-08-30 — G19 room_type never actually fixed + booking-edit sync bug (Tenancy never updates from OnboardingSession edits)

Kiran: "g19 which sharing type is it" → led to two separate confirmed bugs.

**1. G19 room_type revert (data-only fix, no code change needed)**
- DB showed `rooms.room_type='double'` (max_occupancy=2) for G19, contradicting docs which said
  G19 was fixed to single back on 2026-05-14 (`docs/CHANGELOG.md` "Room type corrections").
- Root cause: the 2026-05-14 fix only patched `max_occupancy=1` directly, never the `room_type`
  enum column. The 2026-05-20 refactor (`1.76.12`, `src/database/migrate_all.py`) that made
  `max_occupancy` derive universally from `room_type` (`single=1, double=2, triple=3`) then silently
  reverted G19 back to 2 beds on its next run, since `room_type` itself was still `'double'`. G16
  got the correct fix at the time (`room_type='single'`); G19 didn't.
- Fixed: `UPDATE rooms SET room_type='single', max_occupancy=1 WHERE room_number='G19'`. No script/doc
  constant changes needed — `get_total_revenue_beds()` (`src/services/occupancy.py`) sums
  `Room.max_occupancy` live from DB, so total revenue beds dropped by 1 automatically.

**2. OnboardingSession edits never synced to the linked Tenancy row (real code bug, fixed)**
- Symptom: G19 wasn't showing "Until 12 Sep" in the vacant-beds list even after Lokesh corrected a
  mis-typed check-in date (12 Aug → 12 Sep) on a quick-booked session (Shekhar Paliwal) via the
  Bookings page Edit action.
- Root cause: `quick_book` (`src/api/v2/bookings.py`) creates a real `Tenant` + `Tenancy`
  (`status=no_show`) + `OnboardingSession` together at booking time. But `PATCH
  /api/onboarding/admin/{token}` (`update_session` in `src/api/onboarding_router.py`) only ever
  wrote to the `OnboardingSession` row — never to the already-linked `Tenancy`
  (`obs.tenancy_id`). The occupancy engine, dues, and RentSchedule all read from `Tenancy`, not
  `OnboardingSession`, so the Bookings-page UI showed the corrected date while the room stayed
  blocked with the original (already-past) check-in date forever. Confirmed via zero `AuditLog`
  rows for the tenancy despite the edit having visibly "saved" in the UI.
- Fix (`src/api/onboarding_router.py`, `update_session`): every editable field
  (`checkin_date`, `checkout_date` for day-stays, `room_id`, `agreed_rent`, `maintenance_fee`,
  `security_deposit`, `booking_amount`, tenant `phone`/`name`) now mirrors onto the linked
  `Tenancy`/`Tenant` whenever `obs.tenancy_id` is set, with `AuditLog` entries, and calls
  `recalc_checkin_month_rs()` when `checkin_date`/`agreed_rent`/`security_deposit` changes (per the
  5-call-site rule in `CLAUDE.md`).
- Backfilled the one live affected row (tenancy 1337, Shekhar Paliwal → `checkin_date=2026-09-12`)
  with a manual `AuditLog` entry noting it predates the fix.
- Shipped directly to master (webhook auto-deploy), verified live via `/healthz` (`commit 12872c0`).
- **Not yet verified**: re-test the Bookings-page Edit flow live in the PWA to confirm G19 now shows
  "Until 12 Sep 2026" in the vacant-beds search instead of being silently excluded.

## Session AJ — 2026-08-30 — Vacant-beds "Until X" badge missing for same-day bookings

Kiran: booked Room 411 (Aadi Gupta, check-in today) and the room card still showed plain "1 bed
free" with no reservation tag, while other future-dated bookings (Room 417, "Until 31 Aug") showed
correctly.

- Root cause, confirmed against live DB: Aadi Gupta's booking is an `onboarding_sessions` row
  (`pending_tenant`, link sent, tenant hasn't filled the form — no `Tenancy` row exists yet,
  `tenancy_id IS NULL`). That's correctly excluded from the occupied *count* (nothing held/paid
  yet). The reservation badge, however, is driven by a separate query
  (`src/api/v2/kpi.py`, `type == "vacant"` upcoming-bookings lookup) that filtered
  `checkin_date > today` (strict) for both `no_show` Tenancy rows and pending
  `OnboardingSession` rows — excluding same-day bookings from the badge entirely.
- Fix: both filters changed to `>= today` so a booking due to check in *today* shows the same
  "Until <date>" tag as a future one, instead of rendering as fully vacant.
- Pushed to `development` (b5bc0af), merged to `master` + shipped to prod on Kiran's confirmation.
- **Not changed**: the vacant *count* itself. A booking still only reduces the hard bed count once
  it's a real `no_show` Tenancy (i.e. approved past the onboarding form) — a pending link-sent
  booking stays "free" in the count since the tenant could still no-show entirely. Only the visual
  badge was the bug.

## Session AI — 2026-08-30 — Manual sharing-type override (double↔premium) in Edit Tenant

Kiran: room 615 (Sheetal, double) needed to go premium (whole-room) manually — asked where that
workflow lives today. It didn't exist as a UI action; `sharing_type` was only ever auto-derived
from the room's physical type on room transfer (`resolve_sharing_on_room_change`), and premium is
never a room's physical type in our master data (`Room.room_type` never equals `premium` in the
live DB) — it's always a per-tenancy override.

- **Edit Tenant** (`web/app/tenants/[tenancy_id]/edit/page.tsx`) now shows a **Sharing Type**
  toggle under the Room field whenever the room is a double/triple (or the tenancy is already
  premium): `<room default> (default)` vs `Premium (whole room)`.
- Tapping a different value opens an inline confirm — "have you adjusted this tenant's Agreed
  Rent and Security Deposit?" — before it's applied. `Review Changes` is blocked until confirmed
  or cancelled. Rent/deposit are NOT auto-adjusted; the operator does that in the same edit.
- Backend: `PATCH /api/v2/app/tenants/{id}` accepts an explicit `sharing_type`
  (`src/api/v2/tenants.py`), applied AFTER the existing room-change auto-derivation so it always
  wins. **Gated**: switching to `premium` is rejected (409) unless `get_room_occupants()` confirms
  no other active tenant (long-term or day-stay) is in that room.
- Writes `AuditLog` (`field="sharing_type"`, note "operator confirmed rent/deposit adjusted").
  Registered `sharing_type` in the Activity feed backend (`src/api/v2/kpi.py`) — it was being
  written to `AuditLog` already for room-transfer auto-derivation but was silently filtered out of
  `/activity/feed`'s `NON_PAYMENT_FIELDS` whitelist the whole time; now both auto-derived and
  manual sharing changes show as "Sharing Double → Premium" with their own icon/filter type.
- **Not yet done**: Sheet write-back — `sharing_type` changes don't push to the Google Sheet
  (only `room`/`agreed_rent` do on transfer). Flag if the Sheet needs to reflect it.
- Deployed to prod (`3c3c41a`), verified via `/healthz`. **`[Kiran]` end-to-end test on Sheetal
  (tenancy 615, room 615) was in progress at session end** — confirm the toggle, the 409 gate (if
  another tenant is present), and the Activity feed entry all behave as expected.

## Session AH — 2026-08-21 — Thirumurugan deposit carryover fix (data-only, no code change)

Kiran flagged: Thirumurugan (Room 510, tenancy 1270) deposit kept showing ₹10,000 outstanding in the Collect Payment modal despite being "waived last month."

- **Root cause:** the prior "waiver" was applied to the wrong field. Someone edited `rent_schedule.adjustment` (a per-month RENT field, notes "Already paid" / "Deposit hold") to suppress that month's rent dues — but `deposit_due` in the Collect Payment modal is computed purely as `security_deposit − Σ(payments for_type=deposit)`, which the rent-schedule adjustment never touches. So it looked forgiven each month but reset every period.
- **Real story (confirmed via DB):** this tenant had a prior tenancy (773, same room, earlier stint) with a ₹10,000 deposit paid 03-Jan-2026. He checked out 17-May-2026 and that deposit was **never refunded** (`checkout_records.deposit_refunded_amount = 0`). On his new tenancy (1270, check-in 30-May), only ₹3,000 fresh deposit was collected against a ₹13,000 requirement — the old ₹10,000 was sitting unaccounted-for instead of carrying forward.
- **Fix (direct DB write, not app code):** inserted a `payments` row on tenancy 1270 — `for_type=deposit`, amount 10,000, `payment_mode=bank_transfer` (deliberately non-cash so it doesn't inflate the live "cash collected" figure for August — that sum only totals `payment_mode=cash` rows), with a note explaining the carryover. Added a matching `audit_log` entry. Annotated the old `refunds` row (id 88, tenancy 773) so nobody later assumes a second ₹10,000 refund is still owed separately. **`security_deposit` was deliberately left at ₹13,000** (Kiran: "don't reduce his deposit amount, we need to repay him") — the full amount stays owed back to him at eventual exit.
- **New rule for future cases like this** — see [[rules_financial]] / `memory/rules_financial.md`: when a tenant re-checks-in to a new tenancy after a prior tenancy's deposit was never refunded, carry the old deposit forward as a `for_type=deposit` payment on the new tenancy (non-cash `payment_mode`), don't touch `security_deposit`, and never use `rent_schedule.adjustment` to fake-waive a deposit — that field only affects rent for that one month and doesn't persist.
- Also answered (informational, no action): where the WhatsApp bot is hosted (Hostinger VPS, systemd `pg-accountant` + nginx, webhook-driven not polling) and a 10-step outline for a "rebuild this from scratch" YouTube walkthrough.
- **Not pushed** — no code files changed this session; the fix was a live-DB correction only. Kiran asked not to push.

## Session AG (cont. 3) — 2026-08-14 — Phases 2+3: P&L drill-down + reclassification

Kiran: "if I doubt an expense, how do I deep-dive and reclassify?" — that is spec 01 Phases 2+3, built together.

- **Drill-down** — `GET /finance/pnl/line-items?month=&key=`: every drillable P&L line lists the exact rows behind it, using the SAME WHERE clauses as the engine (bank txns for income/opex/refunds/non-op; cash payments + offline-cash pseudo-row; tenancy rows for deposits held / maintenance kept). UI: tap a line → bottom Sheet with rows + sum; if |sum| ≠ |line| an explicit "engine drift" warning shows (never hidden).
- **Reclassify** — tap a bank row in the sheet → pick a category (fixed lists served by the backend: EXPENSE_CATS for debits, income cats for credits) → "Move to X". `PATCH /finance/transactions/{id}` writes AuditLog (old→new + txn context) and sets new column `bank_transactions.manual_category=true` (migration `run_btxn_manual_category_2026_08_14`, applied to the live DB). Locked rows are skipped by `_detect_tenant_refunds` — the only pass that rewrites existing categories — and re-uploads are hash-dups that never touch existing rows, so a human correction can never be undone by automation. Reclassified rows show a "reclassified" chip.
- After a move, both the sheet and the P&L tree refetch — the amount visibly moves between categories, P&L totals update live.
- Ops note: the Supabase session-mode pooler (15 slots) is mostly held by the VPS app — local scripts must retry or use the 6543 transaction pooler for one-off DDL.

## Session AG (cont. 2) — 2026-08-14 — Phase 1 deployed + save-recalc wiring + July figures incident

- **Deployed to prod** (`18cac6d` then `bd30a89`): Phase 1 P&L card + the 11 audit fixes went live (Kiran wanted to see Phase 1; development-only work is invisible until merged to master).
- **Kiran's first test found a real gap:** saving manual cash figures didn't refresh the P&L (and he saw the OLD three-statement card from the stale service-worker bundle). Fix: no recalculate button — the P&L is computed live server-side, so `PnlAdjustmentsCard.onSaved` / CSV upload now signal `PnlMonthCard` to jump to that month and refetch. Recalculation is automatic and month-aware.
- **Incident: test save clobbered July's closed figures** (rent_paid_cash 15,32,000 → 21,32,000, cash_holding 65,000 → 0, cash_expense 2,000 → 0). The adjustments audit trail deployed ~20s earlier captured the old values; offline_cash + notes survived thanks to the M1 partial-update fix. **Restored** (audit rows written, `updated_by=claude-restore-2026-08-14`); July back to verified ₹14,00,408 / 31.7%.
- **New guardrail from the incident:** changing an already-saved non-zero figure now shows the old → new diff and requires a second "Confirm overwrite" tap.

## Session AG (cont.) — 2026-08-14 — Finance P&L rework Phase 1: SOP hierarchy on screen

Spec `docs/specs/01-finance-pnl-page.md` Phase 1 implemented (Kiran: "keep P&L short, SAC-style hierarchy, dynamically drillable").

- **`GET /api/v2/app/finance/pnl/month?month=YYYY-MM`** — one month's SOP P&L as a node tree. Dynamic months reshape `_compute_dynamic_pnl_months()` records; frozen months come from `pnl_verified_data`; both flow through ONE shared assembler (`_pnl_tree`) so the math cannot diverge: True Revenue = Gross − deposits held − deposits refunded; Net Operating = True Revenue − Total Opex. No new math anywhere — reshape only.
- **`pnl-month-card.tsx`** — collapsed 5-line P&L (Gross inflows / Deposit pass-throughs / True revenue / OPEX / Net operating), each node expands SAC-style into children (bank income per account, cash incl. offline, OPEX by category, manual figures tagged "manual", non-op detail as display-only). MonthNav picker, frozen badge, empty state for months with no bank rows. Node keys are the Phase-2 drill-down contract (`drillable` flags already set).
- **Three-statement card removed from the page** — its P&L deviated from the SOP in 6 documented ways (see spec). BS/CF return in Phases 5–6 rebuilt on SOP outputs; `three_statement.py` + component kept on disk as reference.
- **Parity pinned by tests** — `tests/test_pnl_tree.py` (5 tests, added to pre-push): totals follow SOP formulas; tree sums == `pnl_builder._dynamic_line_values` Excel translation; children sum to parents; manual rows marked; frozen months not drillable.
- **Live verification:** Jul'26 from the endpoint = Net Operating ₹14,00,408 (31.7%) — identical to Kiran's verified July close. Jun'26 ₹8,95,323. Aug shows empty state until its CSV is uploaded.

## Session AG — 2026-08-14 — Audit fixes: 11 CRITICAL/HIGH findings from the 2026-08-12 audit

Kiran approved the audit triage ("go ahead"). Fixed one finding at a time, all on `development`. Verified: py_compile + module imports OK, `tsc --noEmit` clean, 20/20 unit tests (dues + cash logic). NOT yet merged to master — payment paths need a smoke test first.

1. **Quick Collect double-charge** (`kpi-grid.tsx`) — the 3 sequential createPayment legs (cash/UPI/deposit) now track per-leg posted state in a ref; a retry after partial failure posts only the remaining legs, posted inputs disable, and the error names what already went through.
2. **Payment Sheet write-back silently dropped** (`account_handler.py`) — `update_payment` result is now checked; failure (dict, timeout, or exception) queues to the retry queue and the bot reply says "Sheet update failed — queued for auto-retry" instead of claiming success.
3. **Retry queue revived** — (a) checkout + add_tenant call sites now enqueue on `{"success": False}` returns too (previously only on raised exceptions, which gsheets never raises); (b) new APScheduler job `sheet_write_retry` drains the queue every 15 min (was only drained at process start).
4. **Checkout audit trail** — `_do_confirm_checkout` (PWA), bot `_do_checkout`, and form checkout now write AuditLog: `status+checkout_date` (feeds the activity feed, which already queried that field) + `deposit_settlement` (refund vs deposit, dues, deductions, mode, reason).
5. **Finance audit trail** (`finance.py`) — add/edit/void cash expense, cash count, and P&L adjustment saves all write AuditLog rows (old→new per changed field).
6. **UPI reconciliation traceability** (`upi_reconciliation.py`) — every auto-created Payment logs an AuditLog entry with RRN, payer name, and match method (phone/name/fuzzy); manual assignment logs too. (Fuzzy 0.6 threshold + RentSchedule non-update left as-is — behavior changes need Kiran's call.)
7. **Waive-remaining silent failure** (`payment/new/page.tsx`) — a failed waive PATCH now shows a warning on the success screen with the amount and where to re-apply it (was swallowed; tenant kept phantom dues).
8. **"Log anyway" now actually works** (`payments.py` + `account_handler.py`) — new `allow_duplicate` flag salts the unique_hash so a confirmed genuine second identical payment isn't blocked by `uq_payment_unique_hash` (was understating collections).
9. **Gmail poller no longer loses bank emails** (`gmail_poller.py`) — emails are marked Seen only AFTER their reconcile succeeds (was at fetch time, so a failed reconcile permanently skipped the file); UNSEEN search widened to a 3-day lookback so failures retry; IMAP gets a 30s timeout.
10. **M1: P&L adjustments save wiped offline_cash/notes** (`finance.py`) — POST /finance/pnl/adjustments is now a partial update: only fields present in the body are touched (the PWA card omits offline_cash/notes, which were being zeroed/nulled on every save).
11. **A1: extract-id endpoint hardened** (`onboarding_router.py`) — 10/min per-IP rate limit + 403 on closed sessions (approved/cancelled/expired) so anonymous token-holders can't burn Claude vision credits.

Also: BRAIN.md scheduler line updated (4 jobs incl. sheet-write retry). Stale docs index noted: CLAUDE.md points at `docs/BRAIN.md` etc. but most docs live in `docs/architecture/` + subfolders.

## Session AF — 2026-08-13 — DB password rotation, VPS pooler fix, SSH workflow corrected

### DB password rotated + fully propagated
Old leaked `Anchorstrong123!` now DEAD (verified), new value connects. Propagated to local `.env` AND VPS `/opt/pg-accountant/.env`.

### Incident: VPS DB outage exposed + fixed (Supabase pooler)
Restarting the VPS to apply the new password surfaced a latent outage: **Supabase's direct host `db.<ref>.supabase.co` is IPv6-only and the VPS can't reach it** (`ConnectionRefused` → "Application startup failed"). It only worked before on the old process's pre-established connections — the next deploy would have taken the bot down regardless. Fixed by switching both `DATABASE_URL` and `DATABASE_URL_PSYCOPG` to the **Supabase pooler**: `aws-1-ap-south-1.pooler.supabase.com:5432`, session mode, user `postgres.oxiqomoilqwfxjauxhzp` (dotted). Local + VPS both migrated. Verified: service active, DB reads (167 rooms), live healthy, webhook OK.

### Root-cause of recurring "update VPS .env" pain — FIXED
A stale note claimed "Claude cannot SSH (port 22 blocked)". **False — SSH works** (verified). Corrected CLAUDE.md + `reference_vps_ssh.md` + `feedback_never_ask_to_deploy.md`. Added `scripts/vps_env_set.sh KEY "value"` — updates VPS `.env` + restarts over SSH (value passed at runtime, never committed). Secret propagation handled directly now, never handed to Kiran.

### Secrets hygiene
`all passwords.txt` master doc kept current; verified gitignored + never pushed. `rules_no_secrets_in_git.md` saved. service_role key confirmed NOT in git history. Still open (Kiran): rotate 2 Gmail passwords (were in git history) + set real `API_SECRET_KEY` (strong values generated).

## 2026-08-13 — Bike parking notice broadcast + TIER_250 root cause + delivery-status capture

- Sent bike parking notice to all 260 active tenants (unique phones) + 4 operator CCs via `custom_broadcast_notice` template — 264/264 accepted by Meta.
- **Root cause found for Lakshmi/Prabhakaran missing broadcasts (2nd time):** sending number is on `messaging_limit_tier: TIER_250` — 250 unique business-initiated conversations per rolling 24h. Operators were sent LAST (positions 261–264) so they fall past the cap; Meta still returns HTTP 200 for dropped sends. Alphabetically-last ~10 tenants likely also dropped. Permanent fix = Meta Business Verification (Kiran) → TIER_1K.
- **Delivery-status capture built:** new `whatsapp_status_log` table (migration `run_whatsapp_status_log_2026_08_13`, run on live DB); webhook now persists Meta `statuses` events (sent/delivered/read/failed + error code) — previously silently ignored. `send_template()` now returns the wamid (truthy str, backward-compatible).
- **Broadcast delivery report:** `src/whatsapp/broadcast_report.py` — after a broadcast, waits for status webhooks then WhatsApps operators a one-paragraph summary (delivered/read counts + FAILED names with Meta reason) via `custom_broadcast_notice`. Unit tests `tests/test_broadcast_report.py` (added to pre-push gate).
- **All broadcast scripts flipped to operators-FIRST** (staff must never sit past the 250 cap); `_send_bike_parking_notice.py` is now the canonical recipe (wamid collection + report).
- NOTE: status capture goes live on next merge to master (webhook runs on VPS).

## Session AE (cont.) — 2026-08-12 — PWA UI system: canonical primitives, mass de-duplication

Follow-up to the reuse audit (15 INR formatters, ~10 date formatters, 11 hand-rolled modals, 872 hex literals). Built the design-system layer, migrated every reachable page/component, documented it.

### New canonical layer
- `web/lib/date.ts` — fmtDate/fmtDateShort/fmtDateTime/todayISO/nowTime/monthLabel/addMonths/periodMonth (string-split parsing, no TZ off-by-one)
- `web/lib/format.ts` — added `rupeeExact`, `rupeeShort` (K/L/Cr, negative-safe); `indianNumber` now decimal-safe (old version garbled fractions)
- `web/components/ui/` — new `modal.tsx` (Modal + Sheet; encodes inline zIndex-9999 + safe-area rules), `spinner`, `skeleton`, `empty-state`, `page-header`, `month-nav`
- Tailwind tokens: `border` (#F0EDE9) + `border-strong` (#E0DDD8; retires the #E2DEDD fork)
- **`docs/UI_SYSTEM.md`** — the reference doc; CLAUDE.md now mandates reading it before any UI work
- Deleted dead components: `pill.tsx`, `date-select.tsx`, `datetime-select.tsx` (0 importers)

### Migration (3 parallel agents, disjoint scopes; 35 files)
~30 local formatter definitions deleted; ~70 inline `₹…toLocaleString` swapped; 7 hand-rolled modals → `<Modal>`/`<Sheet>` (notices ×2, operations delete, payments-history edit, kpi-grid ×2, logout sheet); ~10 PageHeaders, ~8 EmptyStates, ~35 Skeleton bars, 1 MonthNav; ~350 mapped hex classes tokenized. Orphaned finance components untouched (pending Cash-tab decision). Documented skips: full-bleed sticky headers, voice-sheet roots, server-component month nav (collection/breakdown).
Accepted visual unifications: "05 Jan 2026"→"5 Jan 2026"; standard modal chrome; K-tier gains one decimal in investment section.
Found pre-existing bug: `bg-tile-yellow` (tenants Overdue tile) has no token — class resolves to nothing; logged in UI_SYSTEM.md debt, needs design decision.

### Verification
`tsc --noEmit` clean; `npm run build` passes; zero mapped hexes / local INR formatters left outside orphans; formatter algorithm spot-verified on edge cases.

### Enforcement (added after Kiran asked "will it stay this way?")
`scripts/check_ui_consistency.py` — mechanical gate in the pre-push hook (blocks tokened hexes, local INR formatters, inline en-IN currency, hand-rolled modal backdrops, re-derived API URLs). First run caught 22 stragglers (ui/ primitives' own hexes, 3 month-name lookups, 1 false-positive click-catcher) — all fixed; `monthShortName`/`monthLongName` added to lib/date.ts. NOTE: the hook itself (.git/hooks/pre-push) is machine-local — on a fresh clone, re-add the ui-check call after the unit-test block.

## Session AE — 2026-08-12 — Best-practices adoption: secrets, single-source constants, security fixes, audit, dev branch

Compared the spec-driven-AI-development video (transcript `data/uploads/14RP8liACqo.txt`) against the project; adopted the gaps.

### Track 0 — committed credential removed
- **DB password (`Anchorstrong123!`) was hardcoded in 13 scripts/tests** — all now read `DATABASE_URL` from env (`tests/diag_dues*.py`, `scripts/export_reclassify.py`, `sync_contacts_to_db.py`, `_apply_other_expenses_classifications.py`, `_check_*.py`, `_import_*_sbi.py`, `_migrate_room000_to_onboarding.py`, `_reset_pratham_to_pending.py`, `_void_pratham_payments.py`).
- **ACTION KIRAN: rotate the Supabase DB password** (dashboard → Settings → Database), then update `DATABASE_URL` in local `.env` AND VPS `/opt/pg-accountant/.env`, restart `pg-accountant`. Old password is burned into git history.
- Secret sweep of tracked files found nothing else real.

### Track 1 — single source of truth for constants
- **TOTAL_BEDS**: canonical = `src/services/occupancy.py` (`get_total_revenue_beds` + new `get_total_revenue_beds_sync`). Rewired: `analytics.py`, `unit_economics.py`, `gsheets.py` (`TOTAL_BEDS`→DB value w/ `TOTAL_BEDS_FALLBACK`), `account_handler._dashboard_summary`, `owner_handler._query_occupancy`, `clean_and_load.py` (DB w/ fallback). Fixed divergent formula in `room_occupancy.beds_free_on_date` (now canonical denominator + room-000 tenancies excluded from occupied counts — pre-registrations no longer eat real-bed inventory). Apps Script JS consts annotated as manual copies. Stale one-off scripts (291/293/297) left untouched — historical.
- **FROZEN_MONTHS**: `sync_sheet_from_db.py` now imports from `gsheets.py` (was a verbatim copy). Note: analytics `VERIFIED_MONTHS` (occupancy stats), `pnl_verified_data.MONTHS` (P&L columns), and the rolling SQL `payments_freeze` trigger are three *distinct* concepts, not duplicates — left as-is.
- **Admin phone**: new `role_service.get_primary_admin_phone()` (allowlist-derived, env-overridable). `gmail_poller` (was `ADMIN_WHATSAPP` w/ dummy default) and `tenant_handler` onboarding approval (was `ADMIN_PHONE` w/ dummy default) now use it.
- **Sheet ID**: `clean_and_load.py` now env-backed (`GSHEETS_SHEET_ID`). **PWA API base**: `web/lib/api.ts` exports `BASE_URL`; 3 components that re-derived it now import it. `onboarding_router` PWA redirect now uses `PWA_URL` env.

### Security fixes (from end-to-end audit)
- `DELETE /api/v2/app/tenants/{id}` — had NO role check (any authenticated JWT could hard-delete a tenancy + payments with `force=true`). Now **admin-only** (behavior change: staff can no longer hard-delete).
- `POST /tenants/{id}/transfer-room` — had NO role check (could rewrite `agreed_rent`). Now admin/staff.

### End-to-end audit (3 parallel agents, video's bug-class checklist)
Full findings in `memory/project_audit_findings_2026_08_12.md` — 30+ verified findings awaiting Kiran's triage. Top items: Quick Collect modal can double-charge on partial failure; payment Sheet write-back failure is silent (says "Payment logged" regardless); `_queue_failed_write` retry queue effectively dead (only fires on exceptions gsheets never raises); Gmail poller marks bank emails Seen before reconciling (failure loses the file); checkout writes no AuditLog; UPI reconciliation creates payments bypassing audit+RentSchedule; `_send_whatsapp` returns None so callers always see failure.

### Workflow conventions adopted (CLAUDE.md)
- `docs/specs/NN-name.md` feature specs (template: `docs/specs/TEMPLATE.md`).
- `docs/specs/current-issues.md` debugging file (gitignored) + analyze-then-approve rule.
- **`development` branch created** — work there; merge to `master` = deploy. Staging deferred (needs second env).

### Tests
`test_dues_logic.py` + `test_cash_logic.py`: 20 passed. `tsc --noEmit`: clean. All edited files compile.

## Session AD — 2026-08-12 — August P&L forecast (Google Sheet col N) + July P&L verification

### August forecast (external — Kiran's "August FC" Google Sheet, tab "P&L — Full", column N)
Built a data-driven August forecast in column N (left Kiran's manual col M untouched), written via the `cozeevo-sheets-bot` service account (sheet `1qDrj_lQctxmNgOflXDi_d3xI_roaTxKbMUjOoa8d8t4`, gid 1548899605).
- **Method:** per-line **trailing-4-month median** (Apr–Jul), outliers/ramp-zeros excluded, totals computed from components. Plain all-history median was rejected — it produced a false ₹1.7L *loss* because medianing across the ramp-up (cash ₹3L→₹29L) lands mid-growth, not at current scale.
- **Actuals override the median** wherever Kiran supplied them: Cash ₹28,62,450 (collection sheet), Property Rent ₹16L cash + ₹6.14L UPI, Electricity ₹2,66,570, Water ₹1,66,000.
- **UPI income from the actual CSVs:** parsed `data/uploads/csv/Thor…` + `Hulk Thor…` (UPI-gateway COLLECTION reports, 20 Jul–12 Aug). Aug 1–12 = ₹15,05,180 (THOR ₹7.97L + HULK ₹7.08L); confirms Kiran's ₹16.5L full-month projection. **Double-count avoided** by counting each txn on its own date — Jul 20–31 receipts (₹1.36L) stay in July. Split ₹16.5L into r3/r8 by the 53:47 THOR:HULK ratio.
- **Row 12 (deposits held)** fixed from a bogus median (−₹5.23L, past busy months) to August check-ins only: −₹1,85,000 (10 active + 7 pending, net dep−maint).
- **Result:** col N net operating profit ≈ **₹7.7L (18.8%)**, converging with Kiran's col M (₹8.13L / 20.1%).
- **Still open in the forecast:** r14 refunds to the 28 leaving (on median −₹2.3L; needs actual Aug vs Sep split), small opex lines on median.

### July P&L verified REAL (₹14,00,408)
Kiran suspected July was an outlier (~2× August). Independent reconstruction from source **reconciles to the rupee** (₹17.08L rebuild − ₹3.08L deposits-held = ₹14.00L). July income is clean rent (cash 99% rent, no one-offs; ₹79,900 Chandra loan correctly excluded as Non-Operating). **Key finding: July is NOT the outlier — Mar–May were overstated by ~₹15L each** because the ₹15.32L/mo cash rent to landlords was only added to the model from June. Jun/Jul are the first honest months. Aug < Jul is real: −₹4L income (churn) + ~₹2.6L higher summer utilities & rent hike.

### Data-integrity issues surfaced (need Kiran's decision)
- **`security_deposit` convention:** DB stores it *excluding* maintenance for onboarding-created tenants, but `finance.py`/row-12 subtracts maintenance again → row 12 understated. Contradicts the 2026-07-11 "deposit includes maintenance" rule. Unresolved.
- **5 August "check-ins" are no_show/cancelled/pending in DB** (Prashant, Soumya, D Yaswanth, Ganesh Patil, Kishore Babu) — sheet counts them, DB doesn't.
- **Sheet cash vs live DB drift** for Apr (−₹1.36L) / May (−₹84K); Jun/Jul tie exactly.
- Collection sheet `1Vr_…` (August cash/UPI) NOT shared with `cozeevo-sheets-bot@…` — could not read it directly.

### Repo change
`CLAUDE.md` — documented that **VPS deploy is automatic on push** (webhook), so no SSH / no permission-to-deploy needed.

## Session AC (cont.) — 2026-08-12 — C-1 fixed: Supabase buckets made private + signed URLs (last critical closed)

### Summary
Closed C-1, the last and most serious `docs/SECURITY_AUDIT.md` critical — a **live PII breach**. `kyc-documents` and `agreements` buckets were `public=true`; anyone could download tenant govt IDs, selfies, signatures, and signed rental agreements by guessing object paths (live-verified: pulled a real agreement PDF with zero auth). Now private, served via short-lived signed URLs.

### What changed
- `src/services/storage.py` — `create_signed_url()` + `sign_stored_url()` (parses bucket/path out of the stored public URL and re-signs; passthrough-safe for base64/local/empty; fails open so a Storage hiccup degrades one image, never 500s the response). `ensure_bucket()` now creates buckets `public=False`.
- Re-sign at every read path handing a URL to a viewer: `payments.py` list/detail/upload `receipt_url`; onboarding booking-detail KYC (`saved_files` selfie/id_proof/signature) + `agreement_pdf_path`; both WhatsApp agreement sends (approve flow + regenerate — the regenerate one also **fixes a pre-existing bug** where it concatenated `/static/` onto a full Supabase URL); WhatsApp "show receipt" link (24h expiry). Meta fetches document links at send time, so short-lived signed URLs suffice.
- Staff-signature read already streams server-side via service key → private-safe, unchanged.
- **No DB migration** — stored public URLs are re-signed on read.
- `scripts/_flip_buckets_private.py` — flips the live buckets + `--verify` proves public 403 / signed 200.
- `tests/test_storage_signed_url.py` — 5 tests (parse public/signed, passthrough non-Supabase, fail-open).

### Deploy + verification (done, live)
- Sequenced correctly: deployed signing code FIRST (signed URLs work on public buckets, zero breakage), confirmed live commit `5e751a9` via `/healthz`, live-tested the deployed `sign_stored_url()` on a real agreement URL (→ signed → GET 200), THEN flipped both buckets private.
- **Live-verified closed:** public URL of a real agreement PDF + staff signature now return **HTTP 400** to unauthenticated requests; signed URLs return 200. `receipts` bucket doesn't exist yet (no PWA receipt uploaded) → born private on first upload.

### Note
All three audit criticals (C-1, C-2, C-3) are now resolved. Remaining audit items are lower severity (see SECURITY_AUDIT.md).

## Session AC — 2026-08-12 — C-2 privilege-escalation fixed in code (role from app_metadata)

### Summary
Fixed the C-2 critical from `docs/SECURITY_AUDIT.md` — the privilege-escalation bug where `role` was read from self-editable `user_metadata` (any logged-in user could `supabase.auth.updateUser({data:{role:'admin'}})` and become admin). This is the finding that broke prod on 2026-08-08 when fixed carelessly; done properly this time.

### What changed (all 5 read sites, together — the 08-08 attempt fixed only 2)
- `src/api/v2/auth.py` — `role`/`org_id` from `app_metadata` only, **no `user_metadata` fallback** (a fallback reopens the hole). `name` stays from `user_metadata` (display-only).
- `web/middleware.ts`, `web/lib/auth-server.ts`, `web/components/auth/auth-provider.tsx` (×2), `web/app/finance/page.tsx` — all read `app_metadata.role`.
- `tests/test_auth_role_source.py` — 7 guard tests ported from the `security-redo` sandbox; all pass. Covers the exploit (self-set user_metadata ignored) and fail-closed (old token → tenant).

### Verification
- 79 unit tests pass (pre-push set + auth + dues + cash). Frontend `tsc --noEmit` clean.
- Precondition re-verified: all 6 auth accounts already have `app_metadata.role` (migrated 08-08). 4 days of hourly token refresh → live JWTs already carry it, so the 403-storm risk is largely pre-mitigated.

### Deploy state — CODE ON MASTER, NOT YET ON VPS
Deploy is manual (`deploy/update.sh` via SSH) — pushing to GitHub does not touch the live server. **Remaining Kiran-controlled steps:** (1) run `update.sh` on VPS + rebuild/redeploy the PWA (ship all 5 files together); (2) have the 6 admin/staff log out & back in. Fail-closed, so a stale token means one re-login, never a leak. Resolves C-2 in SECURITY_AUDIT.md (pending deploy).

## Session AB — 2026-08-11 — Supabase RLS exposure fixed + anon grants revoked (defense-in-depth)

### Summary
Kiran got a Supabase security email ("Table publicly accessible — `rls_disabled_in_public`", dated 09 Aug, project `oxiqomoilqwfxjauxhzp`). Investigated live, confirmed a real (small) exposure, fixed it, and closed the underlying class of bug so it can't recur.

### Root cause (not a compromise — a config gap on a new table)
- Two tables had RLS **off**: `pnl_monthly_adjustments` and `pg_config`.
- **`pnl_monthly_adjustments` was live anon-readable** — anon key `GET /rest/v1/pnl_monthly_adjustments` returned real rows (monthly cash-in-hand, cash rent to landlords, investor-return notes). This is the actual leak.
- `pg_config` was RLS-off too but returned `[]` (empty) — no data lost.
- Why now: `pnl_monthly_adjustments` is from the recent dynamic-P&L / manual-cash feature (table added 2026-07-02, `offline_cash` col 2026-08-08); it landed RLS-off. `pg_config` was **wrongly hard-coded into the RLS skip-list** in `migrate_all.py` (grouped with Postgres internals because of the `pg_` prefix — it's actually our app table).

### Fix (live DB, applied immediately — no deploy needed)
1. `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` on both tables (deny-all, matches all 54 tables).
2. **Defense-in-depth — the real fix:** `REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated` + `ALTER DEFAULT PRIVILEGES FOR ROLE postgres ... REVOKE ALL ON TABLES FROM anon, authenticated`. Anon/authenticated held full SELECT/INSERT/UPDATE/DELETE/TRUNCATE on all 54 tables **and default privileges granted the same on every future table** — so RLS was the only thing standing between the anon key and all data. Now stripped: even a table with RLS accidentally left off is unreachable via the anon key.
3. Verified: anon read of `pnl_monthly_adjustments`, `pg_config`, `tenants`, `payments`, `bank_transactions` all now `401 permission denied`. Backend (`postgres`, BYPASSRLS) + `service_role` still read all 54 tables. PWA never queries public tables directly (grep-confirmed no `.from(`/`.rpc(` — auth/session only), so app is unaffected.

### Durable in code
- `src/database/migrate_all.py`: removed `pg_config` from the RLS skip-list (with a comment); appended the REVOKE + ALTER DEFAULT PRIVILEGES to `run_enable_rls_all_tables` so every migration re-applies both layers idempotently.

### Open / caveats
- **Who accessed it:** cannot be determined from here — Supabase API request logs (dashboard → Logs) retain ~1 day; Postgres doesn't log `SELECT`s. No DB-side audit trail. Leaked data was internal cash/P&L figures, not credentials/PII.
- **`supabase_admin`-owned future tables** still carry default anon grants — `postgres` can't ALTER those defaults; needs a superuser action in the Supabase SQL editor. Not a practical exposure (we never create app tables as `supabase_admin`).
- This resolves **C-3** in `docs/SECURITY_AUDIT.md` (was MEDIUM: fragile RLS-only protection) — now defense-in-depth.

## Session AA — 2026-08-10 — Noise/late-night notice broadcast (first real use of custom_broadcast_notice)

### Summary
Kiran drafted a noise & late-night-activities notice (gaming until 10:30 PM only, silence after). Sent it staff-first for review, then broadcast to all active tenants with operator CC. First production use of the `custom_broadcast_notice` template (approved since Session Y).

- ✅ **Review copy → 4 operators** (Kiran, Lokesh, Lakshmi Mam, Prabhakaran), Kiran approved, then **broadcast: 261/261 unique tenant phones + 4/4 operator CC, zero API failures** (`scripts/_send_noise_notice.py`, dry-run default, `--tenants --send` for live).
- 🐛 **Learned: Meta error #132018** — template *parameters* cannot contain newlines/tabs/4+ consecutive spaces. First live attempt failed 0/4; notice had to be flattened to one paragraph for `{{2}}`. Multi-paragraph notices need a dedicated 0-param template (text in BODY, 24-48h approval). Also: template hardcodes `Hi {{1}},` + sign-off, so greeting/sign-off are stripped from drafts; Kiran ruled general broadcasts use `{{1}}`="Tenants" (no per-tenant names).
- ✅ **Standing rule reaffirmed by Kiran: "always include staff in broadcast"** — CC baked into the script, rule updated in `rules_whatsapp_cc.md` along with the #132018 constraint and the staff-review-first flow.
- ⚠️ **Open: staff delivery gaps.** Kiran received both copies; **Devaprabha got nothing (she's not on the 4-person CC list at all)** and **Lakshmi Mam (7358341775) may have received neither** despite Meta accepting both sends — number possibly stale/not-on-WhatsApp. We don't capture delivery webhooks, so accepted ≠ delivered. Pending Kiran: Devaprabha's number (add to CC list?) + confirm Lakshmi's current WhatsApp number + whether Lokesh/Prabhakaran received.
- Recipient list dedupes by unique phone (262 active tenancies → 261 numbers; shared numbers get one message).

### State at session end
No runtime code changed; no deploy needed. New file: `scripts/_send_noise_notice.py`.

## Session Z — 2026-08-08 — Full offensive security audit + a broken/reverted deploy (postmortem)

### Summary
Kiran asked for an unsparing hacker-mindset security audit ("no leakage"). Ran multiple parallel offensive passes over the whole codebase + live infra. An early attempt to auto-fix the first finding **broke the live PWA and was reverted**; the rest of the session was audit-only, with every finding verified directly and a fix-impact analysis written for each. **No security fix is deployed.** Full report: `docs/SECURITY_AUDIT.md`.

### The incident (important — postmortem)
- First pass found a real privilege-escalation bug (role read from self-editable `user_metadata`). I fixed it across `auth.py` + `middleware.ts`, ran the account migration (`_migrate_role_to_app_metadata.py --write` — moved role into `app_metadata` for all 6 accounts, `user_metadata.role` left intact), committed, and pushed.
- **The push auto-deployed** (this repo deploys on push — I had wrongly told Kiran it wouldn't) and **broke the live app**: every in-flight session's JWT had role only in `user_metadata`, which the new code no longer read → 403 across the PWA (Collect payment, Bookings "Load failed: 403", etc.). I had also only fixed 2 of the 5 places that read the role.
- **Reverted** (`1514b5d`) → production restored. No data lost (`user_metadata.role` was never removed, so the reverted code reads it fine). Also gitignored `data/Private/` (a 293MB zip the Stop-hook auto-commit kept trying to push, which was blocking git).
- Lesson recorded in `docs/SECURITY_AUDIT.md`: no security fix ships without its end-to-end impact worked through, a sandbox test, and a deploy sequence that accounts for in-flight sessions.

### Audit findings (17 total; documented, NOT fixed)
- **C-1 CRITICAL (live):** Supabase `kyc-documents` + `agreements` buckets are `public=true` (verified live) — tenant IDs/selfies/signatures/agreements downloadable via guessable paths. Fix needs signed-URL refactor first or images break app-wide.
- **C-2 CRITICAL:** privilege escalation via self-editable `user_metadata.role` (the reverted bug). Reference fix + guard tests preserved in worktree `../pg-security-sandbox` branch `security-redo` (local only, not pushed).
- **C-3 → MEDIUM (live-tested, downgraded):** RLS deny-all IS blocking anon reads+writes (anon `SELECT`→`200 []`, `INSERT`→`42501` policy violation). Not a live breach — but anon table grants are wide open, so one accidental policy = breach. Recommend `REVOKE`.
- **H-1..H-4:** no payment amount cap (₹12cr fat-finger accepted — matches the collect-payment modal), refund cap validated against client-supplied deposit (cash drain), `DELETE ?force=true` erases frozen financial history, 11 endpoints missing role checks.
- **M-1..M-6, L-1..L-4:** fail-open `/auth/send-otp`, freeze-bypass on payment edit, dues-wipe via future check-in date, unauthenticated LLM `extract-id`, unbounded negative adjustment, decorative `org_id`, PII PDFs on public `/static`, etc.
- **Confirmed SAFE:** webhook HMAC, CORS, JWT alg, password reset, XSS, SQL/command/path injection, onboarding token enumeration, tenant self-approval, no committed secrets.

### Files
- Committed to master: `docs/SECURITY_AUDIT.md` (`a75debb`), `.gitignore` (data/Private), the revert (`1514b5d`).
- Local-only (not pushed): worktree `../pg-security-sandbox` (branch `security-redo`) — C-2 reference fix + `tests/test_auth_role_source.py`.
- New memory: `rules_security_role_source.md` (app_metadata rule). `scripts/_migrate_role_to_app_metadata.py` exists but its changes were reverted from master — re-add when C-2 is properly redone.

### State at session end
Production healthy (API + PWA both 200, verified). No security fix live. Everything is documented in `docs/SECURITY_AUDIT.md` with a prioritized remediation plan; C-1 (live PII breach) is the top item and the recommended next task.

## Session Y — 2026-08-08 — Broadcast messaging (manual, template-based) + WhatsApp CC reliability fix + July P&L correction

### Summary
Kiran wanted to check status of 2 pending WhatsApp templates, then send `laundry_rules_notice` to all active tenants as a real manual broadcast, plus scope out a future "type a message, send to tenants" feature for the PWA. Surfaced and fixed a real reliability bug in the CC mechanism along the way, then separately fixed a P&L misclassification Kiran flagged.

- ✅ **`laundry_rules_notice` + `fridge_cleaning_notice`** — confirmed APPROVED on Meta (checked live via Graph API, memory was stale). Sent `laundry_rules_notice` to all 262 active tenants (`scripts/_send_laundry_notice.py`, one-off, dry-run by default, `--send` for live). First live attempt failed 404/0 sent — Meta silently normalized the template's language to `en_US` on approval (not `en` like other templates); fixed by passing `language_code="en_US"` explicitly. Retried and confirmed 262/262 sent.
- ✅ **Submitted new template `custom_broadcast_notice`** (id `1403976844940891`, PENDING) — `Hi {{1}}, {{2}}, Thanks & regards, Team Cozeevo Coliving`. `{{1}}`=tenant name, `{{2}}`=operator-typed free text. This is the reusable wrapper for the future PWA broadcast-messaging feature (not built yet — see [[project_broadcast_messaging]]). Built + published a clickable mockup of that screen (Web v2 Host kit) for Kiran to review before real implementation.
- 🐛 **Found + fixed: CC-to-operators reliability bug.** The original CC mechanism sent free-form text (`_send_whatsapp`) to Lokesh/Lakshmi/Prabhakaran/Kiran — only Kiran actually received it. Root cause: Meta's Cloud API returns HTTP 200 + a message ID for free-form text **even when it's about to silently drop the message** for being outside the 24h customer-service session window (checked via `whatsapp_log.from_number` — none of the 3 had messaged the bot in 2+ months). We don't capture Meta's delivery-status webhooks, so "200 OK" was misleading us, not just Kiran. **Fix:** CC now goes through the exact same `send_template()` path as the tenant broadcast (bypasses the window entirely) — operators are just added to the same send loop, receiving the literal tenant-facing message instead of an abstract summary. No new "CC summary" template needed. Re-sent to the 3 who missed it; all 3 accepted via the reliable path.
- ✅ **Extended `rules_whatsapp_cc.md`** — CC now applies to ALL bulk/broadcast tenant sends (not just checkout notices), and documents the template-vs-free-form reliability finding so it isn't rediscovered.
- ✅ **P&L fix: `9346853507` = Naveen (staff)**, 2 July transactions (₹15,000 + ₹9,000, was sitting in "Other Expenses / Misc UPI Payments") reclassified to Staff & Labour in DB, plus classifier rule added (`src/rules/pnl_classify.py`) so future imports auto-classify. July'26 Staff & Labour total now ₹1,70,143. July is computed live from `bank_transactions` on every P&L view (not frozen), so the DB fix is immediately reflected — no rebuild step needed.

### Files touched
- `scripts/_send_laundry_notice.py` (new, one-off) — dry-run/`--send` broadcast script; also sends the operator CC via the same reliable template path.
- `src/rules/pnl_classify.py` — added `("Staff & Labour", "Salary - Naveen", ["9346853507"])`.
- DB: `bank_transactions` id 3691, 3847 recategorized Staff & Labour.
- Memory: `rules_whatsapp_cc.md` (extended + reliability fix documented), `reference_whatsapp_templates.md` (2 templates confirmed APPROVED, `custom_broadcast_notice` added PENDING), `project_broadcast_messaging.md` (new — decision + mockup + next steps), `reference_pnl_classifications.md` (Naveen entry).

### Verification
- ✅ Dry run matched 262 active tenants before live send.
- ✅ 262/262 tenant sends confirmed (script summary).
- ✅ CC re-verified via `whatsapp_log` DB rows + Meta 200 responses for all 4 operators on the reliable path.
- ✅ July Staff & Labour total spot-checked via `_compute_dynamic_pnl_months()` directly (₹1,70,143, up from pre-fix).

### Key lesson
A `200 OK` from Meta's Cloud API is not proof of delivery for free-form text — it only proves acceptance. The 24h session-window check happens downstream and fails silently from our side (no delivery-status webhook wired up). Any CC/staff-notification mechanism must use an approved template, never free-form text, or it will intermittently and silently fail exactly like this did.

## Session X — 2026-08-08 — Deposit-forfeiture rule reverted (late notice no longer forfeits)

### Summary
Kiran flagged Omkar Deodher (Room 616) showing "Deposit Forfeited" despite giving notice over a month before his actual last day (24 Jul notice, vacates 31 Aug). Traced to `is_deposit_eligible()` checking the day-of-month notice was given in, not the day relative to the month the tenant actually vacates in. Kiran confirmed the correct rule: refundable if notice arrives before the 5th of the VACATING month — which, walked through the math, is equivalent to "any notice at all is refundable, only zero notice forfeits." This reverts the 2026-06-27 rule (late notice also forfeits) back to the 2026-05-10 rule.

- ✅ **`services/property_logic.py::is_deposit_eligible()`** — now refundable for any non-null `notice_date`; forfeited only when `notice_date is None`. Docstring + `NOTICE_BY_DAY` comment updated.
- ✅ **`tests/test_notice_comprehensive.py::TestDepositEligibility`** — 12 parametrized day cases + edge cases updated to expect `True` for late notice, `False` only for `None`. 160/164 passing (4 pre-existing unrelated NLP month-parsing failures, not touched).
- ✅ **Two frontend duplicate implementations fixed** — `web/app/tenants/[tenancy_id]/edit/page.tsx` and `web/app/checkout/new/page.tsx` had each re-implemented the day-of-month check in TS instead of calling the backend (the exact "same formula in two places" anti-pattern `rules_financial.md` §12 warns about). Both now treat any notice as eligible; checkout page's late-notice banner flipped from orange "Deposit Forfeited" to green "Deposit Refundable" (still shows the next-month-cycle/full-rent consequence).
- ✅ **`web/app/notices/page.tsx` legend text** — already read `deposit_eligible` from the API (correct, no logic bug there), only the static help text explaining the rule was stale — fixed.
- ✅ **`src/services/pdf_generator.py` HOUSE_RULES`** — rental-agreement PDF text updated to match (was saying "late notice = forfeited," now says refundable regardless of notice day). Tenants who signed 2026-06-27→2026-08-08 agreed to the stricter old text; app now treats them more generously than what they signed, not a risk to Kiran.
- ✅ **`src/api/v2/checkout.py` and `src/whatsapp/handlers/owner_handler.py`** — both already called the shared `is_deposit_eligible()` function (no duplicate logic), so they picked up the fix automatically. Only had stale comments, not fixed (cosmetic, no behavior impact).
- ✅ **Memory (`rules_financial.md`) reconciled** — had two contradicting entries (§0b said late=forfeited from 2026-06-27, §3 said any-notice=refundable from 2026-05-10, never cleaned up). Consolidated into one current statement with the full flip-flop history documented so it doesn't happen a third time silently.

### Verification
- ✅ 160/164 unit tests passing (4 pre-existing, unrelated)
- ✅ `tsc --noEmit` clean on both edited frontend files
- ⚠️ Not yet deployed to VPS — needs `git push` (webhook auto-deploys) to take effect for Omkar and any other currently-forfeited-due-to-late-notice tenants

### Key lesson
Same lesson as the June 27 entry, but the other direction: when a business rule flips, grep for **every** place that duplicates the check, not just the canonical function — two frontend files had silently drifted out of sync with the backend, which is exactly what "single source of truth" was supposed to prevent, and it still happened.



### Summary
Built an interactive, self-contained sales-demo mockup (no backend, dummy data) of Home, Finance, and the Web v2 Bed Board, for showing prospective PG-owner clients. Iterated through several rounds: static screenshots → single interactive device with real tab navigation → per-tile KPI expand panels (matching the real app's `ExpansionPanel`) → Bed Board room-tap filtering → dedicated Tenants tab (was accidentally aliased to Finance) → hosted on the live VPS instead of a claude.ai link.

- ✅ **`mockups/kozzy.html`** — single HTML file, DM Sans + Geist + Geist Mono fonts embedded as base64 (zero external requests), old-PWA brand kit (cream/pink) for Home+Finance, Web v2 "Host" kit (coral/Geist) for Bed Board. Fully interactive: tab bar switches 4 pages (Home/Board/Tenants/Finance), all 7 Home KPI tiles expand inline with dummy detail rows, Bed Board's 3 KPI tiles filter the room grid (tap Dues → only due rooms stay active), every Bed Board room is tappable and updates the inspector card, Tenants has live name/room search, Finance's Generate P&L button gives real press feedback, Monthly/All-time toggle works.
- ✅ **`mockups/README.md`** — documents the "BRAND TOKENS" comment blocks in the CSS (5 values for Home/Finance, 3 for Bed Board) so reskinning for a new client is a copy + edit ~8 color values, no rebuild needed.
- ✅ **Hosted on the live VPS, not claude.ai** — copied into `web/public/mockups/kozzy.html` (Next.js serves `public/` as static passthrough) and `web/middleware.ts` allowlists `/mockups/**` so it's reachable **without login** (prospective clients have no account). Live at `app.getkozzy.com/mockups/kozzy.html`. Nothing else about the auth gate changed — every other route still requires login exactly as before.
- ⚠️ **`[UNCONFIRMED]` `app.getkozzy.com/login` showed a client-side exception right after this deploy.** The middleware diff is minimal and doesn't touch `/login`'s existing bypass, so this is very likely an unrelated stale-service-worker cache from the deploy (known failure mode — see the "PWA Build Failure" incident earlier in this changelog) rather than something this change caused. **Not yet confirmed fixed** — Kiran was going to hard-refresh / unregister the SW and check `/tmp/deploy.log` on the VPS; needs a follow-up check next session before assuming it's resolved.

## Session W — 2026-08-07/08 — Web v2 real data · July P&L close · admin-PIN removal

### Web v2 Bed Board demo (artifact `6e816cd3`)
- ✅ Real DB snapshot embedded (`scripts/_export_web_demo_data.py`): 166 real rooms/floors, staff rooms grey, per-bed August dues via shared `services/dues.py`, KPIs, last-12-day register, bookings/checkouts/notices, 6-mo occupancy. Real structure captured (THOR x01–x12 / HULK x13–x24 mirror floors).
- ✅ Kiran iterations: equal 12-slot floor grids, THOR left/HULK right, bed ICONS (premium = ONE wide king bed), legend chips = the filters (Today segmented control removed), KPI cards → drill-down tables replacing the board; dues KPI also lights board filters. Old artifacts (5-Directions, Command Center, P&L diagram) wiped to tombstones per Kiran.

### July 2026 P&L — FULL month close (`data/reports/PnL_Cozeevo_2026_07.xlsx`)
- ✅ Imported THOR 57 + HULK 202 rows (importer `scripts/_import_july_2026_csv.py`, dedup 0) — **both statements reconcile to the paisa**.
- ✅ Classification loop ×3 with Kiran (review workbook `scripts/_export_july_review_workbook.py` → `classified 08_08.xlsx` → `scripts/_apply_classified_2026_08_08.py`): ~30 reclasses; permanent rules added: kaveri water→Water, jalluram→Housekeeping, "hand loan" narration→Non-Op, sump clean/heat pump/hand shower/washing machine→Maintenance, master advance→Staff Advance, inar devi→Staff, vegetable words→Food. Bava ₹13L+₹1L auto-classified Non-Op as planned (Session S prep).
- ✅ **Chandra loan flow un-hidden**: ₹90,000 out narration "Hand Loan" was mislabeled Tenant Deposit Refund by the auto-detector (matched tenant "Chandrasekhar"); ₹79,900 back in was counted as rent income. Both → Non-Operating; `_compute_dynamic_pnl_months` income filter now excludes Non-Operating credits.
- ✅ Adjustments final: rent_paid_cash 15,32,000 · cash_expense 2,000 (helper) · cash_holding 65,000 (Jul-31 count) · **offline_cash 67,850 — NEW column** (migration `run_pnl_offline_cash_2026_08_08`); cash income line = ALL cash received + offline (Kiran: "never miss any cash") → **₹28,99,100 = his figure exactly**. June also on all-cash basis now.
- ✅ **July: True Revenue ₹44.18L · OPEX ₹30.18L · NET OPERATING ₹14,00,408 (31.7%)** vs June ₹8.83L — bridge: +3.8L cash (dues catch-up), fewer check-ins (deposit netting −1.65L), June's mass-exit refunds (−2.24L swing).
- ✅ **Closing-balance bug fixed (Kiran caught)**: Yes Bank CSVs newest-first → code took mid-day balance (THOR 4,40,731 vs true 2,70,437; HULK 98,462 vs 77,996). Order id ASC within last date.
- ✅ **Statement self-reconciliation guard**: `read_statement_summary()` reads the bank's printed opening/closing; upload REJECTS files where opening+deposits−withdrawals ≠ closing. Truncated/misparsed statements can no longer import silently.
- ✅ Loan register July: bank Bava 14L + G Ravikumar 2L + Chandra 90K (−79.9K repaid) · cash Chit Belandur 5L + Chit Boobalan 3.5L + Chandra 50K + **Loan to Mama 7L**.
- 📋 `docs/MONTH_CLOSE_TEMPLATE.md` + `data/reports/Cash_Book_2026.xlsx` (auto expected-closing/variance formulas; July example shows Kiran's **+₹64,841 unexplained cash variance — OPEN**).

### Security — shared admin PIN REMOVED (Kiran: "don't need this at all")
- 🔐 `cozeevo2026` shipped inside public JS (PWA bundle + staff-sign page source) → all `/api/onboarding/admin/*` (approve, KYC, session edits, room lookup) effectively open. Now **Supabase JWT admin/staff only**; PIN paths deleted; `static/admin_onboarding.html` + serve route removed; PWA calls switched to JWT. **NOT live until VPS deploys — deploy is urgent.**

### Deploy — DONE 2026-08-08 evening
- ✅ Kiran deployed (VPS was already current via webhook, restarted API + rebuilt PWA ×2). Live-verified from outside: old PIN → 403, legacy checkout → 410, /config live, PWA serving. **The Session U → W deploy backlog is closed.**
- 🐛 Post-deploy fix: bookings page showed mojibake (₹→"â‚¹") — my PowerShell regex edit had corrupted the file's UTF-8; repaired + redeployed (`6ae8af6`). Rule saved: never edit source via PS Get/Set-Content.

### Open (Kiran)
Option A/B refund double-subtraction · ₹64,841 cash variance · internet accrual for dynamic months · chandrasekhar handle got ₹23K in frozen Jan/Feb labeled refunds (note only) · re-upload corrected P&L to Google Sheets (his copy has old balances) · 2FA + Hostinger/Supabase key rotation · VPS `reboot` for kernel updates (quiet hour).

## Session V — 2026-08-07 — Phase 3 backend consolidation (Web v2 prerequisite) — EXECUTED

### Summary
Kiran-approved Phase 3 from `docs/audits/2026-08-06-connectivity.md` + `WEB_REBUILD_SPEC.md` §3, implemented per plan `docs/superpowers/plans/2026-08-07-phase3-backend-consolidation.md`. Commits `40fcda7`…`136b4e1`, all pushed.

- ✅ **`src/services/dues.py` — single source for ALL monthly dues math** (mirrors the daily_dues.py consolidation). `monthly_dues()` split view (first-month proration, rent→deposit overflow, booking_credit) + `paid_toward_period_clause()` / `period_remaining()` / `outstanding_months()` bundled view + `first_month_due()`. 15 unit tests in `tests/test_dues_logic.py`.
- ✅ **All 7 API + 4 bot call-sites wired to it — zero inline copies left:** `get_tenant_dues`, `list_tenants` (now split-math → Manage list finally matches the dues page + KPI tile, fixes D-3; adds the booking credit it lacked), KPI tile, KPI dues panel, reminders overdue (**now credits booking advances — was overstating dues**), reporting pending, recent-checkins fallback (now prorates), bot `_calc_outstanding_dues`, `build_dues_snapshot`, `_query_dues`, `_my_balance`, rollover `_prev_outstanding`.
- ✅ **Legacy PIN checkout stack RETIRED (D-1 HIGH fixed):** all `/api/checkout/*` → 410 tombstone; `static/checkout_admin.html` + `checkout_confirm.html` deleted; serve routes removed. v2 (`/api/v2/app/checkout/create`) with refund re-validation is the only checkout path.
- ✅ **Dead weight deleted:** `sync_router.py` (was unmounted), `/api/ingest`, `/api/entities`, empty `/api/report` shell, v2 `voice/*` (client-side parser replaced it; unused `extractPaymentIntent` wrapper removed), onboarding `/admin/stats`. **KEPT deliberately:** blacklist REST (Web v2 admin UI), `regen-pdf` (10 pending agreement PDFs), `/api/reconcile`. auth_hooks docstring path corrected.
- ✅ **Write-dedup guards:** cash expenses + cash counts → 409 on identical row (double-tap bug); quick-book advance Payment now carries `unique_hash` (same md5 recipe as `log_payment`) → 409 on duplicate submit.
- ✅ **`GET /api/v2/app/config`** serves `notice_by_day` (property_logic) + `total_beds` (live from rooms table). `web/lib/config.ts` cached hook; checkout/new, notices, edit-tenant now consume it — the 2 hardcoded consts + 3 literal `5`s are gone (D-5, spec rule 6).
- ✅ **Classifier catch-all fixed (Session R bug):** "Bank Charges / Bank Transfer / IMPS / NEFT" rule removed — Bank Charges now only matches genuine fee narrations (`neft chg`, `chrg`, …); bare IMPS/NEFT/RTGS principals → `Other Expenses / Unclassified Bank Transfer` so they surface in the review pass instead of silently booking as opex. Applies to future imports only.
- ✅ **Reminders page → read-only "Overdue dues" list** (send actions were permanently 410 → guaranteed error toast); rows deep-link to collect payment; `sendReminder` wrapper removed; Tenants-hub tile renamed.
- 🧪 **Verification:** 195 unit tests run — 191 pass; the 4 failures are the pre-existing `test_future_month_extracted` month-parsing cases (Session I note). `npx tsc --noEmit` clean. Live smoke: `/api/checkout/*` → 410, `/config` mounted (401 unauth), `/api/ingest` → 404.
- ⚠️ **Golden suite is STALE, not broken by this session:** 55/105 fail — 36 are the deliberate WhatsApp finance block (`729ad81`, 25 May), 10 are tenant/lead auto-reply-disabled policy (empty replies), 9 are older behavior changes (ADD_TENANT → onboarding-form redirect) + test-data drift ("Anuron Dutta" not in DB). Zero failures touch dues math. Suite needs a policy-aware rewrite before it can gate deploys again.
- 🚫 **Not deployed to VPS** — rides with the still-pending Session U deploy; see pending tasks.

## Session U2 — 2026-08-06 — Root directory cleanup (Phase 1 of production-safe refactor) — Window B

### Summary
- 🧹 **Root reorganized, commit `dd1423c`** — 10 debug scripts → `scripts/utility/` (sys.path bootstrap added; verified zero external references — no shims needed); 4 root .md → `docs/` (INDEX.md link fixed); migration logs → `docs/audits/`; `file.svg` deleted (Next.js scaffold leftover, unreferenced).
- 🔐 **Secrets consolidated into `credentials/` (gitignored), NOTHING deleted:** both "Cozeevo Receptionist API Key" txt files (byte-identical, md5-verified — actually contain Anthropic API key + Hostinger root password + recovery codes + ngrok codes + Supabase anon key) + `hostinger back up code.pdf`. Personal docs (passport, signature, SBI statement, receipt) → `credentials/personal/`.
- 🗑️ **15 data files deleted after DB verification** (Kiran authorized: delete if incorporated in DB): THOR/HULK Apr–May statements (bank_transactions covers THOR Oct'25–Jun'26, HULK Mar–Jun'26), Whitefield trackers ×2 (Session S reconciled EXACT match), Investment.xlsx (imported as LAKSHMI_SBI), PnL_Accrual ×3 + PnL_Report (regenerable via pnl_builder), dues/reclassification worklists ×3 (acted on Sessions J/R). Plus 42 session screenshots + malformed `C:Temppg_api_test.log`.
- ⚠️ **KEPT in `data/imports/review/` — NOT verifiable in DB:** `AccountSummary Cozeevo hulk` (pdf + 2 xlsx — contains HULK txns from Jan 5 '26 but DB HULK starts Mar 4 '26 → possible 2-month import gap to investigate), Paytm ×2 + PhonePe UPI statements (no such account in bank_transactions — never imported), Lakshmi Gorjala raw statements ×4, `Untitled spreadsheet.xlsx` (331-row tenant roster Nov'25–May'26). Brand assets → `data/brand/`; expense/income photos ×12 → `data/imports/`; WhatsApp chat export → `data/whatsapp_chats/`.
- 📝 `.gitignore`: added `data/imports/`, `data/brand/`.
- 🗄️ **Phase 2 — production DB dry-run audit (read-only, nothing executed)** → `docs/CLEANUP_DRY_RUN.md`: 12 duplicate-payment groups (3 near-certain: pmt 21867 Ashmit ₹16K, 21450 Sheenad ₹7K, 21829 Depthi deposit ₹12K; 7 sheet-reload cash+UPI mirror pairs ≈₹66K need Kiran's Excel cross-check), room 402 premium+double conflict (t676 Anukriti vs t1162 Manu), 10 stale pending_review sessions on active tenancies (= Bookings page noise, overlaps Session Q "Group B"), Sujal phantom ₹1,450 Jul RS on exited t1226, t1143 Devamsh active-past-checkout, t845 Satish exited-no-date, `rentstatus` enum has no void value (cancelled tenancies keep live-looking dues rows).
- 🔌 **Phase 3 — connectivity + idempotency audit (read-only)** → `docs/audits/2026-08-06-connectivity.md` (supersedes 2026-06-15): no PWA→404 breakage; Reminders page still calls the permanently-410 send endpoint (guaranteed error toast); Finance rebuild orphaned 5 components + ~10 api.ts wrappers (12 endpoints unreachable; CLAUDE.md active-files stale); **D-1 HIGH: legacy PIN `POST /api/checkout/create` skips refund validation** that v2 enforces; monthly dues still 7 inline copies + 3 bot helpers (day-stay unified, monthly not); unguarded writes: cash expenses/counts + quick-book advance row. Unified-structure proposal (shared `services/dues.py`, retire PIN checkout stack, delete dead routers) written into the doc — pending Kiran approval.
- ✅ **Approved cleanup EXECUTED (Kiran go 2026-08-06, reversible, backup + audit_log per change)** — `scripts/_cleanup_2026_08_06.py --write`, backup `scripts/_backup_cleanup_2026_08_06.json`: voided dup payments 21867 ₹16K / 21450 ₹7K / 21829 ₹12K (**₹35K double-count removed**, freeze escape hatch used for Jun/Jul rows); RS 15926 (Sujal t1226 phantom Jul due ₹1,450) → na; 10 stale pending_review sessions → approved (Bookings page noise gone; PDFs via regen-pdf later); session 279 (Harshit stale no-show) → cancelled. **Skipped by safety guards:** t1143 Devamsh (has a payment after 10 Jun — manual review) and t845 Satish (no checkout_record date). **Still pending Kiran:** A2 mirror pairs (his Excel), room 402, frozen t871. ⚠ Jun/Jul ops-sheet tabs now ₹35K stale vs DB — decide whether to re-mirror those months.
- ✅ **DESIGN LOCKED (Kiran final):** Brand Kit v2 = **Host** (all other kits removed from demo) + Cupertino framework + **Geist / Geist Mono** production fonts + **KPI semantic-color rule** ("colors look random" fix: neutral cards, red=dues only, green=collected only, coral=interactions only; register tags de-rainbowed). Saved to `memory/project_web_v2_design_lock.md`. **Kiran authorizations recorded:** mirror-pair dedup vs source sheet (April freeze escape for those voids only) = next session's first task; Jun/Jul sheet re-mirror = ignore; 10-PDF list handed over; room 402 / Devamsh / Satish with Kiran to check; VPS verify pending (his terminal mangled the pasted command — typing it manually).
- 🎨 **Final design round (session end):** KPI band → identity stat cards (icon chips, per-KPI tint wash, consistent 8px progress bars, 93% ring, dues sparkbars, day dots — all `color-mix` on kit tokens so every kit re-tints automatically); pink-white gradient wash applied to main background (kit-driven); daily register got REAL calendar navigation (‹ › arrows, generated month popover w/ data dots, Today, empty states) replacing hardcoded day chips; **spec rule 6 added (Kiran): never hardcode — filters/options derive from data/config, ask when unclear, per-screen endpoint contract + parity tests** (`1350507`).
- 🖥️ **Design converged (late session): Bed-Board app shell = the direction.** Artifact `6e816cd3` iterated to: navy sidebar w/ burger + all areas populated (tenants/payments/bookings/checkouts/notices/finance/reports/ops), universal right inspector (rooms AND tenant rows → details + dues + ledger + actions), sorting + minimal filters, THOR/HULK side-by-side, 7 switchable brand kits (pick pending), **Cupertino type framework LOCKED** (Kiran rejected Cereal/Arena/Blend), Finance tabs with full PWA parity (daily register/P&L/cash/occupancy/uploads), Reports & export center, **Uploads tab = month-close pipeline** (upload→classify→review unknowns→cash figures→audit logs→recalculate→P&L — all current VS Code scripts become server jobs). Specs committed: `docs/planning/WEB_REBUILD_SPEC.md` (full PWA→Web/mobile inventory, one-endpoint principle, SaaS readiness §5 — **sequencing approved by Kiran**, month-close pipeline §2b).
- 🛏️ **Design iteration 3 — "Bed Board" published** (artifact `6e816cd3`, via frontend-design taste process): the signature is the building itself as the interface — 297 beds as a floor-by-floor mosaic colored by payment state (green/amber/red, hollow=vacant, pink dot=today's movement), click room → occupant inspector, lenses for Dues/Vacant/Today. Porcelain-light palette, Bahnschrift condensed display, pink=interaction only. Kiran rejected iterations 1 (5 card-grid reskins) and 2 (Command Center = dark+neon default). **Installed `leonxlnx/taste-skill` → `~/.claude/skills/taste` (design-taste-frontend) + `~/.claude/skills/redesign`** for next session (note: its own scope says landing pages, not dashboards).
- 🎛️ **Design iteration 2 — Command Center published** (artifact `5b46ba26`): asymmetric layout replacing the card-grid template — collection hero + dense stat rail + 60/40 master-detail work queue with live inspector, floating pill nav on mobile, icon rail on desktop. Interactive (click rows, filter tabs, bottom-sheet on mobile). UX iteration continues; UI deploy deferred per Kiran.
- 🎨 **Phase 4 — 5 design directions published** for the PWA+Web revamp: claude.ai artifact `40cee500` (V1 Ledger / V2 Graphite / V3 Kozzy Evolved / V4 Ember / V5 Blueprint), same live data in all five. Waiting on Kiran's pick before any UI implementation.

## Session U — 2026-08-06 — Duplicate tenant identities merged + dedup guardrails + payment-date bug

### Summary
- 🔴 **Room 415 "Rakesh" was two tenant rows sharing one phone (+919515739255)** — payments split across tenancy 894 (`Rakesh Thallapally`, 4 pmts) and tenancy 901 (`T.Rakesh Chetan`, 7 pmts). PWA history groups by `tenant_id`, so opening the wrong row showed collection stopping in May. **Cause:** no phone dedup existed on 22 Apr; the normalized-phone lookup landed 4 days later in `2e19b1d`. Also `tenants.phone` is `unique=True` in the model but the live DB only has a **non-unique** index `ix_tenants_phone`.
- ✅ **Merged, keeping the row with more payments (901/914):** ₹20,000 booking advance re-pointed, 4 KYC documents + onboarding session moved, DOB/Aadhaar/address copied onto the surviving tenant, 2 duplicate `rent_schedule` rows dropped, then tenancy 894 + tenant 897 hard-deleted with a JSON backup (`scripts/_backup_dup_tenancy_894.json`). **₹61,533 of double-counted Apr+May collections removed** (Apr rent 9,533 + deposit 26,000 + May rent 26,000 existed non-void on both). Scripts: `_merge_duplicate_tenants_415_615.py`, `_purge_dup_tenancy_894.py`.
- 🔴 **Room 615 "Sheetal" — different failure, still live in code:** booking made with phone 9444921568, onboarding form submitted with 9790791568 → phone lookup missed → second tenant row → `onboarding_router` re-pointed the tenancy to it, orphaning tenant 1169. Orphan deleted.
- 🛡 **Guardrails added (3 layers):**
  1. `onboarding_router.py` — approve now reuses the booking's own stub tenant row (its only tenancy) and lets the form win, so a **corrected phone no longer forks a new identity** and a **corrected name is no longer silently discarded**.
  2. `_absorb_orphan_tenant()` — backstop after both tenancy re-point sites: moves documents/onboarding sessions and deletes the abandoned row, only when zero tenancies remain.
  3. `payments.py::_tenancy_ids_for_person()` — history now groups by the **last 10 digits of the phone**, not `tenant_id`; a split can no longer hide payments. Phones under 10 digits fall back to `tenant_id`. Verified on live split 823/957 → both return `[820, 1039]`.
  - **Deliberately NOT a UNIQUE index on `tenants.phone`** — 4 pairs of genuinely different people share a number (Rupali/Sonali Rout, V.Sathya Priya/V.Bhanu Prakash, Anshsinha/anubhav, Shree Yaswanth/Lavanya). A constraint would block their check-ins.
- 🆕 **`scripts/check_tenant_integrity.py`** — reports SPLIT (same phone + similar name), ORPHAN (tenant with no tenancy), SHARED (same phone, different people = expected). `--strict` exits 1. Run after any data load.
- 🐛 **Advances were stamped with the check-in date, not the collection date** (`bookings.py:268` + 4 sites in `onboarding_router`). An advance taken today for a future check-in landed in the wrong month and read as a payment that hadn't happened. Fixed via `_receipt_date()` — today for future check-ins, the check-in date when back-dated. Sheetal's row was the only future-dated payment in the DB; corrected.
- 🔧 **Room 615 P Sheetal Reddy record rebuilt to match staff account** (`_fix_sheetal_615_record.py`): check-in 28 Aug → **1 Aug**; ₹14,500 UPI re-dated 2 Aug → **27 Jul** and re-typed booking → **deposit**; `booking_amount` 2,000 → 0; Aug RS recalculated 14,306 → **28,500** (full rent 14,000 + deposit 14,500) via `recalc_checkin_month_rs()`.
  - **Audit trail explains the mess:** Lokesh logged a ₹2,000 advance at booking (audit 2008), then on 4 Aug **edited that row's amount to ₹14,500** (audit 2105) to represent the deposit — there is no way to log a deposit against a pre-check-in booking, so editing the advance is the path of least resistance. The 2 Aug cash rent was never logged at all.
- 🟠 **Why "No dues ✓" showed on an unpaid tenant:** `tenants.py:398` forces dues to 0 when `checkin_date > today`. Correct behaviour, misleading label — a future booking is indistinguishable from a paid-up tenant.

## Session T — 2026-08-04 — VPS spec check + 2 new WhatsApp templates submitted (unwired)

### Summary
- 🖥️ **Hostinger VPS specs checked live via SSH:** 1 vCPU, 4GB RAM (~2.8GB avail), no GPU, 43GB disk free. Verdict: not enough to host Qwen-TTS 3B alongside the live bot — 1 vCPU would bottleneck both; needs 4+ vCPU/8GB+ RAM for tolerable CPU-only inference, or a separate GPU box for real-time speed.
- 📋 **2 new WhatsApp templates submitted to Meta (PENDING approval), NOT wired to any send/scheduler code:** `fridge_cleaning_notice` (id 4436544943254987, static "tomorrow" text — one-time use only, needs resubmission per future cleaning) and `laundry_rules_notice` (id 1024139837077941, reusable, no date content). Both logged in `memory/reference_whatsapp_templates.md` with explicit "never send without Kiran's go" flag per [[rules_no_tenant_comms]].

## Session S — 2026-07-11 — Buyout ledger written + loan register + exit-based maintenance + named non-op P&L lines

### Summary
- 💰 **Ashokan & Jitendra buyout ledger WRITTEN to `investment_expenses`** (Kiran confirmed ₹35L Prabhakaran personal, not ₹30L). 3 rows dated 18 Jun 2026, hash-deduped: Ashokan −₹29,04,152 · Jitendra −₹34,13,342.75 · Prabhakaran +₹35,00,000. **Cap table verified = ₹2,30,93,378** (Prabhakaran ₹1.06Cr, Chandrasekhar ₹1.03Cr, A&J zero). Synced: `unit_economics.py` `_TOTAL_INVESTMENT` → ₹2.31Cr + PWA card label. Classifier rules added so re-imports can't misroute the buyout NEFTs (`ashokan perumal`, `jitendranath` → Non-Operating; staff-Jitendra salaries unaffected).
- 🏦 **New Whitefield Expense Tracker (21-June-26) reconciled vs DB — EXACT match** (228 rows, ₹2,59,10,872.75, all 7 investor totals identical).
- 💸 **Loan register — 4 accounts, ₹27.5L lent out of profits (never P&L):** Bava/Bunk ₹19L (₹5L Jun-30 bank + ₹13L Jul-1 + ₹1L Jul-2; "Krishnama Naidu" = Bava's second account; his other ₹61L came from Bharathi = personal, outside PG books) · Balaji Bellandur ₹5L cash Jul-9 · Boopalan ₹3L cash Jul-11 · Boopalan(Tanvi) ₹50K. Jun-30 ₹5L bank txn (id 3417, was mislabeled "Investor Capital Return – Chandrasekhar") reclassified → `Hand Loan to Bava (Bunk)`; classifier keyword `chandrasekhar service` added. July prep notes saved in `memory/sop_pnl.md`. Structure artifact: claude.ai/code/artifact/92286d7c.
- 📊 **P&L "Maintenance Fee retained" line switched to EXIT-month basis (Kiran directive):** SUM(maintenance_fee) of tenancies checked out that month. Frozen row now Oct–Feb 0 (no exit data pre-Mar) · Mar ₹34.5K · Apr ₹1,08.5K · May ₹95.5K; Jun dynamic ₹1,87K (55 exits). Also fixed: May was frozen with maintenance 0 by mistake. Display-only — True Revenue math untouched. `pnl_builder.py` + `_compute_dynamic_pnl_months()`.
- 📊 **Non-Operating lump split into NAMED lines in the dynamic P&L excluded section** (`non_op_detail` by sub_category): June now shows Hand Loan to Bava ₹5L, Ashokan ₹5L, Jitendra ₹5L, Fencing ₹2.5L on their own rows instead of one ₹17.5L lump. Full P&L regenerated: `data/reports/PnL_Cozeevo_2026_07_11_v4.xlsx` (June: True Rev ₹35.99L, Opex ₹30.01L, NOP ₹5.98L, 16.6%).
- ✅ **June sanity checks (Kiran challenges, all verified clean):** deposit-refund ₹4,08,009 ties to ~75 genuine refund txns + `refunds` table corroborates (44/₹3.58L); 55 monthly June exits are NOT double-counted (55 distinct tenants; Bhanu Prakash + Sathya Priya = couple sharing phone, room 314); exits' net refundable = ₹6,15,875 − ₹1,87,000 = ₹4,28,875.
- 🟠 **OPEN:** (1) Kiran's offline Excel has 46 monthly June checkouts vs DB 55 — exit list exported (`June_2026_Exits_Maintenance.xlsx`), bulk days Jun-7 (21) + Jun-30 (20) are where to look. (2) PWA cash-collected vs Kiran's Excel: May gap ₹3.12L (likely deposit+booking cash definitional), June gap ₹17,231 — item register exported (`Cash_Register_May_Jun_2026.xlsx`). (3) Chit cadence (monthly from Aug?) + Tanvi ₹50K date/mode unconfirmed.
- 📝 Docs: `REPORTING.md` (exit-basis rule + buyout/loans never-expense rule), memory (`reference_total_investment.md` settled, `sop_pnl.md` July prep + loan register, MEMORY.md index).

## Session R — 2026-07-09→11 — June'26 P&L reclassification + investor buyout + day-stay deposit fix

### Summary
- 🔴 **June'26 P&L was badly misclassified — 23 bank rows reclassified (committed to DB, revert log saved).** Root causes in `pnl_classify.py`: (1) the `Bank Charges → "Bank Transfer / IMPS / NEFT"` catch-all swallows the **full principal** of any unmatched NEFT/RTGS/IMPS (not just a fee); (2) the `vakkal`/`sravani` Property-Rent keyword matches investor **Jitendranath Guptha Vakkalagadda**. Fixes to June DATA (rules still need patching — see pending):
  - Property Rent ₹13.5L → **₹6.0L** (Raghu ₹3L + Suma ₹3L only). Bank Charges ₹9.2L → **₹0**. Food ₹3.68L → **₹3.83L** (chicken vendor `9739392035` ₹15,330 moved in from Other). Other ₹1.47L → ₹0.33L.
  - Investor money OUT of OPEX → Non-Operating: Ashokan ₹5L + Jitendra ₹5L + Sri Lakshmi Chandrasekhar ₹5L. Fencing (M M Industries ₹1.7L + UPI ₹80K = ₹2.5L) → Non-Operating (capital, Kiran: not opex).
  - Tenant cross-check on "Other Expenses" (per [[rules_audit_logs]] SOP-E): `629939585`=**Naitik Raj** (₹8K) + `manideep163031`=**Manideep** t#566 (₹9.5K) → Tenant Deposit Refund. Unmatched: ₹11,352 "ylg", ₹10,500 "dranbukmb" (left in Other, flagged).
  - Set `pnl_monthly_adjustments` June: rent_paid_cash=₹15,32,000, cash_holding=₹2,35,059. Regenerated `data/reports/PnL_Cozeevo_June2026.xlsx`. **June NET OPERATING PROFIT ₹6,22,309** (True Rev ₹36.23L − OPEX ₹30.01L).
- 💰 **Investor buyout — Ashokan & Jitendra fully exited (18 Jun 2026); Prabhakaran absorbed their remaining stake.** Settlement ₹75L total = ₹10L UPI (₹5L each, in bank) + ₹30L PG cash + ₹35L Prabhakaran personal. **Invested capital recalculated ₹2.59Cr → ₹2.31Cr** (₹63.17L exited out, ₹35L Prabhakaran in). Ledger records NOT yet written — pending Kiran's go (see pending).
- 🐛 **Day-stay tenants were wrongly forfeiting deposit under the monthly notice rule.** Fixed 4 surfaces: `checkout.py:135` (API validation), `web/app/checkout/new/page.tsx:122` (modal), `owner_handler.py:365` + `:4413` (bot). Day-stays now excluded from notice-forfeiture entirely — deposit refundable (minus dues/deductions). Monthly unchanged. Both .py compile. **Needs deploy.**
- 🔧 **Data fix: Mukund Jalan (tenancy 1160, room 209) sharing_type double→premium.** Was clobbered on Lokesh's 413→209 room move (07-05 15:40) — the non-premium re-derive fired because he was stored as `single` (not premium) at move time, so the Session-P premium-preservation guard didn't catch him. Data corrected; premium guard gap noted in pending.

## Session Q — 2026-07-05 — ROOT CAUSE of recurring auto-checkin found + killed (main.py startup hook)

### Summary
- 🔴 **Root cause of the long-recurring "auto-checkin without a form" bug — found and removed.** A startup hook in [main.py](../main.py) (~line 98) ran, on **every app start**, one bulk statement: `UPDATE tenancies SET status=active WHERE status=no_show AND checkin_date<=today` — no onboarding form, no admin approval, no audit log. `bb4bbab` (13 Jun) only removed the date-based flip from `bookings.py`; this hook was never touched. That's why it "recurred after every deploy" — **every deploy restarts the app, re-running the hook.** The prior "deploy-lag / stale VPS commit" diagnosis was wrong. **Fix: hook deleted** (single-UPDATE culprit; Depthi/210 + K.Ramesh/320 flipped in the same txn at `09:00:15.726547` after a ~09:00 restart today).
- 🔁 **Data repair — 5 erroneously auto-activated tenants reverted to `no_show`** (form never filled: `pending_tenant`, no signature): Depthi/210 (t1246), Shreyas Shetty/416 (t1253), K.Ramesh Chandra/320 (t1275), Aryan Sharma/208 (t1247), Swadesh Yadav/221 (t1271). Advances retained, RS rows already `na`, each change `audit_log`ged.
- 🔎 **Full audit of every `status=active` path.** Only `main.py` was automatic. Approve is form-gated (`onboarding_router` requires `pending_review`); `bookings.py` always creates `no_show`. Remaining active-setters are deliberate staff actions: PWA check-in (`checkin.py:291`, blocks if a pending form-session exists), bot add_tenant (`owner_handler.py:6068`, still active-by-date, no form), bot assign-room (`:2639`), bot door check-in (`resolvers/onboarding.py:275`).
- ⚠️ **Needs commit + DEPLOY** — until the main.py fix is live, the next restart on old code re-flips the 5 reverted `no_show`s back to active.
- 🟠 **Open (Kiran's call):** whether to also lock down bot `add_tenant` (`owner_handler.py:6068`) so it never sets active without a form. Group B (10 tenants who DID fill+sign but were auto-activated without formal approval) left active — cleanup = run proper approve to generate their agreement PDFs.

## Session P — 2026-07-05 — Premium clobber-on-room-change fix + rollover moved to 1st + all reminders killed

### Summary
- 🐛 **Premium (whole-room) tenants silently downgraded to "double" on every room change.** Root cause: PWA Edit-Tenant `PATCH /tenancies/{id}` ran `tenancy.sharing_type = SharingType(new_room.room_type.value)` on room reassignment ([tenants.py](../src/api/v2/tenants.py)). Since no room is ever `room_type=premium`, this could only produce single/double/triple — wiping premium, with **no audit entry**. That's why it "kept repeating": every manual premium fix was re-clobbered by the next room move. The shared `execute_room_transfer()` (bot + transfer-room endpoint) was already clean.
  - **Fix:** extracted `resolve_sharing_on_room_change(current_sharing, new_room_type)` into `services/room_transfer.py` (single source of truth) — preserves premium, only re-derives for non-premium (e.g. triple→double), and audits the change. `tenants.py` now uses it. 7 regression tests in `tests/test_sharing_on_room_change.py` (all pass).
  - **Data repair:** restored `premium` on 3 clobbered tenants (audited): Nitya Dangarh/503, Chandra Sagar/604, Tanya Rishikesh/311 (all single-occupant whole-room ₹26–28k). Final scan: 0 victims remaining.
- 🗓️ **Monthly rent generation moved from the 2nd-last day (23:00) to the 1st of the month (00:00 IST).** `_monthly_tab_rollover` now targets the current month (the one that just started) with a 12h misfire catch-up. A tenant properly exited on the prior month's last day is now already `exited` before generation runs → no phantom next-month rent. (Krish Kumar/512 got a full July ₹25k on 29 Jun because it pre-generated while he was still active with a 30 Jun flagged checkout; the skip rule was left as-is per Kiran.)
- 🔕 **All automated outbound messaging switched off.** Removed/disabled: prep reminders (today/tomorrow), checkout-deposit alerts, nightly sheet-drift audit — job registrations removed AND added to the startup DB-jobstore purge list. Stripped admin WhatsApp notifications from rollover (success/failure), daily reconciliation, and weekly backup (now log-only). Manual PWA reminder endpoints (`POST /reminders/send`, `/reminders/trigger-prep`) hard-disabled (410). Only 3 scheduler jobs remain — reconciliation, backup, rollover — none send messages.
- ⚠️ **Needs VPS restart** to take effect (and to purge the persisted reminder jobs from the DB job store).

## Session O — 2026-07-02 — Dynamic SOP-format P&L (any future month) + Occupied day-wise filter

### Summary
- 🚀 **"Generate P&L" is now dynamic for every future month** — no longer hardcoded to Oct'25→May'26. Verified months stay frozen/hardcoded (byte-identical output — regression-checked: NET OP ₹14.97L, ADJ ₹11.17L unchanged); every newer month present in `bank_transactions` is computed **live from the DB** (classifier income THOR/HULK, OPEX by category, deposit refunds, security deposits, bank closing = last txn running balance) and **appended as a new column in the same SOP layout**. Upload dedup (`unique_hash`) already skips re-uploaded past lines, so re-uploading overlapping statements is safe.
  - `pnl_builder.py` parameterized: `_write_pnl_tab` + `build_pnl_workbook(dynamic_data=None)` + `build_pnl_bytes(dynamic_data=None)`. No-arg call = canonical verified report unchanged. DB→SOP key maps (`_DB_CAT_TO_OPEX_KEY`, income/excluded/deposit keys) co-located with the dicts; F&F+Capital Investment merge to "Furniture & Supplies"; unmapped categories fold to "Other Expenses".
  - `finance.py`: `_compute_dynamic_pnl_months()` builds one SOP record per non-verified month from the DB; `GET /finance/pnl/excel` now serves verified + dynamic; new `GET/POST /finance/pnl/adjustments` for the manual cash figures. Frozen verified months reject writes (400).
- 📝 **Manual cash form (Finance page)** — the 3 figures never in a bank CSV: **cash holding** (balance-sheet), **rent paid in cash** (OPEX), **cash expense** (OPEX). New `pnl_monthly_adjustments` table (unique on month) + `PnlAdjustmentsCard` component + `getPnlAdjustments`/`savePnlAdjustments` API. Verified months shown as locked.
- ✅ Verified end-to-end against live DB (fake June injected + rolled back → Jun'26 column renders correctly): builder unchanged, dynamic append, `_compute_dynamic_pnl_months`, HTTP handlers (download xlsx 20,901 B, adjustments round-trip, frozen 400, admin 403), app routes registered, PWA production build.
- ✅ **Occupied beds panel** now has the All/Regular/Day-wise stay filter (was only on check-ins/check-outs) — `kpi-grid.tsx`.
- ⚠️ Today only Oct'25–May'26 exist in DB (all frozen) → Generate gives verified-only until a June+ bank statement is uploaded, then the column appears automatically.
- Migration `run_pnl_adjustments_2026_07_02` (append-only) — run on DB.

## Session N — 2026-06-28 — Duplicate-booking prevention (DB constraint) + stay history + day-wise display

### Summary
- 🐛 **Manual bookings created duplicate tenancies** (same person/room/dates shown 2–3×). Built a 3-layer permanent fix:
  1. **DB exclusion constraint `no_overlap_active_tenancy`** (EXCLUDE USING gist + btree_gist) — physically blocks two active/no_show tenancies for the same tenant+room with overlapping dates, on ANY code path. Scoped to active/no_show so historical exited stays are untouched. Live + added to `migrate_all`.
  2. **App guard** in quick-book (`find_overlapping_tenancy` in room_occupancy) → 409 before insert.
  3. **App-wide handler** in `main.py` catches the constraint violation → 409 popup ("already has a booking in this room for overlapping dates") instead of a 500.
  - Repeat guest on DIFFERENT dates still allowed (new tenancy id, same tenant id).
- ✅ **Cleaned existing duplicates:** Udhayabharathi/115 (1264), Arun/608 (1259), Raja/618 (1167), Rama/G09 (1080) cancelled (0-payment side). Ajit/510 (kept 1158, re-linked ₹750 waiver, cancelled 1159), Jagan/G03 (kept 1252, voided duplicate ₹3,900 rent, cancelled 1263).
- ✅ **Tenant model = repeat-guest correct:** one Tenant id (the person) → many Tenancy ids (each stay). Confirmed/documented.
- ✅ **Tenant-search dropdown now shows each stay's dates + status** ("Room 115 · 10 Jun → 12 Jun · exited") so repeat stays are distinct, not identical rows. Search endpoint returns checkin/checkout/stay_type.
- 🐛 **Day-wise stays showed "/mo"** → fixed to "/day" on checkouts, bookings list, tenant-search. Backfilled 16 historical day-stay tenancies that had `agreed_rent=0` (8 from booking sessions, 8 from prepaid÷nights); Ajit/1158 set to ₹750/day (Kiran-confirmed). 3 ancient March/April records left at 0 (no rate data).
- Commits: `f154f4d` (dedup constraint+guard), `4361bd0` (dropdown dates), `39ee820` (popup handler + /day labels).

## Session M — 2026-06-28 — Day-stay rate lost on quick-book + capacity check dead since 3a6c5bb + VPS deploy-lag

### Summary
- 🐛 **Day-stay quick-book lost the per-night rate** — Lokesh booked Room 608 at ₹800/night, edit page showed ₹0. Root cause: when an advance is paid, quick-book creates the tenancy immediately, but `bookings.py:241` hardcoded `agreed_rent=0` for day-stays — the rate was saved only on the OnboardingSession (`daily_rate`), never on the Tenancy. Every reader (tenant detail, checkin, preview) reads the per-day rate from `Tenancy.agreed_rent` (canonical convention — see `onboarding_router.py:1662`; `Tenancy` has no `daily_rate` column). **Fix (`0bae69f`):** quick-book writes `daily_rate` into `agreed_rent` for day-stays. Repaired live records: Tenancy 1267 (Lokesh) 0→₹800; Tenancy 1226 (Sujal Jaiswal) 0→₹1,450 (inferred 14,500÷10 nights — confirm). Both audit-logged.
- 🐛 **Quick-book capacity check has been DEAD CODE since `3a6c5bb`** — that commit removed the `if room.room_number != "000":` guard but left its body indented one level deeper, so the entire bed-limit check silently nested under `if room.room_number == "000": raise` → unreachable for every room. **Bed limits were never enforced; any room could be overbooked past max_occupancy.** `ast.parse` passed (valid syntax, wrong logic) so it went unnoticed. **Fix (`81846de`):** dedented the block to run for every real room.
- 🐛 **VPS running stale pre-`bb4bbab` code (deploy-lag).** Lokesh's booking (check-in today) auto-jumped to `active`/"currently staying", skipping Bookings approval — the date-based auto-checkin behavior `bb4bbab` removed on **13 Jun**, still live on the VPS 15 days later. The deploy webhook is silently failing. Pushed redeploy trigger (`8b096d4`); **Kiran must verify VPS is at `81846de` via Hostinger console** — if older, every booking keeps auto-checking-in and new day-stays keep losing their rate.
- ✅ **Cleaned 7 stale onboarding sessions** (active tenant + pending session, all from the old auto-checkin path): Lokesh, Rajramani/G15, Nishant/116, Rajveer/108, Abhishek/G03, Sheenad/116, Santosh/507 → set `approved`. Removes orphaned "pending bookings" that double-count in occupancy/KPIs.
- ✅ **Room 608 confirmed legit double** (max_occ 2): Vaibhav (monthly) + Lokesh (day-stay) = 2/2 full, not a double-book.

## Session L — 2026-06-28 — Vacant-beds badge missing for expired-link bookings

### Summary
- 🐛 **Room with a real future booking showed as plainly free** in the home "Vacant beds" widget — no "Until \<date\>" badge — so the bed looked open and could be double-booked. Repro: Room 416 had a booking (Shreyas Shetty, check-in 1 Jul 2026) but showed only "1 bed free · Male". Root cause: the vacant-tile upcoming-checkin query (`src/api/v2/kpi.py` ~L526) gated onboarding sessions on `expires_at > now`. Shreyas's session is stored `status='pending_tenant'` with `expires_at=25 Jun` (link expired) — the "Link expired" UI label is a *lazily-computed display status*, the DB status is still `pending_tenant`. The expired-link session failed the `or_(...)` expires_at gate and was dropped, so no badge.
- ✅ **Fix (`22e4395`):** dropped the `expires_at` gate and added `"expired"` to the status set, so any non-cancelled future booking surfaces as an upcoming check-in. An expired link only means the tenant didn't finish their self-service form — the **room hold is NOT released**. Verified against live Supabase DB: new query returns `(416, 2026-07-01)` → "Until 30 Jun". Cancelled bookings still excluded (Cancel on Bookings page clears the badge); a held bed drops its badge once check-in date passes.
- General fix (query logic, not a 416 data patch) — applies to every room with an expired-link future booking.

## Session K — 2026-06-27 — Premium phantom-bed root cause + occupancy point-in-time + Generate P&L

### Summary
- 🐛 **Premium/whole-room tenants showed a phantom free bed** (Chandra/503, Abhishek/G03, Tanya/311, Soham/105). Root cause: the **`/bookings/quick-book` endpoint dropped `sharing_type` for MONTHLY bookings** — it only persisted it on the daily path, so the OnboardingSession AND no_show Tenancy were created NULL even when "Premium" was picked on the form. (The forms — kpi-grid "Pre-book Room" modal + pre-register — were always correct.) Fix (`5c49401`): quick-book resolves sharing_type for both paths and defaults to the room's master type when unspecified; onboarding-approve + bot add_tenant also default from room. **sharing_type is never NULL now.** Backfilled all 17 existing NULLs (sole whole-room → premium, rest → room type); set Chandra/G03/Soham → premium. 0 NULLs remain.
- 🐛 **Occupancy chart showed identical numbers for May & June (both 291/97.7%)** — `get_occupied_beds()` filters only `status='active'` with no date bound, so it returns *today's* count for any month. Added `get_occupied_beds_asof()` (point-in-time: present on date, incl. since-exited, capped per room); analytics live months now use it. May 287/96.3%, June 290/97.3%. (`c95810c`)
- ✅ **Generate P&L button** on Finance page → `/finance/pnl/excel` (same `pnl_builder`, byte-identical to offline export). Error handling surfaces the real status (`d65afc6`).
- ✅ **REPORTING.md** updated: P&L gross-includes-everything + deposit-flow-summed; occupancy point-in-time rule (`c1c51fd`).
- 📊 May unit economics confirmed: avg 282 occupied beds (96.3% month-end); rent ₹7,572/bed + non-rent ₹3,056/bed = ₹10,627/occupied bed.

### Open
- Tanya/311 (₹26K, tagged double + 2 no-shows) — premium mistag? Needs Kiran's call.
- Live P&L generator + adjustments table (new months self-serve). May 31 cash-in-hand → roll balance sheet.

## Session J — 2026-06-27 — May P&L build, HULK parser fix, reclassification, occupancy point-in-time

### Summary
- 🐛 **HULK bank parser booked all collections as expense.** HULK's CSV header starts with `Transaction Date` (same as THOR) but has only a **Deposits** column. The position-based parser read it as THOR layout → Deposits became Withdrawals → ₹14.18L of May collections misfiled as expense (May Rent Income showed ₹12.99L vs real ₹25.13L). Fixed `read_yes_bank_csv` to map columns by **header name**; regression tests added. Re-imported HULK May (reconciles exactly to statement: +₹12,11,100).
- ✅ **Full P&L built Oct'25 → May'26** in `pnl_builder.py` (canonical). May figures Kiran-confirmed: cash rent paid ₹15,32,000, staff ₹76,258 (bank only, no accrual), internet ₹0 (prepaid bulk), water ₹62,900, cash income ₹20,99,079 (app ₹20.36L + Bala uncle ₹63K). True Rent Revenue ₹40,04,315, **Net Operating Profit ₹10,11,846**.
- ✅ **P&L structure changes (Kiran):** Gross Inflows = everything (rent + deposit + booking); deposit subtracted below ("everything in, subtract what we owe"). "Less: Security Deposits" is a monthly flow — **TOTAL now SUMS** (was showing only last month — bug). Removed opening/closing bank-balance rows from the P&L tab. THOR+HULK combined per category (no HULK lump).
- ✅ **Reclassification:** ₹91,600 of deposit refunds were hiding in "Other Expenses" (paid to tenants' personal UPI). Cross-referenced payees vs tenants table → reclassified to Deposit Refunds (now ₹2,75,800, matches expectation). BESCOM→Electricity, diesel vendor→Fuel, fans→Furniture, stabilizer→Maintenance. Other Expenses ₹1,22,551 → ₹34,687. Classifier rules added to `pnl_classify.py`; DB transactions reclassified.
- ✅ **App: "Generate P&L" button** → `/finance/pnl/excel` (same `pnl_builder` = byte-identical to offline export). **Upload now auto-detects tenant refunds** (`_detect_tenant_refunds`: payee phone matches a tenant → Deposit Refund). UploadCard wired back into Finance page.
- ✅ **Occupancy point-in-time fix:** `get_occupied_beds()` filters only `status='active'` with no date bound → every live month showed today's count (May & June both 291/97.7%). Added `get_occupied_beds_asof()` (counts who was present on the date, incl. since-exited, capped per room). Now May 287/96.3%, June 290/97.3%.
- ✅ **Chandra Sagar (Room 503)** premium tenant mistagged `double` → showed phantom free bed. Set `sharing_type='premium'`; vacant count 8→7. Root cause: no sharing-type field in booking/edit forms.
- 📊 **May unit economics:** rent ₹7,572/occupied bed, non-rent OPEX ₹3,056/bed, total ₹10,627/bed (avg 282 occupied beds, 96.3% at month-end).
- Commits: `5a5be3a` (upload card), `78d7369` (parser), `0d05855` (May column), `c45e34f` (structure), `c3bb3a1` (reclassify), `d124524` (generate button + refund detect), `c95810c` (occupancy). SOP updated with all P&L rules.

### Open (optional next builds)
- Sharing-type selector in booking/edit forms (root-cause fix for premium phantom beds).
- Live P&L generator + `pnl_monthly_adjustments` table so new months self-serve (only 3 manual cash figures needed).
- Roll P&L balance-sheet section to May 31 (needs Kiran's May 31 cash-in-hand count).
- Identify remaining ₹23K "Other Expenses" payees (vinod ₹14.4K, acme ₹5K, charasmatic ₹3.75K).

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
