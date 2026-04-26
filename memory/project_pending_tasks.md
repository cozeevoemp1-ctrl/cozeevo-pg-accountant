---
name: Pending Tasks
description: Master to-do list for PG Accountant project — updated each session
type: project
---

## Active / Next Up

1. **Set Maharajan's daywise rate via bot** — agreed_rent is currently Rs.0 on VPS (room 219, tenancy 945). Send: `change 219 rent to [actual rate] per day` then confirm Yes.
2. **All DaywiseStay attributes editable via bot** — user asked "all attributes in daystay also should be editable via helper functions". Not started.
3. **Agent Phase 2** — Enable `USE_PYDANTIC_AGENTS=true` on VPS. 48h soak window was ready 2026-04-27. Check if still valid.
4. **Task 6 (Supabase Auth)** — Kiran must configure Phone provider in Supabase dashboard.
5. **Task 23 (Vercel staging deploy)** — Connect `web/` to Vercel.
6. **`test_activity_log.py` broken** — pre-existing failure (`sys.exit()` at module level). Investigate separately.
7. **Chandra off-book cash** — Mar Rs.1.6L + Apr Rs.15.5K. Decide if we log as explicit entries.
8. **70 unclassified bank txns** — Kiran to fill yellow column in `data/reports/unclassified_review.xlsx`.
9. **WhatsApp template approval** — `cozeevo_checkin_form` still PENDING from Meta.

## Paused

- **Cozeevo website (getkozzy.com)** — landing page paused, waiting for Canva assets.

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
