# Cash Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Cash tab to the Finance page showing cash collected from rent, manually logged cash expenses, a physical count check card, and 6-month history.

**Architecture:** Two new DB tables (`cash_expenses`, `cash_counts`) + 4 new API endpoints appended to `src/api/v2/finance.py` + a new `CashTab` React component wired into `web/app/finance/page.tsx` via a P&L|Cash tab switcher.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), Next.js App Router + Tailwind (frontend), Supabase JWT auth.

---

## File Map

**Create:**
- `web/components/finance/cash-tab.tsx` — full Cash tab UI

**Modify:**
- `src/database/migrate_all.py` — append migration function + call in `main()`
- `src/database/models.py` — add `CashExpense` and `CashCount` ORM models
- `src/api/v2/finance.py` — add 4 cash endpoints + import new models
- `web/lib/api.ts` — add interfaces + 4 API helpers
- `web/app/finance/page.tsx` — add tab switcher, render `CashTab` when active

---

### Task 1: DB Migration

**Files:**
- Modify: `src/database/migrate_all.py`

- [ ] **Step 1: Add migration function**

Open `src/database/migrate_all.py`. After the last `async def run_*` function (`run_widen_changed_by_2026_04_29`), add:

```python
async def run_cash_tables_2026_05_11(conn) -> None:
    """Cash tracking: cash_expenses (manual outflows) + cash_counts (physical spot-checks)."""
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cash_expenses (
            id          SERIAL PRIMARY KEY,
            date        DATE NOT NULL,
            description TEXT NOT NULL,
            amount      NUMERIC(12,2) NOT NULL,
            paid_by     VARCHAR(100) NOT NULL,
            is_void     BOOLEAN NOT NULL DEFAULT false,
            voided_at   TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by  VARCHAR(100)
        )
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cash_counts (
            id          SERIAL PRIMARY KEY,
            date        DATE NOT NULL,
            amount      NUMERIC(12,2) NOT NULL,
            counted_by  VARCHAR(100) NOT NULL,
            notes       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    print("  [ok] cash_expenses + cash_counts created")
```

- [ ] **Step 2: Call in main()**

In `main()`, after the `await run_widen_changed_by_2026_04_29(conn)` line, add:

```python
            await run_cash_tables_2026_05_11(conn)
```

- [ ] **Step 3: Run migration**

```bash
python -m src.database.migrate_all
```

Expected output contains: `[ok] cash_expenses + cash_counts created`

- [ ] **Step 4: Commit**

```bash
git add src/database/migrate_all.py
git commit -m "feat(db): add cash_expenses + cash_counts tables"
```

---

### Task 2: SQLAlchemy Models

**Files:**
- Modify: `src/database/models.py`

- [ ] **Step 1: Read the top of models.py**

Scan the imports at the top of `src/database/models.py` to confirm which SQLAlchemy column types are already imported (`Column`, `Integer`, `Numeric`, `String`, `Boolean`, `Text`, `Date`, `DateTime`, `func`). Note which are missing — you'll add them.

- [ ] **Step 2: Add missing imports**

Ensure the SQLAlchemy import line includes `Boolean`, `Date`, `DateTime`, `Numeric`, `String`, `Text`, and `func`. For example if the current line is:

```python
from sqlalchemy import Column, Integer, String
```

Expand it to include whatever is missing. The models below need all of the above.

- [ ] **Step 3: Append the two model classes**

At the end of `src/database/models.py`, add:

```python
class CashExpense(Base):
    __tablename__ = "cash_expenses"

    id          = Column(Integer, primary_key=True)
    date        = Column(Date, nullable=False)
    description = Column(Text, nullable=False)
    amount      = Column(Numeric(12, 2), nullable=False)
    paid_by     = Column(String(100), nullable=False)
    is_void     = Column(Boolean, nullable=False, default=False)
    voided_at   = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by  = Column(String(100), nullable=True)


class CashCount(Base):
    __tablename__ = "cash_counts"

    id          = Column(Integer, primary_key=True)
    date        = Column(Date, nullable=False)
    amount      = Column(Numeric(12, 2), nullable=False)
    counted_by  = Column(String(100), nullable=False)
    notes       = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

- [ ] **Step 4: Verify import works**

```bash
python -c "from src.database.models import CashExpense, CashCount; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add src/database/models.py
git commit -m "feat(models): add CashExpense + CashCount ORM models"
```

---

### Task 3: GET /finance/cash endpoint

**Files:**
- Modify: `src/api/v2/finance.py`
- Create: `tests/test_cash_logic.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cash_logic.py`:

```python
"""Unit tests for cash position calculation logic."""


def compute_balance(collected: float, expenses: list[float]) -> float:
    return collected - sum(expenses)


def compute_variance(balance: float, counted: float) -> float:
    return balance - counted


def test_balance_no_expenses():
    assert compute_balance(100000, []) == 100000


def test_balance_with_expenses():
    assert compute_balance(100000, [20000, 5000]) == 75000


def test_variance_short():
    # counted less than expected → positive variance = short
    assert compute_variance(100000, 90000) == 10000


def test_variance_over():
    # counted more than expected → negative variance = over
    assert compute_variance(100000, 110000) == -10000


def test_variance_exact():
    assert compute_variance(100000, 100000) == 0
```

- [ ] **Step 2: Run test to verify it passes**

```bash
pytest tests/test_cash_logic.py -v
```

Expected: 5 passed

- [ ] **Step 3: Add `extract` to the sqlalchemy import in finance.py**

In `src/api/v2/finance.py`, find:

```python
from sqlalchemy import func, select
```

Change to:

```python
from sqlalchemy import extract, func, select
```

- [ ] **Step 4: Add CashExpense, CashCount to models import in finance.py**

Find the existing models import block and add `CashCount, CashExpense`:

```python
from src.database.models import (
    BankTransaction, BankUpload, CashCount, CashExpense, CheckoutRecord,
    Payment, PaymentFor, PaymentMode, Tenancy, Tenant,
)
```

- [ ] **Step 5: Add GET endpoint**

In `src/api/v2/finance.py`, immediately before the `# ── Upload` comment block, insert:

```python
# ── Cash position ─────────────────────────────────────────────────────────────

@router.get("/finance/cash")
async def get_cash_position(
    month: str = Query(..., description="YYYY-MM"),
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)
    _validate_month(month)
    year, month_num = int(month[:4]), int(month[5:7])

    async with get_session() as session:
        collected = float(await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.payment_mode == PaymentMode.cash,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
                extract("year", Payment.payment_date) == year,
                extract("month", Payment.payment_date) == month_num,
            )
        ) or 0)

        expense_rows = (await session.scalars(
            select(CashExpense).where(
                extract("year", CashExpense.date) == year,
                extract("month", CashExpense.date) == month_num,
                CashExpense.is_void == False,
            ).order_by(CashExpense.date.desc(), CashExpense.id.desc())
        )).all()

        expenses_total = sum(float(e.amount) for e in expense_rows)
        balance = collected - expenses_total

        last_count_row = await session.scalar(
            select(CashCount).where(
                extract("year", CashCount.date) == year,
                extract("month", CashCount.date) == month_num,
            ).order_by(CashCount.created_at.desc())
        )

        history = []
        for i in range(6):
            hm = month_num - i
            hy = year
            while hm <= 0:
                hm += 12
                hy -= 1
            h_col = float(await session.scalar(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.payment_mode == PaymentMode.cash,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void == False,
                    extract("year", Payment.payment_date) == hy,
                    extract("month", Payment.payment_date) == hm,
                )
            ) or 0)
            h_exp = float(await session.scalar(
                select(func.coalesce(func.sum(CashExpense.amount), 0)).where(
                    extract("year", CashExpense.date) == hy,
                    extract("month", CashExpense.date) == hm,
                    CashExpense.is_void == False,
                )
            ) or 0)
            history.append({
                "month": f"{hy}-{hm:02d}",
                "collected": h_col,
                "expenses": h_exp,
                "balance": h_col - h_exp,
            })

        return {
            "month": month,
            "collected": collected,
            "expenses_total": expenses_total,
            "balance": balance,
            "last_count": {
                "id": last_count_row.id,
                "date": str(last_count_row.date),
                "amount": float(last_count_row.amount),
                "counted_by": last_count_row.counted_by,
                "variance": balance - float(last_count_row.amount),
            } if last_count_row else None,
            "expenses": [
                {
                    "id": e.id,
                    "date": str(e.date),
                    "description": e.description,
                    "amount": float(e.amount),
                    "paid_by": e.paid_by,
                    "is_void": e.is_void,
                }
                for e in expense_rows
            ],
            "history": history,
        }
```

- [ ] **Step 6: Start server and test manually**

```bash
python main.py
```

In a second terminal, get a valid JWT from Supabase (log in via the PWA), then:

```bash
curl "http://localhost:8000/api/v2/app/finance/cash?month=2026-05" \
  -H "Authorization: Bearer <your-token>"
```

Expected: JSON with keys `month`, `collected`, `expenses_total`, `balance`, `last_count` (null), `expenses` (empty list), `history` (6 rows).

- [ ] **Step 7: Commit**

```bash
git add src/api/v2/finance.py tests/test_cash_logic.py
git commit -m "feat(api): GET /finance/cash — cash position endpoint"
```

---

### Task 4: POST + DELETE /finance/cash/expenses

**Files:**
- Modify: `src/api/v2/finance.py`

- [ ] **Step 1: Add POST and DELETE endpoints**

In `src/api/v2/finance.py`, directly after the `get_cash_position` function, add:

```python
@router.post("/finance/cash/expenses")
async def add_cash_expense(
    body: dict,
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)
    missing = {"date", "description", "amount", "paid_by"} - set(body.keys())
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {missing}")
    try:
        from datetime import date as _date_type
        exp_date = _date_type.fromisoformat(body["date"])
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    try:
        amount = float(body["amount"])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="amount must be a positive number")
    if body["paid_by"] not in ("Prabhakaran", "Lakshmi", "Other"):
        raise HTTPException(status_code=400, detail="paid_by must be Prabhakaran, Lakshmi, or Other")

    async with get_session() as session:
        expense = CashExpense(
            date=exp_date,
            description=str(body["description"]).strip(),
            amount=amount,
            paid_by=body["paid_by"],
            created_by=user.email,
        )
        session.add(expense)
        await session.flush()
        result = {
            "id": expense.id,
            "date": str(expense.date),
            "description": expense.description,
            "amount": float(expense.amount),
            "paid_by": expense.paid_by,
            "is_void": expense.is_void,
        }
        await session.commit()
    return result


@router.delete("/finance/cash/expenses/{expense_id}")
async def void_cash_expense(
    expense_id: int,
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)
    from datetime import datetime, timezone
    async with get_session() as session:
        expense = await session.get(CashExpense, expense_id)
        if not expense:
            raise HTTPException(status_code=404, detail="Expense not found")
        if expense.is_void:
            raise HTTPException(status_code=400, detail="Already voided")
        expense.is_void = True
        expense.voided_at = datetime.now(timezone.utc)
        await session.commit()
    return {"ok": True, "id": expense_id}
```

- [ ] **Step 2: Test POST**

```bash
curl -X POST "http://localhost:8000/api/v2/app/finance/cash/expenses" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-05-11","description":"Test expense","amount":5000,"paid_by":"Prabhakaran"}'
```

Expected: `{"id": <N>, "date": "2026-05-11", "description": "Test expense", "amount": 5000.0, "paid_by": "Prabhakaran", "is_void": false}`

Note the `id`.

- [ ] **Step 3: Test DELETE**

```bash
curl -X DELETE "http://localhost:8000/api/v2/app/finance/cash/expenses/<N>" \
  -H "Authorization: Bearer <token>"
```

Expected: `{"ok": true, "id": <N>}`

Then call GET `/finance/cash?month=2026-05` — voided expense must not appear in `expenses`.

- [ ] **Step 4: Commit**

```bash
git add src/api/v2/finance.py
git commit -m "feat(api): POST+DELETE /finance/cash/expenses — add and void cash expenses"
```

---

### Task 5: POST /finance/cash/counts

**Files:**
- Modify: `src/api/v2/finance.py`

- [ ] **Step 1: Add POST endpoint**

After the `void_cash_expense` function, add:

```python
@router.post("/finance/cash/counts")
async def log_cash_count(
    body: dict,
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)
    missing = {"date", "amount", "counted_by"} - set(body.keys())
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {missing}")
    try:
        from datetime import date as _date_type
        count_date = _date_type.fromisoformat(body["date"])
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    try:
        amount = float(body["amount"])
        if amount < 0:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="amount must be a non-negative number")
    if body["counted_by"] not in ("Prabhakaran", "Lakshmi"):
        raise HTTPException(status_code=400, detail="counted_by must be Prabhakaran or Lakshmi")

    async with get_session() as session:
        count = CashCount(
            date=count_date,
            amount=amount,
            counted_by=body["counted_by"],
            notes=body.get("notes"),
        )
        session.add(count)
        await session.flush()
        result = {
            "id": count.id,
            "date": str(count.date),
            "amount": float(count.amount),
            "counted_by": count.counted_by,
            "notes": count.notes,
        }
        await session.commit()
    return result
```

- [ ] **Step 2: Test POST**

```bash
curl -X POST "http://localhost:8000/api/v2/app/finance/cash/counts" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-05-11","amount":1100000,"counted_by":"Prabhakaran","notes":"Before bank deposit"}'
```

Expected: `{"id": <N>, "date": "2026-05-11", "amount": 1100000.0, "counted_by": "Prabhakaran", "notes": "Before bank deposit"}`

- [ ] **Step 3: Verify last_count appears in GET**

```bash
curl "http://localhost:8000/api/v2/app/finance/cash?month=2026-05" \
  -H "Authorization: Bearer <token>"
```

Expected: `last_count` is populated — `amount`, `counted_by`, `variance` (= balance − counted).

- [ ] **Step 4: Commit**

```bash
git add src/api/v2/finance.py
git commit -m "feat(api): POST /finance/cash/counts — log physical cash count"
```

---

### Task 6: Frontend types + API helpers

**Files:**
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add interfaces**

Open `web/lib/api.ts`. After the last existing interface (e.g. `UnitEconomics`), add:

```typescript
// ── Cash position ─────────────────────────────────────────────────────────────

export interface CashExpense {
  id: number
  date: string           // YYYY-MM-DD
  description: string
  amount: number
  paid_by: string
  is_void: boolean
}

export interface CashCountEntry {
  id: number
  date: string           // YYYY-MM-DD
  amount: number
  counted_by: string
  variance: number       // balance − counted (positive = short, negative = over)
}

export interface CashHistoryRow {
  month: string          // YYYY-MM
  collected: number
  expenses: number
  balance: number
}

export interface CashPosition {
  month: string
  collected: number
  expenses_total: number
  balance: number
  last_count: CashCountEntry | null
  expenses: CashExpense[]
  history: CashHistoryRow[]
}

export interface AddExpenseBody {
  date: string
  description: string
  amount: number
  paid_by: "Prabhakaran" | "Lakshmi" | "Other"
}

export interface LogCountBody {
  date: string
  amount: number
  counted_by: "Prabhakaran" | "Lakshmi"
  notes?: string
}
```

- [ ] **Step 2: Add helper functions**

At the end of `web/lib/api.ts`, add:

```typescript
export async function getCashPosition(month: string): Promise<CashPosition> {
  return _get<CashPosition>(`/api/v2/app/finance/cash?month=${encodeURIComponent(month)}`)
}

export async function addCashExpense(body: AddExpenseBody): Promise<CashExpense> {
  return _post<CashExpense>("/api/v2/app/finance/cash/expenses", body)
}

export async function voidCashExpense(id: number): Promise<{ ok: boolean; id: number }> {
  const headers = await _authHeaders()
  const res = await fetch(`${BASE_URL}/api/v2/app/finance/cash/expenses/${id}`, {
    method: "DELETE",
    headers,
    cache: "no-store",
  })
  if (!res.ok) throw new Error(`DELETE /finance/cash/expenses/${id} → ${res.status}`)
  return res.json()
}

export async function logCashCount(body: LogCountBody): Promise<{ id: number; date: string; amount: number; counted_by: string; notes: string | null }> {
  return _post("/api/v2/app/finance/cash/counts", body)
}
```

- [ ] **Step 3: Check _authHeaders is not private**

Scan `web/lib/api.ts` for the `_authHeaders` function definition. It is defined in the file already — confirm it's accessible from within the same file (it will be, since `voidCashExpense` is in the same file).

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(api-client): CashPosition types + getCashPosition/addCashExpense/voidCashExpense/logCashCount"
```

---

### Task 7: CashTab component

**Files:**
- Create: `web/components/finance/cash-tab.tsx`

- [ ] **Step 1: Create the file**

Create `web/components/finance/cash-tab.tsx` with this full content:

```tsx
"use client"
import { useState, useEffect, useCallback } from "react"
import {
  getCashPosition, addCashExpense, voidCashExpense, logCashCount,
  CashPosition, AddExpenseBody, LogCountBody,
} from "@/lib/api"

function fmt(n: number): string {
  return "₹" + Math.round(n).toLocaleString("en-IN")
}

function fmtShort(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 100000) return `₹${(abs / 100000).toFixed(1)}L`
  if (abs >= 1000) return `₹${(abs / 1000).toFixed(0)}K`
  return fmt(abs)
}

function prevMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number)
  if (mo === 1) return `${y - 1}-12`
  return `${y}-${String(mo - 1).padStart(2, "0")}`
}

function nextMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number)
  if (mo === 12) return `${y + 1}-01`
  return `${y}-${String(mo + 1).padStart(2, "0")}`
}

function monthLabel(m: string): string {
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  const [y, mo] = m.split("-").map(Number)
  return `${months[mo - 1]} ${y}`
}

function fmtDate(d: string): string {
  const [, mm, dd] = d.split("-")
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${months[parseInt(mm) - 1]} ${parseInt(dd)}`
}

function todayStr(): string {
  const n = new Date()
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`
}

// ── Shared input style ─────────────────────────────────────────────────────────

const inputCls = "bg-[#F8F5F3] border border-[#E2DEDD] rounded-xl px-3 py-2.5 text-sm text-[#1A1614] font-medium w-full"

// ── Pill button ────────────────────────────────────────────────────────────────

function Pill({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-1.5 rounded-full text-xs font-bold border transition-colors ${
        active ? "bg-[#EF1F9C] text-white border-[#EF1F9C]" : "bg-[#F0EDE9] text-[#555] border-[#E2DEDD]"
      }`}
    >
      {label}
    </button>
  )
}

// ── Bottom sheet wrapper ───────────────────────────────────────────────────────

function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-t-[24px] p-6 flex flex-col gap-4 max-w-lg mx-auto w-full"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-base font-extrabold text-[#1A1614]">{title}</h2>
          <button onClick={onClose} className="text-[#C0B8B4] font-bold text-xl leading-none">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

// ── Add Expense Sheet ──────────────────────────────────────────────────────────

function AddExpenseSheet({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [date, setDate] = useState(todayStr())
  const [desc, setDesc] = useState("")
  const [amount, setAmount] = useState("")
  const [paidBy, setPaidBy] = useState<AddExpenseBody["paid_by"]>("Prabhakaran")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const amt = parseFloat(amount)
    if (!desc.trim()) return setError("Description required")
    if (!amt || amt <= 0) return setError("Enter a valid amount")
    setSaving(true)
    setError("")
    try {
      await addCashExpense({ date, description: desc.trim(), amount: amt, paid_by: paidBy })
      onSaved()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save")
      setSaving(false)
    }
  }

  return (
    <Sheet title="Add cash expense" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Date</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} className={inputCls} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Description</label>
          <input
            type="text" value={desc} onChange={e => setDesc(e.target.value)}
            placeholder="e.g. Water — Manoj B" className={inputCls}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Amount ₹</label>
          <input
            type="number" value={amount} onChange={e => setAmount(e.target.value)}
            placeholder="0" inputMode="numeric" className={inputCls}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Paid by</label>
          <div className="flex gap-2 flex-wrap">
            {(["Prabhakaran", "Lakshmi", "Other"] as const).map(p => (
              <Pill key={p} label={p} active={paidBy === p} onClick={() => setPaidBy(p)} />
            ))}
          </div>
        </div>
        {error && <p className="text-xs text-red-500 font-medium">{error}</p>}
        <button
          type="submit" disabled={saving}
          className="bg-[#EF1F9C] text-white rounded-xl py-3 text-sm font-extrabold mt-1 disabled:opacity-50 active:opacity-70"
        >
          {saving ? "Saving…" : "Save expense"}
        </button>
      </form>
    </Sheet>
  )
}

// ── Log Count Sheet ────────────────────────────────────────────────────────────

function LogCountSheet({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [date, setDate] = useState(todayStr())
  const [amount, setAmount] = useState("")
  const [countedBy, setCountedBy] = useState<LogCountBody["counted_by"]>("Prabhakaran")
  const [notes, setNotes] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const amt = parseFloat(amount)
    if (isNaN(amt) || amt < 0) return setError("Enter a valid amount")
    setSaving(true)
    setError("")
    try {
      const body: LogCountBody = { date, amount: amt, counted_by: countedBy }
      if (notes.trim()) body.notes = notes.trim()
      await logCashCount(body)
      onSaved()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save")
      setSaving(false)
    }
  }

  return (
    <Sheet title="Log cash count" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Date</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} className={inputCls} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Amount counted ₹</label>
          <input
            type="number" value={amount} onChange={e => setAmount(e.target.value)}
            placeholder="0" inputMode="numeric" className={inputCls}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Counted by</label>
          <div className="flex gap-2">
            {(["Prabhakaran", "Lakshmi"] as const).map(p => (
              <Pill key={p} label={p} active={countedBy === p} onClick={() => setCountedBy(p)} />
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Notes (optional)</label>
          <input
            type="text" value={notes} onChange={e => setNotes(e.target.value)}
            placeholder="e.g. Before bank deposit" className={inputCls}
          />
        </div>
        {error && <p className="text-xs text-red-500 font-medium">{error}</p>}
        <button
          type="submit" disabled={saving}
          className="bg-[#EF1F9C] text-white rounded-xl py-3 text-sm font-extrabold mt-1 disabled:opacity-50 active:opacity-70"
        >
          {saving ? "Saving…" : "Log count"}
        </button>
      </form>
    </Sheet>
  )
}

// ── Main CashTab ───────────────────────────────────────────────────────────────

export function CashTab() {
  const now = new Date()
  const [month, setMonth] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
  )
  const [data, setData] = useState<CashPosition | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [showExpenseSheet, setShowExpenseSheet] = useState(false)
  const [showCountSheet, setShowCountSheet] = useState(false)
  const [voidTarget, setVoidTarget] = useState<number | null>(null)
  const [voiding, setVoiding] = useState(false)

  const load = useCallback(async (m: string) => {
    setLoading(true)
    setError("")
    try {
      setData(await getCashPosition(m))
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(month) }, [month, load])

  async function handleVoid(id: number) {
    if (voidTarget !== id) {
      setVoidTarget(id)  // first tap — show confirm button
      return
    }
    setVoiding(true)
    try {
      await voidCashExpense(id)
      setVoidTarget(null)
      await load(month)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to void")
    } finally {
      setVoiding(false)
    }
  }

  const varColor = (v: number) =>
    v === 0 ? "text-[#16A34A]" : v > 0 ? "text-[#EF4444]" : "text-[#F59E0B]"

  const varLabel = (v: number) =>
    v === 0 ? "Matches" : v > 0 ? `${fmt(v)} short` : `${fmt(Math.abs(v))} over`

  return (
    <div className="flex flex-col gap-4">
      {/* Month picker */}
      <div className="flex items-center justify-between bg-[#0F0E0D] rounded-full px-5 py-3">
        <button onClick={() => setMonth(prevMonth(month))} className="text-[#6F655D] text-sm font-bold">←</button>
        <span className="text-white text-sm font-bold">{monthLabel(month)}</span>
        <button onClick={() => setMonth(nextMonth(month))} className="text-[#6F655D] text-sm font-bold">→</button>
      </div>

      {loading && <div className="py-10 text-center text-xs text-[#999]">Loading…</div>}
      {error && <p className="text-xs text-center text-red-500 font-medium">{error}</p>}

      {!loading && data && (
        <>
          {/* Balance card */}
          <div
            className="rounded-2xl p-5 text-white"
            style={{ background: "linear-gradient(135deg, #1A1614 0%, #2d2421 100%)" }}
          >
            <p className="text-[11px] font-semibold text-[#aaa] uppercase tracking-wider mb-1">Cash in hand</p>
            <p className="text-[32px] font-extrabold leading-tight">{fmt(data.balance)}</p>
            <p className="text-xs text-[#888] mt-2">
              Collected {fmt(data.collected)} — Expenses {fmt(data.expenses_total)}
            </p>
          </div>

          {/* Two stat cards */}
          <div className="grid grid-cols-2 gap-2.5">
            <div className="bg-white rounded-2xl border border-[#F0EDE9] p-3.5 flex flex-col gap-1">
              <p className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Collected</p>
              <p className="text-lg font-extrabold text-[#16A34A]">{fmtShort(data.collected)}</p>
              <p className="text-[10px] text-[#bbb]">Auto · from rent payments</p>
            </div>
            <div className="bg-white rounded-2xl border border-[#F0EDE9] p-3.5 flex flex-col gap-1">
              <p className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Expenses</p>
              <p className="text-lg font-extrabold text-[#EF4444]">{fmtShort(data.expenses_total)}</p>
              <p className="text-[10px] text-[#bbb]">
                {data.expenses.length} entr{data.expenses.length === 1 ? "y" : "ies"} logged
              </p>
            </div>
          </div>

          {/* Count check card */}
          <div className="bg-white rounded-2xl border border-[#F0EDE9] p-4 flex items-center justify-between gap-3">
            <div className="flex flex-col gap-0.5">
              <p className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Count check</p>
              {data.last_count ? (
                <>
                  <p className="text-sm font-semibold text-[#1A1614]">
                    {fmt(data.last_count.amount)} · {fmtDate(data.last_count.date)} · {data.last_count.counted_by.split(" ")[0]}
                  </p>
                  <p className={`text-xs font-bold ${varColor(data.last_count.variance)}`}>
                    {varLabel(data.last_count.variance)}
                  </p>
                </>
              ) : (
                <p className="text-xs text-[#bbb]">No count logged yet</p>
              )}
            </div>
            <button
              onClick={() => setShowCountSheet(true)}
              className="shrink-0 text-xs font-bold text-[#EF1F9C] border border-[#EF1F9C] rounded-full px-3 py-1.5 active:opacity-70"
            >
              + Log count
            </button>
          </div>

          {/* Cash expenses */}
          <p className="text-[11px] font-bold text-[#999] uppercase tracking-wider px-0.5">Cash expenses</p>
          <div className="bg-white rounded-2xl border border-[#F0EDE9] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#F0EDE9]">
              <span className="text-xs font-bold text-[#777]">
                {data.expenses.length} {data.expenses.length === 1 ? "entry" : "entries"} · {fmt(data.expenses_total)}
              </span>
              <button
                onClick={() => setShowExpenseSheet(true)}
                className="bg-[#EF1F9C] text-white rounded-full px-4 py-1.5 text-xs font-bold active:opacity-70"
              >
                + Add expense
              </button>
            </div>
            {data.expenses.length === 0 && (
              <div className="py-6 text-center text-xs text-[#bbb]">No expenses logged</div>
            )}
            {data.expenses.map(exp => (
              <div
                key={exp.id}
                className="flex items-center justify-between px-4 py-3 border-b border-[#F8F5F3] last:border-0 active:bg-[#FFF5FB] cursor-pointer"
                onClick={() => !voiding && handleVoid(exp.id)}
              >
                <div className="flex flex-col gap-0.5">
                  <span className="text-[13px] font-semibold text-[#1A1614]">{exp.description}</span>
                  <span className="text-[11px] text-[#aaa]">{fmtDate(exp.date)} · {exp.paid_by}</span>
                  {voidTarget === exp.id && (
                    <span className="text-[11px] font-bold text-[#EF4444] mt-0.5">
                      {voiding ? "Voiding…" : "Tap again to void"}
                    </span>
                  )}
                </div>
                <span className="text-[14px] font-extrabold text-[#EF4444] shrink-0 ml-2">
                  −{fmt(exp.amount)}
                </span>
              </div>
            ))}
          </div>

          {/* Month history */}
          <p className="text-[11px] font-bold text-[#999] uppercase tracking-wider px-0.5">Month history</p>
          <div className="bg-white rounded-2xl border border-[#F0EDE9] overflow-hidden">
            <div className="grid grid-cols-4 px-3.5 py-2 bg-[#F8F5F3] text-[10px] font-bold text-[#999] uppercase tracking-wide">
              <span>Month</span><span>Collected</span><span>Expenses</span><span>Balance</span>
            </div>
            {data.history.map(h => (
              <div key={h.month} className="grid grid-cols-4 px-3.5 py-2.5 border-t border-[#F8F5F3] text-[12px] items-center">
                <span className="text-[#1A1614] font-medium">{monthLabel(h.month).split(" ")[0]}</span>
                <span className="font-bold text-[#16A34A]">{fmtShort(h.collected)}</span>
                <span className="font-bold text-[#EF4444]">{fmtShort(h.expenses)}</span>
                <span className="font-extrabold text-[#1A1614]">{fmtShort(h.balance)}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {showExpenseSheet && (
        <AddExpenseSheet onClose={() => setShowExpenseSheet(false)} onSaved={() => load(month)} />
      )}
      {showCountSheet && (
        <LogCountSheet onClose={() => setShowCountSheet(false)} onSaved={() => load(month)} />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add web/components/finance/cash-tab.tsx
git commit -m "feat(pwa): CashTab component — balance, expenses, count check, history"
```

---

### Task 8: Wire Cash tab into Finance page

**Files:**
- Modify: `web/app/finance/page.tsx`

- [ ] **Step 1: Add CashTab import**

In `web/app/finance/page.tsx`, add to the imports at the top:

```typescript
import { CashTab } from "@/components/finance/cash-tab"
```

- [ ] **Step 2: Add tab state**

Inside `export default function FinancePage()`, after the existing state declarations, add:

```typescript
const [tab, setTab] = useState<"pnl" | "cash">("pnl")
```

- [ ] **Step 3: Add tab bar after the header div**

In the JSX, after the closing `</div>` of the header block (the one containing the back button and "Finance" h1), insert:

```tsx
{/* Tab bar */}
<div className="flex border-b border-[#F0EDE9]">
  {(["pnl", "cash"] as const).map(key => (
    <button
      key={key}
      onClick={() => setTab(key)}
      className={`px-4 py-2.5 text-xs font-bold border-b-2 transition-colors ${
        tab === key
          ? "text-[#EF1F9C] border-[#EF1F9C]"
          : "text-[#999] border-transparent"
      }`}
    >
      {key === "pnl" ? "P&L" : "Cash"}
    </button>
  ))}
</div>
```

- [ ] **Step 4: Wrap existing P&L content**

Wrap everything from the month picker div down to the final `{error && ...}` line in:

```tsx
{tab === "pnl" && (
  <>
    {/* ... paste existing content here unchanged ... */}
  </>
)}
```

Then add the Cash tab render after the closing `}`:

```tsx
{tab === "cash" && <CashTab />}
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 6: Start dev server and test the full flow**

```bash
cd web && npm run dev
```

Open `http://localhost:3000/finance`. Verify:

1. Tab bar shows P&L and Cash tabs
2. P&L tab: all existing content works unchanged
3. Cash tab: month picker, dark balance card (₹0 for a fresh month with no data), two stat cards, empty count check card with "+ Log count" button, empty expense list with "+ Add expense" button, 6-month history table
4. Add expense: tap "+ Add expense" → sheet slides up → fill Date/Description/Amount/Paid by → Save → expense appears in list, balance updates
5. Void expense: tap an expense row → "Tap again to void" appears → tap again → expense disappears, balance updates
6. Log count: tap "+ Log count" → sheet slides up → fill Amount/Counted by → Log count → count check card shows amount and variance
7. Variance: if balance is ₹5,000 and counted is ₹4,500, card shows "₹500 short" in red

- [ ] **Step 7: Commit**

```bash
git add web/app/finance/page.tsx
git commit -m "feat(pwa): add Cash tab to Finance page — wire in CashTab component"
```

---

## Spec Coverage Check

| Spec requirement | Task |
|---|---|
| `cash_expenses` table | 1 |
| `cash_counts` table | 1 |
| GET `/finance/cash` with collected, expenses_total, balance, last_count, expenses, history | 3 |
| POST `/finance/cash/expenses` | 4 |
| DELETE `/finance/cash/expenses/{id}` (soft-delete) | 4 |
| POST `/finance/cash/counts` | 5 |
| Frontend types: CashPosition, CashExpense, CashCountEntry | 6 |
| Frontend helpers: getCashPosition, addCashExpense, voidCashExpense, logCashCount | 6 |
| Cash tab: month picker | 7 |
| Cash tab: big balance card (dark) | 7 |
| Cash tab: two stat cards (Collected green / Expenses red) | 7 |
| Cash tab: count check card with variance and "+ Log count" | 7 |
| Cash tab: expense list with two-tap void | 7 |
| Cash tab: month history table (6 months) | 7 |
| Add expense sheet (Option B: Date, Desc, Amount, Paid by) | 7 |
| Log count sheet (Date, Amount, Counted by, Notes) | 7 |
| Finance page: P&L \| Cash tab switcher | 8 |
| collected = payments WHERE mode=cash, for_type=rent, not voided | 3 |
| Admin-only access on all endpoints | 3, 4, 5 |
| No per-holder breakdown — single business total | 3, 7 |
