"""Rent schedule business-rule helpers.

Single source of truth for the "first month Rent Due = rent + deposit"
rule documented in `memory/feedback_deposit_dues_logic.md`. Every call
site that creates or refreshes a RentSchedule row must go through
`first_month_rent_due()` so the DB and Sheet stay in sync.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.database.models import Tenancy


def first_month_rent_due(tenancy: "Tenancy", period_month: date) -> Decimal:
    """Return the Rent Due for a given period.

    First month (where ``period_month`` matches the tenancy's check-in
    month) bundles the security deposit into rent_due — this mirrors the
    Google Sheet "Rent Due" column and the printed receipt logic.
    All other months use the plain agreed rent.
    """
    rent = Decimal(str(tenancy.agreed_rent or 0))
    checkin = getattr(tenancy, "checkin_date", None)
    if checkin is None:
        return rent
    if period_month == checkin.replace(day=1):
        deposit = Decimal(str(tenancy.security_deposit or 0))
        return rent + deposit
    return rent
