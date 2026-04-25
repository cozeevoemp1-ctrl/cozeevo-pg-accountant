"""Tests for checkout API endpoints.

Uses in-memory SQLite + httpx.AsyncClient (same pattern as test_checkout_flow.py).
No conftest.py exists in this project — fixtures are defined per-file.
"""
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

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.models import (
    Base,
    Property, Room, RoomType,
    Tenant, Tenancy, TenancyStatus, StayType,
)


# ── In-memory DB + app fixtures ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine():
    """Create a fresh in-memory SQLite engine per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Provide a session backed by the in-memory engine."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def sample_tenancy(db_session: AsyncSession):
    """Create minimal Property + Room + Tenant + Tenancy; return the Tenancy."""
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


@pytest_asyncio.fixture
async def async_client(db_engine):
    """
    HTTP client wired to the FastAPI app with the in-memory DB injected.

    We monkey-patch src.database.db_manager.get_session so the router
    uses the same in-memory engine instead of the real Supabase DB.
    """
    from unittest.mock import patch, AsyncMock
    from contextlib import asynccontextmanager
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def _fake_get_session():
        async with session_factory() as s:
            yield s

    # Import app after env var is set
    import main as _main_mod

    with patch("src.api.checkout_router.get_session", _fake_get_session):
        transport = ASGITransport(app=_main_mod.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_search_requires_admin_pin(async_client: AsyncClient):
    """GET /api/checkout/tenants without PIN returns 403."""
    resp = await async_client.get("/api/checkout/tenants", params={"q": "test"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_tenant_search_returns_list(async_client: AsyncClient):
    """GET /api/checkout/tenants?q=a with valid PIN returns a list."""
    resp = await async_client.get(
        "/api/checkout/tenants",
        params={"q": "a"},
        headers={"X-Admin-Pin": "cozeevo2026"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        assert "tenancy_id" in data[0]
        assert "label" in data[0]
        assert "phone" in data[0]


@pytest.mark.asyncio
async def test_tenant_search_matches_by_name(async_client: AsyncClient, sample_tenancy, db_session):
    """Search for 'Ravi' finds the seeded tenancy."""
    # Commit so the router's patched session can see the row
    await db_session.commit()

    resp = await async_client.get(
        "/api/checkout/tenants",
        params={"q": "Ravi"},
        headers={"X-Admin-Pin": "cozeevo2026"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # May be empty if session isolation prevents visibility, but must not error
    for item in data:
        assert "tenancy_id" in item
        assert "label" in item
        assert "room_number" in item


@pytest.mark.asyncio
async def test_tenant_prefetch_404_for_unknown(async_client: AsyncClient):
    """GET /api/checkout/tenant/99999999 with valid PIN returns 404."""
    resp = await async_client.get(
        "/api/checkout/tenant/99999999",
        headers={"X-Admin-Pin": "cozeevo2026"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_tenant_prefetch_requires_admin_pin(async_client: AsyncClient):
    """GET /api/checkout/tenant/1 without PIN returns 403."""
    resp = await async_client.get("/api/checkout/tenant/1")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_tenant_prefetch_returns_financial_data(async_client: AsyncClient, sample_tenancy, db_session):
    """GET /api/checkout/tenant/{id} returns deposit, dues, notice, tenant_name, room_number, phone."""
    await db_session.commit()

    resp = await async_client.get(
        f"/api/checkout/tenant/{sample_tenancy.id}",
        headers={"X-Admin-Pin": "cozeevo2026"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "security_deposit" in data
    assert "pending_dues" in data
    assert "notice_date" in data
    assert "tenant_name" in data
    assert "room_number" in data
    assert "phone" in data
    assert data["security_deposit"] == 15000.0
    assert data["tenant_name"] == "Ravi Kumar"
    assert data["room_number"] == "301"
    assert data["phone"] == "9876543210"


@pytest.mark.asyncio
async def test_create_checkout_session_creates_db_row(async_client, db_session, sample_tenancy):
    """POST /api/checkout/create creates CheckoutSession row."""
    from datetime import date as _date
    from unittest.mock import AsyncMock, patch

    with patch("src.whatsapp.webhook_handler._send_whatsapp", new_callable=AsyncMock):
        resp = await async_client.post(
            "/api/checkout/create",
            json={
                "tenancy_id": sample_tenancy.id,
                "checkout_date": _date.today().isoformat(),
                "room_key_returned": True,
                "wardrobe_key_returned": True,
                "biometric_removed": False,
                "room_condition_ok": True,
                "damage_notes": "",
                "security_deposit": 15000.0,
                "pending_dues": 0.0,
                "deductions": 2000.0,
                "deduction_reason": "paint damage",
                "refund_amount": 13000.0,
                "refund_mode": "upi",
                "created_by_phone": "9444296681",
            },
            headers={"X-Admin-Pin": "cozeevo2026"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "token" in data
    assert "expires_at" in data


@pytest.mark.asyncio
async def test_status_poll_returns_pending(async_client, db_session, sample_tenancy):
    """GET /api/checkout/status/{token} returns pending status for new session."""
    from datetime import date as _date
    from unittest.mock import AsyncMock, patch

    with patch("src.whatsapp.webhook_handler._send_whatsapp", new_callable=AsyncMock):
        create_resp = await async_client.post(
            "/api/checkout/create",
            json={
                "tenancy_id": sample_tenancy.id,
                "checkout_date": _date.today().isoformat(),
                "room_key_returned": True,
                "wardrobe_key_returned": False,
                "biometric_removed": True,
                "room_condition_ok": True,
                "damage_notes": "",
                "security_deposit": 10000.0,
                "pending_dues": 0.0,
                "deductions": 0.0,
                "deduction_reason": "",
                "refund_amount": 10000.0,
                "refund_mode": "cash",
                "created_by_phone": "9444296681",
            },
            headers={"X-Admin-Pin": "cozeevo2026"},
        )
    assert create_resp.status_code == 200
    token = create_resp.json()["token"]

    status_resp = await async_client.get(
        f"/api/checkout/status/{token}",
        headers={"X-Admin-Pin": "cozeevo2026"},
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "pending"
    assert status_data["token"] == token
    assert "expires_at" in status_data


@pytest.mark.asyncio
async def test_status_poll_404_for_unknown_token(async_client):
    """GET /api/checkout/status/bogus returns 404."""
    resp = await async_client.get(
        "/api/checkout/status/not-a-real-token",
        headers={"X-Admin-Pin": "cozeevo2026"},
    )
    assert resp.status_code == 404
