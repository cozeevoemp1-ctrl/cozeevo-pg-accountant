import os
import asyncio
os.environ['TEST_MODE'] = '1'

async def main():
    from src.database.db_manager import get_session, init_db
    from src.database.models import OnboardingSession, Room
    from sqlalchemy import select
    from dotenv import load_dotenv

    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    await init_db(db_url)

    async with get_session() as session:
        # Get room 000 ID
        room_000 = await session.scalar(select(Room.id).where(Room.room_number == "000"))

        # Get all bookings in room 000
        bookings = await session.execute(
            select(
                OnboardingSession.id,
                OnboardingSession.token,
                OnboardingSession.tenant_phone,
                OnboardingSession.checkin_date,
                OnboardingSession.status,
            )
            .where(OnboardingSession.room_id == room_000)
        )

        result = bookings.all()
        print(f"Room 000 bookings: {len(result)}")
        for bid, token, phone, checkin, status in result:
            print(f"  ID {bid} | {phone} | {checkin} | {status}")

asyncio.run(main())
