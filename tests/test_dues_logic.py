"""Unit tests for src/services/dues.py — the shared monthly-dues service.

These lock the split-dues math that get_tenant_dues / kpi tile / kpi panel
must all agree on. Pure functions only — no DB.
"""
from datetime import date
from decimal import Decimal

from src.services.dues import (
    MonthlyDues,
    first_month_due,
    monthly_dues,
    period_bounds,
    period_remaining,
)

AUG = date(2026, 8, 1)
TODAY = date(2026, 8, 7)


def _md(**kw) -> MonthlyDues:
    """monthly_dues with normal-month defaults; override per test."""
    base = dict(
        period=AUG,
        as_of=TODAY,
        checkin_date=date(2026, 3, 10),
        agreed_rent=10000,
        security_deposit=15000,
        rent_due=10000,
        adjustment=0,
        rent_paid=0,
        deposit_paid=0,
        booking_paid_rows=0,
        booking_amount_field=0,
    )
    base.update(kw)
    return monthly_dues(**base)


# ── period helpers ────────────────────────────────────────────────────────────

def test_period_bounds_normal():
    assert period_bounds(date(2026, 8, 15)) == (date(2026, 8, 1), date(2026, 9, 1))


def test_period_bounds_december_rolls_year():
    assert period_bounds(date(2026, 12, 1)) == (date(2026, 12, 1), date(2027, 1, 1))


def test_period_remaining_basic():
    assert period_remaining(10000, 0, 4000) == Decimal("6000")


def test_period_remaining_with_adjustment():
    assert period_remaining(10000, -2000, 4000) == Decimal("4000")


def test_period_remaining_overpaid_floors_at_zero():
    assert period_remaining(10000, 0, 12000) == Decimal("0")


# ── first_month_due (bundled view: prorated + deposit − booking) ─────────────

def test_first_month_due_nets_booking():
    # Check-in 16 Aug in a 31-day month: 16 days billed → floor(10000*16/31)=5161
    assert first_month_due(10000, 15000, 2000, date(2026, 8, 16)) == 5161 + 15000 - 2000


def test_first_month_due_never_negative():
    assert first_month_due(10000, 0, 99999, date(2026, 8, 16)) == 0


# ── monthly_dues: normal month ───────────────────────────────────────────────

def test_normal_month_unpaid():
    d = _md()
    assert d.rent_dues == 10000
    # Deposit never paid and no advance → still owed in full.
    assert d.deposit_due == 15000
    assert d.total == 25000


def test_normal_month_partial_and_credit():
    d = _md(rent_paid=4000, deposit_paid=15000)
    assert d.rent_dues == 6000
    assert d.credit == 0
    over = _md(rent_paid=12000, deposit_paid=15000)
    assert over.rent_dues == 0
    assert over.credit == 2000


def test_normal_month_adjustment_waiver():
    d = _md(adjustment=-3000, rent_paid=7000, deposit_paid=15000)
    assert d.rent_dues == 0


def test_deposit_due_credits_booking_rows_over_field():
    # Payment rows exist → field ignored (history-first, rules_daystay_dues).
    d = _md(deposit_paid=5000, booking_paid_rows=5000, booking_amount_field=2000)
    assert d.deposit_due == 15000 - 5000 - 5000
    # No rows → legacy field fallback.
    d2 = _md(deposit_paid=5000, booking_paid_rows=0, booking_amount_field=2000)
    assert d2.deposit_due == 15000 - 5000 - 2000


def test_future_checkin_owes_nothing():
    d = _md(checkin_date=date(2026, 8, 20))  # after as_of Aug 7
    assert d.not_yet_checked_in is True
    assert d.rent_dues == 0
    assert d.deposit_due == 0
    assert d.total == 0


# ── monthly_dues: check-in month split ───────────────────────────────────────

def test_first_month_split():
    # Check-in 16 Aug: prorated = floor(10000*16/31) = 5161
    d = _md(checkin_date=date(2026, 8, 16), as_of=date(2026, 8, 20),
            rent_due=5161 + 15000, rent_paid=5161, deposit_paid=15000)
    assert d.is_first_month is True
    assert d.prorated_rent == 5161
    assert d.rent_dues == 0
    assert d.deposit_due == 0


def test_first_month_rent_overflow_fills_deposit():
    # Paid 8000 rent against 5161 prorated → 2839 overflows to deposit.
    d = _md(checkin_date=date(2026, 8, 16), as_of=date(2026, 8, 20),
            rent_due=5161 + 15000, rent_paid=8000)
    assert d.rent_dues == 0
    assert d.deposit_due == 15000 - 2839


def test_first_month_adjustment_reduces_prorated():
    d = _md(checkin_date=date(2026, 8, 16), as_of=date(2026, 8, 20),
            rent_due=5161 + 15000, adjustment=-5161, rent_paid=0)
    assert d.rent_dues == 0
