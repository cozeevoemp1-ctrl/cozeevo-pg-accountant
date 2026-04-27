"""
src/services/reporting.py
=========================
Collection reporting — per REPORTING.md §4.2.

Total Collection = rent_collected + maintenance_collected only.
Deposits and booking advances are tracked but NOT counted in Total Collection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Payment,
    PaymentFor,
    RentSchedule,
    RentStatus,
    Tenancy,
    TenancyStatus,
)


@dataclass
class CollectionSummary:
    period_month: str
    expected: int
    collected: int
    pending: int
    collection_pct: int
    rent_collected: int
    maintenance_collected: int
    deposits_received: int
    booking_advances: int
    overdue_count: int


async def collection_summary(
    *,
    period_month: str,
    session: AsyncSession,
) -> CollectionSummary:
    """Compute collection summary for a given month.

    Args:
        period_month: Month as 'YYYY-MM'.
        session:      SQLAlchemy async session.
    """
    raw = period_month.strip()
    if len(raw) == 7:
        raw = raw + "-01"
    from_date = date.fromisoformat(raw).replace(day=1)

    # ── Expected = sum of all rent_schedule rows for this month (active tenants) ──
    expected_raw = await session.scalar(
        select(
            func.sum(
                RentSchedule.rent_due
                + RentSchedule.maintenance_due
                + RentSchedule.adjustment
            )
        )
        .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
        .where(
            RentSchedule.period_month == from_date,
            Tenancy.status == TenancyStatus.active,
        )
    )
    expected = int(expected_raw or 0)

    # ── Collected amounts by for_type ──────────────────────────────────────────
    collected_rows = (
        await session.execute(
            select(
                Payment.for_type,
                func.sum(Payment.amount).label("total"),
            )
            .join(Tenancy, Tenancy.id == Payment.tenancy_id)
            .where(
                Payment.period_month == from_date,
                Payment.is_void == False,
            )
            .group_by(Payment.for_type)
        )
    ).all()

    breakdown: dict[str, int] = {}
    for row in collected_rows:
        key = row.for_type.value if hasattr(row.for_type, "value") else str(row.for_type)
        breakdown[key] = int(row.total or 0)

    rent_collected = breakdown.get("rent", 0)
    maintenance_collected = breakdown.get("maintenance", 0)
    deposits_received = breakdown.get("deposit", 0)
    booking_advances = breakdown.get("booking", 0)
    collected = rent_collected + maintenance_collected

    pending = max(expected - collected, 0)
    collection_pct = round(collected / expected * 100) if expected > 0 else 0

    # ── Overdue count — tenants with partial/pending rent for THIS month ───────
    overdue_count = int(
        await session.scalar(
            select(func.count(RentSchedule.id))
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .where(
                RentSchedule.period_month == from_date,
                RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                Tenancy.status == TenancyStatus.active,
            )
        )
        or 0
    )

    return CollectionSummary(
        period_month=period_month,
        expected=expected,
        collected=collected,
        pending=pending,
        collection_pct=collection_pct,
        rent_collected=rent_collected,
        maintenance_collected=maintenance_collected,
        deposits_received=deposits_received,
        booking_advances=booking_advances,
        overdue_count=overdue_count,
    )
