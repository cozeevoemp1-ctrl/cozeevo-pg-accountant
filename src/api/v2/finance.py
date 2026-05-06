"""
src/api/v2/finance.py
Finance endpoints — CSV upload, P&L dashboard, Excel download.
Owner-only (admin role required on every endpoint).
"""
from __future__ import annotations

import hashlib
import io
import logging
import re as _re
import calendar as _calendar
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    BankTransaction, BankUpload, CheckoutRecord, Payment, PaymentFor, PaymentMode,
    Tenancy, Tenant,
)
from src.parsers.yes_bank import read_yes_bank_csv
from src.reports.pnl_builder import build_pnl_bytes
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

# Only these categories reduce operating profit
_OPEX_CATS_JSON = {
    "Property Rent", "Electricity", "Water", "IT & Software", "Internet & WiFi",
    "Food & Groceries", "Fuel & Diesel", "Staff & Labour",
    "Maintenance & Repairs", "Cleaning Supplies", "Waste Disposal",
    "Shopping & Supplies", "Operational Expenses", "Marketing",
    "Govt & Regulatory", "Bank Charges", "Other Expenses",
}
# Shown separately below operating profit
_CAPEX_CATS_JSON = {"Furniture & Fittings", "Capital Investment"}
# Balance-sheet items — shown for info only, never deducted from any profit line
_EXCL_CATS_JSON  = {"Tenant Deposit Refund", "Non-Operating"}


def _require_admin(user: AppUser):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _make_hash(txn_date: date, amount: float, desc: str) -> str:
    key = f"{txn_date}|{(desc or '').strip().lower()[:80]}|{round(float(amount), 2)}"
    return hashlib.sha256(key.encode()).hexdigest()


async def _auto_reconcile(session):
    """
    For every bank_transaction with category='Tenant Deposit Refund' and no
    reconciled_checkout_id yet, try to match to a checkout_records row by:
      - amount within ±1 rupee
      - deposit_refund_date within ±7 days of txn_date
    """
    import datetime as _dt

    try:
        unmatched = (await session.scalars(
            select(BankTransaction).where(
                BankTransaction.category == "Tenant Deposit Refund",
                BankTransaction.reconciled_checkout_id == None,
            )
        )).all()

        for txn in unmatched:
            window_start = txn.txn_date - _dt.timedelta(days=7)
            window_end   = txn.txn_date + _dt.timedelta(days=7)
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
    except Exception:
        logger.exception("_auto_reconcile failed — upload committed without reconciliation")


def _validate_month(m: str, param: str = "month"):
    if not _re.fullmatch(r"\d{4}-\d{2}", m):
        raise HTTPException(status_code=400, detail=f"{param} must be YYYY-MM")


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

            rows = read_yes_bank_csv(content)
            if not rows:
                continue

            from_date = min(r[0] for r in rows)
            to_date   = max(r[0] for r in rows)

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
            await session.flush()

            new_count = 0
            for txn_date, desc, txn_type, amount in rows:
                uhash = _make_hash(txn_date, amount, desc)
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

        await _auto_reconcile(session)
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
    if month:
        _validate_month(month)

    async with get_session() as session:
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
            start = date(y, mo, 1)
            end = date(y, mo, _calendar.monthrange(y, mo)[1])
            period_date = date(y, mo, 1)  # Payment.period_month is stored as 1st of month

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
            # "Rent Income" = UPI collection settlements + direct UPI from tenants
            # "Other Income" + "Advance Deposit" = NEFT/RTGS inward, cashback, deposits
            upi_batch   = bank_income.get("Rent Income", 0.0)
            direct_neft = sum(v for k, v in bank_income.items() if k != "Rent Income")

            cash_rows = await session.execute(
                select(func.sum(Payment.amount))
                .where(
                    Payment.payment_mode == PaymentMode.cash,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void == False,
                    Payment.period_month == period_date,
                )
            )
            cash_db = float(cash_rows.scalar() or 0)

            cap_rows = await session.execute(
                select(func.sum(BankTransaction.amount))
                .where(
                    BankTransaction.category == "Capital Investment",
                    BankTransaction.txn_date.between(start, end),
                )
            )
            capital = float(cap_rows.scalar() or 0)

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
                if expense_by_cat.get(cat, 0.0) > 0 and cat in _OPEX_CATS_JSON
            ]
            capex_items = [
                {"category": cat, "amount": expense_by_cat.get(cat, 0.0)}
                for cat in EXPENSE_CATS
                if expense_by_cat.get(cat, 0.0) > 0 and cat in _CAPEX_CATS_JSON
            ]
            excluded_items = [
                {"category": cat, "amount": expense_by_cat.get(cat, 0.0)}
                for cat in EXPENSE_CATS
                if expense_by_cat.get(cat, 0.0) > 0 and cat in _EXCL_CATS_JSON
            ]

            total_expense    = sum(e["amount"] for e in expenses)
            total_capex      = sum(e["amount"] for e in capex_items)
            # Deposits received this month (from tenancies by check-in date)
            dep_recv_rows = await session.execute(
                select(func.sum(Tenancy.security_deposit + Tenancy.maintenance_fee))
                .where(
                    func.date_trunc("month", Tenancy.checkin_date) == start,
                    Tenancy.status != "no_show",
                )
            )
            deposits_received = float(dep_recv_rows.scalar() or 0)

            # Deposit refunds paid this month (from checkout_records)
            dep_ref_rows = await session.execute(
                select(func.sum(CheckoutRecord.deposit_refunded_amount))
                .where(
                    CheckoutRecord.deposit_refund_date.between(start, end),
                    CheckoutRecord.deposit_refunded_amount > 0,
                )
            )
            deposits_refunded = float(dep_ref_rows.scalar() or 0)

            total_gross      = upi_batch + direct_neft + cash_db
            net_dep_adj      = -deposits_received + deposits_refunded
            total_income     = total_gross + net_dep_adj  # true rent revenue
            operating_profit = total_income - total_expense
            net_profit       = operating_profit - total_capex
            margin           = round(operating_profit / total_income * 100, 1) if total_income else 0.0

            result[m] = {
                "month": m,
                "income": {
                    "upi_batch":          upi_batch,
                    "direct_neft":        direct_neft,
                    "cash_db":            cash_db,
                    "total_gross":        total_gross,
                    "deposits_received":  deposits_received,
                    "deposits_refunded":  deposits_refunded,
                    "total":              total_income,   # true revenue (deposits stripped)
                },
                "capital":          capital,
                "expenses":         expenses,
                "capex_items":      capex_items,
                "excluded_items":   excluded_items,
                "total_expense":    total_expense,
                "total_capex":      total_capex,
                "operating_profit": operating_profit,
                "net_profit":       net_profit,
                "margin_pct":       margin,
            }

    return {"months": target_months, "data": result}


# ── Excel Download — P&L Summary ──────────────────────────────────────────────

# Categories that belong in operating expenses (reduce operating profit)
_OPEX_CATS = [
    "Property Rent", "Electricity", "Water", "IT & Software", "Internet & WiFi",
    "Food & Groceries", "Fuel & Diesel", "Staff & Labour", "Maintenance & Repairs",
    "Cleaning Supplies", "Waste Disposal", "Shopping & Supplies",
    "Operational Expenses", "Marketing", "Govt & Regulatory", "Bank Charges",
    "Other Expenses",
]
# Balance-sheet items — shown for reference but NOT deducted from operating profit
_EXCLUDED_CATS = ["Tenant Deposit Refund", "Non-Operating"]
# Capital expenditure — shown below operating profit
_CAPEX_CATS = ["Furniture & Fittings", "Capital Investment"]


@router.get("/finance/pnl/excel")
async def download_pnl_excel(user: AppUser = Depends(get_current_user)):
    """Verified canonical P&L (Oct'25–Apr'26) — same as local export script."""
    _require_admin(user)
    buf = io.BytesIO(build_pnl_bytes())
    filename = f"PnL_Cozeevo_Verified_{datetime.now().strftime('%Y_%m_%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/finance/pnl/live")
async def download_pnl_live(user: AppUser = Depends(get_current_user)):
    """
    Live P&L recomputed from DB — picks up any new CSV uploads (HULK, new months).
    Reclassifies every transaction with the current classifier rules.
    """
    _require_admin(user)

    async with get_session() as session:
        txn_rows = (await session.scalars(
            select(BankTransaction).order_by(BankTransaction.txn_date)
        )).all()

        all_months = sorted({r.txn_date.strftime("%Y-%m") for r in txn_rows})
        if not all_months:
            raise HTTPException(status_code=404, detail="No bank transactions in DB")

        by_cat_month: dict = defaultdict(lambda: defaultdict(float))
        by_sub_month: dict = defaultdict(float)
        bank_upi_batch: dict = defaultdict(float)
        bank_direct:    dict = defaultdict(float)

        for r in txn_rows:
            m = r.txn_date.strftime("%Y-%m")
            cat, sub = classify_txn(r.description or "", r.txn_type or "")
            if r.txn_type == "income":
                if cat == "Rent Income":
                    bank_upi_batch[m] += float(r.amount)
                else:
                    bank_direct[m] += float(r.amount)
            else:
                by_cat_month[cat][m] += float(r.amount)
                by_sub_month[(cat, sub, m)] += float(r.amount)

        cash_rows = await session.execute(
            select(
                func.to_char(Payment.period_month, "YYYY-MM"),
                func.sum(Payment.amount),
            )
            .where(
                Payment.payment_mode == PaymentMode.cash,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
            )
            .group_by(func.to_char(Payment.period_month, "YYYY-MM"))
        )
        cash_by_month: dict = {row[0]: float(row[1]) for row in cash_rows}

        # Deposits received by check-in month (security + maintenance — liability inflows)
        dep_recv_rows = await session.execute(
            select(
                func.to_char(func.date_trunc("month", Tenancy.checkin_date), "YYYY-MM"),
                func.sum(Tenancy.security_deposit + Tenancy.maintenance_fee),
            )
            .where(Tenancy.status != "no_show")
            .group_by(func.date_trunc("month", Tenancy.checkin_date))
        )
        dep_recv_by_month: dict = {row[0]: float(row[1]) for row in dep_recv_rows if row[0]}

        # Deposit refunds paid by refund date
        dep_ref_rows = await session.execute(
            select(
                func.to_char(func.date_trunc("month", CheckoutRecord.deposit_refund_date), "YYYY-MM"),
                func.sum(CheckoutRecord.deposit_refunded_amount),
            )
            .where(CheckoutRecord.deposit_refunded_amount > 0)
            .group_by(func.date_trunc("month", CheckoutRecord.deposit_refund_date))
        )
        dep_ref_by_month: dict = {row[0]: float(row[1]) for row in dep_ref_rows if row[0]}

    wb = _build_pnl_excel(all_months, bank_upi_batch, bank_direct, cash_by_month,
                          by_cat_month, by_sub_month,
                          dep_recv_by_month, dep_ref_by_month)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"PnL_Live_{datetime.now().strftime('%Y_%m_%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _month_label(m: str) -> str:
    """'2025-10' → \"Oct'25\""""
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    y, mo = int(m[:4]), int(m[5:7])
    return f"{months[mo-1]}'{str(y)[2:]}"


def _build_pnl_excel(
    all_months: list,
    bank_upi: dict, bank_direct: dict, cash_db: dict,
    by_cat: dict, by_sub: dict,
    dep_recv: dict | None = None,
    dep_ref: dict | None = None,
) -> openpyxl.Workbook:
    HDR_FILL  = PatternFill("solid", fgColor="1F4E78")
    HDR_FONT  = Font(bold=True, color="FFFFFF", size=10)
    SEC_FILL  = PatternFill("solid", fgColor="2E3F5C")
    SEC_FONT  = Font(bold=True, color="FFFFFF", size=10)
    ALT_FILL  = PatternFill("solid", fgColor="EEF4FF")
    WHT_FILL  = PatternFill("solid", fgColor="FFFFFF")
    GRN_FILL  = PatternFill("solid", fgColor="E2EFDA")
    RED_FILL  = PatternFill("solid", fgColor="FCE4D6")
    EXC_FILL  = PatternFill("solid", fgColor="FFF2CC")
    CAP_FILL  = PatternFill("solid", fgColor="EDEDED")
    BOLD      = Font(bold=True)
    BOLD_GRN  = Font(bold=True, color="375623")
    BOLD_RED  = Font(bold=True, color="9C0006")
    CTR       = Alignment(horizontal="center", vertical="center")
    RIGHT     = Alignment(horizontal="right",  vertical="center")
    LEFT      = Alignment(horizontal="left",   vertical="center")
    NUM_FMT   = INR_NUMBER_FORMAT

    nc = len(all_months) + 2  # label col + month cols + total col

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L Summary"

    def _hdr(col, val, width=14):
        c = ws.cell(1, col, val)
        c.fill = HDR_FILL; c.font = HDR_FONT; c.alignment = CTR
        ws.column_dimensions[get_column_letter(col)].width = width

    # Header row
    _hdr(1, "Category", width=36)
    for ci, m in enumerate(all_months, 2):
        _hdr(ci, _month_label(m))
    _hdr(nc, "TOTAL")
    ws.row_dimensions[1].height = 22

    ri = [2]  # mutable row counter

    def _section(label):
        for col in range(1, nc + 1):
            c = ws.cell(ri[0], col)
            c.fill = SEC_FILL
        ws.cell(ri[0], 1, label).font = SEC_FONT
        ws.cell(ri[0], 1).alignment = LEFT
        ws.row_dimensions[ri[0]].height = 18
        ri[0] += 1

    def _data_row(label, vals_by_month, fill, font=None, indent=False, num_fmt=NUM_FMT):
        lbl = f"  {label}" if indent else label
        c = ws.cell(ri[0], 1, lbl)
        c.fill = fill
        if font: c.font = font
        else: c.font = Font(size=9)
        c.alignment = LEFT
        total = 0.0
        for ci, m in enumerate(all_months, 2):
            v = vals_by_month.get(m, 0.0)
            total += v
            cell = ws.cell(ri[0], ci, round(v) if v else None)
            cell.fill = fill
            if v: cell.number_format = num_fmt
            if font: cell.font = font
            else: cell.font = Font(size=9)
            cell.alignment = RIGHT
        tc = ws.cell(ri[0], nc, round(total) if total else None)
        tc.fill = fill
        if total: tc.number_format = num_fmt
        if font: tc.font = font
        else: tc.font = Font(size=9, bold=True)
        tc.alignment = RIGHT
        ri[0] += 1
        return total

    def _total_row(label, totals_by_month, fill, font):
        c = ws.cell(ri[0], 1, label)
        c.fill = fill; c.font = font; c.alignment = LEFT
        grand = 0.0
        for ci, m in enumerate(all_months, 2):
            v = totals_by_month.get(m, 0.0)
            grand += v
            cell = ws.cell(ri[0], ci, round(v) if v else None)
            cell.fill = fill; cell.font = font; cell.alignment = RIGHT
            if v: cell.number_format = NUM_FMT
        tc = ws.cell(ri[0], nc, round(grand) if grand else None)
        tc.fill = fill; tc.font = font; tc.alignment = RIGHT
        if grand: tc.number_format = NUM_FMT
        ws.row_dimensions[ri[0]].height = 16
        ri[0] += 1
        return grand

    def _blank():
        ri[0] += 1

    DEP_FILL  = PatternFill("solid", fgColor="FFF2CC")
    TRUE_FILL = PatternFill("solid", fgColor="E2EFDA")
    BOLD_DEP  = Font(bold=True, color="7F6000", size=9)

    dep_recv  = dep_recv or {}
    dep_ref   = dep_ref  or {}

    # ── GROSS INFLOWS ─────────────────────────────────────────────────────────
    _section("GROSS INFLOWS")
    gross_month: dict = defaultdict(float)
    for m in all_months:
        gross_month[m] = bank_upi.get(m, 0) + bank_direct.get(m, 0) + cash_db.get(m, 0)

    fill = ALT_FILL
    for label, src in [
        ("Bank — UPI batch settlements (merchant QR)", bank_upi),
        ("Bank — direct UPI / NEFT payments",          bank_direct),
        ("Cash collected (not deposited to bank)",     cash_db),
    ]:
        if sum(src.values()):
            _data_row(label, src, fill, indent=True)
            fill = WHT_FILL if fill == ALT_FILL else ALT_FILL

    _total_row("Total Gross Inflows", gross_month, GRN_FILL, BOLD_GRN)

    # ── DEPOSIT ADJUSTMENT ────────────────────────────────────────────────────
    neg_recv: dict = {m: -dep_recv.get(m, 0) for m in all_months}
    pos_ref:  dict = {m:  dep_ref.get(m, 0)  for m in all_months}
    net_dep:  dict = {m: neg_recv[m] + pos_ref[m] for m in all_months}

    if any(v for v in dep_recv.values()) or any(v for v in dep_ref.values()):
        _data_row("(-) Deposits received (security + maintenance, by check-in month)",
                  neg_recv, DEP_FILL, font=Font(size=9, color="7F6000"), indent=True)
        _data_row("(+) Deposit refunds paid to exiting tenants",
                  pos_ref,  DEP_FILL, font=Font(size=9, color="375623"), indent=True)
        _total_row("Net Deposit Adjustment", net_dep, DEP_FILL, BOLD_DEP)

    # ── TRUE REVENUE ──────────────────────────────────────────────────────────
    true_rev_month: dict = {m: gross_month.get(m, 0) + net_dep.get(m, 0) for m in all_months}
    _total_row("True Revenue (rent only — deposits excluded)", true_rev_month, TRUE_FILL,
               Font(bold=True, color="375623"))
    _blank()

    # ── OPERATING EXPENSES ────────────────────────────────────────────────────
    _section("OPERATING EXPENSES")
    opex_month: dict = defaultdict(float)
    for cat in _OPEX_CATS:
        cat_data = by_cat.get(cat, {})
        if not any(cat_data.values()):
            continue
        fill = ALT_FILL if ri[0] % 2 == 0 else WHT_FILL
        _data_row(cat, cat_data, fill, indent=True)
        for m, v in cat_data.items():
            opex_month[m] += v

    _total_row("Total Operating Expenses", opex_month, RED_FILL, BOLD_RED)
    _blank()

    # ── OPERATING PROFIT (on True Revenue) ───────────────────────────────────
    op_profit_month: dict = {m: true_rev_month.get(m, 0) - opex_month.get(m, 0) for m in all_months}
    _total_row("Operating Profit (on True Revenue)", op_profit_month, GRN_FILL, BOLD_GRN)
    _blank()

    # ── EXCLUDED (balance sheet items — for reference only) ───────────────────
    has_excluded = any(by_cat.get(c, {}) for c in _EXCLUDED_CATS)
    if has_excluded:
        _section("BALANCE SHEET ITEMS (not deducted above)")
        for cat in _EXCLUDED_CATS:
            cat_data = by_cat.get(cat, {})
            if not any(cat_data.values()):
                continue
            fill = ALT_FILL if ri[0] % 2 == 0 else WHT_FILL
            _data_row(cat, cat_data, EXC_FILL, indent=True)
        _blank()

    # ── CAPEX ─────────────────────────────────────────────────────────────────
    capex_month: dict = defaultdict(float)
    has_capex = any(by_cat.get(c, {}) for c in _CAPEX_CATS)
    if has_capex:
        _section("CAPITAL EXPENDITURE (one-time investments)")
        for cat in _CAPEX_CATS:
            cat_data = by_cat.get(cat, {})
            if not any(cat_data.values()):
                continue
            _data_row(cat, cat_data, CAP_FILL, indent=True)
            for m, v in cat_data.items():
                capex_month[m] += v
        _total_row("Total CAPEX", capex_month, CAP_FILL, BOLD)
        _blank()

    # ── NET PROFIT ────────────────────────────────────────────────────────────
    net_month = {m: op_profit_month.get(m, 0) - capex_month.get(m, 0) for m in all_months}
    _total_row("Net Profit after CAPEX", net_month, GRN_FILL, BOLD_GRN)

    ws.freeze_panes = "B2"
    ws.row_dimensions[1].height = 22

    # ── Sheet 2: Sub-category Breakdown ──────────────────────────────────────
    ws2 = wb.create_sheet("Sub-category Detail")
    sub_hdrs = ["Category", "Sub-category"] + [_month_label(m) for m in all_months] + ["TOTAL"]
    for col, h in enumerate(sub_hdrs, 1):
        c = ws2.cell(1, col, h)
        c.fill = HDR_FILL; c.font = HDR_FONT; c.alignment = CTR
    ws2.column_dimensions["A"].width = 26
    ws2.column_dimensions["B"].width = 38
    for i in range(3, len(all_months) + 4):
        ws2.column_dimensions[get_column_letter(i)].width = 14

    ri2 = 2
    all_cats = _OPEX_CATS + _EXCLUDED_CATS + _CAPEX_CATS
    for cat in all_cats:
        subs = sorted({s for (c2, s, m), v in by_sub.items() if c2 == cat and v > 0})
        if not subs:
            continue
        c = ws2.cell(ri2, 1, cat)
        c.fill = SEC_FILL; c.font = SEC_FONT
        for col in range(2, len(all_months) + 4):
            ws2.cell(ri2, col).fill = SEC_FILL
        ri2 += 1
        for sub in subs:
            fill = ALT_FILL if ri2 % 2 == 0 else WHT_FILL
            ws2.cell(ri2, 2, sub).fill = fill
            sub_total = 0.0
            for ci, m in enumerate(all_months, 3):
                v = by_sub.get((cat, sub, m), 0)
                sub_total += v
                c2 = ws2.cell(ri2, ci, round(v) if v else None)
                c2.fill = fill
                if v: c2.number_format = NUM_FMT
            tc = ws2.cell(ri2, len(all_months) + 3, round(sub_total) if sub_total else None)
            tc.fill = fill
            if sub_total: tc.number_format = NUM_FMT; tc.font = Font(bold=True)
            ri2 += 1
    ws2.freeze_panes = "C2"

    return wb


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
    monthly_sub: dict = defaultdict(float)

    INCOME_CATS = ["Rent Income", "Advance Deposit", "Other Income"]

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

    op_profit = [inc_totals[i] - exp_totals[i] for i in range(len(inc_totals))]
    _write_row(ws, ri, "OPERATING PROFIT (EBITDA)", op_profit, font=TOT_FONT)
    ri += 2

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


# ── Deposit Reconciliation ─────────────────────────────────────────────────────

@router.get("/finance/reconcile")
async def get_deposit_reconciliation(
    month: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
):
    _require_admin(user)
    if month:
        _validate_month(month)

    async with get_session() as session:
        q = select(BankTransaction).where(
            BankTransaction.category == "Tenant Deposit Refund"
        ).order_by(BankTransaction.txn_date.desc())

        if month:
            y, mo = int(month[:4]), int(month[5:7])
            start = date(y, mo, 1)
            end   = date(y, mo, _calendar.monthrange(y, mo)[1])
            q = q.where(BankTransaction.txn_date.between(start, end))

        txns = (await session.scalars(q)).all()

        rows = []
        for t in txns:
            tenant_name = None
            if t.reconciled_checkout_id:
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
                "txn_id":      t.id,
                "txn_date":    t.txn_date.isoformat(),
                "amount":      float(t.amount),
                "status":      "matched" if t.reconciled_checkout_id else "unmatched",
                "tenant":      tenant_name,
                "checkout_id": t.reconciled_checkout_id,
            })

    return {"rows": rows}
