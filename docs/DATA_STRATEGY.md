# Data Migration & Load Strategy — Cozeevo PG Accountant

> This document defines WHEN to use which data strategy and HOW to execute it safely.
> Last updated: 2026-03-13

---

## TL;DR — Quick Reference

| Situation | Command | Risk |
|-----------|---------|------|
| New code changes (new columns) | `python -m src.database.migrate_all` | Zero — skips existing |
| Fresh Supabase (new PG customer) | `python -m src.database.migrate_all --seed` | Zero — creates only |
| Re-seed roles/plans only | `python -m src.database.migrate_all --seed` | Zero — ON CONFLICT skip |
| Import tenant data from Excel | `python -m src.database.excel_import` | Zero — ON CONFLICT skip |
| Reset test data only | `python -m src.database.reset_test_data` | LOW — only L3 tables |
| Check DB state | `python -m src.database.migrate_all --status` | None — read only |

---

## 1. Data Layers & Wipe Rules

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

**Golden rule:** If it has money in it → never delete, only `is_void = TRUE`.

---

## 2. Strategy by Scenario

### Scenario A: Code Update (new columns added)
**When:** You change `models.py` and add new columns.

```bash
python -m src.database.migrate_all
```

- Runs `ALTER TABLE ... ADD COLUMN` for each new column
- Skips columns that already exist
- **No data loss, no duplicates**

---

### Scenario B: Test → Production (first deployment)
**When:** Moving from local laptop to Hostinger VPS with a fresh Supabase project.

```bash
# Step 1: Create all tables + seed roles/plans/categories
python -m src.database.migrate_all --seed

# Step 2: Import real tenant/payment data from Excel
python -m src.database.excel_import

# Step 3: Verify
python -m src.database.migrate_all --status
```

- `--seed` uses `ON CONFLICT DO NOTHING` — running it twice is safe
- Excel import checks phone (UNIQUE) before inserting tenants
- No risk of doubling data

---

### Scenario C: Adding a New PG Customer (SaaS)
**When:** Onboarding a second PG business onto a new Supabase project.

1. Create new Supabase project → get new `DATABASE_URL`
2. Update `.env` with the new URL
3. Run:
```bash
python -m src.database.migrate_all --seed
```
4. Import their Excel data:
```bash
python -m src.database.excel_import --file "their_data.xlsx"
```

Each customer gets a completely isolated database. Zero cross-contamination.

---

### Scenario D: Delta Load (ongoing payments / new tenants)
**When:** You get a new Excel export with additional rows — don't want to re-import everything.

The Excel importer already handles this:
- Tenants: keyed on `phone` (UNIQUE) → skips existing, inserts new
- Payments: keyed on `unique_hash` (SHA-256 of date+amount+reference) → skips duplicates
- Rent schedule: keyed on `(tenancy_id, period_month)` → skips existing months

```bash
python -m src.database.excel_import --file "march_update.xlsx"
```

**No manual de-duplication needed.**

---

### Scenario E: Test Data Reset (development only)
**When:** You want to clear out test onboarding sessions, fake leads, rate limit counters — but keep all real tenant/financial data.

Only L3 operational tables are safe to truncate:

```sql
-- Run in Supabase SQL Editor (NOT in production with real data)
TRUNCATE onboarding_sessions, checkout_records, rate_limit_log,
         pending_actions, leads, reminders, vacations RESTART IDENTITY;
```

Or use the script:
```bash
python -m src.database.reset_test_data   # only truncates L3 tables
```

**NEVER run TRUNCATE on:** tenants, tenancies, payments, rent_schedule, expenses, authorized_users, whatsapp_log.

---

### Scenario F: Fix Seed Data (wrong phone / wrong name)
**When:** You seeded a wrong admin phone or wrong plan name.

`ON CONFLICT DO NOTHING` means the seed won't overwrite existing rows. To fix:

```sql
-- In Supabase SQL Editor
UPDATE authorized_users SET phone = '9876543210' WHERE phone = '9999999999';
-- OR
UPDATE authorized_users SET name = 'Kiran Kumar' WHERE phone = '7845952289';
```

Then re-run `migrate_all --seed` — it will skip (correct) existing rows.

---

## 3. Anti-Duplicate Guarantees

| Table | Unique Key | Duplicate Prevention |
|-------|-----------|---------------------|
| `tenants` | `phone` | INSERT ON CONFLICT (phone) DO NOTHING |
| `authorized_users` | `phone` | INSERT ON CONFLICT (phone) DO NOTHING |
| `payments` | `unique_hash` | SHA-256(date+amount+reference) |
| `rent_schedule` | `(tenancy_id, period_month)` | Composite unique index |
| `checkout_records` | `tenancy_id` | UNIQUE constraint |
| `food_plans` | `name` | INSERT ON CONFLICT DO NOTHING |
| `expense_categories` | `name` | INSERT ON CONFLICT DO NOTHING |

---

## 4. Investment & Contacts Import Rules

### `investment_expenses` — import from consolidated sheet ONLY

The expense tracker has 7 sheets:
- `White Field PG Expenses` — **consolidated** — IMPORT THIS ONLY
- `ASHOKAN`, `JITENDRA`, `NARENDRA`, `OUR SIDE` — individual investor views — **SKIP** (subsets of consolidated)
- `Vendor Based Expenses`, `Summary` — different structure — not imported

Dedup key: `SHA-256(sno + purpose + amount + paid_by)`

### `pg_contacts` — all rows, auto-categorized

Source: `Contacts.xlsx` Sheet1. 62 contacts auto-categorized into: plumber, electrician, carpenter, furniture, food_supply, decor, security, internet, design, painting, gym_sports, government, facility, marketing, construction, vendor.

Visible to: `owner,staff` only — NOT accessible to tenants or leads via WhatsApp bot.

Dedup key: `SHA-256(name + phone + contact_for[:100])`

---

## 5. Migration File Register

| File | Purpose | Safe to re-run? |
|------|---------|----------------|
| `migrate_all.py` | Master — schema + seed | YES |
| `migrate_onboarding_checkout.py` | Tables: onboarding_sessions, checkout_records | YES |
| `migrate_tenant_fields.py` | Tenant extended KYC columns | YES |
| `migrate_investment_data.py` | Tables: investment_expenses, pg_contacts + import | YES (delta safe) |
| `excel_import.py` | Import tenant/payment data from Excel | YES (delta safe) |
| `seed.py` | Baseline seed data | YES (ON CONFLICT) |

---

## 5. Pre-Deployment Checklist (Test → Production)

- [ ] `DATABASE_URL` in `.env` points to the **production** Supabase project
- [ ] Run `python -m src.database.migrate_all --status` — confirm empty tables
- [ ] Run `python -m src.database.migrate_all --seed` — create schema + seed
- [ ] Run `python -m src.database.excel_import` — load tenant/payment history
- [ ] Run `python -m src.database.migrate_all --status` — verify row counts
- [ ] Test bot: send WhatsApp message, confirm role detection works
- [ ] Confirm admin phone (`ADMIN_PHONE` in `.env`) is correct
- [ ] Point Meta Cloud API webhook to production n8n URL
