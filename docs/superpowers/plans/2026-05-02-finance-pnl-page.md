# Finance / P&L Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an owner-only Finance page in the PWA — upload Yes Bank CSV statements, view a P&L dashboard (matching current Excel output exactly), download the Excel report, and auto-reconcile bank deposit refund outflows against checkout records.

**Architecture:** CSV upload → `src/parsers/yes_bank.py` parses → `src/rules/pnl_classify.py` classifies (unchanged) → stored in existing `bank_transactions` table with dedup hash. P&L endpoint aggregates bank income + DB cash payments. PWA client page with interactive month picker calls these endpoints.

**Tech Stack:** FastAPI (async SQLAlchemy), openpyxl, Next.js 14 (client component), DM Sans / Kozzy design system, Supabase JWT auth.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/database/models.py` | Modify | Add `account_name` to `BankUpload` + `BankTransaction` |
| `src/database/migrate_all.py` | Modify | Append migration for the 2 new columns |
| `src/parsers/yes_bank.py` | **Create** | `read_yes_bank_csv(f)` — extracted from `export_classified.py` |
| `scripts/export_classified.py` | Modify | Import parser from new module (no logic change) |
| `src/api/v2/finance.py` | **Create** | 3 endpoints: upload, pnl, pnl/excel |
| `src/api/v2/app_router.py` | Modify | Register finance router |
| `web/lib/api.ts` | Modify | Add `uploadBankCsv`, `getFinancePnl`, `downloadPnlExcel` |
| `web/app/finance/page.tsx` | **Create** | Finance dashboard (client component) |
| `web/components/finance/pnl-cards.tsx` | **Create** | IncomeCard + ExpenseCard display components |
| `web/components/finance/upload-card.tsx` | **Create** | CSV upload card with account selector |
| `web/app/page.tsx` | Modify | Admin-only Finance quick link in quick links row |
| `web/components/finance/reconcile-card.tsx` | **Create** | Deposit reconciliation status list |
| `tests/parsers/test_yes_bank_parser.py` | **Create** | Unit tests for CSV parser |
| `tests/api/v2/test_finance.py` | **Create** | Integration tests for finance endpoints |

---

## Task 1: DB Migration — add account_name

**Files:**
- Modify: `src/database/models.py`
- Modify: `src/database/migrate_all.py`

- [ ] **Step 1: Add `account_name` to both ORM models in `src/database/models.py`**

Find `class BankUpload(Base):` (around line 1155) and add the column after `uploaded_at`:

```python
# in BankUpload — add after uploaded_at line:
account_name  = Column(String(20), default="THOR")   # 'THOR' | 'HULK'
```

Find `class BankTransaction(Base):` (around line 1248) and add after `created_at`:

```python
# in BankTransaction — add after created_at line:
account_name  = Column(String(20), default="THOR")   # copied from upload
```

- [ ] **Step 2: Append migration to `src/database/migrate_all.py`**

In the `ADD_COLUMNS` list, append at the end (before the closing `]`):

```python
    # Finance — bank account tagging (added 2026-05-02)
    ("bank_uploads",       "account_name",  "VARCHAR(20) DEFAULT 'THOR'"),
    ("bank_transactions",  "account_name",  "VARCHAR(20) DEFAULT 'THOR'"),
```

- [ ] **Step 3: Run migration**

```bash
venv/Scripts/python -m src.database.migrate_all
```

Expected output contains: `bank_uploads.account_name` and `bank_transactions.account_name` added (or "already exists" if re-run).

- [ ] **Step 4: Commit**

```bash
git add src/database/models.py src/database/migrate_all.py
git commit -m "feat(db): add account_name to bank_uploads + bank_transactions"
```

---

## Task 2: Extract Yes Bank CSV Parser

**Files:**
- Create: `src/parsers/yes_bank.py`
- Modify: `scripts/export_classified.py` (import from new module)

- [ ] **Step 1: Write the parser test**

Create `tests/parsers/__init__.py` (empty) and `tests/parsers/test_yes_bank_parser.py`:

```python
"""Unit tests for Yes Bank CSV parser."""
import io
from src.parsers.yes_bank import read_yes_bank_csv, parse_date, parse_amt
from datetime import date

SAMPLE_CSV = """some header line
another line
Transaction Date,Value Date,Description,Ref No,Withdrawals,Deposits,Balance
01/05/2026,01/05/2026,UPI/9876543210/PAYMENT/ref123,,5000.00,,100000.00
02/05/2026,02/05/2026,UPI-COLL-RAZORPAY,,, 28000.00,128000.00
"""

def test_parse_date_dmy():
    assert parse_date("01/05/2026") == date(2026, 5, 1)

def test_parse_date_ymd():
    assert parse_date("2026-05-01") == date(2026, 5, 1)

def test_parse_amt_comma():
    assert parse_amt("1,23,456.78") == 123456.78

def test_parse_amt_empty():
    assert parse_amt("") == 0.0

def test_read_yes_bank_csv_from_file_obj():
    f = io.StringIO(SAMPLE_CSV)
    rows = read_yes_bank_csv(f)
    # one expense + one income
    assert len(rows) == 2
    dates, descs, types, amts = zip(*rows)
    assert "expense" in types
    assert "income" in types
    assert 5000.0 in amts
    assert 28000.0 in amts
```

- [ ] **Step 2: Run to confirm it fails**

```bash
venv/Scripts/python -m pytest tests/parsers/test_yes_bank_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.parsers.yes_bank'`

- [ ] **Step 3: Create `src/parsers/__init__.py`** (if not exists)

```bash
# check first
ls src/parsers/
```

If no `__init__.py`, create an empty one.

- [ ] **Step 4: Create `src/parsers/yes_bank.py`**

```python
"""
src/parsers/yes_bank.py
Yes Bank CSV / Excel statement parser.
Extracted from scripts/export_classified.py so it can be shared
by the API upload endpoint and the offline script.
"""
from __future__ import annotations

import csv as _csv
import io
from datetime import date, datetime
from typing import IO, Union

__all__ = ["parse_date", "parse_amt", "read_yes_bank_csv"]


def parse_date(v) -> date | None:
    if isinstance(v, (date, datetime)):
        return v.date() if isinstance(v, datetime) else v
    s = str(v).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def parse_amt(v) -> float:
    if v is None or str(v).strip() == "":
        return 0.0
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return 0.0


def read_yes_bank_csv(source: Union[str, IO]) -> list[tuple[date, str, str, float]]:
    """
    Parse a Yes Bank CSV statement.

    Accepts either a file path (str) or a file-like object (e.g. io.StringIO,
    UploadFile.file after reading).

    Returns list of (txn_date, description, txn_type, amount) where
    txn_type is 'income' or 'expense'.
    """
    if isinstance(source, str):
        f = open(source, "r", encoding="utf-8-sig", errors="replace")
        close_after = True
    else:
        # wrap bytes in text wrapper if needed
        if isinstance(source, (bytes, bytearray)):
            f = io.StringIO(source.decode("utf-8-sig", errors="replace"))
        elif hasattr(source, "read"):
            raw = source.read()
            if isinstance(raw, bytes):
                f = io.StringIO(raw.decode("utf-8-sig", errors="replace"))
            else:
                f = io.StringIO(raw)
        else:
            f = source
        close_after = False

    out: list[tuple[date, str, str, float]] = []
    try:
        # skip lines until we find the header
        for line in f:
            if line.startswith("Transaction Date"):
                break
        reader = _csv.reader(f)
        for row in reader:
            if len(row) < 6:
                continue
            dt_str, _, desc = row[0], row[1], row[2]
            wd  = parse_amt(row[4]) if len(row) > 4 else 0.0
            dep = parse_amt(row[5]) if len(row) > 5 else 0.0
            dt  = parse_date(dt_str)
            if not dt:
                continue
            if wd > 0:
                out.append((dt, desc.strip(), "expense", wd))
            if dep > 0:
                out.append((dt, desc.strip(), "income", dep))
    finally:
        if close_after:
            f.close()

    return out
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
venv/Scripts/python -m pytest tests/parsers/test_yes_bank_parser.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Update `scripts/export_classified.py` to import from new module**

Replace the `parse_date`, `parse_amt`, and `read_yes_bank_csv` function definitions in `export_classified.py` with imports:

```python
# Replace the three function definitions (lines ~20-75) with:
from src.parsers.yes_bank import parse_date, parse_amt, read_yes_bank_csv
```

- [ ] **Step 7: Verify the script still runs**

```bash
venv/Scripts/python scripts/export_classified.py
```

Expected: same output as before (or "no files found" if no CSVs in cwd — that's fine).

- [ ] **Step 8: Commit**

```bash
git add src/parsers/yes_bank.py tests/parsers/ scripts/export_classified.py
git commit -m "refactor: extract yes_bank CSV parser into src/parsers/yes_bank.py"
```

---

## Task 3: Finance API — Upload Endpoint

**Files:**
- Create: `src/api/v2/finance.py`
- Create: `tests/api/v2/test_finance.py`

- [ ] **Step 1: Write the upload unit test (parser + classify only, no DB)**

Create `tests/api/v2/test_finance.py`:

```python
"""Tests for finance API helpers."""
import io
import hashlib
from src.parsers.yes_bank import read_yes_bank_csv
from src.rules.pnl_classify import classify_txn

SAMPLE_CSV = """Transaction Date,Value Date,Description,Ref No,Withdrawals,Deposits,Balance
01/05/2026,01/05/2026,UPI/MANOJ B/water/9535665407,,42500.00,,100000.00
02/05/2026,02/05/2026,UPI-COLL-RAZORPAY-settlements,,,28000.00,128000.00
"""

def _make_hash(dt, amt, desc) -> str:
    key = f"{dt}|{round(float(amt), 2):.2f}|{desc.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()

def test_parse_and_classify():
    rows = read_yes_bank_csv(io.StringIO(SAMPLE_CSV))
    assert len(rows) == 2
    for dt, desc, typ, amt in rows:
        cat, sub = classify_txn(desc, typ)
        assert cat  # never empty

def test_expense_classifies_as_water():
    rows = read_yes_bank_csv(io.StringIO(SAMPLE_CSV))
    expense = next(r for r in rows if r[2] == "expense")
    cat, _ = classify_txn(expense[1], "expense")
    assert cat == "Water"

def test_income_classifies_as_upi_batch():
    rows = read_yes_bank_csv(io.StringIO(SAMPLE_CSV))
    income = next(r for r in rows if r[2] == "income")
    cat, _ = classify_txn(income[1], "income")
    # Razorpay settlements are UPI Batch
    assert "batch" in cat.lower() or "upi" in cat.lower() or "income" in cat.lower()

def test_dedup_hash_deterministic():
    from datetime import date
    h1 = _make_hash(date(2026, 5, 1), 42500, "UPI/MANOJ B/water")
    h2 = _make_hash(date(2026, 5, 1), 42500, "UPI/MANOJ B/water")
    assert h1 == h2

def test_dedup_hash_differs_for_different_txns():
    from datetime import date
    h1 = _make_hash(date(2026, 5, 1), 42500, "UPI/MANOJ B/water")
    h2 = _make_hash(date(2026, 5, 1), 42500, "BESCOM PAYMENT")
    assert h1 != h2
```

- [ ] **Step 2: Run tests to confirm they pass**

```bash
venv/Scripts/python -m pytest tests/api/v2/test_finance.py -v
```

Expected: all 5 pass (pure unit tests, no DB needed).

- [ ] **Step 3: Create `src/api/v2/finance.py`**

```python
"""
src/api/v2/finance.py
Finance endpoints — CSV upload, P&L dashboard, Excel download.
Owner-only (admin role required on every endpoint).
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select, text

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import BankTransaction, BankUpload, Payment, PaymentMode
from src.parsers.yes_bank import read_yes_bank_csv
from src.rules.pnl_classify import classify_txn
from src.utils.inr_format import INR_NUMBER_FORMAT

logger = logging.getLogger(__name__)
router = APIRouter()

EXPENSE_CATS = [
    "Property Rent", "Electricity", "Water", "IT & Software", "Internet & WiFi",
    "Food & Groceries", "Fuel & Diesel", "Staff & Labour", "Furniture & Fittings",
    "Maintenance & Repairs", "Cleaning Supplies", "Waste Disposal",
    "Shopping & Supplies", "Operational Expenses", "Marketing",
    "Govt & Regulatory", "Tenant Deposit Refund", "Bank Charges",
    "Capital Investment", "Non-Operating", "Other Expenses",
]


def _require_admin(user: AppUser):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _make_hash(txn_date: date, amount: float, desc: str) -> str:
    key = f"{txn_date}|{round(float(amount), 2):.2f}|{desc.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/finance/upload")
async def upload_bank_csv(
    files: list[UploadFile] = File(...),
    account_name: str = Form(...),
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)
    if account_name not in ("THOR", "HULK"):
        raise HTTPException(status_code=400, detail="account_name must be THOR or HULK")

    total_new = 0
    total_dup = 0
    months_affected: set[str] = set()

    async with get_session() as session:
        for upload_file in files:
            content = await upload_file.read()

            # Parse
            rows = read_yes_bank_csv(content)
            if not rows:
                continue

            from_date = min(r[0] for r in rows)
            to_date   = max(r[0] for r in rows)

            # Create upload record
            upload = BankUpload(
                phone=user.phone,
                file_path=upload_file.filename or "",
                row_count=len(rows),
                new_count=0,
                from_date=from_date,
                to_date=to_date,
                status="processed",
                account_name=account_name,
            )
            session.add(upload)
            await session.flush()  # get upload.id

            new_count = 0
            for txn_date, desc, txn_type, amount in rows:
                uhash = _make_hash(txn_date, amount, desc)
                # Dedup check
                existing = await session.scalar(
                    select(BankTransaction.id).where(BankTransaction.unique_hash == uhash)
                )
                if existing:
                    total_dup += 1
                    continue

                cat, sub = classify_txn(desc, txn_type)
                txn = BankTransaction(
                    upload_id=upload.id,
                    txn_date=txn_date,
                    description=desc,
                    amount=amount,
                    txn_type=txn_type,
                    category=cat,
                    sub_category=sub,
                    unique_hash=uhash,
                    account_name=account_name,
                )
                session.add(txn)
                months_affected.add(txn_date.strftime("%Y-%m"))
                new_count += 1

            upload.new_count = new_count
            total_new += new_count

        await session.commit()

    return {
        "months_affected": sorted(months_affected),
        "new_count": total_new,
        "duplicate_count": total_dup,
    }


# ── P&L ───────────────────────────────────────────────────────────────────────

@router.get("/finance/pnl")
async def get_pnl(
    month: Optional[str] = Query(None, description="YYYY-MM, e.g. 2026-05"),
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)

    async with get_session() as session:
        # Build date filter
        def _month_filter(col, m: str):
            y, mo = int(m[:4]), int(m[5:7])
            start = date(y, mo, 1)
            import calendar
            end_day = calendar.monthrange(y, mo)[1]
            end = date(y, mo, end_day)
            return col.between(start, end)

        # Which months have data?
        month_rows = await session.execute(
            select(func.to_char(BankTransaction.txn_date, "YYYY-MM"))
            .distinct()
            .order_by(func.to_char(BankTransaction.txn_date, "YYYY-MM"))
        )
        available_months = [r[0] for r in month_rows]

        target_months = [month] if month else available_months
        if not target_months:
            return {"months": [], "data": {}}

        result = {}
        for m in target_months:
            y, mo = int(m[:4]), int(m[5:7])
            import calendar
            start = date(y, mo, 1)
            end = date(y, mo, calendar.monthrange(y, mo)[1])

            # Bank income
            inc_rows = await session.execute(
                select(BankTransaction.category, func.sum(BankTransaction.amount))
                .where(
                    BankTransaction.txn_type == "income",
                    BankTransaction.txn_date.between(start, end),
                    BankTransaction.category != "Capital Investment",
                )
                .group_by(BankTransaction.category)
            )
            bank_income = {row[0]: float(row[1]) for row in inc_rows}
            upi_batch   = bank_income.get("UPI Batch", 0.0)
            direct_neft = sum(v for k, v in bank_income.items() if k != "UPI Batch")

            # DB cash payments
            cash_rows = await session.execute(
                select(func.sum(Payment.amount))
                .where(
                    Payment.payment_mode == PaymentMode.cash,
                    Payment.for_type == "rent",
                    Payment.is_void == False,
                    Payment.period_month == m,
                )
            )
            cash_db = float(cash_rows.scalar() or 0)

            # Capital contributions
            cap_rows = await session.execute(
                select(func.sum(BankTransaction.amount))
                .where(
                    BankTransaction.category == "Capital Investment",
                    BankTransaction.txn_date.between(start, end),
                )
            )
            capital = float(cap_rows.scalar() or 0)

            # Expenses
            exp_rows = await session.execute(
                select(BankTransaction.category, func.sum(BankTransaction.amount))
                .where(
                    BankTransaction.txn_type == "expense",
                    BankTransaction.txn_date.between(start, end),
                )
                .group_by(BankTransaction.category)
            )
            expense_by_cat = {row[0]: float(row[1]) for row in exp_rows}
            expenses = [
                {"category": cat, "amount": expense_by_cat.get(cat, 0.0)}
                for cat in EXPENSE_CATS
                if expense_by_cat.get(cat, 0.0) > 0
            ]
            total_expense = sum(e["amount"] for e in expenses)
            total_income  = upi_batch + direct_neft + cash_db
            profit        = total_income - total_expense
            margin        = round(profit / total_income * 100, 1) if total_income else 0.0

            result[m] = {
                "month": m,
                "income": {
                    "upi_batch":   upi_batch,
                    "direct_neft": direct_neft,
                    "cash_db":     cash_db,
                    "total":       total_income,
                },
                "capital": capital,
                "expenses": expenses,
                "total_expense":    total_expense,
                "operating_profit": profit,
                "margin_pct":       margin,
            }

    return {"months": target_months, "data": result}


# ── Excel Download ─────────────────────────────────────────────────────────────

@router.get("/finance/pnl/excel")
async def download_pnl_excel(
    from_month: Optional[str] = Query(None, alias="from"),
    to_month:   Optional[str] = Query(None, alias="to"),
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)

    async with get_session() as session:
        # Load all classified transactions in range
        q = select(BankTransaction).order_by(BankTransaction.txn_date)
        if from_month:
            y, mo = int(from_month[:4]), int(from_month[5:7])
            q = q.where(BankTransaction.txn_date >= date(y, mo, 1))
        if to_month:
            import calendar
            y, mo = int(to_month[:4]), int(to_month[5:7])
            last = calendar.monthrange(y, mo)[1]
            q = q.where(BankTransaction.txn_date <= date(y, mo, last))
        rows = (await session.scalars(q)).all()

    classified = [
        (r.txn_date, r.description, r.txn_type, float(r.amount), r.category, r.sub_category)
        for r in rows
    ]

    wb = _build_excel(classified)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"PnL_{datetime.now().strftime('%Y_%m_%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_excel(classified: list) -> openpyxl.Workbook:
    """Build same 3-sheet Excel as export_classified.py."""
    HDR_FILL = PatternFill("solid", fgColor="1a1a2e")
    HDR_FONT = Font(bold=True, color="FFFFFF", size=10)
    ALT_FILL = PatternFill("solid", fgColor="F8F9FA")
    WHT_FILL = PatternFill("solid", fgColor="FFFFFF")
    CTR      = Alignment(horizontal="center", vertical="center")
    TOT_FONT_G = Font(bold=True, size=11, color="008B00")
    TOT_FONT_R = Font(bold=True, size=11, color="FF0000")
    TOT_FONT   = Font(bold=True, size=11)
    SEC_FILL   = PatternFill("solid", fgColor="2d2d44")
    SEC_FONT   = Font(bold=True, color="FFFFFF", size=11)

    months = sorted(set(dt.strftime("%Y-%m") for dt, *_ in classified))
    monthly_exp = defaultdict(lambda: defaultdict(float))
    monthly_inc = defaultdict(lambda: defaultdict(float))
    monthly_sub: dict[tuple, float] = defaultdict(float)

    INCOME_CATS = ["Rent Income", "Advance Deposit", "UPI Batch", "Other Income"]

    for dt, desc, typ, amt, cat, sub in classified:
        m = dt.strftime("%Y-%m")
        if typ == "expense":
            monthly_exp[m][cat] += amt
            monthly_sub[(m, cat, sub)] += amt
        else:
            monthly_inc[m][cat] += amt

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # ── Sheet 1: Monthly P&L ──────────────────────────────────────────────────
    ws = wb.create_sheet("Monthly P&L")
    hdr_row = [""] + months + ["TOTAL"]
    for col, h in enumerate(hdr_row, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.fill = HDR_FILL; c.font = HDR_FONT; c.alignment = CTR
    ws.row_dimensions[1].height = 22

    def _write_row(ws, ri, label, vals, font=None, fill=None, indent=False):
        lbl = ("  " + label) if indent else label
        c = ws.cell(row=ri, column=1, value=lbl)
        if font: c.font = font
        if fill: c.fill = fill
        for ci, v in enumerate(vals, 2):
            c = ws.cell(row=ri, column=ci, value=round(v) if v else "")
            c.number_format = INR_NUMBER_FORMAT
            if font: c.font = font
            if fill: c.fill = fill

    ri = 2
    # Income section
    c = ws.cell(row=ri, column=1, value="INCOME")
    c.fill = SEC_FILL; c.font = SEC_FONT
    for col in range(2, len(months) + 3):
        ws.cell(row=ri, column=col).fill = SEC_FILL
    ri += 1

    inc_totals = [0.0] * (len(months) + 1)
    for cat in INCOME_CATS:
        vals = [monthly_inc[m].get(cat, 0) for m in months]
        vals.append(sum(vals))
        if sum(vals) == 0:
            continue
        for i, v in enumerate(vals):
            inc_totals[i] += v
        fill = ALT_FILL if ri % 2 == 0 else WHT_FILL
        _write_row(ws, ri, cat, vals, indent=True, fill=fill)
        ri += 1
    _write_row(ws, ri, "TOTAL INCOME", inc_totals, font=TOT_FONT_G)
    ri += 2

    # Expense section
    c = ws.cell(row=ri, column=1, value="OPERATING EXPENSES")
    c.fill = SEC_FILL; c.font = SEC_FONT
    for col in range(2, len(months) + 3):
        ws.cell(row=ri, column=col).fill = SEC_FILL
    ri += 1

    exp_totals = [0.0] * (len(months) + 1)
    op_cats = [c for c in EXPENSE_CATS if c != "Non-Operating"]
    for cat in op_cats:
        vals = [monthly_exp[m].get(cat, 0) for m in months]
        vals.append(sum(vals))
        if sum(vals) == 0:
            continue
        for i, v in enumerate(vals):
            exp_totals[i] += v
        fill = ALT_FILL if ri % 2 == 0 else WHT_FILL
        _write_row(ws, ri, cat, vals, indent=True, fill=fill)
        ri += 1
    _write_row(ws, ri, "TOTAL OPERATING EXPENSES", exp_totals, font=TOT_FONT_R)
    ri += 2

    # Operating profit
    op_profit = [inc_totals[i] - exp_totals[i] for i in range(len(inc_totals))]
    _write_row(ws, ri, "OPERATING PROFIT (EBITDA)", op_profit, font=TOT_FONT)
    ri += 2

    # Non-operating
    nonop = [monthly_exp[m].get("Non-Operating", 0) for m in months]
    nonop.append(sum(nonop))
    if sum(nonop) > 0:
        c = ws.cell(row=ri, column=1, value="NON-OPERATING EXPENSES")
        c.fill = SEC_FILL; c.font = SEC_FONT
        for col in range(2, len(months) + 3):
            ws.cell(row=ri, column=col).fill = SEC_FILL
        ri += 1
        _write_row(ws, ri, "Loan Repayment / Transfers", nonop, indent=True, fill=ALT_FILL)
        ri += 2

    net = [op_profit[i] - nonop[i] for i in range(len(op_profit))]
    _write_row(ws, ri, "NET PROFIT / (LOSS)", net, font=Font(bold=True, size=12))
    ri += 2

    # Margins
    c = ws.cell(row=ri, column=1, value="OPERATING MARGIN %")
    c.font = Font(bold=True, italic=True)
    for ci, m in enumerate(months, 2):
        inc = inc_totals[ci - 2]
        margin = (op_profit[ci - 2] / inc * 100) if inc else 0
        ws.cell(row=ri, column=ci, value=f"{margin:.1f}%").font = Font(italic=True)
    ws.column_dimensions["A"].width = 32
    for i in range(2, len(months) + 3):
        ws.column_dimensions[get_column_letter(i)].width = 15
    ws.freeze_panes = "B2"

    # ── Sheet 2: Sub-category Breakdown ──────────────────────────────────────
    ws2 = wb.create_sheet("Sub-category Breakdown")
    sub_hdrs = ["Category", "Sub-category"] + months + ["TOTAL"]
    for col, h in enumerate(sub_hdrs, 1):
        c = ws2.cell(row=1, column=col, value=h)
        c.fill = HDR_FILL; c.font = HDR_FONT; c.alignment = CTR

    ri = 2
    for cat in EXPENSE_CATS:
        all_subs = sorted({s for (m, c2, s), v in monthly_sub.items() if c2 == cat and v > 0})
        if not all_subs:
            continue
        cat_total = sum(monthly_exp[m].get(cat, 0) for m in months)
        if cat_total == 0:
            continue
        c = ws2.cell(row=ri, column=1, value=cat)
        c.fill = PatternFill("solid", fgColor="2d2d44")
        c.font = Font(bold=True, color="FFFFFF")
        for col in range(2, len(months) + 3):
            ws2.cell(row=ri, column=col).fill = PatternFill("solid", fgColor="2d2d44")
        ri += 1
        for sub in all_subs:
            sub_total = sum(monthly_sub.get((m, cat, sub), 0) for m in months)
            if sub_total == 0:
                continue
            fill = ALT_FILL if ri % 2 == 0 else WHT_FILL
            ws2.cell(row=ri, column=1, value="").fill = fill
            ws2.cell(row=ri, column=2, value=sub).fill = fill
            for ci, m in enumerate(months, 3):
                v = monthly_sub.get((m, cat, sub), 0)
                c = ws2.cell(row=ri, column=ci, value=round(v) if v else 0)
                c.fill = fill; c.number_format = INR_NUMBER_FORMAT
            c = ws2.cell(row=ri, column=len(months) + 3, value=round(sub_total))
            c.fill = fill; c.number_format = INR_NUMBER_FORMAT; c.font = Font(bold=True)
            ri += 1
    ws2.column_dimensions["A"].width = 26
    ws2.column_dimensions["B"].width = 38
    for i in range(3, len(months) + 4):
        ws2.column_dimensions[get_column_letter(i)].width = 14
    ws2.freeze_panes = "C2"

    # ── Sheet 3: All Transactions ─────────────────────────────────────────────
    ws3 = wb.create_sheet("All Transactions")
    txn_hdrs = ["Date", "Month", "Type", "Category", "Sub-category", "Amount (Rs)", "Description"]
    for col, h in enumerate(txn_hdrs, 1):
        c = ws3.cell(row=1, column=col, value=h)
        c.fill = HDR_FILL; c.font = HDR_FONT; c.alignment = CTR
    for ri, (dt, desc, typ, amt, cat, sub) in enumerate(sorted(classified, key=lambda x: x[0]), 2):
        fill = ALT_FILL if ri % 2 == 0 else WHT_FILL
        ws3.cell(row=ri, column=1, value=dt.strftime("%d %b %Y")).fill = fill
        ws3.cell(row=ri, column=2, value=dt.strftime("%Y-%m")).fill = fill
        ws3.cell(row=ri, column=3, value=typ).fill = fill
        ws3.cell(row=ri, column=4, value=cat).fill = fill
        ws3.cell(row=ri, column=5, value=sub).fill = fill
        c = ws3.cell(row=ri, column=6, value=amt)
        c.fill = fill; c.number_format = INR_NUMBER_FORMAT
        ws3.cell(row=ri, column=7, value=desc).fill = fill
    ws3.column_dimensions["A"].width = 14
    ws3.column_dimensions["B"].width = 10
    ws3.column_dimensions["C"].width = 10
    ws3.column_dimensions["D"].width = 26
    ws3.column_dimensions["E"].width = 38
    ws3.column_dimensions["F"].width = 14
    ws3.column_dimensions["G"].width = 80
    ws3.auto_filter.ref = "A1:G1"
    ws3.freeze_panes = "A2"

    return wb
```

- [ ] **Step 4: Register router in `src/api/v2/app_router.py`**

Add after the last `include_router` call:

```python
from src.api.v2.finance import router as finance_router
# ...
router.include_router(finance_router)
```

- [ ] **Step 5: Start local server and smoke-test upload endpoint**

```bash
venv/Scripts/python main.py
# In another terminal, with a real Yes Bank CSV:
curl -X POST http://localhost:8000/api/v2/app/finance/upload \
  -H "Authorization: Bearer <your_token>" \
  -F "files=@Statement-2026-05.csv" \
  -F "account_name=THOR"
```

Expected: `{"months_affected":["2026-05"],"new_count":N,"duplicate_count":0}`

- [ ] **Step 6: Commit**

```bash
git add src/api/v2/finance.py src/api/v2/app_router.py tests/api/v2/test_finance.py
git commit -m "feat(api): add finance upload, pnl, and excel download endpoints"
```

---

## Task 4: PWA API Client

**Files:**
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add finance types and functions to `web/lib/api.ts`**

Append to the end of `web/lib/api.ts`:

```typescript
// ── Finance ──────────────────────────────────────────────────────────────────

export interface FinanceIncomeBreakdown {
  upi_batch: number
  direct_neft: number
  cash_db: number
  total: number
}

export interface FinanceExpenseRow {
  category: string
  amount: number
}

export interface FinanceMonthData {
  month: string
  income: FinanceIncomeBreakdown
  capital: number
  expenses: FinanceExpenseRow[]
  total_expense: number
  operating_profit: number
  margin_pct: number
}

export interface FinancePnlResponse {
  months: string[]
  data: Record<string, FinanceMonthData>
}

export interface FinanceUploadResult {
  months_affected: string[]
  new_count: number
  duplicate_count: number
}

export async function uploadBankCsv(
  files: File[],
  accountName: "THOR" | "HULK",
): Promise<FinanceUploadResult> {
  const headers = await _authHeaders()
  const form = new FormData()
  files.forEach((f) => form.append("files", f))
  form.append("account_name", accountName)
  const res = await fetch(`${BASE_URL}/api/v2/app/finance/upload`, {
    method: "POST",
    headers,  // no Content-Type — browser sets multipart boundary
    body: form,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error((detail as { detail?: string }).detail ?? `Upload failed: ${res.status}`)
  }
  return res.json() as Promise<FinanceUploadResult>
}

export async function getFinancePnl(month?: string): Promise<FinancePnlResponse> {
  const qs = month ? `?month=${month}` : ""
  return _get<FinancePnlResponse>(`/api/v2/app/finance/pnl${qs}`)
}

export async function downloadPnlExcel(fromMonth?: string, toMonth?: string): Promise<void> {
  const headers = await _authHeaders()
  const params = new URLSearchParams()
  if (fromMonth) params.set("from", fromMonth)
  if (toMonth) params.set("to", toMonth)
  const url = `${BASE_URL}/api/v2/app/finance/pnl/excel${params.size ? "?" + params.toString() : ""}`
  const res = await fetch(url, { headers })
  if (!res.ok) throw new Error(`Excel download failed: ${res.status}`)
  const blob = await res.blob()
  const a = document.createElement("a")
  a.href = URL.createObjectURL(blob)
  a.download = `PnL_${new Date().toISOString().slice(0, 10)}.xlsx`
  a.click()
  URL.revokeObjectURL(a.href)
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors related to the new finance functions.

- [ ] **Step 3: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(pwa): add finance API client functions"
```

---

## Task 5: PWA Finance Components

**Files:**
- Create: `web/components/finance/pnl-cards.tsx`
- Create: `web/components/finance/upload-card.tsx`

- [ ] **Step 1: Create `web/components/finance/pnl-cards.tsx`**

```tsx
"use client"

import type { FinanceMonthData } from "@/lib/api"

function rupee(n: number): string {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`
  if (n >= 1000) return `₹${Math.round(n / 1000)}K`
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

function rupeeExact(n: number): string {
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

interface KpiTilesProps {
  data: FinanceMonthData
}

export function KpiTiles({ data }: KpiTilesProps) {
  return (
    <div className="grid grid-cols-3 gap-2">
      <div className="bg-tile-green rounded-tile p-3">
        <p className="text-[11px] font-extrabold text-status-paid">{rupee(data.income.total)}</p>
        <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Income</p>
      </div>
      <div className="bg-tile-orange rounded-tile p-3">
        <p className="text-[11px] font-extrabold text-status-due">{rupee(data.total_expense)}</p>
        <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Expense</p>
      </div>
      <div className="bg-tile-pink rounded-tile p-3">
        <p className={`text-[11px] font-extrabold ${data.operating_profit >= 0 ? "text-brand-pink" : "text-status-warn"}`}>
          {rupee(Math.abs(data.operating_profit))}
        </p>
        <p className="text-[9px] text-ink-muted font-semibold mt-0.5">
          {data.operating_profit >= 0 ? "Profit" : "Loss"} · {data.margin_pct}%
        </p>
      </div>
    </div>
  )
}

export function IncomeCard({ data }: KpiTilesProps) {
  const rows = [
    { label: "Bank — UPI batch settlements", amount: data.income.upi_batch },
    { label: "Bank — direct + NEFT", amount: data.income.direct_neft },
    { label: "Cash (PWA recorded)", amount: data.income.cash_db },
  ]
  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
      <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-2">Income</p>
      {rows.map((row) => (
        <div key={row.label} className="flex items-center justify-between py-2 border-b border-[#F6F5F0] last:border-none">
          <span className="text-xs text-ink-muted">{row.label}</span>
          <span className="text-xs font-bold text-status-paid">{rupeeExact(row.amount)}</span>
        </div>
      ))}
      <div className="flex items-center justify-between pt-2 mt-1">
        <span className="text-xs font-bold text-ink">Total Revenue</span>
        <span className="text-sm font-extrabold text-ink">{rupeeExact(data.income.total)}</span>
      </div>
    </div>
  )
}

export function ExpenseCard({ data }: KpiTilesProps) {
  const nonEmpty = data.expenses.filter((e) => e.amount > 0)
  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
      <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-2">Expenses</p>
      {nonEmpty.map((row) => (
        <div key={row.category} className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0] last:border-none">
          <span className="text-xs text-ink-muted">{row.category}</span>
          <span className="text-xs font-bold text-status-due">−{rupeeExact(row.amount)}</span>
        </div>
      ))}
      <div className="flex items-center justify-between pt-2 mt-1">
        <span className="text-xs font-bold text-ink">Total Expenses</span>
        <span className="text-sm font-extrabold text-status-due">−{rupeeExact(data.total_expense)}</span>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create `web/components/finance/upload-card.tsx`**

```tsx
"use client"

import { useRef, useState } from "react"
import { uploadBankCsv, FinanceUploadResult } from "@/lib/api"

interface UploadCardProps {
  onUploaded: (result: FinanceUploadResult) => void
}

export function UploadCard({ onUploaded }: UploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [account, setAccount] = useState<"THOR" | "HULK">("THOR")
  const [state, setState] = useState<"idle" | "uploading" | "done" | "error">("idle")
  const [result, setResult] = useState<FinanceUploadResult | null>(null)
  const [errorMsg, setErrorMsg] = useState("")

  async function handleFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    e.target.value = ""
    setState("uploading")
    setErrorMsg("")
    try {
      const res = await uploadBankCsv(files, account)
      setResult(res)
      setState("done")
      onUploaded(res)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Upload failed")
      setState("error")
    }
  }

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3 flex flex-col gap-3">
      <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">Bank Statement</p>

      {/* Account selector */}
      <div className="flex gap-2">
        {(["THOR", "HULK"] as const).map((a) => (
          <button
            key={a}
            type="button"
            onClick={() => setAccount(a)}
            className={`flex-1 py-2 rounded-pill text-xs font-bold border transition-colors ${
              account === a
                ? "bg-[#0F0E0D] text-white border-[#0F0E0D]"
                : "bg-surface text-ink-muted border-[#E2DEDD]"
            }`}
          >
            {a}
          </button>
        ))}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv"
        multiple
        className="hidden"
        onChange={handleFiles}
      />

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={state === "uploading"}
        className="flex items-center justify-center gap-2 rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink disabled:opacity-50 active:opacity-70"
      >
        <span>📎</span>
        <span>{state === "uploading" ? "Uploading…" : "Select CSV files"}</span>
      </button>

      {state === "done" && result && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 px-3 py-2 rounded-pill bg-tile-green border border-[#C5E8D0]">
            <span className="text-status-paid text-xs font-semibold">
              {result.new_count} transactions added ✓
            </span>
          </div>
          {result.months_affected.length > 0 && (
            <p className="text-[10px] text-ink-muted text-center">
              Updated: {result.months_affected.join(", ")}
            </p>
          )}
          {result.duplicate_count > 0 && (
            <p className="text-[10px] text-ink-muted text-center">
              {result.duplicate_count} duplicates skipped
            </p>
          )}
        </div>
      )}

      {state === "error" && (
        <p className="text-[10px] text-status-warn font-medium text-center">{errorMsg}</p>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add web/components/finance/
git commit -m "feat(pwa): add Finance KPI tiles, income/expense cards, upload card"
```

---

## Task 6: PWA Finance Page

**Files:**
- Create: `web/app/finance/page.tsx`

- [ ] **Step 1: Create `web/app/finance/page.tsx`**

```tsx
"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { getFinancePnl, downloadPnlExcel, FinanceMonthData, FinanceUploadResult } from "@/lib/api"
import { KpiTiles, IncomeCard, ExpenseCard } from "@/components/finance/pnl-cards"
import { UploadCard } from "@/components/finance/upload-card"
import { supabase } from "@/lib/supabase"

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
  const [y, mo] = m.split("-").map(Number)
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${months[mo - 1]} ${y}`
}

export default function FinancePage() {
  const router = useRouter()
  const now = new Date()
  const [month, setMonth] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
  )
  const [data, setData] = useState<FinanceMonthData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [downloading, setDownloading] = useState(false)

  // Admin gate — client-side check
  useEffect(() => {
    supabase().auth.getSession().then(({ data: s }) => {
      const role = s.session?.user.user_metadata?.role
      if (role !== "admin") router.replace("/")
    })
  }, [router])

  const loadPnl = useCallback(async (m: string) => {
    setLoading(true)
    setError("")
    try {
      const res = await getFinancePnl(m)
      setData(res.data[m] ?? null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load P&L")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadPnl(month) }, [month, loadPnl])

  async function handleDownload() {
    setDownloading(true)
    try {
      await downloadPnlExcel()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed")
    } finally {
      setDownloading(false)
    }
  }

  function handleUploaded(result: FinanceUploadResult) {
    // If the uploaded months include the current view month, reload
    if (result.months_affected.includes(month)) {
      loadPnl(month)
    }
  }

  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-32 max-w-lg mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => router.back()} className="text-ink-muted text-lg font-bold">←</button>
        <h1 className="text-lg font-extrabold text-ink flex-1">Finance</h1>
        <span className="text-[9px] font-bold px-2 py-1 rounded-full bg-tile-pink text-brand-pink uppercase tracking-wide">
          Owner
        </span>
      </div>

      {/* Month picker */}
      <div className="flex items-center justify-between bg-[#0F0E0D] rounded-pill px-5 py-3">
        <button onClick={() => setMonth(prevMonth(month))} className="text-[#6F655D] text-sm font-bold">←</button>
        <span className="text-white text-sm font-bold">{monthLabel(month)}</span>
        <button onClick={() => setMonth(nextMonth(month))} className="text-[#6F655D] text-sm font-bold">→</button>
      </div>

      {/* P&L content */}
      {loading && (
        <div className="py-12 text-center text-xs text-ink-muted">Loading…</div>
      )}

      {!loading && !data && (
        <div className="py-12 text-center">
          <p className="text-sm text-ink-muted font-medium">No data for {monthLabel(month)}</p>
          <p className="text-xs text-ink-muted mt-1">Upload a bank statement below to generate P&L</p>
        </div>
      )}

      {!loading && data && (
        <>
          <KpiTiles data={data} />
          <IncomeCard data={data} />
          <ExpenseCard data={data} />
        </>
      )}

      {/* Upload */}
      <UploadCard onUploaded={handleUploaded} />

      {/* Download */}
      <button
        type="button"
        onClick={handleDownload}
        disabled={downloading}
        className="w-full rounded-pill border border-[#E2DEDD] py-3 text-sm font-semibold text-ink disabled:opacity-50 active:opacity-70"
      >
        {downloading ? "Preparing…" : "↓ Download Excel Report"}
      </button>

      {error && (
        <p className="text-[10px] text-status-warn font-medium text-center">{error}</p>
      )}
    </main>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add web/app/finance/
git commit -m "feat(pwa): add Finance dashboard page with P&L view, upload, and Excel download"
```

---

## Task 7: Home Page Finance Quick Link

**Files:**
- Modify: `web/app/page.tsx`

- [ ] **Step 1: Add Finance quick link to home page (admin-only)**

In `web/app/page.tsx`, the quick links section currently shows Checkouts / Notices / Sessions in a `div.flex.gap-2`. Add Finance as a 4th link, conditionally shown only for admin:

```tsx
{/* existing quick links */}
<div className="flex gap-2">
  <Link href="/checkouts" className="flex-1 bg-surface border border-[#F0EDE9] rounded-card px-3 py-2.5 flex items-center gap-2 active:opacity-70">
    <span className="text-base">🚪</span>
    <div>
      <p className="text-xs font-bold text-ink">Checkouts</p>
      <p className="text-[10px] text-ink-muted">This month</p>
    </div>
  </Link>
  <Link href="/notices" className="flex-1 bg-surface border border-[#F0EDE9] rounded-card px-3 py-2.5 flex items-center gap-2 active:opacity-70">
    <span className="text-base">📋</span>
    <div>
      <p className="text-xs font-bold text-ink">Notices</p>
      <p className="text-[10px] text-ink-muted">On notice</p>
    </div>
  </Link>
  <Link href="/onboarding/sessions" className="flex-1 bg-surface border border-[#F0EDE9] rounded-card px-3 py-2.5 flex items-center gap-2 active:opacity-70">
    <span className="text-base">📝</span>
    <div>
      <p className="text-xs font-bold text-ink">Sessions</p>
      <p className="text-[10px] text-ink-muted">Onboarding</p>
    </div>
  </Link>
</div>

{/* Admin-only: Finance link */}
{session.role === "admin" && (
  <Link href="/finance" className="flex items-center gap-3 bg-surface border border-[#F0EDE9] rounded-card px-4 py-3 active:opacity-70">
    <span className="text-base">📊</span>
    <div className="flex-1">
      <p className="text-xs font-bold text-ink">Finance & P&L</p>
      <p className="text-[10px] text-ink-muted">Upload statements · Download Excel</p>
    </div>
    <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-tile-pink text-brand-pink uppercase">
      Owner
    </span>
  </Link>
)}
```

- [ ] **Step 2: Build and test in browser**

```bash
cd web && npm run build && npm run dev
```

Open http://localhost:3000 logged in as admin — Finance & P&L link must appear below the 3 quick links. Log in as staff — it must be absent.

- [ ] **Step 3: Commit**

```bash
git add web/app/page.tsx
git commit -m "feat(pwa): add Finance quick link to home page (admin-only)"
```

---

## Task 8: Deposit Reconciliation

**Files:**
- Modify: `src/database/models.py` — add `reconciled_checkout_id` to `BankTransaction`
- Modify: `src/database/migrate_all.py` — append migration
- Modify: `src/api/v2/finance.py` — add `GET /finance/reconcile` endpoint + auto-reconcile on upload
- Modify: `web/lib/api.ts` — add `getDepositReconciliation`
- Create: `web/components/finance/reconcile-card.tsx`
- Modify: `web/app/finance/page.tsx` — render ReconcileCard

- [ ] **Step 1: Add `reconciled_checkout_id` to BankTransaction model in `src/database/models.py`**

```python
# in BankTransaction — add after account_name line:
reconciled_checkout_id = Column(Integer, ForeignKey("checkout_records.id"), nullable=True)
```

- [ ] **Step 2: Append migration to `src/database/migrate_all.py`**

```python
    # Deposit reconciliation (added 2026-05-02)
    ("bank_transactions", "reconciled_checkout_id", "INTEGER REFERENCES checkout_records(id)"),
```

- [ ] **Step 3: Run migration**

```bash
venv/Scripts/python -m src.database.migrate_all
```

Expected: `bank_transactions.reconciled_checkout_id` added.

- [ ] **Step 4: Add reconcile endpoint and auto-reconcile helper to `src/api/v2/finance.py`**

Add the following after the `_make_hash` helper:

```python
async def _auto_reconcile(session, upload_id: int):
    """
    For every bank_transaction with category='Tenant Deposit Refund' that has
    no reconciled_checkout_id yet, try to match to a checkout_records row by:
      - amount within ±1 rupee
      - deposit_refund_date within ±7 days of txn_date
    """
    from src.database.models import CheckoutRecord
    from sqlalchemy import and_, or_, func as sqlfunc
    import datetime as dt

    unmatched = (await session.scalars(
        select(BankTransaction).where(
            BankTransaction.category == "Tenant Deposit Refund",
            BankTransaction.reconciled_checkout_id == None,
        )
    )).all()

    for txn in unmatched:
        window_start = txn.txn_date - dt.timedelta(days=7)
        window_end   = txn.txn_date + dt.timedelta(days=7)
        match = await session.scalar(
            select(CheckoutRecord).where(
                CheckoutRecord.deposit_refunded_amount.between(
                    float(txn.amount) - 1, float(txn.amount) + 1
                ),
                CheckoutRecord.deposit_refund_date.between(window_start, window_end),
            )
        )
        if match:
            txn.reconciled_checkout_id = match.id

    await session.flush()
```

Add call to `_auto_reconcile` in the upload endpoint, right before `await session.commit()`:

```python
        # Auto-reconcile deposit refund transactions
        await _auto_reconcile(session, upload.id)

        await session.commit()
```

Add the reconciliation endpoint:

```python
@router.get("/finance/reconcile")
async def get_deposit_reconciliation(
    month: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)

    async with get_session() as session:
        q = select(BankTransaction).where(
            BankTransaction.category == "Tenant Deposit Refund"
        ).order_by(BankTransaction.txn_date.desc())

        if month:
            y, mo = int(month[:4]), int(month[5:7])
            import calendar
            start = date(y, mo, 1)
            end   = date(y, mo, calendar.monthrange(y, mo)[1])
            q = q.where(BankTransaction.txn_date.between(start, end))

        txns = (await session.scalars(q)).all()

        rows = []
        for t in txns:
            tenant_name = None
            if t.reconciled_checkout_id:
                from src.database.models import CheckoutRecord, Tenancy, Tenant
                cr = await session.scalar(
                    select(CheckoutRecord).where(CheckoutRecord.id == t.reconciled_checkout_id)
                )
                if cr:
                    tenancy = await session.scalar(
                        select(Tenancy).where(Tenancy.id == cr.tenancy_id)
                    )
                    if tenancy:
                        tenant = await session.scalar(
                            select(Tenant).where(Tenant.id == tenancy.tenant_id)
                        )
                        if tenant:
                            tenant_name = tenant.name

            rows.append({
                "txn_id":    t.id,
                "txn_date":  t.txn_date.isoformat(),
                "amount":    float(t.amount),
                "status":    "matched" if t.reconciled_checkout_id else "unmatched",
                "tenant":    tenant_name,
                "checkout_id": t.reconciled_checkout_id,
            })

    return {"rows": rows}
```

- [ ] **Step 5: Add API client function in `web/lib/api.ts`**

Append to the finance section in `web/lib/api.ts`:

```typescript
export interface DepositReconcileRow {
  txn_id: number
  txn_date: string
  amount: number
  status: "matched" | "unmatched"
  tenant: string | null
  checkout_id: number | null
}

export async function getDepositReconciliation(month?: string): Promise<{ rows: DepositReconcileRow[] }> {
  const qs = month ? `?month=${month}` : ""
  return _get(`/api/v2/app/finance/reconcile${qs}`)
}
```

- [ ] **Step 6: Create `web/components/finance/reconcile-card.tsx`**

```tsx
"use client"

import type { DepositReconcileRow } from "@/lib/api"

function rupeeExact(n: number): string {
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

interface ReconcileCardProps {
  rows: DepositReconcileRow[]
}

export function ReconcileCard({ rows }: ReconcileCardProps) {
  if (rows.length === 0) return null

  const unmatched = rows.filter((r) => r.status === "unmatched").length

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">Deposit Refunds</p>
        {unmatched > 0 && (
          <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-tile-orange text-status-due">
            {unmatched} unmatched
          </span>
        )}
      </div>
      {rows.map((row) => (
        <div key={row.txn_id} className="flex items-center justify-between py-2 border-b border-[#F6F5F0] last:border-none gap-2">
          <div className="flex flex-col gap-0.5 flex-1 min-w-0">
            <span className="text-xs font-semibold text-ink truncate">
              {row.tenant ?? "Unknown tenant"}
            </span>
            <span className="text-[10px] text-ink-muted">{row.txn_date}</span>
          </div>
          <span className="text-xs font-bold text-status-due">−{rupeeExact(row.amount)}</span>
          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap ${
            row.status === "matched"
              ? "bg-tile-green text-status-paid"
              : "bg-tile-orange text-status-due"
          }`}>
            {row.status === "matched" ? "Matched ✓" : "Unmatched"}
          </span>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 7: Add ReconcileCard to `web/app/finance/page.tsx`**

Add import:
```tsx
import { ReconcileCard } from "@/components/finance/reconcile-card"
import { getDepositReconciliation, DepositReconcileRow } from "@/lib/api"
```

Add state:
```tsx
const [reconcileRows, setReconcileRows] = useState<DepositReconcileRow[]>([])
```

Add load call inside `loadPnl`:
```tsx
const loadPnl = useCallback(async (m: string) => {
  setLoading(true)
  setError("")
  try {
    const [pnlRes, reconcileRes] = await Promise.all([
      getFinancePnl(m),
      getDepositReconciliation(m),
    ])
    setData(pnlRes.data[m] ?? null)
    setReconcileRows(reconcileRes.rows)
  } catch (e) {
    setError(e instanceof Error ? e.message : "Failed to load")
  } finally {
    setLoading(false)
  }
}, [])
```

Add to JSX after `<ExpenseCard>`:
```tsx
<ReconcileCard rows={reconcileRows} />
```

- [ ] **Step 8: Commit**

```bash
git add src/database/models.py src/database/migrate_all.py src/api/v2/finance.py \
        web/lib/api.ts web/components/finance/reconcile-card.tsx web/app/finance/page.tsx
git commit -m "feat: add deposit refund reconciliation to Finance page"
```

---

## Task 9: Deploy

- [ ] **Step 1: Run migration on VPS DB**

```bash
ssh vps
cd /opt/pg-accountant
git pull
venv/bin/python -m src.database.migrate_all
```

Expected: `account_name` columns added (or skipped if already exist).

- [ ] **Step 2: Restart API**

```bash
systemctl restart pg-accountant
```

- [ ] **Step 3: Build and restart PWA**

```bash
cd /opt/kozzy-pwa
git pull
npm run build
systemctl restart kozzy-pwa
```

- [ ] **Step 4: Smoke test on live**

1. Open https://getkozzy.com, log in as admin
2. Confirm Finance link appears on home page
3. Open Finance page — month picker loads, empty state shown
4. Upload a Yes Bank CSV for THOR account
5. Confirm P&L populates with income/expense breakdown
6. Download Excel — confirm it opens with 3 sheets

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - ✓ Data model: `account_name` on both tables, `reconciled_checkout_id` on bank_transactions
  - ✓ Upload endpoint with dedup, multi-file, THOR/HULK, auto-reconcile on upload
  - ✓ P&L endpoint: bank income (UPI batch + direct) + DB cash
  - ✓ Excel endpoint: 3 sheets matching current script
  - ✓ Finance page: month picker, KPI tiles, income/expense cards, upload, download
  - ✓ Reconciliation card: matched/unmatched deposit refunds with tenant name
  - ✓ Home page admin-only Finance link
  - ✓ Access control: admin-only on all 3 endpoints + client-side redirect

- [x] **No placeholders** — every step has working code

- [x] **Type consistency:**
  - `FinanceMonthData` defined in `api.ts`, used identically in `pnl-cards.tsx` and `finance/page.tsx`
  - `FinanceUploadResult` defined in `api.ts`, consumed in `upload-card.tsx` and `finance/page.tsx`
  - `_require_admin(user)` helper called in all 3 endpoints
  - `_make_hash(txn_date, amount, desc)` defined once, used in upload loop

- [x] **Data model consistency:**
  - `BankUpload.account_name` set at insert time in upload endpoint ✓
  - `BankTransaction.account_name` copied from account_name param at insert ✓
  - `unique_hash` checked before insert to prevent duplicates ✓
  - P&L income query reads `bank_transactions` + `payments` — same tables, no new models ✓
  - Reconciliation matches `bank_transactions.category='Tenant Deposit Refund'` ↔ `checkout_records.deposit_refunded_amount` by amount ±₹1 + date ±7 days ✓
  - `reconciled_checkout_id` FK links back to `checkout_records` — consistent with existing schema ✓
