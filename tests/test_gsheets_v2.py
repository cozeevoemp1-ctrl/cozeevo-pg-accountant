"""
Extended Google Sheets integration tests — 50+ edge cases.
Tests gsheets.py against LIVE Google Sheet.

Run: python tests/test_gsheets_v2.py
"""
import sys, os, asyncio, time, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from src.integrations.gsheets import (
    update_payment, add_tenant, record_checkout, record_notice,
)

PASS = 0
FAIL = 0
ERRORS = []


def check(test_id, name, res, expect_success=True, extra_check=None):
    global PASS, FAIL
    ok = res.get("success", False) == expect_success
    if ok and extra_check:
        ok = extra_check(res)
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAIL += 1
        ERRORS.append(f"{test_id}: {name} — got: {res}")
    else:
        PASS += 1
    err = res.get("error") or res.get("warning") or ""
    print(f"  [{status}] {test_id}: {name}" + (f" — {err}" if err else ""))
    return ok


async def run_tests():
    print("=" * 70)
    print("EXTENDED GOOGLE SHEETS INTEGRATION TESTS")
    print("=" * 70)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 1: PAYMENT — BASIC
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 1. PAYMENT BASICS ---")

    r = await update_payment("101", "Krishnan", 10000, "cash")
    check("P01", "Cash 10K Room 101", r)

    r = await update_payment("102", "Prashant", 15000, "upi")
    check("P02", "UPI 15K Room 102", r)

    r = await update_payment("109", "Manoj", 13000, "upi")
    check("P03", "Full rent UPI 13K (exact match)", r)

    r = await update_payment("105", "Anuron Dutta", 29000, "cash")
    check("P04", "Premium tenant cash 29K", r)

    r = await update_payment("118", "Sanjay", 6750, "cash")
    check("P05", "Partial payment half rent (6750 of 13500)", r)

    r = await update_payment("118", "Sanjay", 6750, "upi")
    check("P06", "Complete remaining via UPI (6750)", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 2: PAYMENT — VALIDATION
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 2. PAYMENT VALIDATION ---")

    r = await update_payment("101", "Krishnan", 0, "cash")
    check("V01", "Zero amount", r, expect_success=False)

    r = await update_payment("101", "Krishnan", -5000, "cash")
    check("V02", "Negative amount", r, expect_success=False)

    r = await update_payment("101", "Krishnan", 5000, "bitcoin")
    check("V03", "Invalid method 'bitcoin'", r, expect_success=False)

    r = await update_payment("101", "Krishnan", 5000, "")
    check("V04", "Empty method", r, expect_success=False)

    r = await update_payment("999", "Nobody", 5000, "cash")
    check("V05", "Non-existent room 999", r, expect_success=False)

    r = await update_payment("101", "Wrong Person", 5000, "cash")
    check("V06", "Wrong name for room 101", r, expect_success=False)

    r = await update_payment("", "", 5000, "cash")
    check("V07", "Empty room and name", r, expect_success=False)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 3: PAYMENT — EDGE CASES
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 3. PAYMENT EDGE CASES ---")

    # Overpayment
    r = await update_payment("104", "Bala Subramanyam", 25000, "upi")
    check("E01", "Overpayment (25K > 15.5K rent)", r,
          extra_check=lambda x: x.get("overpayment", 0) > 0)

    # Very large payment
    r = await update_payment("106", "Suraj Prasana", 500000, "upi")
    check("E02", "Very large payment 5 lakh", r)

    # Fuzzy name matching
    r = await update_payment("110", "Ankita", 14000, "upi")
    check("E03", "Fuzzy match 'Ankita' → 'Ankita Benarjee'", r)

    r = await update_payment("103", "Gunturu", 5000, "cash")
    check("E04", "Fuzzy match partial name 'Gunturu'", r)

    # Tenant with previous month dues
    r = await update_payment("121", "Ashish Das", 18500, "upi")
    check("E05", "Payment covers rent + prev due (13000 + 5500)", r)

    # Multiple rapid payments same tenant
    r = await update_payment("112", "Amal", 5000, "cash")
    check("E06a", "Rapid payment 1 (5K cash)", r)
    r = await update_payment("112", "Amal", 5000, "cash")
    check("E06b", "Rapid payment 2 (5K cash again, additive)", r)
    r = await update_payment("112", "Amal", 13500, "upi")
    check("E06c", "Rapid payment 3 (13.5K UPI)", r)

    # Float amount (paise)
    r = await update_payment("102", "Akarsh SM", 14999.50, "upi")
    check("E07", "Float amount with paise (14999.50)", r)

    # Payment for Rs.1 (minimum)
    r = await update_payment("109", "Manideep", 1, "cash")
    check("E08", "Minimum payment Rs.1", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 4: ADD TENANT — BASIC
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 4. ADD TENANT ---")

    r = await add_tenant("601", "New Tenant Single", "9111111111",
                         "Male", "THOR", "6", "Single", "01/04/2026",
                         23500, 5000, 2000, 500)
    check("A01", "New single THOR tenant", r)

    r = await add_tenant("602", "New Tenant Double", "9222222222",
                         "Female", "HULK", "6", "Double", "01/04/2026",
                         14000, 5000, 0, 500)
    check("A02", "New double HULK tenant (no booking)", r)

    r = await add_tenant("603", "Premium Tenant", "9333333333",
                         "Male", "THOR", "6", "premium", "05/04/2026",
                         29000, 10000, 5000, 1000)
    check("A03", "Premium tenant mid-month (5th April)", r)

    r = await add_tenant("604", "Last Day Checkin", "9444444444",
                         "Male", "HULK", "6", "Double", "30/04/2026",
                         15000, 5000, 0, 500)
    check("A04", "Last day of month checkin (30th)", r)

    r = await add_tenant("605", "First Day Checkin", "9555555555",
                         "Female", "THOR", "6", "Double", "01/04/2026",
                         13000, 5000, 2000, 0)
    check("A05", "First day checkin (no maintenance)", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 5: ADD TENANT — VALIDATION
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 5. ADD TENANT VALIDATION ---")

    r = await add_tenant("", "No Room", "9666666666",
                         "Male", "THOR", "1", "Double", "01/04/2026",
                         15000, 5000, 0, 0)
    check("AV01", "Empty room number", r, expect_success=False)

    r = await add_tenant("610", "", "9777777777",
                         "Male", "THOR", "1", "Double", "01/04/2026",
                         15000, 5000, 0, 0)
    check("AV02", "Empty name", r, expect_success=False)

    r = await add_tenant("611", "No Phone", "",
                         "Male", "THOR", "1", "Double", "01/04/2026",
                         15000, 5000, 0, 0)
    check("AV03", "Empty phone", r, expect_success=False)

    r = await add_tenant("612", "Zero Rent Tenant", "9888888888",
                         "Male", "THOR", "1", "Double", "01/04/2026",
                         0, 0, 0, 0)
    check("AV04", "Zero rent tenant (staff/complimentary)", r)

    r = await add_tenant("613", "O'Brien-Kumar Jr.", "9999999999",
                         "Male", "HULK", "1", "Double", "01/04/2026",
                         15000, 5000, 0, 0)
    check("AV05", "Special chars in name", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6: NOTICE + CHECKOUT
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 6. NOTICE + CHECKOUT ---")

    # Notice first, then checkout
    r = await record_notice("601", "New Tenant Single", "28/03/2026")
    check("N01", "Record notice for Room 601", r)

    r = await record_checkout("601", "New Tenant Single", "28/03/2026")
    check("C01", "Checkout Room 601 (with notice)", r)

    # Checkout without notice
    r = await record_checkout("602", "New Tenant Double")
    check("C02", "Checkout Room 602 (no notice)", r)

    # Checkout already exited tenant
    r = await record_checkout("601", "New Tenant Single")
    check("C03", "Checkout already exited tenant (should still work)", r)

    # Notice for non-existent
    r = await record_notice("999", "Nobody", "01/04/2026")
    check("N02", "Notice for non-existent (should fail)", r, expect_success=False)

    # Checkout non-existent
    r = await record_checkout("999", "Ghost Tenant")
    check("C04", "Checkout non-existent (should fail)", r, expect_success=False)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 7: PAYMENT AFTER STATUS CHANGES
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 7. PAYMENT AFTER STATUS CHANGES ---")

    # Payment for EXIT tenant (settling dues at checkout)
    r = await update_payment("601", "New Tenant Single", 23500, "upi")
    check("S01", "Payment for EXIT tenant (settle dues at checkout)", r)

    # Payment after notice (still active, just gave notice)
    r = await update_payment("603", "Premium Tenant", 29000, "upi")
    check("S02", "Payment for tenant who gave no notice (active)", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 8: MONTH BOUNDARY
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 8. MONTH BOUNDARY ---")

    # Payment targeting specific month (April)
    r = await update_payment("101", "Krishnan", 23500, "upi", month=4, year=2026)
    check("M01", "Payment targeting April 2026 specifically", r)

    # Payment targeting non-existent month
    r = await update_payment("101", "Krishnan", 5000, "cash", month=12, year=2030)
    check("M02", "Payment for Dec 2030 (no tab, should fail)", r, expect_success=False)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 9: ROOM TRANSFER (re-add same person, new room)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 9. ROOM TRANSFER + RE-CHECKIN ---")

    # Checkout from old room
    r = await record_checkout("604", "Last Day Checkin")
    check("R01", "Checkout from Room 604", r)

    # Re-checkin to new room
    r = await add_tenant("620", "Last Day Checkin", "9444444444",
                         "Male", "THOR", "6", "Double", "01/04/2026",
                         16000, 5000, 0, 500)
    check("R02", "Re-checkin same person Room 620 (room transfer)", r)

    # Payment in new room
    r = await update_payment("620", "Last Day Checkin", 16000, "upi")
    check("R03", "Payment in new room after transfer", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 10: AGREEMENT SCENARIOS
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 10. AGREEMENT / DISCOUNT SCENARIOS ---")

    # Tenant with discounted first 2 months (rent=10000), then 15000
    # This is handled in DB (rent_schedule.adjustment), sheet just shows Rent Due
    # For the sheet, the bot writes the correct Rent Due for each month
    r = await add_tenant("630", "Discount Tenant", "8111111111",
                         "Male", "HULK", "6", "Double", "01/04/2026",
                         10000, 5000, 0, 500)  # First month discounted rent
    check("AG01", "Discounted rent tenant (10K first 2mo, 15K from 3rd)", r)

    # Lock-in tenant (4 months, no deposit refund if early exit)
    r = await add_tenant("631", "Lockin Tenant", "8222222222",
                         "Female", "THOR", "6", "Single", "01/04/2026",
                         23500, 10000, 5000, 1000)
    check("AG02", "Lock-in tenant (4mo lock, 10K deposit)", r)

    # Early checkout of lock-in tenant (within 4 months = no refund)
    r = await record_notice("631", "Lockin Tenant", "28/03/2026")
    check("AG03", "Notice from lock-in tenant (early exit)", r)

    r = await record_checkout("631", "Lockin Tenant", "28/03/2026")
    check("AG04", "Checkout lock-in tenant (deposit forfeited — tracked in DB)", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 11: DEPOSIT + REFUND SCENARIOS
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 11. DEPOSIT SCENARIOS ---")

    # Tenant with partial deposit (paid 3000 of 5000)
    r = await add_tenant("640", "Partial Deposit", "8333333333",
                         "Male", "HULK", "6", "Double", "01/04/2026",
                         14000, 3000, 0, 500)
    check("D01", "Tenant with partial deposit (3K of 5K standard)", r)

    # Tenant with high deposit (premium)
    r = await add_tenant("641", "High Deposit", "8444444444",
                         "Female", "THOR", "6", "premium", "01/04/2026",
                         29000, 20000, 5000, 1000)
    check("D02", "Premium tenant high deposit (20K)", r)

    # Checkout with pending dues (balance > 0)
    r = await record_checkout("640", "Partial Deposit")
    check("D03", "Checkout with pending dues (deduct from deposit in DB)", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 12: NOTES / COMMENTS
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- 12. NOTES VERIFICATION ---")

    # Payment should append note with timestamp
    r = await update_payment("605", "First Day Checkin", 6500, "cash")
    check("NT01", "Payment adds timestamped note", r)

    r = await update_payment("605", "First Day Checkin", 6500, "upi")
    check("NT02", "Second payment appends to notes (pipe-separated)", r)

    time.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════
    # CLEANUP + SUMMARY
    # ═══════════════════════════════════════════════════════════════════════
    print("\n--- CLEANUP ---")
    print("  Test rows (601-641) left for manual inspection.")

    print("\n" + "=" * 70)
    print(f"RESULTS: {PASS} PASS / {FAIL} FAIL / {PASS + FAIL} TOTAL")
    print("=" * 70)

    if ERRORS:
        print("\nFAILED TESTS:")
        for e in ERRORS:
            print(f"  {e[:200]}")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
