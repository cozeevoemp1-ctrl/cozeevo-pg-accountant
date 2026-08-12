# Security Audit — PG Accountant / Kozzy

**Date:** 2026-08-08
**Type:** Full offensive ("hacker-mindset") audit — whole codebase + live infrastructure checks.
**Status:** AUDIT ONLY. No fixes are deployed. One reference fix exists in an isolated git worktree (`../pg-security-sandbox`, branch `security-redo`) with passing tests — it is NOT on `master` and NOT live.

> ## ⚠️ Read this first — the rollout lesson
> An earlier attempt this session deployed the auth fix and **broke the live PWA** (403s across every page). Root cause: switching the role source invalidated every in-flight session token, and 4 of 5 frontend role-reads were missed. It was reverted; production is healthy. **Every fix in this document carries an "end-to-end impact" section describing what it can break. Nothing here should be deployed without working through that section, testing in the sandbox against real flows, and forcing a re-login where noted.**

---

## Severity summary

| # | Finding | Severity | Live now? | Verified |
|---|---------|----------|-----------|----------|
| C-1 | Public Supabase buckets (KYC IDs, signed agreements) with guessable paths | **CRITICAL** | ✅ YES (buckets `public=true` confirmed live) | live-checked |
| C-2 | Privilege escalation via self-editable `user_metadata.role` | ~~CRITICAL~~ **FIXED IN CODE 2026-08-12** (⏳ pending VPS deploy + re-login) | code reads `app_metadata` in all 5 sites; 7 guard tests pass | fixed + tested |
| C-3 | Anon key wide-open grants; only empty-policy RLS deny-all protects tables | ~~MEDIUM~~ **RESOLVED 2026-08-11** | ✅ FIXED (anon/authenticated grants revoked, existing + future) | fix live-tested (anon → 401) |
| H-1 | No upper bound on payment amount (₹12cr fat-finger accepted) | **HIGH** | ✅ YES | code-read |
| H-2 | Refund cap validated against client-supplied deposit → cash drain | **HIGH** | ✅ YES | code-read |
| H-3 | `DELETE /tenants/{id}?force=true` erases frozen financial history | **HIGH** | ✅ YES | code-read |
| H-4 | 11 API endpoints missing role checks (IDOR / data exposure) | **HIGH** | ✅ YES | code-read |
| M-1 | `POST /auth/send-otp` fail-open (unauth WhatsApp send) | **MEDIUM** | ✅ YES | code + .env checked |
| M-2 | `edit_payment` bypasses freeze trigger, unbounded, any month | **MEDIUM** | ✅ YES | code-read |
| M-3 | Dues wiped via `PATCH /tenants/{id}` (future check-in date) | **MEDIUM** | ✅ YES | code-read |
| M-4 | `extract-id` unauthenticated LLM call, no rate/size cap | **MEDIUM** | ✅ YES | code + .env checked |
| M-5 | Unbounded negative `adjustment` zeroes dues | **MEDIUM** | ✅ YES | code-read |
| M-6 | `org_id` never scopes any query (multi-org IDOR when 2nd org onboarded) | **MEDIUM** | ⚠️ latent | code-read |
| L-1 | Signed agreement PDFs on public `/static` (regen-pdf path) | **LOW** | ✅ YES | code-read |
| L-2 | `/documents` mount unauth; `LocalOnlyMiddleware` no-op behind nginx | **LOW** | ✅ (empty dir today) | code-read |
| L-3 | In-memory rate limiter is per-worker, resets on deploy | **LOW** | ✅ YES | code-read |
| L-4 | Duplicate-payment guard bypassable by ₹1 delta | **LOW** | ✅ YES | code-read |

**Confirmed SAFE (checked, no action):** WhatsApp webhook HMAC signature (fail-closed), CORS whitelist, JWT algorithm allowlist, password-reset flow, XSS (no `dangerouslySetInnerHTML`), SQL/command injection (parameterized, no eval/exec/unsafe subprocess/pickle/yaml), onboarding token enumeration (UUID, no integer id, no oracle), tenant self-approval (submit only moves pending→pending_review, no financial fields), X-Forwarded-For rate-limit spoofing (uvicorn proxy-headers correct), OCR/vision never writes a payment amount, no un-void via API, service-role key server-side only, no secrets committed to git, FastAPI debug endpoints disabled, `/media` JWT-gated with path-traversal guard, KYC upload content-type forced (no stored-XSS).

---

## CRITICAL

### C-1 — Public Supabase buckets with guessable object paths → unauthenticated download of tenant government IDs, selfies, signatures, and signed agreements
**Live-verified:** queried the production Storage API — `kyc-documents` and `agreements` are both `public=true` right now.
**Where:** `src/services/storage.py:66` and `scripts/migrate_media_to_supabase.py:80` create every bucket `{"public": True}`. `public_url()` (`storage.py:46-48`) returns raw `.../object/public/{bucket}/{path}` URLs. **No `createSignedUrl` anywhere in the codebase.**
**Guessable paths:**
- Receipts: `{YYYY-MM}/{payment_id}.jpg` — `payment_id` is a **sequential integer** (`payments.py:541`).
- KYC: `onboarding/{token8}/{selfie|id_proof|signature}.ext` — `token8` = first 8 hex of a UUID (32 bits) (`onboarding_router.py:1215`).
- Staff signatures: `staff-signatures/{phone}.png` — raw phone, and staff phones are in public docs.
- Agreements: `{YYYY-MM}/{filename}.pdf`.

**Exploit (no auth, no login):** the project ref is public (in the web bundle). An attacker iterates
`https://<ref>.supabase.co/storage/v1/object/public/receipts/2026-08/1.jpg`, `/2.jpg`, … and `.../agreements/2026-08/…` → mass-downloads every payment receipt and signed rental agreement. Government-ID selfies need brute-forcing a 32-bit token space per session (feasible at scale).

**Impact:** Wholesale exfiltration of tenant PII — government IDs, selfies, signatures, home addresses, payment screenshots. This is the single most serious finding and it is **live**.

**Fix:** Flip `kyc-documents`, `agreements`, (and `receipts` if created) to `public:false`; serve via short-lived `createSignedUrl` or a JWT-gated FastAPI proxy (like `/media`); randomize object names to UUIDs. Rename existing objects — current names stay guessable even after going private if an old public URL was ever shared.

**⚠️ End-to-end impact of the fix — WILL break things if done naively:**
- The app stores and returns **raw public URLs** in `saved_files`, `payment.receipt_url`, agreement links, and the PWA `<img>`/PDF viewers load them directly. The moment buckets go private, **every one of those URLs 400s** — receipts, KYC previews, and agreement downloads break across the PWA, the Bookings page, and any WhatsApp-delivered agreement link.
- Correct sequencing: (1) add a signed-URL generator in `storage.py`; (2) change every read path (`payments.py` receipt read, onboarding detail, agreement serve, PWA components that render these) to request a fresh signed URL through the backend; (3) migrate/rename existing objects; (4) *then* flip the bucket flag. Flipping the flag first = broken images everywhere.
- Test in sandbox: upload a receipt, load it in the PWA, open a booking's KYC, download an agreement — all must work via signed URLs before deploy.

### C-2 — Privilege escalation: role read from self-editable `user_metadata`
**Where:** `src/api/v2/auth.py:75,83` (`role=meta.get("role")` from `user_metadata`), `web/middleware.ts:51`, and 4 frontend reads (`web/lib/auth-server.ts:13`, `web/components/auth/auth-provider.tsx:61,75`, `web/app/finance/page.tsx:36`).
**Description:** `user_metadata` (`raw_user_meta_data`) is self-editable by any authenticated user via `supabase.auth.updateUser({ data: {...} })` — user's own token, no admin key. `app_metadata` is the admin-API-only field; the codebase never used it.
**Exploit:** any logged-in account (e.g. staff receptionist) runs in the browser console:
```js
await supabase.auth.updateUser({ data: { role: "admin" } })
```
→ new validly-signed JWT with `user_metadata.role: "admin"` → passes every `_require_admin` check (finance P&L, investment data, blacklist) and the PWA `/finance` gate.
**Reproduced:** `tests/test_auth_role_source.py` in the sandbox — `test_self_set_user_metadata_role_is_ignored` fails on current code, passes on the fix.

**Fix:** read `role`/`org_id` from `app_metadata` only (no fallback); write them there in `create_auth_users.py` via the Admin API; update all 5 frontend/backend reads; migrate the 6 existing users (`scripts/_migrate_role_to_app_metadata.py`, already written — moves role into app_metadata, leaves user_metadata intact).

**⚠️ End-to-end impact — THIS IS WHAT BROKE PRODUCTION EARLIER:**
- The moment `auth.py` reads `app_metadata`, **every existing session's JWT (which has role only in `user_metadata`) resolves to `"tenant"` → 403 on every admin/staff endpoint.** The whole app appears broken until each user's token refreshes (~1hr) or they log out/in.
- There are **5 places** that read the role, not 1: `auth.py` (backend), `middleware.ts`, `auth-server.ts`, `auth-provider.tsx` (×2), `finance/page.tsx`. Missing any one leaves the UI half-broken even after a fresh login. The earlier attempt fixed only `auth.py` + `middleware.ts` → still broken.
- Correct sequencing: (1) run the migration script `--write` FIRST so all accounts have `app_metadata.role`; (2) deploy code that reads `app_metadata` across all 5 files; (3) force every admin/staff to log out and back in immediately (their old token is now role-less). Do NOT add a `user_metadata` fallback "to be safe" — that reopens the vulnerability.
- Sandbox test: simulate an old-token payload (role only in user_metadata) → must resolve to `tenant` (fail-closed); simulate app_metadata payload → admin. Both covered by `test_auth_role_source.py`. Note: the account migration was already run once this session (all 6 accounts have `app_metadata.role` set AND still have `user_metadata.role`), so step 1 is effectively done — but re-verify before deploy.

**✅ FIXED IN CODE 2026-08-12 (commit on master; NOT yet deployed to VPS):**
- All 5 read sites now read `role`/`org_id` from `app_metadata` only, no `user_metadata` fallback: `src/api/v2/auth.py` (backend), `web/middleware.ts`, `web/lib/auth-server.ts`, `web/components/auth/auth-provider.tsx` (×2), `web/app/finance/page.tsx`. Display-only `name` stays from `user_metadata`.
- `tests/test_auth_role_source.py` (7 tests) passes, incl. the exploit case (`test_self_set_user_metadata_role_is_ignored`) and fail-closed (`test_user_metadata_only_token_fails_closed` → old token = tenant).
- **Precondition re-verified 2026-08-12:** all 6 auth accounts have `app_metadata.role` (dry-run of `_migrate_role_to_app_metadata.py`); migrated 2026-08-08, so 4 days of hourly token refresh means live JWTs already carry `app_metadata.role` → the 403-storm risk that broke prod on 08-08 is now largely pre-mitigated.
- **REMAINING deploy steps (Kiran-controlled):** (1) deploy backend (`update.sh` on VPS) + rebuild/redeploy PWA — must ship together, all 5 files; (2) have the 6 admin/staff log out & back in. Fix is fail-closed, so worst case for a stale token is one re-login, never a privilege leak. Backend fix is the real security boundary; frontend gates are UI-only (APIs verify the JWT regardless).

### C-3 — Anon key has wide-open table grants; only empty-policy RLS deny-all stands between the internet and all data
**Downgraded from CRITICAL to MEDIUM after live testing — the breach is NOT currently exploitable, but the protection is one accidental policy away from failing.**

**Live test results (2026-08-08, against production):**
- RLS is **enabled** on every table checked (`tenants`, `payments`, `tenancies`, `rooms`, `bank_transactions`, `refunds` all `relrowsecurity=true`) with **0 policies** each. Postgres RLS-enabled-with-no-policy = deny-all for non-owner roles.
- Anon read test: `GET /rest/v1/tenants` (and rooms, payments, bank_transactions) with the real anon key → **HTTP 200 `[]`** (empty — RLS denies, even though the tables have thousands of rows). ✅ reads blocked.
- Anon write test: `POST /rest/v1/rooms` with the anon key → **`42501 new row violates row-level security policy`**, no row created. ✅ writes blocked.
- So an attacker with the public anon key currently gets **nothing** from PostgREST. The earlier assumption ("RLS off → full table access") was WRONG; RLS is on and protecting the data.

**Why this is still MEDIUM, not resolved — the fragility:**
- The `anon` and `authenticated` roles hold **full table privileges** — `SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER` on `tenants`, `payments`, `rooms`, and (by default grant) the rest of the `public` schema. The ONLY thing preventing a breach is the RLS deny-all-because-no-policy state.
- The instant anyone adds a single permissive policy to any table — e.g. someone building a tenant-facing feature runs `CREATE POLICY ... FOR SELECT USING (true)` on `tenants`, or clicks "enable read access" in the Supabase dashboard — that table becomes **world-readable/writable** through the anon key, because the grants underneath are wide open. There is no second layer.
- `TRUNCATE` is granted to anon and is **not governed by RLS** at all (RLS only covers SELECT/INSERT/UPDATE/DELETE). It's currently unreachable because PostgREST doesn't expose TRUNCATE — but the grant should not exist.

**Fix (defense-in-depth, lower urgency than C-1/C-2 now that reads/writes are confirmed blocked):**
`REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;` (and `... DEFAULT PRIVILEGES ... REVOKE` for future tables). Then anon has no table privileges at all, so even a future accidental permissive policy can't expose data without an explicit grant too. The backend uses the service role (bypasses grants + RLS), so it is unaffected.

**⚠️ End-to-end impact of the fix:**
- Revoking anon/authenticated grants: **should break nothing** — the FastAPI backend connects as service-role/`postgres` (bypasses grants), and the web app never calls `.from()`/`.rpc()` (grep-confirmed — only auth/session). This is a safe, isolated change.
- Still test after: login, password reset, session refresh, and 2-3 data pages — in case any forgotten client path relies on the anon key for data (none found in audit, but confirm).
- Do NOT rely on the current RLS-deny-all as the permanent control; revoking grants makes the safe state explicit rather than incidental.

---

## HIGH

### H-1 — No upper bound on payment amount
**Where:** `src/schemas/payments.py:9,29` — `amount: int = Field(gt=0)`, no `le=`. Only backstop is DB `Numeric(12,2)` (~₹99cr).
**Exploit:** `POST /api/v2/app/payments {amount: 123123123, ...}` → ₹12.3cr payment recorded, flips RentSchedule to paid, mirrors to Google Sheet, feeds P&L/cash/collection KPIs. Matches the ₹12,32,46,246 the collect-payment modal showed.
**Impact:** one typo corrupts collections, P&L, cash position, unit economics, and the Sheet mirror.
**Fix:** `Field(gt=0, le=MAX_SINGLE_PAYMENT)` on create + edit (e.g. ₹5,00,000, configurable); confirmation prompt above a threshold; reject amounts far exceeding outstanding + deposit.
**⚠️ End-to-end impact:** low risk. Pick a ceiling above any legitimate single payment (largest real deposit + rent). Verify the biggest historical real payment in `payments` is below the cap before setting it, or a legit large collection gets rejected. No data migration needed.

### H-2 — Refund cap validated against client-supplied deposit → refund can exceed deposit held
**Where:** `src/api/v2/checkout.py:137-158` (`create_checkout`).
**Description:** `expected_refund = max(security_deposit − maintenance − dues − deductions, 0)` where `security_deposit`, `dues`, `deductions` **all come from the request body**. The check `abs(client_refund − expected_refund) > 100` is a tautology (both sides client-derived). Only `maintenance_due` and the forfeiture flag come from the DB.
**Exploit:** `POST /api/v2/app/checkout/create {security_deposit: 500000, pending_dues: 0, deductions: 0, refund_amount: 500000, ...}` → passes even if the tenant's real `tenancy.security_deposit` is ₹20,000 and they owe ₹40,000. Creates a ₹5,00,000 refund.
**Impact:** refund larger than deposit held, dues ignored — real cash drain, deposit reconciliation corrupted.
**Fix:** ignore `body.security_deposit`/`body.pending_dues`; cap at `min(client_refund, actual_deposit_held) − server_recomputed_dues − deductions`, using `tenancy.security_deposit` (or summed deposit payments) and `src/services/dues.py`. The prefetch at `checkout.py:45-46` already computes real dues — just use it in the create path.
**⚠️ End-to-end impact:** medium. Server-recomputed dues/deposit may differ from what the checkout UI currently shows (which trusts client values), so some checkouts that "passed" before will now correctly reject or adjust. Test: a normal-notice full refund, a with-dues partial refund, a day-stay refund, and a forfeited (no-notice) checkout — all must produce the right server-computed number. Confirm the PWA checkout screen sends fields the server can re-derive, or update it to stop sending authoritative deposit/dues.

### H-3 — `DELETE /tenants/{id}?force=true` hard-deletes payments/refunds and bypasses the freeze
**Where:** `src/api/v2/tenants.py:1030-1151`.
**Description:** with `force=true` it sets `app.allow_historical_write='true'` then raw-`DELETE`s from `payments`, `refunds`, `rent_schedule`, `checkout_records` — including frozen Dec-2025–Mar-2026 rows. The only trail is one AuditLog row with a *count* (not amounts/dates). Violates the project's "never hard-delete financial records" rule; the "void" comment is inaccurate (it deletes).
**Exploit:** `DELETE /api/v2/app/tenancies/{id}?reason=x&force=true` → all financial history for that tenancy erased, unreconstructable.
**Fix:** never hard-delete `payments`/`refunds`; soft-void with per-row audit (amount+date+mode); don't auto-bypass the freeze here; also add the missing role check (admin-only — see H-4).
**⚠️ End-to-end impact:** low. This endpoint is for erroneous-entry cleanup; making it soft-void changes cleanup semantics (voided rows remain, filtered by `is_void`). Verify the Bookings/Tenants UI and all reports already exclude `is_void` rows (they do elsewhere) so voided-not-deleted tenancies don't resurface. No legit flow depends on hard deletion.

### H-4 — Endpoints missing role checks (IDOR / data exposure)
**Where:** no role gate (only `Depends(get_current_user)`): `DELETE /tenants/{id}` and `POST /tenants/{id}/transfer-room` (mutating); `tenants.py` list/search/previous-stays/dues, `notices.py`, `checkouts.py`, `rooms.py`, `reporting.py` ×2, `analytics.py` (reads). `get_current_user` defaults an unset role to `"tenant"`.
**Description:** any valid session can hit these. Mutating ones (delete/transfer) are the worst — any authenticated account could wipe history or move tenants. Reads leak full tenant PII/financials. Not exploitable *today* (only admin/staff accounts exist) but becomes live IDOR the instant any lower-privileged account is provisioned.
**Fix:** add `if user.role not in ("admin","staff")` (or admin-only for delete) to all. Fail-closed.
**⚠️ End-to-end impact:** **this was half of what broke production earlier** — combined with C-2, gating reads meant old-token sessions (role→tenant) got 403 on the pages that call these. The role gate is correct; it MUST ship together with C-2 done properly (migration + re-login) or the same pages 403 again. Test every listed page as admin AND as staff after the C-2 migration.

---

## MEDIUM

### M-1 — `POST /api/v2/app/auth/send-otp` fail-open
**Where:** `src/api/v2/auth_hooks.py:37` — bearer check only runs `if _HOOK_SECRET:`; `SUPABASE_SMS_HOOK_SECRET` is **not set** in `.env`, so the guard is skipped and the route is open. Registered under the internet-reachable `/api/v2/app` prefix.
**Exploit:** `POST /api/v2/app/auth/send-otp {"phone":"+91...","otp":"verify at evil.link"}` → server sends `Your Kozzy login code is: *verify at evil.link*` from the business's WhatsApp sender.
**Real-world caveat (lowers severity):** `_send_whatsapp` sends **free-form** text, which Meta silently drops outside the recipient's 24h customer-service window (the exact CC-reliability behavior found earlier this session). So delivery only succeeds to numbers that messaged the business in the last 24h — an attacker can't spam arbitrary numbers. Still: unauthenticated, delivers attacker text to active users, burns quota.
**Fix:** fail closed when `_HOOK_SECRET` is empty (503, or refuse startup); add per-IP + per-recipient rate limiting; prefer verifying the Supabase webhook signature.
**⚠️ End-to-end impact:** if login-OTP-over-WhatsApp is actually in use, making the secret mandatory means the secret must ALSO be set in the Supabase Auth hook config and the VPS `.env` at the same time, or OTP delivery breaks. Check whether this hook is live in Supabase before failing it closed; if unused, the safest fix is to remove the route entirely.

### M-2 — `edit_payment` bypasses freeze, unbounded, any month
**Where:** `src/api/v2/payments.py:257-346` — sets `app.allow_historical_write='true'` unconditionally; no period check, no amount ceiling. A frozen-month payment's amount/method/for_type can be rewritten to anything. AuditLog is written (good).
**Fix:** block edits to `period_month < current` unless an explicit override; add the H-1 ceiling.
**⚠️ End-to-end impact:** low. Confirm no legitimate workflow routinely edits frozen-month payments (corrections should be rare and can use an explicit override flag). Test editing a current-month payment still works.

### M-3 — Dues wiped via `PATCH /tenants/{id}` (future check-in date)
**Where:** `tenants.py` recalc paths + `rent_schedule.py:38-56`. `checkin_date` accepts any date incl. future (only `agreed_rent>0`, `deposit>=0` validated). Future date → `monthly_dues` returns `not_yet` → 0 dues; live tenant's balance zeroed while `active`. Audited per-field (traceable) but no sanity guard.
**Fix:** bound `checkin_date` (not far future, not before booking); flag/deny recalcs that zero a non-zero balance.
**⚠️ End-to-end impact:** low-medium. Legit date corrections must still work — bound generously (e.g. within ±N months of booking). Test editing a real tenant's check-in date by a few days still recomputes correctly.

### M-4 — `extract-id` unauthenticated LLM call, no rate/size cap
**Where:** `onboarding_router.py:1062-1117` — no `_check_admin_pin`, no `_rate_check`, no `MAX_UPLOAD_SIZE`; base64-decodes body and calls Anthropic Haiku on the owner's key.
**Exploit:** any onboarding-token holder loops the call → unbounded Anthropic spend + memory blow-up from decoding large payloads.
**Fix:** add `_rate_check`, enforce size limit before decode, gate to `pending_tenant`/`pending_review` sessions.
**⚠️ End-to-end impact:** low. The onboarding form's ID-scan feature calls this — keep the rate limit high enough for a real tenant filling the form (a few calls), and confirm the size cap exceeds a normal phone photo (e.g. 10MB).

### M-5 — Unbounded negative `adjustment` zeroes dues
**Where:** `tenants.py:912-999` — `amount` any float; large negative waiver drives dues to 0. Audited + note required, but no magnitude cap or approval gate.
**Fix:** cap `|adjustment|` at effective rent, or require admin role for large waivers.
**⚠️ End-to-end impact:** low. Confirm legit waivers (partial rent concessions) stay under the cap.

### M-6 — `org_id` never scopes any query
**Where:** `auth.py` sets `org_id`; no query filters by it. Single-tenant today (org_id always 1) so not exploitable now, but every numeric-ID endpoint becomes a cross-customer IDOR the moment a 2nd PG business shares this backend.
**Fix:** add org-scoped filtering (or a dependency injecting it) before onboarding any 2nd org. **Do not fix speculatively now** — revisit at multi-org time.

---

## LOW

- **L-1** — `regen-pdf` copies signed agreement PDFs (PII) to public `/static/agreements/{token8}/…` (`onboarding_router.py:860-870`). Not enumerable (32-bit token + name) but unauthenticated URL-guessing. Serve via auth-gated endpoint or Supabase signed URL; stop writing PII to `/static`.
- **L-2** — `/documents` StaticFiles mount (`main.py:239`) has no auth; its only guard `LocalOnlyMiddleware` is a **no-op behind nginx** (all proxied requests look like 127.0.0.1 because uvicorn trusts the proxy). Empty of real KYC today (migrated to Supabase), so low — but anything written there becomes internet-reachable. Drop the mount or JWT-gate it; add nginx `internal;` on sensitive prefixes.
- **L-3** — In-memory rate limiter (`onboarding_router.py:43-53`) is per-worker (×2 with 2 workers) and resets on restart. Back with Redis/DB if the throttles are relied on.
- **L-4** — Duplicate-payment guard (`services/payments.py:250`) hashes amount+mode+period; a ₹1 change defeats it. Fine for semi-trusted staff, noted.

---

## Prioritized remediation plan (deploy order matters)

1. **C-1 (public buckets)** — most urgent, the one confirmed **live PII breach**. Needs the signed-URL refactor first or images break everywhere (see its impact section). Highest effort, highest urgency.
2. **C-2 + H-4 (role source + role gates)** — the privilege-escalation hole. Ship together, in the exact order: verify accounts migrated → deploy all 5 file changes → force re-login. This is the one that already broke prod; treat with maximum care. Account migration is already done (verify before deploy).
3. **H-1, H-2, H-3, M-2, M-5 (money-integrity)** — validation caps + server-side recompute + soft-void. Test each money flow in sandbox.
4. **C-3 (anon grants)** — now MEDIUM: reads/writes are already blocked by RLS deny-all (live-tested), so not urgent, but `REVOKE` the wide-open anon/authenticated grants to make the safe state explicit. Low-risk, safe to do anytime.
5. **M-1, M-4 (unauth endpoints)** — set/rotate secrets, add rate limits. Check the OTP hook is actually in use first.
6. **M-3, L-1, L-2, L-3, L-4** — hardening, lower urgency.
7. **M-6 (org scoping)** — only at multi-org time.

**Process rule going forward (from today's incident):** no security fix ships without (a) its end-to-end impact worked through, (b) a sandbox test proving both the fix AND that existing flows still work, (c) a deploy sequence that accounts for in-flight sessions. The reference sandbox is `../pg-security-sandbox` (branch `security-redo`).

---

## Verification evidence
- **C-1** — live query to production Storage API returned `kyc-documents public=true`, `agreements public=true` (2026-08-08). **Confirmed live breach.**
- **C-2** — `tests/test_auth_role_source.py` (sandbox) — 7 tests; the exploit case fails on `master`, passes on the fix.
- **C-3** — live-tested against production with the real anon key: catalog shows RLS enabled + 0 policies on all tables; anon SELECT → `200 []` (empty), anon INSERT → `42501 row-level security policy` violation. **Reads and writes confirmed blocked** → downgraded to MEDIUM (fragile grants, not a live breach). Wide-open anon grants (SELECT/INSERT/UPDATE/DELETE/TRUNCATE) confirmed present via `information_schema.role_table_grants`.
- **H-1/H-2/H-3/M-2/M-5** — direct code reads (line refs above).
- **M-1/M-4** — code + confirmed `SUPABASE_SMS_HOOK_SECRET` absent from `.env`.
- Round-1 SAFE items re-confirmed by the deeper agents (webhook HMAC, JWT alg, no injection, no committed secrets).

## Coverage & honesty note
This audit covered: auth/authorization (JWT, roles, RLS, grants, IDOR), the full public/unauthenticated attack surface (onboarding, QR, webhook, static mounts), storage/bucket privacy, secrets exposure (repo + git history + client bundle), injection (SQL/command/path/prompt/XSS), CORS/session/cookies, and financial-integrity/business-logic abuse. Three independent agent passes plus direct verification of every finding. **No audit can prove zero vulnerabilities exist** — this reduces known risk to the items above. Areas deliberately not deep-tested (would need a live pentest / different tooling): dependency CVEs (`npm audit`/`pip-audit` not run here), timing side-channels, the nginx/VPS host config itself, and Meta/Supabase account-takeover paths outside this codebase. Recommend running `npm audit` + `pip-audit` and reviewing VPS/nginx hardening as a follow-up.
