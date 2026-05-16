"""
Fix April 2026 payment discrepancies vs ops sheet.

Actions:
  1. Un-void 5 wrongly-voided CASH payments (tenants paid both cash + UPI)
  2. Void 2 duplicate payments added by fix/audit scripts
  3. Add 2 missing UPI payments (Didla Lochan +5000, Saurav Mishra +2000)
  4. Void Rakesh Thallapally's cash 35533 (wrongly attributed duplicate of T.Rakesh Chetan)

Usage:
    python scripts/_fix_april_payments.py          # dry run
    python scripts/_fix_april_payments.py --write  # commit
"""
import asyncio, os, sys, argparse
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from decimal import Decimal
from datetime import date
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Payment, PaymentMode, PaymentFor

APRIL = date(2026, 4, 1)

# Wrongly voided cash payments — these tenants paid BOTH cash AND UPI
UNVOID_CASH = [
    (14711, "Jeewan Kant Oberoi  cash 14000 — sheet shows both cash+UPI"),
    (14789, "Prithviraj          cash 12000 — sheet shows cash paid"),
    (14814, "Chaitanya Phad      cash  8000 — sheet shows both cash+UPI"),
    (14922, "Rakshit Joshi       cash 18000 — sheet shows both cash+UPI"),
    (14928, "Arpit Mathur        cash 18000 — sheet shows both cash+UPI"),
]

# Duplicate payments added by fix/audit scripts — should be voided
VOID_DUPES = [
    (15361, "Dhruv               upi  6500 — duplicate from _fix_db_to_match_sheet.py"),
    (15345, "Rakesh Thallapally  cash 35533— wrongly attributed (shares phone with T.Rakesh Chetan)"),
]

# Missing UPI payments to add
ADD_UPI = [
    # (tenancy_phone_lookup, amount, name_for_log)
    # Didla Lochan room G07: DB=13000, sheet=18000
    ("+916363026018", 5000.0, "Didla Lochan — DB had 13000, sheet says 18000"),
    # Saurav Mishra room 221: DB=25000, sheet=27000
    ("+917008639950", 2000.0, "Saurav Mishra — DB had 25000, sheet says 27000"),
]


async def run(write: bool):
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Allow writes to historical months
        await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        print("=" * 60)
        print("APRIL PAYMENT FIX — ops-sheet reconciliation")
        print("=" * 60)

        # 1. Un-void wrongly voided cash payments
        print("\n[1] Un-voiding wrongly voided cash payments:")
        for pmt_id, desc in UNVOID_CASH:
            row = await session.execute(
                text("SELECT id, amount, is_void FROM payments WHERE id=:id"), {"id": pmt_id}
            )
            r = row.fetchone()
            if not r:
                print(f"  NOT FOUND: pmt_id={pmt_id} ({desc})")
                continue
            if not r[2]:
                print(f"  ALREADY ACTIVE: pmt_id={pmt_id} amt={r[1]} — {desc}")
                continue
            print(f"  UN-VOID: pmt_id={pmt_id} amt={r[1]} — {desc}")
            if write:
                await session.execute(
                    text("UPDATE payments SET is_void=false, notes=notes||' [UN-VOIDED: april fix 2026-05-16]' WHERE id=:id"),
                    {"id": pmt_id}
                )

        # 2. Void duplicate payments
        print("\n[2] Voiding duplicate payments:")
        for pmt_id, desc in VOID_DUPES:
            row = await session.execute(
                text("SELECT id, amount, is_void FROM payments WHERE id=:id"), {"id": pmt_id}
            )
            r = row.fetchone()
            if not r:
                print(f"  NOT FOUND: pmt_id={pmt_id} ({desc})")
                continue
            if r[2]:
                print(f"  ALREADY VOIDED: pmt_id={pmt_id} amt={r[1]} — {desc}")
                continue
            print(f"  VOID: pmt_id={pmt_id} amt={r[1]} — {desc}")
            if write:
                await session.execute(
                    text("UPDATE payments SET is_void=true, notes=notes||' [VOIDED: april fix duplicate 2026-05-16]' WHERE id=:id"),
                    {"id": pmt_id}
                )

        # 3. Add missing UPI payments
        print("\n[3] Adding missing UPI payments:")
        for phone, amount, desc in ADD_UPI:
            # Find tenancy by phone
            row = await session.execute(
                text("""
                    SELECT tn.id FROM tenancies tn
                    JOIN tenants t ON t.id=tn.tenant_id
                    WHERE t.phone=:phone
                    ORDER BY tn.id DESC LIMIT 1
                """),
                {"phone": phone}
            )
            r = row.fetchone()
            if not r:
                print(f"  NO TENANCY for phone {phone} — skipping: {desc}")
                continue
            tenancy_id = r[0]

            # Check if this exact amount already exists as active UPI payment
            existing = await session.execute(
                text("""
                    SELECT id, amount FROM payments
                    WHERE tenancy_id=:tid AND period_month=:month
                    AND for_type='rent' AND payment_mode='upi' AND is_void=false
                    AND amount=:amt
                """),
                {"tid": tenancy_id, "month": APRIL, "amt": amount}
            )
            ex = existing.fetchone()
            if ex:
                print(f"  ALREADY EXISTS: pmt_id={ex[0]} amt={ex[1]} — {desc}")
                continue

            print(f"  ADD: tenancy_id={tenancy_id} upi={int(amount)} — {desc}")
            if write:
                session.add(Payment(
                    tenancy_id=tenancy_id,
                    amount=Decimal(str(amount)),
                    payment_date=APRIL,
                    payment_mode=PaymentMode.upi,
                    for_type=PaymentFor.rent,
                    period_month=APRIL,
                    notes="April ops-sheet fix [_fix_april_payments.py 2026-05-16]",
                ))

        if write:
            await session.commit()
            print("\n** COMMITTED **")
        else:
            print("\n** DRY RUN — no changes saved **")

        # Show final totals
        r2 = await session.execute(text("""
            SELECT payment_mode, SUM(amount), COUNT(*)
            FROM payments
            WHERE period_month='2026-04-01' AND for_type='rent' AND is_void=false
            GROUP BY payment_mode
        """))
        print("\nFINAL DB April totals:")
        total = 0
        for row in r2:
            print(f"  {row[0]:5}: {int(row[1]):>12,}  ({row[2]} pmts)")
            total += float(row[1])
        print(f"  TOTAL: {int(total):,}")
        print(f"  Sheet: cash=1,345,283  upi=3,202,415  total=4,547,698")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
