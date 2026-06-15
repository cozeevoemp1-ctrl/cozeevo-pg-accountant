"""Single source of truth for day-stay (daily) dues.

Why this module exists: the day-stay dues formula was copy-pasted across
4 endpoints (tenants list, tenant dues, home KPI aggregate, home KPI dues
list). They drifted — some added the booking advance twice — so the same
tenant showed different dues on different screens. Every caller MUST use
daily_dues() so the math can never diverge again.

The rule: ONLY history payments are real. The booking advance is recorded
as a Payment row (for_type=booking), so the summed non-void payment total
already includes it. NEVER add tenancy.booking_amount on top — that
double-counts the advance and understates dues.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Tuple


def booking_credit(booking_paid_rows, booking_amount_field) -> float:
    """Advance credited toward what a tenant owes (rent/deposit).

    Only history is real: prefer the booking (advance) Payment rows. Fall back
    to the legacy tenancy.booking_amount field ONLY for Excel-imported tenants
    that have no Payment row. Using the field when a Payment row exists is what
    caused deposits to wrongly show as due (field=0 but a ₹5000 advance row
    existed). Mirror of get_tenant_dues' logic so every endpoint agrees.
    """
    rows = float(booking_paid_rows or 0)
    return rows if rows > 0 else float(booking_amount_field or 0)


def daily_owed(checkin: Optional[date], checkout: Optional[date], daily_rate) -> float:
    """Total stay cost = booked nights × per-day rate."""
    nights = (checkout - checkin).days if checkin and checkout else 0
    return nights * float(daily_rate or 0)


def daily_dues(
    checkin: Optional[date],
    checkout: Optional[date],
    daily_rate,
    total_paid_history,
) -> Tuple[float, float, float]:
    """Return (owed, dues, credit) for a day-stay tenancy.

    total_paid_history MUST be the sum of NON-VOID Payment rows for the
    tenancy (which already includes the booking advance). Do NOT pass or add
    tenancy.booking_amount — see module docstring.
    """
    owed = daily_owed(checkin, checkout, daily_rate)
    paid = float(total_paid_history or 0)
    return owed, max(0.0, owed - paid), max(0.0, paid - owed)
