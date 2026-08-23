"""
Lightweight regex intent classification for the Havenly Stays demo bot.
Mirrors the style of src/whatsapp/intent_detector.py — regex first, deliberately
tiny since the demo only needs to cover pricing / availability / visit booking.
"""
from __future__ import annotations

import re
from typing import Optional

INTENT_GREETING = "GREETING"
INTENT_PRICING = "PRICING"
INTENT_AVAILABILITY = "AVAILABILITY"
INTENT_VISIT_REQUEST = "VISIT_REQUEST"
INTENT_CONFIRM = "CONFIRM"
INTENT_CANCEL = "CANCEL"
INTENT_UNKNOWN = "UNKNOWN"

# Order matters — more specific patterns first.
_RULES = [
    (re.compile(r"\b(visit|tour|come (and )?see|show (me )?(the|a) room|book a visit|schedule a visit)\b", re.I), INTENT_VISIT_REQUEST),
    (re.compile(r"\b(available|availability|vacan(t|cy)|free (room|bed)s?|open(ing)?s?)\b", re.I), INTENT_AVAILABILITY),
    (re.compile(r"\b(price|prices|pricing|rent|cost|how much|rate|rates|charges?)\b", re.I), INTENT_PRICING),
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


def extract_month(message: str) -> Optional[int]:
    msg = (message or "").lower()
    for i, name in enumerate(_MONTHS, start=1):
        if name in msg:
            return i
    return None


def extract_email(message: str) -> Optional[str]:
    m = _EMAIL_RE.search(message or "")
    return m.group(0) if m else None
