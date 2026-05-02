# Finance / P&L Page — Design Spec
**Date:** 2026-05-02  
**Status:** Approved  
**Scope:** PWA Finance page — CSV upload, P&L dashboard, Excel download. Owner-only.

---

## 1. Overview

A Finance page inside the Manage section of the PWA, accessible only to admin-role users. Allows Kiran to upload Yes Bank CSV statements (THOR and HULK accounts), view a P&L dashboard matching the existing Excel output exactly, and download the Excel report.

---

## 2. Data Model — Migrations Only (append to existing tables)

### `bank_uploads` — add 1 column
```sql
ALTER TABLE bank_uploads ADD COLUMN account_name VARCHAR(20) DEFAULT 'THOR';
-- values: 'THOR' | 'HULK'
```

### `bank_transactions` — add 1 column
```sql
ALTER TABLE bank_transactions ADD COLUMN account_name VARCHAR(20) DEFAULT 'THOR';
-- copied from bank_uploads.account_name at insert time
```

No new tables. Everything else already exists:
- `bank_transactions`: id, upload_id, txn_date, description, amount, txn_type, category, sub_category, upi_reference, unique_hash, created_at
- `payments`: payment_mode, for_type, amount, period_month, is_void (income source for cash)

---

## 3. API Endpoints

### `POST /api/v2/finance/upload`
- Auth: admin role required (403 otherwise)
- Body: `multipart/form-data` — `files: File[]` (one or more CSVs), `account_name: "THOR" | "HULK"`
- Logic:
  1. Parse each CSV with `read_yes_bank_csv()` from `export_classified.py`
  2. Classify each transaction with `pnl_classify.classify_txn(desc, typ)`
  3. Insert to `bank_transactions` with dedup via `unique_hash = SHA256(date|amount|desc)`
  4. Set `account_name` on each row and on `bank_uploads` record
- Response: `{ months_affected: ["2026-04", "2026-05"], new_count: 241, duplicate_count: 12 }`

### `GET /api/v2/finance/pnl?month=YYYY-MM`
- Auth: admin role required
- Returns structured P&L for the given month (or all months if no param)
- Income:
  1. `bank_transactions` WHERE `txn_type='income'` AND `category='UPI Batch'` AND month
  2. `bank_transactions` WHERE `txn_type='income'` AND `category != 'UPI Batch'` AND month  
  3. DB cash: `payments` WHERE `payment_mode='cash'` AND `for_type='rent'` AND `is_void=false` AND period_month
- Expenses: `bank_transactions` WHERE `txn_type='expense'` grouped by `category`
- Capital: `bank_transactions` WHERE `category='Capital Investment'` (excluded from income)
- Response schema: `{ month, income: {upi_batch, direct_neft, cash_db, total}, expenses: [{category, amount}], total_expense, operating_profit, margin_pct }`

### `GET /api/v2/finance/pnl/excel?from=YYYY-MM&to=YYYY-MM`
- Auth: admin role required
- Generates Excel using same logic as `export_classified.py` + `export_pnl_2026_05_02.py`
- Same sheet structure: Monthly P&L, Sub-category Breakdown, All Transactions
- Returns file as `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

---

## 4. Classification Rules — Unchanged

Reuses `src/rules/pnl_classify.py` exactly. No modifications.

Same 20 expense categories as current Excel:
Property Rent, Electricity, Water, IT & Software, Internet & WiFi, Food & Groceries, Fuel & Diesel, Staff & Labour, Furniture & Fittings, Maintenance & Repairs, Cleaning Supplies, Waste Disposal, Shopping & Supplies, Operational Expenses, Marketing, Govt & Regulatory, Tenant Deposit Refund, Bank Charges, Capital Investment, Non-Operating, Other Expenses.

Unknown = "Other Expenses" (shown in P&L with no review gate — matches chosen approach A).

---

## 5. PWA Finance Page

### Location
`/finance` — linked from the **home page quick links row** (same row as Checkouts / Notices / Sessions), shown only when `session.user.role === 'admin'`. There is no `/manage` hub page — "Manage" tab routes to `/tenants`. No new nav tab added.

### Page Structure (single scroll, matches approved layout A)
```
1. Header: ← back | Finance | [Owner badge]
2. Month picker: dark pill  ← Apr 2026 →
3. KPI tiles (3): Income (green) / Expense (orange) / Profit (pink)
4. Income card
   - Bank UPI batch settlements   ₹X
   - Bank direct + NEFT            ₹X
   - Cash (PWA recorded)           ₹X
   ─────────────────────────────
   Total Revenue                   ₹X
5. Expense card (category rows, same order as Excel)
6. Upload CSV card
   - Account selector: THOR / HULK (pill toggle)
   - File input: supports multiple files
   - Last upload status: "241 transactions · May 1, 2026"
7. Download Excel button (ghost pill)
```

### State
- Month defaults to current month
- If no bank_transactions exist for selected month → show empty state with "Upload a statement to see P&L"
- If bank_transactions exist but no cash payments → cash row shows ₹0

### Access control
- `GET /finance` redirects to `/` if session role ≠ admin
- Manage page shows Finance link only when `session.user.role === 'admin'`

---

## 6. P&L Logic — Income Source (confirmed SOP match)

```
Total Income = 
  bank_transactions (txn_type=income, category=UPI Batch, month=X)   [UPI batch settlements]
+ bank_transactions (txn_type=income, category≠UPI Batch, month=X)   [direct + NEFT]
+ payments (payment_mode=cash, for_type=rent, is_void=false, period_month=X)  [PWA cash]
```

Capital contributions (`category=Capital Investment`) are **excluded from income**, shown in a separate section below the income card.

---

## 7. Multi-account & Multi-month Upload

- User selects THOR or HULK before uploading (required)
- Multiple CSV files can be uploaded in one submission
- Each transaction stored with its actual `txn_date` — month grouping is by date, not by upload
- Dedup via `unique_hash` — re-uploading overlapping months is safe, no double-counting
- `months_affected` in response tells the user which months were updated

---

## 8. Excel Download — Same as Current Script

Output matches `expense_classified_full.xlsx` sheets:
- Sheet 1: Monthly P&L (Income / OpEx / Operating Profit / CAPEX / Net Profit)
- Sheet 2: Sub-category Breakdown
- Sheet 3: All Transactions (full log with filter)

Download triggered from the Finance page. Range defaults to all months with data; user can optionally filter by date range in a future iteration.

---

## 9. Files to Create / Modify

| File | Change |
|------|--------|
| `src/database/migrate_all.py` | Append: add `account_name` to `bank_uploads` + `bank_transactions` |
| `src/database/models.py` | Add `account_name` field to both models |
| `src/api/v2/finance.py` | New — 3 endpoints (upload, pnl, pnl/excel) |
| `src/rules/pnl_classify.py` | No change — reused as-is |
| `src/parsers/yes_bank.py` | New (extract `read_yes_bank_csv` from export_classified.py) |
| `web/app/finance/page.tsx` | New — Finance dashboard page |
| `web/app/page.tsx` | Add Finance quick link (admin-only, home page row) |
| `web/lib/api.ts` | Add finance API functions |
| `web/components/finance/` | New — UploadCard, PnlCard, KpiTiles |

---

## 10. Deposit Reconciliation (in scope)

When a tenant checks out, a deposit refund is processed. The bank statement records this as a `Tenant Deposit Refund` outflow. The PWA records it in `checkout_records.deposit_refunded_amount`. These need to be matched.

**Formula:** `refundable_deposit = security_deposit_paid − maintenance_fee_retained` (agreed individually per tenant, already tracked in `checkout_records.deposit_refunded_amount`).

**Reconciliation logic:**
- Auto-match: for each `bank_transactions` row where `category = 'Tenant Deposit Refund'`, find a `checkout_records` row where `deposit_refunded_amount = bank.amount` AND `deposit_refund_date BETWEEN txn_date − 7 days AND txn_date + 7 days`
- Store match: add `reconciled_checkout_id` (nullable FK → `checkout_records.id`) to `bank_transactions`
- Status per bank row: `matched` | `unmatched`

**Finance page — Reconciliation section** (below expenses card):
- List of bank `Tenant Deposit Refund` transactions for the selected month
- Each row shows: date, amount, status badge (Matched / Unmatched), matched tenant name
- Unmatched rows shown in orange — flag for manual review

**New migration:** `bank_transactions.reconciled_checkout_id INTEGER REFERENCES checkout_records(id)`

## 11. Out of Scope (deferred)

- Manual transaction category overrides in UI
- Yes Bank live API integration
- Multi-month range selector for Excel download (future)
- UPI payment reconciliation (match bank credits to PWA rent payments)
