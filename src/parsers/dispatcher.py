"""
File dispatcher — auto-detects source type and routes to the correct parser.
"""
from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from src.parsers.base_parser import BaseParser


def get_parser(file_path: str | Path) -> BaseParser:
    """
    Inspect filename and (for CSVs) first few lines to choose the right parser.
    Returns a configured parser instance ready to call .parse().
    """
    path = Path(file_path)
    name = path.stem.lower()
    suffix = path.suffix.lower()

    # ── Filename-based detection ──────────────────────────────────────────
    if "phonepe" in name or "phone_pe" in name:
        from src.parsers.phonepe_parser import PhonePeParser
        return PhonePeParser()

    if "paytm" in name:
        from src.parsers.paytm_parser import PaytmParser
        return PaytmParser()

    if any(bank in name for bank in ("hdfc", "sbi", "icici", "axis", "kotak")):
        from src.parsers.bank_statement_parser import BankStatementParser
        for bank in ("hdfc", "sbi", "icici", "axis", "kotak"):
            if bank in name:
                return BankStatementParser(bank=bank)

    if any(kw in name for kw in ("gpay", "googlepay", "google_pay", "upi", "bhim")):
        from src.parsers.upi_parser import UPIParser
        return UPIParser()

    # ── Content sniff for CSV ─────────────────────────────────────────────
    if suffix == ".csv":
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                sample = f.read(2000)
            if re.search(r"phonepe|phone pe", sample, re.I):
                from src.parsers.phonepe_parser import PhonePeParser
                return PhonePeParser()
            if re.search(r"paytm", sample, re.I):
                from src.parsers.paytm_parser import PaytmParser
                return PaytmParser()
            if re.search(r"hdfc bank|hdfc\s*account", sample, re.I):
                from src.parsers.bank_statement_parser import BankStatementParser
                return BankStatementParser(bank="hdfc")
            if re.search(r"state bank|sbi\s*account", sample, re.I):
                from src.parsers.bank_statement_parser import BankStatementParser
                return BankStatementParser(bank="sbi")
            if re.search(r"icici bank", sample, re.I):
                from src.parsers.bank_statement_parser import BankStatementParser
                return BankStatementParser(bank="icici")
            if re.search(r"upi ref|npci|upi transaction", sample, re.I):
                from src.parsers.upi_parser import UPIParser
                return UPIParser()
        except Exception as e:
            logger.warning(f"Content sniff failed for {path.name}: {e}")

    # ── PDF fallback ──────────────────────────────────────────────────────
    if suffix == ".pdf":
        from src.parsers.pdf_parser import PDFParser
        return PDFParser()

    # ── Generic CSV ───────────────────────────────────────────────────────
    from src.parsers.csv_parser import CSVParser
    logger.info(f"[Dispatcher] Using generic CSV parser for: {path.name}")
    return CSVParser()


def parse_file(file_path: str | Path) -> list[dict]:
    """Convenience: dispatch + parse in one call."""
    parser = get_parser(file_path)
    return parser.parse(file_path)
