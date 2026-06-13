#!/usr/bin/env python
import asyncio
import os
from dotenv import load_dotenv
from src.database.db_manager import init_engine, get_session
from src.database.models import Tenancy, Room, OnboardingSession
from sqlalchemy import select

load_dotenv()
db_url = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("DATABASE_URL")

async def check():
    if not db_url:
        print("No database URL")
        return
    init_engine(db_url)
    async with get_session() as session:
        # Check room 208 tenancy
        tenancy = await session.execute(
            select(Tenancy, Room.room_number)
            .join(Room)
            .where(Room.room_number == '208')
            .order_by(Tenancy.created_at.desc())
            .limit(1)
        )
        tenancy_row = tenancy.first()
        if tenancy_row:
            t, room_num = tenancy_row
            print(f"Room 208 Tenancy:")
            print(f"  Status: {t.status.value if hasattr(t.status, 'value') else t.status}")
            print(f"  Checkin: {t.checkin_date}")
            print(f"  Created: {t.created_at}")

            # Check for OnboardingSession linked to room 208
            obs = await session.execute(
                select(OnboardingSession)
                .where(OnboardingSession.tenancy_id == t.id)
                .order_by(OnboardingSession.created_at.desc())
                .limit(1)
            )
            obs_row = obs.first()
            if obs_row:
                o = obs_row[0]
                print(f"\nOnboarding Session for Room 208:")
                print(f"  Status: {o.status}")
                print(f"  Tenant phone: {o.tenant_phone}")
                print(f"  Tenant data filled: {'yes' if o.tenant_data else 'no'}")
            else:
                print("\nNo OnboardingSession linked to this tenancy")

asyncio.run(check())
