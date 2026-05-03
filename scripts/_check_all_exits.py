import asyncio, asyncpg

async def run():
    conn = await asyncpg.connect(
        'postgresql://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres'
    )

    # All-time monthly exits
    q = """
        SELECT
            COUNT(*) AS cnt,
            MIN(t.checkout_date) AS earliest_exit,
            MAX(t.checkout_date) AS latest_exit,
            COALESCE(SUM(t.security_deposit),0) AS tot_dep_db,
            COALESCE(SUM(t.booking_amount),0)   AS tot_booking,
            COALESCE(SUM(t.security_deposit) + SUM(t.booking_amount),0) AS tot_combined,
            COALESCE(SUM(t.maintenance_fee),0)  AS tot_maint,
            COALESCE(SUM(p_dep.dep_paid),0)     AS tot_dep_paid,
            COALESCE(SUM(p_dep.dep_paid),0) - COALESCE(SUM(t.maintenance_fee),0) AS refundable
        FROM tenancies t
        JOIN tenants ten ON ten.id = t.tenant_id
        LEFT JOIN (
            SELECT tenancy_id, SUM(amount) AS dep_paid
            FROM payments
            WHERE for_type='deposit' AND is_void=false
            GROUP BY tenancy_id
        ) p_dep ON p_dep.tenancy_id = t.id
        WHERE t.status = 'exited'
          AND t.stay_type = 'monthly'
    """
    row = await conn.fetchrow(q)
    print("=== ALL-TIME MONTHLY EXITS ===")
    print(f"  Count:          {row['cnt']}")
    print(f"  Date range:     {row['earliest_exit']} → {row['latest_exit']}")
    print(f"  Dep (DB field): Rs {row['tot_dep_db']:,.0f}")
    print(f"  Booking (DB):   Rs {row['tot_booking']:,.0f}")
    print(f"  Dep+Booking:    Rs {row['tot_combined']:,.0f}")
    print(f"  Dep paid (pmts):Rs {row['tot_dep_paid']:,.0f}")
    print(f"  Maintenance:    Rs {row['tot_maint']:,.0f}")
    print(f"  Refundable:     Rs {row['refundable']:,.0f}")

    # Also break down by year-month of checkout
    q2 = """
        SELECT
            to_char(t.checkout_date,'YYYY-MM') AS mo,
            COUNT(*) AS cnt,
            SUM(t.security_deposit) AS dep_db,
            SUM(t.booking_amount) AS booking,
            SUM(t.maintenance_fee) AS maint
        FROM tenancies t
        WHERE t.status='exited' AND t.stay_type='monthly'
        GROUP BY 1 ORDER BY 1
    """
    rows = await conn.fetch(q2)
    print("\n=== BY MONTH ===")
    print(f"  {'Month':<10} {'Count':>5}  {'Dep(DB)':>10}  {'Booking':>10}  {'Combined':>10}  {'Maint':>8}")
    for r in rows:
        combined = (r['dep_db'] or 0) + (r['booking'] or 0)
        print(f"  {r['mo']:<10} {r['cnt']:>5}  {(r['dep_db'] or 0):>10,.0f}  {(r['booking'] or 0):>10,.0f}  {combined:>10,.0f}  {(r['maint'] or 0):>8,.0f}")

    await conn.close()

asyncio.run(run())
