#!/usr/bin/env python
import asyncio
import os
from dotenv import load_dotenv
from src.database.db_manager import init_engine, get_session
from src.database.models import OnboardingSession
from sqlalchemy import select

load_dotenv()
db_url = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("DATABASE_URL")

async def check():
    if not db_url:
        print("No database URL")
        return
    init_engine(db_url)
    async with get_session() as session:
        obs = await session.execute(
            select(OnboardingSession)
            .where(OnboardingSession.tenant_phone == '8905115739')
            .order_by(OnboardingSession.created_at.desc())
            .limit(1)
        )
        obs_row = obs.first()
        if obs_row:
            o = obs_row[0]
            print(f"Room 208 OnboardingSession:")
            print(f"  stay_type: {o.stay_type}")
            print(f"  agreed_rent: {o.agreed_rent}")
            print(f"  daily_rate: {o.daily_rate}")
            print(f"  security_deposit: {o.security_deposit}")
            print(f"  checkout_date: {o.checkout_date}")
            print(f"  num_days: {o.num_days}")
        else:
            print("No OnboardingSession found")

asyncio.run(check())
