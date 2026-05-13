"""
Compare April + May 2026 cash/UPI per tenant between source sheet and DB.
Updates DB where sheet > DB (adds missing payments).

Source sheet: 1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0  "Long term"
  Col  0 = Room
  Col  1 = Name
  Col  3 = Phone
  Col 21 = April Cash
  Col 22 = April UPI
  Col 25 = May UPI
  Col 26 = May Cash

Usage:
    python scripts/_audit_apr_may_payments.py           # dry run — show diffs
    python scripts/_audit_apr_may_payments.py --write   # commit missing payments to DB
"""
import asyncio, os, re, sys, argparse
from datetime import date
from decimal import Decimal

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Tenant, Tenancy, Payment, RentSchedule,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus,
)

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE = "credentials/gsheets_service_account.json"
APR = date(2026, 4, 1)
MAY = date(2026, 5, 1)


def pn(v):
    if not v: return 0.0
    s = str(v).replace(',', '').strip()
    if not re.match(r'^[\d.]+$', s): return 0.0
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
    for i, r in enumerate(rows[1:], start=2):
        # Pad row to ensure enough columns
        while len(r) < 27:
            r.append('')
        name = r[1].strip()
        if not name:
            continue
        apr_cash = pn(r[21])
        apr_upi  = pn(r[22])
        may_upi  = pn(r[25])
        may_cash = pn(r[26])
        if apr_cash == 0 and apr_upi == 0 and may_cash == 0 and may_upi == 0:
            continue
        data.append({
            'row': i,
            'name': name,
            'room': r[0].strip(),
            'phone_raw': r[3].strip(),
            'phone_db': norm_phone(r[3]),
            'apr_cash': apr_cash,
            'apr_upi':  apr_upi,
            'may_cash': may_cash,
            'may_upi':  may_upi,
        })
    return data


async def get_existing_payments(session, month):
    q = await session.execute(text("""
        SELECT p.tenancy_id, p.payment_mode, SUM(p.amount) as total
        FROM payments p
        WHERE p.period_month = :m AND p.for_type = 'rent' AND p.is_void = false
        GROUP BY p.tenancy_id, p.payment_mode
    """), {"m": month})
    result = {}
    for row in q:
        tid = row.tenancy_id
        if tid not in result:
            result[tid] = {'cash': 0.0, 'upi': 0.0}
        result[tid][row.payment_mode] = float(row.total)
    return result


async def ensure_rs(session, tenancy, month, write):
    rs = await session.scalar(
        select(RentSchedule)
        .where(RentSchedule.tenancy_id == tenancy.id, RentSchedule.period_month == month)
    )
    if not rs and write:
        rs = RentSchedule(
            tenancy_id=tenancy.id,
            period_month=month,
            rent_due=tenancy.agreed_rent,
            maintenance_due=Decimal('0'),
            status=RentStatus.pending,
            due_date=month,
            notes="Auto-created by _audit_apr_may_payments.py",
        )
        session.add(rs)
        await session.flush()
    return rs


async def run(write: bool):
    print("=" * 80)
    print("APRIL + MAY 2026 — source sheet vs DB line-by-line audit")
    print("=" * 80)

    print("\nReading source sheet...")
    sheet_data = read_sheet()
    apr_rows_total = [r for r in sheet_data if r['apr_cash'] > 0 or r['apr_upi'] > 0]
    may_rows_total = [r for r in sheet_data if r['may_cash'] > 0 or r['may_upi'] > 0]
    print(f"  {len(apr_rows_total)} rows with April data  (cash={int(sum(r['apr_cash'] for r in sheet_data)):,}  upi={int(sum(r['apr_upi'] for r in sheet_data)):,})")
    print(f"  {len(may_rows_total)} rows with May data    (cash={int(sum(r['may_cash'] for r in sheet_data)):,}  upi={int(sum(r['may_upi'] for r in sheet_data)):,})")

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    stats = {
        'ok': 0,
        'diff': [],        # (name, room, month, mode, sheet, db, delta)
        'no_tenant': [],
        'no_tenancy': [],
        'no_phone': [],
        'added': [],
    }

    # ── Phase 1: read — collect diffs, Payment objects, and missing RS info ──
    payments_to_add: list[Payment] = []
    # {(tenancy_id, month): agreed_rent} for cases where RS may be missing
    rs_needed: dict[tuple, Decimal] = {}

    async with Session() as session:
        apr_existing = await get_existing_payments(session, APR)
        may_existing = await get_existing_payments(session, MAY)

        # Pre-load existing RS for MAY (April RS should already exist)
        may_rs_q = await session.execute(text(
            "SELECT tenancy_id FROM rent_schedule WHERE period_month = '2026-05-01'"
        ))
        may_rs_set = {row[0] for row in may_rs_q}

        for rec in sheet_data:
            phone = rec['phone_db']
            if not phone:
                stats['no_phone'].append(f"{rec['name']} room {rec['room']} (raw: {rec['phone_raw']})")
                continue

            tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == phone)
            )
            if not tenant:
                stats['no_tenant'].append(f"{rec['name']} room {rec['room']} ({phone})")
                continue

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
                stats['no_tenancy'].append(f"{rec['name']} ({phone})")
                continue

            tid = tenancy.id
            checks = [
                (APR, 'cash', rec['apr_cash'], apr_existing.get(tid, {}).get('cash', 0.0)),
                (APR, 'upi',  rec['apr_upi'],  apr_existing.get(tid, {}).get('upi', 0.0)),
                (MAY, 'cash', rec['may_cash'], may_existing.get(tid, {}).get('cash', 0.0)),
                (MAY, 'upi',  rec['may_upi'],  may_existing.get(tid, {}).get('upi', 0.0)),
            ]

            all_ok = True
            needs_write = False
            for month, mode, sheet_amt, db_amt in checks:
                if sheet_amt == 0 and db_amt == 0:
                    continue
                delta = sheet_amt - db_amt
                if abs(delta) < 1:
                    continue
                all_ok = False
                mon_label = "APR" if month == APR else "MAY"
                stats['diff'].append((rec['name'], rec['room'], mon_label, mode, int(sheet_amt), int(db_amt), int(delta)))

                if delta > 0:
                    needs_write = True
                    pm = PaymentMode.cash if mode == 'cash' else PaymentMode.upi
                    payments_to_add.append(Payment(
                        tenancy_id=tenancy.id,
                        amount=Decimal(str(round(delta, 2))),
                        payment_date=month,
                        payment_mode=pm,
                        for_type=PaymentFor.rent,
                        period_month=month,
                        notes=f"{mon_label} source sheet audit [_audit_apr_may_payments.py]",
                    ))
                    stats['added'].append(f"{rec['name']} room {rec['room']} {mon_label} {mode} +{int(delta):,}")

            # Track missing RS rows so Phase 2 can create them
            if needs_write and tid not in may_rs_set:
                rs_needed[(tid, MAY)] = tenancy.agreed_rent

            if all_ok and (rec['apr_cash'] > 0 or rec['apr_upi'] > 0 or rec['may_cash'] > 0 or rec['may_upi'] > 0):
                stats['ok'] += 1

    # ── Phase 2: write — separate session with historical write allowed ────────
    if write and payments_to_add:
        async with Session() as session:
            # April is frozen — must allow historical writes within this transaction
            await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

            # Create missing May RS rows first
            for (tid, month), agreed_rent in rs_needed.items():
                session.add(RentSchedule(
                    tenancy_id=tid,
                    period_month=month,
                    rent_due=agreed_rent,
                    maintenance_due=Decimal('0'),
                    status=RentStatus.pending,
                    due_date=month,
                    notes="Auto-created by _audit_apr_may_payments.py",
                ))

            for p in payments_to_add:
                session.add(p)
            await session.commit()
            print(f"\n  ** COMMITTED {len(payments_to_add)} payments ({len(rs_needed)} RS rows created) **")

    # ── Print results ─────────────────────────────────────────────────────────
    print(f"\n{'─'*80}")
    print(f"LINE-BY-LINE DIFF  (sheet vs DB — sheet amount that differs shown)")
    print(f"{'─'*80}")
    if stats['diff']:
        print(f"{'Name':<25}  {'Rm':5}  {'Mon':3}  {'Mode':4}  {'Sheet':>9}  {'DB':>9}  {'Delta':>9}")
        print(f"{'─'*25}  {'─'*5}  {'─'*3}  {'─'*4}  {'─'*9}  {'─'*9}  {'─'*9}")
        for name, room, mon, mode, sheet, db_a, delta in stats['diff']:
            flag = " << ADD" if delta > 0 else " !! DB > SHEET"
            print(f"{name:<25}  {room:5}  {mon:3}  {mode:4}  {sheet:>9,}  {db_a:>9,}  {delta:>+9,}{flag}")
    else:
        print("  No differences found — DB matches source sheet exactly.")

    print(f"\n{'─'*80}")
    print("SUMMARY")
    print(f"{'─'*80}")
    print(f"  Rows matching DB exactly:  {stats['ok']}")
    print(f"  Rows with differences:     {len(stats['diff'])}")
    print(f"  No phone in sheet:         {len(stats['no_phone'])}")
    print(f"  Tenant not in DB:          {len(stats['no_tenant'])}")
    print(f"  Tenancy not found:         {len(stats['no_tenancy'])}")

    if write:
        print(f"\n  Payments added to DB: {len(stats['added'])}")
        for s in stats['added']: print(f"    + {s}")
    else:
        missing = [d for d in stats['diff'] if d[6] > 0]
        print(f"\n  Payments to add (dry run): {len(missing)}")
        for name, room, mon, mode, sheet, db_a, delta in missing:
            print(f"    + {name} room {room} {mon} {mode} {delta:+,}")

    if stats['no_phone']:
        print(f"\n  NO PHONE (skipped):")
        for s in stats['no_phone']: print(f"    - {s}")
    if stats['no_tenant']:
        print(f"\n  NOT IN DB (need manual add):")
        for s in stats['no_tenant']: print(f"    - {s}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Commit missing payments to DB")
    args = parser.parse_args()
    asyncio.run(run(args.write))
