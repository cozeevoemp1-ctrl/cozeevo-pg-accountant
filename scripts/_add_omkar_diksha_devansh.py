"""
1. Omkar deodher (room 616, +917888016785) — read check-in date + rent from Google Sheet, add to DB
2. Diksha Bhartia + Devansh — already in room 000, set check-in date to May 30 from sheet
Then re-run import to pick up their May payments.

Usage:
    python scripts/_add_omkar_diksha_devansh.py           # dry run
    python scripts/_add_omkar_diksha_devansh.py --write   # commit
"""
import asyncio, os, re, sys, argparse
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.database.models import (
    Tenant, Tenancy, Payment, RentSchedule, Room,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus,
)

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE = "credentials/gsheets_service_account.json"
MAY = date(2026, 5, 1)
MAY_30 = date(2026, 5, 30)

# Long term tab column indices (0-based, from _import_may_payments.py + clean_and_load.py)
COL_ROOM     = 0
COL_NAME     = 1
COL_PHONE    = 3
COL_CHECKIN  = 4   # col 5 in 1-based = check-in date
COL_RENT_MO  = 9   # col 10 = monthly rent
COL_RENT_MAY = 11  # col 12 = May rent
COL_SHARING  = 12  # col 13 = sharing type
COL_MAY_UPI  = 25  # Z
COL_MAY_CASH = 26  # AA


def norm_phone(raw):
    d = re.sub(r'\D', '', str(raw or ''))
    if d.startswith('91') and len(d) == 12:
        d = d[2:]
    return '+91' + d if len(d) == 10 else ''


def pn(v):
    if not v: return 0.0
    s = str(v).replace(',', '').strip()
    try: return float(s)
    except: return 0.0


def parse_checkin(v):
    """Try to parse a date from a cell value."""
    if not v: return None
    if isinstance(v, date): return v
    s = str(v).strip()
    # Try common formats: "01-May-26", "1/5/26", "2026-05-01", "May 1 2026"
    import re as _re
    month_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                 'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
    # DD-Mon-YY or DD-Mon-YYYY
    m = _re.match(r'(\d{1,2})[-/]([A-Za-z]{3})[-/](\d{2,4})', s)
    if m:
        d_, mo, yr = int(m.group(1)), month_map.get(m.group(2).lower(), 0), int(m.group(3))
        if yr < 100: yr += 2000
        if mo: return date(yr, mo, d_)
    # YYYY-MM-DD
    m = _re.match(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # D/M/YY
    m = _re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', s)
    if m:
        d_, mo, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100: yr += 2000
        return date(yr, mo, d_)
    return None


def read_sheet():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SOURCE_SHEET_ID).worksheet('Long term')
    return ws.get_all_values()


async def run(write: bool):
    print("Reading source sheet...")
    rows = read_sheet()

    # Find Omkar, Diksha, Devansh by phone / name
    omkar_row = diksha_row = devansh_row = None
    for r in rows[1:]:
        if not r[COL_NAME].strip(): continue
        phone = norm_phone(r[COL_PHONE])
        name_lower = r[COL_NAME].strip().lower()
        if phone == '+917888016785' or 'omkar' in name_lower and 'deodher' in name_lower:
            omkar_row = r
        if 'diksha' in name_lower and 'bhart' in name_lower:
            diksha_row = r
        if 'devansh' in name_lower:
            devansh_row = r

    print(f"Omkar row found:   {bool(omkar_row)}")
    print(f"Diksha row found:  {bool(diksha_row)}")
    print(f"Devansh row found: {bool(devansh_row)}")

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as s:
        # ── 1. OMKAR DEODHER — add to room 616 ───────────────────────────────
        print("\n── OMKAR DEODHER (room 616) ──")

        if omkar_row:
            name    = omkar_row[COL_NAME].strip()
            phone   = norm_phone(omkar_row[COL_PHONE])
            checkin = parse_checkin(omkar_row[COL_CHECKIN]) or MAY
            rent_mo = pn(omkar_row[COL_RENT_MO])
            rent_may = pn(omkar_row[COL_RENT_MAY])
            rent    = rent_may if rent_may > 0 else rent_mo
            sharing = omkar_row[COL_SHARING].strip() if len(omkar_row) > COL_SHARING else 'double'
            may_upi  = pn(omkar_row[COL_MAY_UPI])
            may_cash = pn(omkar_row[COL_MAY_CASH])

            print(f"  Name:     {name}")
            print(f"  Phone:    {phone}")
            print(f"  Check-in: {checkin}")
            print(f"  Rent:     Rs.{int(rent):,}")
            print(f"  Sharing:  {sharing}")
            print(f"  May UPI:  Rs.{int(may_upi):,}  May Cash: Rs.{int(may_cash):,}")

            existing = await s.scalar(select(Tenant).where(Tenant.phone == phone))
            if existing:
                print(f"  Already in DB: id={existing.id} — skipping")
            else:
                room = await s.scalar(select(Room).where(Room.room_number == "616"))
                if not room:
                    print("  ERROR: Room 616 not found!")
                else:
                    print(f"  Room 616: id={room.id} max_occ={room.max_occupancy}")
                    if write:
                        t = Tenant(name=name, phone=phone)
                        s.add(t)
                        await s.flush()

                        tn = Tenancy(
                            tenant_id=t.id, room_id=room.id,
                            status=TenancyStatus.active,
                            checkin_date=checkin,
                            agreed_rent=int(rent),
                            security_deposit=0, maintenance_fee=0,
                            stay_type="monthly",
                            sharing_type=sharing.lower() if sharing else 'double',
                        )
                        s.add(tn)
                        await s.flush()

                        rs = RentSchedule(
                            tenancy_id=tn.id, period_month=MAY,
                            rent_due=int(rent), paid_amount=0,
                            status=RentStatus.unpaid,
                        )
                        s.add(rs)

                        # Add May payments if present
                        if may_cash > 0:
                            s.add(Payment(
                                tenancy_id=tn.id, amount=int(may_cash),
                                payment_mode=PaymentMode.cash,
                                for_type=PaymentFor.rent,
                                payment_date=MAY, period_month=MAY, is_void=False,
                                notes="Added by _add_omkar_diksha_devansh.py",
                            ))
                        if may_upi > 0:
                            s.add(Payment(
                                tenancy_id=tn.id, amount=int(may_upi),
                                payment_mode=PaymentMode.upi,
                                for_type=PaymentFor.rent,
                                payment_date=MAY, period_month=MAY, is_void=False,
                                notes="Added by _add_omkar_diksha_devansh.py",
                            ))

                        print(f"  Added: tenant={t.id}, tenancy={tn.id}, RS for May, payments added")
        else:
            print("  Not found in sheet — check name/phone")

        # ── 2. DIKSHA + DEVANSH — set check-in May 30, stay in room 000 ──────
        for label, row_data in [("DIKSHA BHARTIA", diksha_row), ("DEVANSH", devansh_row)]:
            print(f"\n── {label} ──")
            if not row_data:
                print("  Not found in sheet")
                continue

            phone = norm_phone(row_data[COL_PHONE])
            name  = row_data[COL_NAME].strip()
            print(f"  Name: {name}  Phone: {phone}")

            tenant = await s.scalar(select(Tenant).where(Tenant.phone == phone))
            if not tenant:
                # Try by name
                tenant = await s.scalar(select(Tenant).where(
                    Tenant.name.ilike(f"%{name.split()[0]}%")
                ))
            if not tenant:
                print(f"  Not found in DB by phone {phone} or name {name}")
                continue

            tenancy = await s.scalar(
                select(Tenancy)
                .where(Tenancy.tenant_id == tenant.id)
                .order_by(Tenancy.id.desc())
            )
            if not tenancy:
                print(f"  No tenancy found for {name}")
                continue

            room = await s.scalar(select(Room).where(Room.id == tenancy.room_id))
            room_num = room.room_number if room else "?"
            print(f"  DB: tenant={tenant.id} tenancy={tenancy.id} room={room_num} checkin={tenancy.checkin_date}")
            print(f"  -> Set check-in to May 30 2026 (stays in room {room_num})")

            if write:
                tenancy.checkin_date = MAY_30  # type: ignore[assignment]
                print(f"  Updated check-in to 2026-05-30")

        if write:
            await s.commit()
            print("\nAll changes committed.")
        else:
            print("\n[DRY RUN] — pass --write to commit")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
