"""Add Akshat (room 416, +917796277597) to DB, then un-void Lenin Das pmt 16229."""
import asyncio, os, sys, re
from datetime import date
from decimal import Decimal
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.database.models import Tenant, Tenancy, TenancyStatus, StayType, Payment, PaymentMode, PaymentFor, RentSchedule, RentStatus

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE = "credentials/gsheets_service_account.json"
MAY = date(2026, 5, 1)

def pn(v):
    if not v: return 0.0
    try: return float(str(v).replace(',', '').strip())
    except: return 0.0

def norm_phone(raw):
    d = re.sub(r'\D', '', str(raw or ''))
    if d.startswith('91') and len(d) == 12: d = d[2:]
    return '+91' + d if len(d) == 10 else ''

async def run():
    # 1. Read Akshat from sheet
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SOURCE_SHEET_ID)
    ws = sh.worksheet('Long term')
    rows = ws.get_all_values()
    akshat_row = None
    for r in rows[1:]:
        phone = norm_phone(r[3]) if len(r) > 3 else ''
        if phone == '+917796277597' or (len(r) > 1 and 'akshat' in r[1].lower()):
            akshat_row = r
            print(f"Found in sheet: room={r[0]} name={r[1]} phone={r[3]} upi={r[25] if len(r)>25 else '?'} cash={r[26] if len(r)>26 else '?'}")
            break

    if not akshat_row:
        print("Akshat not found in sheet")
        return

    may_upi = pn(akshat_row[25]) if len(akshat_row) > 25 else 0
    may_cash = pn(akshat_row[26]) if len(akshat_row) > 26 else 0
    print(f"May UPI: {may_upi}  May Cash: {may_cash}")

    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+asyncpg://', 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        # 2. Find room 416
        room = (await s.execute(text("SELECT id FROM rooms WHERE room_number='416' LIMIT 1"))).fetchone()
        if not room:
            print("Room 416 not found!")
            return
        room_id = room[0]
        print(f"Room 416 id={room_id}")

        # 3. Add tenant Akshat
        existing = (await s.execute(text("SELECT id FROM tenants WHERE phone='+917796277597'"))).fetchone()
        if existing:
            print(f"Tenant already exists: id={existing[0]}")
            tenant_id = existing[0]
        else:
            r = await s.execute(text(
                "INSERT INTO tenants (name, phone, gender) VALUES ('Akshat', '+917796277597', 'male') RETURNING id"
            ))
            tenant_id = r.fetchone()[0]
            print(f"Created tenant Akshat id={tenant_id}")

        # 4. Add tenancy (active, May 1 checkin, agreed_rent = total paid)
        agreed_rent = int(may_upi + may_cash)
        existing_t = (await s.execute(text(
            "SELECT id FROM tenancies WHERE tenant_id=:tid AND status='active'"), {'tid': tenant_id}
        )).fetchone()
        if existing_t:
            print(f"Tenancy already exists: id={existing_t[0]}")
            tenancy_id = existing_t[0]
        else:
            r = await s.execute(text("""
                INSERT INTO tenancies (tenant_id, room_id, stay_type, status, checkin_date, agreed_rent,
                    security_deposit, maintenance_fee, lock_in_months, sharing_type)
                VALUES (:tid, :rid, 'monthly', 'active', '2026-05-01', :rent, 0, 0, 0, 'double')
                RETURNING id
            """), {'tid': tenant_id, 'rid': room_id, 'rent': agreed_rent})
            tenancy_id = r.fetchone()[0]
            print(f"Created tenancy id={tenancy_id} agreed_rent={agreed_rent}")

        # 5. Create rent schedule for May
        rs_exists = (await s.execute(text(
            "SELECT id FROM rent_schedule WHERE tenancy_id=:tid AND period_month='2026-05-01'"),
            {'tid': tenancy_id}
        )).fetchone()
        if not rs_exists:
            await s.execute(text("""
                INSERT INTO rent_schedule (tenancy_id, period_month, rent_due, maintenance_due, status, due_date)
                VALUES (:tid, '2026-05-01', :rent, 0, 'pending', '2026-05-01')
            """), {'tid': tenancy_id, 'rent': agreed_rent})
            print(f"Created rent_schedule for May, rent_due={agreed_rent}")

        # 6. Un-void Lenin Das pmt 16229
        await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
        r2 = await s.execute(text(
            "UPDATE payments SET is_void=false, notes=replace(notes, ' [VOIDED: dup of booking advance -- Z/AA import bug 2026-05-16]', '') || ' [UN-VOIDED: confirmed May rent 2026-05-16]' WHERE id=16229 AND is_void=true"
        ))
        print(f"Lenin Das pmt 16229 un-voided: {r2.rowcount} rows")

        await s.commit()
        print("\nAll done. Run _import_may_payments.py --write next.")

    await engine.dispose()

asyncio.run(run())
