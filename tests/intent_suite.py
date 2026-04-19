"""
tests/intent_suite.py
======================
Run every intent example from the cheat sheet through the local chat harness
and report a pass/fail matrix. Single-turn + multi-turn flows covered.

Usage:
    python tests/intent_suite.py              # run all
    python tests/intent_suite.py --filter pay # only cases with 'pay' in label
    python tests/intent_suite.py --verbose    # show full reply text on each case

A test PASSES if:
  - The bot replied (no unhandled exception), AND
  - The reply does NOT contain any of the failure markers
    ("Sorry, something went wrong", "I don't understand", etc.),
    AND optionally the reply CONTAINS an expected keyword.

A multi-turn test is defined as a list of (message, expected_keyword_in_reply)
tuples. The harness session persists across turns.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

os.makedirs("C:/tmp", exist_ok=True)
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from tests.chat_harness import Session, _boot, POWER_USER_PHONE


# ── Failure markers — any of these in the reply = FAIL ──────────────────────
FAILURE_MARKERS = (
    "Sorry, something went wrong",
    "sorry, something went wrong",
    "I don't understand",
    "i don't understand",
    "Please reply with a number",  # re-prompt after user gave a number = bug
)


@dataclass
class Case:
    label: str
    turns: list[tuple[str, Optional[str]]]  # (message, expected_substring_or_None)
    tags: list[str] = field(default_factory=list)


# ── Single-turn cases (label, message, expected substring) ─────────────────
SINGLE_TURN_CASES: list[Case] = [
    # Reports / queries
    Case("report",               [("report", "Monthly Report")],            ["report"]),
    Case("april report",         [("April report", "April")],               ["report"]),
    Case("dues",                 [("dues", None)],                          ["query"]),
    Case("who owes",             [("who owes", None)],                      ["query"]),
    Case("vacant rooms",         [("vacant rooms", None)],                  ["query"]),
    Case("occupancy",            [("occupancy", None)],                     ["query"]),
    Case("empty beds thor",      [("empty beds in thor", "Empty")],         ["query"]),
    Case("hulk vacant",          [("hulk vacant", None)],                   ["query"]),
    Case("pending refunds",      [("pending refunds", None)],               ["query"]),
    Case("who is leaving",       [("who is leaving this month", None)],     ["query"]),
    Case("wifi password",        [("wifi password", None)],                 ["help"]),
    Case("help / hi",            [("hi", "Type naturally")],                ["help"]),

    # Payment quick-logs
    Case("payment raj cash",     [("Raj paid 14000 cash", None)],           ["payment"]),
    Case("payment raj upi",      [("Raj 14000 upi", None)],                 ["payment"]),
    Case("payment priya gpay",   [("Priya paid 8000 gpay", None)],          ["payment"]),
    Case("payment amount first", [("15000 Raj gpay", None)],                ["payment"]),
    Case("collect rent flow",    [("collect rent", None)],                  ["payment"]),
    Case("record payment flow",  [("record payment", None)],                ["payment"]),

    # Expenses
    Case("expense quick",        [("electricity 4500", None)],              ["expense"]),
    Case("log expense flow",     [("log expense", None)],                   ["expense"]),

    # Operations
    Case("checkout raj",         [("checkout Raj", None)],                  ["checkout"]),
    Case("checkout room",        [("checkout room 301", None)],             ["checkout"]),
    Case("raj gave notice",      [("Raj gave notice", None)],               ["notice"]),
    Case("raj balance",          [("Raj balance", None)],                   ["query"]),
    Case("room 301",             [("room 301", None)],                      ["query"]),
    Case("notes for raj",        [("notes for Raj", None)],                 ["query"]),
    Case("remind unpaid",        [("remind unpaid", None)],                 ["reminder"]),

    # Tenant mgmt
    Case("add tenant flow",      [("add tenant", None)],                    ["tenant"]),
    Case("new tenant flow",      [("new tenant", None)],                    ["tenant"]),
    Case("start onboarding",     [("start onboarding", None)],              ["tenant"]),

    # Rent / room changes
    Case("change rent",          [("change Raj rent to 15000", None)],      ["rent"]),
    Case("transfer room",        [("transfer Raj to 305", None)],           ["transfer"]),
    Case("update checkin",       [("update checkin Raj March 5", None)],    ["update"]),
    Case("update checkout date", [("change checkout date Raj to 15 April", None)], ["update"]),

    # Voids / refunds
    Case("void payment",         [("void payment Raj", None)],              ["void"]),
    Case("add refund",           [("add refund Raj 5000", None)],           ["refund"]),

    # Layout
    Case("floor plan",           [("floor plan", None)],                    ["layout"]),
]

# ── Multi-turn cases ────────────────────────────────────────────────────────
MULTI_TURN_CASES: list[Case] = [
    # The flagship bug: disambiguation "1 or 2" → user replies "1"
    Case("payment disambig 1",   [
        ("room 112 paid rent", None),   # expect bot to either ask 1/2 or log
        ("1", None),                    # user picks first option
    ], ["payment", "disambig"]),
    Case("payment disambig 2",   [
        ("room 112 paid rent", None),
        ("2", None),
    ], ["payment", "disambig"]),

    # Quick payment → disambig (2 Krishnans) → pick 1 → then confirm yes/no
    Case("payment confirm yes",  [
        ("Krishnan paid 20000 cash", None),
        ("1", None),                   # pick Krishnan (Room 101)
        ("yes", None),                 # confirm the payment
    ], ["payment", "confirm"]),
    Case("payment confirm no",   [
        ("Krishnan paid 20000 cash", None),
        ("1", None),
        ("no", None),                  # cancel at confirm step
    ], ["payment", "confirm"]),

    # Collect-rent step-by-step
    Case("collect rent steps",   [
        ("collect rent", None),
        ("Krishnan", None),
        ("10000", None),
        ("0", None),
    ], ["payment", "multistep"]),
]

# ── Framework edge-case tests: things the new router must handle cleanly ───
# These exercise the PAYMENT_LOG / AWAITING_CHOICE handler specifically.
EDGE_CASES: list[Case] = [
    # Cancel at disambiguation
    Case("cancel at disambig",   [
        ("Krishnan paid 20000 cash", None),
        ("cancel", "Cancelled"),
    ], ["edge", "cancel"]),

    # Numeric with trailing punctuation
    Case("choice with period",   [
        ("Krishnan paid 20000 cash", None),
        ("1.", None),
    ], ["edge", "parsing"]),
    Case("choice with paren",    [
        ("Krishnan paid 20000 cash", None),
        ("1)", None),
    ], ["edge", "parsing"]),

    # Out-of-range numeric
    Case("choice out of range",  [
        ("Krishnan paid 20000 cash", None),
        ("9", "number"),             # should reprompt
        ("1", None),                  # recover with valid choice
    ], ["edge", "out-of-range"]),

    # Correction mid-disambiguation (new mode)
    Case("mode correction at disambig", [
        ("Krishnan paid 20000 cash", None),
        ("actually upi", "Updated"),
        ("1", None),
    ], ["edge", "correction"]),

    # Gibberish at disambig — should reprompt not crash
    Case("gibberish at disambig", [
        ("Krishnan paid 20000 cash", None),
        ("xyz??", "number"),
        ("1", None),
    ], ["edge", "gibberish"]),

    # Case-insensitive YES
    Case("confirm uppercase",    [
        ("Krishnan paid 20000 cash", None),
        ("1", None),
        ("YES", None),                # must match despite case
    ], ["edge", "case"]),

    # "skip" at disambig — should reprompt
    Case("skip at disambig",     [
        ("Krishnan paid 20000 cash", None),
        ("skip", "number"),
        ("1", None),
    ], ["edge", "skip"]),
]


# ── Runner ─────────────────────────────────────────────────────────────────
def _passed(reply: str, expected_substring: Optional[str]) -> tuple[bool, str]:
    for marker in FAILURE_MARKERS:
        if marker in reply:
            return False, f"failure-marker: {marker!r}"
    if expected_substring and expected_substring.lower() not in reply.lower():
        # Soft expectation — warn but pass if no failure marker
        return True, f"note: expected {expected_substring!r} missing"
    return True, ""


async def _run_case(case: Case, verbose: bool = False) -> dict:
    s = Session(phone=POWER_USER_PHONE)
    await s.clear_pending()

    result = {"label": case.label, "turns": [], "status": "PASS", "error": None}
    try:
        for i, (msg, expected) in enumerate(case.turns):
            try:
                reply = await s.send(msg)
            except Exception as e:
                result["status"] = "ERROR"
                result["error"] = f"turn {i+1} ({msg!r}): {type(e).__name__}: {e}"
                result["turns"].append({"send": msg, "reply": None, "error": str(e)})
                break
            ok, note = _passed(reply, expected)
            result["turns"].append({"send": msg, "reply": reply[:200], "note": note})
            if not ok:
                result["status"] = "FAIL"
                result["error"] = note
                break
    finally:
        try:
            await s.clear_pending()
        except Exception:
            pass

    if verbose:
        print(f"\n=== {case.label} [{result['status']}] ===")
        for t in result["turns"]:
            print(f"> {t['send']}")
            print(f"< {t.get('reply') or t.get('error')}")
            if t.get("note"):
                print(f"  {t['note']}")
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", type=str, default="", help="Substring filter on labels")
    parser.add_argument("--only-multi", action="store_true")
    parser.add_argument("--only-single", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    await _boot()

    cases = []
    if not args.only_multi:
        cases.extend(SINGLE_TURN_CASES)
    if not args.only_single:
        cases.extend(MULTI_TURN_CASES)
        cases.extend(EDGE_CASES)
    if args.filter:
        cases = [c for c in cases if args.filter.lower() in c.label.lower()]

    print(f"Running {len(cases)} cases...\n")

    results = []
    for c in cases:
        r = await _run_case(c, verbose=args.verbose)
        results.append(r)
        mark = {"PASS": "OK  ", "FAIL": "FAIL", "ERROR": "ERR "}[r["status"]]
        print(f"  [{mark}] {c.label:<30} {r.get('error') or ''}")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errored = sum(1 for r in results if r["status"] == "ERROR")
    print()
    print(f"=== Summary ===")
    print(f"  Total:  {total}")
    print(f"  Pass:   {passed}")
    print(f"  Fail:   {failed}")
    print(f"  Error:  {errored}")
    print(f"  Rate:   {passed/total*100:.0f}%")

    # Detail on failures
    problems = [r for r in results if r["status"] != "PASS"]
    if problems:
        print()
        print("=== Failures ===")
        for r in problems:
            print(f"\n  {r['label']} [{r['status']}]: {r['error']}")
            for t in r["turns"]:
                print(f"    > {t['send']}")
                print(f"    < {(t.get('reply') or t.get('error') or '')[:180]}")


if __name__ == "__main__":
    asyncio.run(main())
