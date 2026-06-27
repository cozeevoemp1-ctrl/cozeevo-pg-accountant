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
        return float(str(v).replace(",", "").replace("?", "").replace("₹", "").strip())
    except ValueError:
        return 0.0


def parse_balance(v) -> float | None:
    """Parse running balance like 'INR 1,23,456.78' or '?1,23,456.78' → float."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("INR", "").replace("?", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _open_text(source) -> tuple:
    """Return (text_file, close_after)."""
    if isinstance(source, str):
        return open(source, "r", encoding="utf-8-sig", errors="replace"), True
    if isinstance(source, (bytes, bytearray)):
        return io.StringIO(source.decode("utf-8-sig", errors="replace")), False
    if hasattr(source, "read"):
        raw = source.read()
        if isinstance(raw, bytes):
            return io.StringIO(raw.decode("utf-8-sig", errors="replace")), False
        return io.StringIO(raw), False
    return source, False


def read_yes_bank_csv(
    source: Union[str, IO],
) -> list[tuple[date, str, str, float, float | None]]:
    """
    Parse a Yes Bank CSV/Excel bank statement.

    Columns are mapped by HEADER NAME (not fixed position) so every Yes Bank
    export layout is handled, including:
      • THOR (full export): Transaction Date, Value Date, Description,
        Reference Number, Withdrawals, Deposits, Running Balance
      • HULK (collection account): Transaction Date, Value Date, Description,
        Reference Number, Deposits, Running Balance   ← NO Withdrawals column
      • legacy app export with a 'Txn Date' header

    CRITICAL: HULK's header also starts with 'Transaction Date' but has only a
    Deposits column. Mapping by name (never by index) prevents the deposits
    column from being misread as withdrawals — which would book every tenant
    collection as an expense.

    Returns list of (txn_date, description, txn_type, amount, balance) where
    txn_type is 'income' or 'expense' and balance is the running balance or None.
    """
    f, close_after = _open_text(source)
    out: list[tuple[date, str, str, float, float | None]] = []
    try:
        lines = f.readlines()
    finally:
        if close_after:
            f.close()

    # Find the header row and parse its column names
    header_idx = None
    header_cols: list[str] = []
    for i, line in enumerate(lines):
        low = line.lower()
        if ("transaction date" in low or "txn date" in low) and (
            "description" in low or "value date" in low
        ):
            header_cols = next(_csv.reader([line]))
            header_idx = i
            break

    if header_idx is None:
        return out

    # Map column name → index (normalised, first match wins)
    idx = {(name or "").strip().lower(): j for j, name in enumerate(header_cols)}

    def col(*names: str) -> int | None:
        for n in names:
            if n in idx:
                return idx[n]
        return None

    date_i = col("transaction date", "txn date", "date")
    desc_i = col("description", "narration", "particulars")
    wd_i   = col("withdrawals", "withdrawal", "debit", "dr", "debit amount")
    dep_i  = col("deposits", "deposit", "credit", "cr", "credit amount")
    bal_i  = col("running balance", "balance", "closing balance")

    # Must have a date and at least one money column to be parseable
    if date_i is None or (wd_i is None and dep_i is None):
        return out

    data_lines = lines[header_idx + 1:]
    reader = _csv.reader(data_lines)

    for row in reader:
        if not row or len(row) <= date_i:
            continue
        try:
            dt = parse_date(row[date_i])
            if not dt:
                continue
            desc = row[desc_i].strip() if desc_i is not None and len(row) > desc_i else ""
            wd   = parse_amt(row[wd_i]) if wd_i is not None and len(row) > wd_i else 0.0
            dep  = parse_amt(row[dep_i]) if dep_i is not None and len(row) > dep_i else 0.0
            bal  = parse_balance(row[bal_i]) if bal_i is not None and len(row) > bal_i else None
        except (IndexError, ValueError):
            continue

        if wd > 0:
            out.append((dt, desc, "expense", wd, bal))
        if dep > 0:
            out.append((dt, desc, "income", dep, bal))

    return out
