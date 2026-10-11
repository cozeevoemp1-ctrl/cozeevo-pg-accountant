"""Demo data for the explainer recordings — SANDBOX DB ONLY (localhost:55432/pgtest).

Starting from the sandbox test baseline (rent data ends July 2026), roll months forward
the way the app does, settling each month before rolling the next so no balance carries
forward: Jul settled -> Aug + Sep rolled and paid -> Oct rolled, ~80% paid.
Run after tests/sandbox/reset_db.sh:
    PYTHONPATH=. venv/Scripts/python video/explainer/seed_demo.py
"""
import asyncio
from datetime import date
from urllib.parse import urlparse

from sqlalchemy import text

DB = "postgresql+asyncpg://postgres@localhost:55432/pgtest"
assert urlparse(DB).hostname == "localhost"

from src.database.db_manager import init_db_for_script, get_session  # noqa: E402
from src.services.monthly_rollover import generate_rent_schedule_for_month  # noqa: E402

SETTLE = """
WITH due AS (
  SELECT rs.tenancy_id, rs.period_month,
         coalesce(rs.rent_due,0) + coalesce(rs.maintenance_due,0) + coalesce(rs.adjustment,0)
         - coalesce((SELECT sum(p.amount) FROM payments p WHERE p.tenancy_id = rs.tenancy_id
                     AND p.period_month = rs.period_month AND NOT p.is_void AND p.for_type = 'rent'), 0) AS left_amt
  FROM rent_schedule rs JOIN tenancies tn ON tn.id = rs.tenancy_id
  WHERE rs.period_month = :m AND rs.status IN ('pending','partial') AND tn.status = 'active'
    AND rs.tenancy_id % :mod <> 0
)
INSERT INTO payments (tenancy_id, amount, payment_date, payment_mode, for_type, period_month, notes)
SELECT tenancy_id, left_amt, period_month + 3,
       CASE WHEN tenancy_id % 3 = 0 THEN 'cash'::paymentmode ELSE 'upi'::paymentmode END,
       'rent', period_month, 'sandbox demo seed'
FROM due WHERE left_amt > 0
"""
MARK = """
UPDATE rent_schedule rs SET status = 'paid' FROM tenancies tn
WHERE tn.id = rs.tenancy_id AND tn.status = 'active' AND rs.period_month = :m
  AND rs.status IN ('pending','partial') AND rs.tenancy_id % :mod <> 0
"""


async def settle(month: date, mod: int) -> None:
    """Pay off the month for tenancies with id % mod <> 0 (huge mod = everyone; 5 = ~80%)."""
    async with get_session() as s:
        await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
        await s.execute(text(SETTLE), {"m": month, "mod": mod})
        await s.execute(text(MARK), {"m": month, "mod": mod})
        await s.commit()


DEPOSITS = """
INSERT INTO payments (tenancy_id, amount, payment_date, payment_mode, for_type, notes)
SELECT tn.id, tn.security_deposit, tn.checkin_date, 'upi'::paymentmode, 'deposit', 'sandbox demo seed'
FROM tenancies tn
WHERE tn.status = 'active' AND coalesce(tn.security_deposit, 0) > 0
  AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.tenancy_id = tn.id AND p.for_type = 'deposit' AND NOT p.is_void)
"""


async def main() -> None:
    await init_db_for_script(DB)
    # Synthetic baseline records no deposit payments, so every tenant "owed" their deposit
    # and the home Dues tile (rent + deposit due) showed an extra month. Pay deposits at check-in.
    async with get_session() as s:
        await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
        await s.execute(text(DEPOSITS))
        await s.commit()
    ALL = 10**9  # tenancy_id % ALL <> 0 for every real id -> settle everyone
    await settle(date(2026, 7, 1), ALL)
    for m in (8, 9):
        print(m, await generate_rent_schedule_for_month(2026, m))
        await settle(date(2026, m, 1), ALL)
    print(10, await generate_rent_schedule_for_month(2026, 10))
    await settle(date(2026, 10, 1), 5)


asyncio.run(main())
