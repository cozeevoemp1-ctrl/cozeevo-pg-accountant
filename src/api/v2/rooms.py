"""GET /api/v2/app/rooms/check?room=XXX — availability check for room transfer and pre-booking."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Room, Tenancy, TenancyStatus, Tenant
from src.services.room_occupancy import get_room_occupants
from sqlalchemy import select

router = APIRouter()


@router.get("/rooms/check")
async def check_room_availability(
    room: str = Query(..., description="Room number to check"),
    checkin_date: str = Query(None, description="YYYY-MM-DD — if provided, also check beds free on that future date"),
    _user: AppUser = Depends(get_current_user),
):
    """Check if a room exists and has free beds. Pass checkin_date to check future availability."""
    room_number = room.upper().strip()

    checkin: date | None = None
    if checkin_date:
        try:
            checkin = date.fromisoformat(checkin_date)
        except ValueError:
            pass

    async with get_session() as session:
        db_room = await session.scalar(
            select(Room).where(Room.room_number == room_number, Room.active == True)
        )
        if not db_room:
            raise HTTPException(status_code=404, detail=f"Room {room_number} not found")

        if db_room.is_staff_room:
            raise HTTPException(status_code=400, detail=f"Room {room_number} is a staff room")

        occupants = await get_room_occupants(session, db_room)

        beds_free_on_date: int | None = None
        earliest_free_date: str | None = None
        current_tenants: list[dict] = []

        if checkin:
            ten_rows = (await session.execute(
                select(Tenancy.checkout_date, Tenant.name)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .where(Tenancy.room_id == db_room.id, Tenancy.status == TenancyStatus.active)
            )).all()
            max_occ_inner = int(db_room.max_occupancy or 1)
            still_occupied = sum(1 for t in ten_rows if t.checkout_date is None or t.checkout_date >= checkin)
            beds_free_on_date = max(max_occ_inner - still_occupied, 0)
            checkouts = [t.checkout_date for t in ten_rows if t.checkout_date is not None]
            if checkouts:
                earliest_free_date = (min(checkouts) + timedelta(days=1)).isoformat()
            current_tenants = [
                {"name": t.name, "checkout_date": t.checkout_date.isoformat() if t.checkout_date else None}
                for t in ten_rows
            ]

    max_occ = int(db_room.max_occupancy or 1)
    free_beds = max(max_occ - occupants.beds_occupied(max_occ), 0)

    result: dict = {
        "room_number": room_number,
        "max_occupancy": max_occ,
        "free_beds": free_beds,
        "is_available": free_beds > 0,
        "occupants": [{"name": t.name, "tenancy_id": tc.id} for t, tc in occupants.tenancies],
    }
    if checkin:
        result["beds_free_on_date"] = beds_free_on_date
        result["earliest_free_date"] = earliest_free_date
        result["current_tenants"] = current_tenants
    return result
