"""
Rules-based WhatsApp intent detector.
Handles ~97% of messages without any AI call.
"""
from __future__ import annotations

import re
from typing import Optional


# ── Pattern rules ──────────────────────────────────────────────────────────

_INTENTS = [
    # summary
    ("summary", re.compile(
        r"\b(summary|report|total|balance|overview|statement|how much|kitna|"
        r"income|expense|profit|net|monthly|weekly|today|yesterday)\b",
        re.I
    ), 0.88),

    # rent_status
    ("rent_status", re.compile(
        r"\b(rent|tenant|room|pg charge|who paid|pending|due|collected|baki)\b",
        re.I
    ), 0.90),

    # export
    ("export", re.compile(
        r"\b(export|download|csv|excel|spreadsheet|file|send|share)\b",
        re.I
    ), 0.92),

    # expense_query
    ("expense_query", re.compile(
        r"\b(expense|spend|spent|payment|paid|electricity|water|grocery|food|"
        r"salary|maintenance|internet|bill|kharcha)\b",
        re.I
    ), 0.85),

    # add_transaction
    ("add_transaction", re.compile(
        r"\b(add|record|enter|log|received|paid|cash|collected|jama karo|add karo)\b",
        re.I
    ), 0.80),

    # help
    ("help", re.compile(
        r"\b(help|commands|what can|how to|guide|instructions|start)\b",
        re.I
    ), 0.95),
]

_PERIOD_MAP = {
    "today":      ("today", 0.95),
    "yesterday":  ("yesterday", 0.95),
    "this week":  ("week", 0.90),
    "last week":  ("last_week", 0.90),
    "this month": ("monthly", 0.90),
    "last month": ("last_month", 0.90),
    "january": ("january", 0.92), "jan": ("january", 0.90),
    "february": ("february", 0.92), "feb": ("february", 0.90),
    "march":  ("march", 0.92),  "mar": ("march", 0.90),
    "april":  ("april", 0.92),  "apr": ("april", 0.90),
    "may":    ("may", 0.92),
    "june":   ("june", 0.92),   "jun": ("june", 0.90),
    "july":   ("july", 0.92),   "jul": ("july", 0.90),
    "august": ("august", 0.92), "aug": ("august", 0.90),
    "september": ("september", 0.92), "sep": ("september", 0.90),
    "october": ("october", 0.92), "oct": ("october", 0.90),
    "november": ("november", 0.92), "nov": ("november", 0.90),
    "december": ("december", 0.92), "dec": ("december", 0.90),
}

_FORMAT_MAP = {
    re.compile(r"\b(csv|comma.separated)\b", re.I):   "csv",
    re.compile(r"\b(excel|xlsx|spreadsheet)\b", re.I): "excel",
    re.compile(r"\b(dashboard|chart|graph|visual)\b", re.I): "dashboard",
    re.compile(r"\b(whatsapp|text|message|chat)\b", re.I):   "text",
}


def detect_intent_rules(message: str) -> dict:
    """
    Deterministic intent detection.
    Returns dict matching the AI intent schema.
    """
    msg = message.strip()

    # Match intent
    best_intent = "unknown"
    best_conf   = 0.0
    for intent, pattern, conf in _INTENTS:
        if pattern.search(msg):
            if conf > best_conf:
                best_intent = intent
                best_conf   = conf

    # Match period
    period = None
    msg_lower = msg.lower()
    for kw, (mapped, _) in _PERIOD_MAP.items():
        if kw in msg_lower:
            period = mapped
            break

    # Match format
    fmt = "text"
    for pattern, mapped_fmt in _FORMAT_MAP.items():
        if pattern.search(msg):
            fmt = mapped_fmt
            break

    return {
        "intent":     best_intent,
        "period":     period,
        "format":     fmt,
        "category":   None,
        "entities":   [],
        "confidence": best_conf,
    }
