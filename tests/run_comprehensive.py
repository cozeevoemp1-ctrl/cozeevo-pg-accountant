"""
tests/run_comprehensive.py
===========================
Runs ALL comprehensive test files and pushes results to Google Sheet
in real-time so Kiran can watch the dashboard update live.

Usage:
    python tests/run_comprehensive.py              # run all 6 test files
    python tests/run_comprehensive.py --file test_add_tenant_comprehensive  # one file
    python tests/run_comprehensive.py --no-sheet    # skip sheet, console only

Creates a "TEST RESULTS" tab in the master Google Sheet with:
  Row 1: Header
  Row 2+: One row per test — File | Test | Status | Duration | Error (if any)
  + Summary row at top with totals
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Google Sheets setup ───────────────────────────────────────────────────────

SHEET_ID = os.getenv(
    "GSHEETS_SHEET_ID",
    "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw",
)
CREDENTIALS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "credentials",
    "gsheets_service_account.json",
)
TAB_NAME = "TEST RESULTS"

# Fix encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _get_sheet():
    """Connect to Google Sheet and return (spreadsheet, worksheet)."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("[WARN] gspread not installed — sheet updates disabled")
        return None, None

    if not os.path.exists(CREDENTIALS_PATH):
        print(f"[WARN] Credentials not found at {CREDENTIALS_PATH} — sheet updates disabled")
        return None, None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SHEET_ID)

    # Create or get TEST RESULTS tab
    try:
        ws = ss.worksheet(TAB_NAME)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=TAB_NAME, rows=1500, cols=8)

    # Write headers
    headers = [
        "File", "Test Name", "Status", "Duration (s)",
        "Error", "Category", "Timestamp", "Run ID",
    ]
    ws.update(values=[headers], range_name="A1:H1", value_input_option="USER_ENTERED")

    # Format header row (bold)
    ws.format("A1:H1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
        "horizontalAlignment": "CENTER",
    })
    # Format header text color white
    ws.format("A1:H1", {
        "textFormat": {"bold": True, "foregroundColorStyle": {"rgbColor": {"red": 1, "green": 1, "blue": 1}}},
        "backgroundColor": {"red": 0.15, "green": 0.15, "blue": 0.15},
    })

    return ss, ws


# ── Test files ────────────────────────────────────────────────────────────────

ALL_TEST_FILES = [
    "test_add_tenant_comprehensive",
    "test_collect_rent_comprehensive",
    "test_checkout_comprehensive",
    "test_notice_comprehensive",
    "test_conversation_context",
    "test_edge_cases",
]

TEST_DIR = Path(__file__).parent
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")


def _extract_category(test_name: str) -> str:
    """Guess category from test function name."""
    name = test_name.lower()
    for cat, keywords in [
        ("Intent Detection", ["detect", "intent", "basic"]),
        ("Entity Extraction", ["entity", "extract", "name_", "room_", "amount_", "mode_", "date_", "phone_"]),
        ("Date Parsing", ["date", "parse"]),
        ("Edge Case", ["edge", "special", "unicode", "empty", "long", "boundary"]),
        ("Negative Test", ["negative", "not_", "should_not", "wrong"]),
        ("Cancel/Breakout", ["cancel", "breakout", "greeting", "mid_flow"]),
        ("Disambiguation", ["ambig", "disambig"]),
        ("Role-based", ["role", "admin", "tenant_role", "lead_role"]),
        ("Hindi/Mixed", ["hindi", "mixed", "hinglish"]),
        ("Parametrized", ["param"]),
    ]:
        if any(k in name for k in keywords):
            return cat
    return "General"


def run_pytest_file(filename: str, ws, current_row: int) -> tuple[int, int, int, int]:
    """
    Run a single test file with pytest --json-report, parse results,
    and write each test to Google Sheet in real-time.

    Returns (passed, failed, errors, next_row)
    """
    filepath = TEST_DIR / f"{filename}.py"
    if not filepath.exists():
        print(f"  [SKIP] {filename}.py not found")
        return 0, 0, 0, current_row

    report_path = TEST_DIR / "results" / f"{filename}_report.json"
    report_path.parent.mkdir(exist_ok=True)

    # Run pytest with JSON report
    cmd = [
        sys.executable, "-m", "pytest",
        str(filepath),
        f"--json-report", f"--json-report-file={report_path}",
        "--tb=short",
        "-q",
        "--no-header",
    ]

    print(f"\n{'=' * 60}")
    print(f"  Running: {filename} ...")
    print(f"{'=' * 60}")

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = time.time() - t0

    # Print console output
    if result.stdout:
        # Show summary line
        for line in result.stdout.strip().split("\n")[-5:]:
            print(f"  {line}")
    if result.returncode != 0 and result.stderr:
        for line in result.stderr.strip().split("\n")[-3:]:
            print(f"  [ERR] {line}")

    # Parse JSON report
    passed = failed = errors = 0
    rows_to_write = []

    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            tests = report.get("tests", [])

            for t in tests:
                test_name = t.get("nodeid", "").split("::")[-1]
                outcome = t.get("outcome", "unknown")
                duration = round(t.get("duration", 0), 4)
                error_msg = ""

                if outcome == "passed":
                    passed += 1
                    status = "PASS"
                elif outcome == "failed":
                    failed += 1
                    status = "FAIL"
                    # Extract failure message
                    call_info = t.get("call", {})
                    crash = call_info.get("crash", {})
                    error_msg = crash.get("message", "")[:200]
                    if not error_msg:
                        longrepr = call_info.get("longrepr", "")
                        if isinstance(longrepr, str):
                            # Get last line of traceback
                            lines = [l for l in longrepr.strip().split("\n") if l.strip()]
                            error_msg = lines[-1][:200] if lines else ""
                elif outcome == "error":
                    errors += 1
                    status = "ERROR"
                    setup_info = t.get("setup", {})
                    crash = setup_info.get("crash", {})
                    error_msg = crash.get("message", "")[:200]
                else:
                    status = outcome.upper()

                category = _extract_category(test_name)
                timestamp = datetime.now().strftime("%H:%M:%S")

                rows_to_write.append([
                    filename, test_name, status, duration,
                    error_msg, category, timestamp, RUN_ID,
                ])

        except Exception as e:
            print(f"  [WARN] Could not parse report: {e}")
            # Fallback: count from return code
            rows_to_write.append([
                filename, "(parse error)", "ERROR", round(elapsed, 2),
                str(e)[:200], "Error", datetime.now().strftime("%H:%M:%S"), RUN_ID,
            ])
            errors += 1
    else:
        rows_to_write.append([
            filename, "(no report)", "ERROR", round(elapsed, 2),
            "pytest-json-report not installed or test crashed",
            "Error", datetime.now().strftime("%H:%M:%S"), RUN_ID,
        ])
        errors += 1

    # ── Write to Google Sheet in batch ────────────────────────────────────
    if ws and rows_to_write:
        try:
            end_row = current_row + len(rows_to_write) - 1
            range_str = f"A{current_row}:H{end_row}"
            ws.update(values=rows_to_write, range_name=range_str, value_input_option="USER_ENTERED")

            # Batch color-code: collect PASS/FAIL row ranges, format in max 3 calls
            pass_rows = [current_row + i for i, r in enumerate(rows_to_write) if r[2] == "PASS"]
            fail_rows = [current_row + i for i, r in enumerate(rows_to_write) if r[2] == "FAIL"]
            err_rows  = [current_row + i for i, r in enumerate(rows_to_write) if r[2] not in ("PASS", "FAIL")]

            if pass_rows:
                # Format entire pass range at once (contiguous or batch)
                batch_ranges = [f"C{pass_rows[0]}:C{pass_rows[-1]}"]
                ws.format(batch_ranges[0], {"backgroundColor": {"red": 0.85, "green": 1.0, "blue": 0.85}})
            if fail_rows:
                for fr in fail_rows:
                    ws.format(f"A{fr}:H{fr}", {
                        "backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.85},
                        "textFormat": {"bold": True},
                    })

            time.sleep(1)  # respect rate limit between files
            print(f"  [SHEET] Wrote {len(rows_to_write)} rows (rows {current_row}-{end_row})")
        except Exception as e:
            print(f"  [WARN] Sheet write failed: {e}")

    next_row = current_row + len(rows_to_write)

    total = passed + failed + errors
    print(f"  Result: {passed}/{total} passed, {failed} failed, {errors} errors ({elapsed:.1f}s)")

    return passed, failed, errors, next_row


def write_summary(ws, ss, total_p, total_f, total_e, elapsed, next_row):
    """Write summary section at the bottom of results."""
    if not ws:
        return

    try:
        summary_row = next_row + 1
        total = total_p + total_f + total_e
        pct = (total_p / total * 100) if total > 0 else 0

        summary = [
            ["", "", "", "", "", "", "", ""],
            ["SUMMARY", f"{total} total", f"{total_p} PASS", f"{total_f} FAIL",
             f"{total_e} ERROR", f"{pct:.1f}%", f"{elapsed:.1f}s", RUN_ID],
        ]
        ws.update(values=summary, range_name=f"A{summary_row}:H{summary_row + 1}", value_input_option="USER_ENTERED")

        # Bold + color the summary row
        ws.format(f"A{summary_row + 1}:H{summary_row + 1}", {
            "textFormat": {"bold": True, "fontSize": 12},
            "backgroundColor": {"red": 0.1, "green": 0.1, "blue": 0.3},
        })
        ws.format(f"A{summary_row + 1}:H{summary_row + 1}", {
            "textFormat": {
                "bold": True, "fontSize": 12,
                "foregroundColorStyle": {"rgbColor": {"red": 1, "green": 1, "blue": 1}},
            },
            "backgroundColor": {"red": 0.1, "green": 0.1, "blue": 0.3},
        })

        # Freeze header row
        ws.freeze(rows=1)

        # Auto-resize columns
        try:
            body = {
                "requests": [
                    {
                        "autoResizeDimensions": {
                            "dimensions": {
                                "sheetId": ws.id,
                                "dimension": "COLUMNS",
                                "startIndex": 0,
                                "endIndex": 8,
                            }
                        }
                    }
                ]
            }
            ss.batch_update(body)
        except Exception:
            pass

        print(f"\n  [SHEET] Summary written at row {summary_row + 1}")

    except Exception as e:
        print(f"  [WARN] Summary write failed: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Run single test file (without .py)")
    parser.add_argument("--no-sheet", action="store_true", help="Skip Google Sheet updates")
    args = parser.parse_args()

    files = [args.file] if args.file else ALL_TEST_FILES

    # Check pytest-json-report is installed
    try:
        import pytest_jsonreport  # noqa: F401
    except ImportError:
        print("[INFO] Installing pytest-json-report...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pytest-json-report", "-q"],
                       capture_output=True)

    # Connect to sheet
    ws, ss = None, None
    if not args.no_sheet:
        print("[SHEET] Connecting to Google Sheet...")
        ss, ws = _get_sheet()
        if ws:
            print(f"[SHEET] Connected — tab: '{TAB_NAME}'")
            print(f"[SHEET] Open your sheet to watch results appear live!")
        else:
            print("[SHEET] Sheet connection failed — running console only")

    print(f"\n{'#' * 60}")
    print(f"  COMPREHENSIVE TEST SUITE — {len(files)} files")
    print(f"  Run ID: {RUN_ID}")
    print(f"{'#' * 60}")

    total_p = total_f = total_e = 0
    current_row = 2  # row 1 is headers
    t0 = time.time()

    for filename in files:
        p, f, e, current_row = run_pytest_file(filename, ws, current_row)
        total_p += p
        total_f += f
        total_e += e

    elapsed = time.time() - t0
    total = total_p + total_f + total_e
    pct = (total_p / total * 100) if total > 0 else 0

    # Write summary to sheet
    write_summary(ws, ss, total_p, total_f, total_e, elapsed, current_row)

    print(f"\n{'#' * 60}")
    print(f"  FINAL: {total_p}/{total} passed ({pct:.1f}%)")
    print(f"  {total_f} failed, {total_e} errors")
    print(f"  Time: {elapsed:.1f}s")
    print(f"{'#' * 60}")

    if total_f > 0 or total_e > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
