"""
src/utils/name_match.py
Single source of truth for "does the name on the ID match the name typed in the form".

Rule (mirrored in static/onboarding.html `namesMatch()` — keep both identical):
  - lowercase, keep letters only, split on whitespace
  - drop 1-letter tokens (initials like "K", "S")
  - match if every token of the shorter name appears in the longer name

Examples:
  "Raghav"            vs "Raghav Mittal"      -> True
  "Raghav Mittal"     vs "MITTAL RAGHAV"      -> True
  "K Raghav"          vs "Raghav Kumar"       -> True   (initial ignored)
  "Loki"              vs "Lokesh Kumar"       -> False
  "Raghav Mittal"     vs "Rakesh Mittal"      -> False
"""
from __future__ import annotations

import re

_NON_LETTER = re.compile(r"[^a-z\s]")


def _tokens(name: str) -> list[str]:
    cleaned = _NON_LETTER.sub(" ", (name or "").lower())
    return [t for t in cleaned.split() if len(t) > 1]


def names_match(a: str, b: str) -> bool:
    """True when the shorter name's tokens are all present in the longer name."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    long_set = set(long_)
    return all(t in long_set for t in short)
