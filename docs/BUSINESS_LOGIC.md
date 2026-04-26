# BUSINESS_LOGIC.md — PG Accountant Financial & Operational Rules

Complete documentation of all business logic, calculations, and decision rules used by the PG Accountant system.

---

## 1. OCCUPANCY CALCULATION

### 1.1 Total Bed Capacity (Dynamic)

**File:** `src/whatsapp/handlers/owner_handler.py`

Total beds are calculated dynamically from the rooms table, never hardcoded:

```sql
TOTAL_BEDS = SUM(max_occupancy) WHERE is_staff_room = False
```

**Current totals (updated 2026-04-26):**
- THOR: 145 beds (78 revenue rooms)
- HULK: 149 beds (80 revenue rooms)
- **Total: 294 beds** (295 from May 2026 when G20 returns to revenue)

Staff rooms excluded: THOR (G05, G06, 107, 108, 701, 702) + HULK (G12, G20[temp until Apr end])

### 1.2 Occupied Beds Calculation

**Files:** `src/whatsapp/handlers/owner_handler.py`

**Key Rule:** Premium tenancy = 1 person occupies ALL beds in the room (max_occupancy). Regular tenancy = 1 person = 1 bed.

```python
occupied_beds = SUM(
    CASE
        WHEN Tenancy.sharing_type == 'premium' THEN Room.max_occupancy
        ELSE 1
    END
)
WHERE Room.is_staff_room = False
  AND Tenancy.status IN (active, no_show)
  AND Tenancy.checkin_date <= month_end
```

### 1.3 No-Show Beds

**File:** `src/whatsapp/handlers/owner_handler.py`

No-show = booked but not yet arrived. Count ALL no-shows regardless of checkin_date (includes future bookings).

```python
noshow_beds = SUM(
    CASE
        WHEN Tenancy.sharing_type == 'premium' THEN Room.max_occupancy
        ELSE 1
    END
)
WHERE Tenancy.status = 'no_show'
  AND Room.is_staff_room = False
```

### 1.4 Vacant Beds

```
vacant_beds = TOTAL_BEDS - occupied_beds - noshow_beds
```

### 1.5 Occupancy Percentage

```
occupancy_pct = ROUND(occupied_beds / TOTAL_BEDS * 100, 1)
```

### 1.6 Premium Tenancy Definition

- Premium is an **operational status on Tenancy**, NOT a physical room attribute
- A premium tenant occupies the ENTIRE room alone and pays premium rent
- Room can switch between premium and regular sharing across months
- For occupancy: 1 premium tenant in a double room = 2 beds occupied
- For occupancy: 1 regular tenant in a double room = 1 bed occupied
- SQL field: `Tenancy.sharing_type = 'premium'` (enum SharingType)

### 1.7 Monthly Occupancy Report

**File:** `src/whatsapp/handlers/account_handler.py:1221-1238`

```python
active_tenants = COUNT(Tenancy WHERE status = active AND checkin_date <= last_day_of_month)
premium_count = COUNT(Tenancy WHERE status = active AND sharing_type = 'premium' AND checkin_date <= last_day_of_month)
no_show = COUNT(Tenancy WHERE status = 'no_show')  # no date filter
regular = active_tenants - premium_count
active_beds = regular + (premium_count * 2)
```

**Output:**
```
Checked-in: {active_beds} beds ({regular} regular + {premium_count} premium)
No-show: {no_show} beds reserved
Vacant: {294 - active_beds - no_show} beds
```

---

## 2. DUES SCOPING RULE (LOCKED)

**Files:** `docs/REPORTING.md:105-135`, `src/whatsapp/handlers/account_handler.py` → `_query_dues()`, `_report()`

### 2.1 Three Conditions (All Required)

1. **Active status**: `Tenancy.status == TenancyStatus.active`
   - Excludes: no_show, exited, cancelled

2. **Checked in before month start** (strict less-than): `Tenancy.checkin_date < date(Y, M, 1)`
   - New arrivals in month M haven't had time to pay yet -- not overdue, just arrived

3. **This month's rent schedule only**: `RentSchedule.period_month == date(Y, M, 1)`
   - Never cumulative across months

### 2.2 Outstanding Dues Formula

```python
paid = SUM(Payment.amount WHERE tenancy_id = T AND period_month = M AND is_void = False)
effective_due = RentSchedule.rent_due + RentSchedule.adjustment
outstanding = effective_due - paid
IF outstanding > 0: include in dues list
```

### 2.3 Applied In (2 Locations)

1. `account_handler.py` → `_report()` function
2. `account_handler.py` → `_query_dues()` function

**Test:** `tests/test_dues_month_scope.py` -- 10/10 passing

### 2.5 Room Occupancy — Single Source of Truth

**Any code answering "who is in room X?" / "is room X free?" / "how many beds occupied?" MUST use `src/services/room_occupancy.py`.**

A bed can be occupied by a long-term `Tenancy` OR a short-stay `DaywiseStay`. Before this helper existed, every caller rolled its own query and many forgot DaywiseStay — rooms looked VACANT while day-stay guests were sleeping in them. Example regression: April 2026 room 609 returned VACANT even though Albin + Anika were checked in as day-stays (fixed 2026-04-22).

Public helpers:
- `get_room_occupants(session, room, on_date)` — returns `RoomOccupants(tenancies, daywise, total_occupied)`
- `find_overlap_conflict(session, room_id, start, end, exclude_tenancy_id)` — returns conflicting name or None; used before every new check-in/transfer
- `count_occupied_beds(session, from_date, to_date)` — global bed count for dashboard KPIs

**Callers (don't inline the queries, import from here):**
- `owner_handler._room_status`, `_query_vacant_rooms`, `_query_occupancy`
- `account_handler._monthly_report`
- `owner_handler._query_occupancy`
- `_shared._check_room_overlap`
- `sync_sheet_from_db` dashboard summary

### 2.4 No-Shows and Future Checkins — AUTO-EXCLUDED

Pending(M) iterates `RentSchedule(period_month = M)`. We do NOT create RentSchedule for:
- `Tenancy.status = no_show`
- Tenancies with `checkin_date >= next_period_month` (future checkins shown in the source sheet but not yet live)

→ They cannot appear in Pending for month M. Source sheet's "April Balance" column may list them; reconciliation scripts must strip no-shows before comparing. See `docs/REPORTING.md §11.2`.

---

## 3. PAYMENT PROCESSING

**File:** `src/whatsapp/handlers/account_handler.py:195-408`

### 3.1 Flow

1. Identify tenant (fuzzy search by name or room)
2. Resolve period month (parse from message or default to current)
3. Check duplicate (24-hour window, same tenancy+amount+month)
4. Create Payment record (is_void=False)
5. Update RentSchedule status (pending → paid/partial)
6. Google Sheets write-back (fire-and-forget)

### 3.2 RentSchedule Status Update

```python
total_paid = SUM(Payment.amount WHERE tenancy_id, period_month, is_void=False)
effective_due = RentSchedule.rent_due + RentSchedule.adjustment

IF total_paid >= effective_due: status = paid
ELSE IF total_paid > 0: status = partial
ELSE: status = pending
```

### 3.3 Overpayment (threshold Rs.10)

```python
extra = total_paid - effective_due
IF extra > 10:
    Show choices: [1. Advance for next month, 2. Add to deposit, 3. Ask tenant]
```

### 3.4 Duplicate Detection

24-hour window: same (tenancy_id, amount, period_month, is_void=False). If found, ask user to confirm.

---

## 4. RENT CHANGES

**File:** `src/whatsapp/handlers/account_handler.py:893-1107`

### 4.1 Permanent Rent Change

Updates `tenancy.agreed_rent` + current and future `RentSchedule.rent_due` rows.

### 4.2 One-Time Rent Change

Updates only the target month's `RentSchedule.rent_due`. `tenancy.agreed_rent` stays unchanged -- next month reverts.

### 4.3 Rent Discount / Concession

Creates negative `RentSchedule.adjustment`:
```python
effective_due = rent_due + adjustment  # adjustment is negative for discounts
```

---

## 5. VOID / REFUND

**File:** `src/whatsapp/handlers/account_handler.py:411-499`

### Golden Rule: NEVER delete payment records. Use `is_void = True`.

After voiding, recalculate RentSchedule status from remaining non-void payments.

### Refund

Separate from void -- for exiting tenants. Recorded in Refund table with status (pending/approved/paid).

---

## 6. BILLING CYCLE, PRORATION & CHECKOUT

**Files:** `services/property_logic.py`, `src/whatsapp/handlers/owner_handler.py`

### 6.1 Billing Cycles

- **Standard (default):** 1st to 1st. First month prorated if mid-month checkin.
- **Custom (per agreement):** e.g. 6th to 6th. Stored in `tenancy.notes`. First month = full rent. No proration.

### 6.2 When Proration Applies

| Scenario | Proration? | Details |
|----------|-----------|---------|
| New checkin mid-month (standard) | YES | First month only. `INT(rent * days_remaining / days_in_month)` |
| New checkin mid-month (custom cycle) | NO | Full rent — billing month starts on checkin day |
| Normal checkout end of month | NO | Full month charged |
| Early exit before agreed date | NO | Full month, no refund for unused days |
| Overstay past agreed checkout | YES | Extra days: `INT(rent * extra_days / days_in_month)` |

**Proration always rounds DOWN** — tenant pays less, not more.

### 6.3 Checkout & Notice Rules

- Notice by 5th of month → deposit refundable, leave end of month
- Notice after 5th → deposit **forfeited**, charged until end of NEXT month
- Early exit (before agreed date) → full month charged, **no refund**
- Overstay (past agreed date) → prorated extra days charged

### 6.4 Settlement

```python
net_refund = deposit - outstanding_rent - outstanding_maintenance - damages
```

---

## 7. EXPENSE CLASSIFICATION (P&L)

**File:** `src/rules/pnl_classify.py`

### 7.1 Algorithm

First keyword match wins. **Order matters -- Non-Operating MUST be first.**

```python
for category, subcategory, keywords in rules:
    for keyword in keywords:
        if keyword in description.lower():
            return category, subcategory
```

### 7.2 Categories (18 expense + 5 income)

| # | Category | Examples |
|---|----------|----------|
| 1 | Non-Operating | bharathi prabhakaran, shalu.pravi |
| 2 | Property Rent | vakkal, sravani, r suma |
| 3 | Electricity | bescom, eb bill |
| 4 | Water | bwssb, water tanker |
| 5 | IT & Software | hostinger, kipinn |
| 6 | Internet & WiFi | airwire, broadband |
| 7 | Furniture & Fittings | wakefit, grace trader (CAPEX) |
| 8 | Food & Groceries | virani, zepto, chicken |
| 9 | Fuel & Diesel | dg rent, petrol |
| 10 | Staff & Labour | salary, arjun, housekeeping |
| 11 | Govt & Regulatory | bbmp, gst |
| 12 | Tenant Deposit Refund | refund, exit refund |
| 13 | Marketing | logo tshirt, sunboard |
| 14 | Cleaning Supplies | garbage, phenyl |
| 15 | Shopping & Supplies | amazon, flipkart |
| 16 | Maintenance & Repairs | plumbing, electrician |
| 17 | Bank Charges | debit card, imps charges |
| 18 | Other Expenses | catch-all |

### 7.3 Bank Statement Deduplication

SHA-256 hash of `date + description[:80] + amount`. Re-uploading same statement is safe.

---

## 8. BILLING RULES

- **Maintenance = one-time check-in fee from deposit, NEVER monthly**
- Excel rent columns `From 1st FEB` etc. = rent revision from that date
- **Proration always rounds DOWN** -- tenant pays less, not more

### 8a. Due date + late fee (effective 2026-04-23)

- **Grace window:** rent for month M is due by the **5th** of M.
- **Late fee:** **Rs.200 per day** for any payment made on or after the **6th**. Accrues daily until balance clears.
  - Day 6 → 1 day × Rs.200 = Rs.200
  - Day 10 → 5 days × Rs.200 = Rs.1,000
- **Reminder cadence** (all via approved Meta templates — no 24h window):
  1. 2 days before next month begins → `rent_reminder` to **every active tenant**.
  2. 1st of month → `rent_reminder` to **every active tenant**.
  3. 2nd onwards daily → `general_notice` to **unpaid tenants only**, with the running late-fee total from day 6.
- Fee wording is driven by `LATE_FEE_PER_DAY` + `LATE_FEE_FROM_DAY` in `src/scheduler.py`.
- **Not yet automated:** the Rs.200/day is currently displayed in reminder text only. Auto-adding it to `rent_schedule.due_amount` is a separate follow-up (needs schema decision: new column vs. folded into `due_amount`).

---

## 9. KEY CONSTANTS

| Constant | Value | Notes |
|----------|-------|-------|
| TOTAL_BEDS | 294 | Dynamic from rooms table (295 from May 2026) |
| NOTICE_BY_DAY | 5 | Deposit eligibility cutoff |
| OVERPAYMENT_NOISE_RS | 10 | Payment rounding tolerance |
| DUPLICATE_PAYMENT_HOURS | 24 | Duplicate detection window |
| DEPOSIT_MATCH_TOLERANCE | 10% | Bank deposit matching |
| DEPOSIT_MATCH_DAYS | 45 | Bank deposit matching window |
| LATE_FEE_PER_DAY | 200 | Rs./day, applied from day 6 |
| LATE_FEE_FROM_DAY | 6 | First day late fee starts accruing |

---

## 10. GOLDEN RULES

1. **NEVER hard-delete financial records** -- use `is_void = True`
2. **Dues are THIS MONTH ONLY** -- never cumulative
3. **Exclude same-month check-ins from dues** -- `checkin_date < month_start`
4. **No-show count has NO date filter** -- all no-shows counted
5. **Bank statement is P&L source of truth** -- not Supabase payments table
6. **Payments table is dues source of truth** -- not bank statement
7. **Classification order matters** -- Non-Operating must be FIRST
8. **Proration rounds DOWN** -- tenant pays less
9. **Maintenance = one-time, NEVER monthly**
10. **Premium is tenancy status, not room type**
11. **Total beds = dynamic from rooms table** -- never hardcode
12. **No refund for early exit** -- tenant leaves before agreed date = full month charged
13. **Overstay = prorate extra days** -- only case proration applies at checkout
14. **Custom billing cycle = full first month** -- no proration for 6th-to-6th type agreements

---

## 11. WHERE EACH CALCULATION LIVES

| Calculation | Primary Location | Also In |
|---|---|---|
| Occupancy % | `owner_handler.py` | -- |
| Dues Outstanding | `account_handler.py` → `_query_dues()` | -- |
| Collection Rate | `account_handler.py` → `_report()` | -- |
| Monthly Report | `account_handler.py:1157-1249` | -- |
| Rent Change | `account_handler.py:893-1107` | -- |
| Checkout Settlement | `owner_handler.py:818-902` | -- |
| Payment Log | `account_handler.py:195-408` | -- |
| Void Payment | `account_handler.py:411-499` | -- |
| Expense Classification | `pnl_classify.py:19-157` | -- |
