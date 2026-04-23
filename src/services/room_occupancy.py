"""Single source of truth for room-occupancy questions.

A bed in Cozeevo can be occupied by EITHER a long-term `Tenancy` OR a
short-stay `DaywiseStay`. Before this module existed, every caller
rolled its own query and many forgot DaywiseStay, causing a whole class
of "room looks vacant but has a guest sleeping in it" bugs.

All callers that need to ask:

    * "Who is in this room?"
    * "Is this room free to book on date X?"
    * "How many beds are occupied right now across the property?"

MUST use the helpers in this file. Do not reimplement these queries
inline. If you find you need a new question answered, add it here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    DaywiseStay,
    Room,
    Staff,
    Tenancy,
    TenancyStatus,
    Tenant,
)


@dataclass
class RoomOccupants:
    """Result of `get_room_occupants`.

    `tenancies` are (Tenant, Tenancy) pairs for long-term residents.
    `daywise` are DaywiseStay rows for guests sleeping in the room today.
    `total_occupied` counts humans, not beds (premium stays count as
    max_occupancy since one person reserves all beds).
    """
    tenancies: list[tuple[Tenant, Tenancy]]
    daywise: list[DaywiseStay]

    @property
    def total_occupied(self) -> int:
        return len(self.tenancies) + len(self.daywise)


async def get_room_occupants(
    session: AsyncSession,
    room: Room,
    on_date: Optional[_date] = None,
) -> RoomOccupants:
    """Return every occupant of `room` on `on_date` (defaults to today).

    Includes active long-term tenancies (checked in, not yet checked out)
    and day-stays where `checkin_date <= on_date < checkout_date` and
    status is not EXIT/CANCELLED.
    """
    when = on_date or _date.today()
    rows = (await session.execute(
        select(Tenant, Tenancy)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .where(
            Tenancy.room_id == room.id,
            Tenancy.status == TenancyStatus.active,
        )
    )).all()
    tenancies = [(t, tc) for t, tc in rows]

    dw = (await session.execute(
        select(DaywiseStay).where(
            DaywiseStay.room_number == room.room_number,
            DaywiseStay.checkin_date <= when,
            DaywiseStay.checkout_date > when,
            DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
        )
    )).scalars().all()

    return RoomOccupants(tenancies=tenancies, daywise=list(dw))


async def find_overlap_conflict(
    session: AsyncSession,
    room_id: int,
    start_date: _date,
    end_date: Optional[_date],
    exclude_tenancy_id: Optional[int] = None,
) -> Optional[str]:
    """Return the conflicting occupant's name if `room_id` is booked during
    [start_date, end_date], else None.

    Checks BOTH long-term tenancies AND day-stays. Used before a new
    check-in or transfer to guarantee we don't double-book a bed.
    """
    far_future = _date(9999, 12, 31)
    period_end = end_date or far_future

    # Long-term overlap
    q = (
        select(Tenant.name, Tenancy.checkin_date, Tenancy.checkout_date)
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .where(
            Tenancy.room_id == room_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    if exclude_tenancy_id:
        q = q.where(Tenancy.id != exclude_tenancy_id)
    for name, checkin, checkout in (await session.execute(q)).all():
        existing_end = checkout or far_future
        if start_date < existing_end and period_end > checkin:
            return name

    # Day-stay overlap — match by room_number since DaywiseStay isn't
    # wired to Room by FK in the current schema.
    room_num = (await session.execute(
        select(Room.room_number).where(Room.id == room_id)
    )).scalar_one_or_none()
    if room_num:
        dw_rows = (await session.execute(
            select(DaywiseStay.guest_name, DaywiseStay.checkin_date, DaywiseStay.checkout_date)
            .where(
                DaywiseStay.room_number == room_num,
                DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
            )
        )).all()
        for name, chk, out in dw_rows:
            existing_end = out or far_future
            if start_date < existing_end and period_end > chk:
                return f"{name} (day-stay)"

    return None


async def check_room_bookable(
    session: AsyncSession,
    room_number: str,
    start_date: _date,
    end_date: Optional[_date],
    property_id: Optional[int] = None,
    exclude_tenancy_id: Optional[int] = None,
) -> tuple[Optional[Room], Optional[str]]:
    """Gate-keeper for every new booking (long-term or day-wise).

    Returns (room, error_message). If error_message is set, refuse the
    booking and surface the message to the caller. Checks, in order:

      1. Room exists in master data (room_number matches a Room row)
      2. Room is marked active
      3. Room is not a staff room (Room.is_staff_room) AND no active
         Staff is assigned to it — if even one staff sleeps here, the
         whole room is off-limits for bookings.
      4. No overlap conflict with any existing tenancy/day-stay.

    Callers MUST use this helper; do not reimplement these checks inline.
    """
    rn = (room_number or "").strip()
    if not rn:
        return None, "Room number is empty."

    q = select(Room).where(Room.room_number == rn)
    if property_id is not None:
        q = q.where(Room.property_id == property_id)
    room = (await session.execute(q)).scalars().first()
    if room is None:
        return None, f"Room '{rn}' is not in master data — booking refused."

    if not bool(room.active):
        return room, f"Room {rn} is marked inactive — booking refused."

    if bool(room.is_staff_room):
        return room, f"Room {rn} is a staff room — tenant/guest bookings not allowed."

    # If ANY active staff is assigned to this room, the whole room is
    # blocked (one staff bed => entire room reserved).
    staff_here = (await session.execute(
        select(Staff.name).where(
            Staff.room_id == room.id,
            Staff.active == True,
            Staff.exit_date.is_(None),
        )
    )).scalars().first()
    if staff_here:
        return room, f"Room {rn} has staff member '{staff_here}' — whole room blocked for bookings."

    conflict = await find_overlap_conflict(
        session, room.id, start_date, end_date, exclude_tenancy_id=exclude_tenancy_id
    )
    if conflict:
        return room, f"Room {rn} already has an overlapping booking: {conflict}."

    return room, None


async def count_occupied_beds(
    session: AsyncSession,
    from_date: _date,
    to_date: _date,
) -> int:
    """Count occupied beds across all non-staff rooms in [from_date, to_date].

    Long-term premium tenancy counts max_occupancy (single occupant holds
    all beds); regular counts 1 bed per tenant. Day-stays count 1 each.
    Used by the monthly dashboard so the occupancy KPI reflects reality.
    """
    from sqlalchemy import case, literal_column

    lt = await session.scalar(
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
            Tenancy.checkin_date <= to_date,
            or_(
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                Tenancy.checkout_date >= from_date,
            ),
        )
    ) or 0

    dw = await session.scalar(
        select(func.count())
        .select_from(DaywiseStay)
        .join(Room, Room.room_number == DaywiseStay.room_number)
        .where(
            Room.is_staff_room == False,
            DaywiseStay.checkin_date <= to_date,
            DaywiseStay.checkout_date >= from_date,
            DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
        )
    ) or 0

    return int(lt) + int(dw)
