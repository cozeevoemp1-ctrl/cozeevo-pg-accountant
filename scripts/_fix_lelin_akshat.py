"""
Fix Lenin Das payments + add Akshat to room 416.

Lenin Das (room 308):
- pmt 16229 (₹27K cash) was wrongly voided as "dup of booking advance"
- Kiran confirmed: paid ₹27K cash (May rent) AND ₹27K deposit separately
- Action: un-void 16229, ensure it's for_type=rent period=May 2026
- Check if deposit entry exists; add if missing

Akshat (room 416):
- phone +917796277597, room 416 (double), agreed_rent=0 placeholder
- agreed_rent must be set via bot once known
- May payment will be picked up by next _import_may_payments.py --write run

Usage:
    python scripts/_fix_lelin_akshat.py           # dry run
    python scripts/_fix_lelin_akshat.py --write   # commit
"""
import asyncio, os, sys, argparse
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
import io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.database.models import (
    Tenant, Tenancy, Payment, RentSchedule, Room,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus,
)

MAY = date(2026, 5, 1)


async def run(write: bool):
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as s:
        # ── 1. LELIN DAS ─────────────────────────────────────────────────────
        print("\n── LELIN DAS (room 308) ──")

        pmt = await s.get(Payment, 16229)
        if pmt:
            print(f"  pmt 16229: ₹{pmt.amount} {pmt.payment_mode.value} for_type={pmt.for_type} is_void={pmt.is_void}")
            if pmt.is_void:
                print("  → Un-voiding (May rent cash)")
                if write:
                    pmt.is_void = False  # type: ignore[assignment]
                    pmt.for_type = PaymentFor.rent  # type: ignore[assignment]
                    pmt.period_month = MAY  # type: ignore[assignment]
            else:
                print("  Already active — no action needed")
        else:
            print("  pmt 16229 not found in DB!")

        # Check Lenin's tenancy + existing payments
        tenant = await s.scalar(select(Tenant).where(Tenant.name.ilike('%lelin%')))
        if not tenant:
            tenant = await s.scalar(select(Tenant).where(Tenant.phone.contains('8106778788')))
        if tenant:
            print(f"  Tenant: id={tenant.id} name={tenant.name} phone={tenant.phone}")
            tenancy = await s.scalar(
                select(Tenancy).where(Tenancy.tenant_id == tenant.id, Tenancy.status == TenancyStatus.active)
            )
            if tenancy:
                print(f"  Tenancy: id={tenancy.id} room_id={tenancy.room_id}")
                pmts = (await s.execute(
                    select(Payment)
                    .where(Payment.tenancy_id == tenancy.id, Payment.is_void == False)
                    .order_by(Payment.payment_date)
                )).scalars().all()
                print(f"  Active payments:")
                for p in pmts:
                    print(f"    pmt {p.id}: ₹{p.amount} {p.payment_mode.value} for_type={p.for_type} date={p.payment_date}")

                # Check if deposit exists
                deposit = next((p for p in pmts if p.for_type == PaymentFor.deposit), None)
                if deposit:
                    print(f"  Deposit already in DB: pmt {deposit.id} ₹{deposit.amount}")
                else:
                    print("  ⚠ NO deposit payment in DB — adding ₹27,000 cash deposit")
                    if write:
                        new_dep = Payment(
                            tenancy_id=tenancy.id,
                            amount=27000,
                            payment_mode=PaymentMode.cash,
                            for_type=PaymentFor.deposit,
                            payment_date=date(2026, 5, 1),
                            period_month=MAY,
                            is_void=False,
                            notes="Added by _fix_lelin_akshat.py — Kiran confirmed ₹27K deposit",
                        )
                        s.add(new_dep)
                        print("  ✓ Deposit payment added")
        else:
            print("  ⚠ Tenant 'Lelin Das' not found by name/phone!")

        # ── 2. AKSHAT — room 416 ─────────────────────────────────────────────
        print("\n── AKSHAT (room 416) ──")

        # Find room 416
        room = await s.scalar(select(Room).where(Room.room_number == "416"))
        if not room:
            print("  ⚠ Room 416 not found!")
            return
        print(f"  Room 416: id={room.id} max_occ={room.max_occupancy} type={room.room_type}")

        # Check if already in DB
        existing = await s.scalar(select(Tenant).where(Tenant.phone == "+917796277597"))
        if existing:
            print(f"  Already in DB: id={existing.id} name={existing.name}")
        else:
            print("  Adding Akshat to room 416...")
            if write:
                new_tenant = Tenant(
                    name="Akshat",
                    phone="+917796277597",
                    sharing_type="double",
                )
                s.add(new_tenant)
                await s.flush()
                print(f"  ✓ Tenant created: id={new_tenant.id}")

                new_tenancy = Tenancy(
                    tenant_id=new_tenant.id,
                    room_id=room.id,
                    status=TenancyStatus.active,
                    checkin_date=date(2026, 5, 1),
                    agreed_rent=0,
                    security_deposit=0,
                    maintenance_fee=0,
                    stay_type="monthly",
                )
                s.add(new_tenancy)
                await s.flush()
                print(f"  ✓ Tenancy created: id={new_tenancy.id}")

                rs = RentSchedule(
                    tenancy_id=new_tenancy.id,
                    period_month=MAY,
                    rent_due=0,
                    paid_amount=0,
                    status=RentStatus.partial,
                )
                s.add(rs)
                print(f"  ✓ RentSchedule created for May 2026")
                print("  ⚠ agreed_rent = 0 — update via bot: 'change Akshat rent to X'")

        if write:
            await s.commit()
            print("\n✓ All changes committed")
        else:
            print("\n[DRY RUN] — pass --write to commit")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
