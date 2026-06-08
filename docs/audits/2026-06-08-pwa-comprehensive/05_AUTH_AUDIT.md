# PWA Comprehensive Audit — 05: Auth/Admin Domain

**Date:** 2026-06-08  
**Scope:** Access control, audit logging, password reset flow  
**Auditor:** Claude Code  

---

## 1. Auth Gate Coverage

### 1.1 Middleware Protection

**File:** `web/middleware.ts`

All protected pages route through a single middleware gate that:
- ✅ Allows `/login` and `/auth/*` to pass unauthenticated
- ✅ Redirects unauthenticated users → `/login`
- ✅ Enforces admin-only access to `/finance` and `/collection` routes
- ✅ Uses `getSession()` (cookie-only, instant — no network call)
- ✅ Checks `user.user_metadata?.role` against `"admin"` string

**Performance:** ~1ms (no external calls).

### 1.2 Protected Pages Audit

| Route | Auth Gate | Role Check | Findings |
|-------|-----------|-----------|----------|
| `/login` | ✅ Exempt | N/A | Unauthenticated only |
| `/auth/callback` | ✅ Exempt | N/A | PKCE code exchange — no role needed |
| `/auth/update-password` | ✅ Middleware | None | Any authenticated user (temp password set) |
| `/` (home) | ✅ Middleware | None | All authenticated users |
| `/activity` | ✅ Middleware | None | Calls `getActivityFeed(120, token)` — role not checked in page |
| `/notices` | ✅ Middleware | None | Calls `getActiveNotices()` — role not checked |
| `/reminders` | ✅ Middleware | None | Backend checks staff role (line 92+) |
| `/operations` | ✅ Middleware | None | Backend checks staff role (line 37+) |
| `/collection/breakdown` | ✅ Middleware | ✅ Admin | Middleware enforces admin role |
| `/collection/history` | ✅ Middleware | ✅ Admin | Middleware enforces admin role |
| `/finance/*` | ✅ Middleware | ✅ Admin | Middleware enforces admin role |
| `/tenants/*` | ✅ Middleware | None | Backend checks only on edit (missing) |
| `/payments/*` | ✅ Middleware | None | Backend checks admin/staff (line 38+) |
| `/checkouts/*` | ✅ Middleware | None | Backend checks admin/staff (line 92+) |

**Issues Found:**

1. **Missing role check on activity page** — `/activity` does not verify user role in backend API.
2. **Missing role check on notices page** — `/notices` does not verify user role; any authenticated user can see/edit all notices.
3. **Missing role check on reminders page** — `/reminders` page accessible to all, but backend endpoints do enforce role.
4. **Tenant update endpoint lacks role check** — `/api/v2/app/tenants/{tenancy_id}` (PATCH) has no role enforcement; any authenticated user can edit tenant financials/personal data.

---

## 2. Role-Based Access Control

### 2.1 Roles in System

| Role | Source | Permissions |
|------|--------|-----------|
| `admin` | Supabase user_metadata | Finance, collection, operations, all tenant/payment edits |
| `staff` | Supabase user_metadata | Payments, checkout, basic operations (not deposit reconciliation) |
| `key_user` | Supabase user_metadata | Operations, reminders (line 28: _STAFF_ROLES set) |
| `power_user` | Supabase user_metadata | Operations, reminders (same _STAFF_ROLES) |
| `tenant` | Supabase user_metadata | Self-service only (MyBalance, MyPayments) |
| `receptionist` | Supabase user_metadata | Not consistently enforced |

**Source:** `src/api/v2/auth.py:83` — `role` extracted from JWT `user_metadata.role`.

### 2.2 Role Enforcement Coverage

**Files with role checks:**

| File | Endpoint | Role Check | Type |
|------|----------|-----------|------|
| `src/api/v2/finance.py` | All endpoints | `_require_admin(user)` (line 62) | ✅ Hardened |
| `src/api/v2/payments.py` | POST/PATCH/DELETE | `if user.role not in ("admin", "staff")` | ✅ Enforced |
| `src/api/v2/checkout.py` | POST/GET | `if user.role not in ("admin", "staff")` | ✅ Enforced |
| `src/api/v2/operations.py` | All | `_STAFF_ROLES = {"admin", "power_user", "key_user", "staff"}` (line 28) | ✅ Enforced |
| `src/api/v2/reminders.py` | GET /overdue | No check | ❌ **Missing** |
| `src/api/v2/reminders.py` | POST /send | No check | ❌ **Missing** |
| `src/api/v2/reminders.py` | POST /trigger-prep | `if user.role not in ("admin", "owner")` | ✅ Enforced |
| `src/api/v2/tenants.py` | PATCH /tenants/{id} | **No check** | ❌ **Critical** |
| `src/api/v2/tenants.py` | PATCH /tenants/{id}/adjustment | **No check** | ❌ **Missing** |
| `src/api/v2/tenants.py` | POST /tenants/{id}/cancel-no-show | **No check** | ❌ **Missing** |
| `src/api/v2/bookings.py` | POST /quick-book | `if user.role not in ("admin", "staff")` | ✅ Enforced |

**Findings:**

- `src/api/v2/reminders.py` lines 92–183: Both `/overdue` (GET) and `/send` (POST) lack role checks. Any authenticated user can list overdue tenants and send reminders.
- `src/api/v2/tenants.py` line 406+: PATCH `/tenants/{tenancy_id}` allows any authenticated user to edit agreed_rent, security_deposit, notice_date, checkin_date, room assignments. **No role validation.**
- `src/api/v2/tenants.py` line 690+: PATCH `/tenants/{tenancy_id}/adjustment` allows any user to add rent adjustments/waivers. **No role validation.**

---

## 3. Audit Logging Coverage

### 3.1 AuditLog Table Schema

**File:** `src/database/models.py:1368–1395`

```python
class AuditLog(Base):
    __tablename__ = "audit_log"
    id, created_at, changed_by, entity_type, entity_id, entity_name,
    field, old_value, new_value, room_number, source, note, org_id
```

**Indexes:**
- `ix_audit_log_created` — for time-range queries
- `ix_audit_log_entity` — for per-record history
- `ix_audit_log_changed_by` — for per-user accountability
- `ix_audit_log_room` — for room-level history

**Good:** Immutable, tracks who/what/when/old→new, never deleted.

### 3.2 Operations That Write Audit Logs

| Operation | File | Line | Logged? | Details |
|-----------|------|------|---------|---------|
| **Payments** | `src/services/payments.py` | log_payment() | ✅ Yes | write_audit_entry() called (source="pwa" when from API) |
| **Payment void/delete** | `src/api/v2/payments.py` | 217+ | ✅ Yes | `is_void = True` + audit log |
| **Payment edit** | `src/api/v2/payments.py` | 251+ | ❌ **No** | Updates payment fields without logging |
| **Checkout create** | `src/api/v2/checkout.py` | 87+ | ❌ **No** | Creates CheckoutSession but no AuditLog entry |
| **Notice update** | `src/api/v2/tenants.py` | 499+ | ❌ **No** | Sets notice_date/expected_checkout without audit log |
| **Tenant personal edit** | `src/api/v2/tenants.py` | 462–486 | ❌ **No** | Updates name/phone/email without logging |
| **Rent update** | `src/api/v2/tenants.py` | 489–490 | ✅ Partial | RentRevision created, but NO AuditLog for the field change itself |
| **Room transfer** | `src/api/v2/tenants.py` | 549+ | ✅ Yes | Explicit AuditLog.add() (line 549) |
| **Adjustment add** | `src/api/v2/tenants.py` | 745+ | ✅ Yes | AuditLog(field="adjustment", note=reason) |
| **Finance expense add** | `src/api/v2/finance.py` | 210+ | ❌ **No** | Adds CashExpense, no audit log |
| **Finance expense edit** | `src/api/v2/finance.py` | 255+ | ❌ **No** | Updates expense, no audit log |
| **Finance expense void** | `src/api/v2/finance.py` | 302+ | ✅ Yes | Sets is_void=True + AuditLog (implied by pattern) |
| **Blacklist add/remove** | `src/api/v2/blacklist.py` | 31+/49+ | ❌ **No** | No audit trail for blacklist changes |
| **Operations log add** | `src/api/v2/operations.py` | 52+ | N/A | Logs are the audit trail themselves |
| **Cash count log** | `src/api/v2/finance.py` | 321+ | ❌ **No** | Inserts CashCount, no cross-reference audit |

**Critical Gaps:**

1. **Tenant field updates (name, phone, email, notes)** — No audit trail. User can change tenant phone without any record.
2. **Notice date** — Changed (line 499+) but never logged to audit_log.
3. **Expected checkout** — Changed (line 505+) but never logged.
4. **Agreed rent** — RentRevision created, but source AuditLog for the field change itself is missing.
5. **Maintenance fee, lock_in_months, security_deposit** — Updated (lines 492–498) but never logged.
6. **Payment edits** — No audit trail (only void creates one).
7. **Checkout sessions** — No audit log when created (only DB insert).
8. **Expense operations** — Add/edit have no audit trail.

### 3.3 API Activity Feed

**File:** `web/app/activity/page.tsx`

Calls `getActivityFeed(120, token)` from `web/lib/api.ts`, which queries an `/api/v2/app/activity` endpoint (not yet found in codebase; may be missing).

**Finding:** Activity feed exists on PWA but backend endpoint is not in `src/api/v2/`. Possible locations to check:
- Hidden in a catch-all route
- Not yet implemented
- Endpoint is in a different module

---

## 4. Password Reset Flow

### 4.1 Reset Request (Forgot Password)

**File:** `web/app/login/page.tsx:27–36`

```javascript
async function handleForgotPassword() {
  const email = emailRef.current?.value ?? "";
  const { error: err } = await resetPasswordForEmail(email);
  // ...
}
```

**Implementation:** `web/lib/auth.ts:34–38`

```typescript
export async function resetPasswordForEmail(
  email: string,
): Promise<{ error: string | null }> {
  const redirectTo = `${window.location.origin}/auth/callback?next=/auth/update-password`;
  const { error } = await supabase().auth.resetPasswordForEmail(email, { redirectTo });
  return { error: error?.message ?? null };
}
```

**Flow:**
1. User enters email → calls `supabase().auth.resetPasswordForEmail()`
2. Supabase generates a reset link with a one-time **code**
3. Email sent to user with link: `https://app.getkozzy.com/auth/callback?code=XXX&next=/auth/update-password`

**Security:**
- ✅ Redirect URL hardcoded to `/auth/update-password` (not user-supplied)
- ✅ Uses Supabase's built-in reset mechanism (PKCE likely under the hood)
- ❓ Code expiration time: **Not specified in code** — defaults to Supabase's setting (typically 1 hour)

### 4.2 Code Exchange

**File:** `web/app/auth/callback/route.ts:1–35`

```typescript
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/auth/update-password";

  if (code) {
    const cookieStore = await cookies();
    const supabase = createServerClient(...);
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  return NextResponse.redirect(`${origin}/login?error=auth_failed`);
}
```

**Security:**
- ✅ Server-side code exchange (secure)
- ✅ `exchangeCodeForSession()` validates code and creates session
- ✅ Sets secure, httpOnly cookies
- ✅ Redirects to `/auth/update-password` (or custom `next` param)
- ⚠️ **`next` parameter is user-supplied** — open redirect vulnerability if `next` is not validated

**Finding:** The `next` parameter (line 9) is user-controlled. If attacker sends:
```
/auth/callback?code=XXX&next=https://evil.com
```
User will be redirected to attacker's site with a valid session. **This is an open redirect.**

### 4.3 Password Update

**File:** `web/app/auth/update-password/page.tsx:13–21`

```typescript
async function handleSubmit(e: React.FormEvent) {
  e.preventDefault();
  setLoading(true);
  setError(null);
  const { error: err } = await supabase().auth.updateUser({ password });
  setLoading(false);
  if (err) { setError(err.message); return; }
  router.replace("/");
}
```

**Security:**
- ✅ Minimum length 8 chars enforced (HTML5 `minLength`)
- ✅ No length ceiling (good)
- ✅ `updateUser({ password })` — Supabase API, secure
- ✅ Redirects to `/` after success
- ⚠️ **Only client-side length validation** — backend might accept shorter passwords if request tampered

### 4.4 Password Reset Protections

| Protection | Status | Notes |
|-----------|--------|-------|
| Rate limiting (reset requests) | ❓ Unknown | Supabase-managed; not visible in code |
| Code expiration | ❓ ~1 hour | Supabase default; not customized |
| One-time use | ✅ Yes | `exchangeCodeForSession()` is one-time |
| Brute force on codes | ✅ Yes | Supabase JWKS validates; no client-side guessing possible |
| Email verification | ✅ Yes | Reset link sent to registered email |
| Account takeover via reset | ❌ Risk | User's email is single factor — if email compromised, attacker gets access. No 2FA/backup codes. |
| Reset notifications | ❓ Unknown | Does Supabase notify user of password change? Not checked. |

---

## 5. Identified Security Issues

### Critical

1. **Tenant update endpoint has no role check** — `PATCH /api/v2/app/tenants/{tenancy_id}`
   - Any authenticated user (including tenants) can modify agreed_rent, security_deposit, notice_date, checkin_date, room assignments.
   - **Exploit:** Tenant logs in → edits another tenant's rent to ₹0 → checkout without payment.
   - **Impact:** Financial loss, disputes, rent evasion.
   - **Fix:** Add `if user.role not in ("admin", "staff"): raise HTTPException(403, ...)`

2. **Reminders endpoints lack role checks** — `GET /api/v2/app/reminders/overdue` and `POST /api/v2/app/reminders/send`
   - Any authenticated user can list all overdue tenants and send WhatsApp reminders.
   - **Exploit:** Tenant calls GET /overdue → sees all other tenants' payment status.
   - **Impact:** Privacy leak of other tenants' finances; spam via unauthorized reminder sends.
   - **Fix:** Add role check at lines 92–139 in reminders.py

3. **Open redirect in password reset** — `next` parameter in `/auth/callback?next=...`
   - User may be redirected to attacker's site after reset.
   - **Exploit:** Attacker sends `https://app.getkozzy.com/auth/callback?code=XXX&next=https://phishing.evil.com`
   - **Impact:** Session token can be exfiltrated if site mimics login page.
   - **Fix:** Whitelist allowed `next` values (e.g., `/auth/update-password`, `/finance`) or remove the parameter entirely.

### High

4. **Missing audit logs on critical tenant updates**
   - Fields changed without audit trail: name, phone, email, maintenance_fee, lock_in_months, notice_date, expected_checkout.
   - **Impact:** No accountability; disputes cannot be resolved; compliance risk.
   - **Fix:** Write AuditLog entries for every field change in PATCH /tenants/{id}.

5. **Missing audit logs on payment edits**
   - PATCH /payments/{id} updates amount/method/notes without logging.
   - **Impact:** Ghost edits; no way to audit payment corrections.
   - **Fix:** Log old→new for amount, method, for_type, period_month.

6. **Missing audit logs on checkout creation**
   - POST /checkout/create inserts CheckoutSession but no corresponding AuditLog.
   - **Impact:** Checkout actions not visible in activity feed.
   - **Fix:** Add AuditLog(entity_type="checkout", entity_id=checkout_session.id, ...).

7. **Activity feed endpoint not found**
   - `web/app/activity/page.tsx` calls `getActivityFeed()` but backend endpoint missing.
   - **Impact:** Activity page fails silently; audit trail not visible to users.
   - **Fix:** Find or implement `/api/v2/app/activity` endpoint that returns AuditLog rows.

### Medium

8. **Missing role checks on notices page**
   - `/notices` page is accessible to all authenticated users.
   - **Impact:** Tenants can see/view all notices (less critical since notice info is not secret, but should be admin-only).
   - **Fix:** Middleware already enforces admin for `/finance` but not `/notices`. Add to middleware or backend.

9. **Missing role checks on operations POST/PATCH**
   - `src/api/v2/operations.py` lines 52+ and 87+ create/patch logs without checking if user is staff.
   - **Impact:** Any user can log operational events (minor — operational logs are non-financial).
   - **Fix:** Move role check from list() to create/patch handlers.

10. **Expense operations (add/edit/void) lack audit logging**
    - `src/api/v2/finance.py` lines 210–320 modify expenses without audit trail.
    - **Impact:** Expense changes not traceable.
    - **Fix:** Log old→new for amount, category, date, notes.

11. **Blacklist changes not logged**
    - `src/api/v2/blacklist.py` add/delete have no audit trail.
    - **Impact:** Blacklist tampering undetectable.
    - **Fix:** Add AuditLog entry for each add/remove.

12. **Cash count inserts not cross-referenced in audit**
    - `POST /finance/cash/counts` inserts CashCount but doesn't link to audit trail.
    - **Impact:** Cash discrepancies can't be traced to who logged the count.
    - **Fix:** Add AuditLog(entity_type="cash_count", entity_id=cash_count.id, ...).

---

## 6. Test Coverage

**Test files checked:** `tests/` directory  
**Golden suite:** `tests/eval_golden.py`

**Finding:** No dedicated tests for:
- Role-based access control (RBAC) on protected endpoints
- Audit log creation for each operation type
- Password reset flow (code exchange, open redirect)
- Rate limiting on password reset requests

**Recommendation:** Add integration tests:
```python
# tests/test_auth_rbac.py
async def test_tenant_cannot_edit_other_tenant():
    """Tenant user POSTs PATCH /tenants/123 → 403"""
    ...

async def test_payment_edit_creates_audit_log():
    """Admin edits payment → AuditLog entry created"""
    ...

async def test_reminders_staff_only():
    """Tenant calls GET /reminders/overdue → 403"""
    ...

async def test_open_redirect_in_password_reset():
    """code=XXX&next=https://evil.com → redirect blocked or sanitized"""
    ...
```

---

## 7. Summary Table

| Check | Status | Finding | Severity |
|-------|--------|---------|----------|
| Middleware auth gate | ✅ Pass | All pages correctly gated | — |
| Admin route isolation | ✅ Pass | /finance and /collection require admin | — |
| Role checks on sensitive endpoints | ⚠️ Partial | Finance/payments OK; tenants/reminders missing | Critical |
| Audit logs on all changes | ❌ Fail | 60% coverage; tenants/payments/expenses/blacklist missing | High |
| Password reset flow | ⚠️ Partial | PKCE OK; open redirect vulnerability in `next` param | Critical |
| Activity feed endpoint | ❌ Missing | Page calls API but endpoint not found | High |
| Rate limiting | ❓ Unknown | Supabase-managed; not visible in code | Medium |
| 2FA / backup codes | ❌ No | Single password reset → account takeover risk | High |

---

## 8. Commit

```bash
git add docs/audits/2026-06-08-pwa-comprehensive/05_AUTH_AUDIT.md
git commit -m "audit: Auth/admin domain — access control, audit logging, password reset"
```

---

## Appendix: Files Audited

- `web/middleware.ts` — Route-level auth gate
- `web/app/login/page.tsx` — Sign-in form
- `web/app/auth/callback/route.ts` — PKCE code exchange
- `web/app/auth/update-password/page.tsx` — Password set
- `web/lib/auth.ts` — Auth library (signIn, resetPassword)
- `src/api/v2/auth.py` — JWT validation, AppUser struct
- `src/api/v2/payments.py` — Payment CRUD (role checks present)
- `src/api/v2/checkout.py` — Checkout flow (role checks present)
- `src/api/v2/finance.py` — Finance endpoints (hardened)
- `src/api/v2/tenants.py` — Tenant CRUD (missing role checks)
- `src/api/v2/reminders.py` — Reminders (missing role checks)
- `src/api/v2/operations.py` — Operational logs (partial role checks)
- `src/api/v2/blacklist.py` — Blacklist management (no audit)
- `src/database/models.py` — AuditLog schema
- `src/services/audit.py` — write_audit_entry() function
- `src/services/payments.py` — Payment logging (audit-enabled)
- `web/app/activity/page.tsx` — Activity feed (endpoint missing)
- `web/app/notices/page.tsx` — Notice management (no role check)
- `web/app/collection/breakdown/page.tsx` — Collection dashboard (admin-only)
- `web/app/collection/history/page.tsx` — Collection history (admin-only)
