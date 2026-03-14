"""
Async database manager for PG Accountant.
Handles engine/session lifecycle for Supabase (PostgreSQL via asyncpg).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional

from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.database.models import (
    Base,
    ExpenseCategory,
    AuthorizedUser,
    Tenant,
    Tenancy,
    RentSchedule,
    Payment,
    RentStatus,
    TenancyStatus,
)


# ── Engine factory ─────────────────────────────────────────────────────────

_engine = None
_session_factory = None


def init_engine(database_url: str, echo: bool = False):
    global _engine, _session_factory
    # Normalise URL scheme for asyncpg
    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("sqlite:///"):
        async_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    else:
        async_url = database_url

    _engine = create_async_engine(async_url, echo=echo, future=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


async def init_db(database_url: str):
    """Create all tables if they don't exist, then seed defaults."""
    engine = init_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")
    await _seed_expense_categories()


# ── Session management ─────────────────────────────────────────────────────

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager — use in scripts and background tasks."""
    if _session_factory is None:
        raise RuntimeError("Call init_db() before using get_session()")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends-compatible async generator for route handlers."""
    if _session_factory is None:
        raise RuntimeError("Call init_db() before using get_db_session()")
    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ── Seeding ────────────────────────────────────────────────────────────────

async def _seed_expense_categories():
    """Seed default expense categories if they don't exist yet."""
    defaults = [
        "Electricity", "Water", "Internet", "Groceries",
        "Maintenance & Repair", "Cleaning Supplies", "Salary",
        "Food & Beverages", "Transport", "Taxes & Fees", "Miscellaneous",
    ]
    async with get_session() as session:
        for name in defaults:
            existing = await session.scalar(
                select(ExpenseCategory).where(ExpenseCategory.name == name)
            )
            if not existing:
                session.add(ExpenseCategory(name=name))
    logger.info("Expense categories seeded.")


# ── Tenant lookups ─────────────────────────────────────────────────────────

async def get_tenant_by_phone(phone: str) -> Optional[Tenant]:
    async with get_session() as session:
        return await session.scalar(select(Tenant).where(Tenant.phone == phone))


async def get_active_tenancy(tenant_id: int) -> Optional[Tenancy]:
    async with get_session() as session:
        return await session.scalar(
            select(Tenancy).where(
                and_(
                    Tenancy.tenant_id == tenant_id,
                    Tenancy.status == TenancyStatus.active,
                )
            ).order_by(Tenancy.checkin_date.desc())
        )


async def get_authorized_user(phone: str) -> Optional[AuthorizedUser]:
    async with get_session() as session:
        return await session.scalar(
            select(AuthorizedUser).where(
                and_(
                    AuthorizedUser.phone == phone,
                    AuthorizedUser.active == True,
                )
            )
        )


# ── Rent schedule helpers ──────────────────────────────────────────────────

async def get_pending_rent_schedule(period_month=None) -> list[RentSchedule]:
    """Return all unpaid rent schedule rows for a given month (default: current month)."""
    from datetime import date
    if period_month is None:
        today = date.today()
        period_month = date(today.year, today.month, 1)

    async with get_session() as session:
        result = await session.execute(
            select(RentSchedule).where(
                and_(
                    RentSchedule.period_month == period_month,
                    RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                )
            )
        )
        return result.scalars().all()


async def get_rent_schedule_for_tenancy(tenancy_id: int) -> list[RentSchedule]:
    async with get_session() as session:
        result = await session.execute(
            select(RentSchedule)
            .where(RentSchedule.tenancy_id == tenancy_id)
            .order_by(RentSchedule.period_month.desc())
        )
        return result.scalars().all()


# ── Payment helpers ────────────────────────────────────────────────────────

async def get_payments_for_tenancy(tenancy_id: int, limit: int = 6) -> list[Payment]:
    async with get_session() as session:
        result = await session.execute(
            select(Payment)
            .where(and_(Payment.tenancy_id == tenancy_id, Payment.is_void == False))
            .order_by(Payment.payment_date.desc())
            .limit(limit)
        )
        return result.scalars().all()


async def upsert_transaction(txn_data: dict) -> tuple:
    """
    Legacy stub — kept for ingest pipeline compatibility.
    In the new schema, payments are logged via the WhatsApp bot or import scripts.
    Returns a dummy (object, is_new) tuple to avoid breaking callers.
    """
    logger.warning("upsert_transaction called — new schema uses payments table directly.")
    return None, False


async def get_category_by_name(name: str) -> Optional[ExpenseCategory]:
    async with get_session() as session:
        return await session.scalar(
            select(ExpenseCategory).where(ExpenseCategory.name == name)
        )


# ── Pending entities (legacy stubs) ───────────────────────────────────────
# The new schema has no pending_entities table.
# These stubs keep main.py entity_router from crashing.

async def get_pending_entities(entity_type: Optional[str] = None) -> list:
    """No pending_entities table in new schema — returns empty list."""
    return []


async def approve_pending_entity(pending_id: int) -> Optional[dict]:
    """No pending_entities table in new schema."""
    return None


async def reject_pending_entity(pending_id: int):
    """No pending_entities table in new schema."""
    pass
