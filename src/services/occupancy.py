"""Canonical occupancy calculations — single source of truth for all endpoints."""
from datetime import date
from sqlalchemy import case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Room, Tenancy, TenancyStatus


async def get_total_revenue_beds(session: AsyncSession) -> int:
    """Total revenue beds (exclude staff rooms and placeholder room 000)."""
    total = await session.scalar(
        select(func.coalesce(func.sum(Room.max_occupancy), 0))
        .where(Room.is_staff_room == False, Room.room_number != "000")
    )
    return int(total or 0)


async def get_occupied_beds(session: AsyncSession, target_date: date) -> int:
    """Occupied beds on target_date: active + no_show (checkin_date <= target_date).

    Per-room sum capped at max_occupancy so overcrowded rooms don't inflate vacant count.
    Premium tenants count as max_occupancy beds; others count as 1.
    """
    # Active tenancies
    per_room_active = (
        select(
            func.least(
                func.sum(
                    case(
                        (Tenancy.sharing_type == "premium", Room.max_occupancy),
                        else_=literal_column("1"),
                    )
                ),
                Room.max_occupancy,
            ).label("capped")
        )
        .select_from(Tenancy)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Room.is_staff_room == False,
            Room.room_number != "000",
            Tenancy.status == TenancyStatus.active,
        )
        .group_by(Room.id, Room.max_occupancy)
        .subquery()
    )
    active_beds = int(
        await session.scalar(select(func.coalesce(func.sum(per_room_active.c.capped), 0))) or 0
    )

    # No-show tenancies with checkin_date <= target_date
    noshow_beds = int(
        await session.scalar(
            select(func.coalesce(func.sum(
                case(
                    (Tenancy.sharing_type == "premium", Room.max_occupancy),
                    else_=literal_column("1"),
                )
            ), 0))
            .select_from(Tenancy)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.status == TenancyStatus.no_show,
                Tenancy.checkin_date <= target_date,
            )
        ) or 0
    )

    return active_beds + noshow_beds


async def get_occupancy_pct(session: AsyncSession, target_date: date) -> float:
    """Occupancy percentage on target_date (0-100)."""
    total_beds = await get_total_revenue_beds(session)
    occupied = await get_occupied_beds(session, target_date)
    if total_beds == 0:
        return 0.0
    return round(occupied / total_beds * 100, 1)
