import asyncio, asyncpg

async def run():
    conn = await asyncpg.connect(
        'postgresql://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres'
    )

    q = """
        SELECT
            ten.name,
            r.room_number,
            t.checkin_date,
            t.checkout_date,
            COALESCE(t.security_deposit, 0)  AS security_deposit,
            COALESCE(t.maintenance_fee, 0)   AS maintenance_fee,
            COALESCE(t.booking_amount, 0)    AS booking_amount,
            COALESCE(t.security_deposit,0) - COALESCE(t.maintenance_fee,0) AS refundable,
            t.agreed_rent,
            t.sharing_type,
            COALESCE(SUM(CASE WHEN p.for_type='rent'    AND p.is_void=false THEN p.amount ELSE 0 END),0) AS rent_paid,
            COALESCE(SUM(CASE WHEN p.for_type='deposit' AND p.is_void=false THEN p.amount ELSE 0 END),0) AS deposit_paid,
            COALESCE(SUM(CASE WHEN p.for_type='booking' AND p.is_void=false THEN p.amount ELSE 0 END),0) AS booking_paid
        FROM tenancies t
        JOIN tenants ten ON ten.id = t.tenant_id
        LEFT JOIN rooms r ON r.id = t.room_id
        LEFT JOIN checkout_records cr ON cr.tenancy_id = t.id
        LEFT JOIN payments p ON p.tenancy_id = t.id
        WHERE t.status = 'exited'
          AND t.checkout_date >= '2025-10-01'
          AND t.checkout_date <= '2026-04-30'
          AND t.stay_type = 'monthly'
          AND cr.id IS NULL
        GROUP BY t.id, ten.name, r.room_number, t.checkin_date, t.checkout_date,
                 t.security_deposit, t.maintenance_fee, t.booking_amount,
                 t.agreed_rent, t.sharing_type
        ORDER BY t.checkout_date, ten.name
    """
    rows = await conn.fetch(q)

    hdr = (
        f"{'Name':<24} {'Room':>5}  {'Check-in':>12}  {'Exit':>12}"
        f"  {'dep(DB)':>9}  {'dep_paid':>9}  {'maint':>7}  {'refundable':>10}"
        f"  {'book_paid':>9}  {'rent_paid':>10}  note"
    )
    print("22 TENANTS WITHOUT CHECKOUT RECORD\n")
    print(hdr)
    print("-" * 135)

    tot_dep_db = tot_dep_paid = tot_maint = tot_ref = tot_rent = 0
    for r in rows:
        dep_db   = float(r["security_deposit"])
        dep_paid = float(r["deposit_paid"])
        maint    = float(r["maintenance_fee"])
        ref      = float(r["refundable"])
        rent     = float(r["rent_paid"])
        book     = float(r["booking_paid"])
        tot_dep_db += dep_db; tot_dep_paid += dep_paid
        tot_maint  += maint;  tot_ref     += ref; tot_rent += rent

        flag = ""
        if dep_db == 0 and dep_paid == 0:
            flag = "no deposit recorded"
        elif abs(dep_db - dep_paid) > 100:
            flag = f"DB vs paid gap: {dep_db-dep_paid:+,.0f}"

        line = (
            f"  {r['name'][:22]:<22} {str(r['room_number'] or '?'):>5}"
            f"  {str(r['checkin_date']):>12}  {str(r['checkout_date']):>12}"
            f"  {dep_db:>9,.0f}  {dep_paid:>9,.0f}  {maint:>7,.0f}  {ref:>10,.0f}"
            f"  {book:>9,.0f}  {rent:>10,.0f}  {flag}"
        )
        print(line)

    print("-" * 135)
    print(
        f"  {'TOTAL':<22} {'':>5}  {'':>12}  {'':>12}"
        f"  {tot_dep_db:>9,.0f}  {tot_dep_paid:>9,.0f}  {tot_maint:>7,.0f}  {tot_ref:>10,.0f}"
        f"  {'':>9}  {tot_rent:>10,.0f}"
    )
    print()
    print("dep(DB)  = tenancies.security_deposit")
    print("dep_paid = SUM of payments where for_type='deposit'")
    print("DB vs paid gap = mismatch between DB field and actual payment recorded")

    await conn.close()

asyncio.run(run())
