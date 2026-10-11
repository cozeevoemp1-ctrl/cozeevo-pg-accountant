"""
Shared room-transfer logic used by both the WhatsApp bot and the PWA API.
Single source of truth — change once, both callers updated.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    AuditLog,
    Room,
    RentRevision,
    RentSchedule,
    SharingType,
    Tenancy,
    Tenant,
)
from src.services.room_occupancy import get_room_occupants


def resolve_sharing_on_room_change(current_sharing, new_room_type):
    """Single source of truth for what a tenancy's sharing_type becomes on a room move.

    Re-derives sharing_type from the destination room's physical type (e.g. a
    triple-room tenant moving into a double becomes "double") — but NEVER clobbers
    an explicit *premium* (whole-room) tenancy. Premium is a tenancy-level choice
    that no room's room_type can ever produce, so a blind "sync to room type"
    silently downgraded whole-room tenants to "double" on every room change,
    causing a phantom free bed and the wrong rent bucket.

    Args:
        current_sharing: the tenancy's current SharingType (enum) or None
        new_room_type:   the destination Room.room_type (enum) or its .value string

    Returns:
        (new_sharing: SharingType | None, changed: bool)
    """
    if current_sharing == SharingType.premium:
        return current_sharing, False
    raw = getattr(new_room_type, "value", new_room_type)
    try:
        new_sharing = SharingType(raw)
    except (ValueError, AttributeError):
        return current_sharing, False
    return new_sharing, new_sharing != current_sharing


async def check_transfer_destination(
    session: AsyncSession,
    tenancy: Tenancy,
    to_room_number: str,
) -> tuple[Room | None, str | None]:
    """Can `tenancy` move into `to_room_number`? Returns (room, error).

    Single capacity gate for every room move (bot prompt, bot confirm, PWA):
    check_room_bookable handles inactive/staff rooms, premium (whole-room)
    occupants, day-stays and overlapping no-show bookings. The bed is needed
    from today — or from the booking's check-in date for a future no-show.
    A premium (whole-room) mover additionally needs the room to itself.
    """
    from src.database.models import SharingType as _ST, TenancyStatus as _TS
    from src.services.room_occupancy import check_room_bookable

    rn = (to_room_number or "").upper().strip()
    today = date.today()
    start = today
    if tenancy.status == _TS.no_show and tenancy.checkin_date and tenancy.checkin_date > today:
        start = tenancy.checkin_date

    room, err = await check_room_bookable(session, rn, start, None, exclude_tenancy_id=tenancy.id)
    if room is None and err:
        return None, f"Room {rn} not found."
    if room is not None and room.id == tenancy.room_id:
        return room, f"Tenant is already in room {room.room_number}."

    occupants = await get_room_occupants(session, room, start) if room is not None else None
    others = [t.name for t, tc in (occupants.tenancies if occupants else []) if tc.id != tenancy.id]
    others += [tc.tenant.name for tc in (occupants.daywise if occupants else [])
               if tc.id != tenancy.id and tc.tenant and tc.tenant.name not in others]
    max_occ = int(room.max_occupancy or 1) if room is not None else 1

    if err:
        if "overlapping booking" in err:
            names = ", ".join(others) if others else err.split(":", 1)[-1].strip(" .")
            return room, f"Room {room.room_number} is full ({max_occ} beds): {names}"
        return room, err
    if tenancy.sharing_type == _ST.premium and others:
        return room, (f"Room {room.room_number} has other occupants ({', '.join(others)}) — "
                      "a premium tenant needs the whole room.")
    return room, None


async def execute_room_transfer(
    tenancy_id: int,
    to_room_number: str,
    new_rent: float | None,
    extra_deposit: float,
    changed_by: str,
    source: str,
    session: AsyncSession,
) -> dict:
    """
    Transfer a tenant to a new room.

    Returns:
        { success: bool, message: str, from_room?, to_room?, new_rent?, extra_deposit? }

    Never raises — errors returned as success=False dict so callers can display inline.
    """
    to_room_number = to_room_number.upper().strip()

    # 1. Load tenancy + tenant + current room (room may be unassigned for a booking)
    row = (await session.execute(
        select(Tenancy, Tenant, Room)
        .join(Tenant, Tenancy.tenant_id == Tenant.id)
        .join(Room, Tenancy.room_id == Room.id, isouter=True)
        .where(Tenancy.id == tenancy_id)
    )).first()
    if not row:
        return {"success": False, "message": "Tenancy not found."}
    tenancy, tenant, current_room = row
    from_room = current_room.room_number if current_room else "unassigned"
    tenant_name = tenant.name

    # 2-3. Destination exists, bookable, and has a free bed (premium/day-stay/
    # no-show aware) — the one capacity gate shared with the bot prompt.
    today = date.today()
    new_room, dest_err = await check_transfer_destination(session, tenancy, to_room_number)
    if dest_err:
        return {"success": False, "message": dest_err}

    # 4. Resolve rent — keep current if new_rent not supplied
    old_rent = float(tenancy.agreed_rent or 0)
    resolved_rent = float(new_rent) if new_rent is not None else old_rent
    rent_changed = resolved_rent != old_rent

    # 5. DB writes (all within the passed session — caller commits)
    to_room_number = new_room.room_number
    tenancy.room_id = new_room.id
    tenancy.agreed_rent = Decimal(str(resolved_rent))

    # sharing_type follows the destination's physical type (premium preserved)
    _old_sharing = getattr(tenancy.sharing_type, "value", tenancy.sharing_type)
    _new_sharing, _sharing_changed = resolve_sharing_on_room_change(tenancy.sharing_type, new_room.room_type)
    if _sharing_changed:
        tenancy.sharing_type = _new_sharing
        session.add(AuditLog(
            changed_by=changed_by, entity_type="tenancy", entity_id=tenancy_id,
            entity_name=tenant_name, field="sharing_type",
            old_value=_old_sharing, new_value=_new_sharing.value,
            room_number=to_room_number, source=source,
            note=f"Re-derived from room type on room change {from_room} → {to_room_number}",
            org_id=tenancy.org_id,
        ))

    if rent_changed:
        session.add(RentRevision(
            tenancy_id=tenancy_id,
            old_rent=Decimal(str(old_rent)),
            new_rent=Decimal(str(resolved_rent)),
            effective_date=today,
            changed_by=changed_by,
            reason=f"Room transfer: {from_room} → {to_room_number}",
        ))
        session.add(AuditLog(
            changed_by=changed_by, entity_type="tenancy", entity_id=tenancy_id,
            entity_name=tenant_name, field="agreed_rent",
            old_value=str(int(old_rent)), new_value=str(int(resolved_rent)),
            room_number=to_room_number, source=source,
            note=f"Room transfer: {from_room} → {to_room_number}",
            org_id=tenancy.org_id,
        ))

    # Update current month RS on room transfer — prorate by remaining days.
    # Only for checked-in tenancies: a booking's (no_show) rows are na/0
    # placeholders that activate_rs_on_checkin() fills at check-in.
    import calendar as _cal
    from src.database.models import TenancyStatus as _TS
    rs = None
    if tenancy.status == _TS.active:
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy_id,
                RentSchedule.period_month == today.replace(day=1),
            )
        )
    if rs:
        period = today.replace(day=1)
        is_first_month = tenancy.checkin_date and tenancy.checkin_date.replace(day=1) == period
        if is_first_month:
            # First month: canonical recalc (CLAUDE.md — agreed_rent changed → recalc;
            # the old min() cap dropped the deposit from the first-month due).
            if rent_changed:
                from src.services.rent_schedule import recalc_checkin_month_rs
                await recalc_checkin_month_rs(session, tenancy)
        else:
            dim = _cal.monthrange(today.year, today.month)[1]
            remaining = dim - today.day + 1
            rs.rent_due = Decimal(str(int(resolved_rent * remaining / dim)))

    if extra_deposit and extra_deposit > 0:
        tenancy.security_deposit = (tenancy.security_deposit or Decimal("0")) + Decimal(str(extra_deposit))
        from src.services.rent_schedule import recalc_checkin_month_rs
        await recalc_checkin_month_rs(session, tenancy)

    session.add(AuditLog(
        changed_by=changed_by,
        entity_type="tenancy",
        entity_id=tenancy_id,
        entity_name=tenant_name,
        field="room_id",
        old_value=from_room,
        new_value=to_room_number,
        room_number=to_room_number,
        source=source,
        note=f"Room transfer: {from_room} → {to_room_number}",
        org_id=tenancy.org_id,
    ))

    # 6. Sheet sync — fire-and-forget
    try:
        import asyncio as _aio
        from src.integrations import gsheets as _gs
        _aio.create_task(_gs.update_tenants_tab_field(
            from_room, tenant_name, "room", to_room_number
        ))
        if rent_changed:
            _aio.create_task(_gs.update_tenants_tab_field(
                to_room_number, tenant_name, "agreed_rent", int(resolved_rent)
            ))
        _gs.trigger_monthly_sheet_sync(today.month, today.year)
    except Exception:
        pass

    rent_note = f"\nNew rent: Rs.{int(resolved_rent):,}/mo" if rent_changed else ""
    deposit_note = f"\nDeposit increased by Rs.{int(extra_deposit):,}" if extra_deposit and extra_deposit > 0 else ""

    return {
        "success": True,
        "message": (
            f"Room transferred — {tenant_name}\n"
            f"Room {from_room} → {to_room_number}"
            f"{rent_note}{deposit_note}\n"
            "Sheet update queued"
        ),
        "from_room": from_room,
        "to_room": to_room_number,
        "new_rent": resolved_rent,
        "extra_deposit": float(extra_deposit or 0),
    }
