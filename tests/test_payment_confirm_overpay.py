"""
Regression test for the "lost Yes" payment confirmation bug.

Bug history (2026-04-23):
  Lokesh sent "Ganesh Divekar paid 20000 cash, 8000 upi" while Ganesh's
  April rent was already fully paid (via morning source-sheet sync).
  Bot prompted "Reply Yes to log". Lokesh replied "Yes". Bot replied
  "Hello, how can I assist..." instead of logging the payment.

Root cause:
  build_dues_snapshot returned April with remaining=0. Account_handler
  routed to CONFIRM_PAYMENT_ALLOC (because pending_months was non-empty),
  but compute_allocation skips zero-remaining months -> allocation=[].
  When user said Yes, owner_handler looped over [] -> returned "" ->
  chat_api.py line 449 `if resolved_reply:` is falsy -> fell through
  to LLM CONVERSE which produced the greeting.

This test re-creates an over-paid tenant scenario and verifies the
"Yes" confirmation actually creates a payment row.

Run:
  TEST_MODE=1 venv/Scripts/python tests/test_payment_confirm_overpay.py
"""
import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["TEST_MODE"] = "1"

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

ADMIN_PHONE = "917845952289"
DB_URL = os.getenv("DATABASE_URL", "")
engine = create_async_engine(DB_URL)
SessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _send(phone: str, message: str):
    from src.whatsapp.chat_api import process_message, InboundMessage
    async with SessionFactory() as session:
        return await process_message(
            body=InboundMessage(phone=phone, message=message),
            session=session,
        )


async def _pick_fully_paid_tenant():
    """Find an active tenant whose current-month dues are all zero."""
    from datetime import date
    pm = date.today().replace(day=1)
    async with SessionFactory() as session:
        rows = (await session.execute(text("""
            SELECT t.id AS tenant_id, t.name, r.room_number, tc.id AS tenancy_id,
                   rs.rent_due,
                   COALESCE((SELECT SUM(p.amount) FROM payments p
                             WHERE p.tenancy_id = tc.id
                               AND p.period_month = :pm
                               AND p.for_type = 'rent'
                               AND p.is_void = FALSE), 0) AS paid_so_far
            FROM tenants t
            JOIN tenancies tc ON tc.tenant_id = t.id
            JOIN rooms r ON r.id = tc.room_id
            JOIN rent_schedule rs ON rs.tenancy_id = tc.id AND rs.period_month = :pm
            WHERE tc.status = 'active'
              AND COALESCE(rs.rent_due, 0) > 0
            ORDER BY t.name
        """), {"pm": pm})).fetchall()
        for r in rows:
            d = dict(r._mapping)
            if float(d["paid_so_far"]) >= float(d["rent_due"]):
                return d
        return None


async def _list_payments(tenancy_id: int, since_id: int):
    async with SessionFactory() as session:
        rows = (await session.execute(text("""
            SELECT id, amount, payment_mode, period_month, payment_date,
                   notes, is_void
            FROM payments
            WHERE tenancy_id = :tid AND id > :since
            ORDER BY id ASC
        """), {"tid": tenancy_id, "since": since_id})).fetchall()
        return [dict(r._mapping) for r in rows]


async def _max_payment_id():
    async with SessionFactory() as session:
        r = (await session.execute(text("SELECT COALESCE(MAX(id), 0) FROM payments"))).scalar_one()
        return int(r)


async def _void_payments(payment_ids):
    if not payment_ids:
        return
    async with SessionFactory() as session:
        await session.execute(
            text("UPDATE payments SET is_void = TRUE, notes = COALESCE(notes,'') || ' [test cleanup]' WHERE id = ANY(:ids)"),
            {"ids": payment_ids},
        )
        await session.commit()


async def _clear_pending(phone):
    async with SessionFactory() as session:
        await session.execute(text("DELETE FROM pending_actions WHERE phone = :p"), {"p": phone})
        await session.commit()


async def main():
    print("=" * 70)
    print("REGRESSION: Yes-confirmation must save payment when dues are zero")
    print("=" * 70)

    tenant = await _pick_fully_paid_tenant()
    if not tenant:
        print("SKIP: No fully-paid active tenant found in current month — cannot run.")
        return 0

    name = tenant["name"]
    room = tenant["room_number"]
    tid = tenant["tenancy_id"]
    print(f"Test tenant: {name} (Room {room}, tenancy_id={tid})")

    await _clear_pending(ADMIN_PHONE)
    baseline = await _max_payment_id()

    # 1. Send the split-payment message that has no dues to allocate to
    msg1 = f"{name} paid 200 cash, 100 upi"
    print(f"\n>>> {msg1!r}")
    res1 = await _send(ADMIN_PHONE, msg1)
    reply1 = (res1.reply or "")
    print(f"<<< intent={res1.intent}")
    print(f"<<< reply (first 220):\n{reply1[:220]}")
    assert "yes" in reply1.lower() or "confirm" in reply1.lower(), \
        f"Expected confirmation prompt, got: {reply1[:200]}"

    # 2. Confirm with Yes
    print("\n>>> 'Yes'")
    res2 = await _send(ADMIN_PHONE, "Yes")
    reply2 = (res2.reply or "")
    print(f"<<< intent={res2.intent}")
    print(f"<<< reply (first 220):\n{reply2[:220]}")

    fail = []

    # The bug signature: bot greets you instead of confirming
    if "how can i assist" in reply2.lower() or "good morning" in reply2.lower() \
            or "good afternoon" in reply2.lower() or "good evening" in reply2.lower():
        fail.append("BUG REPRODUCED: bot greeted instead of confirming the payment.")

    # The fix: a payment row must exist for this tenancy after baseline
    new_pays = await _list_payments(tid, baseline)
    print(f"\nNew payment rows since baseline: {len(new_pays)}")
    for p in new_pays:
        print(f"  {p}")
    if not new_pays:
        fail.append("FAIL: No new payment row created in DB for the confirmed amount.")
    else:
        total = sum(float(p["amount"]) for p in new_pays if not p["is_void"])
        if abs(total - 300.0) > 0.01:
            fail.append(f"FAIL: Total of new (non-void) rows = {total}, expected 300.")

    # cleanup: void the test rows
    await _void_payments([p["id"] for p in new_pays])
    await _clear_pending(ADMIN_PHONE)

    if fail:
        print("\n--- TEST FAILED ---")
        for f in fail:
            print(" ", f)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
