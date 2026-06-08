# Data Architecture

Master reference for how data flows through PG Accountant. Read this before touching any parser, importer, or publisher script.

## Purpose

Define one canonical data model, one way to read inputs, one way to publish outputs. No hardcoded column positions, no duplicated rules, no implicit contracts.

## Related Docs (read before building)

| Topic | Where |
|---|---|
| DB schema (26 tables, enums, constraints) | `docs/DATA_MODEL.md` |
| Excel import workflow (drop+load) | `docs/EXCEL_IMPORT.md` |
| Monthly tab layout + calc rules | `docs/SHEET_LOGIC.md` |
| Financial formulas | `docs/REPORTING.md` |
| Master data (rooms, buildings) | `docs/MASTER_DATA.md` |
| External integrations | `docs/INTEGRATIONS.md` |
| Reconciliation process | `docs/RENT_RECONCILIATION.md` |

## 1. Entity Layers

Every table in the DB falls into one of four layers by lifecycle:

### L0 — Master (rarely changes, seeded or manually curated)
- `properties` (Cozeevo THOR, Cozeevo HULK)
- `rooms` (physical layout — room_number, floor, property)
- `rate_cards` (pricing by sharing type)
- `staff` (employees)
- `food_plans` (veg/non-veg/egg)
- `expense_categories` (P&L taxonomy)
- `authorized_users` (admin, partner, receptionist access)

**Rule:** NEVER wipe via `wipe_imported.py`. Changes require explicit migration.

### L1 — Dimensions (slowly-changing entities)
- `tenants` (name, phone, gender, DOB, ID proof, emergency contact)
- `tenancies` (a tenant's stay — checkin, checkout, room, rent)
- `rent_revisions` (permanent rent changes)

**Rule:** Keys defined by business identity (phone + name for tenants; tenant + room + checkin for tenancies). Shared phones allowed (partners/family in same room).

### L2 — Transactions (append-only, immutable after creation)
- `payments` (money in: rent, deposit, booking, maintenance)
- `rent_schedule` (monthly rent due per tenancy)
- `refunds` (money out to tenants)
- `expenses` (money out to vendors)
- `audit_log` (every field-level change — who/what/when)

**Rule:** Never UPDATE or DELETE. To reverse, set `is_void = True` and write a new record. Audit log is the source of truth for "who did what."

### L3 — Derived / Operational (computed or ephemeral)
- `onboarding_sessions` (digital check-in state)
- `pending_actions` (WhatsApp disambiguation state)
- `whatsapp_log` (message history)
- `leads` (room enquiries)
- `reminders` (scheduled notifications)

**Rule:** Safe to truncate. Can be regenerated or accepted as lost.

## 2. Data Sources (Inputs)

All raw data comes from these six sources. Each must have a typed contract.

| Source | Format | Current parser | Contract (proposed) |
|---|---|---|---|
| Cozeevo Monthly stay (master Excel) | `.xlsx` | `scripts/clean_and_load.py::read_history` | `ExcelHistoryRow` |
| April Month Collection | `.xlsx` | `scripts/import_april.py` (hardcoded cols) | `AprilCollectionRow` |
| Day-wise stays | `.xlsx` | `scripts/import_daywise.py` | `DaywiseRow` |
| YES Bank statement | `.xlsx` / `.csv` | `scripts/export_classified.py` + `classify_new_statement.py` | `BankTxnRow` |
| WhatsApp bot payments | API call | `account_handler._do_log_payment_by_ids` | already typed (SQLAlchemy) |
| Onboarding form | Web POST | `api/onboarding_router.py` | already typed (Pydantic) |

**Gap:** Excel and Bank sources have no schema — parsers use inferred positions. Fix below.

## 3. Proposed File Layout

```
src/
  data/
    __init__.py
    schemas.py          # Pydantic models for ALL input rows
    parsers/
      __init__.py
      excel_history.py    # Cozeevo Monthly stay → ExcelHistoryRow[]
      excel_april.py      # April Collection → AprilCollectionRow[]
      excel_daywise.py    # Day-wise stays → DaywiseRow[]
      bank_yes.py         # YES Bank xlsx/csv → BankTxnRow[]
    loaders/
      __init__.py
      db_loader.py        # Any *Row[] → DB (upsert by business key)
    publishers/
      __init__.py
      sheet.py            # DB view → Google Sheet (uses MONTHLY_HEADERS)
      pnl.py              # DB + bank → P&L Excel
      dashboard.py        # DB → HTML dashboard
  integrations/
    gsheets.py            # Sheet client (already has MONTHLY_HEADERS ✓)
  database/
    models.py             # SQLAlchemy ORM (already typed ✓)
```

## 4. The Golden Rules

1. **No hardcoded column positions.** Every read uses header lookup. Every write uses the canonical header list.
2. **One header registry per entity.** `MONTHLY_HEADERS`, `TENANTS_HEADERS`, `DAYWISE_HEADERS` all live in `src/integrations/gsheets.py`. Reference, don't redefine.
3. **One schema per input.** Every CSV/Excel row shape is a Pydantic model in `src/data/schemas.py`. Parsers output validated instances.
4. **Business keys, not row positions.** Tenants keyed by `(phone, name)`. Tenancies by `(tenant_id, room_id, checkin)`. Payments by `(tenancy_id, payment_date, amount, mode, for_type)`.
5. **Idempotent loads.** Re-running any loader produces the same DB state. No duplicates on re-run.
6. **Schema-drift fails loud.** If the Excel adds/renames a column, the parser throws a clear error — never silently misreads.

## 5. ETL Flow

```
┌───────────────────────┐
│  SOURCES              │  Excel, CSV, API, Bot messages
│  (raw files + APIs)   │
└──────────┬────────────┘
           │ parse() → validate against Schema
           ▼
┌───────────────────────┐
│  STAGING              │  Pydantic models: ExcelHistoryRow, BankTxnRow, ...
│  (typed in-memory)    │  All fields validated, types coerced
└──────────┬────────────┘
           │ transform() → normalize, enrich, classify
           ▼
┌───────────────────────┐
│  WAREHOUSE (Postgres) │  26 tables, ER relations enforced
│  L0/L1/L2/L3 layers   │  Append-only for L2
└──────────┬────────────┘
           │ query() → views, aggregates
           ▼
┌───────────────────────┐
│  PUBLISHERS           │  Google Sheet, HTML dashboard,
│  (outputs)            │  WhatsApp replies, P&L Excel, PDF
└───────────────────────┘
```

## 6. Migration Plan (hardcoded → contract-based)

Execute in order. Each step is one session, testable independently.

### Step 1 — Define schemas (no code change to parsers yet)
- Create `src/data/schemas.py`
- Define `ExcelHistoryRow`, `AprilCollectionRow`, `DaywiseRow`, `BankTxnRow`
- Run existing parsers, assert output shapes match schema (tests only, no writes)

### Step 2 — Refactor `import_april.py`
- Replace `COL_ROOM = 1, COL_NAME = 2, ...` with header lookup
- Output `AprilCollectionRow[]`
- Loader stays as-is (just consumes typed rows now)
- Verify: run import, DB totals match before and after

### Step 3 — Refactor `clean_and_load.py::read_history`
- Use header lookup for all columns (already partially does this)
- Output `ExcelHistoryRow[]`
- `excel_import.py` consumes typed rows

### Step 4 — Bank statement unification
- Merge `classify_new_statement.py` + `export_classified.py` bank readers
- Single `bank_yes.py` handles both .xlsx and .csv
- Output `BankTxnRow[]`
- `pnl_report.py` consumes typed rows

### Step 5 — Publisher consolidation
- `sheet.py` subsumes scattered `gsheets.update_*` calls into one "publish view" pattern
- `pnl.py` replaces `pnl_report.py` + `export_classified.py`
- `dashboard.py` replaces dashboard web routes' inline queries

### Step 6 — Lock it down
- Add CI check: fail if any script has `COL_X = N` constants
- Document: "How to add a new data source" (just add a schema + parser + loader mapping)

## 7. What Stays the Same

- SQLAlchemy ORM (`models.py`) — already perfect
- `MONTHLY_HEADERS`, `TENANTS_HEADERS` — already the right pattern
- `pnl_classify.py` rules — already shared across scripts
- Carry-forward + visibility rules in `SHEET_LOGIC.md` — authoritative
- DB layer constraints (FK, unique, check) — already enforce integrity

## 8. Risks + Mitigations

| Risk | Mitigation |
|---|---|
| Breaking the working import during refactor | One migration step per session, verify DB totals match |
| Schema drift in future Excel files | Pydantic validation fails loud with clear error |
| Different staff use different Excel templates | Each template → its own schema; reject unknown ones |
| Bot-logged payments diverge from Excel | Reconciliation doc defines three-way tie-out (Excel ↔ DB ↔ Bank) |

## 9. Approval Checklist

Before starting Step 1:
- [ ] Kiran reviews this doc
- [ ] Identify any entity I missed (should L3 include something? any source missing?)
- [ ] Confirm file layout (`src/data/*`) is acceptable
- [ ] Confirm migration order

After approval, each step becomes a separate implementation task with its own verification.
