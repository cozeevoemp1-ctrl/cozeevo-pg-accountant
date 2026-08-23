"""
Lightweight regex intent classification for the Havenly Stays demo bot.
Mirrors the style of src/whatsapp/intent_detector.py — regex first, deliberately
tiny since the demo only needs to cover pricing / availability / visit booking
plus enough conversational glue (small talk, closing, confirm/cancel) to not
feel robotic.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

INTENT_GREETING = "GREETING"
INTENT_THANKS = "THANKS"
INTENT_CLOSING = "CLOSING"
INTENT_PRICING = "PRICING"
INTENT_AVAILABILITY = "AVAILABILITY"
INTENT_VISIT_REQUEST = "VISIT_REQUEST"
INTENT_CONFIRM = "CONFIRM"
INTENT_CANCEL = "CANCEL"
INTENT_UNKNOWN = "UNKNOWN"

# Order matters — more specific patterns first. Pricing/availability/visit
# checked before small-talk so "thanks, is single available" still resolves
# to AVAILABILITY rather than THANKS.
_RULES = [
    (re.compile(r"\b(visit|tour|come (and )?see|show (me )?(the|a) room|book a visit|schedule a visit)\b", re.I), INTENT_VISIT_REQUEST),
    (re.compile(r"\b(available|availability|vacan(t|cy)|free (room|bed)s?|open(ing)?s?)\b", re.I), INTENT_AVAILABILITY),
    (re.compile(r"\b(price|prices|pricing|rent|cost|how much|rate|rates|charges?)\b", re.I), INTENT_PRICING),
    (re.compile(r"^\s*(thanks|thank you|thx|ty|great|perfect|awesome|nice|cool|sounds good|got it|noted)[.!,]*\s*$", re.I), INTENT_THANKS),
    # Not fully anchored — real messages combine phrases ("no thanks, all
    # good"). Safe because price/availability/visit are checked above this,
    # so a substantive question never falls through to here.
    (re.compile(r"\b(that'?s all|that'?ll be all|nothing else|no thanks?|i'?m good|all good|no,?\s*(that'?s|it'?s|its)?\s*(all|fine|good)|bye|goodbye|see ya)\b", re.I), INTENT_CLOSING),
    (re.compile(r"\b(hi|hello|hey|good (morning|afternoon|evening))\b", re.I), INTENT_GREETING),
    (re.compile(r"^\s*(yes|yep|yup|confirm|sounds good|that works|ok(ay)?)\s*$", re.I), INTENT_CONFIRM),
    (re.compile(r"^\s*(no|cancel|nevermind|never mind|stop)\s*$", re.I), INTENT_CANCEL),
]

_ROOM_TYPE_KEYWORDS = [
    ("single", "Single"),
    ("triple", "Triple Sharing"),
    ("double", "Double Sharing"),
]

_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def classify(message: str) -> str:
    msg = (message or "").strip()
    for pattern, intent in _RULES:
        if pattern.search(msg):
            return intent
    return INTENT_UNKNOWN


def extract_room_type(message: str) -> Optional[str]:
    msg = (message or "").lower()
    for keyword, label in _ROOM_TYPE_KEYWORDS:
        if keyword in msg:
            return label
    return None


_NEXT_MONTH_RE = re.compile(r"\bnext month\b", re.I)
_THIS_MONTH_RE = re.compile(r"\b(this|current|coming)\s+month\b", re.I)
_IN_N_MONTHS_RE = re.compile(r"\bin\s+(\d+)\s+months?\b", re.I)


def extract_month(message: str) -> Optional[int]:
    """Named months first ('September'), then a small set of explicit
    relative phrases ('next month', 'this month', 'in 2 months'). Deliberately
    NOT using a general free-text date parser here — it produces false
    positives on unrelated text (e.g. hallucinating a date out of 'do you
    allow pets')."""
    msg = (message or "").lower()
    for i, name in enumerate(_MONTHS, start=1):
        if name in msg:
            return i

    today = date.today()

    if _NEXT_MONTH_RE.search(msg):
        return today.month + 1 if today.month < 12 else 1
    if _THIS_MONTH_RE.search(msg):
        return today.month
    m = _IN_N_MONTHS_RE.search(msg)
    if m:
        offset = int(m.group(1))
        return ((today.month - 1 + offset) % 12) + 1

    return None


def extract_email(message: str) -> Optional[str]:
    m = _EMAIL_RE.search(message or "")
    return m.group(0) if m else None
