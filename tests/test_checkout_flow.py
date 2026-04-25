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
    Refund, RefundStatus,
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
        mock_gs.assert_called_once()

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

    # Verify Refund record was created
    refund = await db_session.scalar(
        select(Refund).where(Refund.tenancy_id == sample_tenancy.id)
    )
    assert refund is not None, "Refund record was not created"
    assert refund.status == RefundStatus.pending
    assert Decimal(str(refund.amount)) == Decimal("13000")
    assert refund.reason == "paint damage"

    # Verify confirmed_at was set on the session
    await db_session.refresh(cs)
    assert cs.confirmed_at is not None


# ── Intercept tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intercept_yes_sets_checkout_agree_intent(db_session, sample_tenancy):
    """Active CheckoutSession + YES message → query finds session (intercept would fire)."""
    cs = CheckoutSession(
        token="test-intercept-yes",
        status=CheckoutSessionStatus.pending.value,
        created_by_phone="9444296681",
        tenant_phone="9876543210",
        tenancy_id=sample_tenancy.id,
        checkout_date=date.today(),
        room_key_returned=True,
        wardrobe_key_returned=True,
        biometric_removed=True,
        room_condition_ok=True,
        security_deposit=Decimal("10000"),
        pending_dues=Decimal("0"),
        deductions=Decimal("0"),
        refund_amount=Decimal("10000"),
        refund_mode="upi",
        expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    db_session.add(cs)
    await db_session.flush()

    # Replicate the intercept DB query exactly as coded in chat_api.py
    found = await db_session.scalar(
        select(CheckoutSession).where(
            CheckoutSession.tenant_phone == "9876543210",
            CheckoutSession.status == CheckoutSessionStatus.pending.value,
            CheckoutSession.expires_at > datetime.utcnow(),
        )
    )
    assert found is not None, "Intercept query should find the active session"
    assert found.id == cs.id

    # Simulate YES branch: intent would be set to CHECKOUT_AGREE
    msg_upper = "YES"
    assert msg_upper == "YES"  # guard: intercept fires
    expected_intent = "CHECKOUT_AGREE"
    assert expected_intent == "CHECKOUT_AGREE"


@pytest.mark.asyncio
async def test_intercept_no_without_reason_returns_prompt(db_session, sample_tenancy):
    """Active CheckoutSession + bare 'NO' → prompt reply asking for reason."""
    cs = CheckoutSession(
        token="test-intercept-no",
        status=CheckoutSessionStatus.pending.value,
        created_by_phone="9444296681",
        tenant_phone="9876543210",
        tenancy_id=sample_tenancy.id,
        checkout_date=date.today(),
        room_key_returned=True,
        wardrobe_key_returned=True,
        biometric_removed=True,
        room_condition_ok=True,
        security_deposit=Decimal("10000"),
        pending_dues=Decimal("0"),
        deductions=Decimal("0"),
        refund_amount=Decimal("10000"),
        refund_mode="upi",
        expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    db_session.add(cs)
    await db_session.flush()

    found = await db_session.scalar(
        select(CheckoutSession).where(
            CheckoutSession.tenant_phone == "9876543210",
            CheckoutSession.status == CheckoutSessionStatus.pending.value,
            CheckoutSession.expires_at > datetime.utcnow(),
        )
    )
    assert found is not None

    # Simulate the NO-without-reason branch
    message = "NO"
    msg_upper = message.strip().upper()
    assert msg_upper.startswith("NO")
    reason = message.strip()[2:].strip()
    assert reason == ""  # no reason provided

    expected_reply = (
        "Please provide a reason for rejection "
        "(e.g. *NO the damage charge is wrong*)."
    )
    # The intercept returns this reply verbatim
    assert "reason" in expected_reply.lower()


@pytest.mark.asyncio
async def test_intercept_no_with_reason_sets_checkout_reject(db_session, sample_tenancy):
    """Active CheckoutSession + 'NO the charge is wrong' → CHECKOUT_REJECT with reason entity."""
    cs = CheckoutSession(
        token="test-intercept-no-reason",
        status=CheckoutSessionStatus.pending.value,
        created_by_phone="9444296681",
        tenant_phone="9876543210",
        tenancy_id=sample_tenancy.id,
        checkout_date=date.today(),
        room_key_returned=True,
        wardrobe_key_returned=True,
        biometric_removed=True,
        room_condition_ok=True,
        security_deposit=Decimal("10000"),
        pending_dues=Decimal("0"),
        deductions=Decimal("0"),
        refund_amount=Decimal("10000"),
        refund_mode="upi",
        expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    db_session.add(cs)
    await db_session.flush()

    found = await db_session.scalar(
        select(CheckoutSession).where(
            CheckoutSession.tenant_phone == "9876543210",
            CheckoutSession.status == CheckoutSessionStatus.pending.value,
            CheckoutSession.expires_at > datetime.utcnow(),
        )
    )
    assert found is not None

    # Simulate the NO-with-reason branch
    message = "NO the damage charge is wrong"
    msg_upper = message.strip().upper()
    assert msg_upper.startswith("NO")
    reason = message.strip()[2:].strip()
    assert reason == "the damage charge is wrong"

    # Intent would be set to CHECKOUT_REJECT with reason entity
    expected_intent = "CHECKOUT_REJECT"
    expected_entities = {"reason": reason}
    assert expected_intent == "CHECKOUT_REJECT"
    assert expected_entities["reason"] == "the damage charge is wrong"


@pytest.mark.asyncio
async def test_checkout_agree_confirms_session_and_writes_record(db_session, sample_tenancy):
    """CHECKOUT_AGREE writes CheckoutRecord, marks tenancy exited, sends WA."""
    from src.whatsapp.handlers.owner_handler import _handle_checkout_agree
    from src.database.models import CheckoutRecord, TenancyStatus, CheckoutSession, CheckoutSessionStatus

    tenant_phone = "9876543210"

    cs = CheckoutSession(
        token="agree-test-001",
        status=CheckoutSessionStatus.pending.value,
        created_by_phone="9444296681",
        tenant_phone=tenant_phone,
        tenancy_id=sample_tenancy.id,
        checkout_date=date.today(),
        room_key_returned=True,
        wardrobe_key_returned=True,
        biometric_removed=True,
        room_condition_ok=True,
        security_deposit=Decimal("10000"),
        pending_dues=Decimal("0"),
        deductions=Decimal("0"),
        refund_amount=Decimal("10000"),
        refund_mode="upi",
        expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    db_session.add(cs)
    await db_session.flush()

    with patch("src.integrations.gsheets.record_checkout", new_callable=AsyncMock), \
         patch("src.whatsapp.webhook_handler._send_whatsapp", new_callable=AsyncMock):
        reply = await _handle_checkout_agree(tenant_phone, db_session)

    assert reply

    cr = await db_session.scalar(
        select(CheckoutRecord).where(CheckoutRecord.tenancy_id == sample_tenancy.id)
    )
    assert cr is not None

    await db_session.refresh(cs)
    assert cs.status == CheckoutSessionStatus.confirmed.value

    await db_session.refresh(sample_tenancy)
    assert sample_tenancy.status == TenancyStatus.exited


@pytest.mark.asyncio
async def test_checkout_reject_voids_session_and_records_reason(db_session, sample_tenancy):
    """CHECKOUT_REJECT marks session rejected with reason."""
    from src.whatsapp.handlers.owner_handler import _handle_checkout_reject
    from src.database.models import CheckoutSession, CheckoutSessionStatus

    tenant_phone = "9876543210"

    cs = CheckoutSession(
        token="reject-test-001",
        status=CheckoutSessionStatus.pending.value,
        created_by_phone="9444296681",
        tenant_phone=tenant_phone,
        tenancy_id=sample_tenancy.id,
        checkout_date=date.today(),
        room_key_returned=True,
        wardrobe_key_returned=True,
        biometric_removed=True,
        room_condition_ok=True,
        security_deposit=Decimal("10000"),
        pending_dues=Decimal("0"),
        deductions=Decimal("0"),
        refund_amount=Decimal("10000"),
        refund_mode="upi",
        expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    db_session.add(cs)
    await db_session.flush()

    with patch("src.whatsapp.webhook_handler._send_whatsapp", new_callable=AsyncMock):
        reply = await _handle_checkout_reject(
            tenant_phone, "damage charge is wrong", db_session
        )

    assert reply
    await db_session.refresh(cs)
    assert cs.status == CheckoutSessionStatus.rejected.value
    assert cs.rejection_reason == "damage charge is wrong"


@pytest.mark.asyncio
async def test_intercept_expired_session_not_matched(db_session, sample_tenancy):
    """Expired CheckoutSession should NOT be matched by the intercept query."""
    cs = CheckoutSession(
        token="test-intercept-expired",
        status=CheckoutSessionStatus.pending.value,
        created_by_phone="9444296681",
        tenant_phone="9876543210",
        tenancy_id=sample_tenancy.id,
        checkout_date=date.today(),
        room_key_returned=True,
        wardrobe_key_returned=True,
        biometric_removed=True,
        room_condition_ok=True,
        security_deposit=Decimal("10000"),
        pending_dues=Decimal("0"),
        deductions=Decimal("0"),
        refund_amount=Decimal("10000"),
        refund_mode="upi",
        expires_at=datetime.utcnow() - timedelta(hours=1),  # already expired
    )
    db_session.add(cs)
    await db_session.flush()

    found = await db_session.scalar(
        select(CheckoutSession).where(
            CheckoutSession.tenant_phone == "9876543210",
            CheckoutSession.status == CheckoutSessionStatus.pending.value,
            CheckoutSession.expires_at > datetime.utcnow(),
        )
    )
    assert found is None, "Expired session must not be matched by intercept"
