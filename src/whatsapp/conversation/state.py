"""
src/whatsapp/conversation/state.py
===================================
ConversationState enum + UserInput parser.

A pending action has BOTH an `intent` (what business flow) and a `state`
(what kind of input we're waiting for). The state determines how the
NEXT user message gets parsed; the intent determines which handler
receives it.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


class ConversationState(str, enum.Enum):
    """What the bot is waiting for from the user."""
    IDLE                  = "idle"                   # no pending, greet
    AWAITING_CHOICE       = "awaiting_choice"        # user must pick 1/2/3/...
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # user must reply yes/no
    AWAITING_FIELD        = "awaiting_field"         # multi-step form: next field
    AWAITING_DATE         = "awaiting_date"          # e.g. new checkout date
    AWAITING_AMOUNT       = "awaiting_amount"        # e.g. deposit change amount
    AWAITING_TEXT         = "awaiting_text"          # free text note
    AWAITING_IMAGE        = "awaiting_image"         # user must upload a photo

    @classmethod
    def from_str(cls, value: Optional[str]) -> "ConversationState":
        if not value:
            return cls.IDLE
        try:
            return cls(value)
        except ValueError:
            return cls.IDLE


# ── Parsed input ───────────────────────────────────────────────────────────

_CANCEL_WORDS = frozenset({"cancel", "stop", "abort", "quit", "nevermind", "never mind"})
_YES_WORDS    = frozenset({"yes", "y", "yeah", "yep", "ok", "okay", "confirm", "sure", "done", "approve", "approved"})
_NO_WORDS     = frozenset({"no", "n", "nope", "cancel", "reject", "denied"})
_SKIP_WORDS   = frozenset({"skip", "pass", "nothing"})


@dataclass
class UserInput:
    """A single user message, parsed into all possible interpretations.

    Having all interpretations pre-parsed means a handler doesn't need
    to re-parse. It just picks the field(s) relevant to its state.
    """
    raw: str
    has_media: bool = False
    media_type: Optional[str] = None
    media_id: Optional[str] = None

    # Parsed flags (populated by parse())
    parsed_number: Optional[int] = None   # "1", "2.", "1)" → 1, 2, 1
    parsed_yes: bool = False
    parsed_no: bool = False
    parsed_cancel: bool = False
    parsed_skip: bool = False
    parsed_date: Optional[date] = None
    parsed_amount: Optional[float] = None

    def is_numeric(self) -> bool:
        return self.parsed_number is not None

    def is_yesno(self) -> bool:
        return self.parsed_yes or self.parsed_no

    def is_empty(self) -> bool:
        return not self.raw.strip() and not self.has_media


def parse(message: str, *, media_id: Optional[str] = None,
          media_type: Optional[str] = None) -> UserInput:
    """Parse a raw user message into a structured UserInput.

    Do not add business-specific parsing here (e.g. payment modes,
    tenant names). That belongs in the individual handlers.
    """
    raw = (message or "").strip()
    inp = UserInput(raw=raw, has_media=bool(media_id),
                    media_type=media_type, media_id=media_id)
    low = raw.lower()

    # Strip trailing punctuation for matching
    stripped = raw.rstrip(".!?,;:")
    stripped_low = stripped.lower()

    # Numeric choice: "1", "1.", "1)", "option 1"
    m = re.fullmatch(r"(?:option\s*)?(\d{1,3})[.)]?", stripped_low)
    if m:
        inp.parsed_number = int(m.group(1))

    # Yes / No (exact word match, not substring — avoids "yesterday" = yes)
    if stripped_low in _YES_WORDS:
        inp.parsed_yes = True
    if stripped_low in _NO_WORDS:
        inp.parsed_no = True
    # "no" wins over "yes" if both somehow match — safer default
    if inp.parsed_no:
        inp.parsed_yes = False

    if stripped_low in _CANCEL_WORDS:
        inp.parsed_cancel = True
    if stripped_low in _SKIP_WORDS:
        inp.parsed_skip = True

    # Date (DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, "15 April", "15th April 2026")
    inp.parsed_date = _parse_date(raw)

    # Amount (plain number with optional comma, possibly with ₹ or Rs. prefix)
    m = re.search(r"(?:rs\.?|₹)?\s*(\d[\d,]*(?:\.\d+)?)", low)
    if m:
        try:
            inp.parsed_amount = float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    return inp


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}


def _parse_date(raw: str) -> Optional[date]:
    """Best-effort date extraction. Handles common formats + natural language."""
    if not raw:
        return None
    s = raw.strip()

    # Numeric formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue

    # "15 April" or "15th April 2026" or "April 15"
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)(?:\s+(\d{2,4}))?", s.lower())
    if m and m.group(2) in _MONTHS:
        day = int(m.group(1))
        month = _MONTHS[m.group(2)]
        year = int(m.group(3)) if m.group(3) else date.today().year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    m = re.search(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{2,4}))?", s.lower())
    if m and m.group(1) in _MONTHS:
        day = int(m.group(2))
        month = _MONTHS[m.group(1)]
        year = int(m.group(3)) if m.group(3) else date.today().year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None
