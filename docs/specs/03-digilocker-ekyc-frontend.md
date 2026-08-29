# Spec 03 — DigiLocker e-KYC (onboarding form UI)

## Goal
The tenant-facing onboarding form (`static/onboarding.html`, Step 3 — "Upload
your Aadhaar") gains a "Verify with DigiLocker" action that replaces blind
trust in OCR: tenant consents → redirected to DigiLocker → comes back
verified → form auto-fills from the verified pull and the "Next" button
unlocks. If verification fails/unavailable, the existing OCR path stays as a
manual-review fallback, clearly labeled as such.

Depends on Spec 02 (backend) being implemented first — this spec only wires
the UI to `POST /{token}/kyc/start` and `GET /{token}/kyc/callback`.

## Design decisions
- **No new frontend framework/page.** The tenant form is plain HTML/JS in
  `static/onboarding.html` (not a Next.js `web/app` route — that side is
  admin-only, e.g. `web/app/onboarding/bookings/page.tsx`). This feature
  extends that same file, matching its existing patterns (see the current
  `extract-id` fetch call around line 1299).
- **Consent notice before redirect**: DPDP Act 2023 requires clear consent —
  a short line of copy above the "Verify with DigiLocker" button stating what
  is fetched (Aadhaar details) and why (identity verification for tenancy),
  before the tenant is sent off-site.
- **Status-driven UI, not step-driven**: Step 3 shows one of three states —
  not started / verifying (waiting on callback redirect) / verified (green,
  fields locked & auto-filled) / failed (shows the existing manual
  upload+OCR path as fallback, clearly labeled "manual review required").
- **"Next" button gating mirrors the backend gate** in Spec 02 — the button
  is disabled client-side when `kyc_status` isn't `verified` or
  `unverified_manual`, but this is UX only; the real enforcement is the
  server-side check on `POST /{token}/submit`.

## Implementation
1. In `static/onboarding.html` Step 3 (around line 713-770):
   - Add a "Verify with DigiLocker" button above the existing Aadhaar
     upload/OCR block, with the consent line as design decisions describe.
   - On click: `POST /api/onboarding/{token}/kyc/start`, open the returned
     redirect URL (same tab, since DigiLocker's own flow expects a full
     navigation, not a popup — confirm against the aggregator's docs once
     picked).
   - On return from `GET /api/onboarding/{token}/kyc/callback` (the backend
     redirects back to this same page with a status query param), poll or
     read the session's `kyc_status` and render the matching state.
2. Auto-fill: on `kyc_status=verified`, populate `id-number` (masked value
   only — never render the raw Aadhaar number in the DOM), `perm-address`,
   and any other fields the verified pull returned, same way the existing
   `extract-id` response already does at line 1313-1321 — reuse that
   auto-fill code path rather than duplicating it.
3. Fallback UI: keep the existing manual Aadhaar photo upload + OCR
   (`extract-id`) block, but only show/enable it after a DigiLocker attempt
   fails, and label it "Manual review — admin will verify" so the tenant
   understands this isn't instant.
4. Step-4/submit gating: disable the "Next"/final submit button unless
   `kyc_status` is `verified` or `unverified_manual` (client-side UX; backend
   already enforces this per Spec 02).

## Out of scope
- Backend service, DB migration, API endpoints — Spec 02.
- Any Next.js/PWA admin-side change (Bookings page etc.) — admins already see
  onboarding status through existing admin views; no new admin UI needed
  unless Kiran asks for a KYC-status column later.
- Styling/rebrand beyond matching the existing form's look.

## Verification checklist
- [ ] Compile/typecheck/lint pass (if any build step applies to `static/`)
- [ ] Manual test of the actual flow in a browser against the aggregator
      sandbox: consent → redirect → callback → auto-fill → Next unlocks
- [ ] Manual test of the failure path: cancel/deny consent → falls back to
      OCR upload, labeled as manual review
- [ ] Confirm the raw Aadhaar number is never written into the DOM/JS state
      — only the masked value from the backend
- [ ] Confirm "Next" stays disabled until `kyc_status` is verified or
      unverified_manual, and that bypassing it client-side still gets
      rejected server-side (re-check Spec 02's guard)
- [ ] Do it twice: reload the onboarding link mid-flow and confirm state
      isn't lost/duplicated
