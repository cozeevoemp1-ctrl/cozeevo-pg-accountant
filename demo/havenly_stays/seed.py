"""
One-off: seed Havenly Stays sample room/pricing data into DEMO_DATABASE_URL.
Safe to re-run — upserts by room_type.

Usage:
    py -3 -m demo.havenly_stays.seed
"""
from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from demo.havenly_stays.db import get_session, init_db
from demo.havenly_stays.models import Room

TODAY = date.today()

# Double Sharing is fully booked until 1 Sept — deliberately, so the demo's
# "is a room available from September" question has a real, non-trivial answer.
ROOMS = [
    {"room_type": "Single", "price_monthly": 12000, "total_beds": 10, "available_beds": 3, "available_from": TODAY},
    {"room_type": "Double Sharing", "price_monthly": 8500, "total_beds": 20, "available_beds": 4, "available_from": date(TODAY.year if TODAY.month <= 9 else TODAY.year + 1, 9, 1)},
    {"room_type": "Triple Sharing", "price_monthly": 6500, "total_beds": 15, "available_beds": 5, "available_from": TODAY},
]


async def seed():
    await init_db()
    async with get_session() as session:
        for data in ROOMS:
            existing = await session.scalar(select(Room).where(Room.room_type == data["room_type"]))
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
            else:
                session.add(Room(**data))
    print(f"Seeded {len(ROOMS)} Havenly Stays room types.")


if __name__ == "__main__":
    asyncio.run(seed())
