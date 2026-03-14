"""
Local WhatsApp bot tester — no n8n needed.

Usage:
  python test_bot.py                      # interactive REPL
  python test_bot.py --phone +917845952289 --msg "who hasn't paid"
  python test_bot.py --scenario all       # run all built-in test scenarios

What it does:
  - Hits POST /api/whatsapp/process on your running FastAPI (port 8000)
  - Prints role, intent, and the reply the bot would send back on WhatsApp
"""
from __future__ import annotations

import argparse
import json
import sys
import httpx

API_URL = "http://localhost:8000/api/whatsapp/process"

# ── Phone presets ──────────────────────────────────────────────────────────────
PHONES = {
    "kiran":    "+917845952289",   # admin
    "partner":  "+917358341775",   # power_user
    "lead":     "+919999000001",   # unknown number → lead role
    # add any tenant phone here to test tenant role:
    # "tenant1": "+91XXXXXXXXXX",
}

# ── Built-in test scenarios ────────────────────────────────────────────────────
SCENARIOS: list[dict] = [
    # Admin tests
    {"label": "Admin: help",              "phone": PHONES["kiran"],   "msg": "help"},
    {"label": "Admin: dues query",        "phone": PHONES["kiran"],   "msg": "who hasn't paid this month"},
    {"label": "Admin: specific tenant",   "phone": PHONES["kiran"],   "msg": "Raj balance"},
    {"label": "Admin: monthly report",    "phone": PHONES["kiran"],   "msg": "monthly report"},
    {"label": "Admin: log payment",       "phone": PHONES["kiran"],   "msg": "Raj paid 15000 upi"},
    {"label": "Admin: add expense",       "phone": PHONES["kiran"],   "msg": "electricity 4500"},
    # Partner (power_user) tests
    {"label": "Partner: dues",            "phone": PHONES["partner"], "msg": "pending rent list"},
    {"label": "Partner: report",          "phone": PHONES["partner"], "msg": "summary"},
    # Lead tests
    {"label": "Lead: price enquiry",      "phone": PHONES["lead"],    "msg": "what is the rent"},
    {"label": "Lead: availability",       "phone": PHONES["lead"],    "msg": "any rooms available"},
    {"label": "Lead: visit request",      "phone": PHONES["lead"],    "msg": "can I come visit the PG"},
    {"label": "Lead: general",            "phone": PHONES["lead"],    "msg": "hi"},
]


def call_bot(phone: str, message: str) -> dict:
    payload = {"phone": phone, "message": message}
    try:
        r = httpx.post(API_URL, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        print("\n❌  Cannot connect to FastAPI. Is it running?")
        print("   Run:  python -m cli.start_api   (or START_API.bat)\n")
        sys.exit(1)
    except Exception as e:
        return {"error": str(e)}


def print_result(label: str, phone: str, msg: str, result: dict):
    role   = result.get("role", "?")
    intent = result.get("intent", "?")
    reply  = result.get("reply", "")
    skip   = result.get("skip", False)
    err    = result.get("error")

    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"  Phone  : {phone}")
    print(f"  Message: {msg}")
    print(f"  Role   : {role}  |  Intent: {intent}")
    if err:
        print(f"  ERROR  : {err}")
    elif skip:
        print("  Reply  : [skipped — spam/blocked]")
    else:
        # Indent multi-line replies
        lines = reply.strip().split("\n")
        print(f"  Reply  :")
        for line in lines:
            print(f"    {line}")


def run_scenarios():
    print(f"\nRunning {len(SCENARIOS)} test scenarios against {API_URL}\n")
    ok = fail = 0
    for s in SCENARIOS:
        result = call_bot(s["phone"], s["msg"])
        print_result(s["label"], s["phone"], s["msg"], result)
        if "error" in result:
            fail += 1
        else:
            ok += 1
    print(f"\n{'='*60}")
    print(f"  Results: {ok} passed, {fail} failed")
    print(f"{'='*60}\n")


def interactive_repl():
    print(f"\nPG Accountant — WhatsApp Bot Tester")
    print(f"API: {API_URL}")
    print(f"\nAvailable phone shortcuts:")
    for k, v in PHONES.items():
        print(f"  {k:10s} → {v}")
    print(f"\nType 'quit' to exit, 'scenarios' to run all tests.\n")

    current_phone = PHONES["kiran"]
    print(f"Active phone: {current_phone}  (type 'phone <name or +91xxx>' to switch)\n")

    while True:
        try:
            raw = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not raw:
            continue
        if raw.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break
        if raw.lower() == "scenarios":
            run_scenarios()
            continue
        if raw.lower().startswith("phone "):
            arg = raw[6:].strip()
            if arg in PHONES:
                current_phone = PHONES[arg]
                print(f"  Switched to: {current_phone} ({arg})")
            elif arg.startswith("+") or arg.startswith("91"):
                current_phone = arg if arg.startswith("+") else "+" + arg
                print(f"  Switched to: {current_phone}")
            else:
                print(f"  Unknown: {arg}. Options: {list(PHONES.keys())} or +91xxx")
            continue

        result = call_bot(current_phone, raw)
        role   = result.get("role", "?")
        intent = result.get("intent", "?")
        reply  = result.get("reply", "")
        skip   = result.get("skip", False)
        err    = result.get("error")

        print(f"  [{role} | {intent}]")
        if err:
            print(f"  ERROR: {err}")
        elif skip:
            print("  [skipped]")
        else:
            for line in reply.strip().split("\n"):
                print(f"  {line}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Test the WhatsApp bot locally")
    parser.add_argument("--phone", help="Phone number to send as (e.g. +917845952289 or 'kiran')")
    parser.add_argument("--msg",   help="Message to send")
    parser.add_argument("--scenario", choices=["all"], help="Run built-in test scenarios")
    args = parser.parse_args()

    if args.scenario == "all":
        run_scenarios()
    elif args.phone and args.msg:
        phone = PHONES.get(args.phone, args.phone)
        result = call_bot(phone, args.msg)
        print_result("CLI test", phone, args.msg, result)
    else:
        interactive_repl()


if __name__ == "__main__":
    main()
