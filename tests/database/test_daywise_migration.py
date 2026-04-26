"""Unit tests for DaywiseStay → Tenancy migration logic."""
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal


def _make_daywise(phone="9876543210", name="Test Guest", checkin=date(2026, 4, 1),
                   checkout=date(2026, 4, 3), daily_rate=500, total_amount=1000,
                   booking_amount=500, maintenance=0, room="101",
                   status="EXIT", source_file=None):
    dw = MagicMock()
    dw.phone = phone
    dw.guest_name = name
    dw.checkin_date = checkin
    dw.checkout_date = checkout
    dw.num_days = (checkout - checkin).days
    dw.daily_rate = Decimal(str(daily_rate))
    dw.total_amount = Decimal(str(total_amount))
    dw.booking_amount = Decimal(str(booking_amount))
    dw.maintenance = Decimal(str(maintenance))
    dw.room_number = room
    dw.status = status
    dw.comments = ""
    dw.payment_date = checkin
    dw.source_file = source_file
    return dw


@pytest.mark.asyncio
async def test_skip_no_phone():
    from scripts.migrate_daywise_to_tenancy import migrate_row
    dw = _make_daywise(phone=None)
    session = AsyncMock()
    result = await migrate_row(dw, session, dry_run=True)
    assert result == "skip_no_phone"


@pytest.mark.asyncio
async def test_skip_already_migrated():
    from scripts.migrate_daywise_to_tenancy import migrate_row
    dw = _make_daywise(source_file="MIGRATED")
    session = AsyncMock()
    result = await migrate_row(dw, session, dry_run=True)
    assert result == "skip_already"


@pytest.mark.asyncio
async def test_creates_tenancy_for_new_guest():
    from scripts.migrate_daywise_to_tenancy import _build_tenancy_data
    dw = _make_daywise()
    data = _build_tenancy_data(dw, tenant_id=42, room_id=7)
    assert data["stay_type"].value == "daily"
    assert data["agreed_rent"] == Decimal("500")   # daily_rate
    assert data["booking_amount"] == Decimal("500")
    assert data["checkin_date"] == date(2026, 4, 1)
    assert data["checkout_date"] == date(2026, 4, 3)
    assert data["tenant_id"] == 42
    assert data["room_id"] == 7


@pytest.mark.asyncio
async def test_payment_created_when_total_positive():
    from scripts.migrate_daywise_to_tenancy import _build_payment_data
    dw = _make_daywise(total_amount=1000)
    data = _build_payment_data(dw, tenancy_id=99)
    assert data is not None
    assert data["amount"] == Decimal("1000")
    assert data["tenancy_id"] == 99


@pytest.mark.asyncio
async def test_no_payment_when_total_zero():
    from scripts.migrate_daywise_to_tenancy import _build_payment_data
    dw = _make_daywise(total_amount=0)
    data = _build_payment_data(dw, tenancy_id=99)
    assert data is None
