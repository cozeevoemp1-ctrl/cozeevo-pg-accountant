import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"
    )
    rows = await conn.fetch("""
        SELECT t.id as tenancy_id, te.name, r.room_number, t.status,
               t.agreed_rent, t.checkin_date, t.security_deposit, t.booking_amount
        FROM tenancies t
        JOIN tenants te ON t.tenant_id = te.id
        JOIN rooms r ON t.room_id = r.id
        WHERE te.name ILIKE '%pratham%'
        ORDER BY t.id DESC LIMIT 3
    """)
    for row in rows:
        print("Tenancy:", dict(row))

    if rows:
        tid = rows[0]["tenancy_id"]
        rs = await conn.fetch(
            "SELECT period_month, rent_due, adjustment FROM rent_schedule WHERE tenancy_id=$1 ORDER BY period_month DESC LIMIT 5",
            tid
        )
        print("RentSchedule:", [dict(r) for r in rs])
        pmts = await conn.fetch(
            "SELECT id, amount, for_type, payment_mode, payment_date, notes FROM payments WHERE tenancy_id=$1 ORDER BY id DESC",
            tid
        )
        print("Payments:", [dict(p) for p in pmts])

    await conn.close()

asyncio.run(main())
