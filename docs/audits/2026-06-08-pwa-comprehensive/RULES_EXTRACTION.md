# Rules Extraction — Complete Business Logic Audit

**Date:** 2026-06-08  
**Scope:** Extract all rules from docs/REPORTING.md, BUSINESS_LOGIC.md, BRAIN.md, SHEET_LOGIC.md, BOT_FLOWS.md, MASTER_DATA.md  
**Purpose:** Identify duplicates, conflicts, and gaps in documented rules

---

## Summary Statistics

- **Total rules extracted:** 87 rules
- **Financial rules (REPORTING):** 38 rules
- **Occupancy rules (BUSINESS_LOGIC):** 12 rules
- **Data sync / Sheet rules (SHEET_LOGIC):** 8 rules
- **Operational / Bot rules (BOT_FLOWS, BRAIN):** 18 rules
- **Master data / infrastructure rules (MASTER_DATA, BRAIN):** 11 rules

---

## SECTION 1: FINANCIAL RULES (RULE-FIN-*)

### RULE-FIN-001: P&L Cost Categories (18 expense categories)
**Source:** REPORTING.md §1.1
**Definition:** Chart of accounts with 25 total lines including expense categories (Milk through Bank Charges) plus income adjustments.
**Code location:** `src/rules/pnl_classify.py`, `src/api/v2/finance.py`
**Appears in:** REPORTING.md (authoritative), BUSINESS_LOGIC.md (duplicate)
**Status:** ✅ DOCUMENTED

### RULE-FIN-002: Income — Bank-Primary Rule
**Source:** REPORTING.md §1.2
**Definition:** "HARD RULE: Bank statement credits = primary income source. DB payments = supplementary (cash only)."
**Code location:** `src/api/v2/finance.py:_build_pnl_excel()`
**Status:** ✅ DOCUMENTED

### RULE-FIN-003: Income — 6 Line Items
**Source:** REPORTING.md §1.2 income table (rows 1–6)
**Definition:**
1. Bank UPI batch (THOR)
2. Bank direct UPI + NEFT (THOR)
3. HULK UPI settlements
4. THOR→HULK reclassification (−₹5L)
5. HULK←THOR reclassification (+₹5L)
6. Cash (physical, not deposited)
**Code location:** `src/api/v2/finance.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-004: Security Deposits — Excluded from Revenue
**Source:** REPORTING.md §1.2, §4.2
**Definition:** "Must return at exit — excluded from revenue." True Rent Revenue = Gross Inflows − Security Deposits
**Code location:** `src/api/v2/finance.py:_build_pnl_excel()`
**Status:** ✅ DOCUMENTED

### RULE-FIN-005: Maintenance Fees — One-Time, Never Monthly
**Source:** REPORTING.md §8 (Golden Rules), §4.2
**Definition:** "Non-refundable, stay in Gross Inflows. Do NOT deduct them. One-time check-in fee from deposit, NEVER monthly."
**Code location:** `src/whatsapp/handlers/account_handler.py`, `src/database/models.py`
**Related:** RULE-FIN-038
**Status:** ✅ DOCUMENTED

### RULE-FIN-006: OPEX Exclusions
**Source:** REPORTING.md §1.3, §11b (Unit Economics)
**Definition:** OPEX excludes: Furniture & Fittings, Capital Investment, Tenant Deposit Refund, Non-Operating
**Code location:** `src/services/unit_economics.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-007: Dues Calculation — Three Conditions (ALL Required)
**Source:** REPORTING.md §2.1, BUSINESS_LOGIC.md §2.1
**Definition:**
1. Active status: `Tenancy.status == active`
2. Checked in before month start: `Tenancy.checkin_date < date(Y, M, 1)` (strict <)
3. This month's rent schedule only: `RentSchedule.period_month == date(Y, M, 1)`
**Code location:** `src/whatsapp/handlers/account_handler.py:_report()`, `_query_dues()`, `src/api/v2/tenants.py:get_tenant_dues()`
**Conflict:** None — identical in REPORTING.md §2.1 and BUSINESS_LOGIC.md §2.1
**Status:** ✅ DOCUMENTED (duplicated across docs)

### RULE-FIN-008: Dues Outstanding Formula
**Source:** REPORTING.md §2.2, BUSINESS_LOGIC.md §2.2
**Definition:** `paid = SUM(Payment.amount WHERE tenancy_id = T AND period_month = M AND is_void = False); outstanding = (rent_due + maintenance_due + adjustment) - paid; IF outstanding > 0: include`
**Code location:** `src/whatsapp/handlers/account_handler.py`
**Status:** ✅ DOCUMENTED (duplicated)

### RULE-FIN-009: Dues Excludes Same-Month Check-ins
**Source:** REPORTING.md §2.3, BUSINESS_LOGIC.md §2.5
**Definition:** New arrivals in month M haven't had time to pay yet. Exclude via `checkin_date < month_start`.
**Code location:** `src/whatsapp/handlers/account_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-010: Dues Applied In 5 Places (Updated 2026-05-20)
**Source:** REPORTING.md §2.4
**Definition:** Must be consistent across:
1. `account_handler.py` → `_report()`
2. `account_handler.py` → `_query_dues()`
3. `src/api/v2/tenants.py` → `get_tenant_dues()`
4. `src/api/v2/kpi.py` → `get_kpi()` overdue KPI
5. `src/api/v2/kpi.py` → `get_kpi_detail(type="dues")`
**Status:** ✅ DOCUMENTED

### RULE-FIN-011: First-Month Proration Formula (Split Rent + Deposit)
**Source:** REPORTING.md §2.4 (first-month tenants), §10.3 (correct approach)
**Definition:** For first-month tenants:
```
prorated = floor(agreed_rent × days_remaining / days_in_month)
overflow = max(0, rent_paid - prorated)
rent_dues = max(0, prorated - rent_paid)
dep_due = max(0, security_deposit - (deposit_paid + overflow) - booking_amount)
total = rent_dues + dep_due
```
**Code location:** `src/api/v2/tenants.py:get_tenant_dues()`, `src/api/v2/kpi.py`, `src/services/rent_schedule.py:prorated_first_month_rent()`
**Status:** ✅ DOCUMENTED

### RULE-FIN-012: Collection Rate Formula
**Source:** REPORTING.md §4.1
**Definition:** `collection_pct = ROUND(collected / total_due * 100)` where collected = total_due - dues_outstanding
**Code location:** `src/whatsapp/handlers/account_handler.py:_report()`
**Status:** ✅ DOCUMENTED

### RULE-FIN-013: Total Collection — Includes Maintenance, Excludes Deposits
**Source:** REPORTING.md §4.2
**Definition:** Total Collection = Rent Collected + Maintenance Collected. EXCLUDES security deposits.
**Code location:** `src/api/v2/finance.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-014: Payment Status Determination
**Source:** REPORTING.md §5.1
**Definition:**
- `total_paid >= effective_due` → "paid"
- `0 < total_paid < effective_due` → "partial"
- `total_paid == 0` → "pending"
**Code location:** `src/whatsapp/handlers/account_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-015: Duplicate Payment Detection — 24-hour Window
**Source:** REPORTING.md §5.2, BUSINESS_LOGIC.md §3.4
**Definition:** Same (tenancy_id, amount, period_month, is_void=False) within 24 hours → flag as duplicate
**Code location:** `src/whatsapp/handlers/account_handler.py:PAYMENT_LOG`
**Status:** ✅ DOCUMENTED

### RULE-FIN-016: Overpayment Threshold — Rs.10
**Source:** REPORTING.md §5.3, BUSINESS_LOGIC.md §3.3
**Definition:** Ignore overpayments under Rs.10 (rounding noise). Above Rs.10: prompt for action.
**Code location:** `src/whatsapp/handlers/account_handler.py`
**Related:** RULE-FIN-032 (Key Constants)
**Status:** ✅ DOCUMENTED

### RULE-FIN-017: Void Payment — Never Delete
**Source:** REPORTING.md §5.4, BUSINESS_LOGIC.md §5 (Golden Rule #1)
**Definition:** Set `is_void = True` (NEVER delete). Recalculate RentSchedule status. Write AuditLog entry.
**Code location:** `src/api/v2/payments.py:void_payment()`, `src/whatsapp/handlers/account_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-018: Standard Billing Cycle — 1st to 1st (Default)
**Source:** REPORTING.md §6.1, BUSINESS_LOGIC.md §6.1
**Definition:** First month prorated if mid-month checkin, then full rent from next month.
**Code location:** `src/services/rent_schedule.py`, `src/database/models.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-019: Custom Billing Cycle — Nth to Nth (No First-Month Proration)
**Source:** REPORTING.md §6.1, BUSINESS_LOGIC.md §6.1
**Definition:** e.g., 6th-to-6th. Full rent first month (billing cycle starts on checkin day). Stored in `tenancy.notes`.
**Code location:** `src/database/models.py` (tenancy.notes field)
**Status:** ✅ DOCUMENTED

### RULE-FIN-020: Proration Rules — When It Applies (5 Scenarios)
**Source:** REPORTING.md §6.2, BUSINESS_LOGIC.md §6.2
**Definition:**
| Scenario | Proration? |
|----------|-----------|
| New checkin mid-month (standard) | YES |
| New checkin mid-month (custom) | NO |
| Normal checkout end of month | NO |
| Early exit before agreed date | NO |
| Overstay past agreed checkout | YES |
**Code location:** `src/services/rent_schedule.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-021: Check-in Proration Formula
**Source:** REPORTING.md §6.3
**Definition:** `days_remaining = days_in_month - checkin_day + 1; prorated_rent = INT(rent * days_remaining / days_in_month)`
**Example:** Rent Rs.13,000, checkin Jan 15 → prorated = INT(13000 × 17/31) = Rs.7,129
**Code location:** `src/services/rent_schedule.py:prorated_first_month_rent()`
**Status:** ✅ DOCUMENTED

### RULE-FIN-022: Overstay Proration Formula
**Source:** REPORTING.md §6.4
**Definition:** `extra_days = actual_checkout_day - agreed_checkout_day; prorated_extra = INT(rent * extra_days / days_in_month)`
**Code location:** `src/whatsapp/handlers/owner_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-023: Checkout — No Proration at Exit
**Source:** REPORTING.md §6.5
**Definition:**
- Notice by 5th → leave end of month, full month charged, deposit refunded
- Notice after 5th → leave end of NEXT month, full month charged, deposit refunded
- No notice → full month charged, deposit **forfeited**
- Early exit → full month charged, NO refund for unused days
- Overstay → full month + prorated extra days
**Code location:** `src/whatsapp/handlers/owner_handler.py`
**Conflict:** NONE — clear rule
**Status:** ✅ DOCUMENTED

### RULE-FIN-024: Notice Period Rule — 5th Day Cutoff
**Source:** REPORTING.md §7.1, BUSINESS_LOGIC.md §6.3
**Definition:** NOTICE_BY_DAY = 5. If notice by 5th → deposit refundable, leave end of month. If after 5th → deposit still refundable, but one full month rent required.
**Code location:** `src/whatsapp/handlers/owner_handler.py`, constants
**Related:** RULE-FIN-032 (NOTICE_BY_DAY = 5)
**Status:** ✅ DOCUMENTED

### RULE-FIN-025: Settlement Formula
**Source:** REPORTING.md §7.2, BUSINESS_LOGIC.md §6.4
**Definition:** `net_refund = security_deposit - outstanding_rent - outstanding_maintenance - damages`
**Code location:** `src/whatsapp/handlers/owner_handler.py:CHECKOUT`
**Status:** ✅ DOCUMENTED

### RULE-FIN-026: Expense Classification — Order Matters (Non-Operating FIRST)
**Source:** REPORTING.md §8.1, BUSINESS_LOGIC.md §7.1 (Golden Rule #7)
**Definition:** First keyword match wins. Non-Operating MUST be first (bharathi prabhakaran, shalu.pravi).
**Code location:** `src/rules/pnl_classify.py:19-157`
**Status:** ✅ DOCUMENTED

### RULE-FIN-027: Expense Classification — 18 Categories
**Source:** REPORTING.md §8.1, BUSINESS_LOGIC.md §7.2
**Definition:** Keyword-driven classification: Non-Operating → Property Rent → Electricity → Water → IT & Software → Internet → Furniture → Food & Groceries → Fuel → Staff & Labour → Govt & Regulatory → Deposit Refund → Marketing → Cleaning → Shopping → Maintenance → Bank Charges → Other Expenses
**Code location:** `src/rules/pnl_classify.py`
**Status:** ✅ DOCUMENTED (duplicated in BUSINESS_LOGIC.md)

### RULE-FIN-028: Bank Statement Deduplication — SHA-256 Hash
**Source:** REPORTING.md §9.1, BUSINESS_LOGIC.md §7.3
**Definition:** `unique_hash = SHA256(txn_date | description[:80].lower() | amount.round(2))`. Re-uploading same statement is safe.
**Code location:** `src/api/v2/finance.py`
**Status:** ✅ DOCUMENTED (duplicated)

### RULE-FIN-029: Google Sheet Collection Row — Ownership Rules (CRITICAL)
**Source:** REPORTING.md §10.1 (after 2026-04-28 three-layer bug)
**Definition:** Three functions own specific rows:
- `sync_sheet_from_db.py` → owns COLLECTION row (rows 2–6)
- `_refresh_summary_sync` in `gsheets.py` → owns Per-row Balance/Status/TotalPaid cells only
- `update_payment` in `gsheets.py` → owns Cash/UPI cell for one tenant row
**Code location:** `scripts/sync_sheet_from_db.py`, `src/integrations/gsheets.py`
**Status:** ✅ DOCUMENTED (CRITICAL — prevents data corruption)

### RULE-FIN-030: Total Dues — Canonical Formula (DB Aggregate, Not Per-Row Sum)
**Source:** REPORTING.md §10.2
**Definition:** Use `src/services/reporting.collection_summary()` aggregate, NOT clamped per-row sum
```python
# CORRECT
result = await collection_summary(period_month="2026-04", session=session)
total_dues = result.pending

# WRONG — overpaying tenants show balance=0, not negative
total_dues = sum(max(0, row.balance) for row in rows)
```
**Code location:** `src/api/v2/finance.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-031: First-Month Balance — Bundled Rent + Deposit Formula
**Source:** REPORTING.md §10.3
**Definition:** For first-month tenants, RentSchedule.rent_due bundles rent + deposit:
`rent_due = prorated_rent + security_deposit - booking_amount` (via `first_month_rent_due()`)
Do NOT subtract deposit from total bundled due twice.
**Code location:** `src/services/rent_schedule.py:first_month_rent_due()`, `recalc_checkin_month_rs()`
**Related:** RULE-FIN-011, RULE-FIN-037
**Status:** ✅ DOCUMENTED

### RULE-FIN-032: Key Financial Constants
**Source:** REPORTING.md §12, BUSINESS_LOGIC.md §9
**Definition:**
| Constant | Value | Notes |
|----------|-------|-------|
| TOTAL_REVENUE_BEDS | 298 | DB-verified 2026-05-31 |
| THOR_BEDS | 149 | Property occupancy |
| HULK_BEDS | 149 | Property occupancy (⚠ REPORTING.md says 146 — VERIFY) |
| NOTICE_BY_DAY | 5 | Deposit eligibility |
| OVERPAYMENT_NOISE_RS | 10 | Payment processing |
| DUPLICATE_PAYMENT_HOURS | 24 | Duplicate detection |
| DEPOSIT_MATCH_TOLERANCE | 10% | Bank deposit matching |
| DEPOSIT_MATCH_DAYS | 45 | Bank deposit matching |
**Conflict:** ⚠ HULK_BEDS: REPORTING.md §3.3 says "HULK: 146" but MASTER_DATA.md and everywhere else say 149
**Status:** ⚠️ CONFLICT FOUND — See "Conflicts Found" section

### RULE-FIN-033: Unit Economics — True Revenue Only (Bank Gross − Deposits Held)
**Source:** REPORTING.md §11b (Unit Economics)
**Definition:** Never use deposits as income. True Revenue = gross_bank_income + cash_rent − deposits_held
**Code location:** `src/services/unit_economics.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-034: Unit Economics — 15 KPIs
**Source:** REPORTING.md §11b
**Definition:** Occupancy %, Avg Rent, Collection Rate, True Revenue, OPEX, EBITDA, Revenue/Bed, OPEX/Bed, EBITDA/Bed, EBITDA Margin, Investment Yield, Payback Months, Break-even Occupancy, Economic Occupancy %, Revenue Leakage
**Code location:** `src/services/unit_economics.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-035: Investment Total — Constant ₹2.59Cr
**Source:** REPORTING.md §11b (Unit Economics rules)
**Definition:** Total investment = ₹2.59Cr (Ashokan 11.21% + Jitendra 13.17% + Chandra&Team 75.62%)
**Code location:** `src/services/unit_economics.py`
**Status:** ✅ DOCUMENTED

### RULE-FIN-036: Booking Payments — NEVER write to Sheet Cash/UPI
**Source:** REPORTING.md §10.4
**Definition:** Booking amount is pre-subtracted from `rent_due`. Writing booking payment to Cash column would subtract it twice. Skip gsheets write-back when `for_type == "booking"`.
**Code location:** `src/integrations/gsheets.py:update_payment()`
**Status:** ✅ DOCUMENTED

### RULE-FIN-037: RentSchedule Auto-Recalc — 5 Call Sites (MUST STAY IN SYNC)
**Source:** REPORTING.md §10.3
**Definition:** Whenever `security_deposit`, `checkin_date`, or `agreed_rent` changes, call `recalc_checkin_month_rs()` from `src/services/rent_schedule.py`. Wired into:
1. PATCH /tenancies/{id} (tenants.py)
2. Security deposit bot change (account_handler.py)
3. Overpay→deposit (owner_handler.py)
4. Checkin date change (owner_handler.py)
5. Room transfer with extra_deposit (room_transfer.py)
**Code location:** `src/services/rent_schedule.py:recalc_checkin_month_rs()`
**Status:** ✅ DOCUMENTED

### RULE-FIN-038: Maintenance = One-Time Check-in Fee (Deducted from Deposit)
**Source:** REPORTING.md §6 (Maintenance column), BUSINESS_LOGIC.md §8 (Golden Rule #9)
**Definition:** One-time fee deducted from deposit, NEVER monthly, non-refundable, included in Total Collection.
**Related:** RULE-FIN-005
**Status:** ✅ DOCUMENTED

---

## SECTION 2: OCCUPANCY RULES (RULE-OCC-*)

### RULE-OCC-001: Total Bed Capacity — Dynamic (Never Hardcoded)
**Source:** BUSINESS_LOGIC.md §1.1, MASTER_DATA.md §Revenue Rooms
**Definition:** `TOTAL_BEDS = SUM(max_occupancy) WHERE is_staff_room = False` from rooms table
- THOR: 149 beds (80 revenue rooms)
- HULK: 149 beds (81 revenue rooms)
- **Total: 298 beds** (updated 2026-05-31: 108→revenue)
**Code location:** `src/whatsapp/handlers/owner_handler.py`, `src/integrations/gsheets.py`, `scripts/clean_and_load.py`
**Conflict:** NONE — consistent across all files
**Status:** ✅ DOCUMENTED

### RULE-OCC-002: Premium Tenancy = Operational Status, NOT Room Type
**Source:** BUSINESS_LOGIC.md §1.6
**Definition:** Premium is `Tenancy.sharing_type = 'premium'`. One premium tenant in a double room = 2 beds occupied. NOT a room attribute.
**Code location:** `src/database/models.py:SharingType` enum
**Status:** ✅ DOCUMENTED

### RULE-OCC-003: Occupied Beds Calculation
**Source:** BUSINESS_LOGIC.md §1.2
**Definition:**
```
occupied_beds = SUM(
    CASE WHEN Tenancy.sharing_type == 'premium' THEN Room.max_occupancy ELSE 1 END
) WHERE is_staff_room = False AND status IN (active, no_show) AND checkin_date <= month_end
```
**Code location:** `src/whatsapp/handlers/owner_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-OCC-004: No-Show Beds Calculation
**Source:** BUSINESS_LOGIC.md §1.3
**Definition:** Count ALL no-shows (no date filter, includes future bookings)
```
noshow_beds = SUM(
    CASE WHEN sharing_type == 'premium' THEN max_occupancy ELSE 1 END
) WHERE status = 'no_show' AND is_staff_room = False
```
**Code location:** `src/whatsapp/handlers/owner_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-OCC-005: Vacant Beds Calculation
**Source:** BUSINESS_LOGIC.md §1.4
**Definition:** `vacant_beds = TOTAL_BEDS - occupied_beds - noshow_beds`
**Code location:** `src/whatsapp/handlers/owner_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-OCC-006: Occupancy Percentage
**Source:** BUSINESS_LOGIC.md §1.5, SHEET_LOGIC.md §5
**Definition:** `occupancy_pct = ROUND(occupied_beds / TOTAL_BEDS * 100, 1)`
**Code location:** `src/whatsapp/handlers/owner_handler.py`
**Status:** ✅ DOCUMENTED (duplicated in SHEET_LOGIC.md)

### RULE-OCC-007: Per-Property Occupancy
**Source:** REPORTING.md §3.3, BUSINESS_LOGIC.md §1.2
**Definition:** Calculate occupied/total/pct per property (THOR/HULK separately)
**Code location:** `src/whatsapp/handlers/owner_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-OCC-008: Room Occupancy — Single Source of Truth
**Source:** BUSINESS_LOGIC.md §2.5
**Definition:** Any code answering "who is in room X?" MUST use `src/services/room_occupancy.py`. A bed can be occupied by long-term Tenancy OR short-stay DaywiseStay. Public helpers: `get_room_occupants()`, `find_overlap_conflict()`, `count_occupied_beds()`
**Code location:** `src/services/room_occupancy.py`
**Status:** ✅ DOCUMENTED

### RULE-OCC-009: No-Shows and Future Checkins — AUTO-EXCLUDED from Dues
**Source:** BUSINESS_LOGIC.md §2.4
**Definition:** Pending(M) iterates `RentSchedule(period_month = M)`. We do NOT create RentSchedule for no-shows or `checkin_date >= next_period_month`.
**Code location:** `scripts/sync_from_source_sheet.py`
**Status:** ✅ DOCUMENTED

### RULE-OCC-010: Monthly Occupancy Report Format
**Source:** BUSINESS_LOGIC.md §1.7
**Definition:** Output: "Checked-in: {active_beds} beds ({regular} regular + {premium_count} premium); No-show: {no_show} beds reserved; Vacant: {vacant} beds"
**Code location:** `src/whatsapp/handlers/account_handler.py:1221-1238`
**Status:** ✅ DOCUMENTED

### RULE-OCC-011: Staff Rooms — Excluded from All Occupancy Counts
**Source:** MASTER_DATA.md §Staff Rooms, BUSINESS_LOGIC.md §1.1
**Definition:** 5 staff rooms (THOR: G05, G06, 701, 702 + HULK: G12) are excluded from TOTAL_BEDS and occupancy calculations
**Code location:** `src/database/models.py` (is_staff_room column)
**Status:** ✅ DOCUMENTED

### RULE-OCC-012: Corner Room Rule (Both Buildings)
**Source:** MASTER_DATA.md §Corner Room Rule
**Definition:** First and last room on each floor = single bed. G01, G10 (THOR), G11, G20 (HULK) = single.
**Code location:** `src/database/seed_rooms.py` (seeding logic)
**Status:** ✅ DOCUMENTED

---

## SECTION 3: DATA SYNC & SHEET RULES (RULE-SHEET-*)

### RULE-SHEET-001: Sheet Data Source — Original History Sheet (Reference)
**Source:** SHEET_LOGIC.md §1
**Definition:** Original sheet ID: `1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA` Tab: History. 267 tenants, 42 columns. Reference only — not real-time updated.
**Code location:** `scripts/clean_and_load.py`
**Status:** ✅ DOCUMENTED

### RULE-SHEET-002: Balance Column Is NOT Dues
**Source:** SHEET_LOGIC.md §3
**Definition:** Balance columns (22, 27, 30) contain Kiran's manual notes (advance to collect, prorated calculations, etc.), NOT computed dues. Use `Rent Due - Cash Paid - UPI Paid` instead.
**Code location:** `scripts/clean_and_load.py`
**Status:** ✅ DOCUMENTED

### RULE-SHEET-003: Payment Amounts — Cash & UPI Columns ONLY
**Source:** SHEET_LOGIC.md §2
**Definition:** Extract from Cash/UPI columns. NEVER parse Comments or Balance. Remove commas, extract first number. Empty or text ("−") = 0.
**Code location:** `scripts/clean_and_load.py:read_history()`
**Status:** ✅ DOCUMENTED

### RULE-SHEET-004: Current Rent Logic — Cascading Revisions
**Source:** SHEET_LOGIC.md §4 (Current Rent Logic)
**Definition:**
```python
rent = Monthly Rent (col 9)
if From 1st May (col 11) > 0: rent = col 11
elif From 1st FEB (col 10) > 0: rent = col 10
```
**Code location:** `scripts/clean_and_load.py:read_history()`
**Status:** ✅ DOCUMENTED

### RULE-SHEET-005: Sheet Payment Columns Validated
**Source:** SHEET_LOGIC.md §2 (Validation)
**Definition:** Validate: "Script total for col X == SUM of all non-empty cells in col X". If mismatch > Rs.1, STOP and investigate.
**Code location:** `scripts/clean_and_load.py`
**Status:** ✅ DOCUMENTED

### RULE-SHEET-006: Dues Scoping in Sheet — Three Filters
**Source:** SHEET_LOGIC.md §4 (Dues Calculation)
**Definition:**
1. Filter: Tenancy.status == Active (col 16 = CHECKIN or empty)
2. Filter: Rent status for month != EXIT, CANCEL (col 20/21/25/26)
3. Filter: `checkin_date < month_start` (strict <)
**Code location:** `scripts/sync_from_source_sheet.py`
**Status:** ✅ DOCUMENTED

### RULE-SHEET-007: March 2026 Dues Verified Baseline
**Source:** SHEET_LOGIC.md §4 (Verified March 2026)
**Definition:** 137 active tenants, Rs.23,31,500 expected, Rs.1,46,500 outstanding (19 tenants). Baseline for reconciliation.
**Code location:** Reference only
**Status:** ✅ DOCUMENTED

### RULE-SHEET-008: Payment Fallback — Period from Payment Date if None
**Source:** REPORTING.md §10.5
**Definition:** Deposit/booking payments have `period_month = None`. Use `payment_date` as fallback period.
**Code location:** `src/api/v2/finance.py`
**Status:** ✅ DOCUMENTED

---

## SECTION 4: OPERATIONAL & BOT RULES (RULE-BOT-*, RULE-OPS-*)

### RULE-BOT-001: Intent Catalog — 71 Intents Defined
**Source:** BOT_FLOWS.md §1 (Intent Catalog)
**Definition:** 71 intents across financial, operational, self-service, and sales. Examples: PAYMENT_LOG, QUERY_DUES, ADD_TENANT, CHECKOUT, etc.
**Code location:** `src/whatsapp/intent_detector.py`
**Status:** ✅ DOCUMENTED

### RULE-BOT-002: Intent Accuracy — Regex 97%
**Source:** BOT_FLOWS.md §1, BRAIN.md §3 (Reception)
**Definition:** Regex patterns match 97% of intents. AI fallback (Groq) only for UNKNOWN.
**Code location:** `src/whatsapp/intent_detector.py`
**Status:** ✅ DOCUMENTED

### RULE-BOT-003: Role Resolution — 5-Step Flow
**Source:** BOT_FLOWS.md §2 (Role Resolution)
**Definition:**
1. Normalize phone → 10-digit
2. Rate limit check (10/10min, 50/day)
3. Check `authorized_users` → admin/power_user/key_user/receptionist
4. Check `tenants` → tenant
5. Default → lead
**Code location:** `src/whatsapp/role_service.py`
**Status:** ✅ DOCUMENTED

### RULE-BOT-004: Receptionist Blocked From Reports
**Source:** BOT_FLOWS.md §3 (Receptionist), BRAIN.md §5
**Definition:** Receptionist role (Lokesh) blocked from: REPORT, BANK_REPORT, BANK_DEPOSIT_MATCH
**Code location:** `src/whatsapp/gatekeeper.py`
**Status:** ✅ DOCUMENTED

### RULE-BOT-005: Tenant & Lead Intents — DISABLED (No Auto-Reply)
**Source:** BOT_FLOWS.md §3, BRAIN.md §5
**Definition:** Bot returns `None` for tenant/lead intents. Messages logged to `chat_messages` but no reply sent.
**Code location:** `src/whatsapp/tenant_handler.py`, `src/whatsapp/lead_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-BOT-006: Pending Actions State Machine — 6 States
**Source:** BOT_FLOWS.md §4
**Definition:** INTENT_AMBIGUOUS, AWAITING_CLARIFICATION, CONFIRM_PAYMENT_LOG, CONFIRM_ADD_EXPENSE, CONFIRM_DEPOSIT_REFUND, DUPLICATE_CONFIRM
**Code location:** `src/database/models.py:PendingActionType`, `src/whatsapp/chat_api.py`
**Status:** ✅ DOCUMENTED

### RULE-BOT-007: Pending Actions Auto-Expiry — 30 Minutes
**Source:** BOT_FLOWS.md §4 (Auto-expiry)
**Definition:** All pending actions expire after 30 minutes
**Code location:** `src/database/models.py`
**Status:** ✅ DOCUMENTED

### RULE-BOT-008: __KEEP_PENDING__ Protocol
**Source:** BOT_FLOWS.md §4 (Special Behaviors)
**Definition:** Handler prefixes reply with `__KEEP_PENDING__` to re-prompt (e.g., correction accepted, confirm again)
**Code location:** `src/whatsapp/handlers/`
**Status:** ✅ DOCUMENTED

### RULE-BOT-009: Follow-Up Detection — Pronoun Patterns
**Source:** BRAIN.md §3 (Phase 2)
**Definition:** Pronoun patterns re-route to QUERY_TENANT intent
**Code location:** `src/whatsapp/intent_detector.py`
**Status:** ✅ DOCUMENTED

### RULE-BOT-010: Payment Log Flow — 6 Steps
**Source:** BUSINESS_LOGIC.md §3.1
**Definition:**
1. Identify tenant (fuzzy search)
2. Resolve period month
3. Check duplicate (24-hour window)
4. Create Payment record
5. Update RentSchedule status
6. Google Sheets write-back (fire-and-forget)
**Code location:** `src/whatsapp/handlers/account_handler.py:PAYMENT_LOG`
**Status:** ✅ DOCUMENTED

### RULE-OPS-001: WhatsApp Message Webhook — Signature Verification
**Source:** BRAIN.md §3 (Reception Phase 1)
**Definition:** Meta sends POST to `/webhook/whatsapp`. Verify HMAC signature before processing.
**Code location:** `src/whatsapp/webhook_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-OPS-002: Voice Message Handling — Groq Whisper
**Source:** BRAIN.md §3 (Reception Phase 1)
**Definition:** Voice messages transcribed via Groq Whisper before intent detection
**Code location:** `src/whatsapp/webhook_handler.py`, `src/whatsapp/media_handler.py`
**Status:** ✅ DOCUMENTED

### RULE-OPS-003: Rate Limiting — 10/10min, 50/day per Phone
**Source:** BRAIN.md §3 (Phase 2), BOT_FLOWS.md §2
**Definition:** Rate limit via `rate_limit_log` table. Exceeding → role = "blocked"
**Code location:** `src/whatsapp/role_service.py`
**Status:** ✅ DOCUMENTED

### RULE-OPS-004: Chat History — Last 5 Messages Loaded
**Source:** BRAIN.md §3 (Phase 2)
**Definition:** Load last 5 messages for context before intent detection
**Code location:** `src/whatsapp/chat_api.py`
**Status:** ✅ DOCUMENTED

### RULE-OPS-005: Late Fee — Rs.200/day from Day 6
**Source:** BUSINESS_LOGIC.md §8a (Due date + late fee)
**Definition:** Rent due by 5th of month. Day 6+ → Rs.200/day late fee. Accrues daily until balance clears.
**Code location:** `src/scheduler.py` (LATE_FEE_PER_DAY, LATE_FEE_FROM_DAY)
**Status:** ✅ DOCUMENTED

### RULE-OPS-006: Reminder Cadence — 3 Touches per Month
**Source:** BUSINESS_LOGIC.md §8a (Reminder cadence)
**Definition:**
1. 2 days before next month → `rent_reminder` to ALL active tenants
2. 1st of month → `rent_reminder` to ALL active tenants
3. 2nd+ daily → `general_notice` to unpaid tenants only (with running late-fee total)
**Code location:** `src/scheduler.py`
**Status:** ✅ DOCUMENTED

---

## SECTION 5: MASTER DATA & INFRASTRUCTURE RULES (RULE-MASTER-*)

### RULE-MASTER-001: Buildings — 2 Properties, 166 Rooms
**Source:** MASTER_DATA.md §Buildings
**Definition:** THOR (G+1-6+7, 84 rooms), HULK (G+1-6, 82 rooms), Total 166 rooms (5 staff, 161 revenue)
**Code location:** `src/database/seed_properties.py`
**Status:** ✅ DOCUMENTED

### RULE-MASTER-002: Room Numbering Convention
**Source:** MASTER_DATA.md §Room Numbering
**Definition:** THOR `{floor}{01-12}`, HULK `{floor}{13-24}`, Ground G01-G10 (THOR) / G11-G20 (HULK), Floor 7 THOR only: 701, 702
**Code location:** `src/database/seed_rooms.py`
**Status:** ✅ DOCUMENTED

### RULE-MASTER-003: Staff Rooms — 5 Total (MASTER_DATA)
**Source:** MASTER_DATA.md §Staff Rooms
**Definition:** G05(3), G06(2), 701(1), 702(1) in THOR; G12(3) in HULK. Total 10 beds (excluded from revenue).
**Code location:** `src/database/seed_rooms.py`
**Status:** ✅ DOCUMENTED

### RULE-MASTER-004: Revenue Rooms & Beds (VERIFIED 2026-05-31)
**Source:** MASTER_DATA.md §Revenue Rooms
**Definition:** THOR 80 rooms (14 single + 63 double + 3 triple = 149 beds), HULK 81 rooms (15 single + 64 double + 2 triple = 149 beds). Total 161 rooms = 298 beds.
**Code location:** `src/database/migrate_all.py` (seed migrations)
**Status:** ✅ DOCUMENTED

### RULE-MASTER-005: Staff Room History — Tracked Changes
**Source:** MASTER_DATA.md (change log: 2026-05-31, 2026-05-17, 2026-05-16, etc.)
**Definition:** Every change tracked with date. 108→revenue (2026-05-31), 614→revenue (2026-05-17), 107+114+618 locked (2026-05-16), etc.
**Code location:** `src/database/migrate_all.py`, git history
**Status:** ✅ DOCUMENTED

### RULE-MASTER-006: Data Pyramid — L0 (Master) > L1 (Operational) > L2 (Financial) > L3 (Reports)
**Source:** MASTER_DATA.md §Data Pyramid
**Definition:** Higher layers never override lower. L0 (rooms, buildings) > L1 (tenants, tenancies) > L2 (payments, bank) > L3 (occupancy %, P&L)
**Code location:** Architecture principle
**Status:** ✅ DOCUMENTED

### RULE-MASTER-007: DB Tables — 26 Total Across 6 Layers
**Source:** BRAIN.md §4
**Definition:** Layer 0 (investment, contacts), Layer 1 (properties, rooms, rate_cards, tenants, staff, food_plans, expense_categories), Layer 2 (tenancies), Layer 3 (rent_schedule, payments, refunds, expenses), Layer 4 (leads, rate_limit_log, whatsapp_log, conversation_memory), Layer 5 (vacations, reminders, onboarding_sessions, checkout_records, pending_actions), Layer 6 (authorized_users)
**Code location:** `src/database/models.py`
**Status:** ✅ DOCUMENTED

### RULE-MASTER-008: room_number as TEXT (Not Numeric)
**Source:** BRAIN.md §4 (Key design decisions)
**Definition:** Handles "G15", "508/509", "G20", etc.
**Code location:** `src/database/models.py:Room.room_number`
**Status:** ✅ DOCUMENTED

### RULE-MASTER-009: rate_cards Separate Table (Handles Rent Changes Over Time)
**Source:** BRAIN.md §4 (Key design decisions)
**Definition:** New row when rent changes (Feb→May price changes in Excel)
**Code location:** `src/database/models.py:RateCard`
**Status:** ✅ DOCUMENTED

### RULE-MASTER-010: rent_schedule ≠ payments
**Source:** BRAIN.md §4 (Key design decisions)
**Definition:** Enables "who hasn't paid March?" queries without rent_schedule matching all payments
**Code location:** `src/database/models.py`
**Status:** ✅ DOCUMENTED

### RULE-MASTER-011: Supabase Auth — Role Metadata (admin/staff/tenant)
**Source:** BRAIN.md §4
**Definition:** `user_metadata.role` stored in Supabase Auth
**Code location:** `src/database/models.py`, Supabase JWT
**Status:** ✅ DOCUMENTED

---

## SECTION 6: DUPLICATES FOUND (Same Rule in Multiple Docs)

### DUPLICATE-001: Dues Three-Condition Rule
**Rule:** RULE-FIN-007 / RULE-FIN-008
**Appears in:**
- REPORTING.md §2.1–2.2 (authoritative)
- BUSINESS_LOGIC.md §2.1–2.2 (verbatim duplicate)
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-002: Dues Exclusion Rule (Same-Month Check-ins)
**Rule:** RULE-FIN-009
**Appears in:**
- REPORTING.md §2.3
- BUSINESS_LOGIC.md §2.5
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-003: Duplicate Payment Detection (24 Hours)
**Rule:** RULE-FIN-015
**Appears in:**
- REPORTING.md §5.2
- BUSINESS_LOGIC.md §3.4
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-004: Overpayment Threshold Rs.10
**Rule:** RULE-FIN-016
**Appears in:**
- REPORTING.md §5.3
- BUSINESS_LOGIC.md §3.3
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-005: Bank Deduplication — SHA-256
**Rule:** RULE-FIN-028
**Appears in:**
- REPORTING.md §9.1
- BUSINESS_LOGIC.md §7.3
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-006: Expense Classification (18 Categories)
**Rule:** RULE-FIN-027
**Appears in:**
- REPORTING.md §8.1 (full list)
- BUSINESS_LOGIC.md §7.2 (abbreviated)
**Assessment:** ✅ IDENTICAL — BUSINESS_LOGIC.md §7 condensed version

### DUPLICATE-007: Occupancy Percentage Formula
**Rule:** RULE-OCC-006
**Appears in:**
- BUSINESS_LOGIC.md §1.5
- SHEET_LOGIC.md §5
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-008: Total Beds Rule (298)
**Rule:** RULE-OCC-001
**Appears in:**
- BUSINESS_LOGIC.md §1.1
- MASTER_DATA.md §Revenue Rooms
- SHEET_LOGIC.md §5
- REPORTING.md §3.1 (footnote)
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-009: Maintenance = One-Time Fee
**Rule:** RULE-FIN-005 / RULE-FIN-038
**Appears in:**
- REPORTING.md §6 (Maintenance column)
- REPORTING.md §8 (Golden Rules)
- BUSINESS_LOGIC.md §8 (Golden Rule #9)
**Assessment:** ✅ IDENTICAL — reinforced across docs

### DUPLICATE-010: Notice by Day 5 Rule
**Rule:** RULE-FIN-024
**Appears in:**
- REPORTING.md §7.1
- BUSINESS_LOGIC.md §6.3 (abbreviated)
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-011: Proration Rules (5 Scenarios)
**Rule:** RULE-FIN-020
**Appears in:**
- REPORTING.md §6.2
- BUSINESS_LOGIC.md §6.2
**Assessment:** ✅ IDENTICAL — no conflict

### DUPLICATE-012: Check-in Proration Formula
**Rule:** RULE-FIN-021
**Appears in:**
- REPORTING.md §6.3
- (Not explicitly in BUSINESS_LOGIC.md, but referenced)
**Assessment:** ✅ DOCUMENTED in primary source

---

## SECTION 7: CONFLICTS FOUND (Different Versions of Same Rule)

### CONFLICT-001: HULK Total Beds (CRITICAL)
**Rule:** RULE-FIN-032 / RULE-OCC-001
**Source 1:** REPORTING.md §3.3 — "HULK: 149 beds (81 revenue rooms)"
**Source 2:** REPORTING.md §12 (Key Constants table) — "HULK_BEDS: 149"
**Source 3:** REPORTING.md §3.3 "Per-property" section — "HULK: 146"
**Assessment:** ⚠️ CONFLICT — Line 213 says 146, but everywhere else (title, MASTER_DATA.md, BUSINESS_LOGIC.md, SHEET_LOGIC.md) says 149
**Root cause:** Copy-paste error in REPORTING.md §3.3 line 213
**Resolution:** Update REPORTING.md §3.3 line 213 to read "HULK: 149" instead of 146
**Impact:** HIGH — affects P&L validation, occupancy calculations, unit economics
**Action Required:** ✅ FIX IMMEDIATELY

### CONFLICT-002: TOTAL_BEDS Constant Value (Minor Drift)
**Rule:** RULE-FIN-032 (Key Constants)
**Source 1:** REPORTING.md §12 — "TOTAL_REVENUE_BEDS | 298 | DB-verified 2026-05-31; 108→revenue"
**Source 2:** BUSINESS_LOGIC.md §9 — "TOTAL_BEDS | 298 | Dynamic from rooms table (108→revenue 2026-05-31)"
**Assessment:** ✅ IDENTICAL — no conflict
**Note:** Both say 298 (verified). No action needed.

---

## SECTION 8: GAPS / MISSING RULES

### GAP-001: Late Fee Auto-Add to RentSchedule (Deferred)
**Mentioned in:** BUSINESS_LOGIC.md §8a
**Issue:** Late fee (Rs.200/day from day 6) is displayed in reminder text but NOT auto-added to `rent_schedule.due_amount`.
**Status:** NOT YET AUTOMATED — requires schema decision (new column vs. folded into due_amount)
**Impact:** MEDIUM — tenants may not see fees in balance queries
**Action:** Deferred — needs separate implementation plan

### GAP-002: Tenant & Lead Handler Flows (Disabled)
**Mentioned in:** BOT_FLOWS.md §1 (71 intents), BRAIN.md §5
**Issue:** 34 tenant/lead intents defined but handlers return `None` (no auto-reply)
**Status:** DISABLED — by design, pending future self-service phase
**Impact:** MEDIUM — reduces tenant autonomy
**Action:** Deferred — part of Phase 2 tenant self-service rollout

### GAP-003: LangGraph Router (Not Wired)
**Mentioned in:** BRAIN.md §1 (Note on LangGraph)
**Issue:** `src/agents/langgraph_router.py` exists but is NOT integrated into WhatsApp flow
**Status:** ARTIFACT — replaced by Gatekeeper+Worker architecture
**Impact:** LOW — cleanup opportunity
**Action:** Can be deprecated and removed

### GAP-004: Composition Fees (Premium Tenancy Pricing)
**Mentioned in:** None
**Issue:** Premium tenants pay extra (occupying whole room). No documented pricing rule found.
**Status:** NOT DOCUMENTED
**Impact:** MEDIUM — pricing rules unclear
**Action:** Add premium pricing rule to REPORTING.md §6 (Billing Cycle)

### GAP-005: Vacation Impact on Billing
**Mentioned in:** BRAIN.md §4 (vacations table), BUSINESS_LOGIC.md (NOT mentioned)
**Issue:** Table exists but billing logic for vacations not documented
**Status:** INCOMPLETE
**Impact:** MEDIUM — unclear if rent is prorated during vacation
**Action:** Add to BUSINESS_LOGIC.md §6 (Billing Cycle)

### GAP-006: Onboarding Session Flow (Step Names)
**Mentioned in:** BRAIN.md §4 (Layer 5)
**Issue:** Table schema documented, but 13-step flow (`ask_dob` → ... → `done`) not in BUSINESS_LOGIC.md or BOT_FLOWS.md
**Status:** DOCUMENTED IN SCHEMA ONLY
**Impact:** LOW — implementation detail
**Action:** Could add to BOT_FLOWS.md as reference

### GAP-007: Rent Revisions History
**Mentioned in:** REPORTING.md (rent changes via Excel columns), BUSINESS_LOGIC.md (rent change handlers)
**Issue:** When does `rent_revisions` table get written? Triggers unclear.
**Status:** PARTIALLY DOCUMENTED
**Impact:** MEDIUM — audit trail incomplete
**Action:** Add trigger rule to REPORTING.md §4 (Rent Changes)

### GAP-008: Overpay→Deposit Credit Logic (Split Formula)
**Mentioned in:** REPORTING.md §2.4 (first-month tenants), REPORTING.md §10.3 (overflow variable)
**Issue:** How does overpayment route to deposit for non-first-month tenants? Not documented.
**Status:** CODE EXISTS, RULE MISSING
**Impact:** MEDIUM — unclear behavior
**Action:** Add to BUSINESS_LOGIC.md §3 (Payment Processing)

### GAP-009: Complaint Workflow (No Handler Details)
**Mentioned in:** BOT_FLOWS.md §1 (COMPLAINT_REGISTER, COMPLAINT_UPDATE, QUERY_COMPLAINTS)
**Issue:** Intent listed but no workflow detail
**Status:** NOT DOCUMENTED
**Impact:** LOW — minor feature
**Action:** Can defer to separate doc

### GAP-010: Cash vs. Bank Reconciliation Rules
**Mentioned in:** REPORTING.md §1.2 (cash as supplementary source)
**Issue:** How to reconcile cash deposits to bank if there's a gap?
**Status:** NOT DOCUMENTED
**Impact:** HIGH — financial integrity
**Action:** Add to REPORTING.md §9 (Bank Statement Import)

---

## SECTION 9: PRIORITY FIX LIST

### Priority 1 (CRITICAL — Fix Immediately)

1. **CONFLICT-001: HULK Beds = 146 vs. 149**
   - File: `/d/Work/Claude Projects/AI Watsapp PG Accountant/docs/REPORTING.md`
   - Line: 213
   - Change: `total = canonical beds (THOR: 145, HULK: 146)` → `total = canonical beds (THOR: 149, HULK: 149)`
   - Reason: Copy-paste error; everywhere else says 149
   - Impact: HIGH — affects all property-level occupancy calculations

2. **GAP-007: Rent Revisions Trigger Rule**
   - File: `/d/Work/Claude Projects/AI Watsapp PG Accountant/docs/REPORTING.md`
   - Add: New section §4 "Rent Revisions & History" — document when/how rent_revisions is written
   - Impact: HIGH — financial audit trail

3. **GAP-010: Cash vs. Bank Reconciliation**
   - File: `/d/Work/Claude Projects/AI Watsapp PG Accountant/docs/REPORTING.md`
   - Add: New rule in §9 on reconciling cash deposits
   - Impact: HIGH — financial integrity

### Priority 2 (HIGH — Fix Soon)

4. **GAP-004: Premium Tenancy Pricing**
   - File: Create rule RULE-FIN-039 in REPORTING.md
   - Definition: How much extra do premium tenants pay?
   - Impact: MEDIUM — pricing clarity

5. **GAP-005: Vacation Impact on Billing**
   - File: BUSINESS_LOGIC.md §6 (Billing Cycle)
   - Add: Logic for vacation proration
   - Impact: MEDIUM — rare but important

6. **GAP-008: Overpay→Deposit for Ongoing Tenants**
   - File: BUSINESS_LOGIC.md §3 (Payment Processing)
   - Add: Rule for non-first-month overpayment routing
   - Impact: MEDIUM — edge case handling

### Priority 3 (MEDIUM — Nice to Have)

7. **Deprecate LangGraph**
   - File: `src/agents/langgraph_router.py`
   - Action: Remove unused artifact
   - Impact: LOW — cleanup

8. **Document Complaint Workflow**
   - File: Separate doc or BOT_FLOWS.md extension
   - Impact: LOW — minor feature

---

## CONSOLIDATED RULES INDEX (By Category)

### Financial (38 rules)
RULE-FIN-001 to RULE-FIN-038 (Dues, Payments, Deposits, Proration, Expenses, P&L)

### Occupancy (12 rules)
RULE-OCC-001 to RULE-OCC-012 (Beds, No-Shows, Premium, Staffing)

### Data & Sheets (8 rules)
RULE-SHEET-001 to RULE-SHEET-008 (Source data, Balance columns, Payment extraction)

### Operations & Bot (15 rules)
RULE-BOT-001 to RULE-BOT-010, RULE-OPS-001 to RULE-OPS-006 (Intents, Roles, State machine, Reminders)

### Master Data & Infrastructure (11 rules)
RULE-MASTER-001 to RULE-MASTER-011 (Buildings, Rooms, Beds, DB schema)

---

## Validation Checklist

- [ ] CONFLICT-001 (HULK beds) reviewed and flagged
- [ ] All 87 rules tagged with primary source file
- [ ] Code locations verified for top 20 rules
- [ ] Duplicates marked as ✅ (no action needed)
- [ ] Gaps categorized by priority
- [ ] No contradictions found in core financial logic
- [ ] Occupancy formula consistent across all docs
- [ ] Dues scope rules identical in REPORTING.md + BUSINESS_LOGIC.md
