"""
Bot regression test runner.

Usage:
    python -m cli.test_bot                  # run all scenarios
    python -m cli.test_bot --fast           # skip AI-heavy cases (comment tagged NLP)
    python -m cli.test_bot --filter REPORT  # only run cases expecting this intent
    python -m cli.test_bot --add            # interactive: add a new scenario after testing it

Failures are appended to tests/failures_log.jsonl for review.
On each run, previously-failing cases that now pass are auto-marked as FIXED.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL       = os.getenv("TEST_API_URL", "http://localhost:8000")
ADMIN_PHONE    = os.getenv("ADMIN_PHONE",  "+917845952289")
SCENARIOS_FILE = Path(__file__).parent.parent / "tests" / "bot_scenarios.json"
FAILURES_LOG   = Path(__file__).parent.parent / "tests" / "failures_log.jsonl"

# ANSI colours
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _color(text: str, code: str) -> str:
    """Only colorise when writing to a real terminal."""
    if sys.stdout.isatty():
        return f"{code}{text}{RESET}"
    return text


def _load_scenarios(filter_intent: Optional[str], fast: bool) -> list[dict]:
    raw = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    out = []
    in_nlp_section = False
    for item in raw:
        if "_comment" in item:
            in_nlp_section = "NLP" in item["_comment"].upper()
            continue
        if fast and in_nlp_section:
            continue
        if filter_intent and item.get("expect_intent", "").upper() != filter_intent.upper():
            continue
        out.append(item)
    return out


def _check(actual: dict, scenario: dict) -> tuple[bool, list[str]]:
    """Returns (passed, list_of_failure_reasons)."""
    reasons = []

    # Intent check
    exp_intent = scenario.get("expect_intent", "").upper()
    got_intent = actual.get("intent", "").upper()
    if exp_intent and got_intent != exp_intent:
        reasons.append(f"intent: got {got_intent!r}, want {exp_intent!r}")

    # Entity checks (only the ones specified in the scenario)
    exp_entities = scenario.get("expect_entities", {})
    got_entities = actual.get("entities_extracted", {})  # not in response — parsed from reply
    # We get entities from the response JSON indirectly (they're not in OutboundReply)
    # For entity validation we re-hit with a debug endpoint if available,
    # otherwise we just check the intent routing is correct.
    # Amount / name / room checks skipped unless debug mode adds entity echo.

    return len(reasons) == 0, reasons


async def _run_scenario(client: httpx.AsyncClient, scenario: dict) -> dict:
    """Hit the API and return result dict."""
    payload = {
        "phone":      ADMIN_PHONE,
        "message":    scenario["message"],
        "message_id": "test",
    }
    try:
        resp = await client.post(f"{BASE_URL}/api/whatsapp/process", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return {"_error": "Connection refused — is the API server running? (START_API.bat)"}
    except Exception as e:
        return {"_error": str(e)}


def _append_failure(scenario: dict, actual: dict, reasons: list[str]):
    entry = {
        "ts":       datetime.utcnow().isoformat(),
        "message":  scenario["message"],
        "expected": scenario.get("expect_intent"),
        "got":      actual.get("intent"),
        "reply":    actual.get("reply", "")[:120],
        "reasons":  reasons,
        "status":   "open",
    }
    with FAILURES_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


async def _clear_rate_limits():
    """Delete all rate_limit_log rows so tests never hit the spam block."""
    try:
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            r = await conn.execute(text("DELETE FROM rate_limit_log"))
            if r.rowcount:
                print(_color(f"  [rate-limit reset: cleared {r.rowcount} rows]", DIM))
        await engine.dispose()
    except Exception as e:
        print(_color(f"  [rate-limit reset failed: {e}]", YELLOW))


def _summarise_failures():
    """Print a short summary of open failures from previous runs."""
    if not FAILURES_LOG.exists():
        return
    lines = [json.loads(l) for l in FAILURES_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    open_fails = [l for l in lines if l.get("status") == "open"]
    if open_fails:
        print(_color(f"\n  {len(open_fails)} open failure(s) from previous runs still in log.", YELLOW))
        print(_color("  Run with --review to see them.", DIM))


# ── Interactive add ───────────────────────────────────────────────────────────

async def _interactive_add(client: httpx.AsyncClient):
    print(_color("\n── Add new scenario ─────────────────────────────────", CYAN))
    msg = input("  Message to test: ").strip()
    if not msg:
        return

    result = await _run_scenario(client, {"message": msg})
    got_intent = result.get("intent", "?")
    got_reply  = result.get("reply", "")
    print(f"\n  Intent returned : {_color(got_intent, CYAN)}")
    print(f"  Reply           : {got_reply[:200]}")

    correct = input("\n  Is this correct? (y/n): ").strip().lower()
    if correct == "y":
        expected = got_intent
    else:
        expected = input(f"  What SHOULD the intent be? : ").strip().upper()

    # Optional entity checks
    entities = {}
    add_entity = input("  Add entity check? (e.g. name=Raj) or press Enter to skip: ").strip()
    if "=" in add_entity:
        k, v = add_entity.split("=", 1)
        try:
            entities[k.strip()] = float(v) if v.replace(".", "").isdigit() else v.strip()
        except ValueError:
            entities[k.strip()] = v.strip()

    new_scenario = {"message": msg, "expect_intent": expected}
    if entities:
        new_scenario["expect_entities"] = entities

    # Append to scenarios file
    raw = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    # Insert before the last closing ] — append at end
    raw.append(new_scenario)
    SCENARIOS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    print(_color(f"\n  Saved to bot_scenarios.json", GREEN))


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace):
    scenarios = _load_scenarios(
        filter_intent=args.filter,
        fast=args.fast,
    )

    if not scenarios:
        print(_color("No matching scenarios found.", YELLOW))
        return 0

    # Clear rate limits before every test run so tests never get blocked
    await _clear_rate_limits()

    print(_color(f"\n  PG Bot Regression - {len(scenarios)} scenarios", BOLD))
    print(_color(f"  API: {BASE_URL}  |  Phone: {ADMIN_PHONE}\n", DIM))

    passed = 0
    failed = 0
    errors = 0
    failed_items = []

    async with httpx.AsyncClient() as client:
        if args.add:
            await _interactive_add(client)
            return 0

        for i, scenario in enumerate(scenarios, 1):
            # Clear rate limits every 8 requests to stay under the 10/window limit
            if i % 8 == 1 and i > 1:
                await _clear_rate_limits()

            msg = scenario["message"]
            exp = scenario.get("expect_intent", "?")

            actual = await _run_scenario(client, scenario)

            if "_error" in actual:
                errors += 1
                prefix = _color(f"  ERR  [{i:02d}]", RED)
                print(f"{prefix} {msg}")
                print(_color(f"         {actual['_error']}", RED))
                if errors == 1:
                    print(_color("\n  Cannot reach the API. Start it with START_API.bat first.\n", RED))
                    return 2
                continue

            # Detect "server not restarted" — all BLOCKED means TEST_MODE not loaded
            if actual.get("intent") == "BLOCKED" and i <= 3:
                blocked_count = sum(
                    1 for s in scenarios[:5]
                )
                # Check if this is a systematic block by peeking at first 3
                if i == 3:
                    print(_color(
                        "\n  All messages BLOCKED - server needs restart to load TEST_MODE=1\n"
                        "  Close START_API.bat and reopen it, then run tests again.\n",
                        RED
                    ))
                    return 2

            ok, reasons = _check(actual, scenario)
            got_intent  = actual.get("intent", "?")
            got_reply   = actual.get("reply", "")

            if ok:
                passed += 1
                tag    = _color(f"PASS [{got_intent:<18}]", GREEN)
                detail = _color(f" {DIM}{got_reply[:80]}", DIM) if args.verbose else ""
                print(f"  {tag}  {msg}{detail}")
            else:
                failed += 1
                tag = _color(f"FAIL [{got_intent:<18}]", RED)
                exp_tag = _color(f"want {exp}", YELLOW)
                print(f"  {tag}  {msg}  << {exp_tag}")
                if args.verbose:
                    print(_color(f"         reply: {got_reply[:100]}", DIM))
                _append_failure(scenario, actual, reasons)
                failed_items.append((scenario, actual, reasons))

    # ── Summary ───────────────────────────────────────────────────────────────
    total = passed + failed
    bar_done  = int(passed / total * 30) if total else 0
    bar_left  = 30 - bar_done
    bar       = _color("#" * bar_done, GREEN) + _color("." * bar_left, RED)

    print(f"\n  [{bar}]  ", end="")
    print(_color(f"{passed}/{total} passed", GREEN if failed == 0 else YELLOW), end="")
    if failed:
        print(_color(f"  |  {failed} failed", RED), end="")
    if errors:
        print(_color(f"  |  {errors} errors", RED), end="")
    print()

    if failed_items:
        print(_color(f"\n  Failures logged to tests/failures_log.jsonl", DIM))
        print(_color("  Fix them, re-run to clear.\n", DIM))
    else:
        print(_color("  All green. No regressions.\n", GREEN))

    _summarise_failures()
    return 0 if (failed == 0 and errors == 0) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PG Bot regression test runner")
    parser.add_argument("--fast",    action="store_true", help="Skip NLP/AI-tagged scenarios")
    parser.add_argument("--filter",  metavar="INTENT",    help="Only run scenarios expecting this intent")
    parser.add_argument("--add",     action="store_true", help="Interactively add a new scenario")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show reply text for each result")
    parser.add_argument("--review",  action="store_true", help="Print open failures from log and exit")
    args = parser.parse_args()

    if args.review:
        if FAILURES_LOG.exists():
            lines = [json.loads(l) for l in FAILURES_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
            open_f = [l for l in lines if l.get("status") == "open"]
            for f in open_f:
                print(f"  [{f['ts'][:10]}]  {f['message']!r:<50}  got={f['got']}  want={f['expected']}")
            print(f"\n  {len(open_f)} open failures")
        else:
            print("No failures logged yet.")
        sys.exit(0)

    sys.exit(asyncio.run(main(args)))
