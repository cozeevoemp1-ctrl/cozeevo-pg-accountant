"""
scripts/sort_monthly_by_checkin.py
===================================
One-off: sort every monthly tab's data rows by the Check-in column
ascending, so the LATEST check-in always sits at the bottom.

Row layout:
  rows 1-3: summary (unchanged)
  row 4:    headers
  row 5+:   tenant data  ← sorted

Missing / unparseable check-ins sink to the top so the real latest
check-in stays at the bottom.

Usage:
    python scripts/sort_monthly_by_checkin.py               # dry run
    python scripts/sort_monthly_by_checkin.py --write       # apply
    python scripts/sort_monthly_by_checkin.py --write APRIL 2026   # one tab
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.integrations.gsheets import _get_worksheet_sync
import gspread

DEFAULT_TABS = [
    "DECEMBER 2025",
    "JANUARY 2026",
    "FEBRUARY 2026",
    "MARCH 2026",
    "APRIL 2026",
]


def parse_ci(s: str):
    s = (s or "").strip()
    if not s:
        return None
    if " 00:00:00" in s:
        s = s.replace(" 00:00:00", "")
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def col_letter(n: int) -> str:
    """1-indexed column letter. 1->A, 26->Z, 27->AA."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sort_tab(tab_name: str, write: bool, backup_dir: Path | None) -> None:
    try:
        ws = _get_worksheet_sync(tab_name)
    except gspread.WorksheetNotFound:
        print(f"  [skip] {tab_name} — not found")
        return

    vals = ws.get_all_values()
    if len(vals) < 5:
        print(f"  [skip] {tab_name} — no data rows")
        return

    # Find header row: first row in first 10 where col A is "Room".
    header_idx = -1
    for i in range(min(10, len(vals))):
        if (vals[i][0] if vals[i] else "").strip().lower() == "room":
            header_idx = i
            break

    if header_idx >= 0:
        headers = vals[header_idx]
        ci_col = -1
        for i, h in enumerate(headers):
            if h.strip().lower() in ("check-in", "checkin", "check in"):
                ci_col = i
                break
        if ci_col < 0:
            print(f"  [skip] {tab_name} — header row found but no 'Check-in' column")
            return
        data_start = header_idx + 1
        header_ncols = len(headers)
    else:
        # Legacy tab whose header row was wiped by summary expansion (DECEMBER 2025).
        # 15-col legacy format: Check-in at col K (index 10), data from row 7.
        data_start = 6
        header_ncols = 15
        ci_col = 10
        print(f"  [legacy] {tab_name} — no header row; assuming 15-col format, Check-in at col K")

    raw_data = vals[data_start:]
    while raw_data and not any((c or "").strip() for c in raw_data[-1]):
        raw_data.pop()
    if not raw_data:
        print(f"  [skip] {tab_name} — empty body")
        return

    # NEVER truncate: pad every row to max(header_ncols, widest actual row).
    max_row_cols = max(len(r) for r in raw_data)
    ncols = max(header_ncols, max_row_cols)
    data = [list(row) + [""] * (ncols - len(row)) for row in raw_data]

    # Backup to local CSV before any mutation.
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        safe_name = tab_name.replace(" ", "_")
        bpath = backup_dir / f"{safe_name}.csv"
        with bpath.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for row in vals:
                w.writerow(row)
        print(f"  backup saved: {bpath}")

    def key(row):
        ci = row[ci_col] if ci_col < len(row) else ""
        dt = parse_ci(ci)
        return (dt or date.min, row[0] if row else "", row[1] if len(row) > 1 else "")

    sorted_data = sorted(data, key=key)

    # Integrity checks: same rows, same count — just reordered.
    assert len(sorted_data) == len(data), f"row-count drift on {tab_name}"
    assert sorted(sorted_data) == sorted(data), f"content drift on {tab_name}"

    changed = sorted_data != data
    print(f"  {tab_name}: {len(data)} rows | ci_col={col_letter(ci_col+1)} | "
          f"ncols={ncols} | {'CHANGED' if changed else 'already sorted'}")

    if not changed or not write:
        if write and not changed:
            print(f"    nothing to write for {tab_name}")
        return

    last_col = col_letter(ncols)
    start_row = data_start + 1  # 1-indexed
    end_row = data_start + len(sorted_data)
    ws.update(
        values=sorted_data,
        range_name=f"A{start_row}:{last_col}{end_row}",
        value_input_option="USER_ENTERED",
    )
    print(f"    wrote {len(sorted_data)} sorted rows to {tab_name} "
          f"(range A{start_row}:{last_col}{end_row})")

    # Verify row count post-write.
    post = ws.get_all_values()
    post_data = post[data_start:]
    while post_data and not any((c or "").strip() for c in post_data[-1]):
        post_data.pop()
    if len(post_data) != len(data):
        print(f"    WARN {tab_name}: pre={len(data)} post={len(post_data)} — investigate!")
    else:
        print(f"    verified: {len(post_data)} rows intact")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Actually write changes")
    ap.add_argument("tabs", nargs="*", help="Specific tab names (default: all monthly tabs)")
    args = ap.parse_args()

    tabs = args.tabs if args.tabs else DEFAULT_TABS
    # If user passed "APRIL 2026" as two args it becomes ["APRIL", "2026"] — stitch.
    if len(tabs) == 2 and tabs[1].isdigit():
        tabs = [f"{tabs[0]} {tabs[1]}"]

    backup_dir = None
    if args.write:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(__file__).parent.parent / "data" / "backups" / f"sort_{ts}"

    print(f"{'WRITE' if args.write else 'DRY-RUN'} mode | tabs: {tabs}")
    if backup_dir:
        print(f"backups -> {backup_dir}")
    for t in tabs:
        sort_tab(t, write=args.write, backup_dir=backup_dir)
    print("DONE")


if __name__ == "__main__":
    main()
