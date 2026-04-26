# Day-Wise Stay Parity — Design Spec
**Date:** 2026-04-26  
**Status:** Approved  
**Author:** Kiran + Claude

---

## Problem

`DaywiseStay` is a flat, denormalized table with different field names and no FK relationships. Day-wise guests are invisible to every financial handler (PAYMENT_LOG, QUERY_DUES, CHECKOUT, QUERY_TENANT, REPORT). Sheet columns differ from monthly. This creates two separate code paths that must be maintained forever.

---

## Decision

**Option A — Full merge into Tenancy.**  
Day-wise guests become first-class `Tenant` + `Tenancy(stay_type=daily)` records. All backend fields, sheet columns, and handlers are identical to monthly tenants. `DaywiseStay` table is archived (read-only, no new writes).

---

## Schema Changes

### 1. `Tenant.phone` — make nullable
Day-wise guests may not have a phone. Currently `NOT NULL UNIQUE`. Change to nullable; uniqueness check skipped when NULL.

### 2. `Tenancy` — no new columns needed
`stay_type = "daily"` (enum already exists) is the only distinguishing flag.  
All required fields already exist on Tenancy:

| Concept | Tenancy column | Notes for daily stays |
|---|---|---|
| Daily rate | `agreed_rent` | stored as rate-per-day |
| Total stay cost | computed | `agreed_rent × num_days + maintenance_fee` |
| Number of days | computed | `checkout_date − checkin_date` |
| Upfront booking | `booking_amount` | same |
| Maintenance | `maintenance_fee` | same |
| Deposit | `security_deposit` | same (often 0 for daily) |
| Check-in | `checkin_date` | same |
| Check-out | `checkout_date` | same |
| Expected checkout | `expected_checkout` | same as checkout_date |
| Status | `status` | active/exited — same enum |
| Sharing | `sharing_type` | same |
| Staff | `assigned_staff_id` | same FK |
| Notes | `notes` | same |
| Comments → notes | `notes` | merged |
| Stay type | `stay_type = "daily"` | distinguishes from monthly |

Fields that don't apply to daily stays (left NULL): `notice_date`, `lock_in_months`, `lock_in_penalty`, `food_plan_id`.

### 3. `Payment` table — used for day-wise payments
One `Payment` row per cash/UPI payment received.  
`period_month` = NULL for daily stays (not a monthly billing cycle).  
`payment_for = PaymentFor.rent` (booking payment).

### 4. `RentSchedule` — NOT used for daily stays
Dues are computed on the fly: `agreed_rent × num_days + maintenance_fee − total_paid`.  
No RentSchedule rows created for `stay_type=daily`.

### 5. `DaywiseStay` table — archived
Kept in DB as read-only historical archive. No new records written after migration. All new day-wise guests go through Tenant + Tenancy.

---

## Migration

One-time script: `scripts/migrate_daywise_to_tenancy.py`

For each DaywiseStay row:
1. Look up existing Tenant by phone (if phone matches, reuse — same person returning)
2. If no match, create new Tenant with name, phone (nullable)
3. Create Tenancy(stay_type=daily) with field mapping above
4. If `total_amount > 0`, create one Payment row for the amount paid
5. Mark DaywiseStay row with `source_file = "MIGRATED"` (tombstone, no delete)

Idempotent: skip rows where Tenancy with matching room + checkin_date + Tenant already exists.

---

## Sheet (DAY WISE tab)

DAY WISE tab keeps its own tab — day-wise guests do NOT appear in monthly tabs (APRIL 2026, MAY 2026, etc.).  
Monthly tabs = `stay_type=monthly` only.  
DAY WISE tab = `stay_type=daily` only.

**Column headers change to MONTHLY_HEADERS** (same as every monthly tab):
```
Room | Name | Phone | Building | Sharing | Rent | Deposit | Rent Due |
Cash | UPI | Total Paid | Balance | Status | Check-in | Notice Date |
Event | Notes | Prev Due | Entered By
```

For daily rows:
- **Rent** = daily rate (per day)
- **Rent Due** = `agreed_rent × num_days + maintenance_fee`
- **Cash / UPI** = from Payment table (same as monthly)
- **Balance** = Rent Due − Total Paid
- **Notice Date** = blank (N/A for daily)
- **Prev Due** = blank (no carryforward for daily)

`scripts/sync_daywise_from_db.py` rewrites to query `Tenancy WHERE stay_type=daily`, output using `MONTHLY_HEADERS`. Same sync pattern as `sync_sheet_from_db.py`.

---

## Handler Changes

### Handlers that work automatically (no changes needed)
Since `_find_active_tenants_by_name` and `_find_active_tenants_by_room` query Tenancy, day-wise guests are found the same way as monthly tenants after migration:

- `PAYMENT_LOG` — logs Payment row, updates DAY WISE tab via `update_payment()`
- `QUERY_TENANT` — returns Tenancy info
- `CHECKOUT` — sets Tenancy.status=exited, Tenancy.checkout_date
- `ROOM_TRANSFER` — updates Tenancy.room_id
- `WHERE_IS` / room query — finds by room_number

### Handlers needing minor tweaks
- **QUERY_DUES**: for `stay_type=daily`, skip RentSchedule lookup — compute dues as `agreed_rent × num_days + maintenance_fee − total_paid`
- **REPORT**: include `stay_type=daily` tenancies in occupancy + revenue totals
- **update_payment() in gsheets.py**: route `stay_type=daily` to DAY WISE tab instead of monthly tab

### Handlers to remove
- `DAYWISE_RENT_CHANGE` / `DAYWISE_RENT_CHANGE_WHO` (added yesterday) — no longer needed; Tenancy.agreed_rent is updated via standard `UPDATE_RENT` flow
- Day-wise branch in `resolve_pending_action` for room transfer — unified path via Tenancy

### `_find_active_tenants_by_name` — no change needed
Already queries `Tenancy JOIN Tenant JOIN Room`. Daily tenants are found automatically once migrated.

---

## What Stays the Same
- Monthly billing flow, RentSchedule, rollover — untouched
- Frozen month logic — untouched
- Tenant KYC, onboarding form — can optionally capture day-wise guests via same form
- TENANTS sheet tab — add `stay_type` column so staff can see daily vs monthly

---

## Out of Scope
- Onboarding form for day-wise (handled in a future spec)
- day-wise guests in monthly billing reports (they appear in DAY WISE tab only)
- Historical DaywiseStay data correction (migration is best-effort, source_file=MIGRATED marks them)
