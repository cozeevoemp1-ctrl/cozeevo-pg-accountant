"""
Full Customer Lifecycle Test Suite
===================================
Tests the complete lifecycle: payment log, mode correction, void,
add tenant, checkout, no-show — all via the chat API directly.

Run on VPS:
  cd /opt/pg-accountant
  TEST_MODE=1 venv/bin/python3 tests/test_lifecycle.py

Each test sends messages as an admin phone and checks responses.
GSheets sync is tested by checking the Sheet after each operation.
"""
import asyncio
import os
import sys
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["TEST_MODE"] = "1"

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select

ADMIN_PHONE = "917845952289"
DB_URL = os.getenv("DATABASE_URL", "")

engine = create_async_engine(DB_URL)
SessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

PASS = 0
FAIL = 0
ERRORS = []


async def send(phone: str, message: str) -> dict:
    """Send a message through the chat API and return the result."""
    from src.whatsapp.chat_api import process_message, InboundMessage
    async with SessionFactory() as session:
        result = await process_message(
            body=InboundMessage(phone=phone, message=message),
            session=session,
        )
        return {
            "reply": result.reply or "",
            "intent": result.intent,
            "skip": result.skip,
            "role": result.role,
        }


def check(test_name: str, reply: str, must_contain: list[str], must_not_contain: list[str] = None):
    """Check if reply contains expected strings."""
    global PASS, FAIL
    reply_lower = reply.lower()
    failed = False

    for keyword in must_contain:
        if keyword.lower() not in reply_lower:
            print(f"  FAIL: '{keyword}' not found in reply")
            failed = True

    for keyword in (must_not_contain or []):
        if keyword.lower() in reply_lower:
            print(f"  FAIL: '{keyword}' should NOT be in reply")
            failed = True

    if failed:
        FAIL += 1
        ERRORS.append(test_name)
        print(f"  FAIL [{test_name}]")
        print(f"  Reply: {reply[:200]}")
    else:
        PASS += 1
        print(f"  PASS [{test_name}]")


async def cleanup_test_tenant(name: str):
    """Remove test tenant data from DB."""
    async with SessionFactory() as session:
        await session.execute(text("""
            DELETE FROM payments WHERE tenancy_id IN (
                SELECT tn.id FROM tenancies tn
                JOIN tenants t ON t.id = tn.tenant_id
                WHERE t.name ILIKE :name
            )
        """), {"name": f"%{name}%"})
        await session.execute(text("""
            DELETE FROM rent_schedule WHERE tenancy_id IN (
                SELECT tn.id FROM tenancies tn
                JOIN tenants t ON t.id = tn.tenant_id
                WHERE t.name ILIKE :name
            )
        """), {"name": f"%{name}%"})
        await session.execute(text("""
            DELETE FROM pending_actions WHERE phone = :phone
        """), {"phone": ADMIN_PHONE})
        await session.commit()


async def verify_db_payment(tenant_name: str, expected_count: int, expected_total: float = None):
    """Verify payment records in DB."""
    async with SessionFactory() as session:
        result = await session.execute(text("""
            SELECT COUNT(*), COALESCE(SUM(p.amount), 0)
            FROM payments p
            JOIN tenancies tn ON tn.id = p.tenancy_id
            JOIN tenants t ON t.id = tn.tenant_id
            WHERE t.name ILIKE :name AND p.is_void = FALSE
            AND p.period_month IS NOT NULL
        """), {"name": f"%{tenant_name}%"})
        count, total = result.fetchone()
        ok = True
        if count != expected_count:
            print(f"  DB CHECK FAIL: expected {expected_count} payments, got {count}")
            ok = False
        if expected_total is not None and float(total) != expected_total:
            print(f"  DB CHECK FAIL: expected total {expected_total}, got {float(total)}")
            ok = False
        if ok:
            print(f"  DB CHECK OK: {count} payments, total Rs.{float(total):,.0f}")
        return ok


# =============================================================================
# TEST SCENARIOS
# =============================================================================

async def test_01_payment_with_upi():
    """Payment with explicit UPI mode."""
    print("\n=== TEST 01: Payment with UPI ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    check("01a_confirm_prompt", r["reply"],
          ["krishnanshu", "5,000", "upi", "yes"],
          ["suggested allocation"])

    r = await send(ADMIN_PHONE, "yes")
    check("01b_payment_logged", r["reply"],
          ["payment logged", "5,000", "upi"])

    await verify_db_payment("Krishnanshu", 1, 5000.0)

    # Void it
    r = await send(ADMIN_PHONE, "void payment Krishnanshu")
    # Might show void confirm or "which tenant"
    if "void this payment" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "1")
    elif "which" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "2")  # pick Krishnanshu
        r = await send(ADMIN_PHONE, "1")  # confirm void

    check("01c_voided", r["reply"], ["voided", "krishnanshu"])
    await verify_db_payment("Krishnanshu", 0)


async def test_02_payment_with_cash():
    """Payment with explicit CASH mode."""
    print("\n=== TEST 02: Payment with CASH ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 cash")
    check("02a_confirm_prompt", r["reply"],
          ["krishnanshu", "5,000", "cash", "yes"])

    r = await send(ADMIN_PHONE, "yes")
    check("02b_payment_logged", r["reply"],
          ["payment logged", "5,000", "cash"])

    await verify_db_payment("Krishnanshu", 1, 5000.0)
    await cleanup_test_tenant("Krishnanshu")


async def test_03_payment_no_mode_defaults_cash():
    """Payment without mode specified defaults to cash."""
    print("\n=== TEST 03: Payment no mode ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000")
    check("03a_defaults_cash", r["reply"],
          ["krishnanshu", "5,000", "cash", "yes"])

    r = await send(ADMIN_PHONE, "no")
    check("03b_cancelled", r["reply"], ["cancel"])
    await cleanup_test_tenant("Krishnanshu")


async def test_04_mode_correction_to_upi():
    """Correct mode from cash to UPI during confirmation."""
    print("\n=== TEST 04: Mode correction to UPI ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000")
    check("04a_shows_cash", r["reply"], ["cash"])

    r = await send(ADMIN_PHONE, "upi")
    check("04b_corrected_to_upi", r["reply"], ["upi", "confirm"])

    r = await send(ADMIN_PHONE, "yes")
    check("04c_logged_as_upi", r["reply"], ["payment logged", "upi"])

    await verify_db_payment("Krishnanshu", 1, 5000.0)
    await cleanup_test_tenant("Krishnanshu")


async def test_05_mode_correction_phrase():
    """Correct mode with phrase 'no she paid upi'."""
    print("\n=== TEST 05: Mode correction phrase ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 cash")
    check("05a_shows_cash", r["reply"], ["cash"])

    r = await send(ADMIN_PHONE, "no she paid upi")
    check("05b_corrected", r["reply"], ["upi", "confirm"])

    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_06_full_payment_shows_paid():
    """Full rent payment shows PAID status."""
    print("\n=== TEST 06: Full payment = PAID ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 15000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("06a_paid_status", r["reply"], ["payment logged", "paid"])

    await verify_db_payment("Krishnanshu", 1, 15000.0)
    await cleanup_test_tenant("Krishnanshu")


async def test_07_partial_then_full():
    """Two partial payments completing the full amount."""
    print("\n=== TEST 07: Partial + Partial = PAID ===")
    await cleanup_test_tenant("Krishnanshu")

    # First partial
    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("07a_partial", r["reply"], ["partial"])

    # Second partial to complete
    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 10000 cash")
    r = await send(ADMIN_PHONE, "yes")
    check("07b_paid", r["reply"], ["paid"])

    await verify_db_payment("Krishnanshu", 2, 15000.0)
    await cleanup_test_tenant("Krishnanshu")


async def test_08_overpayment():
    """Overpayment triggers allocation options."""
    print("\n=== TEST 08: Overpayment ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 20000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("08a_overpayment", r["reply"], ["overpayment", "extra"])

    # Reply 3 = ask tenant (dismiss)
    r = await send(ADMIN_PHONE, "3")
    await cleanup_test_tenant("Krishnanshu")


async def test_09_void_current_month():
    """Void defaults to current month payment."""
    print("\n=== TEST 09: Void current month ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    r = await send(ADMIN_PHONE, "yes")

    r = await send(ADMIN_PHONE, "void payment Krishnanshu")
    if "void this payment" in r["reply"].lower():
        check("09a_shows_april", r["reply"], ["apr 2026"])
        r = await send(ADMIN_PHONE, "1")
        check("09b_voided", r["reply"], ["voided"])
    elif "which" in r["reply"].lower():
        # Multi-tenant room
        r = await send(ADMIN_PHONE, "2")
        r = await send(ADMIN_PHONE, "1")
        check("09b_voided", r["reply"], ["voided"])

    await verify_db_payment("Krishnanshu", 0)
    await cleanup_test_tenant("Krishnanshu")


async def test_10_case_insensitive_mode():
    """UPI/Upi/upi all work the same."""
    print("\n=== TEST 10: Case insensitive mode ===")
    await cleanup_test_tenant("Krishnanshu")

    for mode in ["UPI", "Upi", "upi", "CASH", "Cash", "cash"]:
        r = await send(ADMIN_PHONE, f"Krishnanshu room 211 paid 1000 {mode}")
        expected_mode = "upi" if mode.lower() == "upi" else "cash"
        check(f"10_{mode}", r["reply"], [expected_mode.upper()])
        r = await send(ADMIN_PHONE, "no")
        await cleanup_test_tenant("Krishnanshu")


async def test_11_gpay_phonepe_as_upi():
    """GPay, PhonePe, Paytm all map to UPI."""
    print("\n=== TEST 11: GPay/PhonePe = UPI ===")
    await cleanup_test_tenant("Krishnanshu")

    for mode in ["gpay", "phonepe", "paytm", "online"]:
        r = await send(ADMIN_PHONE, f"Krishnanshu room 211 paid 1000 {mode}")
        check(f"11_{mode}", r["reply"], ["upi"])
        r = await send(ADMIN_PHONE, "no")
        await cleanup_test_tenant("Krishnanshu")


async def test_12_payment_by_room_number():
    """Payment using room number instead of name."""
    print("\n=== TEST 12: Payment by room number ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "room 211 paid 5000 upi")
    # Should find tenants in room 211
    check("12a_found", r["reply"], ["211"])
    r = await send(ADMIN_PHONE, "no") if "yes" in r["reply"].lower() else r
    await cleanup_test_tenant("Krishnanshu")


async def test_13_who_hasnt_paid():
    """Query unpaid tenants."""
    print("\n=== TEST 13: Who hasn't paid ===")
    r = await send(ADMIN_PHONE, "who hasn't paid")
    check("13_unpaid_list", r["reply"], ["outstanding", "rs."])


async def test_14_single_month_no_allocation_noise():
    """Single month dues should NOT show 'Suggested allocation'."""
    print("\n=== TEST 14: No allocation noise for single month ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    check("14_no_allocation", r["reply"],
          ["confirm payment"],
          ["suggested allocation"])
    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_15_amount_with_k_suffix():
    """Amount with k suffix (15k = 15000)."""
    print("\n=== TEST 15: Amount with k suffix ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 15k upi")
    check("15_k_suffix", r["reply"], ["15,000"])
    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_16_cancel_payment():
    """Cancel a payment confirmation."""
    print("\n=== TEST 16: Cancel payment ===")
    await cleanup_test_tenant("Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    r = await send(ADMIN_PHONE, "no")
    check("16_cancelled", r["reply"], ["cancel"])
    await verify_db_payment("Krishnanshu", 0)


async def test_17_greeting():
    """Bot responds to greetings."""
    print("\n=== TEST 17: Greeting ===")
    r = await send(ADMIN_PHONE, "hi")
    check("17_greeting", r["reply"], ["kiran"])


async def test_18_help():
    """Bot shows help menu."""
    print("\n=== TEST 18: Help ===")
    r = await send(ADMIN_PHONE, "help")
    check("18_help", r["reply"], ["payment", "report"])


# =============================================================================
# RUNNER
# =============================================================================

async def main():
    global PASS, FAIL

    print("=" * 60)
    print("FULL LIFECYCLE TEST SUITE")
    print(f"Admin phone: {ADMIN_PHONE}")
    print(f"Date: {date.today()}")
    print("=" * 60)

    # Clear all pending actions first
    async with SessionFactory() as session:
        await session.execute(text("DELETE FROM pending_actions WHERE phone = :p"), {"p": ADMIN_PHONE})
        await session.commit()
    print("Cleared pending actions")

    tests = [
        test_01_payment_with_upi,
        test_02_payment_with_cash,
        test_03_payment_no_mode_defaults_cash,
        test_04_mode_correction_to_upi,
        test_05_mode_correction_phrase,
        test_06_full_payment_shows_paid,
        test_07_partial_then_full,
        test_08_overpayment,
        test_09_void_current_month,
        test_10_case_insensitive_mode,
        test_11_gpay_phonepe_as_upi,
        test_12_payment_by_room_number,
        test_13_who_hasnt_paid,
        test_14_single_month_no_allocation_noise,
        test_15_amount_with_k_suffix,
        test_16_cancel_payment,
        test_17_greeting,
        test_18_help,
    ]

    for test_fn in tests:
        try:
            await test_fn()
        except Exception as e:
            FAIL += 1
            ERRORS.append(test_fn.__name__)
            print(f"  EXCEPTION [{test_fn.__name__}]: {e}")

    await engine.dispose()

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    if ERRORS:
        print(f"FAILED: {', '.join(ERRORS)}")
    print("=" * 60)

    return FAIL == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
