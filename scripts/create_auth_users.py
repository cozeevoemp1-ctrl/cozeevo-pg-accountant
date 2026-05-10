# scripts/create_auth_users.py
"""
Create Supabase Auth users for the PWA with role metadata.
Run ONCE. Idempotent — skips users that already exist.

Usage:
    python scripts/create_auth_users.py          # dry run (print what would happen)
    python scripts/create_auth_users.py --write  # create users + send verification emails
"""
import argparse
import os
import secrets
import string
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

USERS = [
    {"email": "Sai1522kl@gmail.com",                   "role": "staff",  "name": "Lokesh (receptionist)"},
    {"email": "Cozeevo@gmail.com",                      "role": "admin",  "name": "Cozeevo business account"},
    {"email": "krish484@gmail.com",                     "role": "admin",  "name": "Kiran"},
    {"email": "lakshmigorjala6@gmail.com",              "role": "admin",  "name": "Lakshmi"},
    {"email": "devarajuluprabhakaran1@gmail.com",       "role": "admin",  "name": "Prabhakaran"},
]


def gen_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def list_existing_emails() -> set[str]:
    """Fetch all existing auth users to avoid duplicates."""
    url = f"{SUPABASE_URL}/auth/v1/admin/users?per_page=1000"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    users = resp.json().get("users", [])
    return {u["email"].lower() for u in users}


def create_user(email: str, role: str, password: str, write: bool) -> str:
    """Create user and return status string."""
    payload = {
        "email": email,
        "password": password,
        "email_confirm": False,          # Supabase sends verification email
        "user_metadata": {
            "role": role,
            "org_id": 1,
        },
    }
    if not write:
        return f"[DRY RUN] would create {email} as {role}"
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=HEADERS,
        json=payload,
        timeout=15,
    )
    if resp.status_code == 422 and "already" in resp.text.lower():
        return f"SKIP (already exists): {email}"
    resp.raise_for_status()
    return f"CREATED: {email} ({role})"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if not SERVICE_KEY:
        sys.exit("SUPABASE_SERVICE_KEY not set in .env")

    existing = list_existing_emails()
    print(f"Found {len(existing)} existing auth users\n")

    credentials = []
    for u in USERS:
        email = u["email"]
        if email.lower() in existing:
            print(f"  SKIP (exists): {email}")
            credentials.append((u["name"], email, "— already exists, use existing password"))
            continue
        password = gen_password()
        status = create_user(email, u["role"], password, args.write)
        print(f"  {status}")
        credentials.append((u["name"], email, password))

    print()
    print("=" * 60)
    print("CREDENTIALS TO COMMUNICATE (send via WhatsApp):")
    print("=" * 60)
    for name, email, pw in credentials:
        print(f"  {name}")
        print(f"    Email:    {email}")
        print(f"    Password: {pw}")
        print(f"    URL:      https://app.getkozzy.com")
        print(f"    Step:     Check email → click verification link → then login")
        print()

    if not args.write:
        print("[DRY RUN] Pass --write to actually create users.")


if __name__ == "__main__":
    main()
