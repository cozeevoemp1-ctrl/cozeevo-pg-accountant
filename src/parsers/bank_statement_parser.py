"""
Bank statement parser — supports HDFC, SBI, ICICI, Axis CSV and PDF formats.
Auto-detects bank from filename / column headers.
"""
from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from src.parsers.base_parser import BaseParser
from src.parsers.csv_parser import CSVParser
from src.parsers.pdf_parser import PDFParser


# Column maps keyed by bank name
_BANK_COLUMN_MAPS = {
    "hdfc": {
        "date":          "Date",
        "description":   "Narration",
        "upi_reference": "Chq./Ref.No.",
        "debit":         "Withdrawal Amt.",
        "credit":        "Deposit Amt.",
    },
    "sbi": {
        "date":          "Txn Date",
        "description":   "Description",
        "upi_reference": "Ref No./Cheque No.",
        "debit":         "Debit",
        "credit":        "Credit",
    },
    "icici": {
        "date":          "Transaction Date",
        "description":   "Transaction Remarks",
        "upi_reference": "Reference Number",
        "debit":         "Withdrawal Amount (INR )",
        "credit":        "Deposit Amount (INR )",
    },
    "axis": {
        "date":          "Tran Date",
        "description":   "PARTICULARS",
        "upi_reference": "CHQNO",
        "debit":         "DR",
        "credit":        "CR",
    },
    "kotak": {
        "date":          "Transaction Date",
        "description":   "Description",
        "upi_reference": "Reference Number",
        "debit":         "Debit Amount",
        "credit":        "Credit Amount",
    },
}

_SOURCE_MAP = {
    "hdfc":  "bank_hdfc",
    "sbi":   "bank_sbi",
    "icici": "bank_icici",
    "axis":  "bank_other",
    "kotak": "bank_other",
}


def _detect_bank(path: Path) -> str:
    """Guess bank from filename."""
    name = path.stem.lower()
    for bank in _BANK_COLUMN_MAPS:
        if bank in name:
            return bank
    return "generic"


class BankStatementParser(BaseParser):
    source_name = "bank_other"

    def __init__(self, bank: str = "auto"):
        """
        bank: "hdfc" | "sbi" | "icici" | "axis" | "kotak" | "auto"
        """
        self.bank = bank

    def parse(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        bank = self.bank if self.bank != "auto" else _detect_bank(path)
        self.source_name = _SOURCE_MAP.get(bank, "bank_other")

        logger.info(f"[BankStatementParser] Bank={bank}, file={path.name}")

        if path.suffix.lower() == ".pdf":
            parser = PDFParser(source_override=self.source_name)
            return parser.parse(path)

        col_map = _BANK_COLUMN_MAPS.get(bank, {})
        csv_parser = CSVParser(column_map=col_map, default_txn_type="expense")
        csv_parser.source_name = self.source_name
        return csv_parser.parse(path)
