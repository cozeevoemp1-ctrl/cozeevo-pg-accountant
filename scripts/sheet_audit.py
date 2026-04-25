"""
scripts/sheet_audit.py
======================
CLI wrapper for the sheet↔DB drift audit.

Usage
-----
    venv/Scripts/python scripts/sheet_audit.py              # dry, print report
    venv/Scripts/python scripts/sheet_audit.py --alert      # + WhatsApp admin
    venv/Scripts/python scripts/sheet_audit.py --json       # JSON output

The scheduler calls the underlying module directly (see
`src/scheduler.py::_nightly_sheet_audit`).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv()

from src.services.sheet_audit import (
    run_audit, run_audit_with_db, apply_fixes, format_report, whatsapp_message,
)


async def _send_alert(body: str) -> bool:
    admin = os.getenv("ADMIN_PHONE", "").strip()
    if not admin:
        print("[audit] ADMIN_PHONE not set — skipping WhatsApp alert")
        return False
    try:
        from src.whatsapp.webhook_handler import _send_whatsapp
        await _send_whatsapp(admin, body)
        return True
    except Exception as e:
        print(f"[audit] WhatsApp alert failed: {e}")
        return False


async def main_async(args) -> int:
    if args.auto_fix:
        r, db_state = await run_audit_with_db()
    else:
        r = await run_audit()
        db_state = {}

    if args.json:
        out = {
            "month_tab": r.month_tab,
            "totals": {
                "tenants_diffs": len(r.tenants_diffs),
                "monthly_diffs": len(r.monthly_diffs),
                "missing_in_db": len(r.missing_in_db),
                "missing_in_sheet": len(r.missing_in_sheet),
            },
            "tenants_diffs": [d.__dict__ for d in r.tenants_diffs],
            "monthly_diffs": [d.__dict__ for d in r.monthly_diffs],
            "missing_in_db": r.missing_in_db,
            "missing_in_sheet": r.missing_in_sheet,
        }
        print(json.dumps(out, indent=2, default=str))
    else:
        print(format_report(r))

    if args.auto_fix and r.total_diffs > 0:
        print("\n-- Auto-fix --")
        fixes = await apply_fixes(r, db_state)
        print(f"  Fixed:   {fixes['fixed']}")
        print(f"  Skipped: {fixes['skipped']}")
        for err in fixes["errors"]:
            print(f"  ERROR: {err}")

    if args.alert and r.total_diffs > 0:
        await _send_alert(whatsapp_message(r))

    return 0 if r.total_diffs == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true",
                    help="Send WhatsApp alert to ADMIN_PHONE when diffs found")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON instead of human-readable report")
    ap.add_argument("--auto-fix", action="store_true",
                    help="Push DB values to sheet for all detected diffs (TENANTS fields + monthly tab)")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
