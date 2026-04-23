"""
scripts/list_sheet_protections.py
==================================
List every protected range on the Operations v2 sheet with its location and
current editors list — so you know which protections are blocking filter/sort.

Usage: python scripts/list_sheet_protections.py
"""
from __future__ import annotations

import os
import sys

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDS_PATH = os.path.join(ROOT, "credentials", "gsheets_service_account.json")
SHEET_ID = os.getenv("GSHEETS_SHEET_ID", "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def col_letter(idx: int) -> str:
    s = ""
    n = idx
    while True:
        s = chr(ord("A") + (n % 26)) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def fmt_range(r: dict | None, sheet_title: str) -> str:
    if not r:
        return f"{sheet_title} (ENTIRE SHEET)"
    sr = r.get("startRowIndex")
    er = r.get("endRowIndex")
    sc = r.get("startColumnIndex")
    ec = r.get("endColumnIndex")
    if sr is None and sc is None:
        return f"{sheet_title} (ENTIRE SHEET)"
    a = f"{col_letter(sc) if sc is not None else 'A'}{(sr or 0) + 1}"
    b = f"{col_letter((ec or 0) - 1) if ec is not None else ''}{er if er is not None else ''}"
    return f"{sheet_title}!{a}:{b}"


def main() -> int:
    if not os.path.exists(CREDS_PATH):
        print(f"ERROR: credentials not found at {CREDS_PATH}", file=sys.stderr)
        return 2

    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    meta = sheets.spreadsheets().get(
        spreadsheetId=SHEET_ID,
        fields="sheets(properties(sheetId,title),protectedRanges)",
    ).execute()

    total = 0
    for sh in meta.get("sheets", []):
        title = sh["properties"]["title"]
        for pr in sh.get("protectedRanges", []):
            total += 1
            rng = fmt_range(pr.get("range"), title)
            desc = pr.get("description", "")
            warn = pr.get("warningOnly", False)
            editors = pr.get("editors", {}) or {}
            users = editors.get("users", []) or []
            domain_ok = editors.get("domainUsersCanEdit", False)
            print(f"\n#{total} {rng}")
            if desc:
                print(f"    description: {desc}")
            print(f"    warningOnly: {warn}")
            print(f"    editors.users: {users if users else '(empty — creator-only)'}")
            print(f"    domainUsersCanEdit: {domain_ok}")

    if total == 0:
        print("No protected ranges found.")
    else:
        print(f"\nTotal: {total} protected ranges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
