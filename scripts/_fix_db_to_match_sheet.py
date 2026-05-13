"""
Fix DB payments to exactly match source sheet for April + May 2026.

Actions:
  1. Add 2 missing Dhruv payments (APR + MAY)
  2. Void excess payments wherever DB > sheet

Voiding strategy:
  - Sort by created_at DESC (newest first)
  - Void whole payments until excess is gone
  - If one payment is larger than remaining excess:
      void it, re-add (amount - excess) as a new payment

Usage:
    python scripts/_fix_db_to_match_sheet.py           # dry run
    python scripts/_fix_db_to_match_sheet.py --write   # commit
"""
import asyncio, os, re, sys, argparse
from datetime import date
from decimal import Decimal

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Tenant, Tenancy, Payment, TenancyStatus, PaymentMode, PaymentFor

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
    if d.startswith('91') and len(d) == 12: d = d[2:]
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
        while len(r) < 27: r.append('')
        name = r[1].strip()
        if not name: continue
        apr_cash = pn(r[21]);  apr_upi = pn(r[22])
        may_upi  = pn(r[25]);  may_cash = pn(r[26])
        if apr_cash == 0 and apr_upi == 0 and may_cash == 0 and may_upi == 0:
            continue
        data.append({
            'name': name, 'room': r[0].strip(),
            'phone': norm_phone(r[3]),
            'apr_cash': apr_cash, 'apr_upi': apr_upi,
            'may_cash': may_cash, 'may_upi': may_upi,
        })
    return data


async def get_payments(session, tenancy_id, month, mode):
    r = await session.execute(text("""
        SELECT id, amount FROM payments
        WHERE tenancy_id = :tid AND period_month = :m AND payment_mode = :mo
          AND is_void = false AND for_type = 'rent'
        ORDER BY created_at DESC
    """), {'tid': tenancy_id, 'm': month, 'mo': mode})
    return r.fetchall()


async def run(write: bool):
    print("=" * 70)
    print("FIX DB TO MATCH SHEET — April + May 2026")
    print("=" * 70)

    sheet_data = read_sheet()

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ── Phase 1: collect all actions ─────────────────────────────────────────
    to_add   = []   # Payment objects to insert
    to_void  = []   # payment ids to void

    async with Session() as session:
        apr_ex = {}; may_ex = {}
        for month, ex in [(APR, apr_ex), (MAY, may_ex)]:
            r = await session.execute(text("""
                SELECT p.tenancy_id, p.payment_mode, SUM(p.amount) as total
                FROM payments p
                WHERE p.period_month = :m AND p.for_type = 'rent' AND p.is_void = false
                GROUP BY p.tenancy_id, p.payment_mode
            """), {'m': month})
            for row in r:
                tid = row.tenancy_id
                if tid not in ex: ex[tid] = {'cash': 0.0, 'upi': 0.0}
                ex[tid][row.payment_mode] = float(row.total)

        # Group sheet rows by phone; aggregate same-person entries (multi-row tenants like
        # Priyansh who has two identical rows for two real payments).
        # Skip phones where different names appear — those are distinct tenants who happen
        # to share a phone in the source sheet (room 314 case); can't safely attribute.
        from collections import defaultdict
        phone_groups: dict = defaultdict(list)
        for rec in sheet_data:
            p = rec['phone']
            if not p: continue
            phone_groups[p].append(rec)

        phone_totals: dict = {}
        for phone, rows in phone_groups.items():
            names = {r['name'].strip().lower() for r in rows}
            if len(names) > 1:
                print(f"  SKIP (shared phone {phone}): {', '.join(r['name'] for r in rows)}")
                continue
            phone_totals[phone] = {
                'name':     rows[0]['name'],
                'room':     rows[0]['room'],
                'apr_cash': sum(r['apr_cash'] for r in rows),
                'apr_upi':  sum(r['apr_upi']  for r in rows),
                'may_cash': sum(r['may_cash'] for r in rows),
                'may_upi':  sum(r['may_upi']  for r in rows),
            }

        for phone, rec in phone_totals.items():
            tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == phone)
            )
            if not tenant: continue
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
            if not tenancy: continue

            tid = tenancy.id
            checks = [
                (APR, 'cash', rec['apr_cash'], apr_ex.get(tid, {}).get('cash', 0.0)),
                (APR, 'upi',  rec['apr_upi'],  apr_ex.get(tid, {}).get('upi', 0.0)),
                (MAY, 'cash', rec['may_cash'], may_ex.get(tid, {}).get('cash', 0.0)),
                (MAY, 'upi',  rec['may_upi'],  may_ex.get(tid, {}).get('upi', 0.0)),
            ]

            for month, mode, sheet_amt, db_amt in checks:
                delta = sheet_amt - db_amt
                if abs(delta) < 1: continue
                mon = "APR" if month == APR else "MAY"
                pm = PaymentMode.cash if mode == 'cash' else PaymentMode.upi

                if delta > 0:
                    # DB < sheet → add
                    print(f"  ADD  {rec['name']:25s} {mon} {mode:4s} +{int(delta):,}")
                    to_add.append(Payment(
                        tenancy_id=tid,
                        amount=Decimal(str(round(delta, 2))),
                        payment_date=month,
                        payment_mode=pm,
                        for_type=PaymentFor.rent,
                        period_month=month,
                        notes=f"{mon} sheet fix [_fix_db_to_match_sheet.py]",
                    ))

                else:
                    # DB > sheet → void excess
                    excess = int(-delta)
                    pmts = await get_payments(session, tid, month, mode)
                    remaining = excess
                    print(f"  VOID {rec['name']:25s} {mon} {mode:4s} -{excess:,}  (db={int(db_amt):,} → sheet={int(sheet_amt):,})")
                    for pmt in pmts:
                        if remaining <= 0: break
                        amt = int(pmt.amount)
                        if amt <= remaining:
                            # void whole payment
                            to_void.append((pmt.id, rec['name'], mon, mode, amt, 're-add=0'))
                            remaining -= amt
                        else:
                            # partial — void and re-add remainder
                            keep = amt - remaining
                            to_void.append((pmt.id, rec['name'], mon, mode, amt, f're-add={keep}'))
                            to_add.append(Payment(
                                tenancy_id=tid,
                                amount=Decimal(str(keep)),
                                payment_date=month,
                                payment_mode=pm,
                                for_type=PaymentFor.rent,
                                period_month=month,
                                notes=f"{mon} sheet fix — split from id={pmt.id}",
                            ))
                            remaining = 0

    print(f"\n  Total: {len(to_void)} voids, {len(to_add)} adds")

    # ── Phase 2: write ────────────────────────────────────────────────────────
    if write:
        async with Session() as session:
            await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

            if to_void:
                ids = [v[0] for v in to_void]
                await session.execute(text(
                    "UPDATE payments SET is_void = true WHERE id = ANY(:ids)"
                ), {'ids': ids})

            for p in to_add:
                session.add(p)

            await session.commit()
            print(f"\n  ** COMMITTED: {len(to_void)} voided, {len(to_add)} added **")
    else:
        print("\n  (dry run — no changes)")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
