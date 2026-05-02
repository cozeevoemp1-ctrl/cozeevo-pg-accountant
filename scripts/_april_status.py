"""Show remaining April diff and Cozeevo Ops v2 April COLLECTION total."""
import asyncio, os, datetime
from dotenv import load_dotenv
load_dotenv()
import asyncpg, gspread

def parse(v):
    v = str(v).strip().replace(',', '').replace('Rs.', '')
    try: return int(float(v))
    except: return 0

async def main():
    # DB
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)
    rows = await conn.fetch(
        "SELECT payment_mode, SUM(amount) as total FROM payments "
        "WHERE period_month='2026-04-01' AND for_type='rent' AND is_void=false "
        "GROUP BY payment_mode")
    db_cash = next((int(r['total']) for r in rows if r['payment_mode']=='cash'), 0)
    db_upi  = next((int(r['total']) for r in rows if r['payment_mode']=='upi'),  0)
    await conn.close()

    gc = gspread.service_account(filename='credentials/gsheets_service_account.json')

    # Source sheet (1Vr_...) totals
    sh1 = gc.open_by_key('1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0')
    ws1 = sh1.worksheet('Long term')
    srows = ws1.get_all_values()
    src_cash, src_upi = 0, 0
    for r in srows[1:]:
        if r[0].strip():
            src_cash += parse(r[21])
            src_upi  += parse(r[22])

    # Cozeevo Ops v2 APRIL 2026 tab COLLECTION row
    sh2 = gc.open_by_key('1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw')
    ws2 = sh2.worksheet('APRIL 2026')
    ops_rows = ws2.get_all_values()
    ops_cash, ops_upi = 0, 0
    for r in ops_rows[:10]:
        if r and 'COLLECTION' in str(r[0]).upper():
            print(f'Ops COLLECTION row: {r[:6]}')
            for cell in r[1:]:
                cell_s = str(cell).replace(',','').replace('Rs.','').strip()
                if 'cash' in cell_s.lower():
                    try: ops_cash = int(float(cell_s.lower().replace('cash:','').strip()))
                    except: pass
                if 'upi' in cell_s.lower():
                    try: ops_upi = int(float(cell_s.lower().replace('upi:','').strip()))
                    except: pass
            break

    print(f'\nDB:        Cash {db_cash:>12,}  UPI {db_upi:>12,}  Total {db_cash+db_upi:>12,}')
    print(f'Src sheet: Cash {src_cash:>12,}  UPI {src_upi:>12,}  Total {src_cash+src_upi:>12,}')
    print(f'Ops sheet: Cash {ops_cash:>12,}  UPI {ops_upi:>12,}  Total {ops_cash+ops_upi:>12,}')
    print(f'DB-Src:    Cash {db_cash-src_cash:>+12,}  UPI {db_upi-src_upi:>+12,}  Total {(db_cash+db_upi)-(src_cash+src_upi):>+12,}')
    print(f'DB-Ops:    Cash {db_cash-ops_cash:>+12,}  UPI {db_upi-ops_upi:>+12,}  Total {(db_cash+db_upi)-(ops_cash+ops_upi):>+12,}')

asyncio.run(main())
