"""
src/utils/money.py
===================
Indian-style INR formatting for all user-visible amounts (WhatsApp + sheets).
"""
from __future__ import annotations


def inr(n) -> str:
    """Format an amount in Indian comma style: 12,03,150 (no abbreviation)."""
    try:
        n = int(float(n))
    except (TypeError, ValueError):
        return "0"
    neg = n < 0
    s = str(abs(n))
    if len(s) <= 3:
        out = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        groups: list[str] = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        out = ",".join(groups) + "," + last3
    return ("-" if neg else "") + out
