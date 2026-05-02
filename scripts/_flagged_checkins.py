import asyncio, os
from dotenv import load_dotenv
load_dotenv()
import asyncpg

FLAGGED = [
    ('000', 'Navdeep Gupta'),
    ('000', 'Aditya Sable'),
    ('000', 'Ganesh Magi'),
    ('000', 'Tanya Rishikesh'),
    ('201', 'Rupali'),
    ('209', 'Thirumurugan'),
    ('215', 'Sachin Kumar Yadav'),
    ('418', 'Rakesh'),
    ('419', 'Akshit'),
    ('520', 'Yatam Ramakanth'),
    ('521', 'Shashank'),
]

async def main():
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)

    for room, name in FLAGGED:
        rows = await conn.fetch(
            "SELECT t.name, r.room_number, te.checkin_date, te.checkout_date, te.status, "
            "       COALESCE(SUM(p.amount) FILTER (WHERE p.payment_mode='cash'), 0) as cash, "
            "       COALESCE(SUM(p.amount) FILTER (WHERE p.payment_mode='upi'),  0) as upi "
            "FROM tenants t "
            "JOIN tenancies te ON te.tenant_id = t.id "
            "JOIN rooms r ON te.room_id = r.id "
            "LEFT JOIN payments p ON p.tenancy_id = te.id "
            "   AND p.period_month='2026-04-01' AND p.for_type='rent' AND p.is_void=false "
            "WHERE LOWER(t.name) LIKE LOWER($1) "
            "GROUP BY t.name, r.room_number, te.checkin_date, te.checkout_date, te.status "
            "ORDER BY te.checkin_date DESC LIMIT 3",
            f'%{name.split()[0]}%')
        if rows:
            for r in rows:
                cash = int(r['cash'])
                upi  = int(r['upi'])
                cout = str(r['checkout_date']) if r['checkout_date'] else '-'
                print(f"  {r['room_number']:6s} {r['name'][:24]:24s}  in={r['checkin_date']}  out={cout:12s}  {r['status']:8s}  Apr pay cash={cash:,} upi={upi:,}")
        else:
            print(f"  {room:6s} {name:24s}  NOT FOUND IN DB")

    await conn.close()

asyncio.run(main())
