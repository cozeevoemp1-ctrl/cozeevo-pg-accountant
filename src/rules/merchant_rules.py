"""
Merchant name normalizer for Indian UPI / payment apps.
Handles messy merchant strings from PhonePe, Paytm, NPCI exports.
"""
from __future__ import annotations

import re
from typing import Optional


# Normalization map: pattern → canonical name
_NORMALIZATIONS: list[tuple[re.Pattern, str]] = [
    # PhonePe patterns
    (re.compile(r"phonepe|phone\s?pe",     re.I), "PhonePe"),
    # Paytm patterns
    (re.compile(r"paytm",                  re.I), "Paytm"),
    # Google Pay
    (re.compile(r"googlepay|google\s?pay|tez", re.I), "Google Pay"),
    # BHIM
    (re.compile(r"\bbhim\b",               re.I), "BHIM"),
    # Amazon
    (re.compile(r"amazon(?!.*fresh)",      re.I), "Amazon"),
    (re.compile(r"amazon\s?fresh",         re.I), "Amazon Fresh"),
    # Swiggy
    (re.compile(r"swiggy\s?instamart",     re.I), "Swiggy Instamart"),
    (re.compile(r"\bswiggy\b",             re.I), "Swiggy"),
    # Zomato
    (re.compile(r"\bzomato\b",             re.I), "Zomato"),
    # BigBasket
    (re.compile(r"bigbasket|big\s?basket", re.I), "BigBasket"),
    # Blinkit
    (re.compile(r"blinkit|grofers",        re.I), "Blinkit"),
    # Electricity
    (re.compile(r"bescom",                 re.I), "BESCOM"),
    (re.compile(r"tsspdcl",                re.I), "TSSPDCL"),
    (re.compile(r"msedcl",                 re.I), "MSEDCL"),
    (re.compile(r"torrent\s?power",        re.I), "Torrent Power"),
    (re.compile(r"\btneb\b",               re.I), "TNEB"),
    # Internet
    (re.compile(r"airtel\s?broadband|airtel\s?fiber", re.I), "Airtel Broadband"),
    (re.compile(r"\bairtel\b",             re.I), "Airtel"),
    (re.compile(r"\bjio\b",                re.I), "Jio"),
    (re.compile(r"act\s?fibernet",         re.I), "ACT Fibernet"),
    # Transport
    (re.compile(r"\bola\b(?!\s?cabs)",     re.I), "Ola"),
    (re.compile(r"\bola\s?cabs\b",         re.I), "Ola Cabs"),
    (re.compile(r"\buber\b",               re.I), "Uber"),
    (re.compile(r"\brapido\b",             re.I), "Rapido"),
    # IRCTC / Railways
    (re.compile(r"irctc|railways|indian\s?rail", re.I), "IRCTC"),
]

# UPI ID suffix → payment app
_UPI_SUFFIX_MAP = {
    "@ybl":      "PhonePe",
    "@ibl":      "PhonePe",
    "@axl":      "PhonePe",
    "@okaxis":   "Google Pay",
    "@okicici":  "Google Pay",
    "@oksbi":    "Google Pay",
    "@okhdfcbank": "Google Pay",
    "@paytm":    "Paytm",
    "@apl":      "Amazon Pay",
    "@rajput":   "BHIM",
    "@upi":      "BHIM",
}


def normalize_merchant(raw: str) -> str:
    """Return a canonical merchant name from a raw UPI / bank description."""
    if not raw:
        return ""
    raw = raw.strip()

    for pattern, canonical in _NORMALIZATIONS:
        if pattern.search(raw):
            return canonical

    # Clean up common noise
    cleaned = re.sub(r"[_\-]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.title()


def infer_source_from_upi_id(upi_id: str) -> Optional[str]:
    """
    Infer the payment app from UPI ID suffix.
    Returns a TransactionSource-compatible string.
    """
    if not upi_id:
        return None
    upi_lower = upi_id.lower()
    for suffix, app in _UPI_SUFFIX_MAP.items():
        if upi_lower.endswith(suffix):
            return {
                "PhonePe":    "upi_phonepe",
                "Google Pay": "upi_gpay",
                "Paytm":      "upi_paytm",
                "Amazon Pay": "upi_other",
                "BHIM":       "upi_bhim",
            }.get(app, "upi_other")
    return "upi_other"


def extract_upi_ref(text: str) -> Optional[str]:
    """
    Extract UPI transaction reference (12-digit number starting with patterns).
    Works for NPCI / PhonePe / Paytm reference formats.
    """
    # Standard 12-digit UPI reference
    m = re.search(r"\b(\d{12})\b", text)
    if m:
        return m.group(1)
    # Paytm ORDER ID format
    m = re.search(r"(?:ORDER\s*ID|REF)\s*[:\-]?\s*([A-Z0-9]{10,20})", text, re.I)
    if m:
        return m.group(1)
    return None


def clean_amount(raw: str) -> Optional[float]:
    """
    Parse amount strings like '₹1,234.56', '1234.56 Cr', '-500.00' etc.
    Returns float or None if unparsable.
    """
    if not raw:
        return None
    text = str(raw).strip()
    # Detect credit/debit markers
    is_credit = bool(re.search(r"\b(cr|credit|deposit)\b", text, re.I))
    is_debit  = bool(re.search(r"\b(dr|debit|withdraw)\b", text, re.I))

    # Remove currency symbols and commas
    numeric = re.sub(r"[₹$,\s]", "", text)
    numeric = re.sub(r"[a-zA-Z]+", "", numeric).strip()

    try:
        value = abs(float(numeric))
        if is_debit:
            return -value
        return value
    except ValueError:
        return None
