"""
tests/run_500.py
================
Smart 500-scenario test runner for Cozeevo PG Accountant v1.4.0.

Executes all scenarios against the running FastAPI server and produces
a full assessment report with per-worker, per-intent scorecards and
go-live readiness verdict.

Usage:
    python tests/run_500.py                          # all 500 scenarios
    python tests/run_500.py --worker AccountWorker   # one worker only
    python tests/run_500.py --intent PAYMENT_LOG     # one intent only
    python tests/run_500.py --tag basic              # tagged subset
    python tests/run_500.py --quick                  # skip edge/flow/stress
    python tests/run_500.py --dry                    # list scenarios, don't run
    python tests/run_500.py --limit 50               # first N scenarios
    python tests/run_500.py --out results.json       # custom output file

Prerequisites:
    1. START_API.bat running   (FastAPI on port 8000)
    2. TEST_MODE=1 in .env     (bypasses rate limiting — REQUIRED for 500 runs)
    3. generate_scenarios.py already run (creates tests/scenarios_500.json)
       python tests/generate_scenarios.py

Configure phones at the top of this file or via environment variables:
    ADMIN_PHONE, POWER_USER_PHONE, KEY_USER_PHONE, TENANT_PHONE, LEAD_PHONE
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

# Fix Windows cp1252 terminal encoding so ₹ and emoji don't crash the runner
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

API_PORT      = int(os.getenv("API_PORT", "8000"))
API_URL       = f"http://localhost:{API_PORT}/api/whatsapp/process"
SCENARIOS_FILE = Path(__file__).parent / "scenarios_500.json"
RESULTS_DIR    = Path(__file__).parent / "results"

# Phone numbers — override with env vars or edit here
PHONES = {
    "admin":      os.getenv("ADMIN_PHONE",      "+917845952289"),
    "power_user": os.getenv("POWER_USER_PHONE", "+917358341775"),
    "key_user":   os.getenv("KEY_USER_PHONE",   "+919000000099"),  # configure real key_user
    "tenant":     os.getenv("TENANT_PHONE",     "+919000000088"),  # configure real tenant phone
    "lead":       os.getenv("LEAD_PHONE",       "+919000000001"),
}

# Delay between API calls (ms) — increase if hitting rate limits
INTER_CALL_DELAY_MS = 150

# How long to wait for each API call (seconds)
REQUEST_TIMEOUT = 10

# ── Outcome classification ────────────────────────────────────────────────────

PASS    = "PASS"
PARTIAL = "PARTIAL"
FAIL    = "FAIL"
ERROR   = "ERROR"
SKIP    = "SKIP"

# ── Utilities ─────────────────────────────────────────────────────────────────

def _resolve_phone(role: str) -> str:
    return PHONES.get(role, PHONES["lead"])


def _classify(scenario: dict, response: dict) -> tuple[str, str]:
    """Return (outcome, reason)."""
    got_intent  = response.get("intent", "")
    got_conf    = response.get("confidence", 0.0)
    got_reply   = response.get("reply", "")
    exp_intent  = scenario["expected_intent"]
    min_conf    = scenario.get("min_confidence", 0.70)
    keywords    = scenario.get("reply_contains", [])

    # SYSTEM_HARD_UNKNOWN means the bot understood the request but blocked it (role gate).
    # Tests that expect UNKNOWN should pass when the bot hard-blocks the message.
    _unknown_variants = {"UNKNOWN", "SYSTEM_HARD_UNKNOWN"}
    intent_match = (got_intent == exp_intent) or (
        exp_intent in _unknown_variants and got_intent in _unknown_variants
    )

    missing_kw = [kw for kw in keywords if kw.lower() not in got_reply.lower()]

    if not intent_match:
        return FAIL, f"intent={got_intent!r} (expected {exp_intent!r})"

    if got_conf < min_conf and min_conf > 0.0:
        return PARTIAL, f"confidence={got_conf:.2f} < min={min_conf:.2f}"

    if missing_kw:
        return PARTIAL, f"reply missing keywords: {missing_kw}"

    return PASS, "ok"


async def _call_api(client: httpx.AsyncClient, phone: str, message: str,
                    scenario_id: str) -> dict:
    payload = {
        "phone":      phone,
        "message":    message,
        "message_id": f"test_{scenario_id}_{int(time.time()*1000)}",
    }
    try:
        resp = await client.post(API_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}", "reply": "", "intent": "", "confidence": 0}
    except Exception as e:
        return {"error": str(e), "reply": "", "intent": "", "confidence": 0}


# ── Core runner ───────────────────────────────────────────────────────────────

async def _clear_pending_for_phone(phone: str) -> None:
    """Delete pending_actions for a phone so the next scenario starts clean."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as _text
        _url = os.getenv("DATABASE_URL", "")
        if not _url:
            return
        # Normalize to 10-digit (DB stores without country code)
        norm = phone.lstrip("+")
        if norm.startswith("91") and len(norm) == 12:
            norm = norm[2:]
        eng = create_async_engine(_url, echo=False)
        async with eng.begin() as conn:
            await conn.execute(_text("DELETE FROM pending_actions WHERE phone IN (:a, :b)"), {"a": phone, "b": norm})
        await eng.dispose()
    except Exception:
        pass  # non-fatal — test continues


async def run(scenarios: list[dict], delay_ms: int = INTER_CALL_DELAY_MS) -> list[dict]:
    results = []
    total   = len(scenarios)

    # Track which phones have had scenarios run so we can clear state before each
    _seen_phones: set[str] = set()

    async with httpx.AsyncClient() as client:
        for idx, sc in enumerate(scenarios, 1):
            phone   = _resolve_phone(sc["role"])
            message = sc["message"]
            sid     = sc["id"]

            # Clear any pending actions from previous scenario for this phone
            # so multi-step flows don't bleed into the next test
            if phone in _seen_phones:
                await _clear_pending_for_phone(phone)
            _seen_phones.add(phone)

            # Progress indicator
            pct = (idx / total) * 100
            bar_len = 30
            filled  = int(bar_len * idx / total)
            bar     = "#" * filled + "-" * (bar_len - filled)
            print(
                f"\r  [{bar}] {pct:5.1f}%  {idx:3d}/{total}  {sid:<6}  "
                f"{sc['intent']:<25}",
                end="", flush=True
            )

            start   = time.perf_counter()
            resp    = await _call_api(client, phone, message, sid)
            elapsed = time.perf_counter() - start

            if "error" in resp:
                outcome, reason = ERROR, resp["error"]
            else:
                outcome, reason = _classify(sc, resp)

            results.append({
                "id":              sid,
                "worker":          sc["worker"],
                "intent":          sc["intent"],
                "expected_intent": sc["expected_intent"],
                "got_intent":      resp.get("intent", ""),
                "role":            sc["role"],
                "message":         message,
                "outcome":         outcome,
                "reason":          reason,
                "confidence":      resp.get("confidence", 0),
                "reply_snippet":   resp.get("reply", "")[:120],
                "elapsed_ms":      round(elapsed * 1000),
                "tags":            sc.get("tags", []),
            })

            # If response created a pending action (AMBIGUOUS or confirmation flow), clear it so next scenario starts clean
            reply_text = resp.get("reply", "")
            if resp.get("intent") == "AMBIGUOUS" or "Reply *Yes*" in reply_text or "Reply Yes" in reply_text:
                await _clear_pending_for_phone(phone)

            await asyncio.sleep(delay_ms / 1000)

    print()  # newline after progress bar
    return results


# ── Assessment ────────────────────────────────────────────────────────────────

def assess(results: list[dict]) -> dict:
    total  = len(results)
    counts = Counter(r["outcome"] for r in results)

    # By worker
    by_worker: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        by_worker[r["worker"]][r["outcome"]] += 1

    # By intent
    by_intent: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        by_intent[r["expected_intent"]][r["outcome"]] += 1

    # By role
    by_role: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        by_role[r["role"]][r["outcome"]] += 1

    # By tag
    by_tag: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        for tag in r.get("tags", []):
            by_tag[tag][r["outcome"]] += 1

    # Failures detail
    failures = [r for r in results if r["outcome"] in (FAIL, ERROR)]
    partials = [r for r in results if r["outcome"] == PARTIAL]

    # Pass rates
    def pct(c: Counter) -> float:
        t = sum(c.values())
        return (c[PASS] / t * 100) if t else 0.0

    worker_rates = {w: pct(c) for w, c in by_worker.items()}
    intent_rates = {i: pct(c) for i, c in by_intent.items()}

    # Weakest intents (pass rate < 80%)
    weak_intents = sorted(
        [(i, pct(c), sum(c.values())) for i, c in by_intent.items() if pct(c) < 80],
        key=lambda x: x[1]
    )

    # Go-live readiness
    overall_pct = counts[PASS] / total * 100 if total else 0
    core_intents = {
        "PAYMENT_LOG", "QUERY_DUES", "QUERY_TENANT", "REPORT",
        "MY_BALANCE", "ROOM_PRICE", "AVAILABILITY",
    }
    core_results = [r for r in results if r["expected_intent"] in core_intents]
    core_pass    = sum(1 for r in core_results if r["outcome"] == PASS)
    core_pct     = (core_pass / len(core_results) * 100) if core_results else 0

    if overall_pct >= 90 and core_pct >= 95:
        verdict = "[OK]  GO-LIVE READY"
        verdict_detail = "Excellent coverage. Safe to deploy."
    elif overall_pct >= 80 and core_pct >= 90:
        verdict = "[WARN]  SOFT LAUNCH READY"
        verdict_detail = "Core intents solid. Fix weak intents before full marketing."
    elif overall_pct >= 70:
        verdict = "[FIX]  NEEDS WORK"
        verdict_detail = "Several intents failing. Fix before any live traffic."
    else:
        verdict = "[FAIL]  NOT READY"
        verdict_detail = "Too many failures. Review intent_detector.py patterns."

    return {
        "overall_pct":   overall_pct,
        "core_pct":      core_pct,
        "total":         total,
        "counts":        dict(counts),
        "by_worker":     {w: dict(c) for w, c in by_worker.items()},
        "by_intent":     {i: dict(c) for i, c in by_intent.items()},
        "by_role":       {r: dict(c) for r, c in by_role.items()},
        "by_tag":        {t: dict(c) for t, c in by_tag.items()},
        "worker_rates":  worker_rates,
        "intent_rates":  intent_rates,
        "weak_intents":  weak_intents,
        "failures":      failures,
        "partials":      partials,
        "verdict":       verdict,
        "verdict_detail":verdict_detail,
    }


# ── Report printing ───────────────────────────────────────────────────────────

def _bar(pct: float, width: int = 20) -> str:
    filled = int(width * pct / 100)
    return "#" * filled + "-" * (width - filled)


def _outcome_icon(pct: float) -> str:
    if pct >= 90: return "[OK]"
    if pct >= 80: return "[WARN] "
    if pct >= 70: return "[FIX]"
    return "[FAIL]"


def print_report(a: dict):
    SEP = "=" * 80

    print(f"\n{SEP}")
    print(f"  COZEEVO PG ACCOUNTANT — 500-SCENARIO TEST REPORT")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)

    # Overall
    p  = a["overall_pct"]
    c  = a["counts"]
    print(f"\n  OVERALL  {_outcome_icon(p)} {p:.1f}%  ({c.get(PASS,0)} pass · "
          f"{c.get(PARTIAL,0)} partial · {c.get(FAIL,0)} fail · "
          f"{c.get(ERROR,0)} error)  out of {a['total']}")
    print(f"  CORE INTENTS  {a['core_pct']:.1f}%  (payment, dues, balance, report, leads)\n")

    # By worker
    print("  BY WORKER")
    print(f"  {'Worker':<22} {'Pass':>6} {'Partial':>8} {'Fail':>6} {'Error':>6}  {'%':>6}  Bar")
    print("  " + "-" * 74)
    for w in ["AccountWorker", "OwnerWorker", "TenantWorker", "LeadWorker"]:
        wc   = a["by_worker"].get(w, {})
        total_w = sum(wc.values())
        rate = a["worker_rates"].get(w, 0)
        icon = _outcome_icon(rate)
        print(f"  {icon} {w:<20} {wc.get(PASS,0):>6} {wc.get(PARTIAL,0):>8} "
              f"{wc.get(FAIL,0):>6} {wc.get(ERROR,0):>6}  {rate:>5.1f}%  {_bar(rate)}")
    print()

    # By intent (sorted by pass rate)
    print("  BY INTENT  (sorted by pass rate, worst first)")
    print(f"  {'Intent':<28} {'Pass':>5} {'Total':>6}  {'%':>6}  Bar")
    print("  " + "-" * 70)
    sorted_intents = sorted(
        [(i, c_) for i, c_ in a["by_intent"].items()],
        key=lambda x: a["intent_rates"].get(x[0], 0)
    )
    for intent, ic in sorted_intents:
        total_i = sum(ic.values())
        rate    = a["intent_rates"].get(intent, 0)
        icon    = _outcome_icon(rate)
        print(f"  {icon} {intent:<26} {ic.get(PASS,0):>5} {total_i:>6}  {rate:>5.1f}%  {_bar(rate,15)}")
    print()

    # By role
    print("  BY ROLE")
    print(f"  {'Role':<14} {'Pass':>6} {'Total':>6}  {'%':>6}")
    print("  " + "-" * 38)
    for role, rc in a["by_role"].items():
        total_r = sum(rc.values())
        rate    = (rc.get(PASS, 0) / total_r * 100) if total_r else 0
        print(f"  {role:<14} {rc.get(PASS,0):>6} {total_r:>6}  {rate:>5.1f}%")
    print()

    # By category tag
    important_tags = ["basic", "edge", "hinglish", "boundary", "flow", "typo", "ambiguous"]
    print("  BY CATEGORY")
    print(f"  {'Tag':<16} {'Pass':>6} {'Total':>6}  {'%':>6}")
    print("  " + "-" * 38)
    for tag in important_tags:
        tc = a["by_tag"].get(tag, {})
        total_t = sum(tc.values())
        if total_t == 0: continue
        rate = (tc.get(PASS, 0) / total_t * 100)
        icon = _outcome_icon(rate)
        print(f"  {icon} {tag:<14} {tc.get(PASS,0):>6} {total_t:>6}  {rate:>5.1f}%")
    print()

    # Weak intents
    if a["weak_intents"]:
        print("  [WARN]  WEAK INTENTS  (pass rate < 80%)")
        print("  " + "-" * 50)
        for intent, rate, total_i in a["weak_intents"]:
            print(f"  [FAIL] {intent:<28} {rate:>5.1f}%  ({total_i} tests)")
        print()

    # Failed scenarios (first 30)
    failures = a["failures"][:30]
    if failures:
        print(f"  FAILED SCENARIOS  (showing {len(failures)} of {len(a['failures'])})")
        print("  " + "-" * 78)
        print(f"  {'ID':<6}  {'Worker':<16} {'Expected':<25} {'Got':<25} Reason")
        print("  " + "-" * 78)
        for f in failures:
            got = f.get("got_intent", "?")[:24]
            exp = f.get("expected_intent", "?")[:24]
            reason = f.get("reason", "")[:30]
            print(f"  {f['id']:<6}  {f['worker']:<16} {exp:<25} {got:<25} {reason}")
        print()

    # Partial scenarios (first 20)
    partials = a["partials"][:20]
    if partials:
        print(f"  PARTIAL SCENARIOS  (showing {len(partials)} of {len(a['partials'])})")
        print("  " + "-" * 78)
        for p_ in partials:
            print(f"  {p_['id']:<6}  {p_['expected_intent']:<25} conf={p_['confidence']:.2f}  {p_['reason'][:40]}")
        print()

    # Recommendations
    print("  RECOMMENDATIONS")
    print("  " + "-" * 60)
    if not a["weak_intents"] and not failures:
        print("  [PASS] All intents passing well — no changes needed.")
    else:
        recs = _generate_recommendations(a)
        for i, rec in enumerate(recs, 1):
            print(f"  {i}. {rec}")
    print()

    # Go-live verdict
    print("  " + "=" * 60)
    print(f"  GO-LIVE VERDICT: {a['verdict']}")
    print(f"  {a['verdict_detail']}")
    print("  " + "=" * 60 + "\n")


def _generate_recommendations(a: dict) -> list[str]:
    recs = []

    # Intent-specific suggestions
    intent_fixes = {
        "VOID_PAYMENT":     "Add patterns: 'cancel payment X', 'payment X wrong', 'reverse X'",
        "ADD_REFUND":       "Add patterns: 'return deposit X to Y', 'give back X to Y'",
        "RENT_DISCOUNT":    "Add patterns: 'waive X for Y', 'reduce Y rent by X'",
        "CHECKOUT_NOTICE":  "Add patterns: 'I am moving out', 'want to leave', 'giving 1 month notice'",
        "VACATION_NOTICE":  "Add patterns: 'going home N days', 'out of station', 'on leave'",
        "REQUEST_RECEIPT":  "Add patterns: 'send receipt', 'payment proof', 'transaction receipt'",
        "ROOM_STATUS":      "Add patterns: 'is room N occupied', 'room N available', 'status room N'",
        "QUERY_CHECKINS":   "Add patterns: 'who joined', 'new admissions', 'recent checkins'",
        "QUERY_CHECKOUTS":  "Add patterns: 'who left', 'exits this month', 'recent checkouts'",
        "SCHEDULE_CHECKOUT":"Add patterns: 'leaving on DATE', 'checkout on DATE'",
        "LOG_VACATION":     "Add patterns: 'N days leave', 'out of station N days'",
        "NOTICE_GIVEN":     "Add patterns: 'serving notice', 'notice period started'",
        "START_ONBOARDING": "Add patterns: 'begin KYC', 'onboard NAME', 'start registration'",
        "ADD_PARTNER":      "Add patterns: 'give access NUMBER', 'add staff NUMBER'",
        "SEND_REMINDER_ALL":"Add patterns: 'remind all', 'bulk reminder', 'send to all'",
    }

    for intent, rate, _ in a["weak_intents"]:
        fix = intent_fixes.get(intent, f"Review regex patterns for {intent} in intent_detector.py")
        recs.append(f"{intent} ({rate:.0f}%): {fix}")

    # General recommendations
    boundary_tag = a["by_tag"].get("boundary", {})
    if sum(boundary_tag.values()) and boundary_tag.get(FAIL, 0) > 0:
        recs.append("Role boundary tests failing — check gatekeeper.py routing for wrong-role messages")

    hinglish_tag = a["by_tag"].get("hinglish", {})
    if sum(hinglish_tag.values()) and (hinglish_tag.get(FAIL, 0) / max(sum(hinglish_tag.values()), 1)) > 0.3:
        recs.append("Hinglish detection weak — add common Hindi-English mixed patterns to intent_detector.py")

    typo_tag = a["by_tag"].get("typo", {})
    if sum(typo_tag.values()) and (typo_tag.get(FAIL, 0) / max(sum(typo_tag.values()), 1)) > 0.4:
        recs.append("Typo handling weak — consider fuzzy matching or add common misspelling variants")

    flow_tag = a["by_tag"].get("flow", {})
    if sum(flow_tag.values()) and (flow_tag.get(FAIL, 0) / max(sum(flow_tag.values()), 1)) > 0.3:
        recs.append("Multi-step flow starters failing — check START_ONBOARDING / RECORD_CHECKOUT patterns")

    if not recs:
        recs.append("Performance is solid. Continue monitoring after go-live.")

    return recs


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_scenarios(args) -> list[dict]:
    if not SCENARIOS_FILE.exists():
        print("[FAIL]  scenarios_500.json not found.")
        print("    Run first:  python tests/generate_scenarios.py")
        sys.exit(1)

    data = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))

    # Resolve phone placeholders in-place
    phone_map = data.get("meta", {}).get("phones", {})
    # Override from runtime PHONES config
    for role in PHONES:
        phone_map[role] = PHONES[role]

    scenarios = data["scenarios"]

    # Apply filters
    if args.worker:
        scenarios = [s for s in scenarios if s["worker"] == args.worker]
    if args.intent:
        scenarios = [s for s in scenarios if s["intent"] == args.intent]
    if args.tag:
        scenarios = [s for s in scenarios if args.tag in s.get("tags", [])]
    if args.quick:
        skip_tags = {"edge", "flow", "stress", "multistep", "long", "typo"}
        scenarios = [s for s in scenarios if not skip_tags.intersection(s.get("tags", []))]
    if args.limit:
        scenarios = scenarios[:args.limit]

    # Resolve phone placeholders
    for s in scenarios:
        s["phone"] = phone_map.get(s.get("role", "lead"), phone_map.get("lead", "+919000000001"))

    return scenarios


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run 500-scenario test suite for PG Accountant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python tests/run_500.py                          # all 500
          python tests/run_500.py --worker AccountWorker   # financial only
          python tests/run_500.py --tag basic              # basic tests only
          python tests/run_500.py --quick --limit 100     # fast sanity check
          python tests/run_500.py --dry                    # preview only
        """)
    )
    parser.add_argument("--worker",  help="Filter by worker (AccountWorker|OwnerWorker|TenantWorker|LeadWorker)")
    parser.add_argument("--intent",  help="Filter by intent (e.g. PAYMENT_LOG)")
    parser.add_argument("--tag",     help="Filter by tag (basic|edge|hinglish|flow|boundary|typo)")
    parser.add_argument("--quick",   action="store_true", help="Skip edge/flow/stress — run core tests only")
    parser.add_argument("--dry",     action="store_true", help="List scenarios without running")
    parser.add_argument("--limit",   type=int, help="Max scenarios to run")
    parser.add_argument("--delay",   type=int, default=INTER_CALL_DELAY_MS,
                        help=f"Delay between calls in ms (default: {INTER_CALL_DELAY_MS})")
    parser.add_argument("--out",     default="results_500.json", help="Output JSON filename")
    return parser.parse_args()


import textwrap

async def main():
    args = parse_args()
    scenarios = _load_scenarios(args)

    print(f"\n  Cozeevo PG Accountant — Test Runner")
    print(f"  API:       {API_URL}")
    print(f"  Scenarios: {len(scenarios)}")
    print(f"  Phones:    admin={PHONES['admin']}  tenant={PHONES['tenant']}  lead={PHONES['lead']}")
    print(f"  Delay:     {args.delay}ms between calls")

    if args.dry:
        print(f"\n  DRY RUN — listing {len(scenarios)} scenarios:\n")
        print(f"  {'ID':<6}  {'Worker':<18} {'Intent':<25} {'Role':<12} Message")
        print("  " + "-" * 90)
        for s in scenarios:
            print(f"  {s['id']:<6}  {s['worker']:<18} {s['intent']:<25} {s['role']:<12} {s['message'][:40]}")
        return

    # Check API is running
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"http://localhost:{API_PORT}/healthz", timeout=3)
            if r.status_code != 200:
                raise Exception(f"Bad status: {r.status_code}")
        print(f"  API health: [OK] running")
    except Exception as e:
        print(f"\n  [FAIL] API not reachable: {e}")
        print(f"  Make sure START_API.bat is running and TEST_MODE=1 is in .env")
        sys.exit(1)

    # Clear test state (pending_actions, onboarding_sessions, rate_limits) before running
    try:
        import os as _os
        from dotenv import load_dotenv as _load
        _load()
        import importlib, sys as _sys
        # Add project root to path if needed
        _root = Path(__file__).parent.parent
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as _text
        _url = _os.environ.get("DATABASE_URL", "")
        if _url:
            _engine = create_async_engine(_url, echo=False)
            all_phones = list(PHONES.values()) + [p.replace("+91", "") for p in PHONES.values() if p.startswith("+91")]
            # Also clean up test-created tenants (from START_ONBOARDING scenarios using 919900xxxx pattern)
            test_tenant_phones = ["9199000001", "9199000088", "9199000099"]
            all_clean = all_phones + test_tenant_phones
            async with _engine.begin() as conn:
                await conn.execute(_text("DELETE FROM pending_actions WHERE phone = ANY(:p)"), {"p": all_clean})
                await conn.execute(_text("DELETE FROM rate_limit_log WHERE phone = ANY(:p)"), {"p": all_clean})
                # Delete test tenants and their data (cascade order)
                await conn.execute(_text("""DELETE FROM onboarding_sessions WHERE tenant_id IN
                    (SELECT id FROM tenants WHERE phone = ANY(:p))"""), {"p": all_clean})
                await conn.execute(_text("""DELETE FROM rent_schedule WHERE tenancy_id IN
                    (SELECT id FROM tenancies WHERE tenant_id IN
                    (SELECT id FROM tenants WHERE phone = ANY(:p)))"""), {"p": test_tenant_phones})
                await conn.execute(_text("""DELETE FROM tenancies WHERE tenant_id IN
                    (SELECT id FROM tenants WHERE phone = ANY(:p))"""), {"p": test_tenant_phones})
                await conn.execute(_text("DELETE FROM tenants WHERE phone = ANY(:p)"), {"p": test_tenant_phones})
            await _engine.dispose()
            print(f"  State clean: pending_actions, rate_limit_log, onboarding_sessions, test tenants cleared")
    except Exception as _e:
        print(f"  [WARN] Could not clear test state: {_e}")
    print()

    print(f"  Running {len(scenarios)} scenarios...\n")
    t0      = time.perf_counter()
    results = await run(scenarios, delay_ms=args.delay)
    elapsed = time.perf_counter() - t0

    print(f"\n  [TIME]  Completed in {elapsed:.1f}s  ({len(results)} calls, avg {elapsed/len(results)*1000:.0f}ms each)\n")

    a = assess(results)
    print_report(a)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"{ts}_{args.out}"
    out_path.write_text(
        json.dumps({
            "meta": {
                "run_at":    ts,
                "elapsed_s": round(elapsed, 1),
                "total":     len(results),
                "api_url":   API_URL,
            },
            "assessment": {
                k: v for k, v in a.items()
                if k not in ("failures", "partials")
            },
            "failures":  a["failures"],
            "partials":  a["partials"],
            "results":   results,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"  [FILE] Full results saved -> {out_path}\n")


if __name__ == "__main__":
    asyncio.run(main())
