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

---

## Migration & Data Strategy

> Merged from DATA_STRATEGY.md on 2026-03-30.

### Quick Reference

| Situation | Command | Risk |
|-----------|---------|------|
| New code changes (new columns) | `python -m src.database.migrate_all` | Zero — skips existing |
| Fresh Supabase (new PG customer) | `python -m src.database.migrate_all --seed` | Zero — creates only |
| Re-seed roles/plans only | `python -m src.database.migrate_all --seed` | Zero — ON CONFLICT skip |
| Import tenant data from Excel | `python -m src.database.excel_import` | Zero — ON CONFLICT skip |
| Reset test data only | `python -m src.database.reset_test_data` | LOW — only L3 tables |
| Check DB state | `python -m src.database.migrate_all --status` | None — read only |

### Data Layers & Wipe Rules

```
L0 — PERMANENT (NEVER wipe)
  authorized_users, properties, rooms, rate_cards, staff,
  food_plans, expense_categories, whatsapp_log, conversation_memory, documents

L1 — TENANT MASTER (re-importable from Excel)
  tenants, tenancies

L2 — FINANCIAL TRANSACTIONS (never hard-delete, use is_void flag)
  payments, rent_schedule, refunds, expenses

L3 — OPERATIONAL (safe to wipe for test resets)
  leads, vacations, reminders, rate_limit_log, pending_actions,
  onboarding_sessions, checkout_records
```

**Golden rule:** If it has money in it -> never delete, only `is_void = TRUE`.

### Strategy by Scenario

#### Scenario A: Code Update (new columns added)
```bash
python -m src.database.migrate_all
```
Runs `ALTER TABLE ... ADD COLUMN` for each new column. Skips columns that already exist. No data loss, no duplicates.

#### Scenario B: Test -> Production (first deployment)
```bash
# Step 1: Create all tables + seed roles/plans/categories
python -m src.database.migrate_all --seed

# Step 2: Import real tenant/payment data from Excel
python -m src.database.excel_import

# Step 3: Verify
python -m src.database.migrate_all --status
```

#### Scenario C: Adding a New PG Customer (SaaS)
1. Create new Supabase project -> get new `DATABASE_URL`
2. Update `.env` with the new URL
3. Run: `python -m src.database.migrate_all --seed`
4. Import their Excel: `python -m src.database.excel_import --file "their_data.xlsx"`

Each customer gets a completely isolated database. Zero cross-contamination.

#### Scenario D: Delta Load (ongoing payments / new tenants)
The Excel importer already handles this:
- Tenants: keyed on `phone` (UNIQUE) -> skips existing, inserts new
- Payments: keyed on `unique_hash` (SHA-256 of date+amount+reference) -> skips duplicates
- Rent schedule: keyed on `(tenancy_id, period_month)` -> skips existing months

```bash
python -m src.database.excel_import --file "march_update.xlsx"
```

#### Scenario E: Test Data Reset (development only)
Only L3 operational tables are safe to truncate:
```sql
TRUNCATE onboarding_sessions, checkout_records, rate_limit_log,
         pending_actions, leads, reminders, vacations RESTART IDENTITY;
```
Or: `python -m src.database.reset_test_data`

**NEVER TRUNCATE:** tenants, tenancies, payments, rent_schedule, expenses, authorized_users, whatsapp_log.

#### Scenario F: Fix Seed Data (wrong phone / wrong name)
`ON CONFLICT DO NOTHING` means the seed won't overwrite existing rows. Fix manually in Supabase SQL Editor, then re-run `migrate_all --seed`.

### Anti-Duplicate Guarantees

| Table | Unique Key | Duplicate Prevention |
|-------|-----------|---------------------|
| `tenants` | `phone` | INSERT ON CONFLICT (phone) DO NOTHING |
| `authorized_users` | `phone` | INSERT ON CONFLICT (phone) DO NOTHING |
| `payments` | `unique_hash` | SHA-256(date+amount+reference) |
| `rent_schedule` | `(tenancy_id, period_month)` | Composite unique index |
| `checkout_records` | `tenancy_id` | UNIQUE constraint |
| `food_plans` | `name` | INSERT ON CONFLICT DO NOTHING |
| `expense_categories` | `name` | INSERT ON CONFLICT DO NOTHING |

### Investment & Contacts Import Rules

#### `investment_expenses` — import from consolidated sheet ONLY
The expense tracker has 7 sheets:
- `White Field PG Expenses` — **consolidated** — IMPORT THIS ONLY
- `ASHOKAN`, `JITENDRA`, `NARENDRA`, `OUR SIDE` — individual investor views — **SKIP** (subsets of consolidated)
- `Vendor Based Expenses`, `Summary` — different structure — not imported

Dedup key: `SHA-256(sno + purpose + amount + paid_by)`

#### `pg_contacts` — all rows, auto-categorized
Source: `Contacts.xlsx` Sheet1. 62 contacts auto-categorized into: plumber, electrician, carpenter, furniture, food_supply, decor, security, internet, design, painting, gym_sports, government, facility, marketing, construction, vendor.

Visible to: `owner,staff` only — NOT accessible to tenants or leads via WhatsApp bot.

Dedup key: `SHA-256(name + phone + contact_for[:100])`

### Migration File Register

| File | Purpose | Safe to re-run? |
|------|---------|----------------|
| `migrate_all.py` | Master — schema + seed | YES |
| `migrate_onboarding_checkout.py` | Tables: onboarding_sessions, checkout_records | YES |
| `migrate_tenant_fields.py` | Tenant extended KYC columns | YES |
| `migrate_investment_data.py` | Tables: investment_expenses, pg_contacts + import | YES (delta safe) |
| `excel_import.py` | Import tenant/payment data from Excel | YES (delta safe) |
| `seed.py` | Baseline seed data | YES (ON CONFLICT) |

### Pre-Deployment Checklist (Test -> Production)

- [ ] `DATABASE_URL` in `.env` points to the **production** Supabase project
- [ ] Run `python -m src.database.migrate_all --status` — confirm empty tables
- [ ] Run `python -m src.database.migrate_all --seed` — create schema + seed
- [ ] Run `python -m src.database.excel_import` — load tenant/payment history
- [ ] Run `python -m src.database.migrate_all --status` — verify row counts
- [ ] Test bot: send WhatsApp message, confirm role detection works
- [ ] Confirm admin phone (`ADMIN_PHONE` in `.env`) is correct
- [ ] Point Meta Cloud API webhook to production URL
