"""
Add Delvin Raj, Suraj SH to DB (room 000), add their April payments.
Also add Siddharth Linge's April 2,400 UPI (advance, te.id=1069).
"""
import asyncio, os, datetime
from dotenv import load_dotenv; load_dotenv()
import asyncpg, gspread

APR = datetime.date(2026, 4, 1)

async def main():
    # Get sheet details for missing tenants
    gc = gspread.service_account(filename='credentials/gsheets_service_account.json')
    sh = gc.open_by_key('1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0')
    ws = sh.worksheet('Long term')
    srows = ws.get_all_values()

    targets = {}
    for r in srows[1:]:
        name_low = r[1].strip().lower()
        if 'delvin' in name_low or 'suraj sh' in name_low or name_low == 'suraj sh':
            targets[r[1].strip()] = {
                'room': r[0].strip(), 'phone': r[3].strip(),
                'gender': r[2].strip(), 'checkin': r[4].strip(),
                'apr_cash': r[21].strip(), 'apr_upi': r[22].strip(),
            }
    print('Sheet entries found:')
    for k, v in targets.items():
        print(f'  {k}: {v}')

    conn = await asyncpg.connect(os.getenv('DATABASE_URL').replace('postgresql+asyncpg','postgresql'))

    # Room 000 id
    room_000 = await conn.fetchrow("SELECT id FROM rooms WHERE room_number='000'")
    room_000_id = room_000['id']
    print(f'\nRoom 000 id: {room_000_id}')

    def parse(v):
        try: return int(float(str(v).replace(',','')))
        except: return 0

    async with conn.transaction():
        await conn.execute("SET LOCAL app.allow_historical_write = 'true'")

        # 1. Siddharth Linge — tenancy exists (te.id=1069), just add payment
        sid_cash = 0
        sid_upi  = 2400
        await conn.execute(
            "INSERT INTO payments (tenancy_id, amount, payment_mode, for_type, period_month, payment_date, is_void, created_at) "
            "VALUES ($1,$2,$3,'rent',$4,$5,false,NOW())",
            1069, sid_upi, 'upi', APR, datetime.date(2026, 4, 30))
        print('Added Siddharth Linge April UPI 2,400')

        # 2. Delvin Raj and Suraj SH — create tenant + tenancy + payment
        for name, info in targets.items():
            apr_cash = parse(info['apr_cash'])
            apr_upi  = parse(info['apr_upi'])
            phone    = info['phone'] or None

            # Create tenant
            tenant_id = await conn.fetchval(
                "INSERT INTO tenants (name, phone) VALUES ($1,$2) RETURNING id",
                name, phone)
            print(f'Created tenant: {name} id={tenant_id}')

            # Parse checkin date
            from dateutil.parser import parse as dparse
            try:
                cin = dparse(info['checkin'], dayfirst=True).date()
            except:
                cin = APR

            # Create tenancy in room 000
            tenancy_id = await conn.fetchval(
                "INSERT INTO tenancies (tenant_id, room_id, status, checkin_date, stay_type) "
                "VALUES ($1,$2,'active',$3,'monthly') RETURNING id",
                tenant_id, room_000_id, cin)
            print(f'  Tenancy id={tenancy_id} room=000 checkin={cin}')

            # Add April payments
            if apr_cash > 0:
                await conn.execute(
                    "INSERT INTO payments (tenancy_id, amount, payment_mode, for_type, period_month, payment_date, is_void, created_at) "
                    "VALUES ($1,$2,'cash','rent',$3,$4,false,NOW())",
                    tenancy_id, apr_cash, APR, datetime.date(2026, 4, 30))
                print(f'  Added cash {apr_cash:,}')
            if apr_upi > 0:
                await conn.execute(
                    "INSERT INTO payments (tenancy_id, amount, payment_mode, for_type, period_month, payment_date, is_void, created_at) "
                    "VALUES ($1,$2,'upi','rent',$3,$4,false,NOW())",
                    tenancy_id, apr_upi, APR, datetime.date(2026, 4, 30))
                print(f'  Added upi {apr_upi:,}')

    # Final verify
    rows = await conn.fetch(
        "SELECT payment_mode, SUM(amount) as total FROM payments "
        "WHERE period_month=$1 AND for_type='rent' AND is_void=false GROUP BY payment_mode", APR)
    cash = next((int(r['total']) for r in rows if r['payment_mode']=='cash'), 0)
    upi  = next((int(r['total']) for r in rows if r['payment_mode']=='upi'),  0)
    print(f'\nDB April:  Cash {cash:>12,}  UPI {upi:>12,}  Total {cash+upi:>12,}')
    print(f'Sheet:     Cash {1343783:>12,}  UPI {3195365:>12,}  Total {1343783+3195365:>12,}')
    print(f'Diff:      Cash {cash-1343783:>+12,}  UPI {upi-3195365:>+12,}  Total {(cash+upi)-(1343783+3195365):>+12,}')

    await conn.close()

asyncio.run(main())
