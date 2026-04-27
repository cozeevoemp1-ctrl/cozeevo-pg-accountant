---
name: Pending Tasks
description: Master to-do list for PG Accountant project — updated each session
type: project
---

## Active / Next Up

### PWA — next features (Track A, agreed by Kiran)
1. **Checkout PWA page** — `/checkout/new` form: tenant search → preview outstanding + deposit → collect/refund → confirmation. Backend endpoint needed (`POST /api/v2/app/checkout`).
2. **Tenant list page** — dedicated `/tenants` page listing all active tenants with room, rent, dues badge. Tap row → dues detail card + quick pay button.
3. **Onboarding form in PWA** — move static HTML at `api.getkozzy.com/admin/onboarding` into `app.getkozzy.com/onboarding/new`. Reuse existing backend (`/api/v2/onboarding/*`). OCR photo pre-fill (backlog).
4. **Smart Query** — AI query bar on dashboard home. Needs `/api/v2/app/query` backend endpoint (NL → DB query → answer). Groq llama-3.3-70b.
5. **Create Supabase account for Lokesh** — so he can log into `app.getkozzy.com` as receptionist. Email: TBD from Kiran.

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
14. **Merge `feature/pwa-forms-rent-collection` → master** — PWA is stable on VPS; needs merge so VPS tracks master.
15. **Task 6 (Supabase Phone Auth)** — Kiran must configure Phone provider in Supabase dashboard.

## Paused

- **Cozeevo website (getkozzy.com)** — landing page paused, waiting for Canva assets.

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
