# Rent Collection Reconciliation — Standard Process

## Golden Rules
1. **DB has zero duplicates** — confirmed by query grouping on (tenancy + date + amount + mode + for_type + notes). Never wipe to "fix" without verifying.
2. **Never sum all cash blindly** — always filter `for_type = 'rent'`. Otherwise you count deposits + advances + maintenance which inflates by 3-5x.
3. **Always exclude voided payments** — filter `is_void = False`.
4. **Cozeevo Operations Sheet is reality going forward** — all monthly tabs must use the FIXED 17-column header. Drop+reload only refreshes data rows; headers are NEVER wiped.
5. **Drop+reload preserves headers** — `sync_sheet_from_db.py` clears data rows 5+ but keeps rows 1-4 (summary + headers).
6. **Carry-forward rule** — exited tenants:
   - Exited in prior months → DO NOT show in current month tab
   - Exited in current month → DO show (with status "EXIT")
   - Active or no-show → ALWAYS show

## Where the Fixed Headers Live (do NOT redefine elsewhere)
- **MONTHLY_HEADERS** (17 cols) — defined in `src/integrations/gsheets.py:75`
- **TENANTS_HEADERS** — defined in `src/integrations/gsheets.py:81`
- **Carry-forward + visibility rules** — defined in `docs/SHEET_LOGIC.md`

All sync scripts read from these. Never hardcode column positions.

## Sync commands
```
python scripts/sync_sheet_from_db.py --month N --year YYYY --write   # one month tab
python scripts/import_daywise.py --write                              # DAY WISE tab
python scripts/sync_sheet_from_db.py --tenants --write                # TENANTS tab (if supported)
```


## Step-by-Step Process (run monthly)

### Step 1 — Pull Excel numbers
Open `Cozeevo Monthly stay (4).xlsx` → History tab. Sum these columns:
- Until Jan: cols 24 (Cash) + 25 (UPI)
- Feb: cols 30 (Cash) + 31 (UPI)
- Mar: cols 33 (Cash) + 34 (UPI)
- Apr+: open `April Month Collection.xlsx` → Long term tab → cols 22 (Cash) + 23 (UPI)

### Step 2 — Pull DB numbers
Run: `venv/Scripts/python scripts/cash_report.py`
Outputs cash by month split into Rent / Deposit / Booking. Use **Rent column only**.
For UPI, query separately (or extend the script).

### Step 3 — Pull bank UPI settlements
From YES Bank statement, find rows with `UPI Collection Settlement` or ref `115063600001082`.
Sum the deposit amount by month.

### Step 4 — Compare and reconcile
| Source | What it should match | Tolerance |
|---|---|---|
| Excel Cash vs DB Cash | exact | Rs.20K |
| Excel UPI vs DB UPI | exact | Rs.20K |
| DB UPI vs Bank UPI Settlement | close | Rs.50K (gateway fees + timing) |

### Step 5 — Investigate gaps
For any gap > Rs.20K:
1. Sort tenants by Excel UPI desc, sort by DB UPI desc → find missing tenant
2. Check Comments column for off-book notes ("Received by Chandra anna" etc.)
3. If found: log manually in DB via bot or admin endpoint
4. Update Excel with the correction

### Step 6 — Add off-book cash collections
Some collections are by partners/staff and never enter DB or bank. Track separately:

| Month | Amount | Notes |
|---|---|---|
| Mar 2026 | Rs.1,60,000 | Collected by Chandra anna (rows 92, 195, 210, 249) |
| Apr 2026 | Rs.15,500 | Shubhi Vishnoi Room 304 — paid to Chandra |

**Actual cash on hand** = DB Cash + Off-book cash

### Step 7 — Output reconciled view
Always use this format (categories rows, months columns):

```
                       Jan        Feb        Mar        Apr      TOTAL
Excel Cash           300,572    653,300  1,094,220    856,050   2,904,142
Excel UPI            530,575  2,324,048  2,785,388  2,788,481   8,428,492
DB Cash              300,572    653,300  1,113,720    856,050   2,923,642
DB UPI               530,575  2,308,048  2,775,888  2,788,481   8,402,992
Off-book (Chandra)         0          0    160,000     15,500     175,500
ACTUAL TOTAL         831,147  2,961,348  4,049,608  3,660,031  11,502,134
Bank UPI Settle       <pull from bank statement>
```

## How to Avoid DB Duplicates

When re-running Excel imports (e.g. after fixing a parser bug):
1. **Wipe imported payments first**: `python -m src.database.wipe_imported --confirm`
   - Drops L1 (Tenancy) + L2 (Payment) data — keeps L0 (master data, audit)
2. Then re-import: `python -m src.database.excel_import --write`

**Never** re-run import without wiping — duplicates will silently accumulate.

## Tools

- `scripts/cash_report.py` — DB cash by month/for_type
- `scripts/pnl_report.py` — full P&L from bank statements
- `scripts/export_classified.py` — classified bank txns
- `scripts/wipe_imported.py` — drop imported data before re-import
