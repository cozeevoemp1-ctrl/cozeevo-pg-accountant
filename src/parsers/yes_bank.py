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
