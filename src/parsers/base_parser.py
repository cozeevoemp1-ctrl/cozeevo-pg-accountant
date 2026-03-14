"""
Abstract base parser — all concrete parsers extend this.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from src.rules.merchant_rules import normalize_merchant, extract_upi_ref, clean_amount
from src.rules.deduplication import enrich_with_hash


# Standard transaction schema keys
TRANSACTION_KEYS = [
    "date", "amount", "txn_type", "source", "description",
    "upi_reference", "merchant", "unique_hash", "raw_data",
    "category", "confidence", "ai_classified", "needs_ai_review",
]


class BaseParser(ABC):
    """
    All parsers must return a list of dicts matching the standard schema.
    """
    source_name: str = "unknown"   # Override in subclasses

    @abstractmethod
    def parse(self, file_path: str | Path) -> list[dict]:
        """
        Parse the input file and return a list of normalized transaction dicts.
        Each dict must contain at minimum: date, amount, txn_type, source, unique_hash.
        """

    def normalize(self, rows: list[dict]) -> list[dict]:
        """
        Apply common normalization to raw rows:
        - merchant name cleaning
        - UPI reference extraction
        - hash computation
        - raw_data preservation
        """
        result = []
        for row in rows:
            try:
                norm = self._normalize_row(row)
                if norm:
                    result.append(norm)
            except Exception as e:
                logger.warning(f"[{self.source_name}] Skipping row due to error: {e} | row={row}")
        return result

    def _normalize_row(self, row: dict) -> Optional[dict]:
        # Preserve original data
        row["raw_data"] = json.dumps(row, default=str)

        # Merchant
        if "merchant" in row:
            row["merchant"] = normalize_merchant(row.get("merchant", ""))

        # UPI reference extraction from description if missing
        if not row.get("upi_reference"):
            row["upi_reference"] = extract_upi_ref(row.get("description", ""))

        # Amount clean-up
        if isinstance(row.get("amount"), str):
            row["amount"] = clean_amount(row["amount"]) or 0.0

        # Ensure positive amounts (sign handled by txn_type)
        row["amount"] = abs(float(row.get("amount", 0)))
        if row["amount"] == 0:
            return None   # skip zero-amount rows

        # Source fallback
        row.setdefault("source", self.source_name)

        # Date normalization
        row["date"] = self._parse_date(row.get("date"))
        if not row["date"]:
            return None

        # Defaults
        row.setdefault("txn_type", "expense")
        row.setdefault("description", "")
        row.setdefault("upi_reference", None)
        row.setdefault("merchant", "")
        row.setdefault("category", None)
        row.setdefault("confidence", 1.0)
        row.setdefault("ai_classified", False)
        row.setdefault("needs_ai_review", False)

        # Hash
        enrich_with_hash(row)
        return row

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            formats = [
                "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
                "%d %b %Y", "%d %B %Y", "%d/%m/%y",
                "%b %d, %Y", "%B %d, %Y",
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(value.strip(), fmt).date()
                except ValueError:
                    continue
            # Fallback: dateparser
            try:
                import dateparser
                parsed = dateparser.parse(value, settings={"RETURN_AS_TIMEZONE_AWARE": False})
                return parsed.date() if parsed else None
            except Exception:
                return None
        return None
