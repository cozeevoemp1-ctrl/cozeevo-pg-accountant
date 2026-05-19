"""
One-off: patch existing Supabase auth users to add 'name' to user_metadata.
Run once after deploying the auth.py name-extraction fix.

Usage:
    python scripts/_patch_auth_user_names.py          # dry run
    python scripts/_patch_auth_user_names.py --write  # actually patch
"""
import argparse
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY  = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

# email → display name mapping (must match create_auth_users.py USERS list)
EMAIL_TO_NAME = {
    "sai1522kl@gmail.com":                 "Lokesh",
    "cozeevo@gmail.com":                   "Cozeevo",
    "krish484@gmail.com":                  "Kiran",
    "lakshmigorjala6@gmail.com":           "Lakshmi",
    "devarajuluprabhakaran1@gmail.com":    "Prabhakaran",
}


def fetch_all_users() -> list[dict]:
    resp = requests.get(
        f"{SUPABASE_URL}/auth/v1/admin/users?per_page=1000",
        headers=HEADERS, timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("users", [])


def patch_user(uid: str, name: str, current_meta: dict, write: bool) -> str:
    new_meta = {**current_meta, "name": name}
    if not write:
        return f"[DRY RUN] would set name='{name}' for uid {uid[:8]}..."
    resp = requests.put(
        f"{SUPABASE_URL}/auth/v1/admin/users/{uid}",
        headers=HEADERS,
        json={"user_metadata": new_meta},
        timeout=15,
    )
    resp.raise_for_status()
    return f"PATCHED uid={uid[:8]}... name='{name}'"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if not SERVICE_KEY:
        sys.exit("SUPABASE_SERVICE_KEY not set")

    users = fetch_all_users()
    print(f"Found {len(users)} auth users\n")

    patched = 0
    for u in users:
        email = (u.get("email") or "").lower()
        name  = EMAIL_TO_NAME.get(email)
        if not name:
            continue
        current_meta = u.get("user_metadata") or {}
        if current_meta.get("name") == name:
            print(f"  SKIP (already set): {email} → {name}")
            continue
        uid    = u["id"]
        status = patch_user(uid, name, current_meta, args.write)
        print(f"  {status}  ({email})")
        patched += 1

    print(f"\n{'Patched' if args.write else 'Would patch'} {patched} users.")
    if not args.write:
        print("Pass --write to apply.")


if __name__ == "__main__":
    main()
