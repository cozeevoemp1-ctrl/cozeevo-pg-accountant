"""
One-off: move existing Supabase Auth users' role/org_id from user_metadata
(self-editable by the user) into app_metadata (admin-API-only writable).

Fixes the privilege-escalation bug documented in docs/SECURITY_AUDIT.md
(finding: role trusted from user_metadata). Run ONCE against production
after deploying the src/api/v2/auth.py + web/middleware.ts fix.

Idempotent — safe to re-run; skips users that already have app_metadata.role.

Usage:
    python scripts/_migrate_role_to_app_metadata.py          # dry run
    python scripts/_migrate_role_to_app_metadata.py --write  # apply
"""
import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}


def list_users() -> list[dict]:
    url = f"{SUPABASE_URL}/auth/v1/admin/users?per_page=1000"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("users", [])


def migrate_user(user: dict, write: bool) -> str:
    user_id = user["id"]
    email = user.get("email", user_id)
    app_meta = user.get("app_metadata") or {}
    user_meta = user.get("user_metadata") or {}

    if app_meta.get("role"):
        return f"SKIP (already has app_metadata.role={app_meta['role']}): {email}"

    role = user_meta.get("role")
    org_id = user_meta.get("org_id", 1)
    if not role:
        return f"SKIP (no user_metadata.role to migrate): {email}"

    if not write:
        return f"[DRY RUN] would set app_metadata={{'role': '{role}', 'org_id': {org_id}}} for {email}"

    resp = requests.put(
        f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers=HEADERS,
        json={"app_metadata": {"role": role, "org_id": org_id}},
        timeout=15,
    )
    resp.raise_for_status()
    return f"MIGRATED: {email} -> app_metadata.role={role}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    users = list_users()
    print(f"Found {len(users)} auth user(s)\n")
    for u in users:
        print(migrate_user(u, args.write))

    if not args.write:
        print("\nDry run only. Re-run with --write to apply.")
    else:
        print(
            "\nDone. Existing sessions keep their old JWT (with role only in "
            "user_metadata) until the access token refreshes (~1hr) or the "
            "user logs out/in. Consider asking admins to re-login after deploy."
        )


if __name__ == "__main__":
    main()
