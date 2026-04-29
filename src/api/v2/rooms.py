"""GET /api/v2/app/rooms/check?room=XXX — availability check for room transfer."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Room
from src.services.room_occupancy import get_room_occupants
from sqlalchemy import select

router = APIRouter()


@router.get("/rooms/check")
async def check_room_availability(
    room: str = Query(..., description="Room number to check"),
    _user: AppUser = Depends(get_current_user),
):
    """Check if a room exists and has free beds. Used by Transfer Room panel."""
    room_number = room.upper().strip()

    async with get_session() as session:
        db_room = await session.scalar(
            select(Room).where(Room.room_number == room_number, Room.active == True)
        )
        if not db_room:
            raise HTTPException(status_code=404, detail=f"Room {room_number} not found")

        if db_room.is_staff_room:
            raise HTTPException(status_code=400, detail=f"Room {room_number} is a staff room")

        occupants = await get_room_occupants(session, db_room)

    max_occ = int(db_room.max_occupancy or 1)
    free_beds = max(max_occ - occupants.total_occupied, 0)

    return {
        "room_number": room_number,
        "max_occupancy": max_occ,
        "free_beds": free_beds,
        "is_available": free_beds > 0,
        "occupants": [{"name": t.name, "tenancy_id": tc.id} for t, tc in occupants.tenancies],
    }
