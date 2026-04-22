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

### 1.2 Income Categories

| # | Account / Category | Source | In Total Collection? |
|---|---|---|---|
| 1 | Rent Collection (THOR) | Supabase payments (for_type=rent, property_id) | YES |
| 2 | Rent Collection (HULK) | Supabase payments (for_type=rent, property_id) | YES |
| 3 | Maintenance Fees | Supabase tenancies (maintenance_fee, checkin month) | YES |
| 4 | Security Deposits Received | Supabase payments (for_type=deposit) | NO — separate line |
| 5 | Booking Advances | Supabase payments (for_type=booking) | NO — separate line |
| 6 | Other Income | Bank statement (unclassified income) | NO |
| | **Total Collection** | Rent + Maintenance | |

### 1.3 Report Layout

```
                        Oct-25    Nov-25    Dec-25    Jan-26    Feb-26    Mar-26    TOTAL
═══════════════════════════════════════════════════════════════════════════════════════════
INCOME
  Rent Collection       XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Maintenance Fees      XXX       XXX       XXX       XXX       XXX       XXX       XXX
───────────────────────────────────────────────────────────────────────────────────────────
  TOTAL COLLECTION      XXX       XXX       XXX       XXX       XXX       XXX       XXX

  Security Deposits     XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Booking Advances      XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Other Income          XXX       XXX       XXX       XXX       XXX       XXX       XXX
───────────────────────────────────────────────────────────────────────────────────────────
  TOTAL INCOME (ALL)    XXX       XXX       XXX       XXX       XXX       XXX       XXX

EXPENSES
  Food & Kitchen        XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Salaries              XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Current Bill          XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Water Bill            XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Property Rent         XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Gas Bill              XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Internet Bill         XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Maintenance Cost      XXX       XXX       XXX       XXX       XXX       XXX       XXX
  House Keeping Items   XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Furniture & Fittings  XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Police/Waste/Govt     XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Marketing             XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Shopping & Supplies   XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Deposit Refunds       XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Non-Operating         XXX       XXX       XXX       XXX       XXX       XXX       XXX
  Other / Miscellaneous XXX       XXX       XXX       XXX       XXX       XXX       XXX
───────────────────────────────────────────────────────────────────────────────────────────
  TOTAL EXPENSES        XXX       XXX       XXX       XXX       XXX       XXX       XXX

═══════════════════════════════════════════════════════════════════════════════════════════
  NET P&L (Income - Expenses)  XXX  XXX   XXX       XXX       XXX       XXX       XXX
═══════════════════════════════════════════════════════════════════════════════════════════
```

### 1.4 Data Sources

| Data | Primary Source | Fallback |
|---|---|---|
| Income (rent) | Bank statement Excel (deposit column) | Supabase `payments` table |
| Expenses | Bank statement Excel (withdrawal column) | Supabase `expenses` table |
| Expense classification | `src/rules/pnl_classify.py` (auto) | Manual via `unclassified_review.xlsx` |
| Bank statements | `2025 statement.xlsx`, `2026 statment.xlsx` (Yes Bank) | WhatsApp PDF upload → Supabase `bank_transactions` |

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

### 2.4 Applied In (4 places — must be consistent)

1. `dashboard_router.py` → KPI `dues_outstanding`
2. `dashboard_router.py` → `/api/dashboard/dues` endpoint
3. `account_handler.py` → `_report()` function
4. `account_handler.py` → `_query_dues()` function

---

## 3. OCCUPANCY CALCULATION

### 3.1 Capacity (Canonical — verified from DB 2026-04-08)

```
TOTAL_REVENUE_BEDS = 291
  THOR: 145 beds (79 revenue rooms)
  HULK: 146 beds (79 revenue rooms)

Staff rooms EXCLUDED (9 rooms):
  THOR: G05(3), G06(2), 107(2), 108(2), 701(1), 702(1)
  HULK: G12(3), 114(2), 618(2)
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

## 12. KEY CONSTANTS

| Constant | Value | Where Used |
|---|---|---|
| TOTAL_REVENUE_BEDS | 291 | Occupancy KPI |
| THOR_BEDS | 145 | Property occupancy |
| HULK_BEDS | 146 | Property occupancy |
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
