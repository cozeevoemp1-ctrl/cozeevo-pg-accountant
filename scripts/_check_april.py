import asyncio, os, datetime
from dotenv import load_dotenv
load_dotenv()
import asyncpg, gspread

async def main():
    # --- DB ---
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)
    rows = await conn.fetch(
        "SELECT payment_mode, SUM(amount) as total, COUNT(*) as cnt "
        "FROM payments WHERE period_month=$1 AND for_type='rent' AND is_void=false "
        "GROUP BY payment_mode",
        datetime.date(2026, 4, 1))
    await conn.close()
    db_cash = next((int(r['total']) for r in rows if r['payment_mode'] == 'cash'), 0)
    db_upi  = next((int(r['total']) for r in rows if r['payment_mode'] == 'upi'),  0)

    # --- Source sheet ---
    gc = gspread.service_account(filename='credentials/gsheets_service_account.json')
    sh = gc.open_by_key('1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0')
    ws = sh.worksheet('Long term')
    all_rows = ws.get_all_values()

    # Print first 8 non-empty rows to understand structure
    print('=== Long term tab (first 8 rows) ===')
    for i, r in enumerate(all_rows[:8]):
        if any(c.strip() for c in r):
            print(f'  {i+1}: {r[:12]}')

    # Find COLLECTION row
    sh_cash, sh_upi = 0, 0
    for r in all_rows[:10]:
        if r and 'COLLECTION' in str(r[0]).upper():
            print(f'\nCOLLECTION row: {r[:8]}')
            for cell in r:
                cell = str(cell).replace(',','').replace('Rs.','').replace('rs.','').strip()
                if 'cash' in cell.lower():
                    try: sh_cash = int(float(cell.lower().replace('cash:','').strip()))
                    except: pass
                if 'upi' in cell.lower():
                    try: sh_upi = int(float(cell.lower().replace('upi:','').strip()))
                    except: pass

    print(f'\nDB:          Cash {db_cash:>12,}  UPI {db_upi:>12,}  Total {db_cash+db_upi:>12,}')
    print(f'Sheet:       Cash {sh_cash:>12,}  UPI {sh_upi:>12,}  Total {sh_cash+sh_upi:>12,}')
    print(f'Diff(DB-Sh): Cash {db_cash-sh_cash:>+12,}  UPI {db_upi-sh_upi:>+12,}  Total {(db_cash+db_upi)-(sh_cash+sh_upi):>+12,}')

asyncio.run(main())
