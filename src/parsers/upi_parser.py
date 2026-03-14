"""
Generic UPI CSV/PDF parser (NPCI format).
Also handles Google Pay exports.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from loguru import logger

from src.parsers.base_parser import BaseParser
from src.rules.merchant_rules import normalize_merchant, infer_source_from_upi_id


class UPIParser(BaseParser):
    """Handles generic UPI / NPCI / Google Pay statement exports."""
    source_name = "upi_other"

    def parse(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        logger.info(f"[UPIParser] Parsing: {path.name}")

        if path.suffix.lower() == ".pdf":
            from src.parsers.pdf_parser import PDFParser
            return PDFParser(source_override=self.source_name).parse(path)

        with open(path, encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        lines = content.splitlines()
        # Skip comment/metadata lines
        header_idx = 0
        for i, line in enumerate(lines):
            if re.search(r"date|amount|description|payee|reference", line, re.I):
                header_idx = i
                break

        reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
        rows = []
        for raw in reader:
            txn = self._map_row(raw)
            if txn:
                rows.append(txn)

        logger.info(f"[UPIParser] {len(rows)} rows parsed")
        return self.normalize(rows)

    def _map_row(self, raw: dict) -> dict | None:
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}

        date_str  = r.get("date") or r.get("transaction date") or ""
        desc      = r.get("description") or r.get("narration") or r.get("note") or ""
        ref       = r.get("upi ref no") or r.get("transaction id") or r.get("reference") or ""
        payee     = r.get("payee") or r.get("merchant") or r.get("paid to") or ""
        payer_upi = r.get("payer upi") or r.get("upi id") or ""
        amt_str   = r.get("amount") or r.get("transaction amount") or "0"

        amount = abs(float(re.sub(r"[₹,\s]", "", amt_str) or 0))
        if amount == 0 or not date_str:
            return None

        # Google Pay specific: "Money sent" / "Money received"
        is_credit = bool(
            re.search(r"received|credit|money\s+received", desc, re.I) or
            re.search(r"received|credit", r.get("type", ""), re.I)
        )

        source = infer_source_from_upi_id(payer_upi) or self.source_name

        return {
            "date":          date_str,
            "amount":        amount,
            "txn_type":      "income" if is_credit else "expense",
            "source":        source,
            "description":   desc,
            "upi_reference": ref,
            "merchant":      normalize_merchant(payee or desc),
        }
