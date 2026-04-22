"""Unified occupant-query framework.

An occupant is anyone sleeping in a Cozeevo bed — long-term (`Tenancy`)
OR short-stay (`DaywiseStay`). Every caller that asks:

    * who is in this room?
    * who has phone X?
    * when does occupant Y leave?
    * update the notes on this occupant

MUST use the functions in this module. That way new callers don't need
to worry about which table to query, and we can't accidentally miss
day-stays again (the bug pattern fixed 2026-04-22).

If you need a new occupant question answered, add it HERE, not in the
handler.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal
from typing import Literal, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    DaywiseStay,
    Room,
    Tenancy,
    TenancyStatus,
    Tenant,
)


Kind = Literal["tenancy", "daystay"]


@dataclass
class Occupant:
    """Type-agnostic view over a long-term tenancy or a day-stay.

    `raw` exposes the underlying ORM row for callers that need fields
    not hoisted up here (e.g. lock_in_months, booking_amount).
    """
    kind: Kind
    id: int
    name: str
    phone: Optional[str]
    room_id: Optional[int]           # NULL for day-stays (DaywiseStay has no FK)
    room_number: str
    checkin_date: _date
    checkout_date: Optional[_date]   # actual exit date if past; else expected for tenancy
    expected_checkout: Optional[_date]
    notice_date: Optional[_date]
    rate: Decimal                    # agreed_rent for tenancy, daily_rate for day-stay
    rate_unit: Literal["month", "day"]
    security_deposit: Decimal
    notes: Optional[str]
    status: str
    raw: object = field(repr=False)

    @property
    def display(self) -> str:
        tag = "" if self.kind == "tenancy" else " (day-stay)"
        return f"{self.name}{tag}"

    def effective_checkout(self) -> Optional[_date]:
        """Best available exit date: actual > expected > notice + convention."""
        return self.checkout_date or self.expected_checkout


def _norm_phone(p: Optional[str]) -> str:
    return re.sub(r"\D", "", p or "")


def _tenancy_to_occupant(tc: Tenancy, tenant: Tenant, room: Room) -> Occupant:
    return Occupant(
        kind="tenancy",
        id=tc.id,
        name=tenant.name,
        phone=tenant.phone,
        room_id=room.id if room else None,
        room_number=room.room_number if room else "",
        checkin_date=tc.checkin_date,
        checkout_date=tc.checkout_date,
        expected_checkout=tc.expected_checkout,
        notice_date=tc.notice_date,
        rate=Decimal(str(tc.agreed_rent or 0)),
        rate_unit="month",
        security_deposit=Decimal(str(tc.security_deposit or 0)),
        notes=tc.notes,
        status=tc.status.value if hasattr(tc.status, "value") else str(tc.status),
        raw=tc,
    )


def _daystay_to_occupant(d: DaywiseStay) -> Occupant:
    return Occupant(
        kind="daystay",
        id=d.id,
        name=d.guest_name,
        phone=d.phone,
        room_id=None,
        room_number=d.room_number,
        checkin_date=d.checkin_date,
        checkout_date=d.checkout_date,
        expected_checkout=d.checkout_date,
        notice_date=None,
        rate=Decimal(str(d.daily_rate or 0)),
        rate_unit="day",
        security_deposit=Decimal("0"),
        notes=d.comments,
        status=(d.status or "").upper(),
    raw=d,
    )


async def find_occupants(
    session: AsyncSession,
    *,
    room: Optional[str] = None,
    room_id: Optional[int] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    active_only: bool = True,
    on_date: Optional[_date] = None,
) -> list[Occupant]:
    """Return every occupant matching the given filter(s), BOTH long-term
    and day-stay.

    - `room` matches room_number (substring, case-insensitive).
    - `room_id` matches exact Room.id.
    - `phone` normalises digits and matches last-10 suffix on both tables.
    - `name` is case-insensitive substring match.
    - `active_only=True` means:
        * tenancies with status=active
        * day-stays where on_date ∈ [checkin, checkout) and status not EXIT/CANCELLED
      (on_date defaults to today)
    - `active_only=False` includes exited/no-show/cancelled.
    """
    when = on_date or _date.today()
    phone_key = _norm_phone(phone)[-10:] if phone else None

    # ── Long-term tenancies ──
    q = (
        select(Tenant, Tenancy, Room)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
    )
    if active_only:
        q = q.where(Tenancy.status == TenancyStatus.active)
    if room_id is not None:
        q = q.where(Room.id == room_id)
    if room:
        q = q.where(Room.room_number.ilike(f"%{room}%"))
    if phone_key:
        q = q.where(Tenant.phone.ilike(f"%{phone_key}"))
    if name:
        q = q.where(Tenant.name.ilike(f"%{name}%"))
    tc_rows = (await session.execute(q)).all()
    occupants = [_tenancy_to_occupant(tc, t, rm) for t, tc, rm in tc_rows]

    # ── Day-stays ──
    dq = select(DaywiseStay)
    if active_only:
        dq = dq.where(
            DaywiseStay.checkin_date <= when,
            DaywiseStay.checkout_date > when,
            DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
        )
    if room_id is not None:
        rm_num = (await session.execute(
            select(Room.room_number).where(Room.id == room_id)
        )).scalar_one_or_none()
        if rm_num:
            dq = dq.where(DaywiseStay.room_number == rm_num)
        else:
            dq = dq.where(DaywiseStay.id == -1)  # no match
    if room:
        dq = dq.where(DaywiseStay.room_number.ilike(f"%{room}%"))
    if phone_key:
        dq = dq.where(DaywiseStay.phone.ilike(f"%{phone_key}"))
    if name:
        dq = dq.where(DaywiseStay.guest_name.ilike(f"%{name}%"))
    dw_rows = (await session.execute(dq)).scalars().all()
    occupants.extend(_daystay_to_occupant(d) for d in dw_rows)

    return occupants


async def update_notes(
    session: AsyncSession,
    occupant: Occupant,
    text: Optional[str],
) -> None:
    """Set (or clear with None/"") the notes on the underlying row.

    Writes to `Tenancy.notes` for long-term, `DaywiseStay.comments` for
    day-stays. Caller must commit the session.
    """
    new = (text or "").strip() or None
    if occupant.kind == "tenancy":
        tc = occupant.raw  # type: Tenancy  # type: ignore[assignment]
        tc.notes = new
    else:
        d = occupant.raw  # type: DaywiseStay  # type: ignore[assignment]
        d.comments = new
    occupant.notes = new


def checkout_of(occupant: Occupant) -> Optional[_date]:
    """Preferred exit date to show to users.

    Order: actual checkout_date (already left) > expected_checkout
    (long-term planned exit) > None. Day-stays always have a checkout.
    """
    return occupant.checkout_date or occupant.expected_checkout


async def search_any(
    session: AsyncSession,
    query: str,
    *,
    active_only: bool = True,
) -> list[Occupant]:
    """Free-text search: auto-pick name / phone / room based on what the
    query looks like.

    - All digits, 10+ chars → phone
    - Starts with G or is short numeric room (e.g. "G09", "609") → room
    - Else → name substring
    """
    q = (query or "").strip()
    if not q:
        return []
    digits = _norm_phone(q)
    if len(digits) >= 10:
        return await find_occupants(session, phone=digits, active_only=active_only)
    if re.fullmatch(r"[Gg]?\d{2,4}[A-Za-z]?", q):
        return await find_occupants(session, room=q, active_only=active_only)
    return await find_occupants(session, name=q, active_only=active_only)
