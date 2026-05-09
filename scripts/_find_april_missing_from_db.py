"""
Find people in April Month Collection sheet (Long term + Day wise):
  1. NOT in DB at all (missing tenants)
  2. Exited in sheet but still ACTIVE in DB (missed checkouts)

Usage: python scripts/_find_april_missing_from_db.py
"""
import asyncio, os, re, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Tenant, Tenancy, TenancyStatus, Room

APRIL_SHEET = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE  = "credentials/gsheets_service_account.json"

# Long term tab column indices (0-based)
LT = {
    'room': 0, 'name': 1, 'gender': 2, 'phone': 3, 'checkin': 4,
    'booking': 5, 'deposit': 6, 'maintenance': 7, 'daywise_rent': 8,
    'monthly_rent': 9, 'from_feb': 10, 'from_may': 11, 'sharing': 12,
    'paid_date': 13, 'comments': 14, 'staff': 15, 'checkinout': 16,
    'block': 17, 'floor': 18, 'april': 19, 'march_bal': 20,
    'april_cash': 21, 'april_upi': 22, 'april_bal': 23,
    'may': 24, 'may_upi': 25, 'may_cash': 26,
    'june_bal': 27, 'food': 28, 'complaints': 29, 'vacation': 30, 'refund': 31,
}

# Day wise tab column indices
DW = {'room': 0, 'name': 1, 'phone': 2, 'checkin': 3}


def pn(v):
    try: return float(str(v).replace(',', '').strip() or 0)
    except: return 0.0


def norm_phone(raw):
    d = re.sub(r'\D', '', str(raw or ''))
    if d.startswith('91') and len(d) == 12:
        d = d[2:]
    return '+91' + d if len(d) == 10 else ''


def is_exit(val):
    return 'exit' in str(val).lower()


def get(r, col, key=None):
    idx = LT[key] if key else col
    return r[idx].strip() if len(r) > idx else ''


def read_sheet():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(APRIL_SHEET)

    # Long term tab
    lt_ws = sh.worksheet('Long term')
    lt_rows = lt_ws.get_all_values()
    lt_people = []
    for r in lt_rows[1:]:
        name = get(r, None, 'name')
        if not name:
            continue
        phone   = norm_phone(get(r, None, 'phone'))
        room    = get(r, None, 'room')
        checkinout = get(r, None, 'checkinout').upper()   # CHECKIN / EXIT
        april_status = get(r, None, 'april').upper()       # PAID / PARTIAL / Exit
        may_status   = get(r, None, 'may').upper()         # PAID / PARTIAL / Exit
        april_bal    = get(r, None, 'april_bal')           # sometimes "exit may 23th"
        apr_cash = pn(get(r, None, 'april_cash'))
        apr_upi  = pn(get(r, None, 'april_upi'))
        may_cash = pn(get(r, None, 'may_cash'))
        may_upi  = pn(get(r, None, 'may_upi'))
        lt_people.append({
            'tab': 'Long term', 'name': name, 'room': room, 'phone': phone,
            'checkinout': checkinout, 'april': april_status, 'may': may_status,
            'april_bal_note': april_bal,
            'apr_cash': apr_cash, 'apr_upi': apr_upi,
            'may_cash': may_cash, 'may_upi': may_upi,
        })

    # Day wise tab
    dw_ws = sh.worksheet('Day wise')
    dw_rows = dw_ws.get_all_values()
    dw_people = []
    for r in dw_rows[1:]:
        name = r[DW['name']].strip() if len(r) > DW['name'] else ''
        if not name:
            continue
        phone = norm_phone(r[DW['phone']] if len(r) > DW['phone'] else '')
        room  = r[DW['room']].strip() if len(r) > DW['room'] else ''
        dw_people.append({'tab': 'Day wise', 'name': name, 'room': room, 'phone': phone})

    print(f"Long term: {len(lt_people)} rows | Day wise: {len(dw_people)} rows")
    return lt_people, dw_people


async def run():
    lt_people, dw_people = read_sheet()

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        tenants = (await session.execute(select(Tenant))).scalars().all()
        db_phones = {t.phone: t for t in tenants if t.phone}
        db_names  = {t.name.lower().strip(): t for t in tenants}

        # Get all active tenancies with room info
        active_rows = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status == TenancyStatus.active)
        )).all()
        active_by_phone = {}
        active_by_name  = {}
        for tn, te, rm in active_rows:
            if te.phone:
                active_by_phone[te.phone] = (tn, te, rm)
            active_by_name[te.name.lower().strip()] = (tn, te, rm)

    await engine.dispose()

    print(f"DB: {len(db_phones)} tenants total | {len(active_by_phone)} active tenancies\n")

    # ── 1. MISSING FROM DB (Long term) ────────────────────────────────────────
    truly_missing_lt = []
    name_mismatch_lt = []
    for p in lt_people:
        phone_match = p['phone'] and p['phone'] in db_phones
        name_match  = p['name'].lower().strip() in db_names
        if not phone_match and not name_match:
            truly_missing_lt.append(p)
        elif not phone_match and name_match:
            name_mismatch_lt.append(p)

    print("=" * 65)
    print(f"1. LONG TERM — Truly NOT in DB: {len(truly_missing_lt)}")
    print("=" * 65)
    for p in truly_missing_lt:
        paid = f"Apr cash={int(p['apr_cash'])} upi={int(p['apr_upi'])}" if (p['apr_cash'] or p['apr_upi']) else "Apr:no payment"
        print(f"  {p['name']:<35} room={p['room']:<10} phone={p['phone']:<15} {paid}")

    # ── 2. EXITED IN SHEET BUT ACTIVE IN DB ───────────────────────────────────
    missed_exits = []
    for p in lt_people:
        sheet_exited = (
            p['checkinout'] == 'EXIT'
            or is_exit(p['april'])
            or is_exit(p['may'])
        )
        if not sheet_exited:
            continue
        phone = p['phone']
        name_key = p['name'].lower().strip()
        # Check if still active in DB
        active_rec = active_by_phone.get(phone) or active_by_name.get(name_key)
        if active_rec:
            tn, te, rm = active_rec
            exit_note = []
            if p['checkinout'] == 'EXIT': exit_note.append('col16=EXIT')
            if is_exit(p['april']): exit_note.append(f"april={p['april']}")
            if is_exit(p['may']):   exit_note.append(f"may={p['may']}")
            if p['april_bal_note'] and is_exit(p['april_bal_note']):
                exit_note.append(f"note={p['april_bal_note']}")
            missed_exits.append({
                'sheet': p, 'tenancy_id': tn.id, 'db_name': te.name,
                'db_room': rm.room_number, 'exit_signals': ', '.join(exit_note)
            })

    print()
    print("=" * 65)
    print(f"2. EXITED IN SHEET BUT STILL ACTIVE IN DB: {len(missed_exits)}")
    print("=" * 65)
    for m in missed_exits:
        s = m['sheet']
        may_note = f"  may_note={s['april_bal_note']}" if s['april_bal_note'] else ''
        print(f"  {m['db_name']:<35} room={m['db_room']:<6} tenancy={m['tenancy_id']:<6} [{m['exit_signals']}]{may_note}")

    # ── 3. MAY BALANCE NOTE — upcoming exits this month ───────────────────────
    may_exits_noted = []
    for p in lt_people:
        note = p['april_bal_note'].lower()
        if 'exit' in note and 'may' in note:
            # Active in DB or not?
            phone = p['phone']
            name_key = p['name'].lower().strip()
            active_rec = active_by_phone.get(phone) or active_by_name.get(name_key)
            may_exits_noted.append({
                'name': p['name'], 'room': p['room'],
                'note': p['april_bal_note'],
                'db_active': bool(active_rec),
            })

    print()
    print("=" * 65)
    print(f"3. MAY BALANCE COLUMN — 'exit may Xth' notes: {len(may_exits_noted)}")
    print("=" * 65)
    for m in may_exits_noted:
        db_s = "ACTIVE in DB" if m['db_active'] else "not in DB"
        print(f"  {m['name']:<35} room={m['room']:<8} note='{m['note']}'  ({db_s})")

    # ── 4. DAY WISE MISSING ───────────────────────────────────────────────────
    dw_missing = []
    for p in dw_people:
        phone_match = p['phone'] and p['phone'] in db_phones
        name_match  = p['name'].lower().strip() in db_names
        if not phone_match and not name_match:
            dw_missing.append(p)

    print()
    print("=" * 65)
    print(f"4. DAY WISE — Truly NOT in DB: {len(dw_missing)}")
    print("=" * 65)
    for p in dw_missing:
        print(f"  {p['name']:<35} room={p['room']:<8} phone={p['phone']}")

    print()
    print("SUMMARY:")
    print(f"  Long term missing from DB entirely:  {len(truly_missing_lt)}")
    print(f"  Exited in sheet, still active in DB: {len(missed_exits)}")
    print(f"  May exit notes (upcoming/recent):    {len(may_exits_noted)}")
    print(f"  Day wise missing from DB:            {len(dw_missing)}")


if __name__ == '__main__':
    asyncio.run(run())
