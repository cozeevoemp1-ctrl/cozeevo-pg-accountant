"""
Deterministic categorization engine.
Maps merchant names / descriptions to categories via keyword rules.
AI fallback is triggered only when confidence < AI_FALLBACK_THRESHOLD.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

AI_FALLBACK_THRESHOLD = float(os.getenv("AI_FALLBACK_THRESHOLD", "0.70"))


@dataclass
class ClassificationResult:
    category: str
    confidence: float
    method: str          # "keyword" | "regex" | "ai" | "default"
    needs_ai: bool = False


# ── Rule tables ────────────────────────────────────────────────────────────
# Format: (compiled_regex_pattern, category_name, confidence)

_INCOME_RULES: list[tuple] = [
    (re.compile(r"rent|room\s?fee|accommodation|pg\s?charge", re.I), "Rent", 0.97),
    (re.compile(r"advance|deposit|security\s?deposit",         re.I), "Advance Deposit", 0.95),
    (re.compile(r"late\s?fee|penalty|fine",                    re.I), "Late Fee", 0.90),
]

_EXPENSE_RULES: list[tuple] = [
    # Utilities
    (re.compile(r"electric|bescom|tsspdcl|msedcl|torrent|wbsedcl|tneb|electricity", re.I), "Electricity", 0.97),
    (re.compile(r"\bwater\b|jal\s?board|bwssb|hmws",           re.I), "Water", 0.95),
    (re.compile(r"internet|broadband|airtel|jio|bsnl|act\s?fibernet|hathway|you\s?broadband", re.I), "Internet", 0.96),
    (re.compile(r"gas|lpg|indane|hp\s?gas|bharatgas",          re.I), "Groceries", 0.88),

    # Groceries / Food
    (re.compile(r"bigbasket|grofers|blinkit|zepto|swiggy\s?instamart|jio\s?mart|reliance\s?smart|d\s?mart", re.I), "Groceries", 0.95),
    (re.compile(r"swiggy|zomato|foodpanda|ubereats|dunzo\s?food", re.I), "Food & Beverages", 0.96),
    (re.compile(r"hotel|restaurant|cafe|dhaba|biryani|mess|tiffin|canteen", re.I), "Food & Beverages", 0.85),

    # Transport
    (re.compile(r"ola|uber|rapido|redbus|irctc|railways|metro|namma\s?metro|bmtc|apsrtc", re.I), "Transport", 0.94),
    (re.compile(r"petrol|diesel|fuel|hp\s?petrol|iocl|bpcl",   re.I), "Transport", 0.92),

    # Maintenance
    (re.compile(r"plumb|electric\s?repair|carpenter|mason|paint|whitewash|hardware|tools", re.I), "Maintenance & Repair", 0.90),
    (re.compile(r"cleaning|housekeeping|maid|broom|phenyl|deterg|sanitiz", re.I), "Cleaning Supplies", 0.88),

    # Salary
    (re.compile(r"\bsalary\b|\bwages?\b|\bpayroll\b|\bstipend\b",re.I), "Salary", 0.97),

    # Taxes
    (re.compile(r"\bgst\b|tax|tds|challan|govt\s?fee",          re.I), "Taxes & Fees", 0.88),

    # Shopping / Misc
    (re.compile(r"amazon|flipkart|myntra|nykaa|ajio|snapdeal",  re.I), "Miscellaneous", 0.80),
    (re.compile(r"medical|pharmacy|chemist|apollo|medplus|1mg", re.I), "Miscellaneous", 0.82),
]

# Simple keyword → category exact matches (fast path)
_KEYWORD_MAP: dict[str, str] = {
    "electricity": "Electricity",
    "water bill": "Water",
    "wifi":        "Internet",
    "salary":      "Salary",
    "rent":        "Rent",
    "advance":     "Advance Deposit",
    "deposit":     "Advance Deposit",
    "swiggy":      "Food & Beverages",
    "zomato":      "Food & Beverages",
    "amazon":      "Miscellaneous",
    "flipkart":    "Miscellaneous",
    "petrol":      "Transport",
    "diesel":      "Transport",
    "uber":        "Transport",
    "ola":         "Transport",
}


def classify(description: str, merchant: str = "", txn_type: str = "expense") -> ClassificationResult:
    """
    Classify a transaction deterministically.
    Returns ClassificationResult with needs_ai=True if confidence < threshold.
    """
    text = f"{merchant} {description}".strip().lower()

    # 1. Fast keyword map
    for kw, cat in _KEYWORD_MAP.items():
        if kw in text:
            return ClassificationResult(cat, 0.93, "keyword")

    # 2. Regex rules — income
    if txn_type == "income":
        for pattern, cat, conf in _INCOME_RULES:
            if pattern.search(text):
                result = ClassificationResult(cat, conf, "regex")
                result.needs_ai = conf < AI_FALLBACK_THRESHOLD
                return result

    # 3. Regex rules — expense (also checked for income fallthrough)
    for pattern, cat, conf in _EXPENSE_RULES:
        if pattern.search(text):
            result = ClassificationResult(cat, conf, "regex")
            result.needs_ai = conf < AI_FALLBACK_THRESHOLD
            return result

    # 4. Unknown → flag for AI
    default_cat = "Other Income" if txn_type == "income" else "Miscellaneous"
    return ClassificationResult(default_cat, 0.40, "default", needs_ai=True)


def classify_batch(transactions: list[dict]) -> list[dict]:
    """
    Classify a list of transaction dicts in-place.
    Adds: category, confidence, ai_classified, needs_ai_review keys.
    """
    for txn in transactions:
        result = classify(
            description=txn.get("description", ""),
            merchant=txn.get("merchant", ""),
            txn_type=txn.get("txn_type", "expense"),
        )
        txn["category"]         = result.category
        txn["confidence"]       = result.confidence
        txn["ai_classified"]    = False
        txn["needs_ai_review"]  = result.needs_ai
    return transactions
