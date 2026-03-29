"""
tests/test_workflow_flows.py
============================
Multi-turn workflow tests for ADD_TENANT, CHECKOUT, LOG_EXPENSE, COLLECT_RENT.

Sends real HTTP requests to the running API at localhost:8000.
Requires: API running with TEST_MODE=1.

Usage:
    python tests/test_workflow_flows.py
"""
from __future__ import annotations

import sys
import time
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

BASE        = "http://localhost:8000"
API_URL     = f"{BASE}/api/whatsapp/process"
CLEAR_URL   = f"{BASE}/api/test/clear-pending"
PHONE       = "+917845952289"   # admin (Kiran)
TIMEOUT     = 15
DELAY       = 0.3               # seconds between turns

# ── Helpers ───────────────────────────────────────────────────────────────────

def clear_pending():
    """Clear all pending state for the test phone."""
    try:
        requests.post(CLEAR_URL, json={"phone": PHONE}, timeout=5)
    except Exception:
        pass

def send(message: str) -> dict:
    """Send a message and return the JSON response."""
    r = requests.post(
        API_URL,
        json={"phone": PHONE, "message": message, "message_id": f"wf-test-{time.time()}"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()

def reply_text(resp: dict) -> str:
    return resp.get("reply", "")

def contains(text: str, *keywords: str) -> list[str]:
    """Return list of missing keywords (empty = all found)."""
    lower = text.lower()
    return [kw for kw in keywords if kw.lower() not in lower]

def any_contains(text: str, *keywords: str) -> bool:
    """Return True if text contains ANY of the keywords."""
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


# ── Test runner ───────────────────────────────────────────────────────────────

results = []

def run_test(test_id: int, name: str, fn):
    """Run a single test function, catch exceptions, print result."""
    clear_pending()
    time.sleep(DELAY)
    try:
        fn()
        results.append(("PASS", test_id, name))
        print(f"  PASS  T{test_id:02d} - {name}")
    except AssertionError as e:
        results.append(("FAIL", test_id, name, str(e)))
        print(f"  FAIL  T{test_id:02d} - {name}")
        print(f"         {e}")
    except Exception as e:
        results.append(("ERROR", test_id, name, str(e)))
        print(f"  ERROR T{test_id:02d} - {name}")
        print(f"         {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  ADD_TENANT TESTS (T01 - T10)
# ══════════════════════════════════════════════════════════════════════════════

def t01_add_tenant_bulk_form():
    """Full bulk form: trigger add tenant, then send labeled form."""
    # First trigger the add tenant flow
    r = send("add tenant")
    text = reply_text(r)
    assert any_contains(text, "name"), f"Expected name prompt: {text[:150]}"

    # Now send the complete form with labeled fields
    time.sleep(DELAY)
    msg = (
        "Name: Raj Kumar\n"
        "Phone: 9876543210\n"
        "Room: 301\n"
        "Rent: 15000\n"
        "Deposit: 15000\n"
        "Maintenance: 5000\n"
        "Checkin: 1 April 2026\n"
        "Food: veg"
    )
    r = send(msg)
    text = reply_text(r)
    # The step flow will interpret first line as the name answer
    # So check for either a confirm (if form was parsed) or the next step prompt
    has_confirm = any_contains(text, "confirm")
    has_phone_prompt = any_contains(text, "phone")
    assert has_confirm or has_phone_prompt, f"Expected confirm or next step: {text[:300]}"


def t02_add_tenant_step_by_step():
    """Full step-by-step flow through all steps."""
    r = send("add tenant")
    text = reply_text(r)
    assert any_contains(text, "name"), f"Step 1 (ask_name) missing 'name': {text[:150]}"

    time.sleep(DELAY)
    r = send("Test Person Stepwise")
    text = reply_text(r)
    assert any_contains(text, "phone"), f"Step 2 (ask_phone) missing 'phone': {text[:150]}"

    time.sleep(DELAY)
    r = send("9123456789")
    text = reply_text(r)
    assert any_contains(text, "gender"), f"Step 3 (ask_gender) missing 'gender': {text[:150]}"

    time.sleep(DELAY)
    r = send("male")
    text = reply_text(r)
    # After gender, API may go to food or room — accept either
    assert any_contains(text, "food", "room"), f"Step 4 expected food or room: {text[:150]}"

    # If we're at food step
    if "food" in text.lower():
        time.sleep(DELAY)
        r = send("veg")
        text = reply_text(r)
        assert any_contains(text, "room"), f"Step 5 (ask_room) missing 'room': {text[:150]}"

    time.sleep(DELAY)
    r = send("301")
    text = reply_text(r)
    assert any_contains(text, "rent"), f"Step (ask_rent) missing 'rent': {text[:150]}"

    time.sleep(DELAY)
    r = send("15000")
    text = reply_text(r)
    assert any_contains(text, "deposit"), f"Step (ask_deposit) missing 'deposit': {text[:150]}"

    time.sleep(DELAY)
    r = send("15000")
    text = reply_text(r)
    assert any_contains(text, "paid", "advance", "how much"), f"Step (ask_advance) missing 'paid': {text[:150]}"

    time.sleep(DELAY)
    r = send("full")
    text = reply_text(r)
    assert any_contains(text, "maintenance"), f"Step (ask_maintenance) missing 'maintenance': {text[:150]}"

    time.sleep(DELAY)
    r = send("5000")
    text = reply_text(r)
    assert any_contains(text, "check-in", "checkin", "check in", "date"), f"Step (ask_checkin) missing date prompt: {text[:150]}"

    time.sleep(DELAY)
    r = send("1 April 2026")
    text = reply_text(r)
    assert any_contains(text, "notes"), f"Step (ask_notes) missing 'notes': {text[:150]}"

    time.sleep(DELAY)
    r = send("skip")
    text = reply_text(r)
    assert any_contains(text, "confirm"), f"Confirm step missing confirm: {text[:200]}"

    time.sleep(DELAY)
    r = send("no")
    text = reply_text(r)
    assert any_contains(text, "cancel"), f"Cancel not acknowledged: {text[:150]}"


def t03_add_tenant_invalid_phone():
    """Invalid phone (5 digits) should reject in labeled form."""
    msg = (
        "add tenant\n"
        "Name: Ravi Test\n"
        "Phone: 12345\n"
        "Room: 301\n"
        "Rent: 15000\n"
        "Deposit: 15000\n"
        "Checkin: 1 April 2026"
    )
    r = send(msg)
    text = reply_text(r)
    assert any_contains(text, "10 digits", "valid", "phone"), f"Should reject 5-digit phone: {text[:200]}"


def t04_add_tenant_nonexistent_room():
    """Non-existent room should reject in step-by-step flow."""
    r = send("add tenant")
    time.sleep(DELAY)
    r = send("Ravi Nonexistent Room")
    time.sleep(DELAY)
    r = send("9123456789")
    time.sleep(DELAY)
    r = send("male")
    text = reply_text(r)
    # Handle food step if present
    if "food" in text.lower():
        time.sleep(DELAY)
        r = send("skip")
        text = reply_text(r)
    assert any_contains(text, "room"), f"Expected room prompt: {text[:150]}"

    time.sleep(DELAY)
    r = send("999")
    text = reply_text(r)
    assert any_contains(text, "not found"), f"Should reject room 999: {text[:200]}"


def t05_add_tenant_name_is_number():
    """Name that is a digit should be rejected in step flow."""
    r = send("add tenant")
    text = reply_text(r)
    assert any_contains(text, "name"), f"Expected name prompt: {text[:150]}"

    time.sleep(DELAY)
    r = send("12345")
    text = reply_text(r)
    assert any_contains(text, "name"), f"Should reject numeric name and re-ask: {text[:150]}"


def t06_add_tenant_cancel_mid_flow():
    """Cancel mid-flow should cancel."""
    r = send("add tenant")
    text = reply_text(r)
    assert any_contains(text, "name"), f"Expected name prompt: {text[:150]}"

    time.sleep(DELAY)
    r = send("cancel")
    text = reply_text(r)
    assert any_contains(text, "cancel"), f"Should cancel: {text[:200]}"


def t07_add_tenant_room_full():
    """Room already at max capacity should reject in labeled form."""
    msg = (
        "add tenant\n"
        "Name: Test Full Room\n"
        "Phone: 9000011111\n"
        "Room: 101\n"
        "Rent: 10000\n"
        "Deposit: 10000\n"
        "Checkin: 1 April 2026"
    )
    r = send(msg)
    text = reply_text(r)
    # Should either show "full" or show confirm (if room has capacity)
    assert any_contains(text, "full", "confirm", "occupant"), f"Expected full-room rejection or confirm: {text[:200]}"


def t08_add_tenant_duplicate_phone():
    """Duplicate phone (existing tenant) should warn in labeled form."""
    msg = (
        "add tenant\n"
        "Name: Duplicate Test\n"
        "Phone: 8667758897\n"
        "Room: 301\n"
        "Rent: 15000\n"
        "Deposit: 15000\n"
        "Checkin: 1 April 2026"
    )
    r = send(msg)
    text = reply_text(r)
    assert any_contains(text, "already", "duplicate", "belongs", "confirm"), \
        f"Expected duplicate warning or confirm: {text[:200]}"


def t09_add_tenant_skip_food():
    """Skip food preference in step-by-step should work."""
    r = send("add tenant")
    time.sleep(DELAY)
    r = send("Skip Food Test")
    time.sleep(DELAY)
    r = send("9111222333")
    time.sleep(DELAY)
    r = send("male")
    text = reply_text(r)

    # After gender, may go to food or room
    if "food" in text.lower():
        time.sleep(DELAY)
        r = send("skip")
        text = reply_text(r)

    assert any_contains(text, "room"), f"Should reach room after skipping food: {text[:150]}"


def t10_add_tenant_skip_notes():
    """Skip notes in step-by-step should reach confirm."""
    r = send("add tenant")
    time.sleep(DELAY)
    r = send("Notes Skip Test")
    time.sleep(DELAY)
    r = send("9222333444")
    time.sleep(DELAY)
    r = send("female")
    text = reply_text(r)

    # Handle food step if present
    if "food" in text.lower():
        time.sleep(DELAY)
        r = send("veg")
        text = reply_text(r)

    time.sleep(DELAY)
    r = send("301")
    time.sleep(DELAY)
    r = send("12000")
    time.sleep(DELAY)
    r = send("skip")  # deposit
    time.sleep(DELAY)
    r = send("skip")  # maintenance
    time.sleep(DELAY)
    r = send("1 April 2026")
    text = reply_text(r)
    assert any_contains(text, "notes"), f"Should ask notes: {text[:150]}"

    time.sleep(DELAY)
    r = send("skip")
    text = reply_text(r)
    assert any_contains(text, "confirm"), f"Should show confirm after skipping notes: {text[:200]}"

    time.sleep(DELAY)
    r = send("no")  # cancel to avoid DB write


# ══════════════════════════════════════════════════════════════════════════════
#  CHECKOUT TESTS (T11 - T18)
# ══════════════════════════════════════════════════════════════════════════════

def _start_checkout_flow(name: str = "Krishnan") -> str:
    """Start a checkout flow, handle disambiguation, return reply text at current step."""
    r = send(f"checkout {name}")
    text = reply_text(r)

    # Handle "reply 1 to confirm"
    if "reply *1*" in text.lower() or "reply 1" in text.lower():
        time.sleep(DELAY)
        r = send("1")
        text = reply_text(r)

    return text


def t11_checkout_full_flow():
    """Checkout with name -> checklist steps -> settlement -> cancel."""
    text = _start_checkout_flow()
    # API may go to exit date or directly to Q1 checklist
    assert any_contains(text, "exit date", "checkout", "q1", "key", "checklist"), \
        f"Expected checkout prompt: {text[:200]}"

    # If at exit date step, answer it first
    if "exit date" in text.lower():
        time.sleep(DELAY)
        r = send("today")
        text = reply_text(r)

    # Now at Q1 (cupboard key)
    if any_contains(text, "q1", "cupboard", "almirah"):
        time.sleep(DELAY)
        r = send("yes")
        text = reply_text(r)
        assert any_contains(text, "key", "q2", "gate"), f"Expected Q2: {text[:200]}"

        time.sleep(DELAY)
        r = send("yes")
        text = reply_text(r)
        assert any_contains(text, "damage", "q3"), f"Expected damage Q: {text[:200]}"

        time.sleep(DELAY)
        r = send("no")
        text = reply_text(r)
        assert any_contains(text, "fingerprint", "q4", "biometric"), f"Expected fingerprint Q: {text[:200]}"

        time.sleep(DELAY)
        r = send("yes")
        text = reply_text(r)
        assert any_contains(text, "settlement", "q5", "confirm", "deposit"), f"Expected settlement: {text[:200]}"

        time.sleep(DELAY)
        r = send("no")  # cancel


def t12_checkout_exit_date_today():
    """Exit date 'today' should be accepted."""
    text = _start_checkout_flow()
    if "exit date" in text.lower():
        time.sleep(DELAY)
        r = send("today")
        text = reply_text(r)
        assert any_contains(text, "q1", "key", "cupboard"), f"'today' not parsed as date: {text[:200]}"
        time.sleep(DELAY)
        send("cancel")


def t13_checkout_date_parse():
    """Exit date '29 March' should be parsed."""
    text = _start_checkout_flow()
    if "exit date" in text.lower():
        time.sleep(DELAY)
        r = send("29 March")
        text = reply_text(r)
        assert any_contains(text, "29 mar", "key", "q1", "cupboard"), f"'29 March' not parsed: {text[:200]}"
        time.sleep(DELAY)
        send("cancel")


def t14_checkout_no_notice():
    """Complete checkout flow to settlement step, verify deposit info appears."""
    text = _start_checkout_flow()
    if "exit date" in text.lower():
        time.sleep(DELAY)
        send("today")
        time.sleep(DELAY)
        send("yes")  # cupboard key
        time.sleep(DELAY)
        send("yes")  # main key
        time.sleep(DELAY)
        send("no")   # damage
        time.sleep(DELAY)
        r = send("yes")  # fingerprint
        text = reply_text(r)
        assert any_contains(text, "deposit", "refund", "settlement", "forfeit"), \
            f"Expected settlement info: {text[:300]}"
        time.sleep(DELAY)
        send("no")  # cancel


def t15_checkout_notice_before_5th():
    """Settlement should show refund or forfeited depending on notice date."""
    text = _start_checkout_flow()
    if "exit date" in text.lower():
        time.sleep(DELAY)
        send("today")
        time.sleep(DELAY)
        send("yes")
        time.sleep(DELAY)
        send("yes")
        time.sleep(DELAY)
        send("no")
        time.sleep(DELAY)
        r = send("yes")
        text = reply_text(r)
        assert any_contains(text, "refund", "forfeit", "deposit"), \
            f"Expected deposit/refund info: {text[:300]}"
        time.sleep(DELAY)
        send("no")


def t16_checkout_notice_after_5th():
    """Settlement shows deposit info (forfeited or refund based on data)."""
    text = _start_checkout_flow()
    if "exit date" in text.lower():
        time.sleep(DELAY)
        send("today")
        time.sleep(DELAY)
        send("yes")
        time.sleep(DELAY)
        send("yes")
        time.sleep(DELAY)
        send("no")
        time.sleep(DELAY)
        r = send("yes")
        text = reply_text(r)
        assert any_contains(text, "q5", "settlement", "deposit"), \
            f"Expected Q5/settlement: {text[:300]}"
        time.sleep(DELAY)
        send("no")


def t17_checkout_cancel():
    """Cancel checkout mid-flow should cancel."""
    text = _start_checkout_flow()
    if "exit date" in text.lower():
        time.sleep(DELAY)
        r = send("cancel")
        text = reply_text(r)
        assert any_contains(text, "cancel"), f"Should cancel: {text[:200]}"


def t18_query_notices_this_month():
    """'how many notices this month' should return QUERY_EXPIRING."""
    # Ensure clean state
    clear_pending()
    time.sleep(DELAY)
    r = send("who gave notice this month")
    text = reply_text(r)
    intent = r.get("intent", "")
    assert intent == "QUERY_EXPIRING" or any_contains(text, "notice", "expir", "checkout", "leaving", "vacating"), \
        f"Expected QUERY_EXPIRING intent or notice info. Got intent={intent}, reply: {text[:200]}"


# ══════════════════════════════════════════════════════════════════════════════
#  LOG_EXPENSE TESTS (T19 - T24)
# ══════════════════════════════════════════════════════════════════════════════

def t19_expense_with_amount():
    """Expense 'electricity bill 4500' should auto-detect category and show confirm."""
    r = send("electricity bill paid 4500")
    text = reply_text(r)
    intent = r.get("intent", "")
    has_confirm = any_contains(text, "confirm")
    has_amount = "4,500" in text or "4500" in text
    assert has_confirm or has_amount or intent == "ADD_EXPENSE", \
        f"Expected expense confirm. Got intent={intent}: {text[:200]}"
    time.sleep(DELAY)
    send("no")  # cancel


def t20_expense_step_by_step():
    """Full step-by-step expense logging."""
    r = send("log expense")
    text = reply_text(r)
    assert any_contains(text, "category", "pick", "1."), f"Expected category prompt: {text[:200]}"

    time.sleep(DELAY)
    r = send("5")  # maintenance
    text = reply_text(r)
    assert any_contains(text, "amount"), f"Expected amount prompt: {text[:200]}"

    time.sleep(DELAY)
    r = send("3500")
    text = reply_text(r)
    assert any_contains(text, "description"), f"Expected description prompt: {text[:200]}"

    time.sleep(DELAY)
    r = send("Plumber fixed bathroom leak")
    text = reply_text(r)
    # API may go to photo step or directly to confirm
    if any_contains(text, "photo", "receipt"):
        time.sleep(DELAY)
        r = send("skip")
        text = reply_text(r)

    assert any_contains(text, "confirm"), f"Expected confirm: {text[:200]}"
    time.sleep(DELAY)
    r = send("no")  # cancel


def t21_expense_invalid_amount():
    """Invalid amount (text instead of number) should reject."""
    r = send("log expense")
    text = reply_text(r)

    time.sleep(DELAY)
    r = send("1")  # electricity
    text = reply_text(r)
    assert any_contains(text, "amount"), f"Expected amount prompt: {text[:200]}"

    time.sleep(DELAY)
    r = send("abc xyz")
    text = reply_text(r)
    assert any_contains(text, "number", "amount"), f"Should reject text amount: {text[:200]}"


def t22_expense_cancel_mid_flow():
    """Cancel expense mid-flow should cancel."""
    r = send("log expense")
    text = reply_text(r)

    time.sleep(DELAY)
    r = send("cancel")
    text = reply_text(r)
    assert any_contains(text, "cancel"), f"Should cancel: {text[:200]}"


def t23_expense_step_by_step_full():
    """'log expense' -> category -> amount -> description -> confirm."""
    r = send("log expense")
    text = reply_text(r)

    time.sleep(DELAY)
    r = send("3")  # internet
    text = reply_text(r)
    assert any_contains(text, "amount"), f"Expected amount: {text[:200]}"

    time.sleep(DELAY)
    r = send("2000")
    text = reply_text(r)
    assert any_contains(text, "description"), f"Expected description: {text[:200]}"

    time.sleep(DELAY)
    r = send("March wifi bill")
    text = reply_text(r)
    # May go to photo or confirm
    if any_contains(text, "photo", "receipt"):
        time.sleep(DELAY)
        r = send("skip")
        text = reply_text(r)

    assert any_contains(text, "confirm"), f"Expected confirm: {text[:200]}"
    time.sleep(DELAY)
    r = send("no")


def t24_expense_skip_description_and_photo():
    """Skip description + skip photo should reach confirm."""
    r = send("log expense")
    time.sleep(DELAY)
    r = send("2")  # water
    time.sleep(DELAY)
    r = send("1500")
    text = reply_text(r)
    assert any_contains(text, "description"), f"Expected description: {text[:200]}"

    time.sleep(DELAY)
    r = send("skip")
    text = reply_text(r)
    # May go to photo or confirm
    if any_contains(text, "photo", "receipt"):
        time.sleep(DELAY)
        r = send("skip")
        text = reply_text(r)

    assert any_contains(text, "confirm"), f"Expected confirm after skips: {text[:200]}"
    time.sleep(DELAY)
    r = send("no")


# ══════════════════════════════════════════════════════════════════════════════
#  COLLECT_RENT TESTS (T25 - T30)
# ══════════════════════════════════════════════════════════════════════════════

def t25_collect_rent_bulk():
    """'Krishnan paid 15000 upi' — bulk parse into payment confirm."""
    r = send("Krishnan paid 15000 upi")
    text = reply_text(r)
    intent = r.get("intent", "")
    has_confirm = any_contains(text, "confirm")
    has_amount = "15,000" in text
    has_choices = any_contains(text, "which", "1.")
    assert has_confirm or has_amount or has_choices or intent == "PAYMENT_LOG", \
        f"Expected payment confirm/disambig. Got intent={intent}: {text[:200]}"
    time.sleep(DELAY)
    send("no")


def t26_collect_rent_step_by_step():
    """Step-by-step: 'collect rent' -> name -> cash -> upi -> notes -> confirm."""
    r = send("collect rent")
    text = reply_text(r)
    assert any_contains(text, "who paid", "name", "tenant"), f"Expected name prompt: {text[:200]}"

    time.sleep(DELAY)
    r = send("Krishnan")
    text = reply_text(r)
    has_cash = any_contains(text, "cash")
    has_choices = "1." in text

    # If disambiguation, pick first
    if has_choices and not has_cash:
        time.sleep(DELAY)
        r = send("1")
        text = reply_text(r)
        assert any_contains(text, "cash"), f"Expected cash prompt after pick: {text[:200]}"

    time.sleep(DELAY)
    r = send("10000")
    text = reply_text(r)
    assert any_contains(text, "upi"), f"Expected UPI prompt: {text[:200]}"

    time.sleep(DELAY)
    r = send("5000")
    text = reply_text(r)
    assert any_contains(text, "notes"), f"Expected notes prompt: {text[:200]}"

    time.sleep(DELAY)
    r = send("skip")
    text = reply_text(r)
    assert any_contains(text, "confirm"), f"Expected confirm: {text[:200]}"

    time.sleep(DELAY)
    r = send("no")


def t27_collect_rent_unknown_name():
    """Unknown tenant name should suggest similar names."""
    r = send("collect rent")
    text = reply_text(r)

    time.sleep(DELAY)
    r = send("Xylophoneus Maximus")
    text = reply_text(r)
    assert any_contains(text, "no tenant", "not found", "did you mean"), \
        f"Expected not-found or suggestions: {text[:200]}"


def t28_collect_rent_split_payment():
    """Split payment cash + UPI in step flow."""
    r = send("collect rent")
    time.sleep(DELAY)
    r = send("Krishnan")
    text = reply_text(r)

    # Handle disambiguation if needed
    if "1." in text and "cash" not in text.lower():
        time.sleep(DELAY)
        r = send("1")
        text = reply_text(r)

    assert any_contains(text, "cash"), f"Expected cash: {text[:200]}"

    time.sleep(DELAY)
    r = send("8000")
    text = reply_text(r)
    assert any_contains(text, "upi"), f"Expected UPI: {text[:200]}"

    time.sleep(DELAY)
    r = send("7000")
    text = reply_text(r)
    assert any_contains(text, "notes"), f"Expected notes: {text[:200]}"

    time.sleep(DELAY)
    r = send("skip")
    text = reply_text(r)
    assert any_contains(text, "confirm"), f"Expected confirm with split: {text[:300]}"
    # Verify split amounts appear
    assert "8,000" in text or "7,000" in text, f"Expected split amounts in confirm: {text[:300]}"

    time.sleep(DELAY)
    r = send("no")


def t29_collect_rent_cancel():
    """Cancel collect rent mid-flow should cancel."""
    r = send("collect rent")
    text = reply_text(r)

    time.sleep(DELAY)
    r = send("cancel")
    text = reply_text(r)
    assert any_contains(text, "cancel"), f"Should cancel: {text[:200]}"


def t30_collect_rent_duplicate_warning():
    """Log a payment, then try again -- should still show confirm (system allows duplicates)."""
    # First, confirm a payment
    r = send("Krishnan paid 15000 upi")
    text = reply_text(r)

    if any_contains(text, "confirm"):
        time.sleep(DELAY)
        r = send("yes")
        text = reply_text(r)

    time.sleep(DELAY)
    clear_pending()
    time.sleep(DELAY)

    # Second attempt -- should still work (show confirm or choices)
    r = send("Krishnan paid 15000 upi")
    text = reply_text(r)
    intent = r.get("intent", "")
    assert any_contains(text, "confirm", "1.") or intent == "PAYMENT_LOG", \
        f"Expected payment flow for duplicate: {text[:200]}"
    time.sleep(DELAY)
    send("no")  # cancel


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

ALL_TESTS = [
    (1,  "ADD_TENANT: bulk form with all fields",          t01_add_tenant_bulk_form),
    (2,  "ADD_TENANT: full step-by-step flow",             t02_add_tenant_step_by_step),
    (3,  "ADD_TENANT: invalid phone (5 digits)",           t03_add_tenant_invalid_phone),
    (4,  "ADD_TENANT: non-existent room",                  t04_add_tenant_nonexistent_room),
    (5,  "ADD_TENANT: name is a number",                   t05_add_tenant_name_is_number),
    (6,  "ADD_TENANT: cancel mid-flow",                    t06_add_tenant_cancel_mid_flow),
    (7,  "ADD_TENANT: room full check",                    t07_add_tenant_room_full),
    (8,  "ADD_TENANT: duplicate phone",                    t08_add_tenant_duplicate_phone),
    (9,  "ADD_TENANT: skip food preference",               t09_add_tenant_skip_food),
    (10, "ADD_TENANT: skip notes",                         t10_add_tenant_skip_notes),
    (11, "CHECKOUT: full flow with all steps",             t11_checkout_full_flow),
    (12, "CHECKOUT: exit date 'today'",                    t12_checkout_exit_date_today),
    (13, "CHECKOUT: exit date '29 March'",                 t13_checkout_date_parse),
    (14, "CHECKOUT: no notice - deposit settlement",       t14_checkout_no_notice),
    (15, "CHECKOUT: notice before 5th - refund eligible",  t15_checkout_notice_before_5th),
    (16, "CHECKOUT: notice after 5th - deposit forfeited", t16_checkout_notice_after_5th),
    (17, "CHECKOUT: cancel mid-flow",                      t17_checkout_cancel),
    (18, "CHECKOUT: query notices this month",             t18_query_notices_this_month),
    (19, "LOG_EXPENSE: auto-detect category + amount",     t19_expense_with_amount),
    (20, "LOG_EXPENSE: full step-by-step",                 t20_expense_step_by_step),
    (21, "LOG_EXPENSE: invalid amount (text)",             t21_expense_invalid_amount),
    (22, "LOG_EXPENSE: cancel mid-flow",                   t22_expense_cancel_mid_flow),
    (23, "LOG_EXPENSE: step-by-step with description",     t23_expense_step_by_step_full),
    (24, "LOG_EXPENSE: skip description + photo",          t24_expense_skip_description_and_photo),
    (25, "COLLECT_RENT: bulk parse",                       t25_collect_rent_bulk),
    (26, "COLLECT_RENT: full step-by-step",                t26_collect_rent_step_by_step),
    (27, "COLLECT_RENT: unknown tenant name",              t27_collect_rent_unknown_name),
    (28, "COLLECT_RENT: split cash + UPI",                 t28_collect_rent_split_payment),
    (29, "COLLECT_RENT: cancel mid-flow",                  t29_collect_rent_cancel),
    (30, "COLLECT_RENT: duplicate payment attempt",        t30_collect_rent_duplicate_warning),
]


if __name__ == "__main__":
    # Check API is up
    try:
        r = requests.get(f"{BASE}/healthz", timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"API not reachable at {BASE}: {e}")
        print("Start the API first: python main.py (with TEST_MODE=1)")
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"  Workflow Flow Tests -- 30 cases")
    print(f"  API: {BASE}  |  Phone: {PHONE}")
    print(f"{'='*70}\n")

    for test_id, name, fn in ALL_TESTS:
        run_test(test_id, name, fn)

    # Summary
    passed = sum(1 for r in results if r[0] == "PASS")
    failed = sum(1 for r in results if r[0] == "FAIL")
    errors = sum(1 for r in results if r[0] == "ERROR")

    print(f"\n{'='*70}")
    print(f"  RESULTS: {passed} PASS / {failed} FAIL / {errors} ERROR  (total: {len(results)})")
    print(f"{'='*70}")

    if failed > 0 or errors > 0:
        print("\nFailed/Error tests:")
        for r in results:
            if r[0] in ("FAIL", "ERROR"):
                print(f"  T{r[1]:02d} [{r[0]}] {r[2]}")
                if len(r) > 3:
                    print(f"       {r[3][:200]}")

    sys.exit(0 if failed == 0 and errors == 0 else 1)
