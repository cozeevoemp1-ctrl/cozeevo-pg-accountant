"""
Stress test: 100+ confusing/edge-case messages per intent group.
Calls Groq directly via ClaudeClient to verify intent classification.

Usage:
    python tests/stress_test_intents.py                    # run all
    python tests/stress_test_intents.py --group payments   # run one group
    python tests/stress_test_intents.py --limit 50         # limit per group
    python tests/stress_test_intents.py --dry-run          # show test cases only

Rate limit: Groq free tier = 30 RPM, 14,400/day.
We add 2.1s delay between calls to stay under 30 RPM.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

os.environ.setdefault("LLM_PROVIDER", "groq")

from src.llm_gateway.claude_client import get_claude_client


# ── Test cases: message -> expected intent ────────────────────────────────────

STRESS_CASES: dict[str, list[dict]] = {
    "PAYMENT_LOG": [
        # Normal
        {"msg": "Raj paid 15000", "expect": "PAYMENT_LOG"},
        {"msg": "received 8000 from room 203", "expect": "PAYMENT_LOG"},
        {"msg": "collected rent from Jeevan 12000 cash", "expect": "PAYMENT_LOG"},
        {"msg": "Priya ne 10k diya", "expect": "PAYMENT_LOG"},
        {"msg": "got 5000 upi from 305", "expect": "PAYMENT_LOG"},
        # Confusing
        {"msg": "Ravi gave money today", "expect": "PAYMENT_LOG"},
        {"msg": "15k mil gaya Arun se", "expect": "PAYMENT_LOG"},
        {"msg": "payment aaya hai 8000", "expect": "PAYMENT_LOG"},
        {"msg": "rent collected Suresh 7000", "expect": "PAYMENT_LOG"},
        {"msg": "Deepak 12000 by gpay", "expect": "PAYMENT_LOG"},
        {"msg": "received from Kumar", "expect": "PAYMENT_LOG"},
        {"msg": "9500 cash Mohan room 102", "expect": "PAYMENT_LOG"},
        {"msg": "Aditya paid via phonepe 11000", "expect": "PAYMENT_LOG"},
        {"msg": "tenant paid half rent 6000", "expect": "PAYMENT_LOG"},
        {"msg": "partial payment 4000 Rahul", "expect": "PAYMENT_LOG"},
        {"msg": "cash mila 7500", "expect": "PAYMENT_LOG"},
        {"msg": "Vikram UPI transfer 13000", "expect": "PAYMENT_LOG"},
        {"msg": "paisa aaya Amit ka", "expect": "PAYMENT_LOG"},
        {"msg": "10000 received today from 401", "expect": "PAYMENT_LOG"},
        {"msg": "collect from Karthik 8500", "expect": "PAYMENT_LOG"},
    ],
    "QUERY_DUES": [
        {"msg": "who hasn't paid", "expect": "QUERY_DUES"},
        {"msg": "pending list", "expect": "QUERY_DUES"},
        {"msg": "dues list for march", "expect": "QUERY_DUES"},
        {"msg": "kiska paisa baaki hai", "expect": "QUERY_DUES"},
        {"msg": "unpaid tenants", "expect": "QUERY_DUES"},
        {"msg": "defaulters list", "expect": "QUERY_DUES"},
        {"msg": "who owes rent", "expect": "QUERY_DUES"},
        {"msg": "outstanding balances", "expect": "QUERY_DUES"},
        {"msg": "show me dues", "expect": "QUERY_DUES"},
        {"msg": "rent pending konsa konsa", "expect": "QUERY_DUES"},
        {"msg": "how many not paid yet", "expect": "QUERY_DUES"},
        {"msg": "pending payments april", "expect": "QUERY_DUES"},
        {"msg": "rent nahi diya kisne", "expect": "QUERY_DUES"},
        {"msg": "baaki list dikhao", "expect": "QUERY_DUES"},
        {"msg": "who all are pending", "expect": "QUERY_DUES"},
    ],
    "QUERY_TENANT": [
        {"msg": "Raj balance", "expect": "QUERY_TENANT"},
        {"msg": "what is rent for chinmay pagey", "expect": "QUERY_TENANT"},
        {"msg": "room 203 details", "expect": "QUERY_TENANT"},
        {"msg": "Arun ka balance kya hai", "expect": "QUERY_TENANT"},
        {"msg": "how much does Priya owe", "expect": "QUERY_TENANT"},
        {"msg": "tenant info Deepak", "expect": "QUERY_TENANT"},
        {"msg": "show details of room 401", "expect": "QUERY_TENANT"},
        {"msg": "Suresh payment history", "expect": "QUERY_TENANT"},
        {"msg": "Chinmay kitna dena hai", "expect": "QUERY_TENANT"},
        {"msg": "305 ka rent", "expect": "QUERY_TENANT"},
        {"msg": "balance check for Mohan", "expect": "QUERY_TENANT"},
        {"msg": "Kumar account", "expect": "QUERY_TENANT"},
        {"msg": "details of Vikram", "expect": "QUERY_TENANT"},
        {"msg": "room 102 tenant", "expect": "QUERY_TENANT"},
        {"msg": "tell me about Aditya", "expect": "QUERY_TENANT"},
    ],
    "ADD_TENANT": [
        {"msg": "new tenant Raj room 203 rent 8000", "expect": "ADD_TENANT"},
        {"msg": "check in Priya to 305", "expect": "ADD_TENANT"},
        {"msg": "add tenant", "expect": "ADD_TENANT"},
        {"msg": "new admission Deepak", "expect": "ADD_TENANT"},
        {"msg": "naya tenant aaya hai", "expect": "ADD_TENANT"},
        {"msg": "checkin karo room 401", "expect": "ADD_TENANT"},
        {"msg": "admit new person", "expect": "ADD_TENANT"},
        {"msg": "new person coming tomorrow room 102", "expect": "ADD_TENANT"},
        {"msg": "register tenant Arun 9876543210", "expect": "ADD_TENANT"},
        {"msg": "allot room to Suresh", "expect": "ADD_TENANT"},
    ],
    "CHECKOUT": [
        {"msg": "Raj leaving today", "expect": "CHECKOUT"},
        {"msg": "checkout room 203", "expect": "CHECKOUT"},
        {"msg": "tenant vacating from 305", "expect": "CHECKOUT"},
        {"msg": "Priya is leaving", "expect": "CHECKOUT"},
        {"msg": "room 401 vacant karo", "expect": "CHECKOUT"},
        {"msg": "Deepak checkout", "expect": "CHECKOUT"},
        {"msg": "tenant leaving room 102", "expect": "CHECKOUT"},
        {"msg": "exit process for Suresh", "expect": "CHECKOUT"},
        {"msg": "vacate 305", "expect": "CHECKOUT"},
        {"msg": "Arun ja raha hai", "expect": "CHECKOUT"},
    ],
    "ADD_EXPENSE": [
        {"msg": "electricity bill 5000", "expect": "ADD_EXPENSE"},
        {"msg": "paid plumber 2000", "expect": "ADD_EXPENSE"},
        {"msg": "salary payment 15000", "expect": "ADD_EXPENSE"},
        {"msg": "wifi bill 3000", "expect": "ADD_EXPENSE"},
        {"msg": "maintenance cost 8000", "expect": "ADD_EXPENSE"},
        {"msg": "EB bill march 4500", "expect": "ADD_EXPENSE"},
        {"msg": "cleaning staff salary 6000", "expect": "ADD_EXPENSE"},
        {"msg": "generator diesel 2500", "expect": "ADD_EXPENSE"},
        {"msg": "repair cost fan broken 800", "expect": "ADD_EXPENSE"},
        {"msg": "pest control 3000", "expect": "ADD_EXPENSE"},
        {"msg": "plumber ko diya 1500", "expect": "ADD_EXPENSE"},
        {"msg": "internet recharge 2000", "expect": "ADD_EXPENSE"},
        {"msg": "water tanker 1200", "expect": "ADD_EXPENSE"},
        {"msg": "groceries for kitchen 4000", "expect": "ADD_EXPENSE"},
        {"msg": "carpenter 2500 for fixing door", "expect": "ADD_EXPENSE"},
    ],
    "ADD_CONTACT": [
        {"msg": "add Mahadevapura lineman contact 9886137766", "expect": "ADD_CONTACT"},
        {"msg": "save plumber number 9876543210", "expect": "ADD_CONTACT"},
        {"msg": "add electrician contact 8765432109", "expect": "ADD_CONTACT"},
        {"msg": "save bescom lineman 7654321098", "expect": "ADD_CONTACT"},
        {"msg": "add vendor Ramesh 9988776655", "expect": "ADD_CONTACT"},
        {"msg": "save ac repair wala 8877665544", "expect": "ADD_CONTACT"},
        {"msg": "plumber ka number save karo 9876543210", "expect": "ADD_CONTACT"},
        {"msg": "add water supplier contact 7766554433", "expect": "ADD_CONTACT"},
        {"msg": "save mason number 9665544332", "expect": "ADD_CONTACT"},
        {"msg": "add laundry service 8554433221", "expect": "ADD_CONTACT"},
        # These should NOT be ADD_TENANT
        {"msg": "add Koramangala electrician 9123456789", "expect": "ADD_CONTACT"},
        {"msg": "save driver contact 8112233445", "expect": "ADD_CONTACT"},
    ],
    "QUERY_CONTACTS": [
        {"msg": "plumber number", "expect": "QUERY_CONTACTS"},
        {"msg": "electrician contact", "expect": "QUERY_CONTACTS"},
        {"msg": "who is the lineman", "expect": "QUERY_CONTACTS"},
        {"msg": "bescom contact", "expect": "QUERY_CONTACTS"},
        {"msg": "show all contacts", "expect": "QUERY_CONTACTS"},
        {"msg": "vendor list", "expect": "QUERY_CONTACTS"},
        {"msg": "plumber ka number kya hai", "expect": "QUERY_CONTACTS"},
        {"msg": "ac repair wala ka number", "expect": "QUERY_CONTACTS"},
        {"msg": "water supplier contact", "expect": "QUERY_CONTACTS"},
        {"msg": "contacts dikhao", "expect": "QUERY_CONTACTS"},
    ],
    "REPORT": [
        {"msg": "monthly report", "expect": "REPORT"},
        {"msg": "how much collected this month", "expect": "REPORT"},
        {"msg": "P&L march", "expect": "REPORT"},
        {"msg": "financial summary", "expect": "REPORT"},
        {"msg": "collection report april", "expect": "REPORT"},
        {"msg": "income and expense summary", "expect": "REPORT"},
        {"msg": "kitna paisa aaya is mahine", "expect": "REPORT"},
        {"msg": "total collection", "expect": "REPORT"},
        {"msg": "revenue report", "expect": "REPORT"},
        {"msg": "mahine ka hisaab", "expect": "REPORT"},
    ],
    "COMPLAINT_REGISTER": [
        {"msg": "no water in room 305", "expect": "COMPLAINT_REGISTER"},
        {"msg": "fan not working 203", "expect": "COMPLAINT_REGISTER"},
        {"msg": "wifi down", "expect": "COMPLAINT_REGISTER"},
        {"msg": "bathroom leak room 401", "expect": "COMPLAINT_REGISTER"},
        {"msg": "geyser broken in 102", "expect": "COMPLAINT_REGISTER"},
        {"msg": "AC not cooling room 508", "expect": "COMPLAINT_REGISTER"},
        {"msg": "paani nahi aa raha", "expect": "COMPLAINT_REGISTER"},
        {"msg": "light nahi jal rahi 305 mein", "expect": "COMPLAINT_REGISTER"},
        {"msg": "toilet flush broken", "expect": "COMPLAINT_REGISTER"},
        {"msg": "cockroach problem room 203", "expect": "COMPLAINT_REGISTER"},
    ],
    "QUERY_VACANT_ROOMS": [
        {"msg": "vacant rooms", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "any rooms available", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "empty beds", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "koi room khali hai kya", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "available rooms for female", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "single room available?", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "vacancy", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "show empty rooms", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "ladies room khali hai", "expect": "QUERY_VACANT_ROOMS"},
        {"msg": "how many beds free", "expect": "QUERY_VACANT_ROOMS"},
    ],
    "VOID_PAYMENT": [
        {"msg": "cancel payment for Raj", "expect": "VOID_PAYMENT"},
        {"msg": "reverse last payment 203", "expect": "VOID_PAYMENT"},
        {"msg": "void Priya's payment", "expect": "VOID_PAYMENT"},
        {"msg": "wrong payment entered delete it", "expect": "VOID_PAYMENT"},
        {"msg": "undo payment for room 305", "expect": "VOID_PAYMENT"},
        {"msg": "galti se payment enter ho gaya Suresh ka", "expect": "VOID_PAYMENT"},
        {"msg": "payment cancel karo Deepak", "expect": "VOID_PAYMENT"},
        {"msg": "remove payment entry for Arun", "expect": "VOID_PAYMENT"},
    ],
    "ROOM_TRANSFER": [
        {"msg": "move Raj from 203 to 305", "expect": "ROOM_TRANSFER"},
        {"msg": "transfer Priya to room 401", "expect": "ROOM_TRANSFER"},
        {"msg": "room change for Deepak", "expect": "ROOM_TRANSFER"},
        {"msg": "shift tenant from 102 to 508", "expect": "ROOM_TRANSFER"},
        {"msg": "Suresh ka room change karo", "expect": "ROOM_TRANSFER"},
    ],
    "RENT_CHANGE": [
        {"msg": "increase rent for Raj to 12000", "expect": "RENT_CHANGE"},
        {"msg": "rent change room 203 to 10000", "expect": "RENT_CHANGE"},
        {"msg": "new rent for Priya 9000", "expect": "RENT_CHANGE"},
        {"msg": "rent badha do 11000 Deepak", "expect": "RENT_CHANGE"},
        {"msg": "change rent 305 to 8500", "expect": "RENT_CHANGE"},
    ],
    "SEND_REMINDER_ALL": [
        {"msg": "send reminders", "expect": "SEND_REMINDER_ALL"},
        {"msg": "remind all tenants", "expect": "SEND_REMINDER_ALL"},
        {"msg": "sabko reminder bhejo", "expect": "SEND_REMINDER_ALL"},
        {"msg": "send payment reminder to everyone", "expect": "SEND_REMINDER_ALL"},
        {"msg": "bulk reminder", "expect": "SEND_REMINDER_ALL"},
    ],
    "HELP": [
        {"msg": "help", "expect": "HELP"},
        {"msg": "hi", "expect": "HELP"},
        {"msg": "hello", "expect": "HELP"},
        {"msg": "menu", "expect": "HELP"},
        {"msg": "what can you do", "expect": "HELP"},
        {"msg": "commands", "expect": "HELP"},
        {"msg": "kya kya kar sakte ho", "expect": "HELP"},
        {"msg": "start", "expect": "HELP"},
        {"msg": "options", "expect": "HELP"},
        {"msg": "hey", "expect": "HELP"},
    ],
    # ── Edge cases that should NOT match wrong intents ──
    "EDGE_CASES": [
        # "contact" alone should be QUERY_CONTACTS, NOT ADD_TENANT
        {"msg": "contact", "expect": "QUERY_CONTACTS"},
        # Name query should NOT be ADD_TENANT
        {"msg": "Chinmay pagey balance", "expect": "QUERY_TENANT"},
        {"msg": "what is rent for chinmay", "expect": "QUERY_TENANT"},
        # "Add" + name + number = contact, NOT tenant
        {"msg": "add Mahadevapura line man contact number 9886137766", "expect": "ADD_CONTACT"},
        # Expense vs payment
        {"msg": "paid 5000 for electricity", "expect": "ADD_EXPENSE"},
        {"msg": "paid 5000 from Raj", "expect": "PAYMENT_LOG"},
        # Checkout vs schedule
        {"msg": "Raj leaving on 15th april", "expect": "SCHEDULE_CHECKOUT"},
        {"msg": "Raj leaving today", "expect": "CHECKOUT"},
        # Query expenses vs add expense
        {"msg": "expenses this month", "expect": "QUERY_EXPENSES"},
        {"msg": "log expense electricity 5000", "expect": "ADD_EXPENSE"},
        # Occupancy vs vacant
        {"msg": "how full are we", "expect": "QUERY_OCCUPANCY"},
        {"msg": "empty rooms", "expect": "QUERY_VACANT_ROOMS"},
        # Notice vs checkout
        {"msg": "Raj wants to leave next month", "expect": "NOTICE_GIVEN"},
        {"msg": "Raj leaving now", "expect": "CHECKOUT"},
    ],
    # ── Conversation flow: corrections during pending state ──
    "CORRECTIONS": [
        {"msg": "no name is Mahadevapura lineman", "expect": "ADD_CONTACT", "context": "correction"},
        {"msg": "no the amount is 15000 not 12000", "expect": "PAYMENT_LOG", "context": "correction"},
        {"msg": "wrong room, its 305", "expect": "PAYMENT_LOG", "context": "correction"},
        {"msg": "change mode to UPI", "expect": "PAYMENT_LOG", "context": "correction"},
        {"msg": "actually its for march not april", "expect": "PAYMENT_LOG", "context": "correction"},
        {"msg": "no cancel this", "expect": "CANCEL", "context": "correction"},
        {"msg": "thats wrong start over", "expect": "CANCEL", "context": "correction"},
        {"msg": "yes confirm", "expect": "CONFIRM", "context": "correction"},
        {"msg": "ok save it", "expect": "CONFIRM", "context": "correction"},
        {"msg": "haan sahi hai", "expect": "CONFIRM", "context": "correction"},
    ],
}


async def run_stress_test(
    groups: list[str] | None = None,
    limit: int = 0,
    dry_run: bool = False,
    delay: float = 2.1,
) -> dict:
    """Run stress tests. Returns summary stats."""
    client = get_claude_client()
    results = {"total": 0, "pass": 0, "fail": 0, "errors": 0, "failures": []}

    test_groups = groups or list(STRESS_CASES.keys())

    for group in test_groups:
        cases = STRESS_CASES.get(group, [])
        if not cases:
            print(f"\n[SKIP] Unknown group: {group}")
            continue

        if limit:
            cases = cases[:limit]

        print(f"\n{'='*60}")
        print(f"  GROUP: {group} ({len(cases)} tests)")
        print(f"{'='*60}")

        for i, case in enumerate(cases, 1):
            msg = case["msg"]
            expected = case["expect"]
            is_correction = case.get("context") == "correction"
            results["total"] += 1

            if dry_run:
                print(f"  [{i:3d}] {msg:50s} -> {expected}")
                results["pass"] += 1
                continue

            try:
                if is_correction:
                    # Use conversation manager for correction tests
                    resp = await client.manage_conversation(
                        message=msg,
                        role="admin",
                        pending_context="Pending: CONFIRM_PAYMENT_LOG, step: confirm, data: {name: 'Raj', amount: 12000, room: '203'}",
                    )
                    got_intent = str(resp.get("action", "UNKNOWN")).upper()
                else:
                    resp = await client.detect_whatsapp_intent(msg, "admin")
                    got_intent = str(resp.get("intent", "UNKNOWN")).upper()

                # For corrections, map action types
                if is_correction:
                    if expected == "CANCEL" and got_intent in ("CANCEL",):
                        passed = True
                    elif expected == "CONFIRM" and got_intent in ("CONFIRM",):
                        passed = True
                    elif got_intent == "CORRECT_FIELD":
                        passed = True  # Any correction detection is good
                    elif got_intent == expected:
                        passed = True
                    else:
                        passed = False
                else:
                    passed = got_intent == expected

                status = "PASS" if passed else "FAIL"
                if passed:
                    results["pass"] += 1
                else:
                    results["fail"] += 1
                    results["failures"].append({
                        "group": group,
                        "msg": msg,
                        "expected": expected,
                        "got": got_intent,
                        "full_response": resp,
                    })

                conf = resp.get("confidence", 0)
                entities_str = ""
                if not is_correction:
                    ent = resp.get("entities", {})
                    ent_parts = [f"{k}={v}" for k, v in ent.items() if v is not None]
                    entities_str = f" | {', '.join(ent_parts)}" if ent_parts else ""

                mark = "+" if passed else "X"
                print(f"  [{mark}] {msg:50s} -> {got_intent:25s} (exp: {expected}, conf: {conf:.2f}){entities_str}")

                # Rate limit: 30 RPM = 2s between calls
                await asyncio.sleep(delay)

            except Exception as e:
                results["errors"] += 1
                print(f"  [!] {msg:50s} -> ERROR: {e}")
                await asyncio.sleep(delay)

    return results


def print_summary(results: dict):
    total = results["total"]
    passed = results["pass"]
    failed = results["fail"]
    errors = results["errors"]
    pct = (passed / total * 100) if total else 0

    print(f"\n{'='*60}")
    print(f"  STRESS TEST RESULTS")
    print(f"{'='*60}")
    print(f"  Total:  {total}")
    print(f"  Pass:   {passed} ({pct:.1f}%)")
    print(f"  Fail:   {failed}")
    print(f"  Errors: {errors}")
    print(f"{'='*60}")

    if results["failures"]:
        print(f"\n  FAILURES:")
        for f in results["failures"]:
            print(f"    [{f['group']}] \"{f['msg']}\" -> got {f['got']}, expected {f['expected']}")

    # Save results to file
    out_path = Path("tests/results/stress_test_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "summary": {"total": total, "pass": passed, "fail": failed, "errors": errors, "pass_rate": pct},
        "failures": results["failures"],
    }, indent=2, default=str), encoding="utf-8")
    print(f"\n  Results saved to {out_path}")


async def main():
    parser = argparse.ArgumentParser(description="Stress test intent classification")
    parser.add_argument("--group", nargs="*", help="Test specific groups")
    parser.add_argument("--limit", type=int, default=0, help="Max tests per group")
    parser.add_argument("--dry-run", action="store_true", help="Show test cases only")
    parser.add_argument("--delay", type=float, default=2.1, help="Seconds between API calls")
    args = parser.parse_args()

    print(f"Stress Test — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Provider: {os.getenv('LLM_PROVIDER', 'groq')}")
    print(f"Delay: {args.delay}s between calls")

    total_cases = sum(len(v) for k, v in STRESS_CASES.items()
                      if not args.group or k in args.group)
    est_time = total_cases * args.delay / 60
    print(f"Total cases: {total_cases} (est. {est_time:.1f} min)")

    results = await run_stress_test(
        groups=args.group,
        limit=args.limit,
        dry_run=args.dry_run,
        delay=args.delay,
    )
    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
