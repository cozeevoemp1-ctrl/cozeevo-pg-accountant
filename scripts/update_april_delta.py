"""
April delta updater — only update records that changed between Excel and DB.

Compares per-tenant: cash, UPI, rent_status, notes.
Only touches rows where Excel != DB.

Usage:
  python scripts/update_april_delta.py              # dry run — show what would change
  python scripts/update_april_delta.py --write      # commit changes to DB
"""
import sys, os, asyncio
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, selectinload

from src.database.models import (
    Tenant, Tenancy, RentSchedule, Payment, Room,
    RentStatus, PaymentMode, PaymentFor, TenancyStatus, StayType,
)
from scripts.import_april import read_april, _clean_status, APRIL_PERIOD

DATABASE_URL = os.environ["DATABASE_URL"]


async def find_delta(write=False):
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    records = read_april()
    print(f"Excel: {len(records)} records")

    stats = {
        'unchanged': 0, 'payment_updated': 0, 'payment_added': 0,
        'status_updated': 0, 'new_tenant': 0, 'new_tenancy': 0,
        'notes_updated': 0, 'skipped': 0, 'no_match': [],
    }

    async with Session() as session:
        session.autoflush = False

        # Pre-load rooms for creating tenancies
        rooms_result = await session.execute(select(Room))
        room_map = {}
        for r in rooms_result.scalars().all():
            room_map[r.room_number] = r

        for rec in records:
            is_exit = 'EXIT' in rec['inout']
            is_cancelled = 'CANCEL' in rec['inout']
            has_payment = rec['apr_cash'] > 0 or rec['apr_upi'] > 0

            # EXIT/CANCELLED with no payment: skip
            if (is_exit or is_cancelled) and not has_payment:
                continue

            phone_db = rec['phone_db']
            if not phone_db:
                stats['skipped'] += 1
                continue

            # Find tenant
            tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == phone_db)
            )
            if not tenant:
                if write:
                    tenant = Tenant(
                        name=rec['name'],
                        phone=phone_db,
                        gender='female' if str(rec['gender']).strip().lower() == 'female' else 'male',
                        notes=rec['permanent_note'] or None,
                    )
                    session.add(tenant)
                    await session.flush()
                    stats['new_tenant'] += 1
                    print(f"  NEW TENANT: {rec['name']} ({phone_db})")
                else:
                    stats['new_tenant'] += 1
                    print(f"  NEW TENANT (dry): {rec['name']} ({phone_db})")
                    continue

            # Find tenancy
            tenancy = await session.scalar(
                select(Tenancy).where(
                    Tenancy.tenant_id == tenant.id,
                    Tenancy.status == TenancyStatus.active,
                )
            )
            if not tenancy:
                tenancy = await session.scalar(
                    select(Tenancy).where(
                        Tenancy.tenant_id == tenant.id,
                    ).order_by(Tenancy.checkin_date.desc())
                )

            if not tenancy:
                import re as _re
                room_str = _re.sub(r'\.0$', '', str(rec['room']))
                room_obj = room_map.get(room_str)
                if not room_obj:
                    for k, v in room_map.items():
                        if k.lstrip('0') == room_str.lstrip('0'):
                            room_obj = v
                            break
                if not room_obj:
                    stats['no_match'].append(f"{rec['name']} — room {rec['room']} not found")
                    continue

                if write:
                    tenancy = Tenancy(
                        tenant_id=tenant.id,
                        room_id=room_obj.id,
                        stay_type=StayType.monthly,
                        status=_clean_status(rec['inout']),
                        checkin_date=rec['checkin'] or APRIL_PERIOD,
                        agreed_rent=Decimal(str(rec['april_rent'])),
                        security_deposit=Decimal(str(rec['deposit'])),
                        booking_amount=Decimal(str(rec['booking'])),
                        maintenance_fee=Decimal(str(rec['maintenance'])),
                        notes=rec['permanent_note'] or None,
                    )
                    session.add(tenancy)
                    await session.flush()
                    stats['new_tenancy'] += 1
                    print(f"  NEW TENANCY: {rec['name']} room {rec['room']}")
                else:
                    stats['new_tenancy'] += 1
                    print(f"  NEW TENANCY (dry): {rec['name']} room {rec['room']}")
                    continue

            # ── Compare DB vs Excel for this tenancy ────────────────
            gets_rs = not is_exit and not is_cancelled

            # Get existing DB payments for April
            db_payments = (await session.execute(
                select(Payment).where(
                    Payment.tenancy_id == tenancy.id,
                    Payment.period_month == APRIL_PERIOD,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void == False,
                )
            )).scalars().all()

            db_cash = sum(float(p.amount) for p in db_payments if p.payment_mode == PaymentMode.cash)
            db_upi = sum(float(p.amount) for p in db_payments if p.payment_mode == PaymentMode.upi)

            excel_cash = rec['apr_cash']
            excel_upi = rec['apr_upi']

            # Get existing rent_schedule
            db_rs = await session.scalar(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == tenancy.id,
                    RentSchedule.period_month == APRIL_PERIOD,
                )
            )

            changed = False

            # ── Cash delta ──────────────────────────────────────────
            if abs(excel_cash - db_cash) > 0.5:
                diff = excel_cash - db_cash
                if diff > 0:
                    print(f"  CASH +{diff:,.0f}: {rec['name']} (DB {db_cash:,.0f} -> Excel {excel_cash:,.0f})")
                    if write:
                        session.add(Payment(
                            tenancy_id=tenancy.id,
                            amount=Decimal(str(diff)),
                            payment_date=APRIL_PERIOD,
                            payment_mode=PaymentMode.cash,
                            for_type=PaymentFor.rent,
                            period_month=APRIL_PERIOD,
                            notes="April Excel delta update",
                        ))
                    stats['payment_added'] += 1
                else:
                    # Cash decreased — void old, add new
                    print(f"  CASH CHANGED: {rec['name']} (DB {db_cash:,.0f} -> Excel {excel_cash:,.0f})")
                    if write:
                        for p in db_payments:
                            if p.payment_mode == PaymentMode.cash:
                                p.is_void = True
                        if excel_cash > 0:
                            session.add(Payment(
                                tenancy_id=tenancy.id,
                                amount=Decimal(str(excel_cash)),
                                payment_date=APRIL_PERIOD,
                                payment_mode=PaymentMode.cash,
                                for_type=PaymentFor.rent,
                                period_month=APRIL_PERIOD,
                                notes="April Excel delta update (replaced)",
                            ))
                    stats['payment_updated'] += 1
                changed = True

            # ── UPI delta ───────────────────────────────────────────
            if abs(excel_upi - db_upi) > 0.5:
                diff = excel_upi - db_upi
                if diff > 0:
                    print(f"  UPI  +{diff:,.0f}: {rec['name']} (DB {db_upi:,.0f} -> Excel {excel_upi:,.0f})")
                    if write:
                        session.add(Payment(
                            tenancy_id=tenancy.id,
                            amount=Decimal(str(diff)),
                            payment_date=APRIL_PERIOD,
                            payment_mode=PaymentMode.upi,
                            for_type=PaymentFor.rent,
                            period_month=APRIL_PERIOD,
                            notes="April Excel delta update",
                        ))
                    stats['payment_added'] += 1
                else:
                    print(f"  UPI CHANGED: {rec['name']} (DB {db_upi:,.0f} -> Excel {excel_upi:,.0f})")
                    if write:
                        for p in db_payments:
                            if p.payment_mode == PaymentMode.upi:
                                p.is_void = True
                        if excel_upi > 0:
                            session.add(Payment(
                                tenancy_id=tenancy.id,
                                amount=Decimal(str(excel_upi)),
                                payment_date=APRIL_PERIOD,
                                payment_mode=PaymentMode.upi,
                                for_type=PaymentFor.rent,
                                period_month=APRIL_PERIOD,
                                notes="April Excel delta update (replaced)",
                            ))
                    stats['payment_updated'] += 1
                changed = True

            # ── Rent schedule status ────────────────────────────────
            if gets_rs and rec['apr_status'] and db_rs:
                if db_rs.status != rec['apr_status']:
                    print(f"  STATUS: {rec['name']} {db_rs.status.value} -> {rec['apr_status'].value}")
                    if write:
                        db_rs.status = rec['apr_status']
                    stats['status_updated'] += 1
                    changed = True
                # Update rent_due if changed
                if abs(float(db_rs.rent_due) - rec['april_rent']) > 0.5:
                    print(f"  RENT DUE: {rec['name']} {float(db_rs.rent_due):,.0f} -> {rec['april_rent']:,.0f}")
                    if write:
                        db_rs.rent_due = Decimal(str(rec['april_rent']))
                    changed = True
            elif gets_rs and rec['apr_status'] and not db_rs:
                print(f"  NEW RS: {rec['name']} {rec['apr_status'].value} rent={rec['april_rent']:,.0f}")
                if write:
                    session.add(RentSchedule(
                        tenancy_id=tenancy.id,
                        period_month=APRIL_PERIOD,
                        rent_due=Decimal(str(rec['april_rent'])),
                        maintenance_due=Decimal("0"),
                        status=rec['apr_status'],
                        due_date=APRIL_PERIOD,
                        notes=rec['monthly_note'] or None,
                    ))
                stats['payment_added'] += 1
                changed = True

            # ── Tenancy notes (permanent) ──────────────────────────
            if gets_rs and rec['permanent_note']:
                if rec['permanent_note'] != (tenancy.notes or ''):
                    print(f"  NOTES: {rec['name']} -> {rec['permanent_note'][:60]}")
                    if write:
                        tenancy.notes = rec['permanent_note']
                    stats['notes_updated'] += 1
                    changed = True

            # ── Rent schedule notes (monthly) ──────────────────────
            if gets_rs and db_rs and rec['monthly_note']:
                if rec['monthly_note'] != (db_rs.notes or ''):
                    print(f"  RS NOTES: {rec['name']} -> {rec['monthly_note'][:60]}")
                    if write:
                        db_rs.notes = rec['monthly_note']
                    stats['notes_updated'] += 1
                    changed = True

            if not changed:
                stats['unchanged'] += 1

        if write:
            await session.commit()
            print("\n** COMMITTED **")
        else:
            print("\n** DRY RUN — no changes **")

    await engine.dispose()

    print(f"\n{'='*50}")
    print(f"Unchanged:      {stats['unchanged']}")
    print(f"Payments added: {stats['payment_added']}")
    print(f"Payments fixed: {stats['payment_updated']}")
    print(f"Status updated: {stats['status_updated']}")
    print(f"Notes updated:  {stats['notes_updated']}")
    print(f"New tenants:    {stats['new_tenant']}")
    print(f"New tenancies:  {stats['new_tenancy']}")
    print(f"Skipped:        {stats['skipped']}")
    if stats['no_match']:
        print(f"\nNo match:")
        for m in stats['no_match']:
            print(f"  {m}")

    return stats


if __name__ == "__main__":
    write = "--write" in sys.argv
    asyncio.run(find_delta(write=write))
