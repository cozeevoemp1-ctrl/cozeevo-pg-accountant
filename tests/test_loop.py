#!/usr/bin/env python3
"""
Local Loop Tester — PG Accountant WhatsApp Bot
================================================
Simulates WhatsApp webhook payloads against the running FastAPI server,
verifies intent classification and DB state, and logs failures with
suggestions.

Usage:
    python tests/test_loop.py                         # run all 20 tests
    python tests/test_loop.py --id TC001,TC010        # run specific tests
    python tests/test_loop.py --category Maintenance  # filter by category
    python tests/test_loop.py --dry                   # show test plan only

Requirements: START_API.bat must be running before executing this script.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
_PORT            = int(os.getenv("API_PORT", "8000"))
API_URL          = f"http://localhost:{_PORT}/api/whatsapp/process"
_RAW_DB_URL      = os.getenv("DATABASE_URL", "")
# asyncpg wants plain postgresql:// (not +asyncpg)
DB_URL           = _RAW_DB_URL.replace("postgresql+asyncpg://", "postgresql://")

TESTS_DIR        = Path(__file__).parent
TEST_CASES_FILE  = TESTS_DIR / "test_cases.json"
FAILURES_LOG     = TESTS_DIR / "failures_log.jsonl"

# Confidence threshold (must match chat_api.py)
CONF_THRESHOLD   = 0.85

# ── DB helpers ────────────────────────────────────────────────────────────────

async def _ensure_audit_table(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS testing_audit (
            id               SERIAL PRIMARY KEY,
            test_id          VARCHAR(20)   NOT NULL,
            category         VARCHAR(100),
            phone            VARCHAR(30),
            message          TEXT,
            expected_intent  VARCHAR(60),
            actual_intent    VARCHAR(60),
            min_confidence   FLOAT,
            actual_confidence FLOAT,
            db_verified      BOOLEAN,
            failure_reason   TEXT,
            suggestion       TEXT,
            tested_at        TIMESTAMPTZ DEFAULT now()
        )
    """)


async def _log_to_audit(conn: asyncpg.Connection, result: dict, tc: dict) -> None:
    await conn.execute(
        """
        INSERT INTO testing_audit
            (test_id, category, phone, message, expected_intent, actual_intent,
             min_confidence, actual_confidence, db_verified, failure_reason, suggestion)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        """,
        result["id"],
        result.get("category", ""),
        tc.get("phone", ""),
        tc.get("message", "")[:500],
        tc.get("expected_intent", ""),
        result.get("actual_intent") or "ERROR",
        float(tc.get("min_confidence") or 0.0),
        float(result.get("actual_confidence") or 0.0),
        bool(result.get("db_verified", False)),
        result.get("failure_reason", ""),
        result.get("suggestion", ""),
    )


# ── DB verification ───────────────────────────────────────────────────────────

async def _verify_db(conn: asyncpg.Connection, tc: dict, api_response: dict) -> tuple[bool, str]:
    """
    Verify DB state after a test run.
    Returns (passed: bool, note: str).
    """
    spec = tc.get("db_verify")
    if not spec:
        return True, "no DB check"

    check = spec.get("check")

    # ── reply_contains: check bot's reply text ────────────────────────────
    if check == "reply_contains":
        reply_text = api_response.get("reply", "")
        keywords = spec.get("keywords", [])
        if not keywords:
            return True, "no keywords specified — skipped"
        # At least ONE keyword must appear (OR logic — not all required)
        found = [k for k in keywords if k.lower() in reply_text.lower()]
        if not found:
            return False, f"reply missing all keywords {keywords!r}"
        return True, f"reply contains {found}"

    # ── payment_created: latest payment row matches expected amount ───────
    if check == "payment_created":
        row = await conn.fetchrow(
            "SELECT amount FROM payments ORDER BY created_at DESC LIMIT 1"
        )
        if not row:
            return False, "no payment row found"
        expected_amount = spec.get("amount")
        if expected_amount and abs(float(row["amount"]) - float(expected_amount)) > 0.01:
            return False, f"amount mismatch: got {row['amount']}, expected {expected_amount}"
        return True, f"payment row created: Rs.{row['amount']}"

    # ── pending_action_created: pending_actions row for given intent ──────
    if check == "pending_action_created":
        intent_filter = spec.get("intent", "COMPLAINT_REGISTER")
        row = await conn.fetchrow(
            "SELECT id FROM pending_actions WHERE intent = $1 "
            "AND resolved = FALSE ORDER BY created_at DESC LIMIT 1",
            intent_filter,
        )
        if not row:
            return False, f"no pending_action with intent={intent_filter}"
        return True, f"pending_action created (id={row['id']})"

    # ── rent_schedule_updated: verify latest rent_schedule change ─────────
    if check == "rent_schedule_updated":
        row = await conn.fetchrow(
            "SELECT rent_due, period_month FROM rent_schedule ORDER BY id DESC LIMIT 1"
        )
        if not row:
            return False, "no rent_schedule row found"
        return True, f"rent_schedule row: {row['period_month']} Rs.{row['rent_due']}"

    return True, f"unknown check type '{check}' — skipped"


# ── Suggestion engine ─────────────────────────────────────────────────────────

def _generate_suggestion(tc: dict, actual_intent: str, actual_conf: float) -> str:
    expected = tc["expected_intent"]
    msg = tc["message"]

    if actual_intent == "ERROR":
        return "Server error — check FastAPI logs (START_API.bat terminal)"

    if actual_intent in ("SYSTEM_HARD_UNKNOWN",) and tc.get("should_be_hard_unknown"):
        return "No suggestion — correct low-confidence routing"

    if actual_intent == "UNKNOWN" and expected not in ("UNKNOWN", "SYSTEM_HARD_UNKNOWN"):
        return (
            f"Rule gap: '{msg[:50]}' matched nothing. "
            f"Add a regex for '{expected}' covering this phrasing in intent_detector.py → _OWNER_RULES or _TENANT_RULES."
        )

    if actual_intent != expected:
        return (
            f"Wrong intent: got '{actual_intent}', expected '{expected}'. "
            f"Check rule priority in intent_detector.py — '{actual_intent}' pattern may be too broad and fire before '{expected}'."
        )

    min_conf = float(tc.get("min_confidence") or 0.0)
    if min_conf > 0 and actual_conf < min_conf:
        return (
            f"Confidence too low ({actual_conf:.2f} < {min_conf:.2f}). "
            f"Consider raising the confidence constant for '{expected}' rule in intent_detector.py, "
            f"or tighten the regex so it only fires on high-signal phrases."
        )

    return "No suggestion — test passed."


# ── Single test runner ────────────────────────────────────────────────────────

async def _run_test(
    client: httpx.AsyncClient,
    conn: asyncpg.Connection,
    tc: dict,
) -> dict:
    result: dict = {
        "id":               tc["id"],
        "category":         tc.get("category", ""),
        "message":          tc["message"],
        "expected_intent":  tc["expected_intent"],
        "actual_intent":    "ERROR",
        "actual_confidence": 0.0,
        "reply_preview":    "",
        "db_verified":      False,
        "db_note":          "",
        "passed":           False,
        "failure_reason":   "",
        "suggestion":       "",
    }

    # ── POST to FastAPI ───────────────────────────────────────────────────
    try:
        resp = await client.post(
            API_URL,
            json={
                "phone":      tc["phone"],
                "message":    tc["message"],
                "message_id": f"test_{tc['id']}_{int(datetime.utcnow().timestamp())}",
            },
            timeout=20.0,
        )
    except httpx.ConnectError:
        result["failure_reason"] = (
            f"Cannot connect to FastAPI at {API_URL}. "
            "Run START_API.bat first, wait for 'Uvicorn running' message."
        )
        result["suggestion"] = "Start the API server before running tests."
        return result
    except Exception as exc:
        result["failure_reason"] = f"HTTP request failed: {exc}"
        result["suggestion"]     = "Check network / server health."
        return result

    if resp.status_code != 200:
        result["failure_reason"] = f"HTTP {resp.status_code}: {resp.text[:300]}"
        result["suggestion"]     = "Server returned an error — check FastAPI logs."
        return result

    data = resp.json()
    result["actual_intent"]     = data.get("intent", "UNKNOWN")
    result["actual_confidence"] = float(data.get("confidence", 0.0))
    result["reply_preview"]     = (data.get("reply") or "")[:80]

    # ── Determine pass/fail ───────────────────────────────────────────────
    expected = tc["expected_intent"]
    min_conf = float(tc.get("min_confidence") or 0.0)

    # Special: tests that expect low-confidence routing
    if tc.get("should_be_hard_unknown"):
        intent_ok = result["actual_intent"] in ("SYSTEM_HARD_UNKNOWN", "UNKNOWN")
        conf_ok   = True
    else:
        intent_ok = result["actual_intent"] == expected
        conf_ok   = (result["actual_confidence"] >= min_conf) if min_conf > 0 else True

    # ── DB verification ───────────────────────────────────────────────────
    db_ok, db_note = await _verify_db(conn, tc, data)
    result["db_verified"] = db_ok
    result["db_note"]     = db_note

    reasons = []
    if not intent_ok:
        reasons.append(
            f"intent: got '{result['actual_intent']}', expected '{expected}'"
        )
    if not conf_ok:
        reasons.append(
            f"confidence: got {result['actual_confidence']:.2f}, min {min_conf:.2f}"
        )
    if not db_ok:
        reasons.append(f"DB: {db_note}")

    if reasons:
        result["failure_reason"] = " | ".join(reasons)
        result["suggestion"] = _generate_suggestion(
            tc, result["actual_intent"], result["actual_confidence"]
        )
    else:
        result["passed"]     = True
        result["suggestion"] = "passed"

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> int:
    # Parse CLI args
    args = sys.argv[1:]
    filter_ids: set[str] | None = None
    filter_cat: str | None      = None
    dry_run                     = False

    i = 0
    while i < len(args):
        if args[i] == "--id" and i + 1 < len(args):
            filter_ids = set(args[i + 1].split(","))
            i += 2
        elif args[i] == "--category" and i + 1 < len(args):
            filter_cat = args[i + 1].lower()
            i += 2
        elif args[i] == "--dry":
            dry_run = True
            i += 1
        else:
            i += 1

    # Load test cases (skip entries with "_comment" or "_skip")
    all_cases: list[dict] = [
        tc for tc in json.loads(TEST_CASES_FILE.read_text(encoding="utf-8"))
        if "_comment" not in tc and not tc.get("_skip")
    ]
    if filter_ids:
        all_cases = [tc for tc in all_cases if tc["id"] in filter_ids]
    if filter_cat:
        all_cases = [tc for tc in all_cases if filter_cat in tc.get("category", "").lower()]

    print(f"\n{'='*65}")
    print(f"  PG ACCOUNTANT  —  LOCAL LOOP TESTER")
    print(f"  {len(all_cases)} test(s) | {datetime.now().strftime('%d %b %Y %H:%M:%S')}")
    print(f"  Target: {API_URL}")
    print(f"{'='*65}\n")

    if dry_run:
        for tc in all_cases:
            print(f"  [{tc['id']}] {tc.get('category',''):<30} {tc['message'][:50]}")
        print()
        return 0

    # Connect to DB
    try:
        conn: asyncpg.Connection = await asyncpg.connect(DB_URL)
    except Exception as exc:
        print(f"  [ERROR] Cannot connect to Supabase DB: {exc}")
        print("  DB verification will be skipped.\n")
        conn = None  # type: ignore[assignment]

    if conn:
        await _ensure_audit_table(conn)

    results: list[dict] = []
    passed: int = 0
    failed: int = 0

    async with httpx.AsyncClient() as client:
        for tc in all_cases:
            label = f"[{tc['id']}] {tc.get('category',''):<28}"
            msg_preview = tc["message"][:42]
            print(f"  {label} {msg_preview:<42}", end=" → ", flush=True)

            result = await _run_test(client, conn, tc)
            results.append(result)

            if result["passed"]:
                passed = passed + 1
                conf_str = f"conf={result['actual_confidence']:.2f}" if result["actual_confidence"] else ""
                print(f"PASS  {result['actual_intent']} {conf_str}")
            else:
                failed = failed + 1
                print(f"FAIL  {result['actual_intent']}")
                print(f"         Reason:     {result['failure_reason']}")
                if result["suggestion"] not in ("passed", ""):
                    print(f"         Suggestion: {result['suggestion']}")
                if result["reply_preview"]:
                    print(f"         Bot reply:  {result['reply_preview']!r}")

                # Append to JSONL failure log
                with FAILURES_LOG.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "timestamp":       datetime.utcnow().isoformat(),
                        "id":              result["id"],
                        "category":        result["category"],
                        "message":         result["message"],
                        "expected_intent": result["expected_intent"],
                        "actual_intent":   result["actual_intent"],
                        "confidence":      result["actual_confidence"],
                        "failure_reason":  result["failure_reason"],
                        "suggestion":      result["suggestion"],
                    }, ensure_ascii=False) + "\n")

                # Log to DB audit table
                if conn:
                    try:
                        await _log_to_audit(conn, result, tc)
                    except Exception as exc:
                        print(f"         [audit log error: {exc}]")

    if conn:
        await conn.close()

    # Summary
    print(f"\n{'='*65}")
    print(f"  RESULTS:  {passed}/{len(results)} passed  |  {failed} failed")

    if failed:
        print(f"\n  Failed tests:")
        for r in results:
            if not r["passed"]:
                print(f"    [{r['id']}] {r['category']}")
                print(f"         {r['failure_reason'][:75]}")
        print(f"\n  Failure log: {FAILURES_LOG}")
        print(f"  DB audit:    testing_audit table (Supabase)")
    else:
        print("\n  All tests passed!")

    print(f"{'='*65}\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
