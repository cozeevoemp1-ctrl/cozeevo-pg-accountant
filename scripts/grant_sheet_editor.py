"""
scripts/grant_sheet_editor.py
=============================
Grant cozeevoemp1@gmail.com (or any email passed via --email) full edit + filter
rights on the Cozeevo Operations v2 sheet.

What it does:
  1. Ensures the email has 'writer' role on the file (Drive API).
  2. Lists every protected range on every sheet and adds the email to the
     allowed-editors list (so filter/sort stops being blocked).

Usage:
  python scripts/grant_sheet_editor.py
  python scripts/grant_sheet_editor.py --email someone@example.com
  python scripts/grant_sheet_editor.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDS_PATH = os.path.join(ROOT, "credentials", "gsheets_service_account.json")
SHEET_ID = os.getenv("GSHEETS_SHEET_ID", "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _svc():
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return drive, sheets, creds.service_account_email


def grant_file_editor(drive, email: str, dry: bool) -> str:
    """Ensure email has 'writer' role on the file. Returns status."""
    perms = drive.permissions().list(
        fileId=SHEET_ID,
        fields="permissions(id,emailAddress,role,type)",
        supportsAllDrives=True,
    ).execute().get("permissions", [])

    existing = next(
        (p for p in perms if p.get("emailAddress", "").lower() == email.lower()),
        None,
    )
    if existing and existing.get("role") in ("writer", "owner", "organizer", "fileOrganizer"):
        return f"already '{existing['role']}'"

    if dry:
        return "would grant writer"

    body = {"type": "user", "role": "writer", "emailAddress": email}
    drive.permissions().create(
        fileId=SHEET_ID,
        body=body,
        sendNotificationEmail=False,
        supportsAllDrives=True,
    ).execute()
    return "granted writer"


def add_to_protections(sheets, email: str, caller_email: str, dry: bool) -> tuple[int, int, list[str]]:
    """Add email to every protected range's editor list. Returns (updated, skipped, errs)."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=SHEET_ID,
        fields="sheets(properties(sheetId,title),protectedRanges)",
    ).execute()

    updated_count = 0
    skipped = 0
    errs: list[str] = []

    for sh in meta.get("sheets", []):
        title = sh["properties"]["title"]
        for pr in sh.get("protectedRanges", []):
            editors = pr.get("editors", {}) or {}
            users = editors.get("users", []) or []
            pr_id = pr.get("protectedRangeId")
            if any(u.lower() == email.lower() for u in users):
                print(f"  = {title} (id={pr_id}): already includes {email}")
                skipped += 1
                continue

            new_users = list(users)
            if caller_email and caller_email.lower() not in (u.lower() for u in new_users):
                new_users.append(caller_email)
            new_users.append(email)
            print(f"  > {title} (id={pr_id}): users {users} -> {new_users}")

            if dry:
                updated_count += 1
                continue

            new_pr = dict(pr)
            new_pr["editors"] = {
                "users": new_users,
                "groups": editors.get("groups", []),
                "domainUsersCanEdit": editors.get("domainUsersCanEdit", False),
            }
            req = {
                "updateProtectedRange": {
                    "protectedRange": new_pr,
                    "fields": "editors",
                }
            }
            try:
                sheets.spreadsheets().batchUpdate(
                    spreadsheetId=SHEET_ID,
                    body={"requests": [req]},
                ).execute()
                updated_count += 1
                print(f"    OK")
            except HttpError as e:
                errs.append(f"{title} (id={pr_id}): {e}")
                print(f"    FAIL: {e}")

    return updated_count, skipped, errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default="cozeevoemp1@gmail.com")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(CREDS_PATH):
        print(f"ERROR: credentials not found at {CREDS_PATH}", file=sys.stderr)
        return 2

    drive, sheets, caller_email = _svc()

    print(f"Target sheet: {SHEET_ID}")
    print(f"Target email: {args.email}")
    print(f"Caller (service account): {caller_email}")
    print(f"Dry-run: {args.dry_run}")
    print()

    print("[1/2] File-level permission…")
    try:
        status = grant_file_editor(drive, args.email, args.dry_run)
        print(f"  -> {status}")
    except HttpError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return 1

    print("\n[2/2] Protected ranges…")
    updated, skipped, errs = add_to_protections(sheets, args.email, caller_email, args.dry_run)
    print(f"  updated={updated}  already-allowed={skipped}  errors={len(errs)}")
    for e in errs:
        print(f"  ERROR: {e}", file=sys.stderr)

    print("\nDone.")
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
