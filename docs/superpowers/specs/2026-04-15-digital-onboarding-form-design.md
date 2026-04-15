# Digital Onboarding Form — Design Spec

**Date:** 2026-04-15
**Status:** Approved
**Approach:** Option B — Two Separate Forms, Linked by Token

---

## Overview

Replace the printed 2-page registration form with a digital onboarding system. Receptionist creates a session (assigns room/rent), sends a unique link to the tenant via WhatsApp, tenant fills personal details + reads personalized agreement + draws signature on their phone, receptionist reviews and approves.

## Architecture: Two Forms, One Token

### Flow

1. **Receptionist** opens `/admin/onboarding` on desktop/tablet
2. Fills financial details: room number (auto-fills building, floor, sharing from DB), agreed rent, deposit, maintenance, check-in date, stay type, lock-in period, special terms
3. Clicks "Generate Tenant Link" → creates `onboarding_session` in DB with UUID token, 48-hour expiry
4. Link (`/onboard/{token}`) sent to tenant via WhatsApp (bot auto-sends or copy-paste)
5. **Tenant** opens link on phone → sees room/rent summary (read-only, pre-filled by receptionist)
6. Fills 5 sections: Personal → Family → Address & Work → ID Proof → Agreement & Signature
7. Draws signature on canvas pad → submits
8. **Receptionist** sees completed form in admin panel → reviews all details + signature preview
9. Clicks "Approve & Create Tenant" → Tenant + Tenancy + RentSchedule created in DB, Sheet updated, signed PDF generated and sent to tenant via WhatsApp

### Why Two Forms

- Clean separation: tenant form is mobile-first, admin form is desktop-optimized
- No concurrent editing conflicts — sequential, not parallel
- Receptionist controls the process (must act first)
- Each UI optimized for its user

## Data Model

### New Table: `onboarding_sessions`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| token | UUID | unique, indexed, used in URL |
| status | Enum | `draft`, `pending_tenant`, `pending_review`, `approved`, `expired`, `cancelled` |
| created_by_phone | String(20) | receptionist phone |
| tenant_phone | String(20) | tenant's phone (for WhatsApp delivery) |
| room_id | Integer FK | rooms.id |
| agreed_rent | Numeric(12,2) | |
| security_deposit | Numeric(12,2) | |
| maintenance_fee | Numeric(10,2) | |
| booking_amount | Numeric(12,2) | advance paid |
| advance_mode | String(10) | cash/upi (always asked if amount > 0) |
| checkin_date | Date | |
| stay_type | Enum | monthly/daily |
| lock_in_months | Integer | |
| special_terms | Text | rent remarks, conditions |
| tenant_data | JSONB | personal details filled by tenant |
| signature_image | Text | base64 PNG of drawn signature |
| agreement_pdf_path | String | path to generated PDF |
| expires_at | DateTime | 48 hours from creation |
| completed_at | DateTime | when tenant submitted |
| approved_at | DateTime | when receptionist approved |
| created_at | DateTime | |

### Status Transitions

```
draft → pending_tenant (link generated)
pending_tenant → pending_review (tenant submitted)
pending_review → approved (receptionist approved → creates Tenant + Tenancy)
pending_tenant → expired (48h timeout)
any → cancelled (manual cancel)
```

## Tenant Form (Mobile)

### URL: `/onboard/{token}`

### Header
- White background, Cozeevo SVG logo (`/static/logo.svg`), clean and simple

### Pre-filled Summary Card (read-only, blue-themed)
- Room number, building, floor, sharing type (derived from room)
- Agreed rent, deposit, maintenance
- Check-in date

### 5-Step Progress Bar
Pink active step, blue completed steps.

#### Step 1: Personal Details
- Full Name * (text)
- Phone * (tel, 10 digits)
- Gender * (radio: Male / Female)
- Date of Birth (date picker)
- Age (number, shown if DOB skipped, 15-99)
- Email (email)
- Food Preference * (radio: Veg / Non-Veg / Egg)

#### Step 2: Family & Emergency
- Father's Name (text)
- Father's Phone (tel)
- Emergency Contact Name * (text)
- Emergency Contact Phone * (tel, 10 digits)
- Relationship * (select: Father/Mother/Sibling/Spouse/Friend/Other)

#### Step 3: Address & Work
- Permanent Address (textarea)
- Occupation (text)
- Educational Qualification (text)
- Office/College Address (textarea)
- Office Phone (tel)

#### Step 4: ID Proof
- ID Type (select: Aadhaar/PAN/Passport/Driving License/Voter ID)
- ID Number (text, apostrophe-prefixed in Sheet to preserve leading zeros)

#### Step 5: Agreement & Signature
- **Agreement Summary** — personalized card showing tenant name, room, rent, deposit, maintenance, check-in, lock-in (blue-themed, read-only)
- **Terms & Conditions** — scrollable box with 12 rules, tenant-specific values highlighted in blue (rent amount, deposit, lock-in period, food plan, quiet hours)
- **Signature Pad** — HTML5 canvas, finger/stylus drawing, pink-themed border
- "Clear & redraw" link
- **"Sign & Submit Agreement"** button (pink-to-blue gradient)
- Note: "A signed PDF copy will be sent to your WhatsApp"

### Confirmation Screen
- Pink-to-blue gradient check icon
- "Welcome to Cozeevo!"
- What Happens Next: 3 numbered steps (pink badges, blue card)
- WhatsApp help contact

## Admin Panel (Desktop)

### URL: `/admin/onboarding`

Integrated into existing dashboard as a new tab/section.

### Create Session View
- Room number input (auto-fills building, floor, sharing from rooms table)
- Rent, deposit, maintenance, booking amount fields
- If booking amount > 0: "Cash or UPI?" prompt (always ask, never default)
- Check-in date, stay type, lock-in months
- Special terms / rent remarks (textarea)
- Tenant phone number (for WhatsApp link delivery)
- "Generate Link" button → creates session, shows copyable link + option to auto-send via WhatsApp

### Review Queue
- List of sessions with status: pending_tenant, pending_review
- Click to expand → shows all tenant-filled data + signature preview
- "Approve & Create Tenant" button
- "Reject / Request Changes" option

## PDF Agreement

### Generation
- Server-side HTML template → PDF (weasyprint or reportlab)
- Contains: Cozeevo logo, tenant details, room/rent summary, full terms & conditions, signature image, date, session reference

### Storage
- Saved to `media/agreements/YYYY-MM/agreement_{token}.pdf`
- Path stored in `onboarding_sessions.agreement_pdf_path`
- Also saved as `Document` record in DB (doc_type=agreement)

### Delivery
- Sent to tenant via WhatsApp as document message after receptionist approval
- Uses existing WhatsApp Cloud API media upload + document message

## Brand & Colors

| Role | Color | Hex |
|------|-------|-----|
| Primary (actions, buttons, progress active, required markers) | Pink | `#EF1F9C` |
| Secondary (info cards, completed steps, agreement terms, summary) | Cyan Blue | `#00AEED` |
| Background | Light gray | `#F9FAFB` |
| Cards | White | `#FFFFFF` |
| Text | Dark gray | `#2D3748` |
| Text light | Medium gray | `#718096` |
| Borders | Light | `#E8ECF0` |
| Success | Green | `#38C172` |

### Color Rules
- Pink = personal, actions, signatures, buttons
- Blue = info, legal, pre-filled data, agreement terms
- White header with SVG logo (no dark backgrounds)
- Pink-to-blue gradient on submit button and confirmation icon

## API Endpoints (New)

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/onboarding/create` | POST | admin | Create session, return token + link |
| `/api/onboarding/send-link` | POST | admin | Send link via WhatsApp to tenant |
| `/api/onboarding/{token}` | GET | public | Get session data (room/rent summary for tenant form) |
| `/api/onboarding/{token}/submit` | POST | public | Tenant submits personal data + signature |
| `/api/onboarding/pending` | GET | admin | List sessions pending review |
| `/api/onboarding/{token}/approve` | POST | admin | Approve → create Tenant + Tenancy + Sheet + PDF |
| `/api/onboarding/{token}/reject` | POST | admin | Reject with reason |
| `/onboard/{token}` | GET | public | Serve tenant form HTML |
| `/admin/onboarding` | GET | admin | Serve admin panel HTML |

## What Gets Removed

- **Step-by-step WhatsApp checkin flow** (`ADD_TENANT_STEP` intent + all `ask_*` steps in owner_handler.py)
- The image extraction flow (`FORM_EXTRACT_CONFIRM`) stays — it's still useful for quick OCR of paper forms
- `_add_tenant_prompt` updated to only offer: image upload OR "send onboarding link"

## Dependencies

- `weasyprint` or `reportlab` — PDF generation
- `signature_pad.js` — client-side signature canvas (MIT, ~30KB)
- No other new dependencies — uses existing FastAPI + Supabase + WhatsApp API

## Files to Create/Modify

### New Files
- `src/api/onboarding_router.py` — API endpoints
- `static/onboarding.html` — tenant form (single-page, 5-step wizard)
- `static/admin_onboarding.html` — admin create/review panel
- `templates/agreement.html` — PDF template
- `src/services/pdf_generator.py` — HTML → PDF
- `src/database/migrate_all.py` — append `onboarding_sessions` table migration

### Modified Files
- `main.py` — mount onboarding router
- `src/database/models.py` — add OnboardingSession model
- `src/whatsapp/handlers/owner_handler.py` — remove step-by-step flow, update `_add_tenant_prompt`
- `src/whatsapp/intent_detector.py` — update ADD_TENANT intent description

## Entered By Values

| Source | Value |
|--------|-------|
| WhatsApp bot (image extraction) | `bot` |
| Digital onboarding form | `onboarding_form` |
| Excel import | `excel_load` |
| Admin manual entry | `admin` |

## Validation Rules (Client + Server)

- Phone: exactly 10 digits, strip non-numeric
- Name: required, non-empty
- Gender: required, male/female
- Food: required, veg/non-veg/egg
- Emergency contact: name + phone + relationship all required
- ID number: apostrophe-prefixed in Sheet (preserve leading zeros)
- Signature: required, minimum stroke count (prevent accidental taps)
- Room: validated against rooms table, auto-derive building/floor/sharing
- Advance mode: always asked if amount > 0, never defaulted

## Token Security

- UUID v4, unguessable
- 48-hour expiry
- One-time use (status transitions prevent replay)
- No login required — link IS the auth
- Rate limited: max 5 submissions per IP per hour
