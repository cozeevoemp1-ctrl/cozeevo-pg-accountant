# Auth Users & Role Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create 5 Supabase Auth accounts (admin/staff roles) with email verification, and enforce auth + finance gating in Next.js middleware.

**Architecture:** Python script calls Supabase Admin REST API to create users with role metadata. Next.js middleware reads the Supabase session server-side and redirects unauthenticated users to `/login` and staff users away from `/finance/**`. No new pages needed — backend finance endpoints already block non-admin via `_require_admin()`.

**Tech Stack:** Python `requests`, Supabase Admin REST API, Next.js middleware, `@supabase/ssr` v0.10.2

---

## Pre-flight: Supabase service role key

The admin API requires the **service role key** (not the anon key).

- [ ] Get it: Supabase Dashboard → Settings → API → `service_role` (secret) key
- [ ] Add to local `.env`:
  ```
  SUPABASE_SERVICE_KEY="eyJ..."
  ```
- [ ] Add to VPS `.env` (already needed for backend):
  ```bash
  ssh -i ~/.ssh/id_ed25519 root@187.127.130.194 \
    "echo 'SUPABASE_SERVICE_KEY=\"eyJ...\"' >> /opt/pg-accountant/.env"
  ```

---

## Task 1: Create 5 Supabase auth users via Admin API

**Files:**
- Create: `scripts/create_auth_users.py`

### Users to create

| Email | Role (user_metadata) | Person |
|---|---|---|
| `Sai1522kl@gmail.com` | `staff` | Lokesh (receptionist) |
| `Cozeevo@gmail.com` | `admin` | Business account |
| `krish484@gmail.com` | `admin` | Kiran |
| `lakshmigorjala6@gmail.com` | `admin` | Lakshmi |
| `devarajuluprabhakaran1@gmail.com` | `admin` | Prabhakaran |

### How it works

- `POST /auth/v1/admin/users` with `email_confirm: false`
- Supabase creates the user and sends a **"Confirm your email"** email
- User clicks the link → account activated
- User logs in with the generated password (script prints it — Kiran communicates via WhatsApp)
- `user_metadata` carries `role` and `org_id` — these appear in the JWT and are read by `auth.py`

- [ ] **Step 1: Write the script**

```python
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
```

- [ ] **Step 2: Dry run to verify config**

```bash
python scripts/create_auth_users.py
```

Expected output:
```
Found N existing auth users

  [DRY RUN] would create Sai1522kl@gmail.com as staff
  [DRY RUN] would create Cozeevo@gmail.com as admin
  ...

CREDENTIALS TO COMMUNICATE ...
[DRY RUN] Pass --write to actually create users.
```

If you see `SUPABASE_SERVICE_KEY not set` — add it to `.env` first.

- [ ] **Step 3: Create users (run once)**

```bash
python scripts/create_auth_users.py --write
```

Expected: each user line shows `CREATED: <email> (admin/staff)`.  
If a user already existed: `SKIP (already exists): <email>`.

Save the printed credentials — Kiran sends them to each person via WhatsApp.

- [ ] **Step 4: Verify in Supabase dashboard**

Supabase Dashboard → Authentication → Users.  
Should see 5 users. Each should have `email_confirmed_at = NULL` (pending) and `user_metadata = {"role": "...", "org_id": 1}`.

- [ ] **Step 5: Commit**

```bash
git add scripts/create_auth_users.py
git commit -m "feat(auth): script to create Supabase auth users with role metadata"
```

---

## Task 2: Middleware — auth guard + finance role gate

**Files:**
- Modify: `web/middleware.ts`

### Rules

| Condition | Action |
|---|---|
| Path is `/login` | Always allow (skip all checks) |
| No valid session | Redirect to `/login` |
| Valid session, path starts with `/finance` | Allow only if `user_metadata.role === "admin"`, else redirect to `/` |
| Valid session, any other path | Allow |

### Important

- Timeout stays at 3 s (Supabase slow = serve the page rather than block all access)
- On timeout, **do not redirect** — fail open so Supabase being slow doesn't lock everyone out
- `getUser()` validates the JWT server-side (more secure than `getSession()`)

- [ ] **Step 1: Replace `web/middleware.ts`**

```typescript
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Always allow the login page through
  if (pathname.startsWith("/login")) {
    return NextResponse.next({ request });
  }

  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() { return request.cookies.getAll(); },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    },
  );

  let user: { user_metadata?: Record<string, unknown> } | null = null;
  try {
    const result = await Promise.race([
      supabase.auth.getUser(),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("timeout")), 3000),
      ),
    ]);
    user = result.data?.user ?? null;
  } catch {
    // Supabase slow/down — fail open, don't lock everyone out
    return supabaseResponse;
  }

  // No session → login
  if (!user) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    return NextResponse.redirect(loginUrl);
  }

  // Finance routes → admin only
  if (pathname.startsWith("/finance")) {
    const role = user.user_metadata?.role as string | undefined;
    if (role !== "admin") {
      const homeUrl = request.nextUrl.clone();
      homeUrl.pathname = "/";
      return NextResponse.redirect(homeUrl);
    }
  }

  return supabaseResponse;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|manifest.json|icons).*)"],
};
```

- [ ] **Step 2: Test locally**

Start the PWA dev server:
```bash
cd web && npm run dev
```

Open `http://localhost:3000` in an incognito window.

Expected: redirected to `http://localhost:3000/login`.

Log in as an admin account. Go to `/finance`. Expected: page loads.

Log in as Lokesh (`Sai1522kl@gmail.com`). Go to `/finance`. Expected: redirected to `/`.

- [ ] **Step 3: Commit**

```bash
git add web/middleware.ts
git commit -m "feat(auth): enforce login gate and admin-only finance route in middleware"
```

---

## Task 3: Deploy + smoke test on VPS

- [ ] **Step 1: Deploy backend + PWA**

```bash
ssh -i ~/.ssh/id_ed25519 root@187.127.130.194 \
  "cd /opt/pg-accountant && git pull && systemctl restart pg-accountant && \
   cd web && npm run build && systemctl restart kozzy-pwa && echo done"
```

Expected: `done` with no build errors.

- [ ] **Step 2: Smoke test as admin**

Open `https://app.getkozzy.com` in incognito.
- Should redirect to `/login`
- Log in as `krish484@gmail.com` (after email verification)
- Finance link visible on home screen
- `/finance` loads

- [ ] **Step 3: Smoke test as staff**

Log in as `Sai1522kl@gmail.com`.
- Finance link NOT visible on home screen
- Navigating to `/finance` directly → redirected to `/`
- All other pages (tenants, payment, checkin, etc.) work normally

- [ ] **Step 4: Confirm Lokesh's delete now works**

While logged in as Lokesh, go to the edit page for a room 514 tenant and attempt delete.  
Expected: delete succeeds (the `agreements` bug was already fixed and deployed).

---

## Self-review

**Spec coverage:**
- ✅ 5 users created with correct roles
- ✅ Email verification on first activation
- ✅ Unauthenticated → /login
- ✅ Staff → blocked from /finance
- ✅ Backend finance endpoints already have `_require_admin()` (no change needed)
- ✅ Finance link already hidden in `page.tsx` for non-admin (no change needed)

**No placeholders:** All code is complete.

**Type consistency:** `user_metadata.role` read the same way in both middleware and `auth.py`. Redirect pattern consistent across both redirect cases.

**Edge cases covered:**
- Supabase timeout → fail open (no lockout)
- Already-existing users → script skips gracefully
- Staff visiting `/finance` → redirected to `/` not `/login` (they're authenticated, just wrong role)
