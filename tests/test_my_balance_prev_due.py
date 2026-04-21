"""Regression tests for MY_BALANCE prev-month carry-forward.

Bug fixed in commit d6d83f9: when a tenant asks for a specific month's
balance, the handler must include unpaid dues from months BEFORE that
month (same formula as scripts/sync_sheet_from_db.py:201-220):

    balance = this_month_rent_due + prev_month_unpaid - this_month_paid

where prev_month_unpaid = sum(prev RentSchedule.rent_due) - sum(prev Payments).
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database.models import RentStatus, TenancyStatus


def _make_session(
    tenancy,
    rent_schedule_row,
    this_month_paid: Decimal,
    prev_total_due: Decimal,
    prev_total_paid: Decimal,
):
    """Mock AsyncSession that returns, in order:
      1. Tenancy (scalars().first())
      2. RentSchedule for asked month (scalars().first())
      3. sum(Payment) for asked month (scalar())
      4. prev_due_row tuple (first())
    """
    session = AsyncMock()

    # Each call to session.execute returns a result whose methods are callables
    call_idx = {"n": 0}

    def _make_result(kind, value):
        res = MagicMock()
        if kind == "scalars_first":
            scalars = MagicMock()
            scalars.first = MagicMock(return_value=value)
            scalars.all = MagicMock(return_value=[value] if value else [])
            res.scalars = MagicMock(return_value=scalars)
        elif kind == "scalar":
            res.scalar = MagicMock(return_value=value)
        elif kind == "first":
            res.first = MagicMock(return_value=value)
        return res

    plan = [
        ("scalars_first", tenancy),
        ("scalars_first", rent_schedule_row),
        ("scalar", this_month_paid),
        ("first", (prev_total_due, prev_total_paid)),
    ]

    async def _execute(stmt):
        i = call_idx["n"]
        call_idx["n"] += 1
        kind, val = plan[i]
        return _make_result(kind, val)

    session.execute = _execute
    return session


def _make_ctx():
    ctx = MagicMock()
    ctx.tenant_id = 42
    return ctx


def _make_tenancy():
    t = MagicMock()
    t.id = 1
    t.tenant_id = 42
    t.status = TenancyStatus.active
    t.security_deposit = Decimal("0")
    t.booking_amount = Decimal("0")
    return t


def _make_rs(rent_due: Decimal, status=RentStatus.pending):
    rs = MagicMock()
    rs.rent_due = rent_due
    rs.adjustment = Decimal("0")
    rs.status = status
    rs.period_month = date(2026, 5, 1)
    return rs


def test_prev_month_fully_paid_no_carry_forward():
    """(a) Tenant paid last month in full → prev_due should be 0."""
    from src.whatsapp.handlers.tenant_handler import _my_balance

    tenancy = _make_tenancy()
    rs = _make_rs(Decimal("12000"))
    session = _make_session(
        tenancy=tenancy,
        rent_schedule_row=rs,
        this_month_paid=Decimal("0"),
        prev_total_due=Decimal("12000"),
        prev_total_paid=Decimal("12000"),  # fully paid prev month
    )
    ctx = _make_ctx()
    entities = {"description": "my balance for may"}

    msg = asyncio.run(_my_balance(entities, ctx, session))

    assert "Previous unpaid" not in msg, f"should not show prev unpaid line: {msg}"
    assert "Outstanding: Rs.12,000" in msg
    assert "Rent due: Rs.12,000" in msg


def test_prev_month_partial_unpaid_carry_forward():
    """(b) Tenant has Rs.5,000 unpaid from prev month → balance must include it."""
    from src.whatsapp.handlers.tenant_handler import _my_balance

    tenancy = _make_tenancy()
    rs = _make_rs(Decimal("12000"))
    session = _make_session(
        tenancy=tenancy,
        rent_schedule_row=rs,
        this_month_paid=Decimal("0"),
        prev_total_due=Decimal("12000"),
        prev_total_paid=Decimal("7000"),  # Rs.5000 unpaid carry-forward
    )
    ctx = _make_ctx()
    entities = {"description": "my balance for may"}

    msg = asyncio.run(_my_balance(entities, ctx, session))

    # 12,000 this month + 5,000 prev unpaid - 0 paid = 17,000
    assert "Previous unpaid: Rs.5,000" in msg, f"missing prev unpaid: {msg}"
    assert "Outstanding: Rs.17,000" in msg, f"wrong outstanding: {msg}"
