"""
Full import from Excel → Supabase
Imports: tenants, tenancies, rent_schedule, payments
Reads from: Cozeevo Monthly stay (4).xlsx → History sheet
"""
import os, sys, asyncio, re
from datetime import datetime, date
from decimal import Decimal
import openpyxl
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

EXCEL = "Cozeevo Monthly stay (4).xlsx"

def parse_num(v):
    if not v or str(v).strip() in ('-','Nil','Eqaro',''): return 0
    if isinstance(v, (int, float)): return float(v)
    s = str(v).replace(',','').strip()
    try: return float(s)
    except: return 0

def parse_date(v):
    if isinstance(v, datetime): return v.date()
    if not v: return None
    s = str(v).strip()
    for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y'):
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None

def parse_mobile(v):
    if not v: return None
    s = re.sub(r'[^0-9]', '', str(v))
    if len(s) >= 10: return s[-10:]
    return s or None

def status_map(s):
    s = str(s).strip().upper()
    if s == 'CHECKIN': return 'active'
    if s == 'EXIT': return 'exited'
    if s == 'NO SHOW': return 'no_show'
    return None

def sharing_map(s):
    s = str(s).strip().lower()
    if s in ('single','double','triple','premium'): return s
    return 'double'

def detect_property(room_num, block_col):
    """Detect property from room number pattern, not just BLOCK column."""
    block = str(block_col).strip().upper()
    rn = str(room_num).strip()
    # Ground floor
    if rn.startswith('G'):
        num = int(re.sub(r'\D','',rn) or 0)
        return 'HULK' if num >= 11 else 'THOR'
    # Floor rooms
    if rn not in ('May','') and not rn.startswith('G'):
        num = int(re.sub(r'\D','',rn.split('/')[0]) or 0)
        unit = num % 100
        if unit >= 13: return 'HULK'
        if unit <= 12 and unit >= 1: return 'THOR'
    return block if block in ('THOR','HULK') else 'THOR'


async def run():
    # Read Excel
    wb = openpyxl.load_workbook(EXCEL, read_only=True, data_only=True)
    ws = wb['History']
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    data = [r for r in rows[1:] if r[1] and str(r[1]).strip()]
    print(f"Excel: {len(data)} rows with data")

    engine = create_async_engine(os.getenv('DATABASE_URL'))
    async with engine.begin() as conn:
        # Room lookup
        r = await conn.execute(text(
            'SELECT r.id, r.room_number, p.name FROM rooms r JOIN properties p ON p.id=r.property_id'
        ))
        room_db = {}
        for row in r.fetchall():
            prop = 'THOR' if 'THOR' in row[2].upper() else 'HULK'
            room_db[(row[1], prop)] = row[0]

        stats = {'tenants': 0, 'tenancies': 0, 'rent_schedule': 0, 'payments': 0, 'skipped': 0}
        used_phones = set()

        for row in data:
            name = str(row[1]).strip()
            room_num = str(row[0] or '').strip().replace('.0','')
            status_raw = str(row[16] or '').strip().upper()
            db_status = status_map(status_raw)
            if not db_status:
                stats['skipped'] += 1
                continue

            sharing = sharing_map(row[12] if row[12] else 'double')
            prop = detect_property(room_num, row[17] if row[17] else '')
            mobile = parse_mobile(row[3])
            checkin = parse_date(row[4])
            gender = str(row[2] or '').strip().lower()
            deposit = parse_num(row[6])
            maintenance = parse_num(row[7])
            rent = parse_num(row[9])
            feb_rent = parse_num(row[10])
            may_rent = parse_num(row[11])
            booking = parse_num(row[5])
            current_rent = may_rent if may_rent > 0 else (feb_rent if feb_rent > 0 else rent)

            # Find room
            room_id = room_db.get((room_num, prop))
            if room_num == '523/219':
                room_id = room_db.get(('523', 'HULK')) or room_db.get(('219', 'HULK'))
            if room_num in ('May', '') or not room_id:
                room_id = room_db.get(('G20', 'HULK'))  # placeholder
            if not room_id:
                other = 'HULK' if prop == 'THOR' else 'THOR'
                room_id = room_db.get((room_num, other))
            if not room_id:
                print(f"  SKIP no room: {room_num} {name} ({prop})")
                stats['skipped'] += 1
                continue

            # Create tenant — use name+room+checkin for truly unique dummy phone
            phone = mobile or f'000{abs(hash(name + room_num + str(checkin))) % 100000000:08d}'
            # Ensure uniqueness with counter
            if phone in used_phones:
                phone = f'000{abs(hash(name + room_num + str(stats["tenants"]))) % 100000000:08d}'
            used_phones.add(phone)
            r = await conn.execute(text(
                "INSERT INTO tenants (name, phone, gender) VALUES (:n, :p, :g) RETURNING id"
            ), {'n': name, 'p': phone, 'g': gender if gender in ('male','female') else None})
            tenant_id = r.scalar()
            stats['tenants'] += 1

            # Create tenancy
            checkin_dt = checkin if checkin else date(2026, 1, 1)
            # Collect comments from text columns
            comments_parts = []
            if row[14] and str(row[14]).strip() and str(row[14]).strip() != '-':
                comments_parts.append(str(row[14]).strip())
            # March Balance text notes
            if row[30] and not isinstance(row[30], (int, float)) and str(row[30]).strip():
                mb = str(row[30]).strip()
                if not mb.replace('.','').replace('-','').isdigit():
                    comments_parts.append(f"[Mar bal] {mb}")
            # March Cash text notes
            if row[31] and not isinstance(row[31], (int, float)) and str(row[31]).strip():
                mc = str(row[31]).strip()
                if not mc.replace('.','').replace('-','').isdigit():
                    comments_parts.append(f"[Mar cash] {mc}")
            notes = ' | '.join(comments_parts) if comments_parts else None

            r = await conn.execute(text("""
                INSERT INTO tenancies (tenant_id, room_id, stay_type, sharing_type, status, checkin_date,
                    booking_amount, security_deposit, maintenance_fee, agreed_rent, notes)
                VALUES (:tid, :rid, 'monthly', :sh, :st, :ci, :bk, :dep, :mnt, :rent, :notes)
                RETURNING id
            """), {'tid': tenant_id, 'rid': room_id, 'sh': sharing, 'st': db_status,
                   'ci': checkin_dt, 'bk': booking, 'dep': deposit, 'mnt': maintenance,
                   'rent': current_rent, 'notes': notes})
            tenancy_id = r.scalar()
            stats['tenancies'] += 1

            # Rent schedule for each month
            months = [
                (20, date(2025,12,1)),  # DEC RENT
                (21, date(2026,1,1)),   # JAN RENT
                (25, date(2026,2,1)),   # FEB RENT
                (26, date(2026,3,1)),   # MARCH RENT
            ]
            for col_idx, period in months:
                if col_idx >= len(row) or not row[col_idx]: continue
                rent_status = str(row[col_idx]).strip().upper()
                if rent_status in ('NO SHOW','EXIT','CANCELLED',''): continue

                # Rent for this period
                if period >= date(2026,5,1) and may_rent > 0:
                    period_rent = may_rent
                elif period >= date(2026,2,1) and feb_rent > 0:
                    period_rent = feb_rent
                else:
                    period_rent = rent
                if period_rent <= 0: continue

                is_paid = rent_status == 'PAID'
                rs_status = 'paid' if is_paid else 'pending'
                await conn.execute(text("""
                    INSERT INTO rent_schedule (tenancy_id, period_month, rent_due, status)
                    VALUES (:tid, :pm, :amt, :st)
                """), {'tid': tenancy_id, 'pm': period, 'amt': period_rent, 'st': rs_status})
                stats['rent_schedule'] += 1

            # Payments from Cash/UPI columns
            # Jan: col 23=cash, 24=upi; Feb: col 28=cash, 29=upi; Mar: col 31=cash, 32=upi
            pay_cols = [
                (23, 24, date(2026,1,15), 'jan'),
                (28, 29, date(2026,2,15), 'feb'),
                (31, 32, date(2026,3,15), 'mar'),
            ]
            for cash_col, upi_col, pay_date, label in pay_cols:
                if cash_col >= len(row): continue
                cash = parse_num(row[cash_col])
                upi = parse_num(row[upi_col]) if upi_col < len(row) else 0

                if cash > 0:
                    await conn.execute(text("""
                        INSERT INTO payments (tenancy_id, amount, payment_mode, payment_date, period_month, for_type, notes)
                        VALUES (:tid, :amt, 'cash', :dt, :pm, 'rent', :pl)
                    """), {'tid': tenancy_id, 'amt': cash, 'dt': pay_date, 'pm': pay_date.replace(day=1), 'pl': label})
                    stats['payments'] += 1
                if upi > 0:
                    await conn.execute(text("""
                        INSERT INTO payments (tenancy_id, amount, payment_mode, payment_date, period_month, for_type, notes)
                        VALUES (:tid, :amt, 'upi', :dt, :pm, 'rent', :pl)
                    """), {'tid': tenancy_id, 'amt': upi, 'dt': pay_date, 'pm': pay_date.replace(day=1), 'pl': label})
                    stats['payments'] += 1

        print(f"\nImport complete:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

        # Final DB counts
        print("\nDB totals:")
        for tbl in ['tenants','tenancies','rent_schedule','payments']:
            r = await conn.execute(text(f'SELECT count(*) FROM {tbl}'))
            print(f"  {tbl}: {r.scalar()}")

        # Occupancy check
        r = await conn.execute(text("SELECT count(*) FROM tenancies WHERE status='active'"))
        active = r.scalar()
        r = await conn.execute(text("SELECT count(*) FROM tenancies WHERE status='active' AND sharing_type='premium'"))
        prem = r.scalar()
        r = await conn.execute(text("SELECT count(*) FROM tenancies WHERE status='no_show'"))
        ns = r.scalar()
        beds = (active - prem) + prem * 2
        print(f"\nOccupancy: {active} active ({active-prem} regular + {prem} premium) = {beds} beds")
        print(f"No-show: {ns}")
        print(f"Total beds held: {beds + ns} / 291")

asyncio.run(run())
