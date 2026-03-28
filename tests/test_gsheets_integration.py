"""
End-to-end Google Sheets integration tests.
Tests gsheets.py functions against the LIVE Google Sheet.

Run: python tests/test_gsheets_integration.py

Simulates receptionist workflows:
  - Collecting rent (cash/upi/partial/full/overpayment)
  - Adding new tenants
  - Recording checkout/notice
  - Edge cases (wrong room, duplicate, zero amount, etc.)
"""
import sys, os, asyncio, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from src.integrations.gsheets import (
    update_payment, add_tenant, record_checkout, record_notice,
)

PASS = 0
FAIL = 0
ERRORS = []

def result(test_id, name, res, expect_success=True):
    global PASS, FAIL
    ok = res.get("success", False) == expect_success
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAIL += 1
        ERRORS.append(f"{test_id}: {name} — expected success={expect_success}, got {res}")
    else:
        PASS += 1
    err = res.get("error", "")
    print(f"  [{status}] {test_id}: {name}" + (f" — {err}" if err else ""))
    return ok


async def run_tests():
    print("=" * 70)
    print("GOOGLE SHEETS INTEGRATION TESTS")
    print("=" * 70)

    # ─── SECTION 1: PAYMENT RECORDING ────────────────────────────────────
    print("\n--- 1. PAYMENT RECORDING ---")

    # T001: Record cash payment for existing tenant
    r = await update_payment("101", "Krishnan", 10000, "cash")
    result("T001", "Cash payment for Room 101 Krishnan (10000)", r)

    # T002: Record UPI payment for existing tenant
    r = await update_payment("102", "Prashant", 15000, "upi")
    result("T002", "UPI payment for Room 102 Prashant (15000)", r)

    # T003: Partial payment (less than rent)
    r = await update_payment("103", "Gunturu Sai Sri Anvitha", 5000, "cash")
    result("T003", "Partial cash payment Room 103 (5000 of 17000)", r)

    # T004: Second payment for same tenant (additive)
    r = await update_payment("103", "Gunturu Sai Sri Anvitha", 5000, "upi")
    result("T004", "Second payment UPI Room 103 (should add to existing)", r)

    # T005: Full payment exactly matching rent
    r = await update_payment("109", "Manoj", 13000, "upi")
    result("T005", "Full UPI payment Room 109 Manoj (exact rent match)", r)

    # T006: Overpayment
    r = await update_payment("104", "Bala Subramanyam", 20000, "upi")
    result("T006", "Overpayment Room 104 (20000 > rent 15500)", r)
    if r.get("overpayment"):
        print(f"         Overpayment detected: {r.get('overpayment')}")

    # T007: Wrong room number (should fail gracefully)
    r = await update_payment("999", "Nobody", 5000, "cash")
    result("T007", "Wrong room 999 (should fail)", r, expect_success=False)

    # T008: Wrong tenant name for correct room
    r = await update_payment("101", "Wrong Name", 5000, "cash")
    result("T008", "Wrong name for Room 101 (should fail)", r, expect_success=False)

    # T009: Zero amount payment
    r = await update_payment("105", "Anuron Dutta", 0, "cash")
    result("T009", "Zero amount payment (should fail)", r, expect_success=False)

    # T010: Very large payment
    r = await update_payment("106", "Suraj Prasana", 100000, "upi")
    result("T010", "Very large payment 1 lakh (should succeed with warning)", r)

    # T011: Cash payment for premium room tenant
    r = await update_payment("119", "Karesse", 25000, "cash")
    result("T011", "Cash for premium room 119 Karesse (25000)", r)

    # T012: Payment with fuzzy name match
    r = await update_payment("110", "Ankita", 14000, "upi")
    result("T012", "Fuzzy name match 'Ankita' for Room 110", r)

    # T013: Payment for tenant with prev due
    r = await update_payment("121", "Ashish Das", 13000, "cash")
    result("T013", "Payment for tenant with prev due (Ashish Das, 5500 prev)", r)

    time.sleep(2)

    # ─── SECTION 2: ADD NEW TENANT ───────────────────────────────────────
    print("\n--- 2. ADD NEW TENANT ---")

    # T020: Add completely new tenant
    r = await add_tenant(
        room_number="501", name="Test Tenant Alpha", phone="9876543210",
        gender="Male", building="THOR", floor="5", sharing="Double",
        checkin="28/03/2026", agreed_rent=14000, deposit=5000,
        booking=2000, maintenance=500,
    )
    result("T020", "Add new tenant Room 501 Test Tenant Alpha", r)

    # T021: Add tenant to HULK building
    r = await add_tenant(
        room_number="401", name="Test Tenant Beta", phone="9876543211",
        gender="Female", building="HULK", floor="4", sharing="Single",
        checkin="01/04/2026", agreed_rent=23500, deposit=5000,
        booking=2000, maintenance=500,
    )
    result("T021", "Add new tenant Room 401 Test Tenant Beta (HULK)", r)

    # T022: Add premium room tenant
    r = await add_tenant(
        room_number="301", name="Test Tenant Gamma", phone="9876543212",
        gender="Male", building="THOR", floor="3", sharing="premium",
        checkin="05/04/2026", agreed_rent=29000, deposit=10000,
        booking=5000, maintenance=1000,
    )
    result("T022", "Add premium tenant Room 301", r)

    # T023: Add tenant with mid-month checkin (pro-rata test)
    r = await add_tenant(
        room_number="502", name="Test Midmonth", phone="9876543213",
        gender="Male", building="HULK", floor="5", sharing="Double",
        checkin="15/04/2026", agreed_rent=15000, deposit=5000,
        booking=0, maintenance=500,
    )
    result("T023", "Add mid-month tenant (checkin 15th, pro-rata rent)", r)

    # T024: Add tenant with missing required fields
    r = await add_tenant(
        room_number="", name="", phone="",
        gender="", building="", floor="", sharing="",
        checkin="", agreed_rent=0, deposit=0,
        booking=0, maintenance=0,
    )
    result("T024", "Add tenant with empty fields (should fail)", r, expect_success=False)

    time.sleep(2)

    # ─── SECTION 3: RECORD NOTICE ────────────────────────────────────────
    print("\n--- 3. RECORD NOTICE ---")

    # T030: Record notice for existing tenant
    r = await record_notice("109", "Manideep", "28/03/2026")
    result("T030", "Record notice for Room 109 Manideep", r)

    # T031: Record notice for wrong room
    r = await record_notice("999", "Nobody", "28/03/2026")
    result("T031", "Notice for wrong room (should fail)", r, expect_success=False)

    time.sleep(2)

    # ─── SECTION 4: RECORD CHECKOUT ──────────────────────────────────────
    print("\n--- 4. RECORD CHECKOUT ---")

    # T040: Checkout with notice date
    r = await record_checkout("501", "Test Tenant Alpha", "28/03/2026")
    result("T040", "Checkout Room 501 Test Tenant Alpha (with notice)", r)

    # T041: Checkout without notice
    r = await record_checkout("401", "Test Tenant Beta")
    result("T041", "Checkout Room 401 Test Tenant Beta (no notice)", r)

    # T042: Checkout for non-existent tenant
    r = await record_checkout("999", "Nobody")
    result("T042", "Checkout non-existent (should fail)", r, expect_success=False)

    time.sleep(2)

    # ─── SECTION 5: EDGE CASES ───────────────────────────────────────────
    print("\n--- 5. EDGE CASES ---")

    # T050: Payment after checkout (tenant is EXIT)
    r = await update_payment("501", "Test Tenant Alpha", 5000, "cash")
    result("T050", "Payment after checkout (EXIT tenant, should still find row)", r)

    # T051: Multiple payments same tenant same session
    r = await update_payment("112", "Amal", 10000, "cash")
    result("T051a", "First payment Amal 10000 cash", r)
    r = await update_payment("112", "Amal", 13500, "upi")
    result("T051b", "Second payment Amal 13500 upi", r)

    # T052: Payment for tenant in HULK
    r = await update_payment("118", "Sanjay", 13500, "upi")
    result("T052", "HULK tenant Sanjay UPI payment", r)

    # T053: Negative amount (should fail)
    r = await update_payment("101", "Krishnan", -5000, "cash")
    result("T053", "Negative amount (should fail)", r, expect_success=False)

    # T054: Invalid payment method
    r = await update_payment("101", "Krishnan", 5000, "bitcoin")
    result("T054", "Invalid payment method 'bitcoin'", r, expect_success=False)

    # T055: Very long tenant name
    r = await add_tenant(
        room_number="503", name="A" * 200, phone="9876543214",
        gender="Male", building="THOR", floor="5", sharing="Double",
        checkin="01/04/2026", agreed_rent=15000, deposit=5000,
        booking=0, maintenance=0,
    )
    result("T055", "Very long tenant name (200 chars)", r)

    # T056: Special characters in name
    r = await add_tenant(
        room_number="504", name="Test O'Brien-Kumar", phone="9876543215",
        gender="Male", building="HULK", floor="5", sharing="Double",
        checkin="01/04/2026", agreed_rent=13000, deposit=5000,
        booking=0, maintenance=0,
    )
    result("T056", "Special chars in name (O'Brien-Kumar)", r)

    # T057: Duplicate room + name add (second add should still work - append)
    r = await add_tenant(
        room_number="504", name="Test O'Brien-Kumar", phone="9876543215",
        gender="Male", building="HULK", floor="5", sharing="Double",
        checkin="01/04/2026", agreed_rent=13000, deposit=5000,
        booking=0, maintenance=0,
    )
    result("T057", "Duplicate add (same room+name, should append)", r)

    time.sleep(2)

    # ─── SECTION 6: CLEANUP TEST DATA ────────────────────────────────────
    print("\n--- 6. CLEANUP ---")
    print("  NOTE: Test tenants (501-504) left in sheet for manual inspection.")
    print("  Delete rows manually after review.")

    # ─── SUMMARY ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"RESULTS: {PASS} PASS / {FAIL} FAIL / {PASS + FAIL} TOTAL")
    print("=" * 70)

    if ERRORS:
        print("\nFAILED TESTS:")
        for e in ERRORS:
            print(f"  {e}")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
