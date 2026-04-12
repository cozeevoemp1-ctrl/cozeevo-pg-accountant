"""Anomaly report: payment issues, data quality, rent mismatches, stale no-shows."""
import sys, os, asyncio
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from datetime import date
from decimal import Decimal
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Tenant, Tenancy, Room, Payment, RentSchedule, Property,
    TenancyStatus, RentStatus, PaymentFor,
)

DATABASE_URL = os.environ["DATABASE_URL"]
APRIL = date(2026, 4, 1)
TODAY = date.today()


async def run():
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # ── 2. PAYMENT ANOMALIES ──────────────────────────────────
        print("=" * 60)
        print("2. PAYMENT ANOMALIES (April 2026)")
        print("=" * 60)

        # PAID but no actual payment
        paid_rs = (await session.execute(
            select(RentSchedule, Tenant.name, Room.room_number)
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(RentSchedule.period_month == APRIL, RentSchedule.status == RentStatus.paid)
        )).all()

        paid_but_zero = []
        for rs, name, room in paid_rs:
            total = await session.scalar(
                select(func.sum(Payment.amount)).where(
                    Payment.tenancy_id == rs.tenancy_id,
                    Payment.period_month == APRIL,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void == False,
                )
            ) or 0
            if total == 0:
                paid_but_zero.append((name, room, int(rs.rent_due or 0)))

        if paid_but_zero:
            print(f"\n  PAID status but Rs.0 collected ({len(paid_but_zero)}):")
            for name, room, due in paid_but_zero:
                print(f"    {room:5} {name:25} due={due:,}")

        # UNPAID/PENDING but has payments
        pending_rs = (await session.execute(
            select(RentSchedule, Tenant.name, Room.room_number)
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(RentSchedule.period_month == APRIL, RentSchedule.status == RentStatus.pending)
        )).all()

        unpaid_but_paid = []
        for rs, name, room in pending_rs:
            total = await session.scalar(
                select(func.sum(Payment.amount)).where(
                    Payment.tenancy_id == rs.tenancy_id,
                    Payment.period_month == APRIL,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void == False,
                )
            ) or 0
            if total > 0:
                unpaid_but_paid.append((name, room, int(rs.rent_due or 0), int(total)))

        if unpaid_but_paid:
            print(f"\n  UNPAID/PENDING but has payments ({len(unpaid_but_paid)}):")
            for name, room, due, paid in unpaid_but_paid:
                print(f"    {room:5} {name:25} due={due:,} paid={paid:,}")

        # Overpaid (paid > rent due)
        all_rs = (await session.execute(
            select(RentSchedule, Tenant.name, Room.room_number)
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(RentSchedule.period_month == APRIL)
        )).all()

        overpaid = []
        for rs, name, room in all_rs:
            total = await session.scalar(
                select(func.sum(Payment.amount)).where(
                    Payment.tenancy_id == rs.tenancy_id,
                    Payment.period_month == APRIL,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void == False,
                )
            ) or 0
            due = float(rs.rent_due or 0)
            total = float(total)
            if total > due and due > 0 and (total - due) > 100:
                overpaid.append((name, room, int(due), int(total), int(total - due)))

        if overpaid:
            print(f"\n  Overpaid — paid more than rent due ({len(overpaid)}):")
            for name, room, due, paid, extra in overpaid:
                print(f"    {room:5} {name:25} due={due:,} paid={paid:,} excess={extra:,}")

        if not paid_but_zero and not unpaid_but_paid and not overpaid:
            print("\n  No payment anomalies.")

        # ── 3. DATA QUALITY ──────────────────────────────────────
        print(f"\n{'=' * 60}")
        print("3. DATA QUALITY")
        print("=" * 60)

        # Missing/placeholder phones
        bad_phones = (await session.execute(
            select(Tenant.name, Tenant.phone, Room.room_number)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status == TenancyStatus.active, Tenant.phone.like("NOPHONE%"))
            .order_by(Room.room_number)
        )).all()
        if bad_phones:
            print(f"\n  Missing/placeholder phones ({len(bad_phones)}):")
            for name, phone, room in bad_phones:
                print(f"    {room:5} {name}")

        # Duplicate active tenant names
        dupes = (await session.execute(text("""
            SELECT t.name, count(*) as cnt, array_agg(t.phone) as phones, array_agg(r.room_number) as rooms
            FROM tenants t
            JOIN tenancies tn ON tn.tenant_id = t.id
            JOIN rooms r ON r.id = tn.room_id
            WHERE tn.status = 'active'
            GROUP BY t.name
            HAVING count(*) > 1
            ORDER BY cnt DESC
        """))).all()
        if dupes:
            print(f"\n  Duplicate active tenant names ({len(dupes)}):")
            for name, cnt, phones, rooms in dupes:
                print(f"    {name:25} x{cnt}  rooms={rooms}")

        # Blank sharing type
        blank_sharing = (await session.execute(
            select(Tenant.name, Room.room_number)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status == TenancyStatus.active, Tenancy.sharing_type.is_(None))
            .order_by(Room.room_number)
        )).all()
        if blank_sharing:
            print(f"\n  Blank sharing type ({len(blank_sharing)}):")
            for name, room in blank_sharing:
                print(f"    {room:5} {name}")

        # Zero rent
        zero_rent = (await session.execute(
            select(Tenant.name, Room.room_number, Tenancy.agreed_rent)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status == TenancyStatus.active, Tenancy.agreed_rent <= 0)
            .order_by(Room.room_number)
        )).all()
        if zero_rent:
            print(f"\n  Zero/negative rent ({len(zero_rent)}):")
            for name, room, rent in zero_rent:
                print(f"    {room:5} {name:25} rent={rent}")

        # Room with more tenants than max_occupancy
        overcrowded = (await session.execute(text("""
            SELECT r.room_number, r.max_occupancy,
                   count(tn.id) as tenant_count,
                   array_agg(t.name) as names
            FROM rooms r
            JOIN tenancies tn ON tn.room_id = r.id AND tn.status = 'active'
            JOIN tenants t ON t.id = tn.tenant_id
            WHERE r.is_staff_room = false
            GROUP BY r.id, r.room_number, r.max_occupancy
            HAVING count(tn.id) > r.max_occupancy
            ORDER BY r.room_number
        """))).all()
        if overcrowded:
            print(f"\n  Overcrowded rooms ({len(overcrowded)}):")
            for room, max_occ, cnt, names in overcrowded:
                print(f"    {room:5} {cnt}/{max_occ} tenants: {names}")

        if not bad_phones and not dupes and not blank_sharing and not zero_rent and not overcrowded:
            print("\n  No data quality issues.")

        # ── 4. RENT MISMATCH (DB vs Sheet) ────────────────────────
        print(f"\n{'=' * 60}")
        print("4. RENT MISMATCH (DB vs Sheet — April 2026)")
        print("=" * 60)

        from src.integrations.gsheets import _get_worksheet_sync
        ws = _get_worksheet_sync("APRIL 2026")
        sheet_data = ws.get_all_values()

        sheet_rent = {}
        for row in sheet_data[4:]:
            room = str(row[0]).strip()
            name = str(row[1]).strip().lower()
            try:
                rent = float(str(row[5]).replace(",", "").strip() or 0)
            except ValueError:
                rent = 0
            if room and name:
                sheet_rent[(room, name)] = rent

        db_tenants = (await session.execute(
            select(Tenant.name, Room.room_number, Tenancy.agreed_rent)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status == TenancyStatus.active)
            .order_by(Room.room_number)
        )).all()

        mismatches = []
        for name, room, db_rent in db_tenants:
            sheet_key = (str(room), name.lower())
            if sheet_key in sheet_rent:
                s_rent = sheet_rent[sheet_key]
                d_rent = float(db_rent or 0)
                if abs(d_rent - s_rent) > 1:
                    mismatches.append((room, name, d_rent, s_rent))

        if mismatches:
            print(f"\n  Rent differs DB vs Sheet ({len(mismatches)}):")
            for room, name, db_r, sh_r in sorted(mismatches, key=lambda x: str(x[0])):
                print(f"    {room:5} {name:25} DB={int(db_r):>8,}  Sheet={int(sh_r):>8,}")
        else:
            print("\n  No rent mismatches.")

        # ── 5. STALE NO-SHOWS ────────────────────────────────────
        print(f"\n{'=' * 60}")
        print("5. STALE NO-SHOWS")
        print("=" * 60)

        stale = (await session.execute(
            select(Tenant.name, Room.room_number, Tenancy.checkin_date)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status == TenancyStatus.no_show)
            .order_by(Tenancy.checkin_date)
        )).all()

        if stale:
            print(f"\n  No-show tenants ({len(stale)}):")
            for name, room, checkin in stale:
                days = (TODAY - checkin).days if checkin else "?"
                flag = " *** STALE" if isinstance(days, int) and days > 30 else ""
                print(f"    {room:5} {name:25} checkin={checkin}  ({days} days ago){flag}")
        else:
            print("\n  No no-shows.")

    await engine.dispose()
    print(f"\n{'=' * 60}")
    print("Done.")


asyncio.run(run())
