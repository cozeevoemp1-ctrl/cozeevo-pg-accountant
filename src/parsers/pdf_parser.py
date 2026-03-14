"""
PDF parser using pdfplumber.
Extracts tables from bank statement PDFs and maps to standard schema.
Falls back to text extraction if no tables are found.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from loguru import logger

from src.parsers.base_parser import BaseParser
from src.rules.merchant_rules import clean_amount, extract_upi_ref


class PDFParser(BaseParser):
    source_name = "pdf_generic"

    def __init__(self, source_override: Optional[str] = None):
        self.source_name = source_override or "pdf_generic"

    def parse(self, file_path: str | Path) -> list[dict]:
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("pdfplumber not installed. Run: pip install pdfplumber")

        path = Path(file_path)
        logger.info(f"[PDFParser] Parsing: {path.name}")
        rows = []

        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        parsed = self._parse_table(table)
                        rows.extend(parsed)
                else:
                    # Fallback: extract text line by line
                    text = page.extract_text() or ""
                    parsed = self._parse_text_lines(text)
                    rows.extend(parsed)

        logger.info(f"[PDFParser] {len(rows)} rows extracted from {path.name}")
        return self.normalize(rows)

    def _parse_table(self, table: list[list]) -> list[dict]:
        """Parse a pdfplumber table (list of rows, each row a list of strings)."""
        if not table or len(table) < 2:
            return []

        # First row = headers
        headers = [str(h or "").strip().lower() for h in table[0]]
        rows = []

        for raw_row in table[1:]:
            cells = [str(c or "").strip() for c in raw_row]
            if not any(cells):
                continue
            row_dict = dict(zip(headers, cells))
            txn = self._map_pdf_row(row_dict)
            if txn:
                rows.append(txn)
        return rows

    def _parse_text_lines(self, text: str) -> list[dict]:
        """
        Fallback: parse common Indian bank statement text patterns.
        Pattern: DD/MM/YYYY  description  amount  balance
        """
        rows = []
        date_pattern = re.compile(
            r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"      # date
            r"\s+(.+?)\s+"                           # description
            r"([\d,]+\.?\d*)\s*"                     # amount
            r"(?:Cr|Dr)?\s*"                         # optional Cr/Dr
            r"[\d,]*\.?\d*",                         # balance (ignored)
            re.I
        )
        for line in text.split("\n"):
            m = date_pattern.search(line)
            if m:
                date_str, desc, amount_str = m.group(1), m.group(2), m.group(3)
                is_credit = bool(re.search(r"\bCr\b", line, re.I))
                txn = {
                    "date": date_str,
                    "description": desc.strip(),
                    "amount": amount_str.replace(",", ""),
                    "txn_type": "income" if is_credit else "expense",
                    "upi_reference": extract_upi_ref(desc),
                    "merchant": "",
                    "source": self.source_name,
                }
                rows.append(txn)
        return rows

    def _map_pdf_row(self, row: dict) -> Optional[dict]:
        """Map a generic PDF table row dict to transaction schema."""
        # Find date
        date_val = (
            row.get("date") or row.get("txn date") or
            row.get("transaction date") or row.get("value date") or ""
        )
        if not date_val:
            return None

        # Find amount (debit/credit or single column)
        debit  = clean_amount(row.get("debit") or row.get("withdrawal") or row.get("dr") or "")
        credit = clean_amount(row.get("credit") or row.get("deposit")   or row.get("cr") or "")
        amount = clean_amount(row.get("amount") or "")

        if credit and credit > 0:
            final_amount = credit
            txn_type     = "income"
        elif debit and debit > 0:
            final_amount = debit
            txn_type     = "expense"
        elif amount:
            final_amount = abs(amount)
            txn_type     = "income" if amount > 0 else "expense"
        else:
            return None

        desc = (
            row.get("description") or row.get("narration") or
            row.get("particulars") or row.get("remarks") or ""
        )
        ref = row.get("upi ref no") or row.get("reference no") or row.get("cheque no") or ""

        return {
            "date":          date_val,
            "amount":        final_amount,
            "txn_type":      txn_type,
            "description":   str(desc).strip(),
            "upi_reference": str(ref).strip() or None,
            "merchant":      "",
            "source":        self.source_name,
        }
