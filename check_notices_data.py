import os
import asyncio

os.environ['TEST_MODE'] = '1'

async def main():
    from src.database.db_manager import get_session, init_db
    from src.database.models import OnboardingSession, Tenancy, Tenant, Room, TenancyStatus, StayType
    from sqlalchemy import select, func, or_
    from datetime import date, timedelta
    from dotenv import load_dotenv

    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    await init_db(db_url)

    async with get_session() as session:
        today = date.today()

        # Get all MONTHLY leaving tenants (on notice or expected checkout in next 60 days)
        leaving = await session.execute(
            select(
                Tenancy.id,
                Tenancy.room_id,
                Tenant.name,
                Room.room_number,
                Tenancy.expected_checkout,
                Tenancy.notice_date,
            )
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.status == TenancyStatus.active,
                Tenancy.stay_type == StayType.monthly,
                or_(
                    Tenancy.notice_date != None,
                    Tenancy.expected_checkout.between(today - timedelta(days=30), today + timedelta(days=60))
                ),
            )
            .order_by(Tenancy.expected_checkout)
        )
        leaving_list = leaving.all()
        print(f"=== {len(leaving_list)} LEAVING TENANTS (same query as notices page) ===\n")

        # Get all bookings with actual rooms (pending_review + pending_tenant)
        bookings = await session.execute(
            select(
                OnboardingSession.id,
                OnboardingSession.tenant_phone,
                OnboardingSession.checkin_date,
                OnboardingSession.status,
                Room.room_number,
                OnboardingSession.room_id,
            )
            .outerjoin(Room, Room.id == OnboardingSession.room_id)
            .where(
                OnboardingSession.status.in_(["pending_review", "pending_tenant"]),
                OnboardingSession.room_id.isnot(None),
            )
        )
        bookings_list = bookings.all()
        print(f"=== {len(bookings_list)} BOOKINGS WITH ROOMS ===\n")

        # Build maps
        leaving_by_room = {}
        for tid, room_id, name, room_num, checkout, notice in leaving_list:
            if room_id not in leaving_by_room:
                leaving_by_room[room_id] = []
            leaving_by_room[room_id].append({
                'name': name,
                'room_num': room_num,
                'checkout': checkout,
                'notice_date': notice,
            })

        bookings_by_room = {}
        for bid, phone, checkin, status, room_num, room_id in bookings_list:
            if room_id and room_id in leaving_by_room:
                if room_id not in bookings_by_room:
                    bookings_by_room[room_id] = []
                bookings_by_room[room_id].append({
                    'phone': phone,
                    'checkin': checkin,
                    'status': status,
                })

        # Analysis
        print("=== MATCHING ANALYSIS ===\n")
        matched = 0
        unmatched_bookings = 0

        for room_id, leaving_tenants in leaving_by_room.items():
            for tenant in leaving_tenants:
                bookings = bookings_by_room.get(room_id, [])
                room_num = tenant['room_num']
                checkout = tenant['checkout']

                if bookings:
                    # Check each booking
                    for b in bookings:
                        ci = b['checkin']
                        if ci and checkout:
                            # Current logic from kpi.py: ci >= eco
                            if ci >= checkout:
                                print(f"[MATCH] {room_num} ({tenant['name']}) | Checkout {checkout} -> Booking {ci} ({b['status']})")
                                matched += 1
                            else:
                                diff = (checkout - ci).days
                                print(f"[NOMATCH] {room_num} ({tenant['name']}) | Checkout {checkout} -> Booking {ci} ({diff} days BEFORE)")
                                unmatched_bookings += 1

        # Find bookings NOT in rooms with leaving tenants
        leaving_room_ids = set(leaving_by_room.keys())
        orphan_bookings = [b for b in bookings_list if b[5] not in leaving_room_ids]

        print(f"\n=== BOOKINGS IN ROOMS WITH NO LEAVING TENANTS ===")
        print(f"Count: {len(orphan_bookings)}")
        for bid, phone, checkin, status, room_num, room_id in orphan_bookings:
            print(f"  Room {room_num}: {phone} | Check-in {checkin} ({status})")

        print(f"\n=== SUMMARY ===")
        print(f"Matched replacements (ci >= checkout): {matched}")
        print(f"Unmatched (too early): {unmatched_bookings}")
        print(f"Bookings in rooms with NO leaving tenant: {len(orphan_bookings)}")
        print(f"")
        print(f"Total leaving tenants: {len(leaving_list)}")
        print(f"Total bookings: {len(bookings_list)}")
        print(f"  - In rooms with leavers: {len(bookings_list) - len(orphan_bookings)}")
        print(f"  - In rooms with NO leavers: {len(orphan_bookings)}")

asyncio.run(main())
