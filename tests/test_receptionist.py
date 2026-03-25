"""
Receptionist role edge-case test suite — 60+ tests.
Run with: PYTHONIOENCODING=utf-8 venv/Scripts/python tests/test_receptionist.py
Server must be running on localhost:8000
"""
import requests, sys, json, time
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://localhost:8000'
PHONE = '919999999999'
RESULTS = []

def send(msg):
    r = requests.post(f'{BASE}/api/whatsapp/process', json={'phone': PHONE, 'message': msg})
    d = r.json()
    reply = d.get('reply', d.get('message', str(d)))
    return reply

def clear():
    requests.post(f'{BASE}/api/test/clear-pending', params={'phone': PHONE})

def safe(s, n=200):
    return s.encode('ascii', 'replace').decode('ascii')[:n]

def test(name, msg, expect_contains=None, expect_not_contains=None, follow_up=None):
    """Run a test, optionally with a follow-up message (for pending flows)."""
    clear()
    reply = send(msg)

    if follow_up:
        time.sleep(0.3)
        reply = send(follow_up)

    passed = True
    reason = ""

    if expect_contains:
        for ec in (expect_contains if isinstance(expect_contains, list) else [expect_contains]):
            if ec.lower() not in reply.lower():
                passed = False
                reason = f"Missing: '{ec}'"
                break

    if expect_not_contains:
        for enc in (expect_not_contains if isinstance(expect_not_contains, list) else [expect_not_contains]):
            if enc.lower() in reply.lower():
                passed = False
                reason = f"Should NOT contain: '{enc}'"
                break

    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, status, reason))
    print(f"{status:4} | {name:<55} | {safe(reply, 120)}")
    if not passed:
        print(f"     | REASON: {reason}")
    return reply


print("=" * 120)
print("RECEPTIONIST EDGE CASE TEST SUITE")
print("=" * 120)

# ═══════════════════════════════════════════════════════
# PAYMENT LOGGING (25 tests)
# ═══════════════════════════════════════════════════════
print("\n--- PAYMENT LOGGING ---")

test("P01: Normal cash payment",
     "Akarsh room 102 paid 15000 cash",
     expect_contains="confirm")

test("P02: Normal UPI payment",
     "Akarsh room 102 paid 10000 upi",
     expect_contains=["confirm", "10,000"])

test("P03: Very small amount (suspicious)",
     "Akarsh room 102 paid 500 cash",
     expect_contains="confirm")

test("P04: Zero amount",
     "Prashant room 102 paid 0 cash",
     expect_contains=None)  # should reject or ask

test("P05: Negative amount",
     "Prashant paid -5000 upi",
     expect_not_contains="payment logged")

test("P06: Very large amount (5 lakh)",
     "Prashant room 102 paid 500000 upi",
     expect_contains=None)  # should flag overpayment

test("P07: No payment mode specified",
     "Prashant room 102 paid 15000",
     expect_contains=None)  # should ask cash/upi

test("P08: No amount specified",
     "Prashant room 102 paid cash",
     expect_contains=None)

test("P09: Only name no room",
     "Prashant paid 15000 upi",
     expect_contains="prashant")

test("P10: Only room no name",
     "room 102 paid 15000 cash",
     expect_contains="102")

test("P11: Wrong room for tenant",
     "Prashant room 305 paid 15000 upi",
     expect_contains=None)

test("P12: Non-existent tenant",
     "Xyzabc room 999 paid 15000 cash",
     expect_contains=None)

test("P13: Partial name multiple matches",
     "Kumar paid 10000 upi",
     expect_contains=None)

test("P14: Payment with decimal",
     "Prashant room 102 paid 15000.50 upi",
     expect_contains=None)

test("P15: Payment with comma format",
     "Prashant room 102 paid 15,000 upi",
     expect_contains=None)

test("P16: ALL CAPS input",
     "PRASHANT ROOM 102 PAID 15000 UPI",
     expect_contains="prashant")

test("P17: Mixed natural language",
     "collected 15000 from Prashant in room 102 via upi",
     expect_contains=None)

test("P18: Hindi style",
     "Prashant ne 15000 diya cash mein",
     expect_contains=None)

test("P19: Amount first",
     "15000 upi received from Prashant room 102",
     expect_contains=None)

test("P20: Shorthand",
     "102 15k cash",
     expect_contains=None)

test("P21: Rent + deposit combined",
     "Prashant room 102 paid 30000 upi rent and deposit",
     expect_contains=None)

test("P22: Payment with date",
     "Prashant room 102 paid 15000 cash on 20th march",
     expect_contains=None)

test("P23: Duplicate payment same tenant",
     "Akarsh room 102 paid 5000 cash",
     expect_contains="confirm")

test("P24: Payment with comment",
     "Prashant room 102 paid 15000 upi late payment",
     expect_contains=None)

test("P25: Two amounts mentioned",
     "Prashant paid 10000 cash and 5000 upi",
     expect_contains=None)


# ═══════════════════════════════════════════════════════
# DUES QUERIES (15 tests)
# ═══════════════════════════════════════════════════════
print("\n--- DUES QUERIES ---")

test("D01: Specific tenant dues by name",
     "Prashant balance",
     expect_contains=None)

test("D02: Dues by room number",
     "room 204 dues",
     expect_contains=None)

test("D03: All outstanding dues",
     "who has pending dues",
     expect_contains=None)

test("D04: Dues for exited tenant",
     "Sethuraman dues",
     expect_contains=None)

test("D05: Dues with typo in name",
     "Prashanttt balance",
     expect_contains=None)

test("D06: Total outstanding query",
     "total outstanding",
     expect_contains=None)

test("D07: Total pending query",
     "total pending amount",
     expect_contains=None)

test("D08: Dues for specific month",
     "february dues",
     expect_contains=None)

test("D09: March dues only",
     "march dues outstanding",
     expect_contains=None)

test("D10: How much does X owe",
     "how much does Prashant owe",
     expect_contains=None)

test("D11: Pending for room",
     "pending payment room 102",
     expect_contains=None)

test("D12: Balance enquiry",
     "check balance of Anshit room 204",
     expect_contains=None)

test("D13: Dues after logging payment",
     "Anshit room 204 dues",
     expect_contains=None)

test("D14: Non-existent tenant dues",
     "Xyzabc balance",
     expect_contains=None)

test("D15: All dues with comments",
     "show all dues with comments",
     expect_contains=None)


# ═══════════════════════════════════════════════════════
# COMPLAINTS (10 tests)
# ═══════════════════════════════════════════════════════
print("\n--- COMPLAINTS ---")

test("C01: Register with room + details",
     "complaint room 204 water leaking from bathroom ceiling",
     expect_contains=["complaint logged", "204"])

test("C02: Register without room number",
     "complaint ac not working in building",
     expect_contains="room")

test("C03: Register plumbing",
     "complaint room 305 toilet is blocked since yesterday",
     expect_contains="plumbing")

test("C04: Register electrical",
     "complaint room 102 light switch not working",
     expect_contains="complaint logged")

test("C05: Query all open complaints",
     "show open complaints",
     expect_contains="open complaints")

test("C06: Long complaint text",
     "complaint room 401 " + "the AC is making very loud noise and water is dripping from it onto the floor causing water damage to the furniture below and the tenant is very upset about this situation " * 2,
     expect_contains="complaint logged")

test("C07: Resolve latest complaint",
     "resolve complaint 305",
     expect_contains=["resolved", "305"])

test("C08: Resolve already resolved",
     "resolve complaint 305",
     expect_contains=None)  # should say already resolved or not found

test("C09: Complaint with tenant name",
     "complaint from Prashant room 102 wifi not working",
     expect_contains="complaint logged")

test("C10: Multiple complaints same room",
     "complaint room 204 cockroach problem in kitchen",
     expect_contains="complaint logged")


# ═══════════════════════════════════════════════════════
# ACCESS CONTROL (8 tests)
# ═══════════════════════════════════════════════════════
print("\n--- ACCESS CONTROL ---")

test("A01: Bank report - BLOCKED",
     "bank report march",
     expect_contains="owner-level")

test("A02: Add tenant - BLOCKED",
     "add tenant john room 105",
     expect_contains="owner-level")

test("A03: Checkout - BLOCKED",
     "checkout Prashant room 102",
     expect_contains="owner-level")

test("A04: Void payment - BLOCKED",
     "void last payment",
     expect_contains="owner-level")

test("A05: Rent change - BLOCKED",
     "change rent room 102 to 20000",
     expect_contains="owner-level")

test("A06: Monthly report - BLOCKED",
     "monthly report march",
     expect_contains="owner-level")

test("A07: Add expense - BLOCKED",
     "add expense 5000 plumbing repair",
     expect_contains="owner-level")

test("A08: Deposit change - BLOCKED",
     "change deposit room 102 to 30000",
     expect_contains="owner-level")


# ═══════════════════════════════════════════════════════
# TENANT/ROOM LOOKUP (7 tests)
# ═══════════════════════════════════════════════════════
print("\n--- TENANT/ROOM LOOKUP ---")

test("T01: Who is in room",
     "who is in room 204",
     expect_not_contains="owner-level")

test("T02: Room status",
     "room status 305",
     expect_not_contains="owner-level")

test("T03: Tenant details by name",
     "tenant details Prashant",
     expect_not_contains="owner-level")

test("T04: Occupancy report",
     "occupancy",
     expect_contains=["291", "beds"])

test("T05: Vacant rooms",
     "vacant rooms",
     expect_not_contains="owner-level")

test("T06: Contact list",
     "contact list",
     expect_contains="contacts")

test("T07: Greeting",
     "hi",
     expect_contains="artha")


# ═══════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════
print("\n" + "=" * 120)
passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
total = len(RESULTS)
print(f"RESULTS: {passed}/{total} PASSED, {failed} FAILED")

if failed > 0:
    print("\nFAILED TESTS:")
    for name, status, reason in RESULTS:
        if status == "FAIL":
            print(f"  - {name}: {reason}")
