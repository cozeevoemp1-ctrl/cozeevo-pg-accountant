import os
import asyncio
import json

os.environ['TEST_MODE'] = '1'

async def main():
    from src.database.db_manager import get_session, init_db
    from src.database.models import OnboardingSession, Tenancy, Tenant, Room, TenancyStatus, StayType
    from sqlalchemy import select, func
    from datetime import date, timedelta
    from dotenv import load_dotenv

    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    await init_db(db_url)

    async with get_session() as session:
        today = date.today()

        # Get all leaving tenants (on notice or expected checkout within 30 days)
        leaving = await session.execute(
            select(
                Tenancy.id,
                Tenancy.room_id,
                Tenant.name,
                Room.room_number,
                Tenancy.expected_checkout,
                Tenancy.notice_date,
                Tenancy.status,
            )
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.status == TenancyStatus.active,
                Tenancy.stay_type == StayType.monthly,
            )
            .order_by(Tenancy.expected_checkout)
        )
        leaving_list = leaving.all()
        print(f"=== {len(leaving_list)} LEAVING TENANTS ===\n")

        # Get all bookings with actual rooms assigned
        bookings = await session.execute(
            select(
                OnboardingSession.id,
                OnboardingSession.tenant_phone,
                OnboardingSession.checkin_date,
                OnboardingSession.status,
                Room.room_number,
            )
            .outerjoin(Room, Room.id == OnboardingSession.room_id)
            .where(
                OnboardingSession.status.in_(["pending_review", "pending_tenant"]),
                OnboardingSession.room_id.isnot(None),
            )
        )
        bookings_list = bookings.all()
        print(f"=== {len(bookings_list)} BOOKINGS WITH ROOMS ASSIGNED ===\n")

        # Create a map of room_id -> leaving tenant
        leaving_by_room = {}
        for tenancy_id, room_id, name, room_num, checkout, notice, status in leaving_list:
            leaving_by_room[room_id] = (name, room_num, checkout)

        # Create a map of room_id -> bookings in that room
        bookings_by_room = {}
        for bid, phone, checkin, bstatus, room_num in bookings_list:
            # Get room_id from room_number
            room_result = await session.scalar(
                select(Room.id).where(Room.room_number == room_num)
            )
            if room_result and room_result in leaving_by_room:
                if room_result not in bookings_by_room:
                    bookings_by_room[room_result] = []
                bookings_by_room[room_result].append({
                    'phone': phone,
                    'checkin': checkin.isoformat() if checkin else None,
                    'status': bstatus,
                    'room': room_num,
                })

        # Show the mismatches
        print("=== ROOMS WITH LEAVING TENANTS ===")
        for room_id, (leaving_name, room_num, checkout) in leaving_by_room.items():
            bookings_in_room = bookings_by_room.get(room_id, [])
            print(f"\n{room_num}: {leaving_name}")
            print(f"  Expected checkout: {checkout.isoformat() if checkout else '?'}")
            if bookings_in_room:
                print(f"  ✅ Bookings in this room:")
                for b in bookings_in_room:
                    print(f"     - {b['phone']} | Check-in: {b['checkin']} | Status: {b['status']}")
                    # Check if dates match
                    if b['checkin'] and checkout:
                        ci = b['checkin']
                        co = checkout.isoformat()
                        if ci >= co:
                            print(f"       ✓ Check-in AFTER checkout (valid replacement)")
                        else:
                            print(f"       ✗ Check-in BEFORE checkout ({(date.fromisoformat(co) - date.fromisoformat(ci)).days} days early)")
            else:
                print(f"  ❌ NO BOOKING IN THIS ROOM")

asyncio.run(main())
