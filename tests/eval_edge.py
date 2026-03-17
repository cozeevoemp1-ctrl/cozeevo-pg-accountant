"""
tests/eval_edge.py
==================
Edge-case test suite runner (245 cases across 18 categories).

Usage:
    python tests/eval_edge.py                            # all 245 cases
    python tests/eval_edge.py --category tenant_lifecycle
    python tests/eval_edge.py --category financial_prorate
    python tests/eval_edge.py --category security_firewall
    python tests/eval_edge.py --id E201
    python tests/eval_edge.py --check-leaks              # leak-only mode
    python tests/eval_edge.py --verbose                  # show all turn details

Prerequisites:
    1. START_API.bat running (FastAPI on port 8000)
    2. TEST_MODE=1 in .env
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

API_PORT  = int(os.getenv("API_PORT", "8000"))
API_URL   = f"http://localhost:{API_PORT}/api/whatsapp/process"
CLEAR_URL = f"http://localhost:{API_PORT}/api/test/clear-pending"
EDGE_FILE = Path(__file__).parent / "edge_test_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"

PHONES = {
    "admin":      os.getenv("ADMIN_PHONE",      "+917845952289"),
    "power_user": os.getenv("POWER_USER_PHONE", "+917358341775"),
    "key_user":   os.getenv("KEY_USER_PHONE",   "+919000000099"),
    "tenant":     os.getenv("TENANT_PHONE",     "+919000000088"),
    "lead":       os.getenv("LEAD_PHONE",       "+919000000001"),
}

REQUEST_TIMEOUT     = 12
INTER_TURN_DELAY_MS = 200

LEAK_KEYWORDS = [
    "traceback", "exception", "File \"", "line ", "error:",
    "vps", "seed", "database", "asyncpg", "sqlalchemy",
    "TypeError", "ValueError", "KeyError", "AttributeError",
    "NoneType", "psycopg", "Supabase", "supabase",
]

PASS = "PASS"
FAIL = "FAIL"
LEAK = "LEAK"


# ── Core logic ─────────────────────────────────────────────────────────────────

def _phone(role: str) -> str:
    return PHONES.get(role, PHONES["lead"])


async def _clear_pending(phone: str, client: httpx.AsyncClient) -> None:
    try:
        await client.post(CLEAR_URL, json={"phone": phone}, timeout=5)
    except Exception:
        pass


def _check_turn(turn: dict, response: dict) -> tuple[str, list[str]]:
    failures: list[str] = []
    reply = response.get("reply", "").lower()
    got_intent = response.get("intent", "")

    leaks_found = []
    for kw in LEAK_KEYWORDS:
        if kw.lower() in reply:
            leaks_found.append(kw)
    for kw in turn.get("reply_must_not_contain", []):
        if kw.lower() in reply:
            leaks_found.append(f"[must_not] {kw}")
    if leaks_found:
        failures.append(f"LEAK — found forbidden words: {leaks_found}")
        return LEAK, failures

    expected_intent = turn.get("expected_intent", "")
    if expected_intent:
        _unknown_variants = {"UNKNOWN", "SYSTEM_HARD_UNKNOWN"}
        intent_ok = (got_intent == expected_intent) or (
            expected_intent in _unknown_variants and got_intent in _unknown_variants
        )
        if not intent_ok:
            failures.append(f"intent={got_intent!r} (expected {expected_intent!r})")

    for kw in turn.get("reply_must_contain", []):
        if kw.lower() not in reply:
            failures.append(f"missing keyword: {kw!r}")

    if failures:
        return FAIL, failures
    return PASS, []


async def run_case(
    case: dict,
    client: httpx.AsyncClient,
    verbose: bool = False,
    check_leaks_only: bool = False,
) -> dict:
    case_id   = case["id"]
    case_name = case["name"]
    turns     = case["turns"]
    category  = case.get("category", "unknown")

    first_role = turns[0]["role"] if turns else "admin"
    phone = _phone(first_role)
    await _clear_pending(phone, client)

    turn_results = []
    overall = PASS

    for i, turn in enumerate(turns):
        role  = turn["role"]
        phone = _phone(role)
        msg   = turn["input"]

        try:
            resp = await client.post(
                API_URL,
                json={"phone": phone, "message": msg, "message_id": f"edge-{case_id}-t{i}"},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                turn_results.append({
                    "turn": i + 1, "input": msg,
                    "outcome": FAIL, "reason": [f"HTTP {resp.status_code}"], "reply": "",
                })
                overall = FAIL
                continue
            data = resp.json()
        except Exception as e:
            turn_results.append({
                "turn": i + 1, "input": msg,
                "outcome": FAIL, "reason": [f"Request failed: {e}"], "reply": "",
            })
            overall = FAIL
            continue

        reply = data.get("reply", "")

        if check_leaks_only:
            leaks = [kw for kw in LEAK_KEYWORDS if kw.lower() in reply.lower()]
            also  = [kw for kw in turn.get("reply_must_not_contain", [])
                     if kw.lower() in reply.lower()]
            all_leaks = leaks + also
            outcome = LEAK if all_leaks else PASS
            reason  = [f"LEAK: {all_leaks}"] if all_leaks else []
        else:
            outcome, reason = _check_turn(turn, data)

        if outcome != PASS:
            overall = outcome if overall == PASS else overall

        turn_results.append({
            "turn": i + 1, "input": msg, "role": role,
            "outcome": outcome, "reason": reason,
            "got_intent": data.get("intent", ""),
            "got_confidence": data.get("confidence", 0),
            "reply_snippet": reply[:120],
        })

        if verbose:
            icon = "✓" if outcome == PASS else ("⚡" if outcome == LEAK else "✗")
            print(f"    [{icon}] T{i+1} ({role}): {msg!r}")
            print(f"          intent={data.get('intent')} conf={data.get('confidence', 0):.2f}")
            if outcome != PASS:
                print(f"          FAIL: {reason}")
            print(f"          reply: {reply[:100]!r}")

        await asyncio.sleep(INTER_TURN_DELAY_MS / 1000)

    return {"id": case_id, "name": case_name, "category": category, "outcome": overall, "turns": turn_results}


async def run_all(cases: list[dict], verbose: bool = False, check_leaks_only: bool = False) -> list[dict]:
    results = []
    async with httpx.AsyncClient() as client:
        for i, case in enumerate(cases):
            print(f"  [{i+1:3d}/{len(cases)}] {case['id']} — {case['name'][:55]}", end="")
            result = await run_case(case, client, verbose=verbose, check_leaks_only=check_leaks_only)
            icon = "✓" if result["outcome"] == PASS else ("⚡" if result["outcome"] == LEAK else "✗")
            print(f"  {icon}")
            results.append(result)
    return results


# ── Report ─────────────────────────────────────────────────────────────────────

def print_report(results: list[dict], elapsed: float) -> bool:
    total  = len(results)
    passed = sum(1 for r in results if r["outcome"] == PASS)
    failed = sum(1 for r in results if r["outcome"] == FAIL)
    leaked = sum(1 for r in results if r["outcome"] == LEAK)

    print("\n" + "=" * 65)
    print("  EDGE CASE RESULTS")
    print("=" * 65)
    print(f"  Total cases : {total}")
    print(f"  PASS        : {passed}  ({passed/total*100:.1f}%)")
    print(f"  FAIL        : {failed}")
    print(f"  LEAK        : {leaked}  <- technical info exposed to users!")
    print(f"  Time        : {elapsed:.1f}s")
    print()

    by_cat: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0, "leak": 0, "total": 0})
    for r in results:
        cat = r.get("category", "unknown")
        by_cat[cat]["total"] += 1
        by_cat[cat][r["outcome"].lower()] += 1

    print("  Per category:")
    for cat, counts in sorted(by_cat.items()):
        bar    = f"{counts['pass']}/{counts['total']}"
        status = "OK  " if counts["pass"] == counts["total"] else "FAIL"
        leak_note = f" ({counts['leak']} LEAK)" if counts["leak"] else ""
        print(f"    {status}  {cat:<30s}  {bar}{leak_note}")

    failures = [r for r in results if r["outcome"] != PASS]
    if failures:
        print(f"\n  {'─'*60}")
        print(f"  FAILURES & LEAKS ({len(failures)}):")
        for r in failures:
            icon = "⚡" if r["outcome"] == LEAK else "✗"
            print(f"\n  {icon} {r['id']} [{r['category']}] — {r['name']}")
            for t in r["turns"]:
                if t["outcome"] != PASS:
                    print(f"      Turn {t['turn']}: input={t['input']!r}")
                    print(f"      Got: intent={t.get('got_intent')} conf={t.get('got_confidence', 0):.2f}")
                    for reason in t.get("reason", []):
                        print(f"      Reason: {reason}")
                    print(f"      Reply: {t.get('reply_snippet', '')!r}")

    print()
    if passed == total:
        print("  All edge cases passed.")
    elif leaked > 0:
        print("  TECHNICAL LEAKS DETECTED — block deploy immediately")
    else:
        print(f"  {failed + leaked} cases failing — review and fix")
    print("=" * 65)
    return passed == total


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Artha Edge Case Test Suite")
    parser.add_argument("--category",    help="Run only this category")
    parser.add_argument("--id",          help="Run only this case ID")
    parser.add_argument("--verbose",     action="store_true")
    parser.add_argument("--check-leaks", action="store_true", dest="check_leaks")
    parser.add_argument("--out",         help="Save JSON results to this file")
    args = parser.parse_args()

    if not EDGE_FILE.exists():
        print(f"ERROR: {EDGE_FILE} not found.")
        sys.exit(1)

    with open(EDGE_FILE, encoding="utf-8") as f:
        all_cases: list[dict] = json.load(f)

    cases = all_cases
    if args.category:
        cases = [c for c in cases if c.get("category") == args.category]
        print(f"  Filtered to category '{args.category}': {len(cases)} cases")
    if args.id:
        cases = [c for c in cases if c["id"] == args.id]
        print(f"  Filtered to ID '{args.id}': {len(cases)} cases")

    if not cases:
        print("No matching cases found.")
        sys.exit(1)

    print(f"\nArtha Edge Case Suite — {len(cases)} cases")
    print(f"API: {API_URL}")
    if args.check_leaks:
        print("Mode: LEAK CHECK ONLY")
    print()

    start = time.time()
    results = asyncio.run(run_all(cases, verbose=args.verbose, check_leaks_only=args.check_leaks))
    elapsed = time.time() - start

    all_passed = print_report(results, elapsed)

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = args.out or str(
        RESULTS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_edge_results.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_at":    datetime.now().isoformat(),
            "total":     len(results),
            "passed":    sum(1 for r in results if r["outcome"] == PASS),
            "failed":    sum(1 for r in results if r["outcome"] == FAIL),
            "leaked":    sum(1 for r in results if r["outcome"] == LEAK),
            "elapsed_s": round(elapsed, 2),
            "results":   results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved: {out_path}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
