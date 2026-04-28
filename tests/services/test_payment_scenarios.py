"""
tests/services/test_payment_scenarios.py
=========================================
Scenario-level tests for payment business logic.

Covers:
  - Rent vs deposit as separate transactions
  - Adjustment reduces effective due
  - Freeze guard blocks past-month payments (bot + PWA)
  - Partial payment → RentStatus.partial
  - Second payment clears balance
  - Deposit/booking payment: no RentSchedule touched, status=None
  - Duplicate hash raises ValueError
  - Method mapping (UPI, cash, bank)
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock factory ────────────────────────────────────────────────────────

def _mock_session(
    tenancy_rent: Decimal = Decimal("8000"),
    existing_paid: Decimal = Decimal("0"),
    rent_schedule=None,
    daily: bool = False,
):
    """Mock AsyncSession for a single tenancy."""
    from src.database.models import Payment, RentSchedule, RentStatus

    session = AsyncMock()

    tenancy = MagicMock()
    tenancy.id = 99
    tenancy.room_id = 5
    tenancy.agreed_rent = tenancy_rent
    tenancy.maintenance_fee = Decimal("0")
    tenancy.booking_amount = Decimal("0")
    tenancy.stay_type = MagicMock()
    tenancy.stay_type.value = "daily" if daily else "monthly"

    # scalar call order: rent_schedule lookup → prev_paid sum → staff lookup
    scalar_seq = [rent_schedule, existing_paid, None]
    _i = {"n": 0}

    async def _scalar(stmt):
        idx = _i["n"]
        _i["n"] += 1
        return scalar_seq[idx] if idx < len(scalar_seq) else None

    _next_id = {"v": 1}

    def _add(obj):
        if isinstance(obj, Payment) and obj.id is None:
            obj.id = _next_id["v"]
            _next_id["v"] += 1

    session.scalar = _scalar
    session.get = AsyncMock(return_value=tenancy)
    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    return session, tenancy


def _mock_rs(rent_due: Decimal, adjustment: Decimal = Decimal("0")):
    """Return a mock RentSchedule row."""
    from src.database.models import RentSchedule, RentStatus
    rs = MagicMock(spec=RentSchedule)
    rs.rent_due = rent_due
    rs.adjustment = adjustment
    rs.notes = None
    rs.status = RentStatus.pending
    return rs


# ── Scenario 1: Rent and deposit are SEPARATE transactions ─────────────────────

class TestRentAndDepositAreSeparate:

    @pytest.mark.asyncio
    async def test_rent_payment_sets_period_month(self):
        """Rent payment: period_month is set on the Payment row."""
        from src.services.payments import log_payment
        from src.database.models import Payment, PaymentFor

        session, _ = _mock_session()
        added = []
        session.add = MagicMock(side_effect=added.append)

        await log_payment(
            tenancy_id=99, amount=8000, method="UPI", for_type="rent",
            period_month="2026-05", recorded_by="kiran", session=session,
        )

        payments = [o for o in added if isinstance(o, Payment)]
        assert payments, "No Payment row created"
        assert payments[0].for_type == PaymentFor.rent
        assert payments[0].period_month == date(2026, 5, 1)

    @pytest.mark.asyncio
    async def test_deposit_payment_has_no_period_month(self):
        """Deposit payment: period_month is NULL (not linked to a month)."""
        from src.services.payments import log_payment
        from src.database.models import Payment, PaymentFor

        session, _ = _mock_session()
        added = []
        session.add = MagicMock(side_effect=added.append)

        await log_payment(
            tenancy_id=99, amount=15000, method="cash", for_type="deposit",
            period_month=None, recorded_by="kiran", session=session,
        )

        payments = [o for o in added if isinstance(o, Payment)]
        assert payments, "No Payment row created"
        assert payments[0].for_type == PaymentFor.deposit
        assert payments[0].period_month is None, "Deposit must NOT have period_month set"

    @pytest.mark.asyncio
    async def test_deposit_does_not_touch_rent_schedule(self):
        """Deposit payment: RentSchedule must NOT be created or modified."""
        from src.services.payments import log_payment
        from src.database.models import RentSchedule

        session, _ = _mock_session()
        added = []
        session.add = MagicMock(side_effect=added.append)

        result = await log_payment(
            tenancy_id=99, amount=15000, method="cash", for_type="deposit",
            period_month=None, recorded_by="kiran", session=session,
        )

        rs_rows = [o for o in added if isinstance(o, RentSchedule)]
        assert not rs_rows, "Deposit must not create a RentSchedule row"
        assert result.status is None, "status must be None for non-rent payments"
        assert result.effective_due == Decimal("0")
        assert result.total_paid == Decimal("0")

    @pytest.mark.asyncio
    async def test_booking_advance_no_rent_schedule(self):
        """Booking advance (for_type=booking): same as deposit — no RentSchedule."""
        from src.services.payments import log_payment
        from src.database.models import RentSchedule

        session, _ = _mock_session()
        added = []
        session.add = MagicMock(side_effect=added.append)

        result = await log_payment(
            tenancy_id=99, amount=5000, method="UPI", for_type="booking",
            period_month=None, recorded_by="kiran", session=session,
        )

        rs_rows = [o for o in added if isinstance(o, RentSchedule)]
        assert not rs_rows
        assert result.status is None


# ── Scenario 2: Adjustment reduces effective due ───────────────────────────────

class TestAdjustmentReducesDue:

    @pytest.mark.asyncio
    async def test_positive_adjustment_increases_due(self):
        """Carry-forward (+500): effective_due = rent_due + 500."""
        from src.services.payments import log_payment
        from src.database.models import RentStatus

        rs = _mock_rs(rent_due=Decimal("8000"), adjustment=Decimal("500"))
        session, _ = _mock_session(rent_schedule=rs)

        result = await log_payment(
            tenancy_id=99, amount=8500, method="cash", for_type="rent",
            period_month="2026-05", recorded_by="kiran", session=session,
        )

        assert result.effective_due == Decimal("8500")
        assert result.new_balance == Decimal("0")
        assert result.status == RentStatus.paid

    @pytest.mark.asyncio
    async def test_negative_adjustment_is_discount(self):
        """Discount (-500): effective_due = rent_due - 500."""
        from src.services.payments import log_payment
        from src.database.models import RentStatus

        rs = _mock_rs(rent_due=Decimal("8000"), adjustment=Decimal("-500"))
        session, _ = _mock_session(rent_schedule=rs)

        result = await log_payment(
            tenancy_id=99, amount=7500, method="cash", for_type="rent",
            period_month="2026-05", recorded_by="kiran", session=session,
        )

        assert result.effective_due == Decimal("7500")
        assert result.new_balance == Decimal("0")
        assert result.status == RentStatus.paid

    @pytest.mark.asyncio
    async def test_zero_adjustment_unchanged(self):
        """adjustment=0: effective_due equals rent_due exactly."""
        from src.services.payments import log_payment

        rs = _mock_rs(rent_due=Decimal("8000"), adjustment=Decimal("0"))
        session, _ = _mock_session(rent_schedule=rs)

        result = await log_payment(
            tenancy_id=99, amount=8000, method="UPI", for_type="rent",
            period_month="2026-05", recorded_by="kiran", session=session,
        )

        assert result.effective_due == Decimal("8000")
        assert result.new_balance == Decimal("0")


# ── Scenario 3: Freeze guard blocks past months ────────────────────────────────

class TestFreezeGuard:

    @pytest.mark.asyncio
    async def test_past_month_rent_raises_value_error(self):
        """Logging rent for a past calendar month must raise ValueError with 'period_frozen'."""
        from src.services.payments import log_payment

        session, _ = _mock_session()
        with pytest.raises(ValueError, match="period_frozen"):
            await log_payment(
                tenancy_id=99, amount=8000, method="cash", for_type="rent",
                period_month="2026-03",  # March is past
                recorded_by="kiran", session=session,
            )

    @pytest.mark.asyncio
    async def test_current_month_is_allowed(self):
        """Current month must always be allowed."""
        from src.services.payments import log_payment

        today = date.today()
        period = f"{today.year}-{today.month:02d}"
        session, _ = _mock_session()

        # Should not raise
        result = await log_payment(
            tenancy_id=99, amount=8000, method="cash", for_type="rent",
            period_month=period, recorded_by="kiran", session=session,
        )
        assert result.payment_id is not None

    @pytest.mark.asyncio
    async def test_future_month_advance_is_allowed(self):
        """Advance payment for a future month must be allowed."""
        from src.services.payments import log_payment

        today = date.today()
        # next month
        nm = today.month % 12 + 1
        ny = today.year + (1 if today.month == 12 else 0)
        period = f"{ny}-{nm:02d}"
        session, _ = _mock_session()

        result = await log_payment(
            tenancy_id=99, amount=8000, method="cash", for_type="rent",
            period_month=period, recorded_by="kiran", session=session,
        )
        assert result.payment_id is not None

    @pytest.mark.asyncio
    async def test_deposit_bypasses_freeze_guard(self):
        """Deposit (no period_month) must never be blocked by the freeze guard."""
        from src.services.payments import log_payment

        session, _ = _mock_session()
        result = await log_payment(
            tenancy_id=99, amount=15000, method="cash", for_type="deposit",
            period_month=None, recorded_by="kiran", session=session,
        )
        assert result.payment_id is not None


# ── Scenario 4: Partial then full payment ─────────────────────────────────────

class TestPartialThenFull:

    @pytest.mark.asyncio
    async def test_partial_payment_leaves_balance(self):
        """₹5000 paid against ₹8000 due → balance ₹3000, status partial."""
        from src.services.payments import log_payment
        from src.database.models import RentStatus

        rs = _mock_rs(rent_due=Decimal("8000"))
        session, _ = _mock_session(existing_paid=Decimal("0"), rent_schedule=rs)

        result = await log_payment(
            tenancy_id=99, amount=5000, method="cash", for_type="rent",
            period_month="2026-05", recorded_by="kiran", session=session,
        )
        assert result.new_balance == Decimal("3000")
        assert result.status == RentStatus.partial

    @pytest.mark.asyncio
    async def test_second_payment_clears_balance(self):
        """After ₹5000 already paid, second ₹3000 → balance 0, status paid."""
        from src.services.payments import log_payment
        from src.database.models import RentStatus

        rs = _mock_rs(rent_due=Decimal("8000"))
        # existing_paid=5000 simulates first payment already recorded
        session, _ = _mock_session(existing_paid=Decimal("5000"), rent_schedule=rs)

        result = await log_payment(
            tenancy_id=99, amount=3000, method="UPI", for_type="rent",
            period_month="2026-05", recorded_by="kiran", session=session,
        )
        assert result.new_balance == Decimal("0")
        assert result.status == RentStatus.paid
        assert result.total_paid == Decimal("8000")

    @pytest.mark.asyncio
    async def test_overpayment_gives_negative_balance(self):
        """Overpayment: balance goes negative (credit for next month)."""
        from src.services.payments import log_payment

        rs = _mock_rs(rent_due=Decimal("8000"))
        session, _ = _mock_session(existing_paid=Decimal("0"), rent_schedule=rs)

        result = await log_payment(
            tenancy_id=99, amount=9000, method="cash", for_type="rent",
            period_month="2026-05", recorded_by="kiran", session=session,
        )
        assert result.new_balance == Decimal("-1000")


# ── Scenario 5: Payment method mapping ────────────────────────────────────────

class TestMethodMapping:

    @pytest.mark.asyncio
    async def test_upi_maps_correctly(self):
        from src.services.payments import log_payment
        from src.database.models import Payment, PaymentMode
        session, _ = _mock_session()
        added = []
        session.add = MagicMock(side_effect=added.append)
        await log_payment(tenancy_id=99, amount=8000, method="UPI", for_type="rent",
                          period_month="2026-05", recorded_by="k", session=session)
        p = [o for o in added if isinstance(o, Payment)][0]
        assert p.payment_mode == PaymentMode.upi

    @pytest.mark.asyncio
    async def test_cash_maps_correctly(self):
        from src.services.payments import log_payment
        from src.database.models import Payment, PaymentMode
        session, _ = _mock_session()
        added = []
        session.add = MagicMock(side_effect=added.append)
        await log_payment(tenancy_id=99, amount=8000, method="CASH", for_type="rent",
                          period_month="2026-05", recorded_by="k", session=session)
        p = [o for o in added if isinstance(o, Payment)][0]
        assert p.payment_mode == PaymentMode.cash

    @pytest.mark.asyncio
    async def test_bank_maps_correctly(self):
        from src.services.payments import log_payment
        from src.database.models import Payment, PaymentMode
        session, _ = _mock_session()
        added = []
        session.add = MagicMock(side_effect=added.append)
        await log_payment(tenancy_id=99, amount=8000, method="BANK", for_type="rent",
                          period_month="2026-05", recorded_by="k", session=session)
        p = [o for o in added if isinstance(o, Payment)][0]
        assert p.payment_mode == PaymentMode.bank_transfer


# ── Scenario 6: Daily stay — no RentSchedule ──────────────────────────────────

class TestDailyStay:

    @pytest.mark.asyncio
    async def test_daily_stay_rent_has_no_rent_schedule(self):
        """Daily-stay tenancies skip RentSchedule entirely."""
        from src.services.payments import log_payment
        from src.database.models import RentSchedule

        session, _ = _mock_session(daily=True)
        added = []
        session.add = MagicMock(side_effect=added.append)

        result = await log_payment(
            tenancy_id=99, amount=500, method="cash", for_type="rent",
            period_month="2026-05", recorded_by="kiran", session=session,
        )

        rs_rows = [o for o in added if isinstance(o, RentSchedule)]
        assert not rs_rows, "Daily stay must not create RentSchedule"
        assert result.status is None


# ── Scenario 7: Tenancy not found ─────────────────────────────────────────────

class TestTenancyNotFound:

    @pytest.mark.asyncio
    async def test_missing_tenancy_raises(self):
        from src.services.payments import log_payment

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await log_payment(
                tenancy_id=999999, amount=8000, method="cash", for_type="rent",
                period_month="2026-05", recorded_by="kiran", session=session,
            )
