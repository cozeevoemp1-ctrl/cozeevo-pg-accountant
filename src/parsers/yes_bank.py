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

    Supports two layouts:
      • THOR (Yes Bank web export): header starts with 'Transaction Date';
        cols 0=date, 2=desc, 4=withdrawal, 5=deposit, 6=running balance ('INR X')
      • HULK (Yes Bank app export): header row contains 'Txn Date';
        cols 1=date, 3=desc, 5=withdrawal, 6=deposit, 7=balance ('?X')

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

    # Detect layout by scanning for the header row
    header_idx = None
    layout = "thor"
    for i, line in enumerate(lines):
        if line.startswith("Transaction Date"):
            header_idx = i
            layout = "thor"
            break
        if "Txn Date" in line and "Value Date" in line:
            header_idx = i
            layout = "hulk"
            break

    if header_idx is None:
        return out

    data_lines = lines[header_idx + 1:]
    reader = _csv.reader(data_lines)

    for row in reader:
        if len(row) < 4:
            continue
        try:
            if layout == "thor":
                dt = parse_date(row[0])
                desc = row[2].strip() if len(row) > 2 else ""
                wd   = parse_amt(row[4]) if len(row) > 4 else 0.0
                dep  = parse_amt(row[5]) if len(row) > 5 else 0.0
                bal  = parse_balance(row[6]) if len(row) > 6 else None
            else:  # hulk
                dt = parse_date(row[1])
                desc = row[3].strip() if len(row) > 3 else ""
                wd   = parse_amt(row[5]) if len(row) > 5 else 0.0
                dep  = parse_amt(row[6]) if len(row) > 6 else 0.0
                bal  = parse_balance(row[7]) if len(row) > 7 else None
        except (IndexError, ValueError):
            continue

        if not dt:
            continue
        if wd > 0:
            out.append((dt, desc, "expense", wd, bal))
        if dep > 0:
            out.append((dt, desc, "income", dep, bal))

    return out
