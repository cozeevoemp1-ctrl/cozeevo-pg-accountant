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
    Tenancy,
    Tenant,
)
from src.services.room_occupancy import get_room_occupants


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

    # 1. Lookup destination room
    new_room = await session.scalar(
        select(Room).where(Room.room_number == to_room_number, Room.active == True)
    )
    if not new_room:
        return {"success": False, "message": f"Room {to_room_number} not found."}

    if new_room.is_staff_room:
        return {"success": False, "message": f"Room {to_room_number} is a staff room — tenant bookings not allowed."}

    # 2. Load tenancy + tenant + current room
    row = (await session.execute(
        select(Tenancy, Tenant, Room)
        .join(Tenant, Tenancy.tenant_id == Tenant.id)
        .join(Room, Tenancy.room_id == Room.id)
        .where(Tenancy.id == tenancy_id)
    )).first()
    if not row:
        return {"success": False, "message": "Tenancy not found."}
    tenancy, tenant, current_room = row
    from_room = current_room.room_number
    tenant_name = tenant.name

    if from_room == to_room_number:
        return {"success": False, "message": f"Tenant is already in room {to_room_number}."}

    # 3. Occupancy check using canonical helper
    today = date.today()
    occupants = await get_room_occupants(session, new_room)
    max_occ = int(new_room.max_occupancy or 1)
    if occupants.total_occupied >= max_occ:
        names = ", ".join(t.name for t, _ in occupants.tenancies)
        return {
            "success": False,
            "message": f"Room {to_room_number} is full ({occupants.total_occupied}/{max_occ} beds): {names}",
        }

    # 4. Resolve rent — keep current if new_rent not supplied
    old_rent = float(tenancy.agreed_rent or 0)
    resolved_rent = float(new_rent) if new_rent is not None else old_rent
    rent_changed = resolved_rent != old_rent

    # 5. DB writes (all within the passed session — caller commits)
    tenancy.room_id = new_room.id
    tenancy.agreed_rent = Decimal(str(resolved_rent))

    if rent_changed:
        session.add(RentRevision(
            tenancy_id=tenancy_id,
            old_rent=Decimal(str(old_rent)),
            new_rent=Decimal(str(resolved_rent)),
            effective_date=today,
            changed_by=changed_by,
            reason=f"Room transfer: {from_room} → {to_room_number}",
        ))

    # Always update current month RS on room transfer — prorate by remaining days
    import calendar as _cal
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
            # First month: keep whatever proration was set at checkin; just update rent cap
            rs.rent_due = min(rs.rent_due, Decimal(str(resolved_rent)))
        else:
            dim = _cal.monthrange(today.year, today.month)[1]
            remaining = dim - today.day + 1
            rs.rent_due = Decimal(str(int(resolved_rent * remaining / dim)))

    if extra_deposit and extra_deposit > 0:
        tenancy.security_deposit = (tenancy.security_deposit or Decimal("0")) + Decimal(str(extra_deposit))

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
