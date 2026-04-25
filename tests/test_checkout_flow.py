"""Tests for checkout confirm helper — _do_confirm_checkout()."""
from __future__ import annotations

import os
import sys

# Force sqlite path so models.py uses JSON fallback instead of JSONB
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pytest_asyncio
from decimal import Decimal
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.database.models import (
    Base,
    Property, Room, RoomType,
    Tenant, Tenancy, TenancyStatus, StayType,
    CheckoutRecord, CheckoutSession, CheckoutSessionStatus,
)


# ── In-memory DB fixtures ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    """Provide a fresh in-memory SQLite session per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def sample_tenancy(db_session: AsyncSession):
    """Create a minimal Property + Room + Tenant + Tenancy and return the Tenancy."""
    prop = Property(name="Test PG")
    db_session.add(prop)
    await db_session.flush()

    room = Room(
        property_id=prop.id,
        room_number="301",
        room_type=RoomType.double,
        org_id=1,
    )
    db_session.add(room)
    await db_session.flush()

    tenant = Tenant(name="Ravi Kumar", phone="9876543210")
    db_session.add(tenant)
    await db_session.flush()

    tenancy = Tenancy(
        tenant_id=tenant.id,
        room_id=room.id,
        stay_type=StayType.monthly,
        status=TenancyStatus.active,
        checkin_date=date(2026, 1, 1),
        agreed_rent=Decimal("12000"),
        security_deposit=Decimal("15000"),
    )
    db_session.add(tenancy)
    await db_session.flush()

    return tenancy


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_do_confirm_checkout_writes_checkout_record(db_session, sample_tenancy):
    """_do_confirm_checkout writes CheckoutRecord with all new fields."""
    from src.whatsapp.handlers.owner_handler import _do_confirm_checkout

    cs = CheckoutSession(
        token="test-token-001",
        status=CheckoutSessionStatus.confirmed.value,
        created_by_phone="9444296681",
        tenant_phone="9876543210",
        tenancy_id=sample_tenancy.id,
        checkout_date=date.today(),
        room_key_returned=True,
        wardrobe_key_returned=True,
        biometric_removed=False,
        room_condition_ok=True,
        damage_notes=None,
        security_deposit=Decimal("15000"),
        pending_dues=Decimal("0"),
        deductions=Decimal("2000"),
        deduction_reason="paint damage",
        refund_amount=Decimal("13000"),
        refund_mode="upi",
        expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    db_session.add(cs)
    await db_session.flush()

    with patch("src.integrations.gsheets.record_checkout", new_callable=AsyncMock) as mock_gs:
        mock_gs.return_value = {"success": True}
        msg = await _do_confirm_checkout(cs, db_session)

    cr = await db_session.scalar(
        select(CheckoutRecord).where(CheckoutRecord.tenancy_id == sample_tenancy.id)
    )
    assert cr is not None, "CheckoutRecord was not created"
    assert cr.main_key_returned is True
    assert cr.cupboard_key_returned is True
    assert cr.biometric_removed is False
    assert cr.room_condition_ok is True
    assert Decimal(str(cr.deductions)) == Decimal("2000")
    assert cr.deduction_reason == "paint damage"
    assert cr.refund_mode == "upi"
    assert Decimal(str(cr.deposit_refunded_amount)) == Decimal("13000")
    assert cr.checkout_session_id == cs.id

    # Tenancy should be marked exited
    await db_session.refresh(sample_tenancy)
    assert sample_tenancy.status == TenancyStatus.exited
    assert sample_tenancy.checkout_date == date.today()

    # Return string must mention checkout/confirmed
    assert "checkout" in msg.lower() or "confirmed" in msg.lower(), f"Unexpected msg: {msg!r}"
    # Must include refund line
    assert "13,000" in msg or "13000" in msg, f"Refund amount missing from msg: {msg!r}"
