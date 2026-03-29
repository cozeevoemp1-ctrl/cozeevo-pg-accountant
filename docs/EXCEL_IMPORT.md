# Excel Import Workflow

Single source of truth for loading data from Kiran's offline Excel into DB + Google Sheet.

## Files

| File | Purpose |
|---|---|
| `scripts/clean_and_load.py` | **THE parser** -- reads Excel History sheet, writes to Google Sheet |
| `src/database/excel_import.py` | Imports parsed records into Supabase DB (uses `clean_and_load.read_history()`) |
| `src/database/wipe_imported.py` | Drops L1+L2 data before reimport (tenants, tenancies, payments, rent_schedule, expenses, refunds) |

**Rule: ONE parser.** `clean_and_load.py` owns `read_history()`. The DB import calls it -- never duplicate parsing logic.

## Step-by-step

```bash
# 1. Place new Excel in project root
#    File: "Cozeevo Monthly stay (N).xlsx"
#    Update EXCEL_FILE in scripts/clean_and_load.py if filename changed

# 2. Write to Google Sheet (Cozeevo Operations v2)
python scripts/clean_and_load.py

# 3. Wipe DB (dry run first, then confirm)
python -m src.database.wipe_imported              # preview
python -m src.database.wipe_imported --confirm     # actual wipe

# 4. Import into DB
python -m src.database.excel_import --write

# 5. Verify
#    Output should show: 0 skipped, all counts match Excel
```

## What gets wiped (L1+L2)

| Level | Tables | Why |
|---|---|---|
| L2 | refunds, payments, rent_schedule, expenses | Financial data -- reimported from Excel |
| L1 | tenancies, tenants | Tenant data -- reimported from Excel |

## What is NEVER wiped (L0)

authorized_users, properties, rooms, rate_cards, staff, food_plans,
expense_categories, whatsapp_log, conversation_memory, documents.

These are structural / operational -- they exist independent of the Excel.

## Room lookup rules

**DB is truth for building assignment.** Excel BLOCK column may have manual mistakes.

The import resolves rooms by number only, ignoring which building Excel says they're in.
If room 121 is in HULK in DB but Excel says THOR, the import uses the DB's HULK assignment.

### Edge cases

| Excel value | What it means | How import handles it |
|---|---|---|
| `May` | Future no-show, no room assigned yet | Maps to `UNASSIGNED` dummy room |

### No-show visibility rules

No-shows appear in **every monthly tab from first appearance until their checkin month**.
A no-show bed is reserved and not available — it must count toward occupancy in all months.

Example: A no-show with checkin 2026-04-01 appears in Dec, Jan, Feb, Mar, and April tabs.
Once they check in (status changes to Active), they stop showing as no-show and appear as checked-in instead.

The no-show count in each monthly tab is calculated per-month: only those whose `checkin >= month_start`.
| `617/416` | Multi-room string | Takes first number (`617`) |
| Room in wrong BLOCK | Manual Excel error | Ignored -- DB building wins |
| Room not in DB at all | Genuinely new room | **STOP and ask Kiran** -- don't skip, don't auto-create |

## Parser details (read_history)

Source: `scripts/clean_and_load.py :: read_history()`

Reads History sheet only. Returns list of dicts with keys:
- Tenant: `name`, `phone`, `gender`, `food`
- Room: `room`, `block`, `floor`, `sharing`
- Tenancy: `checkin`, `status`, `current_rent`, `rent_monthly`, `rent_feb`, `rent_may`, `deposit`, `booking`, `maintenance`, `staff`, `comment`
- Payments: `dec_st`, `jan_st`/`jan_cash`/`jan_upi`, `feb_st`/`feb_cash`/`feb_upi`, `mar_st`/`mar_cash`/`mar_upi`
- Other: `refund_status`, `refund_amount`

### Rent revision logic

Excel has 3 rent columns:
- Col 10: `Monthly Rent` (original)
- Col 11: `From 1st FEB` (revision)
- Col 12: `From 1st May` (revision)

`current_rent` = latest non-zero value (May > Feb > Monthly).
Rent schedule uses the correct rent per period:
- Dec/Jan: `rent_monthly`
- Feb-Apr: `rent_feb` (if > 0, else `rent_monthly`)
- May+: `rent_may` (if > 0)

### Payment columns

| Month | Status col | Cash col | UPI col |
|---|---|---|---|
| Dec 2025 | 21 (DEC RENT) | -- | -- |
| Jan 2026 | 22 (JAN RENT) | 24 (until jan Cash) | 25 (until jan UPI) |
| Feb 2026 | 26 (FEB RENT) | 29 (FEB Cash) | 30 (FEB UPI) |
| Mar 2026 | 27 (MARCH RENT) | 32 (March Cash) | 33 (March UPI) |

### Status mapping

| Excel IN/OUT | DB TenancyStatus |
|---|---|
| CHECKIN | active |
| EXIT | exited |
| NO SHOW | no_show |
| CANCELLED | cancelled |

## Google Sheet structure (Cozeevo Operations v2)

Sheet ID: `1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw`

| Tab | Content |
|---|---|
| TENANTS | All 283 rows, DB-aligned columns |
| DECEMBER 2025 | Monthly payment view with summary |
| JANUARY 2026 | Monthly payment view with summary |
| FEBRUARY 2026 | Monthly payment view with summary |
| MARCH 2026 | Monthly payment view with summary |

Monthly tabs include: Cash, UPI, Total Paid, Balance, Status, Chandra/Lakshmi tracking columns.

## Adding a new month

When April data appears in Excel:
1. Add new columns to Excel (APR RENT, APR Cash, APR UPI)
2. Update `MONTH_COLS` in `excel_import.py`
3. Update `months_cfg` in `clean_and_load.py`
4. Add `apr_st`/`apr_cash`/`apr_upi` to `read_history()` return dict

## Verification checklist

After every import, confirm:
- [ ] 0 rows skipped (or explained edge cases)
- [ ] DB tenancy count == Excel row count
- [ ] DB active count == Excel CHECKIN count
- [ ] DB exited count == Excel EXIT count
- [ ] Spot-check 5 random tenants: name, room, rent, deposit match
- [ ] Google Sheet TENANTS tab row count matches
- [ ] Monthly tab totals (Cash + UPI) roughly match DB payment sums
