import asyncio, os, sys
from datetime import date as _date
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()
import asyncpg

approved = {
    '2025-11-01': {'cash': 0,       'upi': 0},
    '2025-12-01': {'cash': 0,       'upi': 0},
    '2026-01-01': {'cash': 300572,  'upi': 530575},
    '2026-02-01': {'cash': 653300,  'upi': 2324048},
    '2026-03-01': {'cash': 1094220, 'upi': 2889193},
}

async def main():
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)
    for m, app in approved.items():
        sql = ("SELECT DATE(created_at) as day, payment_mode, "
               "SUM(amount) as total, COUNT(*) as cnt "
               "FROM payments "
               "WHERE period_month = $1 AND for_type = 'rent' AND is_void = false "
               "GROUP BY DATE(created_at), payment_mode "
               "ORDER BY day, payment_mode")
        rows = await conn.fetch(sql, _date.fromisoformat(m))
        db_cash = sum(int(r['total']) for r in rows if r['payment_mode'] == 'cash')
        db_upi  = sum(int(r['total']) for r in rows if r['payment_mode'] == 'upi')
        dc = db_cash - app['cash']
        du = db_upi  - app['upi']
        print(f'=== {m[:7]} ===')
        print(f'  Approved:  Cash {app["cash"]:>10,}  UPI {app["upi"]:>10,}  = {app["cash"]+app["upi"]:>10,}')
        print(f'  DB now:    Cash {db_cash:>10,}  UPI {db_upi:>10,}  = {db_cash+db_upi:>10,}')
        print(f'  Diff:      Cash {dc:>+10,}  UPI {du:>+10,}  = {dc+du:>+10,}')
        if rows:
            for r in rows:
                print(f'    {str(r["day"]):12s}  {r["payment_mode"]:5s}  {int(r["cnt"]):3d} rows  Rs.{int(r["total"]):,}')
        else:
            print(f'    No entries in DB')
        print()
    await conn.close()

asyncio.run(main())
