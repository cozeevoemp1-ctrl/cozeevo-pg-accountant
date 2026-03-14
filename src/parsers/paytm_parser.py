"""
Paytm statement parser.
Handles Paytm CSV and PDF exports.

Paytm CSV columns (as of 2024):
  Date, Type, Details, Txn ID, Amount (INR), Balance (INR)
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from loguru import logger

from src.parsers.base_parser import BaseParser
from src.rules.merchant_rules import normalize_merchant


class PaytmParser(BaseParser):
    source_name = "upi_paytm"

    def parse(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        logger.info(f"[PaytmParser] Parsing: {path.name}")

        if path.suffix.lower() in (".xlsx", ".xls"):
            return self._parse_excel(path)
        if path.suffix.lower() == ".csv":
            return self._parse_csv(path)
        return self._parse_pdf(path)

    def _parse_excel(self, path: Path) -> list[dict]:
        import pandas as pd
        # Try each sheet, use first one that has recognisable columns
        xl = pd.ExcelFile(path)
        for sheet in xl.sheet_names:
            df = xl.parse(sheet, header=None)
            # Find the header row (contains "date" or "amount")
            header_row = None
            for i, row in df.iterrows():
                row_str = " ".join(str(v).lower() for v in row.values)
                if re.search(r"\bdate\b|\bamount\b|\btype\b|\bdetails\b", row_str):
                    header_row = i
                    break
            if header_row is None:
                continue
            df.columns = df.iloc[header_row].str.strip().str.lower()
            df = df.iloc[header_row + 1:].reset_index(drop=True)
            rows = []
            for _, raw in df.iterrows():
                txn = self._map_row(dict(raw))
                if txn:
                    rows.append(txn)
            if rows:
                logger.info(f"[PaytmParser] {len(rows)} rows from Excel sheet '{sheet}'")
                return self.normalize(rows)
        logger.warning(f"[PaytmParser] No parseable sheet found in {path.name}")
        return []

    def _parse_csv(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        # Paytm exports may have metadata lines before headers
        lines = content.splitlines()
        header_idx = 0
        for i, line in enumerate(lines):
            if re.search(r"\bdate\b|\btype\b|\bdetails\b|\bamount\b", line, re.I):
                header_idx = i
                break

        reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
        rows = []
        for raw in reader:
            txn = self._map_row(raw)
            if txn:
                rows.append(txn)

        logger.info(f"[PaytmParser] {len(rows)} rows from CSV")
        return self.normalize(rows)

    def _map_row(self, raw: dict) -> dict | None:
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}

        date_str = r.get("date") or r.get("transaction date") or ""
        txn_type = r.get("type") or ""            # "Debit" | "Credit" | "Refund"
        details  = r.get("details") or r.get("description") or ""
        txn_id   = r.get("txn id") or r.get("transaction id") or r.get("order id") or ""

        # Amount
        amt_str  = (
            r.get("amount (inr)") or r.get("amount(inr)") or
            r.get("amount") or "0"
        )
        amount   = abs(float(re.sub(r"[₹,\s]", "", amt_str) or 0))

        if amount == 0 or not date_str:
            return None

        is_debit = txn_type.lower() in ("debit", "payment", "transfer") or \
                   re.search(r"\bdebit\b|\bpayment\b", details, re.I)

        return {
            "date":          date_str,
            "amount":        amount,
            "txn_type":      "expense" if is_debit else "income",
            "source":        self.source_name,
            "description":   details,
            "upi_reference": txn_id,
            "merchant":      normalize_merchant(details),
        }

    def _parse_pdf(self, path: Path) -> list[dict]:
        from src.parsers.pdf_parser import PDFParser
        return PDFParser(source_override=self.source_name).parse(path)
