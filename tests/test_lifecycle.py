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

# Sheet column indices (APRIL 2026 — new 17-column format)
S_ROOM = 0
S_NAME = 1
S_RENT = 5
S_CASH = 6
S_UPI = 7
S_TOTAL = 8
S_BAL = 9
S_STATUS = 10
S_NOTES = 14

_sheet_cache = {}  # tab_name -> worksheet


def _get_sheet_ws(tab_name: str = None):
    """Get worksheet, cached to avoid rate limits."""
    import gspread
    if tab_name is None:
        today = date.today()
        months = ["", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
                  "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
        tab_name = f"{months[today.month]} {today.year}"
    if tab_name not in _sheet_cache:
        sa = gspread.service_account(filename='credentials/gsheets_service_account.json')
        sh = sa.open_by_key(os.getenv("GSHEETS_SHEET_ID", "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"))
        _sheet_cache[tab_name] = sh.worksheet(tab_name)
    return _sheet_cache[tab_name]


def _find_sheet_row(room_number: str, tenant_name: str, tab_name: str = None) -> dict:
    """Find a tenant's row in the Sheet and return their data."""
    import time
    time.sleep(1)  # wait for Sheet API write to propagate
    ws = _get_sheet_ws(tab_name)
    all_vals = ws.get_all_values()
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()
    for i in range(4, len(all_vals)):
        r = all_vals[i]
        if not r or not r[0]:
            continue
        cell_room = str(r[0]).strip().upper()
        cell_name = str(r[1]).strip().lower() if len(r) > 1 else ""
        if cell_room == room_clean and (name_lower in cell_name or cell_name in name_lower):
            def _num(idx):
                try:
                    return float(str(r[idx]).replace(",", "").strip() or "0")
                except (ValueError, IndexError):
                    return 0.0
            return {
                "row": i + 1,
                "room": r[S_ROOM],
                "name": r[S_NAME],
                "rent_due": _num(S_RENT),
                "cash": _num(S_CASH),
                "upi": _num(S_UPI),
                "total_paid": _num(S_TOTAL),
                "balance": _num(S_BAL),
                "status": str(r[S_STATUS]).strip().upper() if len(r) > S_STATUS else "",
                "notes": str(r[S_NOTES]) if len(r) > S_NOTES else "",
            }
    return None


def verify_sheet(test_name: str, room: str, name: str,
                 expected_cash: float = None, expected_upi: float = None,
                 expected_status: str = None, expected_total: float = None):
    """Verify Sheet row matches expected values."""
    global PASS, FAIL
    row = _find_sheet_row(room, name)
    if row is None:
        FAIL += 1
        ERRORS.append(f"{test_name}_sheet")
        print(f"  SHEET FAIL [{test_name}]: Row not found for {name} / Room {room}")
        return False

    failed = False
    if expected_cash is not None and row["cash"] != expected_cash:
        print(f"  SHEET FAIL: Cash expected {expected_cash}, got {row['cash']}")
        failed = True
    if expected_upi is not None and row["upi"] != expected_upi:
        print(f"  SHEET FAIL: UPI expected {expected_upi}, got {row['upi']}")
        failed = True
    if expected_total is not None and row["total_paid"] != expected_total:
        print(f"  SHEET FAIL: Total expected {expected_total}, got {row['total_paid']}")
        failed = True
    if expected_status is not None and row["status"] != expected_status.upper():
        print(f"  SHEET FAIL: Status expected {expected_status}, got {row['status']}")
        failed = True

    if failed:
        FAIL += 1
        ERRORS.append(f"{test_name}_sheet")
        print(f"  SHEET FAIL [{test_name}]")
        return False
    else:
        PASS += 1
        print(f"  SHEET OK [{test_name}]: Cash={row['cash']}, UPI={row['upi']}, Status={row['status']}")
        return True


def reset_sheet_row(room: str, name: str):
    """Reset a tenant's Sheet row to clean state (0/0/UNPAID)."""
    row_data = _find_sheet_row(room, name)
    if not row_data:
        return
    ws = _get_sheet_ws()
    row = row_data["row"]
    rent_due = row_data["rent_due"]
    import gspread
    ws.batch_update([
        {"range": gspread.utils.rowcol_to_a1(row, S_CASH + 1), "values": [[0]]},
        {"range": gspread.utils.rowcol_to_a1(row, S_UPI + 1), "values": [[0]]},
        {"range": gspread.utils.rowcol_to_a1(row, S_TOTAL + 1), "values": [[0]]},
        {"range": gspread.utils.rowcol_to_a1(row, S_BAL + 1), "values": [[rent_due]]},
        {"range": gspread.utils.rowcol_to_a1(row, S_STATUS + 1), "values": [["UNPAID"]]},
        {"range": gspread.utils.rowcol_to_a1(row, S_NOTES + 1), "values": [[""]]},
    ], value_input_option="USER_ENTERED")
    import time
    time.sleep(1)


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
    """Payment with explicit UPI mode — verify DB + Sheet."""
    print("\n=== TEST 01: Payment with UPI + Sheet sync ===")
    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    check("01a_confirm_prompt", r["reply"],
          ["krishnanshu", "5,000", "upi", "yes"],
          ["suggested allocation"])

    r = await send(ADMIN_PHONE, "yes")
    check("01b_payment_logged", r["reply"],
          ["payment logged", "5,000", "upi"])

    await verify_db_payment("Krishnanshu", 1, 5000.0)
    verify_sheet("01c_sheet_after_pay", "211", "Krishnanshu",
                 expected_upi=5000.0, expected_cash=0.0, expected_status="PARTIAL")

    # Void it
    r = await send(ADMIN_PHONE, "void payment Krishnanshu")
    if "void this payment" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "1")
    elif "which" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "2")
        r = await send(ADMIN_PHONE, "1")

    check("01d_voided", r["reply"], ["voided", "krishnanshu"])
    await verify_db_payment("Krishnanshu", 0)
    verify_sheet("01e_sheet_after_void", "211", "Krishnanshu",
                 expected_upi=0.0, expected_cash=0.0, expected_status="UNPAID")


async def test_02_payment_with_cash():
    """Payment with explicit CASH mode — verify DB + Sheet."""
    print("\n=== TEST 02: Payment with CASH + Sheet sync ===")
    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 cash")
    check("02a_confirm_prompt", r["reply"],
          ["krishnanshu", "5,000", "cash", "yes"])

    r = await send(ADMIN_PHONE, "yes")
    check("02b_payment_logged", r["reply"],
          ["payment logged", "5,000", "cash"])

    await verify_db_payment("Krishnanshu", 1, 5000.0)
    verify_sheet("02c_sheet", "211", "Krishnanshu",
                 expected_cash=5000.0, expected_upi=0.0, expected_status="PARTIAL")

    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")


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
    """Full rent payment shows PAID status — verify DB + Sheet."""
    print("\n=== TEST 06: Full payment = PAID + Sheet sync ===")
    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 15000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("06a_paid_status", r["reply"], ["payment logged", "paid"])

    await verify_db_payment("Krishnanshu", 1, 15000.0)
    verify_sheet("06b_sheet_paid", "211", "Krishnanshu",
                 expected_upi=15000.0, expected_status="PAID")

    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")


async def test_07_partial_then_full():
    """Two partial payments — verify DB + Sheet after each."""
    print("\n=== TEST 07: Partial + Partial = PAID + Sheet sync ===")
    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")

    # First partial
    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("07a_partial", r["reply"], ["partial"])
    verify_sheet("07b_sheet_partial", "211", "Krishnanshu",
                 expected_upi=5000.0, expected_cash=0.0, expected_status="PARTIAL")

    # Second partial to complete
    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 10000 cash")
    r = await send(ADMIN_PHONE, "yes")
    check("07c_paid", r["reply"], ["paid"])
    verify_sheet("07d_sheet_paid", "211", "Krishnanshu",
                 expected_upi=5000.0, expected_cash=10000.0, expected_status="PAID")

    await verify_db_payment("Krishnanshu", 2, 15000.0)
    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")


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
    """Void defaults to current month — verify DB + Sheet."""
    print("\n=== TEST 09: Void current month + Sheet sync ===")
    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    r = await send(ADMIN_PHONE, "yes")
    verify_sheet("09a_sheet_after_pay", "211", "Krishnanshu",
                 expected_upi=5000.0, expected_status="PARTIAL")

    r = await send(ADMIN_PHONE, "void payment Krishnanshu")
    if "void this payment" in r["reply"].lower():
        check("09b_shows_april", r["reply"], ["apr 2026"])
        r = await send(ADMIN_PHONE, "1")
        check("09c_voided", r["reply"], ["voided"])
    elif "which" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "2")
        r = await send(ADMIN_PHONE, "1")
        check("09c_voided", r["reply"], ["voided"])

    await verify_db_payment("Krishnanshu", 0)
    verify_sheet("09d_sheet_after_void", "211", "Krishnanshu",
                 expected_upi=0.0, expected_cash=0.0, expected_status="UNPAID")
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
    r = await send(ADMIN_PHONE, "cancel")
    await cleanup_test_tenant("Krishnanshu")


async def test_13_who_hasnt_paid():
    """Query unpaid tenants."""
    print("\n=== TEST 13: Who hasn't paid ===")
    # Clear any stale pending from previous test
    async with SessionFactory() as session:
        await session.execute(text("DELETE FROM pending_actions WHERE phone = :p"), {"p": ADMIN_PHONE})
        await session.commit()
    r = await send(ADMIN_PHONE, "who hasn't paid")
    check("13_unpaid_list", r["reply"], ["outstanding", "rs."])


async def test_14_single_month_no_allocation_noise():
    """Single month dues should NOT show 'Suggested allocation'."""
    print("\n=== TEST 14: No allocation noise for single month ===")
    await cleanup_test_tenant("Krishnanshu")
    # Clear any stale pending
    async with SessionFactory() as session:
        await session.execute(text("DELETE FROM pending_actions WHERE phone = :p"), {"p": ADMIN_PHONE})
        await session.commit()

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


async def test_19_netbanking_as_upi():
    """Netbanking maps to UPI."""
    print("\n=== TEST 19: Netbanking = UPI ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 netbanking")
    check("19_netbanking", r["reply"], ["upi"])
    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_20_neft_as_upi():
    """NEFT maps to UPI."""
    print("\n=== TEST 20: NEFT = UPI ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 neft")
    check("20_neft", r["reply"], ["upi"])
    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_21_amount_correction():
    """Correct amount during confirmation."""
    print("\n=== TEST 21: Amount correction ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    check("21a_shows_5000", r["reply"], ["5,000"])

    r = await send(ADMIN_PHONE, "10000")
    check("21b_corrected", r["reply"], ["10,000", "confirm"])

    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_22_payment_then_check_balance():
    """Log payment then check tenant balance."""
    print("\n=== TEST 22: Payment then balance check ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("22a_logged", r["reply"], ["payment logged"])

    await clear_pendings()
    r = await send(ADMIN_PHONE, "Krishnanshu balance")
    check("22b_balance", r["reply"], ["krishnanshu", "10,000"])  # 15000-5000=10000 outstanding

    await cleanup_test_tenant("Krishnanshu")


async def test_23_multiple_tenants_same_room():
    """Room with multiple tenants shows disambiguation."""
    print("\n=== TEST 23: Multiple tenants same room ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "room 211 paid 5000 upi")
    check("23_disambig", r["reply"], ["jay gandhi", "krishnanshu", "which"])
    r = await send(ADMIN_PHONE, "cancel")


async def test_24_void_keep_payment():
    """Void but choose to keep the payment."""
    print("\n=== TEST 24: Void but keep ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 upi")
    r = await send(ADMIN_PHONE, "yes")

    r = await send(ADMIN_PHONE, "void payment Krishnanshu")
    if "void this payment" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "2")  # No, keep it
        check("24_kept", r["reply"], ["cancel", "remains"])
    elif "which" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "2")
        r = await send(ADMIN_PHONE, "2")
        check("24_kept", r["reply"], ["cancel", "remains"])

    await verify_db_payment("Krishnanshu", 1, 5000.0)
    await cleanup_test_tenant("Krishnanshu")


async def test_25_payment_with_comma_amount():
    """Amount with commas (15,000)."""
    print("\n=== TEST 25: Amount with commas ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 15,000 upi")
    check("25_comma", r["reply"], ["15,000"])
    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_26_query_dues():
    """Query specific tenant dues."""
    print("\n=== TEST 26: Query dues ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "how much does Krishnanshu owe")
    check("26_dues", r["reply"], ["krishnanshu"])
    if "which" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "cancel")


async def test_27_collect_rent_flow():
    """Step-by-step collect rent flow."""
    print("\n=== TEST 27: Collect rent step-by-step ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "collect rent")
    check("27a_asks_who", r["reply"], ["who paid"])

    r = await send(ADMIN_PHONE, "Krishnanshu")
    # Should show tenant or ask for disambiguation
    check("27b_found", r["reply"], ["krishnanshu"])
    r = await send(ADMIN_PHONE, "cancel")


async def test_28_monthly_report():
    """Monthly report generation."""
    print("\n=== TEST 28: Monthly report ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "monthly report")
    check("28_report", r["reply"], ["april", "202"])


async def test_29_payment_different_tenant():
    """Payment for a different tenant (not Krishnanshu)."""
    print("\n=== TEST 29: Different tenant - Akarsh ===")
    await cleanup_test_tenant("Akarsh")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Akarsh room 102 paid 5000 cash")
    check("29a_confirm", r["reply"], ["akarsh", "5,000", "cash"])

    r = await send(ADMIN_PHONE, "yes")
    check("29b_logged", r["reply"], ["payment logged"])

    await verify_db_payment("Akarsh", 1, 5000.0)
    await cleanup_test_tenant("Akarsh")


async def test_30_payment_name_only():
    """Payment with name only, no room number."""
    print("\n=== TEST 30: Payment name only ===")
    await cleanup_test_tenant("Ronak")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Ronak paid 10000 upi")
    check("30_name_only", r["reply"], ["ronak"])
    r = await send(ADMIN_PHONE, "cancel") if "cancel" not in r["reply"].lower() else r
    await cleanup_test_tenant("Ronak")


async def test_31_exact_rent_amount():
    """Pay exact rent amount for different tenant."""
    print("\n=== TEST 31: Exact rent Ronak (15000) ===")
    await cleanup_test_tenant("Ronak")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Ronak Samriya paid 15000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("31_paid", r["reply"], ["paid"])

    await verify_db_payment("Ronak", 1, 15000.0)
    await cleanup_test_tenant("Ronak")


async def test_32_payment_wrong_name():
    """Payment with misspelled name."""
    print("\n=== TEST 32: Misspelled name ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishanshu paid 5000 upi")
    # Should fuzzy match to Krishnanshu
    check("32_fuzzy", r["reply"], ["krishnanshu"])
    r = await send(ADMIN_PHONE, "cancel")


async def test_33_void_nonexistent():
    """Void when no payment exists for current month."""
    print("\n=== TEST 33: Void nonexistent ===")
    await cleanup_test_tenant("Ronak")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "void payment Ronak Samriya")
    check("33_no_payment", r["reply"], ["no active payment"])


async def test_34_payment_with_for_month():
    """Payment specifying month explicitly."""
    print("\n=== TEST 34: Payment for specific month ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 15000 upi april")
    check("34_april", r["reply"], ["april 2026"])
    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_35_multiple_payments_different_modes():
    """Multiple payments with different modes for same tenant."""
    print("\n=== TEST 35: Cash + UPI payments ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 cash")
    r = await send(ADMIN_PHONE, "yes")
    check("35a_cash", r["reply"], ["payment logged", "cash"])

    await clear_pendings()
    # Use different amount to avoid duplicate detection
    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 7000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("35b_upi", r["reply"], ["payment logged", "upi"])

    await verify_db_payment("Krishnanshu", 2, 12000.0)
    await cleanup_test_tenant("Krishnanshu")


async def test_36_add_tenant_flow():
    """Add new tenant step-by-step."""
    print("\n=== TEST 36: Add tenant flow ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "add tenant")
    check("36a_asks_name", r["reply"], ["name"])

    r = await send(ADMIN_PHONE, "cancel")


async def test_37_checkout_flow():
    """Checkout tenant flow."""
    print("\n=== TEST 37: Checkout flow ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "checkout Krishnanshu")
    # Should start checkout or ask which tenant
    check("37_checkout", r["reply"], ["krishnanshu"])
    r = await send(ADMIN_PHONE, "cancel")


async def test_38_notice_given():
    """Give notice to tenant."""
    print("\n=== TEST 38: Notice given ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu notice given")
    check("38_notice", r["reply"], ["krishnanshu"])
    r = await send(ADMIN_PHONE, "cancel")


async def test_39_occupied_beds():
    """Check occupancy."""
    print("\n=== TEST 39: Occupancy ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "occupancy")
    check("39_occupancy", r["reply"], ["occupied", "bed"])


async def test_40_vacant_beds():
    """Check vacant beds."""
    print("\n=== TEST 40: Vacant beds ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "how many beds are vacant")
    check("40_vacant", r["reply"], ["vacant"])


async def test_41_no_shows():
    """Check no-shows."""
    print("\n=== TEST 41: No shows ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "list all no show tenants")
    check("41_noshows", r["reply"], ["no"])


async def test_42_rent_change():
    """Request rent change."""
    print("\n=== TEST 42: Rent change ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "change rent Krishnanshu to 16000")
    check("42_rent_change", r["reply"], ["krishnanshu"])
    r = await send(ADMIN_PHONE, "cancel")


async def test_43_add_expense():
    """Log an expense."""
    print("\n=== TEST 43: Add expense ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "cleaning 5000 cash")
    check("43_expense", r["reply"], ["5,000"])
    r = await send(ADMIN_PHONE, "cancel") if "yes" in r["reply"].lower() else r


async def test_44_payment_exact_rent_multiple_tenants():
    """Full payment clearing balance for different tenants."""
    print("\n=== TEST 44: Full payment Prashant ===")
    await cleanup_test_tenant("Prashant")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Prashant room 102 paid 15000 cash")
    r = await send(ADMIN_PHONE, "yes")
    check("44_paid", r["reply"], ["payment logged"])

    await verify_db_payment("Prashant", 1, 15000.0)
    await cleanup_test_tenant("Prashant")


async def test_45_correction_mode_then_confirm():
    """Correct mode then confirm in one flow."""
    print("\n=== TEST 45: Correct mode + confirm ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000")
    check("45a_default_cash", r["reply"], ["cash"])

    r = await send(ADMIN_PHONE, "upi")
    check("45b_updated", r["reply"], ["upi"])

    r = await send(ADMIN_PHONE, "yes")
    check("45c_logged_upi", r["reply"], ["payment logged", "upi"])

    await verify_db_payment("Krishnanshu", 1, 5000.0)
    await cleanup_test_tenant("Krishnanshu")


async def test_46_void_then_relog():
    """Void a payment then log correct one — verify DB + Sheet at each step."""
    print("\n=== TEST 46: Void then relog + Sheet sync ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()
    reset_sheet_row("211", "Krishnanshu")

    # Log wrong amount
    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 cash")
    r = await send(ADMIN_PHONE, "yes")
    check("46a_logged", r["reply"], ["payment logged"])
    verify_sheet("46b_sheet_wrong", "211", "Krishnanshu",
                 expected_cash=5000.0, expected_status="PARTIAL")

    # Void it
    r = await send(ADMIN_PHONE, "void payment Krishnanshu")
    if "void this payment" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "1")
    elif "which" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "2")
        r = await send(ADMIN_PHONE, "1")
    check("46c_voided", r["reply"], ["voided"])
    verify_sheet("46d_sheet_voided", "211", "Krishnanshu",
                 expected_cash=0.0, expected_upi=0.0, expected_status="UNPAID")

    # Relog correct amount
    await clear_pendings()
    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 10000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("46e_relogged", r["reply"], ["payment logged", "upi", "10,000"])
    verify_sheet("46f_sheet_correct", "211", "Krishnanshu",
                 expected_upi=10000.0, expected_cash=0.0, expected_status="PARTIAL")

    await verify_db_payment("Krishnanshu", 1, 10000.0)
    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")


async def test_47_payment_various_formats():
    """Various message formats for payment."""
    print("\n=== TEST 47: Various payment formats ===")
    await cleanup_test_tenant("Krishnanshu")

    formats = [
        "Krishnanshu paid 5000 upi",
        "Krishnanshu room 211 paid 5000",
        "5000 from Krishnanshu upi",
        "received 5000 from Krishnanshu",
    ]
    for i, fmt in enumerate(formats):
        await clear_pendings()
        r = await send(ADMIN_PHONE, fmt)
        check(f"47_{i}_{fmt[:30]}", r["reply"], ["krishnanshu"])
        r = await send(ADMIN_PHONE, "cancel")
        await cleanup_test_tenant("Krishnanshu")


async def test_48_payment_no_amount():
    """Payment without amount should ask for it."""
    print("\n=== TEST 48: No amount ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu paid upi")
    check("48_no_amount", r["reply"], ["amount", "include"])


async def test_49_payment_no_name():
    """Payment with amount but no name."""
    print("\n=== TEST 49: No name ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "paid 5000 upi")
    check("49_no_name", r["reply"], ["who"])


async def test_50_three_partial_payments():
    """Three partial payments — verify DB + Sheet cumulative."""
    print("\n=== TEST 50: Three partials + Sheet sync ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()
    reset_sheet_row("211", "Krishnanshu")

    # Use different amounts to avoid duplicate detection
    for i, (amt, mode) in enumerate([(3000, "cash"), (5000, "upi"), (7000, "cash")]):
        r = await send(ADMIN_PHONE, f"Krishnanshu room 211 paid {amt} {mode}")
        r = await send(ADMIN_PHONE, "yes")
        if i < 2:
            check(f"50_{i}_partial", r["reply"], ["partial"])
        else:
            check(f"50_{i}_paid", r["reply"], ["paid"])
        await clear_pendings()

    await verify_db_payment("Krishnanshu", 3, 15000.0)
    verify_sheet("50_sheet_final", "211", "Krishnanshu",
                 expected_cash=10000.0, expected_upi=5000.0, expected_status="PAID")

    await cleanup_test_tenant("Krishnanshu")
    reset_sheet_row("211", "Krishnanshu")


# =============================================================================
# FULL LIFECYCLE TESTS (51-100)
# =============================================================================

async def cleanup_test_data(name: str):
    """Full cleanup: payments, rent_schedule, tenancy, tenant."""
    async with SessionFactory() as session:
        await session.execute(text("""
            DELETE FROM payments WHERE tenancy_id IN (
                SELECT tn.id FROM tenancies tn JOIN tenants t ON t.id = tn.tenant_id
                WHERE t.name ILIKE :name)
        """), {"name": f"%{name}%"})
        await session.execute(text("""
            DELETE FROM rent_schedule WHERE tenancy_id IN (
                SELECT tn.id FROM tenancies tn JOIN tenants t ON t.id = tn.tenant_id
                WHERE t.name ILIKE :name)
        """), {"name": f"%{name}%"})
        await session.execute(text("""
            DELETE FROM tenancies WHERE tenant_id IN (
                SELECT id FROM tenants WHERE name ILIKE :name)
        """), {"name": f"%{name}%"})
        await session.execute(text("""
            DELETE FROM tenants WHERE name ILIKE :name
        """), {"name": f"%{name}%"})
        await session.execute(text("DELETE FROM pending_actions WHERE phone = :p"), {"p": ADMIN_PHONE})
        await session.commit()


async def verify_db_tenant(name: str) -> dict:
    """Check if tenant exists in DB and return info."""
    async with SessionFactory() as session:
        r = await session.execute(text("""
            SELECT t.name, t.phone, t.gender, tn.status, tn.agreed_rent, tn.security_deposit,
                   tn.checkin_date, r.room_number, tn.maintenance_fee
            FROM tenants t
            JOIN tenancies tn ON tn.tenant_id = t.id
            JOIN rooms r ON r.id = tn.room_id
            WHERE t.name ILIKE :name
            ORDER BY tn.created_at DESC LIMIT 1
        """), {"name": f"%{name}%"})
        row = r.fetchone()
        if row:
            return {
                "name": row[0], "phone": row[1], "gender": row[2],
                "status": row[3], "rent": float(row[4] or 0),
                "deposit": float(row[5] or 0), "checkin": row[6],
                "room": row[7], "maintenance": float(row[8] or 0),
            }
        return None


async def test_51_add_tenant_full_flow():
    """Full add tenant: name → phone → gender → food → room → rent → deposit → advance → maintenance → checkin → notes → confirm."""
    global PASS, FAIL
    print("\n=== TEST 51: Add tenant full flow ===")
    await cleanup_test_data("Testuser Alpha")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "add tenant")
    check("51a_asks_name", r["reply"], ["name"])

    r = await send(ADMIN_PHONE, "Testuser Alpha")
    check("51b_asks_phone", r["reply"], ["phone"])

    r = await send(ADMIN_PHONE, "9876543210")
    check("51c_asks_gender", r["reply"], ["gender"])

    r = await send(ADMIN_PHONE, "male")
    check("51d_asks_food", r["reply"], ["food"])

    r = await send(ADMIN_PHONE, "non-veg")
    check("51e_asks_room", r["reply"], ["room"])

    r = await send(ADMIN_PHONE, "101")
    check("51f_asks_rent", r["reply"], ["rent"])

    r = await send(ADMIN_PHONE, "15000")
    check("51g_asks_deposit", r["reply"], ["deposit"])

    r = await send(ADMIN_PHONE, "15000")
    check("51h_asks_advance", r["reply"], ["paid", "advance"])

    r = await send(ADMIN_PHONE, "5000")
    check("51i_asks_maintenance", r["reply"], ["maintenance"])

    r = await send(ADMIN_PHONE, "5000")
    check("51j_asks_checkin", r["reply"], ["check-in", "date"])

    r = await send(ADMIN_PHONE, "1 april 2026")
    check("51k_asks_notes", r["reply"], ["notes"])

    r = await send(ADMIN_PHONE, "3 month lockin")
    check("51l_confirm", r["reply"], ["testuser alpha", "15,000", "confirm"])

    r = await send(ADMIN_PHONE, "yes")
    check("51m_saved", r["reply"], ["saved", "testuser alpha"])

    # Verify DB
    tenant = await verify_db_tenant("Testuser Alpha")
    if tenant:
        global PASS, FAIL
        if tenant["rent"] == 15000.0 and tenant["status"] == "active":
            PASS += 1
            print(f"  DB OK [51n]: rent={tenant['rent']}, status={tenant['status']}, room={tenant['room']}")
        else:
            FAIL += 1
            ERRORS.append("51n_db")
            print(f"  DB FAIL [51n]: {tenant}")
    else:
        FAIL += 1
        ERRORS.append("51n_db")
        print("  DB FAIL [51n]: Tenant not found in DB")

    await cleanup_test_data("Testuser Alpha")


async def test_52_add_tenant_cancel():
    """Cancel add tenant midway."""
    print("\n=== TEST 52: Add tenant cancel ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "add tenant")
    check("52a_asks_name", r["reply"], ["name"])

    r = await send(ADMIN_PHONE, "cancel")
    check("52b_cancelled", r["reply"], ["cancel"])


async def test_53_add_tenant_skip_optional():
    """Add tenant with skip on optional fields."""
    global PASS, FAIL
    print("\n=== TEST 53: Add tenant skip optional ===")
    await cleanup_test_data("Testuser Beta")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "add tenant")
    r = await send(ADMIN_PHONE, "Testuser Beta")
    r = await send(ADMIN_PHONE, "9876543211")
    r = await send(ADMIN_PHONE, "female")
    r = await send(ADMIN_PHONE, "skip")  # food
    r = await send(ADMIN_PHONE, "203")   # room
    r = await send(ADMIN_PHONE, "12000")  # rent
    r = await send(ADMIN_PHONE, "skip")  # deposit
    # Should skip advance since deposit=0
    r = await send(ADMIN_PHONE, "skip")  # maintenance
    r = await send(ADMIN_PHONE, "15 april 2026")  # checkin
    r = await send(ADMIN_PHONE, "skip")  # notes
    check("53a_confirm", r["reply"], ["testuser beta", "confirm"])

    r = await send(ADMIN_PHONE, "yes")
    check("53b_saved", r["reply"], ["saved"])

    tenant = await verify_db_tenant("Testuser Beta")
    if tenant:
        PASS += 1
        print(f"  DB OK [53c]: rent={tenant['rent']}, gender={tenant['gender']}")
    else:
        FAIL += 1
        ERRORS.append("53c_db")
        print("  DB FAIL [53c]: Tenant not found")

    await cleanup_test_data("Testuser Beta")


async def test_54_checkout_flow():
    """Full checkout flow for existing tenant."""
    print("\n=== TEST 54: Checkout flow ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "checkout Manoj")
    check("54a_starts", r["reply"], ["manoj"])

    if "exit date" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "today")
        check("54b_cupboard", r["reply"], ["cupboard", "key"])

        r = await send(ADMIN_PHONE, "yes")
        check("54c_main_key", r["reply"], ["main", "key"])

        r = await send(ADMIN_PHONE, "yes")
        check("54d_damage", r["reply"], ["damage"])

        r = await send(ADMIN_PHONE, "no")
        check("54e_fingerprint", r["reply"], ["fingerprint", "biometric"])

        r = await send(ADMIN_PHONE, "yes")
        check("54f_summary", r["reply"], ["settlement", "confirm"])

        # Cancel — don't actually check out Manoj
        r = await send(ADMIN_PHONE, "cancel")
        check("54g_cancelled", r["reply"], ["cancel"])
    else:
        # Might show disambiguation
        r = await send(ADMIN_PHONE, "cancel")
        check("54b_cancelled", r["reply"], ["cancel"])


async def test_55_notice_then_checkout():
    """Give notice then checkout."""
    print("\n=== TEST 55: Notice flow ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Ronak notice")
    check("55a_notice", r["reply"], ["ronak"])
    r = await send(ADMIN_PHONE, "cancel")


async def test_56_payment_log_then_balance():
    """Log payment, check balance, void, check balance again."""
    print("\n=== TEST 56: Pay → balance → void → balance ===")
    await cleanup_test_tenant("Akarsh")
    await clear_pendings()
    reset_sheet_row("102", "Akarsh")

    # Pay
    r = await send(ADMIN_PHONE, "Akarsh SM room 102 paid 8000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("56a_paid", r["reply"], ["payment logged", "8,000"])

    # Check balance
    await clear_pendings()
    r = await send(ADMIN_PHONE, "Akarsh balance")
    check("56b_balance", r["reply"], ["7,000"])  # 15000-8000=7000

    # Void
    await clear_pendings()
    r = await send(ADMIN_PHONE, "void payment Akarsh SM")
    if "void this payment" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "1")
    check("56c_voided", r["reply"], ["voided"])

    # Check balance after void
    await clear_pendings()
    r = await send(ADMIN_PHONE, "Akarsh balance")
    check("56d_balance_after", r["reply"], ["15,000"])  # back to full

    verify_sheet("56e_sheet", "102", "Akarsh",
                 expected_cash=0.0, expected_upi=0.0, expected_status="UNPAID")

    await cleanup_test_tenant("Akarsh")


async def test_57_multiple_tenants_different_rooms():
    """Payments for different tenants in different rooms."""
    print("\n=== TEST 57: Multi-tenant payments ===")
    await clear_pendings()

    # Akarsh room 102
    await cleanup_test_tenant("Akarsh")
    r = await send(ADMIN_PHONE, "Akarsh SM room 102 paid 5000 cash")
    r = await send(ADMIN_PHONE, "yes")
    check("57a_akarsh", r["reply"], ["payment logged"])

    # Ronak room 203
    await clear_pendings()
    await cleanup_test_tenant("Ronak")
    r = await send(ADMIN_PHONE, "Ronak Samriya paid 8000 upi")
    r = await send(ADMIN_PHONE, "yes")
    check("57b_ronak", r["reply"], ["payment logged"])

    await verify_db_payment("Akarsh", 1, 5000.0)
    await verify_db_payment("Ronak", 1, 8000.0)

    await cleanup_test_tenant("Akarsh")
    await cleanup_test_tenant("Ronak")


async def test_58_expense_log():
    """Log an expense and verify."""
    print("\n=== TEST 58: Expense log ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "generator diesel 5000 cash")
    check("58a_expense", r["reply"], ["5,000"])

    if "yes" in r["reply"].lower():
        r = await send(ADMIN_PHONE, "no")  # don't actually log


async def test_59_payment_with_imps():
    """IMPS maps to UPI."""
    print("\n=== TEST 59: IMPS = UPI ===")
    await cleanup_test_tenant("Krishnanshu")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "Krishnanshu room 211 paid 5000 imps")
    check("59_imps", r["reply"], ["upi"])
    r = await send(ADMIN_PHONE, "no")
    await cleanup_test_tenant("Krishnanshu")


async def test_60_add_tenant_existing_phone():
    """Add tenant with phone that already exists — should link to existing tenant."""
    print("\n=== TEST 60: Add tenant existing phone ===")
    await clear_pendings()

    r = await send(ADMIN_PHONE, "add tenant")
    r = await send(ADMIN_PHONE, "Test Duplicate")
    # Use Krishnanshu's phone
    r = await send(ADMIN_PHONE, "6284043938")
    # Should either link to existing or continue
    check("60_existing", r["reply"], ["gender", "already"])
    r = await send(ADMIN_PHONE, "cancel")


# ── Helper ──

async def clear_pendings():
    async with SessionFactory() as session:
        await session.execute(text("DELETE FROM pending_actions WHERE phone = :p"), {"p": ADMIN_PHONE})
        await session.commit()


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
        test_19_netbanking_as_upi,
        test_20_neft_as_upi,
        test_21_amount_correction,
        test_22_payment_then_check_balance,
        test_23_multiple_tenants_same_room,
        test_24_void_keep_payment,
        test_25_payment_with_comma_amount,
        test_26_query_dues,
        test_27_collect_rent_flow,
        test_28_monthly_report,
        test_29_payment_different_tenant,
        test_30_payment_name_only,
        test_31_exact_rent_amount,
        test_32_payment_wrong_name,
        test_33_void_nonexistent,
        test_34_payment_with_for_month,
        test_35_multiple_payments_different_modes,
        test_36_add_tenant_flow,
        test_37_checkout_flow,
        test_38_notice_given,
        test_39_occupied_beds,
        test_40_vacant_beds,
        test_41_no_shows,
        test_42_rent_change,
        test_43_add_expense,
        test_44_payment_exact_rent_multiple_tenants,
        test_45_correction_mode_then_confirm,
        test_46_void_then_relog,
        test_47_payment_various_formats,
        test_48_payment_no_amount,
        test_49_payment_no_name,
        test_50_three_partial_payments,
        test_51_add_tenant_full_flow,
        test_52_add_tenant_cancel,
        test_53_add_tenant_skip_optional,
        test_54_checkout_flow,
        test_55_notice_then_checkout,
        test_56_payment_log_then_balance,
        test_57_multiple_tenants_different_rooms,
        test_58_expense_log,
        test_59_payment_with_imps,
        test_60_add_tenant_existing_phone,
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
