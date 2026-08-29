# Spec 02 — DigiLocker e-KYC (backend)

## Goal
Tenant onboarding can require a verified Aadhaar identity pull via DigiLocker
(through an aggregator that is already a registered DigiLocker Requester —
Setu or Cashfree Verification). `POST /{token}/submit` refuses to let a
session proceed unless `kyc_status` is `verified` or `unverified_manual`
(admin-approved fallback). No raw Aadhaar number is ever persisted.

Direct UIDAI AUA/KUA access is legally unavailable to Cozeevo (2019 Aadhaar
Amendment Act restricts it to PMLA-notified entities). Direct DigiLocker
Requester self-registration with MeitY is a slow, uncertain approval process
for a business this size. Decision: integrate via an aggregator that already
holds Requester status — same tenant-facing DigiLocker OAuth/consent screen,
no government approval needed on our side, ~₹3–10 per verification.

## Design decisions
- **Vendor: Setu** (`setu.co`, "Setu Data — DigiLocker" product — distinct
  from the government's `apisetu.gov.in` portal). Chosen for its narrow
  DigiLocker-specialist focus, public developer docs (`docs.setu.co/data/digilocker`),
  and self-serve sandbox signup. Kiran still needs to create the account and
  obtain sandbox/prod credentials — this spec covers integration code only.
- **Vendor adapter, not a hard dependency**: new module `src/services/digilocker_kyc.py`
  wraps Setu's REST API behind three functions —
  `create_consent_request()`, `handle_callback()`, `fetch_aadhaar_doc()`.
  Keep the Setu-specific request/response shapes contained to this file so a
  future vendor swap (e.g. to Cashfree) only touches this module.
- **Never store the raw Aadhaar number.** `Tenant.id_proof_number` currently
  stores it in plaintext (`src/database/models.py:306`) — this is the gap to
  close. Going forward, only a masked form (`XXXX-XXXX-1234`) is written
  there. If the full number is ever needed, re-fetch from the aggregator by
  `kyc_provider_ref`; never persist it locally. This mirrors UIDAI's own
  Aadhaar Data Vault rule even though we're not a direct AUA/KUA.
- **KYC status lives on `OnboardingSession`**, not `Tenant` (session is the
  pre-tenant record) — `kyc_status` (`pending`/`verified`/`unverified_manual`/
  `failed`), `kyc_verified_at`, `kyc_provider_ref`. Same naming convention as
  the existing `Staff.kyc_verified` / `Staff.kyc_document_url`
  (`src/database/models.py:334-335`) so both flows read the same way.
- **Storage**: any pulled Aadhaar image/XML/photo goes into the existing
  private `kyc-documents` bucket (`src/services/storage.py:30 BUCKET_KYC`),
  written via `upload()` (`storage.py:130`), read only via
  `sign_stored_url()` (`storage.py:90`) — never a public URL. Same pattern
  already used for staff KYC (`upload_staff_kyc_to_supabase`,
  `src/whatsapp/media_handler.py:91`).
- **Fallback path**: the existing OCR extraction
  (`onboarding_router.py:1074`, `_AADHAAR_EXTRACT_PROMPT`) stays, but its
  result now sets `kyc_status=unverified_manual` instead of being treated as
  authoritative — routes to the existing admin-approval step
  (`resolve_approve_onboarding`, `resolvers/onboarding.py:16`) instead of
  auto-proceeding.
- **Audit trail**: every consent grant and verification result calls
  `write_audit_entry()` (`src/services/audit.py:19`) with
  `entity_type="onboarding_session"`, `field="kyc.consent"` /
  `field="kyc.verify"`.
- **Secrets**: `DIGILOCKER_PROVIDER=setu`, `DIGILOCKER_CLIENT_ID`,
  `DIGILOCKER_CLIENT_SECRET`, `DIGILOCKER_REDIRECT_URI` — VPS `.env` only via
  `scripts/vps_env_set.sh`, placeholder keys added to `.env.example`. Kiran
  handles the Setu account signup/credentials; this spec covers integration
  code only.

## Implementation
1. **Migration** (`src/database/migrate_all.py`, append-only, same
   `ADD COLUMN IF NOT EXISTS` pattern used at line 1090/1147 for this table):
   - `onboarding_sessions.kyc_status VARCHAR(20) DEFAULT 'pending'`
   - `onboarding_sessions.kyc_verified_at TIMESTAMP`
   - `onboarding_sessions.kyc_provider_ref VARCHAR(100)`
   - Add the matching `Column(...)` fields to `OnboardingSession` in
     `src/database/models.py` (after `future_rent_after_months`, line 885).
2. **`src/services/digilocker_kyc.py`** (new file):
   - `create_consent_request(session_token: str) -> str` — calls the
     aggregator to start a DigiLocker consent flow, returns the redirect URL
     the tenant is sent to. Writes `kyc_provider_ref` on the
     `OnboardingSession` row, writes an audit entry.
   - `handle_callback(request_id: str, session_token: str) -> dict` —
     verifies the aggregator's callback signature, pulls the e-Aadhaar doc,
     parses name/DOB/gender/address, uploads the raw doc to `BUCKET_KYC`,
     sets `kyc_status="verified"`, `kyc_verified_at=utcnow()`, writes the
     masked Aadhaar number into `tenant_data`/`collected_data`, writes an
     audit entry. On any failure sets `kyc_status="failed"`.
   - `mask_aadhaar(number: str) -> str` — shared helper so masking logic
     lives in exactly one place (also usable by the OCR fallback so it never
     accidentally persists a full number either).
3. **API** (`src/api/onboarding_router.py`):
   - `POST /{token}/kyc/start` — calls `create_consent_request()`, returns
     the redirect URL. Rate-limited (each call costs money at the
     aggregator) — reuse whatever rate-limit pattern `chat_api.py` already
     uses for the webhook, or a simple per-token cooldown if none exists.
   - `GET /{token}/kyc/callback` — the aggregator/DigiLocker redirect target;
     calls `handle_callback()`, then redirects the browser back to the
     onboarding form with a status query param.
   - `POST /{token}/submit` (existing, line 1193) — add a server-side guard:
     reject with 422 if `kyc_status` not in `("verified", "unverified_manual")`.
     This must be enforced here, not only hidden in the PWA UI.
   - `POST /{token}/extract-id` (existing, line 1074) — on success, set
     `kyc_status="unverified_manual"` on the session instead of leaving it
     untouched.
4. **Config**: add `DIGILOCKER_PROVIDER`, `DIGILOCKER_CLIENT_ID`,
   `DIGILOCKER_CLIENT_SECRET`, `DIGILOCKER_REDIRECT_URI` to `.env.example`
   with placeholder values only.
5. **No-PII-in-logs check**: grep the new module and callback handler for any
   `log`/`print` of the raw Aadhaar number or e-Aadhaar XML before merging.

## Out of scope
- PWA UI changes — covered by Spec 03.
- Direct UIDAI AUA/KUA integration (legally unavailable).
- Video-KYC / liveness detection.
- Self-hosting an Aadhaar Data Vault (the aggregator already satisfies this).
- Automated retention/purge job for old KYC documents — note as a follow-up
  ticket, not blocking.
- Vendor account signup itself (Kiran-only action, outside this codebase).

## Verification checklist
- [ ] Compile/typecheck/lint pass
- [ ] Golden suite (if bot behavior changed): `python tests/eval_golden.py`
- [ ] Aggregator sandbox: full consent → callback → parsed data round-trip
      works end to end against a test onboarding session
- [ ] `Tenant.id_proof_number` / `OnboardingSession` data never contains a
      full, unmasked Aadhaar number after a successful pull
- [ ] KYC documents in `kyc-documents` bucket are reachable only via
      `sign_stored_url()`, never a raw public URL
- [ ] `POST /{token}/submit` actually rejects (422) an unverified session —
      test directly against the API, not just through the UI
- [ ] `audit_log` rows are written for both consent-start and verify-result
- [ ] `git diff` / `git status` confirm no real secret values were added to
      `.env.example` or committed anywhere
- [ ] Do it twice: re-running the consent flow on an already-verified session
      behaves sanely (doesn't duplicate audit rows in a confusing way / no
      crash)
- [ ] Dependency sync rule run (CLAUDE.md checklist) — intent_detector,
      docs index, etc. checked for anything referencing onboarding KYC state
