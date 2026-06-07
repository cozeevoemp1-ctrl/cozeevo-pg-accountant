import os
import asyncio
from datetime import date

os.environ['TEST_MODE'] = '1'

async def main():
    from src.database.db_manager import get_session, init_db
    from src.database.models import OnboardingSession, Tenancy, Tenant, Room, TenancyStatus
    from sqlalchemy import select, func

    await init_db()

    async with get_session() as session:
        # Get all bookings (pending_review + pending_tenant)
        obs = await session.execute(
            select(
                OnboardingSession.id,
                OnboardingSession.tenant_phone,
                OnboardingSession.checkin_date,
                Room.room_number,
                OnboardingSession.status,
                OnboardingSession.room_id,
            )
            .outerjoin(Room, Room.id == OnboardingSession.room_id)
            .where(OnboardingSession.status.in_(['pending_review', 'pending_tenant', 'expired']))
            .order_by(OnboardingSession.checkin_date)
        )

        bookings = obs.all()
        print(f"\n=== ALL BOOKINGS ({len(bookings)} total) ===\n")

        # Group by status
        by_status = {}
        for bid, phone, checkin, room, status, room_id in bookings:
            if status not in by_status:
                by_status[status] = []
            by_status[status].append((bid, phone, checkin, room, status, room_id))

        for st in ['pending_review', 'pending_tenant', 'expired']:
            if st in by_status:
                print(f"\n--- {st.upper()} ({len(by_status[st])}) ---")
                for bid, phone, checkin, room, status, room_id in by_status[st]:
                    # Check if this is a replacement (room has active tenants)
                    if room_id:
                        active = await session.execute(
                            select(func.count(Tenancy.id))
                            .where(
                                Tenancy.room_id == room_id,
                                Tenancy.status == TenancyStatus.active
                            )
                        )
                        active_count = active.scalar() or 0
                    else:
                        active_count = 0

                    ci = checkin.strftime('%d %b') if checkin else '?'
                    room_display = room or "TBD"
                    replacement_marker = " ⚠️ IS REPLACEMENT" if active_count > 0 else ""
                    print(f"  {phone:15} | Room {room_display:4} | {ci:6} | Active: {active_count}{replacement_marker}")

asyncio.run(main())
