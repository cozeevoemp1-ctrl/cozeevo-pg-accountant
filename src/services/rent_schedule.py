"""Rent schedule business-rule helpers.

Single source of truth for the first-month Rent Due formula. Every call
site that creates or refreshes a RentSchedule row must go through
`first_month_rent_due()` so DB, Sheet, and Excel stay in sync.

Rule (memory/feedback_billing_proration.md): first month is always pro
rata by check-in date. Rent Due for the check-in month bundles the
security deposit (deposit-included Sheet convention).
    Rent Due (first month) = floor(agreed_rent * days_billed / days_in_month)
                             + security_deposit
    Rent Due (later)       = agreed_rent
"""
from __future__ import annotations

import calendar
import math
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.database.models import Tenancy


def prorated_first_month_rent(agreed_rent, checkin: date) -> Decimal:
    """Prorated rent for the check-in month (no deposit bundled)."""
    rent = Decimal(str(agreed_rent or 0))
    if not checkin or rent == 0:
        return rent
    days_in_month = calendar.monthrange(checkin.year, checkin.month)[1]
    days_billed = days_in_month - checkin.day + 1
    return Decimal(str(math.floor(float(rent) * days_billed / days_in_month)))


def first_month_rent_due(tenancy: "Tenancy", period_month: date) -> Decimal:
    """Return the Rent Due for a given period.

    First month: prorated_rent + deposit − booking_amount.
    Booking advance is already received before check-in and reduces
    what the tenant still owes — so it is netted out of rent_due at
    save time rather than deducted again at display time.
    All other months: agreed_rent.
    """
    rent = Decimal(str(tenancy.agreed_rent or 0))
    checkin = getattr(tenancy, "checkin_date", None)
    if checkin is None:
        return rent
    if period_month == checkin.replace(day=1):
        prorated = prorated_first_month_rent(rent, checkin)
        deposit  = Decimal(str(tenancy.security_deposit or 0))
        booking  = Decimal(str(tenancy.booking_amount or 0))
        return max(prorated + deposit - booking, Decimal("0"))
    return rent
