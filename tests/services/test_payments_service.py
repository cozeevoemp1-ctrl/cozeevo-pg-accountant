"""
tests/services/test_payments_service.py
=========================================
Unit tests for src/services/payments.py

Uses mocked AsyncSession — no live DB required.
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The service we're testing — imported lazily inside each test so the module
# is fresh each run (avoids circular-import issues at collection time).


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_session(
    tenancy_rent: Decimal = Decimal("8000"),
    existing_paid: Decimal = Decimal("0"),
    rent_schedule_row=None,
):
    """Return a mock AsyncSession pre-configured for a single tenancy."""
    from src.database.models import Payment as _Payment

    session = AsyncMock()

    # session.get(Tenancy, ...) — return a minimal Tenancy
    tenancy = MagicMock()
    tenancy.id = 99
    tenancy.room_id = 5
    tenancy.agreed_rent = tenancy_rent
    tenancy.maintenance_fee = Decimal("0")

    # session.scalar(select(RentSchedule)...) called twice:
    #   1st call → existing rent_schedule (or None to force auto-create)
    #   2nd call → sum of previous payments
    scalar_results = [rent_schedule_row, existing_paid]
    call_count = {"n": 0}

    async def _scalar(stmt):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(scalar_results):
            return scalar_results[idx]
        return None

    _next_id = {"v": 1}

    def _add(obj):
        # Simulate DB assigning an auto-increment id on add
        if isinstance(obj, _Payment) and obj.id is None:
            obj.id = _next_id["v"]
            _next_id["v"] += 1

    session.scalar = _scalar
    session.get = AsyncMock(return_value=tenancy)
    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()

    return session, tenancy


# ── Test 1: failing test (before service exists) ───────────────────────────────

class TestLogPayment:
    """Core contract tests for log_payment()."""

    @pytest.mark.asyncio
    async def test_creates_payment_row(self):
        """log_payment must insert a Payment row with correct fields."""
        from src.services.payments import log_payment, PaymentResult

        session, tenancy = _make_session()

        result = await log_payment(
            tenancy_id=99,
            amount=8000,
            method="UPI",
            for_type="rent",
            period_month="2026-04",
            recorded_by="kiran@cozeevo",
            session=session,
        )

        # Must return a PaymentResult
        assert isinstance(result, PaymentResult), f"Expected PaymentResult, got {type(result)}"
        assert result.payment_id is not None, "payment_id must be set"
        assert isinstance(result.new_balance, Decimal), "new_balance must be Decimal"

        # session.add must have been called at least once with a Payment-like object
        assert session.add.called, "session.add was never called"

    @pytest.mark.asyncio
    async def test_payment_row_fields(self):
        """The Payment object added to session must carry correct field values."""
        from src.services.payments import log_payment
        from src.database.models import Payment, PaymentMode, PaymentFor

        session, tenancy = _make_session()
        added_objects = []
        session.add = MagicMock(side_effect=added_objects.append)

        await log_payment(
            tenancy_id=99,
            amount=8000,
            method="UPI",
            for_type="rent",
            period_month="2026-04",
            recorded_by="kiran@cozeevo",
            session=session,
        )

        payment_rows = [o for o in added_objects if isinstance(o, Payment)]
        assert len(payment_rows) == 1, f"Expected 1 Payment row, got {len(payment_rows)}"

        p = payment_rows[0]
        assert p.tenancy_id == 99
        assert p.amount == Decimal("8000")
        assert p.payment_mode == PaymentMode.upi
        assert p.for_type == PaymentFor.rent
        assert p.is_void == False
        assert p.period_month == date(2026, 4, 1)

    @pytest.mark.asyncio
    async def test_audit_log_row_created(self):
        """log_payment must write an AuditLog row with action='payment.log'."""
        from src.services.payments import log_payment
        from src.database.models import AuditLog

        session, tenancy = _make_session()
        added_objects = []
        session.add = MagicMock(side_effect=added_objects.append)

        await log_payment(
            tenancy_id=99,
            amount=8000,
            method="UPI",
            for_type="rent",
            period_month="2026-04",
            recorded_by="kiran@cozeevo",
            session=session,
        )

        audit_rows = [o for o in added_objects if isinstance(o, AuditLog)]
        assert len(audit_rows) >= 1, "Expected at least one AuditLog row"

        audit = audit_rows[0]
        assert audit.field == "payment.log", (
            f"Expected field='payment.log', got field='{audit.field}'"
        )
        assert audit.changed_by == "kiran@cozeevo"
        assert audit.entity_type == "payment"

    @pytest.mark.asyncio
    async def test_new_balance_zero_after_exact_payment(self):
        """When amount == rent_due, new_balance should be 0."""
        from src.services.payments import log_payment

        session, tenancy = _make_session(tenancy_rent=Decimal("8000"), existing_paid=Decimal("0"))

        result = await log_payment(
            tenancy_id=99,
            amount=8000,
            method="cash",
            for_type="rent",
            period_month="2026-04",
            recorded_by="kiran@cozeevo",
            session=session,
        )

        assert result.new_balance == Decimal("0"), (
            f"Expected new_balance=0, got {result.new_balance}"
        )

    @pytest.mark.asyncio
    async def test_new_balance_positive_when_underpaid(self):
        """When amount < rent_due, new_balance should be the remainder."""
        from src.services.payments import log_payment

        session, tenancy = _make_session(tenancy_rent=Decimal("8000"), existing_paid=Decimal("0"))

        result = await log_payment(
            tenancy_id=99,
            amount=5000,
            method="cash",
            for_type="rent",
            period_month="2026-04",
            recorded_by="kiran@cozeevo",
            session=session,
        )

        assert result.new_balance == Decimal("3000"), (
            f"Expected new_balance=3000, got {result.new_balance}"
        )

    @pytest.mark.asyncio
    async def test_payment_id_is_set_after_flush(self):
        """payment_id in PaymentResult must come from the Payment object after flush."""
        from src.services.payments import log_payment
        from src.database.models import Payment

        session, tenancy = _make_session()
        added_objects = []

        def _add(obj):
            added_objects.append(obj)
            if isinstance(obj, Payment):
                obj.id = 42  # simulate DB-assigned id after flush

        session.add = MagicMock(side_effect=_add)

        result = await log_payment(
            tenancy_id=99,
            amount=8000,
            method="UPI",
            for_type="rent",
            period_month="2026-04",
            recorded_by="kiran@cozeevo",
            session=session,
        )

        assert result.payment_id == 42
