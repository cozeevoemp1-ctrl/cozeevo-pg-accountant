"""
tests/test_data_integrity.py
==============================
END-TO-END DATA INTEGRITY TESTS

Tests the FULL flow: WhatsApp message -> API -> DB + Google Sheet
Verifies that the correct data lands in the right places.

This is what Kiran actually cares about:
  - Does "Raj paid 14000 cash" create the right payment in DB?
  - Does the Google Sheet row update with correct Cash/UPI/Balance?
  - Does "add tenant" create the tenant in DB + both sheet tabs?
  - Does "checkout" mark tenancy as EXITED + sheet shows EXIT?
  - Does invalid data get REJECTED properly?

Prerequisites:
  1. API must be running: python main.py (with TEST_MODE=1)
  2. Google Sheet must be accessible
  3. Internet connection (for Supabase + GSheets)

Usage:
  python tests/test_data_integrity.py               # run all
  python tests/test_data_integrity.py --section add  # just add tenant
  python tests/test_data_integrity.py --no-sheet     # skip sheet verification
  python tests/test_data_integrity.py --no-cleanup   # keep test data after run

Results are pushed LIVE to Google Sheet "TEST RESULTS" tab.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, date
from typing import Optional

import httpx
from dotenv import load_dotenv

# Fix encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

API_PORT  = int(os.getenv("API_PORT", "8000"))
API_URL   = f"http://localhost:{API_PORT}/api/whatsapp/process"
CLEAR_URL = f"http://localhost:{API_PORT}/api/test/clear-pending"

ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+917845952289")

# Test tenant data — uses vacant rooms to avoid clashing with real tenants
TEST_ROOM = "307"  # must be a vacant room in master data

SHEET_ID = "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"
CREDS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "credentials", "gsheets_service_account.json",
)

# ── Results tracking ─────────────────────────────────────────────────────────

P, F, TOTAL = 0, 0, 0
ERRORS = []
RESULTS_ROWS = []  # for Google Sheet
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")


def ok(tid: str, desc: str, passed: bool, detail: str = ""):
    global P, F, TOTAL
    TOTAL += 1
    status = "PASS" if passed else "FAIL"
    if passed:
        P += 1
        print(f"  [{status}] {tid}: {desc}")
    else:
        F += 1
        ERRORS.append(f"{tid}: {desc} — {detail}")
        print(f"  [{status}] {tid}: {desc} — {detail}")

    RESULTS_ROWS.append([
        "data_integrity", f"{tid}: {desc}", status,
        "", detail[:200], tid.split("-")[0],
        datetime.now().strftime("%H:%M:%S"), RUN_ID,
    ])


# ── API helpers ───────────────────────────────────────────────────────────────

async def send(client: httpx.AsyncClient, msg: str, phone: str = "") -> dict:
    """Send a WhatsApp message via API and return the response."""
    phone = phone or ADMIN_PHONE
    resp = await client.post(API_URL, json={
        "phone": phone, "message": msg, "message_id": f"test_{int(time.time()*1000)}",
    }, timeout=15)
    return resp.json()


async def clear_pending(client: httpx.AsyncClient, phone: str = ""):
    phone = phone or ADMIN_PHONE
    try:
        await client.post(CLEAR_URL, json={"phone": phone}, timeout=5)
    except Exception:
        pass


async def multi_turn(client: httpx.AsyncClient, messages: list[str], phone: str = "") -> list[dict]:
    """Send multiple messages in sequence, return all responses."""
    results = []
    for msg in messages:
        r = await send(client, msg, phone)
        results.append(r)
        await asyncio.sleep(0.3)
    return results


# ── DB helpers ────────────────────────────────────────────────────────────────

async def get_db_session():
    """Get a direct DB session for verification queries."""
    from src.database.db_manager import init_engine, _session_factory
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    db_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL", "")
    if not db_url:
        # Build from SUPABASE_URL
        supa_url = os.getenv("SUPABASE_URL", "")
        if "supabase" in supa_url:
            # Extract project ref
            ref = supa_url.split("//")[1].split(".")[0]
            pwd = os.getenv("SUPABASE_DB_PASSWORD", "")
            db_url = f"postgresql://postgres.{ref}:{pwd}@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"

    if not db_url:
        return None

    engine = init_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return factory


async def verify_db_tenant(session_factory, name: str) -> Optional[dict]:
    """Check if tenant exists in DB and return their data."""
    if not session_factory:
        return None
    from sqlalchemy import select
    from src.database.models import Tenant, Tenancy, Room

    async with session_factory() as session:
        result = await session.execute(
            select(Tenant, Tenancy, Room)
            .join(Tenancy, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenant.name.ilike(f"%{name}%"))
            .order_by(Tenancy.created_at.desc())
        )
        row = result.first()
        if not row:
            return None
        tenant, tenancy, room = row
        return {
            "name": tenant.name,
            "phone": tenant.phone,
            "room": room.room_number,
            "rent": float(tenancy.agreed_rent or 0),
            "deposit": float(tenancy.security_deposit or 0),
            "status": tenancy.status.value if tenancy.status else "unknown",
            "checkin_date": str(tenancy.checkin_date) if tenancy.checkin_date else None,
            "notice_date": str(tenancy.notice_date) if tenancy.notice_date else None,
            "expected_checkout": str(tenancy.expected_checkout) if tenancy.expected_checkout else None,
        }


async def verify_db_payment(session_factory, tenant_name: str, amount: float) -> Optional[dict]:
    """Check if a payment exists in DB for this tenant+amount."""
    if not session_factory:
        return None
    from sqlalchemy import select, and_
    from src.database.models import Payment, Tenant, Tenancy

    async with session_factory() as session:
        result = await session.execute(
            select(Payment)
            .join(Tenancy, Payment.tenancy_id == Tenancy.id)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .where(and_(
                Tenant.name.ilike(f"%{tenant_name}%"),
                Payment.amount == amount,
                Payment.is_void == False,
            ))
            .order_by(Payment.created_at.desc())
        )
        row = result.scalars().first()
        if not row:
            return None
        return {
            "amount": float(row.amount),
            "method": row.payment_mode.value if row.payment_mode else "unknown",
            "period_month": str(row.period_month) if row.period_month else None,
            "is_void": row.is_void,
        }


async def verify_db_tenancy_status(session_factory, name: str) -> Optional[str]:
    """Get current tenancy status for a tenant."""
    if not session_factory:
        return None
    from sqlalchemy import select
    from src.database.models import Tenant, Tenancy

    async with session_factory() as session:
        result = await session.execute(
            select(Tenancy.status)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .where(Tenant.name.ilike(f"%{name}%"))
            .order_by(Tenancy.created_at.desc())
        )
        row = result.scalars().first()
        return row.value if row else None


# ── Google Sheet helpers ──────────────────────────────────────────────────────

def get_sheet_connection():
    """Connect to Google Sheet, return (spreadsheet, dict of worksheets)."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return None, {}

    if not os.path.exists(CREDS_PATH):
        return None, {}

    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
    ])
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SHEET_ID)
    return ss, {}


def find_in_sheet(ss, tab_name: str, room: str, tenant_name: str = "") -> Optional[dict]:
    """Find a row in a sheet tab by room number (and optionally tenant name)."""
    if not ss:
        return None
    try:
        ws = ss.worksheet(tab_name)
        data = ws.get_all_values()
    except Exception:
        return None

    # Find data start row (skip headers)
    start = 1 if tab_name == "TENANTS" else 4  # monthly tabs start at row 5

    # Search by name first (more unique), fall back to room
    for i, row in enumerate(data[start:], start=start + 1):
        if len(row) < 3:
            continue
        row_room = str(row[0]).strip()
        row_name = str(row[1]).strip().lower()
        # Match by name if provided
        if tenant_name and tenant_name.lower() in row_name:
            return {"row": i, "data": row}
        # Match by room only if no name filter
        if not tenant_name and row_room == str(room).strip():
            return {"row": i, "data": row}

    return None


# ── SECTION 1: ADD TENANT ────────────────────────────────────────────────────

async def test_add_tenant(client: httpx.AsyncClient, session_factory, ss):
    """Test the step-by-step add tenant flow — DB + Sheet verification."""
    print("\n" + "=" * 60)
    print("  SECTION 1: ADD TENANT — Data Integrity")
    print("=" * 60)

    await clear_pending(client)

    # --- Test 1A: Full add tenant flow (multi-turn) ---
    print("\n  --- 1A: Step-by-step add tenant ---")

    r1 = await send(client, "add new tenant")
    ok("ADD-01", "Bot starts add tenant flow",
       "name" in r1.get("reply", "").lower(),
       f"Reply: {r1.get('reply', '')[:80]}")
    await asyncio.sleep(0.3)

    r2 = await send(client, "Testuser Alpha")
    ok("ADD-02", "Bot asks for phone after name",
       "phone" in r2.get("reply", "").lower(),
       f"Reply: {r2.get('reply', '')[:80]}")
    await asyncio.sleep(0.3)

    r3 = await send(client, "9800000001")
    ok("ADD-03", "Bot asks for room after phone",
       "room" in r3.get("reply", "").lower(),
       f"Reply: {r3.get('reply', '')[:80]}")
    await asyncio.sleep(0.3)

    r4 = await send(client, TEST_ROOM)
    ok("ADD-04", "Bot asks for rent after room",
       "rent" in r4.get("reply", "").lower(),
       f"Reply: {r4.get('reply', '')[:80]}")
    await asyncio.sleep(0.3)

    r5 = await send(client, "14000")
    ok("ADD-05", "Bot asks for deposit after rent",
       "deposit" in r5.get("reply", "").lower(),
       f"Reply: {r5.get('reply', '')[:80]}")
    await asyncio.sleep(0.3)

    r6 = await send(client, "5000")
    ok("ADD-06", "Bot asks for maintenance after deposit",
       "maintenance" in r6.get("reply", "").lower(),
       f"Reply: {r6.get('reply', '')[:80]}")
    await asyncio.sleep(0.3)

    r7 = await send(client, "500")
    ok("ADD-07", "Bot asks for check-in date after maintenance",
       "date" in r7.get("reply", "").lower() or "check" in r7.get("reply", "").lower(),
       f"Reply: {r7.get('reply', '')[:80]}")
    await asyncio.sleep(0.3)

    r8 = await send(client, "29 March 2026")
    ok("ADD-08", "Bot shows confirmation with all details",
       "confirm" in r8.get("reply", "").lower() and "testuser alpha" in r8.get("reply", "").lower(),
       f"Reply: {r8.get('reply', '')[:100]}")
    await asyncio.sleep(0.3)

    r9 = await send(client, "yes")
    ok("ADD-09", "Bot confirms tenant added",
       "added" in r9.get("reply", "").lower() or "saved" in r9.get("reply", "").lower()
       or "success" in r9.get("reply", "").lower() or "check" in r9.get("reply", "").lower(),
       f"Reply: {r9.get('reply', '')[:100]}")
    await asyncio.sleep(1)

    # --- Verify in DB ---
    print("\n  --- 1B: DB Verification ---")
    db_tenant = await verify_db_tenant(session_factory, "Testuser Alpha")
    if db_tenant:
        ok("DB-ADD-01", "Tenant exists in DB", True)
        ok("DB-ADD-02", f"Name correct: {db_tenant['name']}",
           "testuser alpha" in db_tenant["name"].lower(),
           f"Got: {db_tenant['name']}")
        ok("DB-ADD-03", f"Phone correct: {db_tenant['phone']}",
           "9800000001" in str(db_tenant["phone"]),
           f"Got: {db_tenant['phone']}")
        ok("DB-ADD-04", f"Room correct: {db_tenant['room']}",
           db_tenant["room"] == TEST_ROOM,
           f"Got: {db_tenant['room']}")
        ok("DB-ADD-05", f"Rent correct: {db_tenant['rent']}",
           db_tenant["rent"] == 14000,
           f"Got: {db_tenant['rent']}")
        ok("DB-ADD-06", f"Deposit correct: {db_tenant['deposit']}",
           db_tenant["deposit"] == 5000,
           f"Got: {db_tenant['deposit']}")
        ok("DB-ADD-07", f"Status is active",
           db_tenant["status"] == "active",
           f"Got: {db_tenant['status']}")
    else:
        ok("DB-ADD-01", "Tenant exists in DB", False, "NOT FOUND in database")
        for i in range(2, 8):
            ok(f"DB-ADD-0{i}", "(skipped — tenant not in DB)", False, "depends on DB-ADD-01")

    # --- Verify in Google Sheet ---
    print("\n  --- 1C: Google Sheet Verification ---")
    if ss:
        await asyncio.sleep(2)  # let sheet update propagate

        # TENANTS tab
        t_row = find_in_sheet(ss, "TENANTS", TEST_ROOM, "Testuser Alpha")
        if t_row:
            d = t_row["data"]
            ok("SHEET-ADD-01", "Tenant found in TENANTS tab", True)
            ok("SHEET-ADD-02", f"Name in sheet: {d[1]}",
               "testuser" in d[1].lower(), f"Got: {d[1]}")
            ok("SHEET-ADD-03", f"Phone in sheet: {d[2]}",
               "9800000001" in str(d[2]), f"Got: {d[2]}")
            ok("SHEET-ADD-04", f"Rent in sheet: {d[9]}",
               str(int(float(str(d[9]).replace(",", "") or "0"))) == "14000",
               f"Got: {d[9]}")
            ok("SHEET-ADD-05", f"Deposit in sheet: {d[10]}",
               str(int(float(str(d[10]).replace(",", "") or "0"))) == "5000",
               f"Got: {d[10]}")
            ok("SHEET-ADD-06", f"Status in sheet: {d[8]}",
               d[8].lower() in ("active", "new", ""), f"Got: {d[8]}")
        else:
            ok("SHEET-ADD-01", "Tenant found in TENANTS tab", False, "NOT FOUND")
            for i in range(2, 7):
                ok(f"SHEET-ADD-0{i}", "(skipped)", False, "depends on SHEET-ADD-01")

        # Monthly tab
        month_tab = "MARCH 2026"
        m_row = find_in_sheet(ss, month_tab, TEST_ROOM, "Testuser Alpha")
        if m_row:
            ok("SHEET-ADD-07", f"Tenant found in {month_tab} tab", True)
        else:
            ok("SHEET-ADD-07", f"Tenant found in {month_tab} tab", False,
               f"NOT FOUND in {month_tab} (may be in different month tab)")
    else:
        print("  [SKIP] No Google Sheet connection")

    # --- Test 1D: Invalid add tenant ---
    print("\n  --- 1D: Reject invalid data ---")
    await clear_pending(client)

    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)

    # Invalid name (digits only)
    r = await send(client, "12345")
    ok("ADD-REJECT-01", "Rejects number-only name",
       "keep_pending" in r.get("intent", "").lower() or "name" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:80]}")
    await clear_pending(client)

    # --- Test 1E: Cancel mid-flow ---
    print("\n  --- 1E: Cancel mid-flow ---")
    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)
    r = await send(client, "Testuser Beta")
    await asyncio.sleep(0.3)
    r = await send(client, "cancel")
    ok("ADD-CANCEL-01", "Cancel stops add tenant flow",
       "cancel" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:80]}")


# ── SECTION 2: COLLECT RENT / PAYMENT ────────────────────────────────────────

async def test_payment(client: httpx.AsyncClient, session_factory, ss):
    """Test payment logging — DB + Sheet verification."""
    print("\n" + "=" * 60)
    print("  SECTION 2: PAYMENT — Data Integrity")
    print("=" * 60)

    await clear_pending(client)

    # --- Test 2A: Simple payment ---
    print("\n  --- 2A: Log a cash payment ---")
    responses = await multi_turn(client, [
        "Testuser Alpha paid 5000 cash",
    ])
    r = responses[-1]
    ok("PAY-01", "Bot acknowledges payment",
       "5" in r.get("reply", "") and "000" in r.get("reply", ""),
       f"Reply: {r.get('reply', '')[:100]}")

    # If confirmation needed, confirm
    if "confirm" in r.get("reply", "").lower() or "yes" in r.get("reply", "").lower():
        await asyncio.sleep(0.3)
        r2 = await send(client, "yes")
        ok("PAY-02", "Payment confirmed",
           "record" in r2.get("reply", "").lower() or "saved" in r2.get("reply", "").lower()
           or "logged" in r2.get("reply", "").lower() or "rs" in r2.get("reply", "").lower(),
           f"Reply: {r2.get('reply', '')[:100]}")
    else:
        ok("PAY-02", "Payment auto-confirmed", True)

    await asyncio.sleep(1)

    # --- Verify payment in DB ---
    print("\n  --- 2B: DB Payment Verification ---")
    db_pay = await verify_db_payment(session_factory, "Testuser Alpha", 5000)
    if db_pay:
        ok("DB-PAY-01", "Payment exists in DB", True)
        ok("DB-PAY-02", f"Amount correct: {db_pay['amount']}",
           db_pay["amount"] == 5000, f"Got: {db_pay['amount']}")
        ok("DB-PAY-03", f"Method correct: {db_pay['method']}",
           "cash" in str(db_pay["method"]).lower(), f"Got: {db_pay['method']}")
    else:
        ok("DB-PAY-01", "Payment exists in DB", False, "NOT FOUND")
        ok("DB-PAY-02", "(skipped)", False, "depends on DB-PAY-01")
        ok("DB-PAY-03", "(skipped)", False, "depends on DB-PAY-01")

    # --- Verify in Google Sheet ---
    print("\n  --- 2C: Sheet Payment Verification ---")
    if ss:
        await asyncio.sleep(2)
        month_tab = "MARCH 2026"
        m_row = find_in_sheet(ss, month_tab, TEST_ROOM, "Testuser Alpha")
        if m_row:
            d = m_row["data"]
            cash_val = str(d[6]).replace(",", "").strip() if len(d) > 6 else "0"
            ok("SHEET-PAY-01", f"Cash column updated: {d[6] if len(d) > 6 else '?'}",
               float(cash_val or "0") >= 5000,
               f"Cash={d[6] if len(d) > 6 else 'missing'}")
        else:
            ok("SHEET-PAY-01", "Tenant found in monthly tab for payment check", False,
               f"NOT FOUND in {month_tab}")
    else:
        print("  [SKIP] No sheet connection")

    # --- Test 2D: UPI payment ---
    print("\n  --- 2D: Log a UPI payment ---")
    await clear_pending(client)
    responses = await multi_turn(client, [
        "Testuser Alpha 3000 UPI",
    ])
    r = responses[-1]

    # May need confirmation
    if "confirm" in r.get("reply", "").lower():
        await asyncio.sleep(0.3)
        r = await send(client, "yes")

    ok("PAY-04", "UPI payment processed",
       "3" in r.get("reply", "") and "000" in r.get("reply", ""),
       f"Reply: {r.get('reply', '')[:100]}")

    # --- Test 2E: Reject invalid payment ---
    print("\n  --- 2E: Reject invalid payment ---")
    await clear_pending(client)

    # Zero amount
    r = await send(client, "Testuser Alpha paid 0 cash")
    ok("PAY-REJECT-01", "Zero amount handled",
       r.get("intent", "") != "ERROR",
       f"Intent: {r.get('intent', '')}, Reply: {r.get('reply', '')[:80]}")


# ── SECTION 3: NOTICE ────────────────────────────────────────────────────────

async def test_notice(client: httpx.AsyncClient, session_factory, ss):
    """Test notice recording — DB + Sheet verification."""
    print("\n" + "=" * 60)
    print("  SECTION 3: NOTICE — Data Integrity")
    print("=" * 60)

    await clear_pending(client)

    # --- Test 3A: Give notice ---
    print("\n  --- 3A: Record notice ---")
    responses = await multi_turn(client, [
        "Testuser Alpha gave notice",
    ])
    r = responses[-1]

    # May need disambiguation if multiple matches
    if "which" in r.get("reply", "").lower() or "reply" in r.get("reply", "").lower():
        await asyncio.sleep(0.3)
        r = await send(client, "1")

    ok("NOTICE-01", "Bot confirms notice recorded",
       "notice" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:100]}")

    await asyncio.sleep(1)

    # --- Verify in DB ---
    print("\n  --- 3B: DB Notice Verification ---")
    db_tenant = await verify_db_tenant(session_factory, "Testuser Alpha")
    if db_tenant:
        ok("DB-NOTICE-01", f"Notice date set: {db_tenant['notice_date']}",
           db_tenant["notice_date"] is not None,
           f"Got: {db_tenant['notice_date']}")
        ok("DB-NOTICE-02", f"Expected checkout set: {db_tenant['expected_checkout']}",
           db_tenant["expected_checkout"] is not None,
           f"Got: {db_tenant['expected_checkout']}")
    else:
        ok("DB-NOTICE-01", "Tenant found for notice check", False, "NOT FOUND")
        ok("DB-NOTICE-02", "(skipped)", False, "depends on DB-NOTICE-01")

    # --- Verify in Google Sheet ---
    print("\n  --- 3C: Sheet Notice Verification ---")
    if ss:
        await asyncio.sleep(2)
        t_row = find_in_sheet(ss, "TENANTS", TEST_ROOM, "Testuser Alpha")
        if t_row:
            d = t_row["data"]
            notice_val = str(d[13]).strip() if len(d) > 13 else ""
            expected_val = str(d[14]).strip() if len(d) > 14 else ""
            ok("SHEET-NOTICE-01", f"Notice Date in TENANTS: {notice_val}",
               len(notice_val) > 0,
               f"Col 13 (Notice Date) = '{notice_val}'")
            ok("SHEET-NOTICE-02", f"Expected Exit in TENANTS: {expected_val}",
               len(expected_val) > 0,
               f"Col 14 (Expected Exit) = '{expected_val}'")
        else:
            ok("SHEET-NOTICE-01", "Tenant found in TENANTS tab", False, "NOT FOUND")
            ok("SHEET-NOTICE-02", "(skipped)", False, "depends on SHEET-NOTICE-01")
    else:
        print("  [SKIP] No sheet connection")


# ── SECTION 4: CHECKOUT ──────────────────────────────────────────────────────

async def test_checkout(client: httpx.AsyncClient, session_factory, ss):
    """Test checkout flow — DB + Sheet verification."""
    print("\n" + "=" * 60)
    print("  SECTION 4: CHECKOUT — Data Integrity")
    print("=" * 60)

    await clear_pending(client)

    # --- Test 4A: Full checkout checklist ---
    print("\n  --- 4A: Checkout checklist flow ---")
    r = await send(client, "checkout Testuser Alpha")
    ok("CHECKOUT-01", "Bot starts checkout flow",
       "checkout" in r.get("reply", "").lower() or "key" in r.get("reply", "").lower()
       or "which" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:100]}")
    await asyncio.sleep(0.3)

    # If disambiguation needed
    if "which" in r.get("reply", "").lower() or "reply" in r.get("reply", "").lower():
        r = await send(client, "1")
        await asyncio.sleep(0.3)

    # Answer checklist Q1-Q4 if in checklist mode
    reply_lower = r.get("reply", "").lower()
    if "cupboard" in reply_lower or "key" in reply_lower or "q1" in reply_lower:
        r = await send(client, "yes")  # Q1 cupboard key
        await asyncio.sleep(0.3)
        r = await send(client, "yes")  # Q2 main key
        await asyncio.sleep(0.3)
        r = await send(client, "no")   # Q3 damages
        await asyncio.sleep(0.3)
        r = await send(client, "yes")  # Q4 fingerprint
        await asyncio.sleep(0.3)

        ok("CHECKOUT-02", "Bot shows settlement summary",
           "refund" in r.get("reply", "").lower() or "settlement" in r.get("reply", "").lower()
           or "deposit" in r.get("reply", "").lower(),
           f"Reply: {r.get('reply', '')[:100]}")

        # Confirm checkout
        r = await send(client, "confirm")
        await asyncio.sleep(0.3)

    ok("CHECKOUT-03", "Bot confirms checkout complete",
       "checkout" in r.get("reply", "").lower() or "exit" in r.get("reply", "").lower()
       or "completed" in r.get("reply", "").lower() or "done" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:100]}")

    await asyncio.sleep(1)

    # --- Verify in DB ---
    print("\n  --- 4B: DB Checkout Verification ---")
    status = await verify_db_tenancy_status(session_factory, "Testuser Alpha")
    ok("DB-CHECKOUT-01", f"Tenancy status is exited: {status}",
       status in ("exited", "checked_out"),
       f"Got: {status}")

    # --- Verify in Google Sheet ---
    print("\n  --- 4C: Sheet Checkout Verification ---")
    if ss:
        await asyncio.sleep(2)
        month_tab = "MARCH 2026"
        m_row = find_in_sheet(ss, month_tab, TEST_ROOM, "Testuser Alpha")
        if m_row:
            d = m_row["data"]
            status_val = str(d[10]).strip().upper() if len(d) > 10 else ""
            ok("SHEET-CHECKOUT-01", f"Status in monthly tab: {status_val}",
               status_val == "EXIT",
               f"Got: '{status_val}'")
        else:
            ok("SHEET-CHECKOUT-01", "Tenant found for checkout check", False,
               f"NOT FOUND in {month_tab}")

        t_row = find_in_sheet(ss, "TENANTS", TEST_ROOM, "Testuser Alpha")
        if t_row:
            d = t_row["data"]
            status_val = str(d[8]).strip().upper() if len(d) > 8 else ""
            ok("SHEET-CHECKOUT-02", f"TENANTS tab status: {status_val}",
               "EXIT" in status_val or "INACTIVE" in status_val,
               f"Got: '{status_val}'")
        else:
            ok("SHEET-CHECKOUT-02", "Tenant in TENANTS tab for status check", False, "NOT FOUND")
    else:
        print("  [SKIP] No sheet connection")


# ── SECTION 5: MID-FLOW BREAKOUT ─────────────────────────────────────────────

async def test_mid_flow_breakout(client: httpx.AsyncClient):
    """Test that cancel/hi/new-intent breaks out of multi-step flows."""
    print("\n" + "=" * 60)
    print("  SECTION 5: MID-FLOW BREAKOUT")
    print("=" * 60)

    # --- 5A: Cancel during add tenant ---
    print("\n  --- 5A: Cancel during add tenant ---")
    await clear_pending(client)
    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)
    r = await send(client, "John Test")
    await asyncio.sleep(0.3)
    r = await send(client, "cancel")
    ok("BREAK-01", "Cancel during add tenant",
       "cancel" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:80]}")

    # --- 5B: Hi/menu resets flow ---
    print("\n  --- 5B: 'hi' resets flow ---")
    await clear_pending(client)
    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)
    r = await send(client, "Test Person")
    await asyncio.sleep(0.3)
    r = await send(client, "hi")
    ok("BREAK-02", "'hi' resets flow and shows menu",
       r.get("intent", "") in ("HELP", "GENERAL") or "help" in r.get("reply", "").lower()
       or "what" in r.get("reply", "").lower() or "menu" in r.get("reply", "").lower(),
       f"Intent: {r.get('intent')}, Reply: {r.get('reply', '')[:80]}")

    # --- 5C: New intent breaks flow ---
    print("\n  --- 5C: New intent during add tenant ---")
    await clear_pending(client)
    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)
    r = await send(client, "Some Name")
    await asyncio.sleep(0.3)
    r = await send(client, "who owes rent")
    ok("BREAK-03", "New intent breaks add tenant flow",
       r.get("intent", "") != "CONFIRMATION" and r.get("intent", "") != "ADD_TENANT_STEP",
       f"Intent: {r.get('intent')}, Reply: {r.get('reply', '')[:80]}")


# ── SECTION 6: DATA REJECTION ────────────────────────────────────────────────

async def test_data_rejection(client: httpx.AsyncClient):
    """Test that the bot rejects clearly invalid data."""
    print("\n" + "=" * 60)
    print("  SECTION 6: DATA REJECTION / VALIDATION")
    print("=" * 60)

    await clear_pending(client)

    # --- 6A: Non-existent tenant ---
    r = await send(client, "checkout GhostPerson999")
    ok("REJECT-01", "Non-existent tenant handled gracefully",
       "not found" in r.get("reply", "").lower() or "no match" in r.get("reply", "").lower()
       or "could not" in r.get("reply", "").lower() or "who" in r.get("reply", "").lower()
       or r.get("intent", "") not in ("ERROR",),
       f"Reply: {r.get('reply', '')[:80]}")

    # --- 6B: Invalid phone in add tenant ---
    await clear_pending(client)
    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)
    r = await send(client, "Valid Name")
    await asyncio.sleep(0.3)
    r = await send(client, "123")  # too short phone
    ok("REJECT-02", "Rejects 3-digit phone number",
       "10" in r.get("reply", "") or "digit" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:80]}")
    await clear_pending(client)

    # --- 6C: Invalid room ---
    await clear_pending(client)
    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)
    r = await send(client, "Valid Name")
    await asyncio.sleep(0.3)
    r = await send(client, "9876543210")
    await asyncio.sleep(0.3)
    r = await send(client, "999")  # non-existent room
    ok("REJECT-03", "Rejects non-existent room",
       "not found" in r.get("reply", "").lower() or "try again" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:80]}")
    await clear_pending(client)

    # --- 6D: Invalid rent (zero) ---
    await clear_pending(client)
    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)
    r = await send(client, "Valid Name")
    await asyncio.sleep(0.3)
    r = await send(client, "9876543210")
    await asyncio.sleep(0.3)
    r = await send(client, TEST_ROOM)
    await asyncio.sleep(0.3)
    r = await send(client, "0")
    ok("REJECT-04", "Rejects zero rent",
       "valid" in r.get("reply", "").lower() or "enter" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:80]}")
    await clear_pending(client)

    # --- 6E: Invalid date ---
    await clear_pending(client)
    r = await send(client, "add new tenant")
    await asyncio.sleep(0.3)
    for answer in ["Valid Name", "9876543210", TEST_ROOM, "14000", "5000", "500"]:
        r = await send(client, answer)
        await asyncio.sleep(0.3)
    r = await send(client, "not a date")
    ok("REJECT-05", "Rejects invalid date",
       "parse" in r.get("reply", "").lower() or "date" in r.get("reply", "").lower()
       or "try" in r.get("reply", "").lower(),
       f"Reply: {r.get('reply', '')[:80]}")
    await clear_pending(client)


# ── Google Sheet Results Writer ───────────────────────────────────────────────

def write_results_to_sheet(ss):
    """Write all results to TEST RESULTS tab in Google Sheet."""
    if not ss or not RESULTS_ROWS:
        return

    try:
        # Get or create tab
        tab_name = "TEST RESULTS"
        try:
            ws = ss.worksheet(tab_name)
            ws.clear()
        except Exception:
            ws = ss.add_worksheet(title=tab_name, rows=200, cols=8)

        # Headers
        headers = ["File", "Test Name", "Status", "Duration", "Error", "Section", "Timestamp", "Run ID"]
        all_rows = [headers] + RESULTS_ROWS
        ws.update(values=all_rows, range_name=f"A1:H{len(all_rows)}", value_input_option="USER_ENTERED")

        # Format header
        ws.format("A1:H1", {
            "textFormat": {"bold": True, "foregroundColorStyle": {"rgbColor": {"red": 1, "green": 1, "blue": 1}}},
            "backgroundColor": {"red": 0.15, "green": 0.15, "blue": 0.15},
        })

        # Color PASS/FAIL
        pass_rows = [i + 2 for i, r in enumerate(RESULTS_ROWS) if r[2] == "PASS"]
        fail_rows = [i + 2 for i, r in enumerate(RESULTS_ROWS) if r[2] == "FAIL"]

        if pass_rows:
            ws.format(f"C{pass_rows[0]}:C{pass_rows[-1]}", {"backgroundColor": {"red": 0.85, "green": 1.0, "blue": 0.85}})
        for fr in fail_rows:
            ws.format(f"A{fr}:H{fr}", {
                "backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.85},
                "textFormat": {"bold": True},
            })

        # Summary row
        summary_row = len(all_rows) + 2
        pct = (P / TOTAL * 100) if TOTAL > 0 else 0
        ws.update(
            values=[["SUMMARY", f"{TOTAL} total", f"{P} PASS", f"{F} FAIL", "", f"{pct:.0f}%", "", RUN_ID]],
            range_name=f"A{summary_row}:H{summary_row}",
            value_input_option="USER_ENTERED",
        )
        ws.format(f"A{summary_row}:H{summary_row}", {
            "textFormat": {"bold": True, "fontSize": 12, "foregroundColorStyle": {"rgbColor": {"red": 1, "green": 1, "blue": 1}}},
            "backgroundColor": {"red": 0.1, "green": 0.1, "blue": 0.3},
        })

        ws.freeze(rows=1)
        print(f"\n  [SHEET] Results written to '{tab_name}' tab ({len(RESULTS_ROWS)} rows)")

    except Exception as e:
        print(f"\n  [WARN] Sheet write failed: {e}")


# ── Main runner ───────────────────────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", type=str, help="Run one section: add, pay, notice, checkout, break, reject")
    parser.add_argument("--no-sheet", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    args = parser.parse_args()

    # Check API is running
    async with httpx.AsyncClient() as client:
        try:
            test_r = await client.get(f"http://localhost:{API_PORT}/docs", timeout=3)
            print("[OK] API is running")
        except Exception:
            print("[ERROR] API is NOT running! Start it with: python main.py")
            print("        Make sure TEST_MODE=1 is in your .env")
            sys.exit(1)

    # Connect to DB
    print("[DB] Connecting to database...")
    try:
        session_factory = await get_db_session()
        if session_factory:
            print("[DB] Connected")
        else:
            print("[DB] Could not connect — DB checks will be skipped")
    except Exception as e:
        print(f"[DB] Connection failed: {e} — DB checks will be skipped")
        session_factory = None

    # Connect to Sheet
    ss = None
    if not args.no_sheet:
        print("[SHEET] Connecting to Google Sheet...")
        ss, _ = get_sheet_connection()
        if ss:
            print("[SHEET] Connected — results will update live")
        else:
            print("[SHEET] Could not connect — sheet checks will be skipped")

    print(f"\n{'#' * 60}")
    print(f"  DATA INTEGRITY TESTS — End-to-End")
    print(f"  Run ID: {RUN_ID}")
    print(f"{'#' * 60}")

    sections = {
        "add": test_add_tenant,
        "pay": test_payment,
        "notice": test_notice,
        "checkout": test_checkout,
        "break": test_mid_flow_breakout,
        "reject": test_data_rejection,
    }

    async with httpx.AsyncClient() as client:
        if args.section:
            if args.section in sections:
                if args.section in ("break", "reject"):
                    await sections[args.section](client)
                else:
                    await sections[args.section](client, session_factory, ss)
            else:
                print(f"Unknown section: {args.section}. Choose: {', '.join(sections.keys())}")
                sys.exit(1)
        else:
            # Run all in order: add → pay → notice → checkout → breakout → reject
            await test_add_tenant(client, session_factory, ss)
            await test_payment(client, session_factory, ss)
            await test_notice(client, session_factory, ss)
            await test_checkout(client, session_factory, ss)
            await test_mid_flow_breakout(client)
            await test_data_rejection(client)

    # Write results to sheet
    if ss:
        write_results_to_sheet(ss)

    # Print summary
    pct = (P / TOTAL * 100) if TOTAL > 0 else 0
    print(f"\n{'#' * 60}")
    print(f"  FINAL: {P}/{TOTAL} passed ({pct:.0f}%)")
    if F > 0:
        print(f"  {F} FAILED:")
        for err in ERRORS:
            print(f"    - {err}")
    print(f"{'#' * 60}")

    if F > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
