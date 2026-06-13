#!/usr/bin/env python
import asyncio
import os
from datetime import date
from dotenv import load_dotenv
from src.database.db_manager import init_engine, get_session
from src.database.models import Tenancy, Room, TenancyStatus
from sqlalchemy import select

load_dotenv()
db_url = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("DATABASE_URL")

async def check_room_208():
    if not db_url:
        print("No database URL found")
        return
    init_engine(db_url)
    async with get_session() as session:
        result = await session.execute(
            select(Tenancy, Room.room_number)
            .join(Room)
            .where(Room.room_number == '208')
            .order_by(Tenancy.created_at.desc())
            .limit(5)
        )
        rows = result.all()
        if not rows:
            print("No tenancies found for room 208")
            return

        today = date.today().isoformat()
        for tenancy, room_num in rows:
            checkin = tenancy.checkin_date.isoformat() if tenancy.checkin_date else "None"
            status = tenancy.status.value if hasattr(tenancy.status, 'value') else str(tenancy.status)
            entered_by = tenancy.entered_by or "unknown"
            created = tenancy.created_at.isoformat() if tenancy.created_at else "unknown"
            is_past = "[AUTO-CHECKIN]" if tenancy.checkin_date and tenancy.checkin_date <= date.today() else ""
            print(f"Status: {status:12} | Checkin: {checkin} | Today: {today} | {is_past}")
            print(f"  Entered by: {entered_by} | Created: {created}")

asyncio.run(check_room_208())
