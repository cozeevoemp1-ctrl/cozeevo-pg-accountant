"""One-off: reduce Sachin Kumar Yadav (Room 409) March deposit 5,250 -> 4,750.

Kiran confirmed ₹500 is still pending on the deposit. Mirrors the app's
edit_payment path: UPDATE amount + AuditLog row + freeze-trigger bypass
(payment dated 2026-03-01 is in a frozen month). Dues are computed live from
payments, so PWA + bot reflect deposit_due=500 immediately after this.
"""
import asyncio, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()
import asyncpg

PMT_ID = 21397
OLD = 5250
NEW = 4750

async def main():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql'))
    cur = await conn.fetchrow(
        "SELECT p.id, p.amount, p.for_type, p.tenancy_id, te.org_id, tn.name "
        "FROM payments p JOIN tenancies te ON te.id=p.tenancy_id "
        "JOIN tenants tn ON tn.id=te.tenant_id WHERE p.id=$1", PMT_ID)
    if cur is None:
        print(f"payment {PMT_ID} not found"); await conn.close(); return
    print(f"before: id={cur['id']} {cur['for_type']} amount={int(cur['amount'])} {cur['name']}")
    if int(cur['amount']) != OLD:
        print(f"ABORT: expected amount {OLD} but found {int(cur['amount'])} — not editing.")
        await conn.close(); return

    async with conn.transaction():
        await conn.execute("SET LOCAL app.allow_historical_write = 'true'")
        await conn.execute("UPDATE payments SET amount=$1 WHERE id=$2", NEW, PMT_ID)
        await conn.execute(
            "INSERT INTO audit_log (changed_by, entity_type, entity_id, entity_name, "
            "field, old_value, new_value, source, org_id, note, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, NOW())",
            "Kiran", "payment", PMT_ID, f"Payment {PMT_ID}",
            "amount", str(float(OLD)), str(float(NEW)), "manual",
            cur['org_id'], "₹500 deposit pending — Sachin Kumar Yadav Rm 409")

    after = await conn.fetchval("SELECT amount FROM payments WHERE id=$1", PMT_ID)
    print(f"after:  amount={int(after)}")

    # Verify resulting deposit_due
    tid = cur['tenancy_id']
    dep = int(await conn.fetchval(
        "SELECT coalesce(sum(amount),0) FROM payments WHERE tenancy_id=$1 "
        "AND is_void IS NOT TRUE AND for_type='deposit'", tid))
    book = int(await conn.fetchval(
        "SELECT coalesce(sum(amount),0) FROM payments WHERE tenancy_id=$1 "
        "AND is_void IS NOT TRUE AND for_type='booking'", tid))
    agreed = int(await conn.fetchval("SELECT security_deposit FROM tenancies WHERE id=$1", tid))
    print(f"deposit_paid={dep:,}  booking={book:,}  agreed={agreed:,}  -> deposit_due={max(0, agreed-dep-book):,}")
    await conn.close()

asyncio.run(main())
