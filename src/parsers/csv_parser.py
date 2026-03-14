"""
Generic CSV parser — maps any CSV to the standard transaction schema.
Uses a flexible column mapping so different banks/apps can be supported
without code changes — just supply a column_map in the config.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional

from loguru import logger

from src.parsers.base_parser import BaseParser


# Commonly seen column names across Indian bank/UPI exports
_COLUMN_ALIASES: dict[str, list[str]] = {
    "date": [
        "date", "transaction date", "txn date", "value date",
        "posted date", "booking date", "transaction_date", "Date",
    ],
    "amount": [
        "amount", "transaction amount", "txn amount", "debit", "credit",
        "amount (inr)", "amount(inr)", "Amount",
    ],
    "debit": ["debit", "withdrawal", "dr", "debit amount", "withdrawal amt"],
    "credit": ["credit", "deposit", "cr", "credit amount", "deposit amt"],
    "description": [
        "description", "narration", "particulars", "transaction details",
        "remarks", "note", "transaction_description", "Description",
    ],
    "upi_reference": [
        "upi ref no", "upi ref", "reference no", "transaction id",
        "txn id", "ref no", "cheque no", "chq no", "Reference Number",
    ],
    "merchant": [
        "merchant", "payee", "beneficiary", "merchant name",
        "counterparty", "merchant/payee", "Merchant Name",
    ],
    "balance": ["balance", "closing balance", "available balance", "Balance"],
}


def _find_column(headers: list[str], field: str) -> Optional[str]:
    """Find the actual CSV column name that maps to a standard field."""
    aliases = _COLUMN_ALIASES.get(field, [])
    headers_lower = {h.strip().lower(): h for h in headers}
    for alias in aliases:
        if alias.lower() in headers_lower:
            return headers_lower[alias.lower()]
    return None


class CSVParser(BaseParser):
    source_name = "csv_generic"

    def __init__(self, column_map: Optional[dict] = None, default_txn_type: str = "expense"):
        """
        column_map: override auto-detection, e.g. {"date": "Date", "amount": "Amt"}
        """
        self.column_map   = column_map or {}
        self.default_type = default_txn_type

    def parse(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        logger.info(f"[CSVParser] Parsing: {path.name}")

        with open(path, encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        # Detect and skip header comment lines (common in Paytm/PhonePe exports)
        lines = content.splitlines()
        skip = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                skip = i + 1
            elif stripped and not stripped.startswith(","):
                break

        cleaned = "\n".join(lines[skip:])
        reader = csv.DictReader(io.StringIO(cleaned))
        headers = reader.fieldnames or []

        # Build field → column mapping
        col = {}
        for field in ["date", "amount", "debit", "credit", "description", "upi_reference", "merchant"]:
            col[field] = self.column_map.get(field) or _find_column(list(headers), field)

        rows = []
        for raw_row in reader:
            txn = self._map_row(raw_row, col)
            if txn:
                rows.append(txn)

        logger.info(f"[CSVParser] {len(rows)} rows parsed from {path.name}")
        return self.normalize(rows)

    def _map_row(self, raw: dict, col: dict) -> Optional[dict]:
        txn: dict = {}

        # Date
        date_col = col.get("date")
        txn["date"] = raw.get(date_col, "").strip() if date_col else ""

        # Amount — prefer separate debit/credit columns
        debit_col  = col.get("debit")
        credit_col = col.get("credit")
        amount_col = col.get("amount")

        debit_val  = float(raw.get(debit_col,  0) or 0) if debit_col  else 0.0
        credit_val = float(raw.get(credit_col, 0) or 0) if credit_col else 0.0

        if debit_val or credit_val:
            if credit_val > 0:
                txn["amount"]   = credit_val
                txn["txn_type"] = "income"
            else:
                txn["amount"]   = debit_val
                txn["txn_type"] = "expense"
        elif amount_col:
            raw_amt = raw.get(amount_col, "0")
            txn["amount"] = raw_amt
            txn["txn_type"] = self.default_type
        else:
            return None

        # Other fields
        desc_col = col.get("description")
        txn["description"] = raw.get(desc_col, "").strip() if desc_col else ""

        ref_col = col.get("upi_reference")
        txn["upi_reference"] = raw.get(ref_col, "").strip() if ref_col else ""

        merch_col = col.get("merchant")
        txn["merchant"] = raw.get(merch_col, "").strip() if merch_col else ""

        txn["source"] = self.source_name
        return txn
