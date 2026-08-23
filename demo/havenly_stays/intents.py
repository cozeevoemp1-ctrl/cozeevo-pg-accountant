"""
Small deterministic regex helpers for the Havenly Stays demo bot.

Topic detection (pricing/availability/visit/room-type/month) is handled by
an LLM call in handler.py (`_interpret`) — regex was too brittle for natural
phrasing ("a single", "solo stay", "next month"). What's left here is
genuinely regex-appropriate: short, unambiguous acknowledgements
(thanks/closing/confirm/cancel) and email extraction, where deterministic
matching is both reliable and cheaper than an LLM call.
"""
from __future__ import annotations

import re
from typing import Optional

INTENT_THANKS = "THANKS"
INTENT_CLOSING = "CLOSING"
INTENT_CONFIRM = "CONFIRM"
INTENT_CANCEL = "CANCEL"
INTENT_UNKNOWN = "UNKNOWN"

_RULES = [
    (re.compile(r"^\s*(thanks|thank you|thx|ty|great|perfect|awesome|nice|cool|sounds good|got it|noted)[.!,]*\s*$", re.I), INTENT_THANKS),
    # Not fully anchored — real messages combine phrases ("no thanks, all
    # good"). Safe because this is only checked for short acknowledgement-
    # shaped messages in practice (handler.py checks this before anything
    # substantive gets a chance to reach here).
    (re.compile(r"\b(that'?s all|that'?ll be all|nothing else|no thanks?|i'?m good|all good|no,?\s*(that'?s|it'?s|its)?\s*(all|fine|good)|bye|goodbye|see ya)\b", re.I), INTENT_CLOSING),
    (re.compile(r"^\s*(yes|yep|yup|confirm|sounds good|that works|ok(ay)?)\s*$", re.I), INTENT_CONFIRM),
    (re.compile(r"^\s*(no|cancel|nevermind|never mind|stop)\s*$", re.I), INTENT_CANCEL),
]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def classify(message: str) -> str:
    msg = (message or "").strip()
    for pattern, intent in _RULES:
        if pattern.search(msg):
            return intent
    return INTENT_UNKNOWN


def extract_email(message: str) -> Optional[str]:
    m = _EMAIL_RE.search(message or "")
    return m.group(0) if m else None
