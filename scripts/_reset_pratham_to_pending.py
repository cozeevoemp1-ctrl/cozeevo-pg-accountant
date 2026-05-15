import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"
    )
    # Set tenancy 1102 to no_show (removes from active count, doesn't block room re-booking)
    await conn.execute(
        "UPDATE tenancies SET status='no_show' WHERE id=1102"
    )
    # Reset onboarding session back to pending_review and clear approval fields
    r = await conn.execute("""
        UPDATE onboarding_sessions
        SET status='pending_review',
            tenancy_id=NULL,
            approved_at=NULL,
            approved_by_phone=''
        WHERE token='f0e7fc81-6f0b-44b6-85d1-589988dc47e4'
    """)
    print("Session reset:", r)
    # Confirm state
    row = await conn.fetchrow(
        "SELECT token, status, tenancy_id, tenant_name FROM onboarding_sessions WHERE token='f0e7fc81-6f0b-44b6-85d1-589988dc47e4'"
    )
    print("Session:", dict(row))
    ten = await conn.fetchrow("SELECT id, status FROM tenancies WHERE id=1102")
    print("Tenancy:", dict(ten))
    await conn.close()

asyncio.run(main())
