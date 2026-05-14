---
name: Pending Tasks
description: Master to-do list for PG Accountant project — updated each session
type: project
---

## Active / Next Up

### UPI auto-reconciliation — activate before June 1
0d. **Gmail app password** — create at `myaccount.google.com/apppasswords`, add to VPS `.env` as `GMAIL_APP_PASSWORD` (also set `GMAIL_USER`, `HULK_EMAIL_SUBJECT=HULK`, `THOR_EMAIL_SUBJECT=THOR`)
0e. **Bank email forwarding** — configure Lakshmi UPI app / Yes Bank dashboard to send daily collection report to `GMAIL_USER` with "HULK" or "THOR" in subject
0f. **Cron job on VPS** — add: `0 8 * * * cd /opt/pg-accountant && .venv/bin/python -m src.workers.gmail_poller >> /tmp/upi_reconcile.log 2>&1`
0g. **Deploy new code to VPS** — `git pull && systemctl restart pg-accountant` + rebuild PWA: `cd /opt/kozzy-pwa && git pull && npm run build && systemctl restart kozzy-pwa`

### Outstanding dues analysis — resume when HULK bank available
0a. **Upload HULK April+May bank statement** — Kiran will upload `hulk bank statement april til now` → re-run `scripts/_thor_outstanding.py` to catch remaining THOR cross-building payments (currently 24 tenants Rs.2,25,434 outstanding but some may be cleared via HULK April bank)
0b. **G.D.Abhishek (612) manual review** — name has initials only; fuzzy match fails. HULK May bank shows "G D ABHISHEK" Rs.20K + Rs.2K = Rs.22K unmatched. His Sheet cash = Rs.13,250. Clarify actual balance with Kiran.
0c. **Navdeep/Navdaap duplicate** — rooms 000 + 506, phone 9953195499, same person. Two tenancy records double-count Rs.16K + Rs.14K. Determine which is active tenancy and remove duplicate from reports.

### Housekeeping (from 2026-05-09 session)
0. **Open PG Accountant from D drive** — `D:\Work\Claude Projects\AI Watsapp PG Accountant` → `git pull` → delete `C:\Users\kiran\Desktop\AI Watsapp PG Accountant`
0b. **LinkedIn Brand** — open `D:\Work\Claude Projects\LinkedIn Brand` in Claude Code → run writing-plans to create implementation plan → build PROFILE.md, hooks.md, topics.md, pipeline.md

## Active / Next Up

### Data fixes (from May payment import — 2026-05-05, updated 2026-05-14)
1. **G20 reclassification** — `UPDATE rooms SET is_staff_room=false WHERE room_number='G20'` + re-sync + import Chandraprakash ₹33k payment. Blocked because G20 is staff room in DB.
2. **May payments — still missing:**
   - Vijay Kumar (room listed "June" in sheet — not in DB, needs clarification which room)
   - Small residual gap ~₹6K cash vs sheet — from bot-logged payments not in sheet (acceptable)
3. **May P&L cash expenses not yet added** — May 2026 property rent + ops cash expenses need to be added to cash_expenses table once Kiran confirms amounts
3. **5 UNASSIGNED-room tenants with dues** — Tanya Rishikesh, Nihanth, Kiran Koushik, Ganesh Magi, Aditya Sable
4. **Room mismatches** — Gayatri Kulkarni NM (sheet:514, DB:519), Ganesh Magi (sheet:418, DB:219)

### Reminders
5. **REMINDERS_PAUSED=1** — still active on VPS. Re-enable when Kiran says so: `sed -i '/REMINDERS_PAUSED/d' /opt/pg-accountant/.env && systemctl restart pg-accountant`

### PWA — next features
6. **Smart Query** — AI query bar on dashboard home. Needs `/api/v2/app/query` backend endpoint (NL → DB query → answer). Groq llama-3.3-70b.
7. **Create Supabase account for Lokesh** — so he can log into `app.getkozzy.com` as receptionist. Email: TBD from Kiran.
8. **PWA adjustment form** — set `adjustment + adjustment_note` on tenant's current month row. (Backend done; PWA UI done on edit-tenant page — may already be complete, verify.)

### Completed this session (2026-05-06 — blacklist + reminders pause)
- ✅ **Blacklist system** — DB table, service layer, REST API, onboarding guard, bot commands (add/show/remove with disambiguation), 28/28 E2E tests passing.
- ✅ **Prem Prasana blacklisted** — "Do not admit — flagged by owner."
- ✅ **REMINDERS_PAUSED=1** — all rent reminders silenced on VPS until further notice.
- ✅ **migrate_all.py Unicode fix** — `→` → `->` (was crashing Windows console)

### Completed this session (2026-04-29, session 5)
- ✅ **Proration choice toggle** — Full/Prorated toggle on edit form when rent or room changes; backend honours `prorate_this_month` flag for both room-change and rent-only cases.
- ✅ **Edit Notice modal** — now edits `expected_checkout` (Last Day), not notice_date. Notice-given date shown as read-only hint.
- ✅ **Notices page** — removed "Expected Checkout — No Notice" section; daily-stay tenants excluded from notices API.
- ✅ **Maharajan (room 219)** — DB status set to exited; DAY WISE sheet resynced.
- ✅ **Checkouts list page** — `/checkouts`: month picker, search, All/Regular/Day-wise tabs, per-tenant cards with refund amounts.
- ✅ **Home quick links** — Checkouts · Notices · Sessions shortcuts always visible below KPI grid.

### Bot / backend
6. **DASHBOARD_SUMMARY "dues" line fix** — COLLECTION shows "Mar 2026 dues: Rs.15,500" but should show CURRENT MONTH (April) outstanding. Change `prev_dues` query in `_dashboard_summary`. Kiran expects ~Rs.3L.
7. **Set Maharajan's daywise rate via bot** — agreed_rent Rs.0 on VPS (room 219, tenancy 945). `change 219 rent to [rate] per day` → Yes.
8. **All DaywiseStay attributes editable via bot** — not started.
9. **Agent Phase 2** — Enable `USE_PYDANTIC_AGENTS=true` on VPS. 48h soak was ready 2026-04-27. Check if still valid.
10. **`test_activity_log.py` broken** — pre-existing failure (`sys.exit()` at module level). Investigate separately.
11. **Chandra off-book cash** — Mar Rs.1.6L + Apr Rs.15.5K. Decide if we log as explicit entries.
12. **70 unclassified bank txns** — Kiran to fill yellow column in `data/reports/unclassified_review.xlsx`.
13. **WhatsApp template approval** — `cozeevo_checkin_form` still PENDING from Meta.

### Infra
14. ~~**Merge `feature/pwa-forms-rent-collection` → master**~~ — Done; all work on master.
15. **Task 6 (Supabase Phone Auth)** — Kiran must configure Phone provider in Supabase dashboard.

## Paused

- **Cozeevo website (getkozzy.com)** — landing page paused, waiting for Canva assets.

## Recently Completed (v1.74.11 — 2026-04-28)

- **Day-wise time entry** — `checkin_time` + `checkout_time` on `Tenancy`; check-in form: time input for day-wise (defaults to now), "Days" → "Nights"; checkout form: time input, Stay Summary card, extra nights auto-detected + extra charge added to dues. Deployed.

## Recently Completed (v1.74.10 — 2026-04-28)

- **Sessions page editable UX** — `pending_review` sessions now have editable fields (name, phone, gender, all financials, checkout_date/num_days/daily_rate for day-wise); blue hint banner; `handleApprove` sends `overrides` to backend
- **Onboarding room occupancy guardrail** — room-number blur triggers occupancy check; red warning + occupant names if full, green count if space
- **Checkin idempotency guard** — checkin preview returns `already_checked_in` flag; PWA shows red warning + disables CTA for already-checked-in monthly tenants
- **no_show → active checkin fix** — POST `/api/v2/app/checkin` now accepts `no_show` tenants and transitions status to `active` on check-in (was 404 for all monthly tenants before physical check-in)
- **Sheet cash inflation fixed** — `deposit_credit` removed from `cash`/`total paid` display columns in `sync_sheet_from_db.py` (was inflating by ~₹3.1L)
- **Ronak Samriya ₹18,000 voided** — payment ID 14636, test/mistake; real April rent already captured from source sync
- **April 2026 sheet resynced** — 283 rows, corrected: Cash ₹13,05,783 / UPI ₹31,54,345 / Dues ₹88,766
- **Navdaap Gupta ₹4,400 gap** — accepted as May carry-forward (overpaid April, no DB action needed)

## Recently Completed (v1.74.7 — 2026-04-28)

- **Notice management — full feature** — KPI tile (On Notice · N, col-span-2, orange) with deposit badge per tenant; tenant edit Notice card (date input, deposit flag, expected checkout, withdraw button); checkout page auto-fills checkout date from expected_checkout + shows refund amount in notice banner; bot NOTICE_WITHDRAWN intent (cancel/withdraw/revoke notice → yes/no confirm → clears DB fields + sheet sync); API types updated throughout.

## Recently Completed (v1.74.0 — 2026-04-28)

- **April dues fixed (Rs.4L → Rs.88,766)** — three compounding bugs found and patched:
  1. gsheets write-back crashed for deposit payments (period_month=None → TypeError in strptime)
  2. sync_sheet_from_db.py April balance excluded deposit_credit → first-month tenants showed as unpaid
  3. _refresh_summary_sync was overwriting COLLECTION row with wrong per-row clamped sum after every bot/PWA payment
- **Booking payments excluded from Sheet Cash** — booking already pre-subtracted from rent_due; writing it to Cash was double-counting
- **trigger_monthly_sheet_sync added to payments.py** — COLLECTION row now refreshes after every PWA payment
- **Backfill script run** — 23 April deposit payments (Rs.3,18,750) written to Sheet Cash that were missing since crash
- **REPORTING.md §10 added** — canonical sheet ownership rules documented to prevent recurrence
- **CHANGELOG v1.74.0** — full fix log documented

## Recently Completed (v1.73.8 — 2026-04-27)

- **First-month dues inflation fixed** — deposit/booking payments (period_month=NULL) now counted in dues calc. Was affecting 28 April tenants / ₹3.9L invisible to old query. Arumugam 513: ₹32k → ₹5k.
- **PWA dues tile deployed** — rebuilt Next.js on VPS; "Open complaints" replaced with expandable dues tile.
- **Full amounts everywhere** — ₹1.98L → ₹19,80,000 on PWA and Sheet COLLECTION row.

## Recently Completed (v1.73.5 — 2026-04-27)

- **Full amounts everywhere** — PWA KPI tile + Google Sheet COLLECTION row now show `12,90,183` instead of `12.90L`. Applies to all future monthly tabs permanently.

## Recently Completed (v1.71.0 — 2026-04-27)

- **PWA deployed at app.getkozzy.com** — nginx + systemd + SSL on VPS. Auth fixed (ES256/PyJWKClient). CORS updated.
- **KPI panels v2** — occupied (name search + rent filter), vacant (room search + gender pills + partial vacancies), checkins/checkouts (name search + stay-type pills: All/Regular/Day-wise)
- **Tenant detail card** — click any tenant in KPI panel → see check-in date, rent, deposit, maintenance, dues, last payment
- **Money dashboard** — month nav, cash/UPI/bank breakdown, pure rent total, cumulative deposits held
- **Backend**: kpi-detail enriched (tenancy_id, rent, stay_type, free_beds, gender), deposits-held endpoint, reporting method_breakdown, total_deposits_held service function

## Recently Completed (v1.69.0–v1.69.1 — 2026-04-27)

- **DASHBOARD_SUMMARY handler** — all 6 Sheet-dashboard rows queryable via bot (occupancy, buildings, collection, status, notice, deposits). Deployed to VPS. 5 golden tests G101-G105 all pass.
- **BOT_FLOWS.md + RECEPTIONIST_CHEAT_SHEET.md** — DASHBOARD_SUMMARY + SHOW_MASTER_DATA added

## Recently Completed (v1.65.0 — 2026-04-26)

- **HTML dashboard deleted** — `src/dashboard/`, `src/api/dashboard_router.py`, `static/dashboard.html` removed; all main.py wiring cleaned up
- **Daywise tenant balance display fixed** — `_do_query_tenant_by_id` now shows Rs.X/day, days stayed, correct balance for daywise tenants (was broken with RentSchedule queries)
- **Daywise handler fallback confirmed** — all shared lookups already return both monthly and daily tenants; no changes needed to COLLECT_RENT, CHECKOUT, etc.

## Recently Completed (v1.64.0 — 2026-04-26)

- **ADD_STAFF flow** — single-message bulk input: `add staff [name] | role | salary | dob | phone | aadhar | room [num]`
- **Staff KYC** — photo/PDF upload to Supabase Storage `kyc-documents/staff/`; `kyc_verified` flag; `⚠ KYC pending` shown in `show staff rooms`
- **Staff model** — 5 new columns: salary, date_of_birth, aadhar_number, kyc_document_url, kyc_verified (migrated)
- **media_handler** — `download_whatsapp_media_bytes` + `upload_staff_kyc_to_supabase`
- **assign_staff_to_room** — no longer silent-creates; returns help prompt when name not found
- **Daywise rent change e2e test** — `tests/test_daywise_rent_e2e.py` (6/6); disambig tests (15/15) confirmed passing
- **sync_daywise_from_db.py** — active_count bug fixed (was showing 6 instead of 1)
- **Daywise rent change via bot** — `change [room] rent to [N] per day` → yes/no → updates `tenancy.agreed_rent` → confirmed working on VPS
