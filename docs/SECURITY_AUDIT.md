# Security Audit — PG Accountant / Kozzy

Date: 2026-08-08
Scope: full repo (FastAPI backend `src/`, one-off `scripts/`, Next.js PWA `web/`) — DB authz/RLS/IDOR, secrets exposure, injection (SQL/command/path/prompt), CORS/session/webhook/XSS.
Method: 3 parallel offensive-review passes (independent, no shared context) + direct verification of every claimed finding against the live source before patching. All fixes below are already applied and syntax-checked (`py_compile`); nothing has been deployed or run against production yet.

---

## CRITICAL

### 1. Privilege escalation — role trusted from self-editable `user_metadata`
**Files:** `src/api/v2/auth.py:75-87` (fixed), `web/middleware.ts:33,51` (fixed), `scripts/create_auth_users.py:59-64` (fixed)

**Was:** `get_current_user()` read `role` and `org_id` from the JWT's `user_metadata` claim. In Supabase Auth, `user_metadata` is **self-editable by the authenticated user** via `supabase.auth.updateUser({ data: {...} })` — it only needs the user's own access token, not an admin key. `app_metadata` is the field Supabase reserves for admin-only writes, and the codebase never used it.

**Exploit:** Any logged-in account (e.g. the receptionist "staff" login) opens the browser console and runs:
```js
await supabase.auth.updateUser({ data: { role: "admin" } })
```
Supabase updates `raw_user_meta_data.role` and mints a new, validly-signed JWT with `user_metadata.role: "admin"`. Every admin-gated route (`finance.py` P&L/investment data, `blacklist.py`, the PWA's `/finance` middleware gate) now accepts them, because the signature check only proves the token wasn't tampered with — not that its self-supplied content is trustworthy.

**Fix applied:**
- `src/api/v2/auth.py` — `role`/`org_id` now read from `app_metadata` only; `name` (non-privileged) stays in `user_metadata`.
- `web/middleware.ts` — admin gate now reads `app_metadata.role`.
- `scripts/create_auth_users.py` — new users get `role`/`org_id` written to `app_metadata` (via the service-role Admin API, which is the only way to write it).
- `scripts/_migrate_role_to_app_metadata.py` (new) — one-off migration to move the 5 existing users' role from `user_metadata` into `app_metadata`. **Not yet run** — needs to be run against production once, after this code deploys (see "Next steps" below).

---

## HIGH

### 2. `DELETE /api/v2/app/tenants/{tenancy_id}` had no role check (fixed)
**File:** `src/api/v2/tenants.py:1030` (now `:1032`)

Hard-deletes a tenant's entire financial history (payments, refunds, rent schedule, checkout records) — the one place in this codebase that bypasses the project's own "never hard-delete, use `is_void`" rule, by design, for erroneous-entry cleanup. It required a valid JWT but **no role check**, unlike every sibling mutating endpoint in the same file. Any authenticated account (including "staff") could wipe any tenant's history.

**Fix applied:** `if user.role != "admin": raise HTTPException(403)` before any DB access — admin-only, stricter than the `admin|staff` bar used by lesser mutations, since this one is irreversible.

### 3. `POST /api/v2/app/tenants/{tenancy_id}/transfer-room` had no role check (fixed)
**File:** `src/api/v2/tenants.py:1008` (now `:1010`)

Any authenticated account could move any tenant to any room, changing rent/deposit as a side effect — no role gate, inconsistent with the `admin|staff` check on neighboring endpoints in the same file.

**Fix applied:** `if user.role not in ("admin", "staff"): raise HTTPException(403)`.

---

## MEDIUM

### 4. Read endpoints authorized by "any valid JWT," not by role (fixed)
**Files:** `src/api/v2/tenants.py` (`list_tenants`, `search_tenants`, `get_previous_stays`, `get_tenant_dues`), `notices.py` (`get_active_notices`), `checkouts.py` (`get_checkouts`), `rooms.py` (`check_room_availability`), `reporting.py` (`get_collection_summary`, `get_collection_history`), `analytics.py` (`get_occupancy`)

None of these checked `user.role` — any Supabase Auth user with a valid session got full tenant PII, rent, dues, deposit, and occupancy data. Not exploitable **today** (only 5 accounts exist, all `admin`/`staff`, provisioned by `scripts/create_auth_users.py` — no self-signup path exists anywhere in `web/`), but `get_current_user()` silently defaults `role` to `"tenant"` for any account that ever lacks the claim. The moment a lower-privileged account type is provisioned (tenant self-service login, a future lead account, a password-reset-created account with no role set) it would get read access to every other tenant's financial data through these routes with zero additional check.

**Fix applied:** added `if user.role not in ("admin", "staff"): raise HTTPException(403)` to all nine routes above — fail-closed, matching the pattern already used by every mutating endpoint. Safe under current account population (all 5 existing accounts are `admin`/`staff`), closes the gap before it becomes live.

### 5. `org_id` is decorative — never used to scope a query
**Files:** `src/api/v2/auth.py`, every `src/api/v2/*.py` query keyed by `tenancy_id`/`payment_id`/etc.

`AppUser.org_id` is only ever stamped onto new `AuditLog`/`RentRevision` rows for record-keeping; no query anywhere filters `WHERE org_id = user.org_id`. This is single-tenant today (one PG business, `org_id` always `1`) so it's **not exploitable now** — but the field's presence signals multi-org SaaS intent (per the roadmap docs). If a second org is ever onboarded on the same DB/backend, every numeric-ID endpoint in this codebase becomes a cross-customer IDOR (any staff/tenant account could enumerate another org's `tenancy_id`/`payment_id`).

**Not fixed** — no code change made; this needs a real design decision (org-scoped dependency injection across every v2 router) before it matters, and making that change today with only one org would be speculative. **Action:** revisit before onboarding any second organization — do not treat "single-tenant so far" as permanent.

---

## LOW

### 6. `src/database/rls_policies.sql` is misleading dead code (fixed — documented, not deleted)
The backend connects to Postgres as the `postgres` role (table owner), which bypasses RLS entirely regardless of these policies, and the `app.caller_phone` session variable every policy depends on is never `SET` anywhere in the codebase. Real authorization correctly lives in the FastAPI/JWT layer — but anyone reading this file cold would assume DB-level tenant isolation exists when it provides none.

**Fix applied:** added a prominent header to the file stating it is not enforced and why, pointing at this audit.

### 7. Stale doc with hardcoded webhook shared-secret (fixed)
**File:** `docs/reference/APPS_SCRIPT_SYNC.md`

Hardcoded token `kozzy-sync-2026` for `X-Sync-Token` auth on `/api/sync/source-sheet`. Confirmed `src/api/sync_router.py` no longer exists and isn't registered anywhere — the endpoint isn't live, so this isn't currently exploitable. Risk is only if someone resurrects the endpoint from git history without rotating the token, since it's sitting in a committed doc.

**Fix applied:** replaced all three occurrences of the real-looking token with `REPLACE_WITH_NEW_SECRET` placeholders and added a "STALE — endpoint removed" banner.

---

## Checked and confirmed SAFE (no action needed)

- **CORS** (`main.py`): explicit origin whitelist (localhost dev + `kozzy.vercel.app` + `app.getkozzy.com`), not `"*"` — safe combined with `allow_credentials=True`.
- **WhatsApp webhook signature** (`src/whatsapp/webhook_handler.py`): `X-Hub-Signature-256` verified via `hmac.compare_digest` (timing-safe), fails closed (503) if the app secret is unset. GET verify-token challenge doesn't leak the token.
- **Session cookies**: PWA uses `@supabase/ssr`'s cookie-based session storage throughout (`middleware.ts`, `auth/callback/route.ts`) — no tokens read from `localStorage`/`sessionStorage` for authorization decisions.
- **JWT verification** (`src/api/v2/auth.py`): explicit algorithm allowlist (ES256/RS256 via JWKS, HS256 fallback with shared secret), audience-checked — no algorithm-confusion or `"none"`-alg path.
- **Password reset flow**: `next` redirect param is whitelisted (no open redirect); code exchange happens server-side; can't be used to change an arbitrary user's password without a valid reset session.
- **XSS**: no `dangerouslySetInnerHTML` anywhere in `web/` (JSX default-escapes). Only raw `innerHTML` usage is in the static, no-backend `web/public/mockups/kozzy.html` sales demo — not reachable with attacker-controlled input.
- **SQL injection**: every raw-SQL f-string in the codebase interpolates a fixed table/column name from a Python literal in the same function — never request/WhatsApp-supplied text. All values go through SQLAlchemy bind params.
- **Command/code injection**: no `eval`, `exec`, `pickle.load`, or unsafe `yaml.load` anywhere. All `subprocess` calls use list-argv form (never `shell=True` or a concatenated string).
- **Path traversal**: media/upload handling never builds a filesystem path from user-supplied text — always fixed literals + internal numeric IDs.
- **Prompt injection**: the vision-LLM (Claude Haiku) receipt-reading path never mutates financial records directly — output is either attached to an already-human-logged payment or shown as a preview an admin must confirm. It's also only reachable by the 4 hardcoded staff phone numbers (`role_service.py`) — tenants are silently blocked from the bot entirely, closing off the "malicious tenant image" injection scenario at the authorization layer.
- **Secrets on disk**: no `.env` committed (`.gitignore`'d), only placeholder `.env.example`/`.env.template` files. Repo-wide + `venv`/`node_modules` scan for API-key-shaped strings and JWT-shaped strings found zero real secrets — only false positives inside third-party library source/docs (ecdsa, google-auth, twilio, jose, authlib, botocore examples).
- **DB connection model**: backend connects via SQLAlchemy+asyncpg as the `postgres` role, not the Supabase REST/anon-key path — RLS bypass is total but intentional; the web client never queries Supabase tables directly (grepped for `.from(...)` calls — none found), only uses the Supabase JS client for auth/session.
- **Every `finance.py` and `blacklist.py` route**: verified line-by-line — each uses `_require_admin()` or an explicit role allowlist, genuinely server-enforced (not just a hidden UI button).

---

## Next steps (require your go-ahead — not run yet)

1. **Deploy the code fixes** (auth.py, middleware.ts, tenants.py, notices.py, checkouts.py, rooms.py, reporting.py, analytics.py, create_auth_users.py) to VPS after local testing.
2. **Run `scripts/_migrate_role_to_app_metadata.py --write`** against production once (moves the 5 existing users' role into `app_metadata`). Dry-run first (no `--write`) to see what it would do.
3. After deploy, existing sessions keep their old JWT (role only in `user_metadata`, which the new code no longer reads) until the access token refreshes (~1hr) or the user logs out/in — **admins should log out and back in** right after deploy to avoid a temporary "why can't I see Finance" confusion.
4. Rotate the `SYNC_WEBHOOK_TOKEN` if `sync_router.py` is ever reintroduced (finding 7).
5. Revisit `org_id` scoping (finding 5) before onboarding any second PG business on this backend.
