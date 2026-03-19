"""
src/whatsapp/handlers/finance_handler.py
=========================================
Bank Statement Analytics — WhatsApp-first financial reporting.

Three entry points:

  handle_bank_upload(file_path, phone, caption, session)
      Called from webhook_handler when owner sends a PDF attachment.
      Parses → classifies → deduplicates → saves to DB → returns summary.

  handle_bank_report(entities, ctx, session)
      Called for BANK_REPORT intent.
      Queries bank_transactions with optional date filter → P&L text summary.

  handle_deposit_match(entities, ctx, session)
      Called for BANK_DEPOSIT_MATCH intent.
      Cross-references bank income transactions against tenant security deposits.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import BankUpload, BankTransaction, Tenancy, Tenant, TenancyStatus
from src.rules.pnl_classify import classify_txn

# ── Month name helpers ─────────────────────────────────────────────────────────

_MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_MONTH_NAME = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _parse_date_range(entities: dict) -> tuple[date, date]:
    """
    Extract (from_date, to_date) from entities.
    Supports:
      - entities["month"] + optional entities["year"]  → full month
      - entities["from_date"] / entities["to_date"]    → explicit range
      - fallback: current month
    """
    today = date.today()

    # Explicit range
    if entities.get("from_date") and entities.get("to_date"):
        return entities["from_date"], entities["to_date"]

    # Month + optional year
    month_num = entities.get("month")
    if month_num:
        year = int(entities.get("year") or today.year)
        month_num = int(month_num)
        # last day of the month
        if month_num == 12:
            last_day = date(year, 12, 31)
        else:
            last_day = date(year, month_num + 1, 1) - timedelta(days=1)
        return date(year, month_num, 1), last_day

    # "last month"
    if entities.get("relative") == "last_month":
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start, last_month_end

    # Default: current month
    first_this = today.replace(day=1)
    if today.month == 12:
        last_this = date(today.year, 12, 31)
    else:
        last_this = date(today.year, today.month + 1, 1) - timedelta(days=1)
    return first_this, last_this


def _txn_hash(txn_date, description: str, amount: float) -> str:
    """Stable SHA-256 fingerprint for deduplication."""
    key = f"{txn_date}|{(description or '').strip().lower()[:80]}|{round(float(amount), 2)}"
    return hashlib.sha256(key.encode()).hexdigest()


# ── 1. Bank statement upload ───────────────────────────────────────────────────

def _load_dataframe(path: Path):
    """Load a bank statement file (PDF / Excel / CSV) into a DataFrame."""
    import pandas as pd
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        from scripts.bank_statement_extractor import extract_transactions
        return extract_transactions(str(path))

    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(str(path))
        # Normalise column names to match PDF extractor output
        df.columns = [str(c).strip() for c in df.columns]
        # Try to find date / debit / credit columns by fuzzy name
        col_map = {}
        for c in df.columns:
            cl = c.lower()
            if any(k in cl for k in ("transaction date", "txn date", "date", "value date")) and "date" not in col_map:
                col_map["Transaction Date"] = c
            if any(k in cl for k in ("withdrawal", "debit", "dr")) and "Withdrawals" not in col_map:
                col_map["Withdrawals"] = c
            if any(k in cl for k in ("deposit", "credit", "cr")) and "Deposits" not in col_map:
                col_map["Deposits"] = c
            if any(k in cl for k in ("description", "narration", "particulars", "remarks")) and "Description" not in col_map:
                col_map["Description"] = c
            if any(k in cl for k in ("ref", "reference", "cheque", "utr")) and "Reference" not in col_map:
                col_map["Reference"] = c
        return df.rename(columns={v: k for k, v in col_map.items()})

    if suffix in (".csv", ".txt"):
        df = pd.read_csv(str(path), encoding="utf-8-sig", on_bad_lines="skip")
        df.columns = [str(c).strip() for c in df.columns]
        col_map = {}
        for c in df.columns:
            cl = c.lower()
            if "date" in cl and "date" not in col_map:
                col_map["Transaction Date"] = c
            if any(k in cl for k in ("withdrawal", "debit", "dr")) and "Withdrawals" not in col_map:
                col_map["Withdrawals"] = c
            if any(k in cl for k in ("deposit", "credit", "cr")) and "Deposits" not in col_map:
                col_map["Deposits"] = c
            if any(k in cl for k in ("description", "narration", "particulars")) and "Description" not in col_map:
                col_map["Description"] = c
        return df.rename(columns={v: k for k, v in col_map.items()})

    raise ValueError(f"Unsupported file type: {suffix}")


async def handle_bank_upload(
    file_path: str,
    phone: str,
    caption: str,
    session: AsyncSession,
) -> str:
    """
    Parse a bank statement PDF/Excel/CSV, classify transactions, save to DB.
    Returns a WhatsApp-friendly summary string.
    """
    path = Path(file_path)
    if not path.exists():
        return "Could not find the uploaded file. Please try again."

    # ── Parse file ─────────────────────────────────────────────────────────────
    try:
        df = _load_dataframe(path)
    except Exception as e:
        return f"Could not parse the file: {e}. Make sure it's a bank statement."

    if df is None or df.empty:
        return "No transactions found. Make sure it's a bank statement (PDF/Excel/CSV)."

    # ── Build transaction list ─────────────────────────────────────────────────
    rows_parsed = 0
    rows_new    = 0
    min_date: Optional[date] = None
    max_date: Optional[date] = None

    # Create upload record first
    upload = BankUpload(phone=phone, file_path=str(path), status="processing")
    session.add(upload)
    await session.flush()   # get upload.id

    for _, row in df.iterrows():
        # Date
        raw_date = row.get("Transaction Date") or row.get("date") or ""
        txn_date = _parse_row_date(str(raw_date))
        if not txn_date:
            continue

        # Amount + direction
        withdrawal = _to_float(row.get("Withdrawals", ""))
        deposit    = _to_float(row.get("Deposits", ""))

        if deposit and deposit > 0:
            amount   = deposit
            txn_type = "income"
        elif withdrawal and withdrawal > 0:
            amount   = withdrawal
            txn_type = "expense"
        else:
            continue

        description = str(row.get("Description") or "").strip()
        ref         = str(row.get("Reference") or "").strip() or None

        # Classify
        cat, sub = classify_txn(description, txn_type)

        # Dedup hash
        h = _txn_hash(txn_date, description, amount)

        # Check duplicate
        existing = await session.scalar(
            select(BankTransaction.id).where(BankTransaction.unique_hash == h)
        )
        rows_parsed += 1
        if existing:
            continue

        txn = BankTransaction(
            upload_id     = upload.id,
            txn_date      = txn_date,
            description   = description,
            amount        = Decimal(str(round(amount, 2))),
            txn_type      = txn_type,
            category      = cat,
            sub_category  = sub,
            upi_reference = ref,
            source        = "bank_statement",
            unique_hash   = h,
        )
        session.add(txn)
        rows_new += 1

        if min_date is None or txn_date < min_date:
            min_date = txn_date
        if max_date is None or txn_date > max_date:
            max_date = txn_date

    # Update upload record
    upload.row_count   = rows_parsed
    upload.new_count   = rows_new
    upload.from_date   = min_date
    upload.to_date     = max_date
    upload.status      = "processed"

    dupes = rows_parsed - rows_new
    date_range = ""
    if min_date and max_date:
        date_range = f" ({min_date.strftime('%d %b %Y')} — {max_date.strftime('%d %b %Y')})"

    lines = [
        f"*Bank Statement Uploaded*{date_range}",
        f"",
        f"Transactions parsed: {rows_parsed}",
        f"New rows saved:      {rows_new}",
    ]
    if dupes:
        lines.append(f"Duplicates skipped:  {dupes}")
    lines += [
        f"",
        f"Reply *bank report* for this month's P&L",
        f"Reply *bank report march* for a specific month",
        f"Reply *match deposits* to identify tenant payments",
    ]
    return "\n".join(lines)


def _parse_row_date(raw: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d %b %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            pass
    # Try with dateparser as fallback
    try:
        import dateparser
        p = dateparser.parse(raw, settings={"RETURN_AS_TIMEZONE_AWARE": False})
        return p.date() if p else None
    except Exception:
        return None


def _to_float(val) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


# ── 2. Bank P&L report ────────────────────────────────────────────────────────

async def handle_bank_report(
    entities: dict,
    ctx,
    session: AsyncSession,
) -> str:
    """
    Query bank_transactions and return a WhatsApp P&L summary.
    Supports date filters from entities.
    """
    from_date, to_date = _parse_date_range(entities)

    # Check if any data exists at all
    total_rows = await session.scalar(select(func.count(BankTransaction.id)))
    if not total_rows:
        return (
            "No bank statement data yet.\n\n"
            "Send me a bank statement PDF and I'll parse it automatically."
        )

    # Query transactions in range
    rows = (await session.execute(
        select(
            BankTransaction.txn_type,
            BankTransaction.category,
            func.sum(BankTransaction.amount).label("total"),
            func.count(BankTransaction.id).label("cnt"),
        )
        .where(
            BankTransaction.txn_date >= from_date,
            BankTransaction.txn_date <= to_date,
        )
        .group_by(BankTransaction.txn_type, BankTransaction.category)
        .order_by(BankTransaction.txn_type, func.sum(BankTransaction.amount).desc())
    )).all()

    if not rows:
        range_label = _range_label(from_date, to_date)
        return f"No transactions found for {range_label}. Try a different date range."

    # Separate income vs expense
    income_rows  = [(r.category, float(r.total), r.cnt) for r in rows if r.txn_type == "income"]
    expense_rows = [(r.category, float(r.total), r.cnt) for r in rows if r.txn_type == "expense"]

    total_income  = sum(v for _, v, _ in income_rows)
    total_expense = sum(v for _, v, _ in expense_rows)
    net           = total_income - total_expense
    net_sign      = "+" if net >= 0 else "-"

    range_label = _range_label(from_date, to_date)
    lines = [f"*Bank P&L Report — {range_label}*", ""]

    # Income section
    lines.append(f"*INCOME — Rs.{total_income:,.0f}*")
    for cat, total, cnt in income_rows[:8]:   # cap at 8 categories
        lines.append(f"  {cat}: Rs.{total:,.0f}  ({cnt} txns)")
    if len(income_rows) > 8:
        lines.append(f"  …and {len(income_rows)-8} more categories")

    lines.append("")
    lines.append(f"*EXPENSES — Rs.{total_expense:,.0f}*")
    for cat, total, cnt in expense_rows[:12]:
        lines.append(f"  {cat}: Rs.{total:,.0f}  ({cnt} txns)")
    if len(expense_rows) > 12:
        lines.append(f"  …and {len(expense_rows)-12} more categories")

    lines.append("")
    lines.append(f"*NET: {net_sign}Rs.{abs(net):,.0f}*")

    lines += [
        "",
        f"_Data: {from_date.strftime('%d %b')} — {to_date.strftime('%d %b %Y')}_",
        "_Reply *match deposits* to identify tenant advance payments_",
    ]
    return "\n".join(lines)


def _range_label(from_date: date, to_date: date) -> str:
    """'March 2026' if full month, else 'Mar 1 — Mar 31 2026'."""
    if from_date.day == 1:
        # check if to_date is last day of same month
        if from_date.year == to_date.year and from_date.month == to_date.month:
            import calendar
            last = calendar.monthrange(from_date.year, from_date.month)[1]
            if to_date.day == last:
                return f"{from_date.strftime('%B %Y')}"
    return f"{from_date.strftime('%d %b')} — {to_date.strftime('%d %b %Y')}"


# ── 3. Deposit matching ───────────────────────────────────────────────────────

async def handle_deposit_match(
    entities: dict,
    ctx,
    session: AsyncSession,
) -> str:
    """
    Cross-reference bank income transactions with tenant security deposits.

    Matching logic:
      1. Load all active + exited tenancies with security_deposit > 0
      2. Load bank income transactions filtered by date range
      3. For each tenancy, look for a bank txn where:
           a. amount is within 10% of security_deposit  AND
           b. txn_date within ±45 days of check_in_date
              OR  tenant name appears in description
      4. Show matched pairs + unmatched deposits
    """
    from_date, to_date = _parse_date_range(entities)

    # Widen the income window slightly (deposits may arrive before check-in)
    income_from = from_date - timedelta(days=45)
    income_to   = to_date   + timedelta(days=45)

    # ── Load tenancies ─────────────────────────────────────────────────────────
    tenancy_rows = (await session.execute(
        select(
            Tenancy.id,
            Tenancy.security_deposit,
            Tenancy.check_in_date,
            Tenant.name,
            Tenant.phone,
        )
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .where(
            Tenancy.security_deposit > 0,
            or_(
                Tenancy.check_in_date >= income_from,
                Tenancy.check_in_date <= income_to,
            ),
        )
        .order_by(Tenancy.check_in_date.desc())
    )).all()

    if not tenancy_rows:
        return "No tenancies with security deposits found in this period."

    # ── Load income transactions ───────────────────────────────────────────────
    income_txns = (await session.execute(
        select(BankTransaction)
        .where(
            BankTransaction.txn_type == "income",
            BankTransaction.txn_date >= income_from,
            BankTransaction.txn_date <= income_to,
        )
        .order_by(BankTransaction.txn_date)
    )).scalars().all()

    if not income_txns:
        return (
            "No income transactions in the bank statement for this period.\n\n"
            "Upload a bank statement PDF first."
        )

    # ── Match ──────────────────────────────────────────────────────────────────
    used_txn_ids: set[int] = set()
    matched:   list[str] = []
    unmatched: list[str] = []

    for ten_id, dep_amount, checkin, name, phone in tenancy_rows:
        dep = float(dep_amount or 0)
        if dep <= 0:
            continue
        first_name = (name or "").split()[0].lower() if name else ""

        best: Optional[BankTransaction] = None
        best_score = 0

        for txn in income_txns:
            if txn.id in used_txn_ids:
                continue
            txn_amt = float(txn.amount)
            desc    = (txn.description or "").lower()

            # Amount match: within 10%
            if abs(txn_amt - dep) / max(dep, 1) > 0.10:
                continue

            score = 0
            # Date proximity to check-in
            if checkin:
                days_diff = abs((txn.txn_date - checkin).days)
                if days_diff <= 7:
                    score += 3
                elif days_diff <= 30:
                    score += 2
                elif days_diff <= 45:
                    score += 1

            # Name in description
            if first_name and first_name in desc:
                score += 2

            if score > best_score:
                best_score = score
                best = txn

        checkin_str = checkin.strftime("%d %b %Y") if checkin else "?"
        if best:
            used_txn_ids.add(best.id)
            matched.append(
                f"  {name} ({checkin_str}) → Rs.{dep:,.0f} matched "
                f"{best.txn_date.strftime('%d %b')} Rs.{float(best.amount):,.0f}"
            )
        else:
            unmatched.append(f"  {name} ({checkin_str}) — Rs.{dep:,.0f} *NOT FOUND* in bank")

    # Unmatched income (income txns with no tenancy match)
    unmatched_income = [
        t for t in income_txns
        if t.id not in used_txn_ids
        and float(t.amount) >= 5000    # only show large credits
    ]

    lines = ["*Deposit Matching Report*", ""]

    if matched:
        lines.append(f"*Matched ({len(matched)}):*")
        lines.extend(matched[:20])

    if unmatched:
        lines.append("")
        lines.append(f"*Not found in bank ({len(unmatched)}):*")
        lines.extend(unmatched[:15])

    if unmatched_income:
        lines.append("")
        lines.append(f"*Unmatched income credits (≥ Rs.5,000):*")
        for t in unmatched_income[:10]:
            lines.append(
                f"  {t.txn_date.strftime('%d %b')}  Rs.{float(t.amount):,.0f}  {t.description[:40]}"
            )

    if not matched and not unmatched:
        lines.append("No matching tenancies found for this date range.")

    return "\n".join(lines)
