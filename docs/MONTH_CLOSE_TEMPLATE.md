# Month-End Close Sheet — Cozeevo

> Fill on the LAST day of every month (or 1st of next). Everything here is what
> the bank CSVs CANNOT see. Together: bank CSVs + this sheet = complete P&L.
> Feeds `pnl_monthly_adjustments` + the P&L excluded/balance-sheet sections.
> Amounts in ₹. Write 0 explicitly — blank means "not counted", not "zero".

## Month: ________  Filled by: ________  Date: ________

### A. CASH RECONCILIATION (the whole cash economy)

| # | Line | Amount | Notes |
|---|------|-------:|-------|
| A1 | Opening cash in hand (= last month's A11 count) | | |
| A2 | + Cash collected — app total (rent + deposit + advance) | | app Cash tab shows this; verify |
| A3 | + Cash collected OFFLINE, never entered in app | | who + why (e.g. Bala uncle) |
| A4 | − Cash deposited into bank this month | | date-wise if multiple |
| A5 | − Property rent paid to landlords in CASH | | per landlord split |
| A6 | − Operating expenses paid in cash | | itemise below in F |
| A7 | − Deposit REFUNDS paid in cash | | tenant + room (bank refunds auto-tracked) |
| A8 | − Loans given from cash / − capital returned in cash | | goes to loan register D |
| A9 | + Loan repayments received in cash | | which account |
| A10 | = EXPECTED closing cash (A1+A2+A3−A4−A5−A6−A7−A8+A9) | | auto |
| A11 | PHYSICAL COUNT at month close | | counted by + date |
| A12 | Variance (A11 − A10) | | explain if > ₹500 |

### B. DEPOSIT EVENTS (not visible as narrations)

| # | Line | Amount | Notes |
|---|------|-------:|-------|
| B1 | Deposits FORFEITED this month (no/late notice exits) | | tenant + room + reason each |
| B2 | Deposit deductions kept (damages/dues) at checkout | | |
| B3 | Refunds still OWED but not yet paid (payable) | | tenant list |

### C. PAYABLES / ACCRUALS (owed but not yet paid)

| # | Line | Amount | Notes |
|---|------|-------:|-------|
| C1 | Landlord rent for THIS month (paid next month) | | cash-basis P&L books it next month — this line tracks the liability |
| C2 | Manoj water bill for this month (he bills 1 mo behind) | | |
| C3 | BESCOM / other utility bills pending | | |
| C4 | Staff salary/advances outstanding | | e.g. worker advances |
| C5 | Any vendor credit (groceries, gas, etc.) | | |

### D. LOAN REGISTER MOVEMENTS (never P&L — balance sheet)

| Account | Given this month | Repaid this month | Balance owed | Mode |
|---|---:|---:|---:|---|
| Bava (Bunk) | | | | |
| Balaji Bellandur | | | | |
| Boopalan (Prabhakaran) | | | | |
| Boopalan (Tanvi) | | | | |
| (new account?) | | | | |
| Chit payments made (Balaji/Boopalan/Tanvi cadence) | | | | |

### E. CAPITAL / PERSONAL (money crossing personal ↔ PG line)

| # | Line | Amount | Notes |
|---|------|-------:|-------|
| E1 | Personal money spent for PG (Kiran/Lakshmi/partners) | | company owes back — capital contribution |
| E2 | PG money taken as drawings / investor payout | | |
| E3 | Rent/income received into PERSONAL accounts (not THOR/HULK) | | needs that statement imported |

### F. CASH EXPENSE ITEMISATION (backs A6)

| Date | Paid to | What | Amount |
|---|---|---|---:|
| | | | |

### G. ONE-OFFS / NOTES
Anything unusual: asset purchases, buyouts, disputes, rate changes, tenants paying to wrong account, etc.

---
**Where it flows:** A5 → `rent_paid_cash` · A6 → `cash_expense` · A11 → `cash_holding` ·
A3 → offline-cash income line · B1 → "Deposits forfeited" (once Option A approved) ·
D → loan register section · C = accrual footnotes · E → Capital Contributions section.
