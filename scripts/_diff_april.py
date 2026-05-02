import asyncio, os, datetime, gspread
from dotenv import load_dotenv
load_dotenv()
import asyncpg

def parse(v):
    v = str(v).strip().replace(',', '').replace('Rs.', '')
    try:
        return int(float(v))
    except:
        return 0

async def main():
    # Source sheet
    gc = gspread.service_account(filename='credentials/gsheets_service_account.json')
    sh = gc.open_by_key('1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0')
    ws = sh.worksheet('Long term')
    srows = ws.get_all_values()
    sheet = {}
    for r in srows[1:]:
        if not r[0].strip():
            continue
        key = (r[0].strip(), r[1].strip())
        sheet[key] = (parse(r[21]), parse(r[22]))  # April cash, April UPI

    # DB
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)
    rows = await conn.fetch(
        "SELECT r.room_number, t.name, p.payment_mode, SUM(p.amount) as total "
        "FROM payments p "
        "JOIN tenancies te ON p.tenancy_id = te.id "
        "JOIN tenants t ON te.tenant_id = t.id "
        "JOIN rooms r ON te.room_id = r.id "
        "WHERE p.period_month=$1 AND p.for_type='rent' AND p.is_void=false "
        "GROUP BY r.room_number, t.name, p.payment_mode "
        "ORDER BY r.room_number, t.name",
        datetime.date(2026, 4, 1))
    await conn.close()

    db = {}
    for r in rows:
        key = (r['room_number'], r['name'])
        if key not in db:
            db[key] = {'cash': 0, 'upi': 0}
        db[key][r['payment_mode']] += int(r['total'])

    print('=== April: DB vs Source sheet differences ===')
    total_diff = 0
    for key in sorted(db.keys()):
        dvals = db[key]
        svals = sheet.get(key, (0, 0))
        d_cash, d_upi = dvals['cash'], dvals['upi']
        s_cash, s_upi = svals
        diff = (d_cash + d_upi) - (s_cash + s_upi)
        if diff != 0:
            print(f'  {key[0]:5s} {key[1][:22]:22s}  DB={d_cash+d_upi:>8,} (c={d_cash:,} u={d_upi:,})  Sheet={s_cash+s_upi:>8,} (c={s_cash:,} u={s_upi:,})  diff={diff:>+9,}')
            total_diff += diff

    # Check sheet tenants not in DB
    for key in sorted(sheet.keys()):
        if key not in db:
            s_cash, s_upi = sheet[key]
            if s_cash + s_upi > 0:
                print(f'  {key[0]:5s} {key[1][:22]:22s}  DB=       0  Sheet={s_cash+s_upi:>8,}  diff={-(s_cash+s_upi):>+9,}  [IN SHEET NOT DB]')
                total_diff -= (s_cash + s_upi)

    print(f'\nTotal diff (DB - Sheet): {total_diff:>+,}')

asyncio.run(main())
