"""
Live workflow tests — tests against real Google Sheet.
Simulates real receptionist interactions.

Run: python tests/test_live_workflows.py
"""
import sys, os, asyncio, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from src.integrations.gsheets import update_payment, add_tenant, record_checkout, record_notice

P, F, ERRORS = 0, 0, []

def ok(tid, name, res, expect=True, check=None):
    global P, F
    success = res.get("success", False) == expect
    if success and check:
        success = check(res)
    if success:
        P += 1
        print(f"  [OK] {tid}: {name}")
    else:
        F += 1
        err = res.get("error") or res.get("warning") or str(res)[:100]
        ERRORS.append(f"{tid}: {name} => {err}")
        print(f"  [FAIL] {tid}: {name} => {err}")
    return success

def pause(s=3):
    time.sleep(s)


async def main():
    print("=" * 70)
    print("LIVE WORKFLOW TESTS — Google Sheet")
    print("=" * 70)

    # ═════════════════════════════════════════════════════════════════════
    # WORKFLOW 1: ADD 5 NEW TENANTS (April checkin)
    # ═════════════════════════════════════════════════════════════════════
    print("\n=== WORKFLOW 1: ADD NEW TENANTS ===")

    tenants = [
        ("701", "Rahul Sharma", "9100000001", "Male", "THOR", "7", "Double", "01/04/2026", 14000, 5000, 0, 500),
        ("702", "Priya Patel", "9100000002", "Female", "THOR", "7", "Single", "01/04/2026", 23500, 10000, 2000, 1000),
        ("703", "Amit Singh", "9100000003", "Male", "HULK", "7", "Double", "05/04/2026", 13500, 5000, 0, 500),
        ("704", "Sneha Reddy", "9100000004", "Female", "HULK", "7", "premium", "01/04/2026", 29000, 15000, 5000, 1000),
        ("705", "Vikram Das", "9100000005", "Male", "THOR", "7", "Double", "15/04/2026", 15000, 5000, 0, 500),
    ]

    for rm, name, phone, gender, bld, fl, sh, ci, rent, dep, bk, mt in tenants:
        r = await add_tenant(rm, name, phone, gender, bld, fl, sh, ci, rent, dep, bk, mt)
        ok(f"ADD-{rm}", f"Add {name} Room {rm} ({bld}, {sh})", r)
        pause(2)

    # ═════════════════════════════════════════════════════════════════════
    # WORKFLOW 2: COLLECT RENT — various scenarios
    # ═════════════════════════════════════════════════════════════════════
    print("\n=== WORKFLOW 2: COLLECT RENT ===")
    pause(3)

    # Full payment cash
    r = await update_payment("701", "Rahul Sharma", 14000, "cash", month=4, year=2026)
    ok("PAY-01", "Rahul full rent 14K cash", r,
       check=lambda x: x.get("balance", 1) <= 0)
    pause(2)

    # Full payment UPI
    r = await update_payment("702", "Priya Patel", 23500, "upi", month=4, year=2026)
    ok("PAY-02", "Priya full rent 23.5K UPI", r)
    pause(2)

    # Partial payment
    r = await update_payment("703", "Amit Singh", 5000, "cash", month=4, year=2026)
    ok("PAY-03", "Amit partial 5K of 13.5K", r,
       check=lambda x: x.get("balance", 0) > 0)
    pause(2)

    # Second partial to complete
    r = await update_payment("703", "Amit Singh", 8500, "upi", month=4, year=2026)
    ok("PAY-04", "Amit completes with 8.5K UPI (total 13.5K)", r)
    pause(2)

    # Overpayment
    r = await update_payment("704", "Sneha Reddy", 35000, "upi", month=4, year=2026)
    ok("PAY-05", "Sneha overpays 35K (rent 29K)", r,
       check=lambda x: x.get("overpayment", 0) > 0)
    pause(2)

    # No payment for Vikram (stays UNPAID)

    # ═════════════════════════════════════════════════════════════════════
    # WORKFLOW 3: RECORD NOTICE
    # ═════════════════════════════════════════════════════════════════════
    print("\n=== WORKFLOW 3: RECORD NOTICE ===")
    pause(3)

    r = await record_notice("705", "Vikram Das", "28/03/2026")
    ok("NOTICE-01", "Vikram gives notice (28 March)", r)
    pause(2)

    # ═════════════════════════════════════════════════════════════════════
    # WORKFLOW 4: CHECKOUT
    # ═════════════════════════════════════════════════════════════════════
    print("\n=== WORKFLOW 4: CHECKOUT ===")
    pause(3)

    r = await record_checkout("705", "Vikram Das", "28/03/2026")
    ok("CHECKOUT-01", "Vikram checkout (with notice)", r)
    pause(2)

    # Checkout without notice
    r = await record_checkout("704", "Sneha Reddy")
    ok("CHECKOUT-02", "Sneha checkout (no notice, deposit forfeited)", r)
    pause(2)

    # ═════════════════════════════════════════════════════════════════════
    # WORKFLOW 5: PAYMENT AFTER CHECKOUT (settling dues)
    # ═════════════════════════════════════════════════════════════════════
    print("\n=== WORKFLOW 5: PAYMENT AFTER CHECKOUT ===")
    pause(3)

    r = await update_payment("705", "Vikram Das", 15000, "upi", month=4, year=2026)
    ok("PAY-EXIT-01", "Vikram pays after checkout (settling dues)", r)
    pause(2)

    # ═════════════════════════════════════════════════════════════════════
    # WORKFLOW 6: VALIDATION EDGE CASES
    # ═════════════════════════════════════════════════════════════════════
    print("\n=== WORKFLOW 6: EDGE CASES ===")
    pause(3)

    r = await update_payment("701", "Rahul Sharma", 0, "cash")
    ok("EDGE-01", "Zero amount rejected", r, expect=False)

    r = await update_payment("701", "Rahul Sharma", -1000, "upi")
    ok("EDGE-02", "Negative amount rejected", r, expect=False)

    r = await update_payment("999", "Ghost", 5000, "cash")
    ok("EDGE-03", "Non-existent room rejected", r, expect=False)

    r = await add_tenant("", "", "", "", "", "", "", "", 0, 0, 0, 0)
    ok("EDGE-04", "Empty add_tenant rejected", r, expect=False)

    r = await update_payment("701", "Rahul Sharma", 5000, "bitcoin")
    ok("EDGE-05", "Invalid method rejected", r, expect=False)

    # ═════════════════════════════════════════════════════════════════════
    # WORKFLOW 7: VERIFY GOOGLE SHEET
    # ═════════════════════════════════════════════════════════════════════
    print("\n=== WORKFLOW 7: VERIFY SHEET DATA ===")
    pause(5)

    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file('credentials/gsheets_service_account.json',
        scopes=['https://www.googleapis.com/auth/spreadsheets'])
    gc = gspread.authorize(creds)
    sp = gc.open_by_key('1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw')

    # Check APRIL tab
    april = sp.worksheet('APRIL 2026')
    adata = april.get_all_values()

    test_rooms = {"701": {}, "702": {}, "703": {}, "704": {}, "705": {}}
    # New format: 0=Room,1=Name,2=Phone,3=Building,4=Sharing,5=Rent,6=Cash,7=UPI,8=TP,9=Bal,10=Status
    for row in adata[4:]:
        rm = str(row[0]).strip()
        if rm in test_rooms:
            test_rooms[rm] = {
                "name": row[1], "phone": row[2], "building": row[3],
                "rent": row[5], "cash": row[6], "upi": row[7],
                "total_paid": row[8], "balance": row[9], "status": row[10],
                "notes": row[14] if len(row) > 14 else "",
            }

    print("\n  APRIL 2026 — Test tenant rows:")
    sheet_pass = 0
    sheet_fail = 0
    for rm, d in sorted(test_rooms.items()):
        if not d:
            print(f"  [FAIL] Room {rm}: NOT FOUND in April tab")
            sheet_fail += 1
            ERRORS.append(f"SHEET-{rm}: Not found in April tab")
            continue
        print(f"  Room {rm} | {d['name'][:20]} | Rent={d['rent']} | Cash={d['cash']} | UPI={d['upi']} | Bal={d['balance']} | St={d['status']} | Notes={d['notes'][:40]}")
        sheet_pass += 1

    # Specific checks
    d701 = test_rooms.get("701", {})
    if d701 and str(d701.get("status", "")).upper() == "PAID":
        ok("SHEET-701", "Rahul shows PAID (14K cash)", {"success": True})
    else:
        ok("SHEET-701", f"Rahul should be PAID, got {d701.get('status')}", {"success": False})

    d703 = test_rooms.get("703", {})
    if d703 and str(d703.get("status", "")).upper() == "PAID":
        ok("SHEET-703", "Amit shows PAID (5K cash + 8.5K UPI = 13.5K)", {"success": True})
    else:
        ok("SHEET-703", f"Amit should be PAID, got {d703.get('status')}", {"success": False})

    d705 = test_rooms.get("705", {})
    if d705 and str(d705.get("status", "")).upper() == "EXIT":
        ok("SHEET-705", "Vikram shows EXIT (checked out)", {"success": True})
    else:
        ok("SHEET-705", f"Vikram should be EXIT, got {d705.get('status')}", {"success": False})

    # Check notes contain payment timestamps
    if d701 and d701.get("notes"):
        ok("SHEET-NOTES", "Rahul has payment notes", {"success": True})
    else:
        ok("SHEET-NOTES", "Rahul should have payment notes", {"success": False})

    # Check TENANTS tab
    pause(2)
    tenants_ws = sp.worksheet('TENANTS')
    tdata = tenants_ws.get_all_values()
    found_count = 0
    for row in tdata[1:]:
        if str(row[0]).strip() in test_rooms:
            found_count += 1
    ok("SHEET-TENANTS", f"All 5 test tenants in TENANTS tab ({found_count}/5)", {"success": found_count >= 5})

    # ═════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ═════════════════════════════════════════════════════════════════════
    total = P + F
    print(f"\n{'=' * 70}")
    print(f"RESULTS: {P} PASS / {F} FAIL / {total} TOTAL")
    print(f"{'=' * 70}")
    if ERRORS:
        print("\nFAILED:")
        for e in ERRORS:
            print(f"  {e}")
    return F == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
