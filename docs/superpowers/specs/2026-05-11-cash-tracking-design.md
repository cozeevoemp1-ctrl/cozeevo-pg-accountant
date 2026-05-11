# Cash Tracking — Design Spec
Date: 2026-05-11

## Problem

Cash rent collections are in the DB (payments.payment_mode='cash') but cash expenses
paid out of that cash — vendor payments, staff salary, police, bank deposits — are not
tracked anywhere. The P&L currently has hardcoded cash-in-hand figures (Lakshmi
₹10,63,500 + Prabhakaran ₹8,23,350) that must be manually updated each month.
There is no way to see real-time cash position or month-wise cash flow in the app.

## Goal

A Cash tab on the Finance page that shows:
- How much cash was collected as rent this month (auto, from DB)
- How much cash went out as expenses this month (manually logged)
- Net cash in hand = collected − expenses
- Month-wise history table
- Add/void cash expense entries

## Decisions Made

| Question | Decision |
|----------|----------|
| Where in app | Finance page → new Cash tab |
| Who can access | Admin only (same as Finance page) |
| Per-holder tracking | No — single business total |
| Cash IN source | Auto-pulled from payments table (payment_mode='cash', for_type='rent', is_void=false) |
| Cash OUT | Manually logged expense entries |
| Add expense fields | Date, Description, Amount, Paid by (Prabhakaran / Lakshmi / Other) |

---

## Data Model

### New table: `cash_expenses`

```sql
CREATE TABLE cash_expenses (
    id          SERIAL PRIMARY KEY,
    date        DATE NOT NULL,
    description TEXT NOT NULL,
    amount      NUMERIC(12,2) NOT NULL,
    paid_by     VARCHAR(100) NOT NULL,  -- 'Prabhakaran', 'Lakshmi', 'Other'
    is_void     BOOLEAN NOT NULL DEFAULT false,
    voided_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  VARCHAR(100)           -- email of admin who logged it
);
```

No building/account split — single table for the whole business.

### New table: `cash_counts`

Physical cash count log — Prabhakaran or Lakshmi physically counts the cash and records it
so the app can show the variance against the calculated balance.

```sql
CREATE TABLE cash_counts (
    id          SERIAL PRIMARY KEY,
    date        DATE NOT NULL,
    amount      NUMERIC(12,2) NOT NULL,
    counted_by  VARCHAR(100) NOT NULL,  -- 'Prabhakaran', 'Lakshmi'
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

No void — this is append-only log. Multiple counts per day are fine.

---

## API

### GET `/api/v2/finance/cash?month=YYYY-MM`

Returns:
```json
{
  "month": "2026-05",
  "collected": 1343783,
  "expenses_total": 206150,
  "balance": 1137633,
  "last_count": {
    "id": 3,
    "date": "2026-05-11",
    "amount": 1123000,
    "counted_by": "Prabhakaran",
    "variance": 14633
  },
  "expenses": [
    {
      "id": 1,
      "date": "2026-05-05",
      "description": "Water — Manoj B",
      "amount": 42500,
      "paid_by": "Prabhakaran",
      "is_void": false
    }
  ],
  "history": [
    { "month": "2026-05", "collected": 1343783, "expenses": 206150, "balance": 1137633 },
    { "month": "2026-04", "collected": 1343783, "expenses": 321000, "balance": 1022783 }
  ]
}
```

`collected` = SUM of payments WHERE payment_mode='cash' AND for_type='rent'
             AND is_void=false AND payment_date in month.

`history` = last 6 months, same formula per month.

`last_count` = most recent cash_counts row for the selected month.
`variance` = balance − last_count.amount (positive = more cash than expected, negative = short).

### POST `/api/v2/finance/cash/expenses`

Body: `{ date, description, amount, paid_by }`
Auth: admin only.
Returns: created expense object.

### DELETE `/api/v2/finance/cash/expenses/{id}`

Soft-delete: sets is_void=true, voided_at=now().
Admin only.

### POST `/api/v2/finance/cash/counts`

Body: `{ date, amount, counted_by, notes? }`
Auth: admin only.
Returns: created count object with variance field (balance − amount).

---

## PWA — Finance Page Cash Tab

### Tab bar
Finance page currently has tabs: P&L | Upload | Deposits (or similar).
Add **Cash** as a new tab. No changes to other tabs.

### Cash tab layout (top to bottom)

1. **Month picker** — same `‹ May 2026 ›` pattern used on Collection page
2. **Big balance card** — dark card showing "Cash in hand ₹X" with subtitle "Collected ₹X — Expenses ₹X"
3. **Two stat cards** side by side — Collected (green) | Expenses (red)
   - Collected card has hint: "Auto · from rent payments"
4. **Count check card** — shows last physical count vs calculated balance
   - "Last count: ₹X · May 11 · Prabhakaran"
   - Variance line: "₹X short" (red) or "₹X over" (amber) or "Matches" (green)
   - "+ Log count" button on the right
5. **Section label** "Cash expenses"
6. **Expense list card** — header shows count + total with "+ Add expense" button
   - Each row: description | meta (date · paid by) | amount in red
   - Tap row → shows void option (two-tap confirm)
7. **Section label** "Month history"
8. **History table** — Month | Collected | Expenses | Balance (last 6 months)

### Add expense sheet

Slides up from bottom (same pattern as existing sheets in the app).
Fields:
- Date (date picker, default today)
- Description (text input)
- Amount ₹ (numeric input)
- Paid by (pill selector: Prabhakaran | Lakshmi | Other)

Submit → POST to API → refreshes expense list and balance.

### Log count sheet

Slides up from bottom.
Fields:
- Date (date picker, default today)
- Amount counted ₹ (numeric input)
- Counted by (pill selector: Prabhakaran | Lakshmi)
- Notes (optional text, e.g. "counted before depositing to bank")

Submit → POST to API → refreshes count check card + shows variance immediately.

### Data fetching

Client component. On mount and on month change: fetch `/api/v2/finance/cash?month=YYYY-MM`.
No server-side prefetch needed (Finance page is already client-heavy).

---

## Migration

Append to `src/database/migrate_all.py`:

```python
CREATE TABLE IF NOT EXISTS cash_expenses (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    description TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    paid_by VARCHAR(100) NOT NULL,
    is_void BOOLEAN NOT NULL DEFAULT false,
    voided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS cash_counts (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    counted_by VARCHAR(100) NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Files to create / modify

| File | Action |
|------|--------|
| `src/database/migrate_all.py` | Append cash_expenses + cash_counts migrations |
| `src/api/v2/finance.py` | Add GET /cash, POST+DELETE /cash/expenses, POST /cash/counts |
| `web/app/finance/page.tsx` | Add Cash tab to tab switcher |
| `web/components/finance/cash-tab.tsx` | New component — full Cash tab UI |
| `web/lib/api.ts` | Add getCashPosition(), addCashExpense(), voidCashExpense(), logCashCount() |

---

## Out of scope

- Per-holder balance tracking (decided: single business total)
- Cash transfer between holders
- WhatsApp bot integration for logging expenses
- Receipts / photo upload for expenses
- Export to Excel
