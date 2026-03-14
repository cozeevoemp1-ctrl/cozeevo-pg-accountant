"""
PhonePe statement parser.
Handles both CSV and PDF exports from PhonePe app.

PhonePe CSV columns (as of 2024):
  Date, Transaction ID, Transaction Details, Paid To/Received From,
  Amount, Status, Comments

PhonePe PDF: table inside PDF with similar columns.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from loguru import logger

from src.parsers.base_parser import BaseParser
from src.rules.merchant_rules import normalize_merchant, clean_amount


class PhonePeParser(BaseParser):
    source_name = "upi_phonepe"

    def parse(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        suffix = path.suffix.lower()
        logger.info(f"[PhonePeParser] Parsing: {path.name}")

        if suffix == ".csv":
            return self._parse_csv(path)
        elif suffix == ".pdf":
            return self._parse_pdf(path)
        else:
            raise ValueError(f"Unsupported file type for PhonePe: {suffix}")

    # ── CSV ─────────────────────────────────────────────────────────────────

    def _parse_csv(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        # PhonePe prepends non-data lines (account info, date range)
        lines = content.splitlines()
        header_idx = 0
        for i, line in enumerate(lines):
            if re.search(r"date|transaction", line, re.I):
                header_idx = i
                break

        reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
        rows = []
        for raw in reader:
            txn = self._map_csv_row(raw)
            if txn:
                rows.append(txn)

        logger.info(f"[PhonePeParser] {len(rows)} rows from CSV")
        return self.normalize(rows)

    def _map_csv_row(self, raw: dict) -> dict | None:
        # Normalize header keys
        r = {k.strip().lower(): v.strip() for k, v in raw.items() if k}

        date_str = r.get("date") or r.get("transaction date") or ""
        txn_id   = r.get("transaction id") or r.get("upi transaction id") or ""
        details  = r.get("transaction details") or r.get("details") or ""
        party    = r.get("paid to/received from") or r.get("payee/payer") or ""
        amt_str  = r.get("amount") or r.get("transaction amount") or "0"
        status   = r.get("status") or "completed"
        comments = r.get("comments") or ""

        if status.lower() not in ("completed", "success", "successful", ""):
            return None   # skip failed/pending transactions

        # Determine direction from amount sign or separate columns
        # PhonePe uses "-" prefix for debits
        amount_raw = re.sub(r"[₹,\s]", "", amt_str)
        is_debit   = amount_raw.startswith("-") or re.search(r"\bdebit\b", details, re.I)
        amount     = abs(float(amount_raw.replace("-", "") or 0))

        if amount == 0:
            return None

        return {
            "date":          date_str,
            "amount":        amount,
            "txn_type":      "expense" if is_debit else "income",
            "source":        self.source_name,
            "description":   f"{details} {comments}".strip(),
            "upi_reference": txn_id,
            "merchant":      normalize_merchant(party or details),
        }

    # ── PDF ─────────────────────────────────────────────────────────────────

    def _parse_pdf(self, path: Path) -> list[dict]:
        from src.parsers.pdf_parser import PDFParser
        pdf_parser = PDFParser(source_override=self.source_name)
        return pdf_parser.parse(path)
