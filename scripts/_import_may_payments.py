"""
Import May 2026 rent payments from source sheet (1Vr_...) columns Z (MAY UPI) + AA (MAY Cash).
Only imports rows where payment is missing or incomplete in DB.
All payments recorded as for_type=rent.

Usage:
    python scripts/_import_may_payments.py          # dry run
    python scripts/_import_may_payments.py --write  # commit to DB
"""
import asyncio, os, re, sys, argparse
from datetime import date
from decimal import Decimal
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Tenant, Tenancy, Payment, RentSchedule,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus,
)

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE = "credentials/gsheets_service_account.json"
MAY = date(2026, 5, 1)

# Column indices (0-based) in "Long term" tab
COL_ROOM    = 0
COL_NAME    = 1
COL_PHONE   = 3
COL_MAY_UPI  = 25   # Z
COL_MAY_CASH = 26   # AA


def pn(v):
    if not v: return 0.0
    s = str(v).replace(',', '').strip()
    try: return float(s)
    except: return 0.0


def norm_phone(raw):
    d = re.sub(r'\D', '', str(raw or ''))
    if d.startswith('91') and len(d) == 12:
        d = d[2:]
    return '+91' + d if len(d) == 10 else ''


def read_sheet():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SOURCE_SHEET_ID)
    ws = sh.worksheet('Long term')
    rows = ws.get_all_values()
    data = []
    for r in rows[1:]:
        if not r[COL_NAME].strip():
            continue
        may_upi  = pn(r[COL_MAY_UPI])
        may_cash = pn(r[COL_MAY_CASH])
        if may_cash > 0 or may_upi > 0:
            data.append({
                'name': r[COL_NAME].strip(),
                'room': r[COL_ROOM].strip(),
                'phone_db': norm_phone(r[COL_PHONE]),
                'may_cash': may_cash,
                'may_upi':  may_upi,
            })
    return data


async def run(write: bool):
    print("=" * 60)
    print("MAY 2026 PAYMENT IMPORT (from source sheet Z/AA columns)")
    print("=" * 60)

    print("\nStep 1: Reading source sheet...")
    sheet_data = read_sheet()
    print("  %d rows with May payments in sheet" % len(sheet_data))
    print("  Sheet Cash: %d" % int(sum(r['may_cash'] for r in sheet_data)))
    print("  Sheet UPI:  %d" % int(sum(r['may_upi']  for r in sheet_data)))

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    stats = {
        'skipped_no_phone': 0, 'skipped_already_in_db': 0,
        'no_tenant': [], 'no_tenancy': [], 'no_rs': [],
        'added_cash': 0, 'added_upi': 0,
        'added_cash_total': 0.0, 'added_upi_total': 0.0,
        'room_mismatch': [],
    }

    print("\nStep 2: Checking DB + importing missing payments...")

    async with Session() as session:
        # Pre-load existing May payments by tenancy_id
        from sqlalchemy import text
        existing_q = await session.execute(text("""
            SELECT p.tenancy_id, p.payment_mode, SUM(p.amount) as total
            FROM payments p
            WHERE p.period_month = '2026-05-01' AND p.for_type = 'rent' AND p.is_void = false
            GROUP BY p.tenancy_id, p.payment_mode
        """))
        existing_pmts = {}  # tenancy_id -> {'cash': X, 'upi': Y}
        for row in existing_q:
            tid = row.tenancy_id
            if tid not in existing_pmts:
                existing_pmts[tid] = {'cash': 0.0, 'upi': 0.0}
            existing_pmts[tid][row.payment_mode] = float(row.total)

        for rec in sheet_data:
            phone = rec['phone_db']
            if not phone:
                stats['skipped_no_phone'] += 1
                print("  SKIP (no phone): %s room %s" % (rec['name'], rec['room']))
                continue

            # Find tenant
            tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == phone)
            )
            if not tenant:
                stats['no_tenant'].append("%s room %s (%s)" % (rec['name'], rec['room'], phone))
                print("  NO TENANT: %s room %s phone %s" % (rec['name'], rec['room'], phone))
                continue

            # Find active tenancy (prefer active, fallback to most recent)
            tenancy = await session.scalar(
                select(Tenancy)
                .where(Tenancy.tenant_id == tenant.id, Tenancy.status == TenancyStatus.active)
            )
            if not tenancy:
                tenancy = await session.scalar(
                    select(Tenancy)
                    .where(Tenancy.tenant_id == tenant.id)
                    .order_by(Tenancy.checkin_date.desc())
                )
            if not tenancy:
                stats['no_tenancy'].append("%s (%s)" % (rec['name'], phone))
                print("  NO TENANCY: %s room %s" % (rec['name'], rec['room']))
                continue

            # Room mismatch check
            from sqlalchemy.orm import joinedload
            from src.database.models import Room
            room_obj = await session.scalar(
                select(Room).where(Room.id == tenancy.room_id)
            )
            db_room = room_obj.room_number if room_obj else '?'
            if db_room != rec['room']:
                stats['room_mismatch'].append(
                    "%s — sheet: %s  DB: %s" % (rec['name'], rec['room'], db_room)
                )

            # Check rent_schedule for May
            rs = await session.scalar(
                select(RentSchedule)
                .where(RentSchedule.tenancy_id == tenancy.id, RentSchedule.period_month == MAY)
            )
            if not rs:
                stats['no_rs'].append("%s room %s" % (rec['name'], rec['room']))
                print("  NO RS: %s room %s — creating RS with agreed_rent" % (rec['name'], rec['room']))
                # Create rent_schedule from tenancy.agreed_rent
                if write:
                    rs = RentSchedule(
                        tenancy_id=tenancy.id,
                        period_month=MAY,
                        rent_due=tenancy.agreed_rent,
                        maintenance_due=Decimal('0'),
                        status=RentStatus.pending,
                        due_date=MAY,
                        notes="Auto-created by _import_may_payments.py",
                    )
                    session.add(rs)
                    await session.flush()

            # Calculate what's already in DB
            db_cash = existing_pmts.get(tenancy.id, {}).get('cash', 0.0)
            db_upi  = existing_pmts.get(tenancy.id, {}).get('upi', 0.0)
            need_cash = rec['may_cash'] - db_cash
            need_upi  = rec['may_upi']  - db_upi

            if need_cash < 1 and need_upi < 1:
                stats['skipped_already_in_db'] += 1
                continue

            print("  ADD: %-25s room %-6s  cash=%8d  upi=%8d" % (
                rec['name'], db_room,
                int(need_cash) if need_cash >= 1 else 0,
                int(need_upi) if need_upi >= 1 else 0
            ))

            if write:
                if need_cash >= 1:
                    session.add(Payment(
                        tenancy_id=tenancy.id,
                        amount=Decimal(str(round(need_cash, 2))),
                        payment_date=MAY,
                        payment_mode=PaymentMode.cash,
                        for_type=PaymentFor.rent,
                        period_month=MAY,
                        notes="May source sheet [Z/AA import]",
                    ))
                    stats['added_cash'] += 1
                    stats['added_cash_total'] += need_cash

                if need_upi >= 1:
                    session.add(Payment(
                        tenancy_id=tenancy.id,
                        amount=Decimal(str(round(need_upi, 2))),
                        payment_date=MAY,
                        payment_mode=PaymentMode.upi,
                        for_type=PaymentFor.rent,
                        period_month=MAY,
                        notes="May source sheet [Z/AA import]",
                    ))
                    stats['added_upi'] += 1
                    stats['added_upi_total'] += need_upi
            else:
                # Dry run — just count
                if need_cash >= 1:
                    stats['added_cash'] += 1
                    stats['added_cash_total'] += need_cash
                if need_upi >= 1:
                    stats['added_upi'] += 1
                    stats['added_upi_total'] += need_upi

        if write:
            await session.commit()
            print("\n  ** COMMITTED to DB **")
        else:
            print("\n  ** DRY RUN — no changes saved **")

    print("\nSUMMARY:")
    print("  Skipped (no phone):      %d" % stats['skipped_no_phone'])
    print("  Skipped (already in DB): %d" % stats['skipped_already_in_db'])
    print("  Cash payments added:     %d  (total: %d)" % (stats['added_cash'], int(stats['added_cash_total'])))
    print("  UPI payments added:      %d  (total: %d)" % (stats['added_upi'], int(stats['added_upi_total'])))
    print("  No RS (auto-created):    %d" % len(stats['no_rs']))
    print("  No tenant in DB:         %d" % len(stats['no_tenant']))
    print("  No tenancy in DB:        %d" % len(stats['no_tenancy']))

    if stats['no_tenant']:
        print("\n  MISSING TENANTS (need manual add):")
        for s in stats['no_tenant']: print("    - " + s)

    if stats['no_tenancy']:
        print("\n  MISSING TENANCIES:")
        for s in stats['no_tenancy']: print("    - " + s)

    if stats['room_mismatch']:
        print("\n  ROOM MISMATCHES (sheet vs DB):")
        for s in stats['room_mismatch']: print("    - " + s)
    else:
        print("\n  No room mismatches.")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Commit to DB (default: dry run)")
    args = parser.parse_args()
    asyncio.run(run(args.write))
