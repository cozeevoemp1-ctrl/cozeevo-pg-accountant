# Changelog

## Session D — 2026-06-13 — Critical Bug Fixes: Data Consistency + Booking Cleanup

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
