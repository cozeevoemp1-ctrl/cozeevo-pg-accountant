# SHEET_LOGIC.md — Google Sheet Data Rules & Calculation Reference

> **READ THIS BEFORE touching ANY Google Sheet code, transform script, or dashboard.**
> If you forget a rule, READ THIS. Don't ask Kiran.

---

## 1. DATA SOURCE

### Original Sheet (current source of truth for manual data)
- ID: `1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA`
- Tab: `History`
- 267 tenants, 42 columns

### New Sheet (target, under construction)
- ID: `1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw`
- Tabs: DASHBOARD, TENANTS, DECEMBER 2025, JANUARY 2026, FEBRUARY 2026, MARCH 2026

### Column Map (Original History Sheet, 0-indexed)

| Col | Header | Type | Notes |
|-----|--------|------|-------|
| 0 | Room No | text | "101", "G05", "523/219" |
| 1 | Name | text | tenant name |
| 2 | Gender | text | Male/Female |
| 3 | Mobile Number | text | phone |
| 4 | Checkin date | date | DD-MM-YYYY or DD/MM/YYYY |
| 5 | Booking | number | advance booking amount |
| 6 | Security Deposit | number | deposit paid |
| 7 | Maintenance | number | one-time fee |
| 8 | Day wise Rent | number | prorated rent if applicable |
| 9 | Monthly Rent | number | original agreed rent |
| 10 | From 1st FEB | number | rent revision from Feb |
| 11 | From 1st May | number | rent revision from May |
| 12 | Sharing | text | Single/Double/Triple/Premium |
| 13 | Paid Date | date | when they paid |
| 14 | Comments | text | **MIXED DATA — see Section 6** |
| 15 | Assigned Staff | text | staff name |
| 16 | IN/OUT | text | CHECKIN / EXIT / CANCELLED |
| 17 | BLOCK | text | THOR / HULK |
| 18 | Floor Number | number | 0-6 |
| 20 | DEC RENT | text | PAID / NOT PAID / EXIT / NO SHOW |
| 21 | JAN RENT | text | same |
| 22 | Jan Balance | number | **NOT dues — see Section 3** |
| 23 | until jan Cash | number | January cash payments |
| 24 | until jan UPI | number | January UPI payments |
| 25 | FEB RENT | text | rent status |
| 26 | MARCH RENT | text | rent status |
| 27 | FEB Balance | number/text | **NOT dues — may have text like "Feb28th exit"** |
| 28 | FEB Cash | number | February cash payments |
| 29 | FEB UPI | number | February UPI payments |
| 30 | March Balance | number | **NOT dues — see Section 3** |
| 31 | March Cash | number | March cash payments |
| 32 | March UPI | number | March UPI payments |
| 38 | Refund Status | text | Paid / Pending |
| 39 | Refund Amount | number | refund amount |

---

## 2. PAYMENT AMOUNTS — WHERE TO GET THEM

**ONLY from the Cash/UPI columns. NEVER from Comments. NEVER from Balance.**

| Month | Cash Col | UPI Col | Verified Total |
|-------|----------|---------|----------------|
| January | 23 | 24 | Cash 3,00,572 / UPI 5,30,575 |
| February | 28 | 29 | Cash 6,53,300 / UPI 23,24,048 |
| March | 31 | 32 | Cash 10,26,720 / UPI 26,09,950 |

### Parser rules:
- Remove commas: `"15,000"` → `15000`
- Extract first number: `re.search(r'[\d.]+', cleaned)`
- If cell is empty or `"0"` → 0
- If cell has text (like `"-"`) → 0
- **NEVER parse numbers from Comments column as payments**

### Validation (MUST DO after every transform):
```
Script total for col X == SUM of all non-empty cells in col X of original sheet
```
If mismatch > Rs.1, STOP and investigate.

---

## 3. BALANCE COLUMN IS NOT DUES

The "Balance" columns (22, 27, 30) contain **Kiran's manual notes**, NOT computed dues.

Examples of what's in March Balance (col 30):
- `5500` = "advance to collect in April" (Ashish Das — already PAID)
- `8256` = "prorated calculation 516*16" (Priyansh — already PAID)
- `9000` = "from deposit" (Hardik — advance/deposit related)
- `877` = "due on April 1st" (Arjun — partial carry forward)
- `4500` = "Received by Chandra" context note (Jahnavi)

**Rule: NEVER use Balance column as the due amount.**

Correct due amount = `Rent Due - Cash Paid - UPI Paid`

---

## 4. DUES CALCULATION (from REPORTING.md Section 2)

### Formula
```
For month M:
  1. Filter: Tenancy.status == Active (col 16 = CHECKIN or empty)
  2. Filter: Rent status for month != EXIT, CANCEL (col 20/21/25/26)
  3. Filter: checkin_date < month_start (strict <) — only tenants who were there BEFORE the month
  4. Rent Due = current rent (col 9, or col 10 if > 0, or col 11 if > 0)
  5. Paid = Cash (col) + UPI (col) for that month
  6. Due = Rent Due - Paid
  7. If Due > 0: tenant owes money
```

### Current Rent Logic
```python
rent = Monthly Rent (col 9)
if From 1st May (col 11) > 0: rent = col 11
elif From 1st FEB (col 10) > 0: rent = col 10
```

### Verified March 2026 Dues
- Scoped tenants: 137 (active, checked in before Mar 1)
- Rent expected: Rs.23,31,500
- Paid: 118 fully, 13 partial, 6 unpaid
- **Total outstanding: Rs.1,46,500 (19 tenants)**

---

## 5. OCCUPANCY CALCULATION

### Formula
```
Active tenants = status == Active AND checkin_date <= month_end
Premium tenants = active AND sharing == Premium
Regular count = active - premium
Beds = regular + (premium * 2)
No-show = ALL tenants with status == No-show (NO date filter)
Vacant = 297 - beds - no_show
Occupancy % = beds / 297 * 100
```

### THOR / HULK Split
```
Filter by BLOCK column (col 17) = THOR or HULK
Same formula per building
TOTAL_BEDS = 297 (THOR 147 + HULK 150)  -- updated 2026-05-09
```

### Verified March 2026
- Checked-in: 219 beds (181 regular + 19 premium)
- No-show: 20
- Vacant: 52
- THOR: 125 beds (109 tenants)
- HULK: 94 beds (91 tenants)

---

## 6. COMMENTS COLUMN (col 14) — PARSING RULES

### What's in it
185 cells with text. Contains a mix of:
- Master agreements: `"always cash"`, `"3 months lockin"`, `"referrel bonus"`
- Structured data: `[Security Deposit: 15,000]`, `[March Balance: 516*16=8256]`
- Monthly context: `[March Cash: Received by Chandra anna]`
- Status notes: `"Exit"`, `"exit jan 1st"`, `"No Due Jan 31st Exit"`
- Timestamps: `[25-Mar 17:45] Rs.500 CASH`

### Pattern: `[Key: Value]`
Extract using: `re.findall(r'\[([^:]+):\s*([^\]]+)\]', comment)`

### Classification Rules
| Pattern | Destination | NOT |
|---------|-------------|-----|
| `[March Balance: X]` | March Notes column | NOT a payment, NOT a due |
| `[March Cash: text]` | March Notes column | NOT a payment override |
| `[Security Deposit: X]` | TENANTS master | NOT monthly |
| `[Day wise Rent: X]` | TENANTS master | NOT monthly |
| `[Refund Amount: X]` | TENANTS master | NOT monthly |
| `"always cash"` | TENANTS master comment | permanent policy |
| `"3 months lockin"` | TENANTS master comment | permanent policy |
| `"Received by Chandra"` | Monthly Notes | WHO collected, not HOW MUCH |
| `"on april 1st"` | Monthly Notes | WHEN due, not amount |
| `"paid in feb"` | Monthly Notes | context, not payment |
| `[25-Mar 17:45] Rs.500 CASH` | Monthly Notes | timestamp entry |
| `"Exit"` | Status context | not a comment |

### CRITICAL RULE
**Numbers in comments are CONTEXT, not data.** Never override Cash/UPI/Balance columns from comments.

Example: `[March Cash: 13000 Received by Chandra /5000 Lakshmi gorjala]`
- This does NOT mean March Cash = 13000. The actual Cash column has the real number.
- This means: "of the cash collected, 13000 was received by Chandra and 5000 by Lakshmi"
- Goes into Notes as: "Received by Chandra 13000, Lakshmi gorjala 5000"

---

## 7. WHO APPEARS IN EACH MONTHLY TAB

### Rule
A tenant appears in month M if:
1. They have ANY payment (cash > 0 or upi > 0) for that month — **includes booking advances from future tenants**
2. OR they were physically present (checkin <= month_end AND (active OR exited after month_start))
3. OR they are No-show with checkin in that month

### Why booking advances matter
Some tenants check in February but pay booking advance in January. Their Jan Cash/UPI column has a value even though checkin_date is in Feb. They MUST appear in January tab because money was received.

### Verified counts
| Month | Tenants in tab |
|-------|---------------|
| December 2025 | 68 |
| January 2026 | 129 |
| February 2026 | 187 |
| March 2026 | 232 |

---

## 8. NEW SHEET STRUCTURE (monthly tab)

### Rows 1-4: Summary (auto-calculated by Apps Script on edit)
```
Row 1: Month Title
Row 2: Occupancy | beds (reg+premP) | No-show: X | Vacant: X | Occ: X% | Rent Expected | X | Collected | X | Outstanding | X | Coll: X%
Row 3: New check-ins | X | Exits | X
Row 4: Headers
```

### Row 5+: Tenant Data
| Col | Header | Source | Notes |
|-----|--------|--------|-------|
| A | Room | col 0 | |
| B | Name | col 1 | |
| C | Building | col 17 | THOR/HULK |
| D | Sharing | col 12 | |
| E | Rent Due | calculated | current rent, prorated if mid-month checkin |
| F | Cash Paid | col 23/28/31 | from original Cash column ONLY |
| G | UPI Paid | col 24/29/32 | from original UPI column ONLY |
| H | Total Paid | F + G | calculated |
| I | Balance | E - H | **calculated, NOT from original Balance column** |
| J | Status | calculated | PAID (bal<=0) / PARTIAL (paid>0) / UNPAID (paid=0) / EXIT / NO SHOW |
| K | Check-in | col 4 | date |
| L | Event | calculated | NEW CHECK-IN / EXITED / NO-SHOW |
| M | Notes | from comments | monthly notes extracted from comment parser |

---

## 9. PRORATION

### Mid-month check-in
```
If checkin_date is in the month:
  days_in_month = calendar days
  days_stayed = days_in_month - checkin_day + 1
  prorated_rent = FLOOR(rent * days_stayed / days_in_month)
```

### Full month
```
If checkin_date is before month start:
  rent_due = full current rent
```

---

## 10. STATUS MAPPING

### From original IN/OUT column (col 16)
| Original | New Status |
|----------|-----------|
| CHECKIN | Active |
| (empty) | Active |
| EXIT | Exited |
| CANCELLED | Cancelled |
| NO SHOW | No-show |

### From rent status columns (col 20/21/25/26)
| Original | Meaning |
|----------|---------|
| PAID | fully paid |
| NOT PAID | nothing paid |
| Partially Paid | some paid |
| EXIT | tenant left before/during this month |
| CANCELLED | booking cancelled |
| NO SHOW | booked but didn't arrive |
| ADVANCE | paid advance (booking) |

---

## 11. APPS SCRIPT BEHAVIOR

### On edit (any monthly tab):
1. Recalculate Total Paid (H) = Cash (F) + UPI (G) for edited row
2. Recalculate Balance (I) = Rent Due (E) - Total Paid (H)
3. Recalculate Status (J) = PAID/PARTIAL/UNPAID based on balance
4. Update summary rows 2-3 (totals, occupancy, collections)
5. Refresh DASHBOARD tab

### New month creation (daily at midnight or manual):
1. Read TENANTS tab for active + no-show tenants
2. Create new tab with prorated rent for mid-month checkins
3. All Cash/UPI = 0, Status = UNPAID
4. Refresh dashboard

### Dashboard reads from monthly tabs (row-by-row), never from summary headers
- `readMonthData(sheet)` iterates row 5+ and sums everything directly
- THOR/HULK split by Building column (C)
- Month-on-month comparison reads all monthly tabs

---

## 12. TRANSFORM SCRIPT USAGE

### Current best: `scripts/transform_sheet_v3.py`

```bash
python scripts/transform_sheet_v3.py
```

### What it does:
1. Reads original History sheet (all 267 rows, 42 cols)
2. Parses comments: extracts [Key: Value] patterns, separates master vs monthly notes
3. Payment amounts from Cash/UPI columns ONLY (never from comments)
4. Writes TENANTS tab (master data + master comments in col P)
5. Writes monthly tabs (Dec/Jan/Feb/Mar) with correct filtering
6. Balance = Rent Due - Cash - UPI (calculated, not from original)
7. Validates column totals match original sheet

### When to re-run:
- Kiran updates original sheet with new data
- New month needs to be added
- Data correction needed

### Report script: `scripts/monthly_report.py`
Generates text report with occupancy, collections, dues, THOR/HULK — for verification.

---

## 13. VALIDATION CHECKLIST

After every transform, verify:

| Check | Expected |
|-------|----------|
| Jan Cash total | 3,00,572 |
| Jan UPI total | 5,30,575 |
| Feb Cash total | 6,53,300 |
| Feb UPI total | 23,24,048 |
| Mar Cash total | 10,26,720 |
| Mar UPI total | 26,09,950 |
| Active tenants | 201 |
| Exited | 38 |
| No-show | 20 |
| Mar beds | 219 (181 reg + 19 prem) |
| Mar dues | Rs.1,46,500 (19 tenants) |

If ANY number doesn't match, STOP and investigate before writing to sheet.

---

## 14. MISTAKES MADE (DON'T REPEAT)

1. **Used Balance column as dues** — Balance is manual notes, not computed dues
2. **Parsed comment numbers as payment overrides** — comments are context only
3. **Filtered monthly tabs by checkin_date only** — missed booking advances from future tenants
4. **Used SUMPRODUCT formulas across sheets** — broke on text cells, too fragile
5. **Wrote dashboard from summary rows** — summary rows can be stale; always read row-by-row
6. **Didn't validate totals** — wrote wrong numbers to sheet without checking
7. **Rushed to ship before verifying** — always verify numbers match before any write
