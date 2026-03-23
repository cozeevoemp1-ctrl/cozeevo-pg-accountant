"""Sync tenants from Excel History sheet to Supabase. Idempotent."""
import openpyxl, os, asyncio
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

def parse_mobile(v):
    if not v: return None
    s = str(v).replace(' ','').replace('.0','').strip()
    if len(s) == 10 and s.isdigit(): return '+91' + s
    if len(s) > 10 and s.isdigit(): return '+' + s
    return None

def parse_amt(v):
    if not v: return 0
    if isinstance(v, (int, float)): return float(v)
    s = str(v).replace(',','').strip()
    if s in ['-','Nil','Eqaro','']: return 0
    try: return float(s)
    except: return 0

wb = openpyxl.load_workbook('Cozeevo Monthly stay (4).xlsx', read_only=True, data_only=True)
ws = wb['History']
rows = list(ws.iter_rows(values_only=True))
data = [r for r in rows[1:] if r[1] and str(r[0] or '').strip()]

async def run():
    engine = create_async_engine(os.getenv('DATABASE_URL'))
    async with engine.begin() as conn:
        # Existing tenancies
        r = await conn.execute(text(
            "SELECT lower(trim(tn.name)), r.room_number FROM tenancies t "
            "JOIN tenants tn ON tn.id = t.tenant_id JOIN rooms r ON r.id = t.room_id"
        ))
        existing = set((row[0], row[1]) for row in r.fetchall())

        # Room lookup
        r = await conn.execute(text(
            "SELECT r.id, r.room_number, p.name FROM rooms r JOIN properties p ON p.id = r.property_id"
        ))
        room_lookup = {}
        for row in r.fetchall():
            prop = 'THOR' if 'THOR' in row[2].upper() else 'HULK'
            room_lookup[(row[1], prop)] = row[0]

        created_t, created_y, skipped = 0, 0, 0

        for row in data:
            name = str(row[1] or '').strip()
            room_num = str(row[0] or '').strip().replace('.0','')
            status_raw = str(row[16] or '').strip().upper()
            sharing = str(row[12] or '').strip().lower()
            block = str(row[17] or '').strip().upper()
            mobile = parse_mobile(row[3])
            checkin = row[4] if isinstance(row[4], datetime) else None
            gender = str(row[2] or '').strip().lower()
            deposit = parse_amt(row[6])
            maintenance = parse_amt(row[7])
            rent = parse_amt(row[9])
            feb_rent = parse_amt(row[10])
            may_rent = parse_amt(row[11])
            booking = parse_amt(row[5])

            if not name or status_raw in ['', 'CANCELLED']:
                continue
            if (name.lower(), room_num) in existing:
                continue

            if status_raw == 'CHECKIN': db_status = 'active'
            elif status_raw == 'EXIT': db_status = 'exited'
            elif status_raw == 'NO SHOW': db_status = 'no_show'
            else: continue

            if sharing not in ('single','double','triple','premium'):
                sharing = 'double'

            prop = block if block in ['THOR','HULK'] else 'THOR'
            room_id = room_lookup.get((room_num, prop))
            if room_num == '523/219':
                room_id = room_lookup.get(('523', prop)) or room_lookup.get(('219', prop))
            if room_num == 'May':
                skipped += 1; continue
            if not room_id:
                print(f"  SKIP no room: {room_num} {name} ({prop})")
                skipped += 1; continue

            # Find or create tenant
            r = await conn.execute(text(
                "SELECT id FROM tenants WHERE lower(trim(name)) = :n"
            ), {'n': name.lower()})
            t_row = r.fetchone()
            if t_row:
                tenant_id = t_row[0]
            else:
                g = gender if gender in ('male','female') else None
                r = await conn.execute(text(
                    "INSERT INTO tenants (name, phone, gender) VALUES (:name, :phone, :gender) RETURNING id"
                ), {'name': name, 'phone': mobile, 'gender': g})
                tenant_id = r.fetchone()[0]
                created_t += 1

            current_rent = may_rent if may_rent > 0 else (feb_rent if feb_rent > 0 else rent)
            from datetime import date as date_type
            checkin_date = checkin.date() if isinstance(checkin, datetime) else date_type(2026, 1, 1)

            await conn.execute(text(
                "INSERT INTO tenancies (tenant_id, room_id, stay_type, sharing_type, status, checkin_date, "
                "booking_amount, security_deposit, maintenance_fee, agreed_rent) "
                "VALUES (:tid, :rid, 'monthly', :sharing, :status, :checkin, :booking, :deposit, :maint, :rent)"
            ), {
                'tid': tenant_id, 'rid': room_id, 'sharing': sharing, 'status': db_status,
                'checkin': checkin_date, 'booking': booking, 'deposit': deposit,
                'maint': maintenance, 'rent': current_rent
            })
            created_y += 1
            print(f"  + {room_num:<8} {name:<25} {db_status:<8} {sharing}")

        print(f"\nCreated {created_t} tenants, {created_y} tenancies, skipped {skipped}")

        # Final counts
        for st in ['active', 'no_show', 'exited']:
            r = await conn.execute(text(f"SELECT count(*) FROM tenancies WHERE status='{st}'"))
            print(f"  {st}: {r.scalar()}")

        # Occupancy
        r = await conn.execute(text(
            "SELECT count(*) FROM tenancies t JOIN rooms r ON r.id=t.room_id "
            "WHERE r.is_staff_room=FALSE AND t.status='active'"
        ))
        active = r.scalar()
        r = await conn.execute(text(
            "SELECT count(*) FROM tenancies t JOIN rooms r ON r.id=t.room_id "
            "WHERE r.is_staff_room=FALSE AND t.status='active' AND t.sharing_type='premium'"
        ))
        prem = r.scalar()
        r = await conn.execute(text(
            "SELECT count(*) FROM tenancies t JOIN rooms r ON r.id=t.room_id "
            "WHERE r.is_staff_room=FALSE AND t.status='no_show'"
        ))
        ns = r.scalar()

        regular = active - prem
        beds = regular + prem * 2
        print(f"\nOCCUPANCY:")
        print(f"  Checked-in: {active} ({regular} regular + {prem} premium)")
        print(f"  Active beds: {beds}")
        print(f"  No-show: {ns}")
        print(f"  Total beds held: {beds + ns}")
        print(f"  Capacity: 291")
        print(f"  Vacant: {291 - beds - ns}")

asyncio.run(run())
