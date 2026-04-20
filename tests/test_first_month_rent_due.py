"""Tests for the first-month Rent Due formula.

Business rule (memory/feedback_deposit_dues_logic.md):
  First month (checkin month) Rent Due = agreed_rent + security_deposit
  Subsequent months       Rent Due = agreed_rent

Motivated by the 2026-04-20 Diya Gupta blunder where her April
(checkin month) RentSchedule row had rent_due=12,000 instead of
18,000, so the bot/sheet said "This month: PAID" after she paid only
the rent portion.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.services.rent_schedule import first_month_rent_due


class _FakeTenancy:
    def __init__(self, agreed_rent, security_deposit, checkin_date):
        self.agreed_rent = Decimal(str(agreed_rent))
        self.security_deposit = Decimal(str(security_deposit))
        self.checkin_date = checkin_date


def test_first_month_bundles_deposit():
    ten = _FakeTenancy(agreed_rent=12000, security_deposit=6000,
                       checkin_date=date(2026, 4, 11))
    assert first_month_rent_due(ten, date(2026, 4, 1)) == Decimal("18000")


def test_subsequent_months_are_rent_only():
    ten = _FakeTenancy(agreed_rent=12000, security_deposit=6000,
                       checkin_date=date(2026, 4, 11))
    assert first_month_rent_due(ten, date(2026, 5, 1)) == Decimal("12000")
    assert first_month_rent_due(ten, date(2026, 6, 1)) == Decimal("12000")


def test_checkin_on_first_of_month_still_bundles():
    ten = _FakeTenancy(agreed_rent=10000, security_deposit=5000,
                       checkin_date=date(2026, 3, 1))
    assert first_month_rent_due(ten, date(2026, 3, 1)) == Decimal("15000")


def test_zero_deposit_first_month_equals_rent():
    ten = _FakeTenancy(agreed_rent=10000, security_deposit=0,
                       checkin_date=date(2026, 4, 5))
    assert first_month_rent_due(ten, date(2026, 4, 1)) == Decimal("10000")


def test_none_deposit_treated_as_zero():
    ten = _FakeTenancy(agreed_rent=10000, security_deposit=0,
                       checkin_date=date(2026, 4, 5))
    ten.security_deposit = None
    assert first_month_rent_due(ten, date(2026, 4, 1)) == Decimal("10000")


def test_none_rent_treated_as_zero():
    ten = _FakeTenancy(agreed_rent=0, security_deposit=6000,
                       checkin_date=date(2026, 4, 5))
    ten.agreed_rent = None
    assert first_month_rent_due(ten, date(2026, 4, 1)) == Decimal("6000")


@pytest.mark.parametrize("period", [
    date(2026, 3, 1),  # before checkin
    date(2027, 4, 1),  # a year after — still just rent
])
def test_period_not_matching_checkin_month_returns_rent_only(period):
    ten = _FakeTenancy(agreed_rent=12000, security_deposit=6000,
                       checkin_date=date(2026, 4, 11))
    assert first_month_rent_due(ten, period) == Decimal("12000")
