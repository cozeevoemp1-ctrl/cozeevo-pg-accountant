# Spec 04 — Booking terms, lock-in, and stricter KYC on the onboarding form

Status: in-progress (2026-09-05)

## Goal
Staff can record lock-in, customer-facing special terms, and internal notes as three
separate fields when pre-booking or pre-registering. The customer onboarding form shows
lock-in and special terms, requires Aadhaar front + back (address from the back), rejects
a name that does not match the Aadhaar, and rejects an emergency phone equal to the
tenant's own phone.

## Background (found 2026-09-05)
- The "Notes (admin only)" field on both booking forms was stored in
  `onboarding_sessions.special_terms`, which is printed in the signed agreement PDF under
  "Special Terms". Room 106 (Raghav Mittal) went out with "Lock in period three months" in
  Special Terms while the same PDF's table said "Lock-in: 0 months".
- Neither booking form had a lock-in input; `lock_in_months` was always 0.
- The customer form has one ID upload slot. Physical Aadhaar has the address on the back,
  so the front-only OCR returned no address and the form silently said nothing.

## Design decisions
- Three fields, three meanings:
  - `lock_in_months` (existing column) — structured, shown on customer form + PDF table.
  - `special_terms` (existing column) — customer-facing free text, shown on customer form
    (room card + agreement card, below lock-in) and PDF "Special Terms".
  - `admin_notes` (NEW column) — internal only. Never returned by the public
    `GET /api/onboarding/{token}` endpoint, never in the PDF.
- Both booking forms already share `POST /api/v2/app/bookings/quick-book`; the only
  difference is the pre-book modal has the room prefilled. No component merge.
- Tenancy `notes` on check-in = admin_notes, plus "Terms: <special_terms>" when both are
  set (helper `_tenancy_notes_from_obs()` in `onboarding_router.py`, replaces 5 inline
  sites).
- Aadhaar back side: second required upload when ID type is Aadhaar. Runs the same
  `/extract-id` OCR and fills the address. Stored as `saved_files.id_proof_back` in the
  KYC bucket and linked as a `Document(id_proof)` on approve. All uploads are kept — they
  are our proof.
- Name match: front OCR name vs the name typed in Step 1. Rule: normalise to lowercase
  letter tokens, drop 1-letter tokens (initials); every token of the shorter name must
  appear in the longer name. Enforced client-side at Step 3 and server-side at submit
  (`aadhaar_name` sent in the payload). Single source: `src/utils/name_match.py`; the JS
  mirror in `onboarding.html` must implement the identical rule.
- Emergency phone must differ from the tenant phone: client-side at Step 2, server-side
  at submit (400).

## Implementation
Backend
1. `src/database/models.py` — `OnboardingSession.admin_notes = Column(Text)`.
2. `src/database/migrate_all.py` — `run_add_onboarding_admin_notes_2026_09_05` (append).
3. `src/api/v2/bookings.py` — `QuickBookRequest`: `lock_in_months: int = 0`,
   `special_terms: str = ""`, `notes` now → `admin_notes`. Set all three on both
   monthly and daily `OnboardingSession(...)` constructions.
4. `src/api/onboarding_router.py`
   - list endpoint: `notes` → admin_notes; add `special_terms`, `lock_in_months`.
   - staff session GET: add `admin_notes`.
   - `TenantSubmitRequest`: `id_photo_back: str = ""`, `aadhaar_name: str = ""`.
   - submit: size check + upload `id_proof_back`; emergency phone == tenant phone → 400;
     aadhaar_name mismatch → 400.
   - approve: `doc_map["id_proof_back"] = DocumentType.id_proof`.
   - `_tenancy_notes_from_obs()` replaces the 5 `obs.special_terms or ""` tenancy sites.
5. `src/utils/name_match.py` — `names_match(a, b) -> bool`. Tests in
   `tests/test_name_match.py`.
6. `src/scheduler.py` — check-in digest notes column = admin_notes | special_terms.
7. `scripts/_fix_106_lockin.py` — one-off: tenancy 1296 + session 273 `lock_in_months=3`,
   audit_log entry.

Frontend (PWA)
8. `web/lib/api.ts` — `quickBook` payload: `lock_in_months`, `special_terms`.
9. `web/components/home/kpi-grid.tsx` (pre-book modal) and
   `web/app/tenants/pre-register/page.tsx` — Lock-in select (None/1/2/3/6), Special terms
   textarea ("shown to customer"), Notes textarea ("admin only").
10. `web/app/onboarding/bookings/page.tsx` — show Lock-in and TERMS lines beside NOTE.

Customer form (`static/onboarding.html`)
11. Room card + agreement card: "Special terms" item below lock-in, hidden when empty.
12. Step 2: emergency phone must differ from tenant phone.
13. Step 3: second upload slot "Aadhaar back side" (required when ID type = Aadhaar),
    same OCR path, fills address; front OCR stores the extracted name; Step 3 validation
    fails on name mismatch with a clear message; payload adds `id_photo_back`,
    `aadhaar_name`.

Docs
14. `docs/DATA_MODEL.md` (admin_notes), `docs/CHANGELOG.md`, `memory/project_pending_tasks.md`.

## Out of scope
- Merging the pre-book modal and pre-register page into one component.
- Editing lock-in / terms / notes on an existing session from the Bookings page.
- Re-issuing the Room 106 agreement PDF.
- DigiLocker e-KYC (specs 02/03).

## Verification checklist
- [ ] `py -3 -m pytest tests/test_name_match.py`
- [ ] `cd web && npx tsc --noEmit` passes
- [ ] Migration applied locally: `admin_notes` column exists
- [ ] Pre-book with lock-in 3 + terms + notes → session row has all three; public
      `GET /api/onboarding/{token}` returns lock_in + special_terms, NOT admin_notes
- [ ] Customer form shows lock-in + special terms in room card and agreement card
- [ ] Emergency phone = own phone → blocked at Step 2 and by API
- [ ] Aadhaar: back side required; address fills from back; name mismatch blocks Step 3
- [ ] Approve → Documents: selfie, id_proof, id_proof_back, signature, agreement
- [ ] Room 106: tenancy 1296 lock_in_months = 3, audit_log row present
- [ ] Dependency sync rule run (CLAUDE.md checklist)
