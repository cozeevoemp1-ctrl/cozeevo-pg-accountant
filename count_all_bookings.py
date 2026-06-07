import os
import asyncio
os.environ['TEST_MODE'] = '1'

async def main():
    from src.database.db_manager import get_session, init_db
    from src.database.models import OnboardingSession, Room
    from sqlalchemy import select, func
    from dotenv import load_dotenv

    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    await init_db(db_url)

    async with get_session() as session:
        # Count by status
        by_status = {}
        for status in ["pending_review", "pending_tenant", "expired", "approved", "cancelled"]:
            count = await session.scalar(
                select(func.count(OnboardingSession.id))
                .where(OnboardingSession.status == status)
            )
            by_status[status] = count

        print("=== ALL ONBOARDING SESSIONS BY STATUS ===")
        for status, count in by_status.items():
            print(f"{status}: {count}")

        # Total
        total = sum(by_status.values())
        print(f"\nTotal: {total}")

        # Bookings page filter: pending_review + expired
        bookings_page = by_status['pending_review'] + by_status['expired']
        print(f"\nBookings page filter (pending_review + expired): {bookings_page}")

        # With rooms assigned
        with_rooms = await session.scalar(
            select(func.count(OnboardingSession.id))
            .where(
                OnboardingSession.status.in_(["pending_review", "pending_tenant"]),
                OnboardingSession.room_id.isnot(None),
            )
        )
        print(f"With rooms assigned (pending_review + pending_tenant): {with_rooms}")

asyncio.run(main())
