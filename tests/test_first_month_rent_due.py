"""Tests for the first-month Rent Due formula.

Business rule (memory/feedback_billing_proration.md):
  First month (checkin month) Rent Due = floor(agreed_rent * days_billed
                                                / days_in_month)
                                         + security_deposit
      where days_billed = days_in_month - checkin.day + 1
  Subsequent months                     = agreed_rent

First month is always pro rata by check-in date, everywhere (DB, Sheet,
Excel, bot, onboarding). Deposit bundling mirrors the sheet's "Rent Due"
column convention.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.services.rent_schedule import first_month_rent_due, prorated_first_month_rent


class _FakeTenancy:
    def __init__(self, agreed_rent, security_deposit, checkin_date, booking_amount=0):
        self.agreed_rent = Decimal(str(agreed_rent))
        self.security_deposit = Decimal(str(security_deposit))
        self.checkin_date = checkin_date
        self.booking_amount = Decimal(str(booking_amount))


def test_first_month_prorates_and_bundles_deposit():
    # Check-in 11 Apr (30-day month): 20/30 days.
    # Prorated rent = floor(12000 * 20/30) = 8000. + deposit 6000 = 14000.
    ten = _FakeTenancy(agreed_rent=12000, security_deposit=6000,
                       checkin_date=date(2026, 4, 11))
    assert first_month_rent_due(ten, date(2026, 4, 1)) == Decimal("14000")


def test_subsequent_months_are_rent_only():
    ten = _FakeTenancy(agreed_rent=12000, security_deposit=6000,
                       checkin_date=date(2026, 4, 11))
    assert first_month_rent_due(ten, date(2026, 5, 1)) == Decimal("12000")
    assert first_month_rent_due(ten, date(2026, 6, 1)) == Decimal("12000")


def test_checkin_on_first_of_month_no_proration():
    # Full month billed; bundles deposit.
    ten = _FakeTenancy(agreed_rent=10000, security_deposit=5000,
                       checkin_date=date(2026, 3, 1))
    assert first_month_rent_due(ten, date(2026, 3, 1)) == Decimal("15000")


def test_zero_deposit_first_month_just_prorated_rent():
    # Apr 5 (30-day month): 26/30 days. floor(10000 * 26/30) = 8666.
    ten = _FakeTenancy(agreed_rent=10000, security_deposit=0,
                       checkin_date=date(2026, 4, 5))
    assert first_month_rent_due(ten, date(2026, 4, 1)) == Decimal("8666")


def test_none_deposit_treated_as_zero():
    ten = _FakeTenancy(agreed_rent=10000, security_deposit=0,
                       checkin_date=date(2026, 4, 5))
    ten.security_deposit = None
    assert first_month_rent_due(ten, date(2026, 4, 1)) == Decimal("8666")


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


@pytest.mark.parametrize("checkin,expected", [
    (date(2026, 4, 1),  10000),  # full 30-day month
    (date(2026, 4, 15),  5333),  # 16/30
    (date(2026, 4, 30),   333),  # 1/30
    (date(2026, 5, 15),  5483),  # 17/31
    (date(2026, 2, 28),   357),  # 1/28
    (date(2024, 2, 29),   344),  # leap year, 1/29
])
def test_prorated_first_month_rent_math(checkin, expected):
    assert prorated_first_month_rent(10000, checkin) == Decimal(str(expected))
