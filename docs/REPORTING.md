# Cozeevo Financial Reporting & Business Logic

> **This is the SINGLE SOURCE OF TRUTH for all financial calculations.**
> Claude MUST refer to this file before generating any financial report or answering financial queries.
> If logic here conflicts with code, THIS FILE wins. Fix the code.

---

## 1. P&L REPORT FORMAT

### 1.1 Cost (Expense) Categories — Chart of Accounts

Months as columns, categories as rows. All amounts in INR.

| # | Account / Category | Maps to (bank classification) |
|---|---|---|
| 1 | Milk | Food & Groceries |
| 2 | Curd | Food & Groceries |
| 3 | Paneer | Food & Groceries |
| 4 | Chicken | Food & Groceries |
| 5 | Eggs | Food & Groceries |
| 6 | Groceries | Food & Groceries |
| 7 | Vegetables | Food & Groceries |
| 8 | Salaries | Staff & Labour |
| 9 | Current Bill (Electricity) | Electricity |
| 10 | Water Bill | Water |
| 11 | Police Fees | Govt & Regulatory |
| 12 | Waste Disposal Fees | Govt & Regulatory |
| 13 | Maintenance Cost | Maintenance & Repairs |
| 14 | House Keeping Items | Cleaning Supplies |
| 15 | Miscellaneous | Other Expenses |
| 16 | Gas Bill | Fuel & Diesel |
| 17 | Internet Bill | Internet & WiFi |
| 18 | Property Rent | Property Rent |
| 19 | Furniture & Fittings | Furniture & Fittings |
| 20 | Marketing | Marketing |
| 21 | Shopping & Supplies | Shopping & Supplies |
| 22 | IT & Software | IT & Software |
| 23 | Bank Charges | Bank Charges |
| 24 | Tenant Deposit Refund | Tenant Deposit Refund |
| 25 | Non-Operating | Non-Operating |
| | **Total Cost** | |

**Note:** Items 1-7 (Milk through Vegetables) are sub-items of "Food & Groceries" in bank statements.
Bank data cannot split these — they will be grouped as "Food & Kitchen" until Kiran provides item-level data from a separate source (Excel/notebook).

### 1.2 Income Categories (updated 2026-05-06 — bank-primary)

**HARD RULE:** Bank statement credits = primary income source. DB payments = supplementary (cash only).

| # | Account / Category | Source | Notes |
|---|---|---|---|
| 1 | Bank — UPI batch settlements (THOR) | `bank_transactions` WHERE category='UPI Batch' AND account_name='THOR' | Merchant QR batch settlements |
| 2 | Bank — individual direct payments + NEFT (THOR) | `bank_transactions` WHERE category IN ('UPI Direct','NEFT') AND account_name='THOR' | Individual UPI + NEFT |
| 3 | HULK — UPI settlements | `bank_transactions` WHERE account_name='HULK' | HULK building bank account |
| 4 | THOR → HULK reclassification | Explicit −₹5L row in THOR column | Internal transfer — shown for transparency, net zero |
| 5 | HULK ← THOR reclassification | Explicit +₹5L row in HULK column | Mirrors row 4 |
| 6 | Cash (physical, not deposited) | `payments` WHERE payment_mode='cash' AND for_type='rent' AND is_void=false | Supplement only — cash NOT in bank |
| | **Total Gross Inflows** | Sum of rows 1–6 | |
| | **Less: Security Deposits (refundable)** | `tenancies.security_deposit` WHERE status='active' AND check-in month = target month | Must return at exit — excluded from revenue |
| | **True Rent Revenue** | Gross Inflows − Security Deposits | Operating income base |

Maintenance fees (non-refundable) are retained income and stay in Gross Inflows. Do NOT deduct them.

Capital contributions (owner equity injections) are shown separately — NOT in income.

### 1.3 Report Layout (updated 2026-05-06)

```
HEADER:  [blank] | Oct'25 | Nov'25 | Dec'25 | Jan'26 | Feb'26 | Mar'26 | Apr'26 | TOTAL

1. INCOME
   Bank — UPI batch settlements (THOR)
   Bank — individual direct + NEFT (THOR)
   HULK — UPI settlements
   THOR — transferred to HULK acct (reclassification)     [-5L on THOR col]
   HULK — received from THOR acct (reclassification)      [+5L on HULK col]
   Cash (physical, not deposited to bank)
   ─────────────────────────────────────
   Total Gross Inflows
   Less: Security Deposits Received (refundable)           [italic, negative]
   ─────────────────────────────────────
   True Rent Revenue (excl. refundable deposits)           [bold green]

2. CAPITAL CONTRIBUTIONS (not P&L — owner equity injections)
   Owner startup — Lakshmi SBI to Yes Bank (Oct 2025)
   Kiran top-up transfer (Jan 2026)

3. OPERATING EXPENSES
   [all opex lines]
   EXCLUDED FROM OPEX (balance sheet items — not costs):   [italic section]
     Tenant Deposit Refund
     Loan Repayment / Transfers (non-op)
   ─────────────────────────────────────
   Total Operating Expenses

4. OPERATING PROFIT (EBITDA) = True Rent Revenue − Opex   [bold]
   Operating Margin % (on True Revenue)

5. CAPEX — ONE-TIME INVESTMENTS
   Furniture & Fittings
   8 Ball Pool Equipment
   ─────────────────────────────────────
   Total CAPEX

6. NET PROFIT AFTER CAPEX                                  [bold]
   Net Margin % (on True Revenue)

7. DEPOSITS HELD
   Security Deposits — refundable (must return at exit)
   Maintenance Fee retained (non-refundable)
   Net working capital owed to tenants

8. CASH POSITION (month-end)
   Bank closing balance THOR + HULK
   Net deposits owed (sec collected − sec refunded)
   True free cash = Bank − Net deposits owed

9. ⚠ ITEMS NEEDING REVIEW
```

### 1.4 Data Sources (updated 2026-05-06)

| Data | Primary Source | Notes |
|---|---|---|
| Bank income (THOR) | `bank_transactions` WHERE account_name='THOR' | Uploaded via Finance page CSV upload |
| Bank income (HULK) | `bank_transactions` WHERE account_name='HULK' | Uploaded via Finance page CSV upload |
| Cash income | `payments` WHERE payment_mode='cash' AND for_type='rent' | Physical cash not in bank |
| Security deposits | `tenancies.security_deposit` WHERE status='active' | Active tenants only, by check-in month |
| Expense classification | `src/rules/pnl_classify.py` | Auto-classify bank debits |
| Verified canonical P&L | `src/reports/pnl_builder.py` | Hardcoded Oct'25–Apr'26; served by `/finance/pnl/excel` |
| Live P&L (recomputed) | `src/api/v2/finance.py:_build_pnl_excel()` | Picks up new uploads; served by `/finance/pnl/live` |
| JSON API (PWA) | `src/api/v2/finance.py:get_pnl()` | Powers Finance page dashboard cards |

---

## 2. DUES CALCULATION (LOCKED)

### 2.1 Core Rule

Any dues query for month M MUST only include tenants who:

1. `Tenancy.status == active` (NOT no_show, NOT checkout, NOT cancelled)
2. `Tenancy.checkin_date < date(Y, M, 1)` — checked in BEFORE month start (strict `<`)
3. `RentSchedule.period_month == date(Y, M, 1)` — only THIS month's dues (not cumulative)
4. `RentSchedule.status IN (pending, partial)` — not already paid/waived

### 2.2 Outstanding Formula

```
FOR EACH qualifying tenant:
  paid = SUM(Payment.amount WHERE tenancy_id = T AND period_month = M AND is_void = False)
  outstanding = (rent_due + maintenance_due + adjustment) - paid
  IF outstanding > 0: include in dues list
```

### 2.3 Why `checkin_date < from_date` (strict less-than)

New arrivals in month M haven't had time to pay yet. They're not "overdue" — they just checked in. Only chase tenants who were already there before the month started.

### 2.4 Applied In (2 places — must be consistent)

1. `account_handler.py` → `_report()` function
2. `account_handler.py` → `_query_dues()` function

---

## 3. OCCUPANCY CALCULATION

### 3.1 Capacity (Canonical — verified from DB 2026-04-08)

```
THOR: 147 beds (79 revenue rooms)
HULK: 150 beds (81 revenue rooms)
Total: 297 beds  ← updated 2026-05-09; DB verified

Staff rooms EXCLUDED (6 rooms, updated 2026-05-09):
  THOR: G05(3), G06(2), 108(2), 701(1), 702(1)
  HULK: G12(3)
  — 114 and 618 moved to revenue 2026-04-26
  — G20 → revenue 2026-05-09 (Chandraprakash); 107 → revenue 2026-05-09 (Samruddhi Thanwar)
```

### 3.2 Formula

```
occupied_beds = COUNT(Tenancy WHERE status IN [active, no_show] AND Room.is_staff_room = False)
vacant_beds = TOTAL_REVENUE_BEDS - occupied_beds
occupancy_pct = ROUND(occupied_beds / TOTAL_REVENUE_BEDS * 100, 1)
```

### 3.3 Property-Level

```
Per property (THOR/HULK):
  occupied = COUNT(tenancies for that property_id)
  total = canonical beds (THOR: 145, HULK: 146)
  pct = ROUND(occupied / total * 100, 1)
  vacant = total - occupied
```

---

## 4. COLLECTION RATE

### 4.1 Formula

```
total_due = SUM(rent_due + maintenance_due + adjustment)
            WHERE period_month = M, Tenancy.status = active, Tenancy.checkin_date < M_start

dues_outstanding = (calculated per Section 2)

collected = total_due - dues_outstanding
collection_pct = ROUND(collected / total_due * 100)  IF total_due > 0 ELSE 0
```

### 4.2 Total Collection (monthly report)

```
Total Collection = Rent Collected + Maintenance Collected
  - Rent Collected = SUM(payments WHERE for_type = 'rent', period_month = M, is_void = False)
  - Maintenance Collected = SUM(maintenance_fee) for tenancies with checkin_date in month M

EXCLUDES: Security deposits (shown separately)
INCLUDES: Maintenance fees (non-refundable, part of revenue)
```

### 4.3 Security Deposit Metrics

**Monthly deposit received (for report):**
```
deposit_received_month = SUM(payments WHERE for_type = 'deposit', payment_date in month M, is_void = False)
  — Shows new deposits collected that month only
  — Separate line item in report, NOT included in Total Collection
```

**Total security deposit held (query: "total deposit held"):**
```
total_deposit_held = SUM(security_deposit) for ALL tenancies WHERE status = 'active'
  — Full amount held from the start of each tenancy
  — Includes maintenance portion (maintenance is non-refundable but deposit is held in full)
```

**Net refundable deposit (query: "refundable deposit"):**
```
net_refundable = SUM(security_deposit - maintenance_fee) for ALL tenancies WHERE status = 'active'
  — What we'd actually return if everyone left today
  — security_deposit includes maintenance; maintenance is deducted at exit
```

**Current values (as of 2026-04-08):**
- Total deposit held: 32,67,425
- Maintenance (non-refundable): 10,12,200
- Net refundable: 22,55,225
- Active tenants: 220

---

## 5. PAYMENT PROCESSING

### 5.1 Payment Status Determination

```
total_paid = SUM(all non-void payments for this tenancy + period_month)
effective_due = rent_due + adjustment

IF total_paid >= effective_due → status = "paid"
ELSE IF total_paid > 0         → status = "partial"
ELSE                           → status = "pending"
```

### 5.2 Duplicate Detection

Same (tenancy_id, amount, period_month, is_void=False) within 24 hours → flag as potential duplicate.

### 5.3 Overpayment Threshold

Ignore overpayments under Rs 10 (rounding noise). Above Rs 10: prompt user for action (advance / deposit / clarify).

### 5.4 Void Payment

- Set `is_void = True` (NEVER delete payment records)
- Recalculate RentSchedule status using remaining non-void payments

---

## 6. BILLING CYCLE & PRORATION

### 6.1 Billing Cycle Types

| Type | Example | First month | Ongoing | How stored |
|------|---------|-------------|---------|------------|
| **Standard (1st-to-1st)** | Checkin Jan 15 | Prorated: rent x 17/31 | Full rent on 1st | `billing_cycle_day` = 1 (default) |
| **Custom (Nth-to-Nth)** | Checkin Mar 6, cycle 6th-to-6th | Full rent (first billing month is complete) | Full rent on 6th | `tenancy.notes` = "billing cycle 6th to 6th", `rent_schedule.due_date` = 6th |

**Standard tenants (majority):** first month prorated based on checkin day, then full rent from next month.
**Custom cycle tenants:** first month is full (their billing cycle starts on checkin day), full rent continues on their cycle day.

### 6.2 Proration Rules — When It Applies

| Scenario | Proration? | Calculation |
|----------|-----------|-------------|
| **New checkin mid-month (standard cycle)** | YES — first month only | `INT(rent * days_remaining / days_in_month)` rounds DOWN |
| **New checkin mid-month (custom cycle)** | NO — full rent | Full `agreed_rent` (billing month starts on checkin day) |
| **Normal checkout (notice given, end of month)** | NO | Full month charged |
| **Early exit (leaves before agreed date)** | NO — no refund | Full month charged, no refund for unused days |
| **Overstay (stays past agreed checkout)** | YES — extra days only | `INT(rent * extra_days / days_in_month)` rounds DOWN |
| **Ongoing months** | NO | Full `agreed_rent` every month |

### 6.3 Check-in Proration Formula (standard cycle only)

```
days_remaining = days_in_month - checkin_day + 1  (inclusive of checkin day)
prorated_rent = INT(rent * days_remaining / days_in_month)  (rounds DOWN)
```

Example: Rent Rs.13,000, checkin Jan 15, January has 31 days
→ days_remaining = 31 - 15 + 1 = 17
→ prorated = INT(13000 * 17 / 31) = INT(7129) = Rs.7,129

### 6.4 Overstay Proration Formula

```
extra_days = actual_checkout_day - agreed_checkout_day
prorated_extra = INT(rent * extra_days / days_in_month)  (rounds DOWN)
```

Only applies when tenant stays PAST their agreed checkout date. Charged on top of the full months already billed.

### 6.5 Checkout Rules — NO Proration at Exit

| Checkout scenario | Charge | Deposit |
|-------------------|--------|---------|
| Notice by 5th → leave end of month | Full month | Refunded (minus damages/dues) |
| Notice after 5th → leave end of month | Full month | **Forfeited** |
| Leaves before agreed checkout (sudden exit) | Full month charged, **no refund** for unused days | Forfeited |
| Stays past agreed checkout (overstay) | Full month + prorated extra days | Held until settlement |

**Key principle:** We never refund partial months on exit. If tenant paid for the month and leaves early, that's their choice. Proration only helps tenants (first month, overstay) — it never reduces what they owe for a committed month.

---

## 7. DEPOSIT & SETTLEMENT

### 7.1 Notice Period Rule

```
NOTICE_BY_DAY = 5

IF notice given by 5th of month → deposit refundable, stay ends last day of that month
IF notice after 5th             → deposit forfeited, tenant charged until end of NEXT month
```

### 7.2 Settlement Formula

```
net_refund = security_deposit - outstanding_rent - outstanding_maintenance - damages

IF net_refund < 0 → tenant still owes money
IF net_refund > 0 → refund this amount to tenant
```

---

## 8. EXPENSE CLASSIFICATION RULES

### 8.1 Processing Order (first match wins)

```
1. Non-Operating       — "bharathi prabhakaran", "shalu.pravi" (MUST be first)
2. Property Rent       — "vakkal", "sravani", "r suma"
3. Electricity         — "bescom", "eb bill"
4. Water               — "bwssb", "water tanker", "barrels"
5. IT & Software       — "hostinger", "think straight"
6. Internet & WiFi     — "airwire", "wifi", "broadband"
7. Furniture           — "wakefit", "bedsheet", "shoe rack", "grace trader"
8. Food & Groceries    — "virani", "vyapar", "cylinder", "chicken", "zepto", "blinkit"
9. Fuel & Diesel       — "dg rent", "deepu.1222", "petrol"
10. Staff & Labour     — "salary", "arjun", "phiros", "lokesh", "housekeeping"
11. Govt & Regulatory  — "bbmp", "edcs", "directorate", "gst"
12. Deposit Refund     — "booking cancellation", "refund", "exit refund"
13. Marketing          — "logo tshirt", "sun board", "flyers", "find my pg"
14. Cleaning Supplies  — "garbage", "phenyl", "mop"
15. Shopping           — "amazon", "flipkart", "bharatpe"
16. Maintenance        — "plumbing", "electrician", "repair"
17. Bank Charges       — "debit card", "imps", "rtgs", "neft"
18. Other Expenses     — catch-all for unmatched
```

### 8.2 Unclassified Vendors (need Kiran's input)

- `arunphilip25` — ???
- `tpasha638` — ???
- `M036TPQEK` — ???
- `akhilreddy007420` — ???
- `volipi.l` — ???
- `ksshyamreddy` — ???
- CHQ Rs 82K Nov — ???

---

## 9. BANK STATEMENT IMPORT

### 9.1 Deduplication

```
unique_hash = SHA256(txn_date | description[:80].lower() | amount.round(2))
Re-uploading same statement is safe — duplicates are skipped.
```

### 9.2 Source Files

- `2025 statement.xlsx` — Yes Bank, Oct-Dec 2025
- `2026 statment.xlsx` — Yes Bank, Jan-Mar 2026
- Account: 124563400000961, LAKSHMI GORJALA

### 9.3 Excel Format (Yes Bank)

```
Column A: Txn Date (dd/mm/yyyy or datetime)
Column B: Value Date
Column C: Description
Column D: Cheque/Ref No
Column E: Withdrawal (expense)
Column F: Deposit (income)
Column G: Balance
```

---

## 10. GOOGLE SHEET COLLECTION ROW — OWNERSHIP RULES (CRITICAL)

These rules were established 2026-04-28 after a three-layer bug caused Total Dues to show Rs.4,04,266 instead of Rs.88,766. Violating any of these rules will corrupt the sheet.

### 10.1 Who owns what

| Surface | Owns | Must NOT write |
|---------|------|----------------|
| `sync_sheet_from_db.py` | COLLECTION row (rows 2-6: occupancy, building, collection, status, notice) | Per-row Balance/Status cells |
| `_refresh_summary_sync` in `gsheets.py` | Per-row Balance/Status/TotalPaid cells only | COLLECTION row — NEVER |
| `update_payment` in `gsheets.py` | Cash/UPI cell for one tenant row | COLLECTION row |

**The COLLECTION row must only be written by `sync_sheet_from_db.py`.** Any function that writes per-row data must not touch rows 2-6.

### 10.2 Total Dues — canonical formula

```python
# CORRECT — DB aggregate (used by PWA, bot, and sync script)
from src.services.reporting import collection_summary
result = await collection_summary(period_month="2026-04", session=session)
total_dues = result.pending

# WRONG — per-row clamped sum
total_dues = sum(max(0, row.balance) for row in rows)
# This overstates dues because overpaying tenants show balance=0, not negative.
# Their overpayment does NOT cancel underpaying tenants in per-row view.
```

### 10.3 April first-month balance formula

For April 2026 first-month tenants, `rent_due` already bundles deposit:
```
rent_due = prorated_rent + security_deposit - booking_amount  (via first_month_rent_due())
```

Therefore the balance formula MUST include `deposit_credit`:
```python
balance = max(0, rent_due - total_paid - prepaid_credit - deposit_credit)
```

Without `- deposit_credit`, tenants who paid their deposit show as fully unpaid — dues inflated.

### 10.4 Booking payments — NEVER write to Sheet Cash/UPI

Booking amount is already pre-subtracted from `rent_due` via `first_month_rent_due()`. Writing the booking payment to the Cash column would subtract it a second time.

Rule: skip gsheets write-back when `for_type == "booking"`.

### 10.5 gsheets write-back — period fallback for deposit payments

Deposit/booking payments have `period_month = None` (no billing period). Use `payment_date` as the period:

```python
if body.period_month:
    period = datetime.strptime(body.period_month, "%Y-%m")
else:
    period = date.today()  # or payment.payment_date for historical backfills
```

Never pass `period_month=None` to `datetime.strptime` — raises `TypeError`.

### 10.6 trigger_monthly_sheet_sync — call after every payment

Every PWA payment must fire a background sync so the COLLECTION row stays current:

```python
trigger_monthly_sheet_sync(period.month, period.year)
```

This spawns `sync_sheet_from_db.py` as a subprocess. It is the only way the COLLECTION row gets updated after individual payments.

---

## 10. DEPOSIT MATCHING (Bank vs Supabase)

### 10.1 Algorithm

```
For each Tenancy with security_deposit > 0 (last 90 days):
  Find BankTransaction where:
    - txn_type = "income"
    - amount within 10% of deposit
    - within 45 days of check-in date OR tenant first name in description

  Score matches: +3 for <=7 days, +2 for <=30 days, +1 for <=45 days, +2 for name match
  Pick highest score
```

---

## 11. MONTHLY REPORT (WhatsApp Bot)

### 11.1 Format

```
For month M:
  collected = SUM(Payment.amount WHERE period_month = M, for_type = rent, is_void = False)
  cash = SUM(... WHERE payment_mode = cash)
  upi = SUM(... WHERE payment_mode = upi)

  pending = SUM(positive per-row Balance over tenancies that have RentSchedule for M)
            Balance = rent_due + prev_due − (cash + upi + prepaid + booking_credit + deposit_credit)

  active_tenants = COUNT(Tenancy WHERE status = active, checkin_date <= last_day_of_M)
```

### 11.2 Pending Excludes No-Shows and Future Checkins (LOCKED)

**A tenancy contributes to Pending(M) only if it has a `RentSchedule(period_month = M)` row.**

- No-shows: `Tenancy.status = no_show` — no RentSchedule is created for them → excluded.
- Future checkins (e.g., May/June tenants visible in April source sheets): `checkin_date >= next_month_start` — no April RentSchedule created → excluded.
- Frozen months (Dec 2025 – Mar 2026) are loaded 1:1 and retain their RentSchedule rows.

**Enforcement site:** `scripts/sync_from_source_sheet.py` — skips RentSchedule creation when `checkin_date >= next period_month`. `scripts/sync_sheet_from_db.py` and `account_handler._monthly_report()` iterate only over RentSchedule rows for month M, so exclusion is automatic.

**Why:** Source sheet (`April Month Collection`) tracks deposit installments and future booking balances in its Balance column. Our bot/sheet/DB are month-scoped: Pending(April) = money owed *for April rent only*. Someone arriving in May cannot be "pending" for April.

**Reconciliation:** Source "April Balance" sum includes no-shows + deposit installments; after excluding those it matches our per-row Balance for the same tenants. Any residual gap is the formula difference (standard `first_month_rent_due = rent + deposit` vs source's installment view). Our formula is authoritative.

---

## 11b. UNIT ECONOMICS

### Definition
Unit economics = per-bed breakdown of revenue, cost, and profit. All figures use **True Revenue** (bank gross income − security deposits held). Never use deposits as income.

### KPIs computed by `src/services/unit_economics.py`

| KPI | Formula | Data Source |
|-----|---------|-------------|
| Occupancy % | occupied_beds / total_beds × 100 | DB — tenancies |
| Avg Agreed Rent | avg(tenancy.agreed_rent) for active monthly tenants | DB — tenancies (True Rent, no deposits) |
| Collection Rate | rent_collected / rent_billed × 100 | DB — payments vs rent_schedule |
| True Revenue | gross_bank_income + cash_rent − deposits_held | bank_transactions + payments (cash) |
| OPEX | sum of OPEX-category bank expenses | bank_transactions |
| EBITDA | True Revenue − OPEX | derived |
| Revenue / Bed | True Revenue / occupied_beds | derived |
| OPEX / Bed | OPEX / total_beds | derived |
| EBITDA / Bed | EBITDA / occupied_beds | derived |
| EBITDA Margin | EBITDA / True Revenue × 100 | derived |

### Rules
- **True Rent only** — agreed_rent excludes security_deposit and booking_amount
- Bank KPIs (revenue/bed, cost/bed, EBITDA/bed) only shown when bank CSV uploaded for that month
- Occupancy, avg rent, collection rate always available from DB
- OPEX excludes: Furniture & Fittings, Capital Investment, Tenant Deposit Refund, Non-Operating
- API: `GET /api/v2/app/finance/unit-economics?month=YYYY-MM`
- Bot: `QUERY_UNIT_ECONOMICS` intent — phrases: "unit economics", "revenue per bed", "cost per bed", "avg rent", "collection rate", "unit kpi"

---

## 12. KEY CONSTANTS

| Constant | Value | Where Used |
|---|---|---|
| TOTAL_REVENUE_BEDS | 294–295 (verify DB) | Occupancy KPI — G20 revenue from May 2026 |
| THOR_BEDS | 145 | Property occupancy |
| HULK_BEDS | 149 (⚠ section 12 says 146 — verify DB) | Property occupancy |
| NOTICE_BY_DAY | 5 | Deposit eligibility |
| OVERPAYMENT_NOISE_RS | 10 | Payment processing |
| DUPLICATE_PAYMENT_HOURS | 24 | Duplicate detection |
| DEPOSIT_MATCH_TOLERANCE | 10% | Bank deposit matching |
| DEPOSIT_MATCH_DAYS | 45 | Bank deposit matching |

---

## 13. GOLDEN RULES

1. **NEVER hard-delete financial records** — use `is_void = True`
2. **Dues are THIS MONTH ONLY** — never cumulative across months
3. **Exclude same-month check-ins from dues** — `checkin_date < month_start`
4. **Bank statement is the source of truth for P&L** — not Supabase payments table
5. **Payments table is the source of truth for dues** — not bank statement
6. **Classification rules: order matters** — Non-Operating MUST be first
7. **Proration always rounds DOWN** — tenant pays less, not more
8. **Maintenance = one-time check-in fee deducted from deposit, NEVER monthly. Non-refundable. Included in Total Collection.**
