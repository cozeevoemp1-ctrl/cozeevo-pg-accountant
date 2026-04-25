# Checkout Form — Design Spec

**Date:** 2026-04-25
**Status:** Approved
**Author:** Kiran + Claude (brainstorming session)

---

## Overview

Replace the WhatsApp-only conversational checkout with a structured web form. Receptionist fills all checkout details in a 3-step form, submits, and a WhatsApp summary is sent to the tenant for confirmation. Tenant has 2 hours to agree or reject. No response = auto-confirmed. Rejection requires a typed reason.

---

## Flow

```
Receptionist opens /admin/checkout
  │
  ├─ Step 1: Tenant search + checkout date
  ├─ Step 2: Physical handover (keys, biometric, room condition)
  └─ Step 3: Financial settlement (all fields editable, deposit pre-filled from DB)
       │
       └─ Submit → CheckoutSession created (2-hr expiry)
                 → WhatsApp checkout_request sent to tenant
                         │
            ┌────────────┼──────────────────┐
         YES reply    NO + reason        No reply (2hr)
            │            │                  │
        Confirmed    Receptionist       Auto-confirmed
        → DB+Sheet   notified on WA     → DB+Sheet
                     Session void
                     (new session needed)
```

---

## Admin Portal Nav Bar

Both `/admin/onboarding` and `/admin/checkout` share a top navigation bar:

```
[ Cozeevo Admin ]   Check-in   Checkout
```

- `/admin/onboarding` → existing `static/admin_onboarding.html` (add nav bar)
- `/admin/checkout` → new `static/checkout_admin.html`

Nav bar is a minimal shared HTML snippet injected at the top of each page. No backend routing change needed — both are served as static files by FastAPI's `StaticFiles` mount.

---

## Form Fields (3 Steps)

All fields are compulsory. Form will not advance to the next step unless all fields on the current step are filled.

### Step 1 — Tenant & Date

| Field | Type | Notes |
|-------|------|-------|
| Tenant | Autocomplete search | Search by name or room number; fetches active tenancies |
| Checkout date | Date picker | Defaults to today |

On tenant selection, the form pre-fetches from DB:
- Tenant name, room number, phone
- Security deposit amount
- Pending dues (unpaid rent + maintenance from `rent_schedules` where status != paid)
- Notice date (if recorded on tenancy)

### Step 2 — Physical Handover

| Field | Type | Notes |
|-------|------|-------|
| Room key returned | Yes / No toggle | |
| Wardrobe key returned | Yes / No toggle | |
| Biometric removed | Yes / No toggle | |
| Room condition | OK / Not OK toggle | |
| Damage notes | Text area | Shown only when Room condition = Not OK; compulsory if visible |

### Step 3 — Financial Settlement

All fields are editable even when auto-filled from DB.

| Field | Type | Notes |
|-------|------|-------|
| Security deposit | Number | Pre-filled from `tenancy.security_deposit` |
| Pending dues | Number | Pre-filled: sum of unpaid rent + maintenance |
| Deductions | Number | Manual — damages, notice forfeiture, etc. |
| Deduction reason | Text | Compulsory if deductions > 0 |
| Refund amount | Number | Auto-calc: deposit − pending dues − deductions. Editable override. Min = 0. |
| Refund mode | Dropdown | Cash / UPI / Bank |

**Notice forfeiture logic (auto-applied to deductions pre-fill):**
- If `tenancy.notice_date` is null → deductions pre-filled with full deposit amount, reason = "No notice given"
- If `tenancy.notice_date` is after the 5th of the checkout month → same forfeiture
- If `tenancy.notice_date` is on or before the 5th → no forfeiture pre-fill
- Receptionist can override any of these values before submitting

---

## Data Model

### New Table: `checkout_sessions`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| token | UUID | unique, indexed |
| status | Enum | `pending` → `confirmed` / `auto_confirmed` / `rejected` / `cancelled` |
| created_by_phone | String(20) | receptionist phone |
| tenant_phone | String(20) | for WhatsApp delivery |
| tenancy_id | Integer FK | tenancies.id |
| checkout_date | Date | |
| room_key_returned | Boolean | |
| wardrobe_key_returned | Boolean | |
| biometric_removed | Boolean | |
| room_condition_ok | Boolean | |
| damage_notes | Text nullable | null if room_condition_ok = true |
| security_deposit | Numeric(12,2) | receptionist-confirmed value |
| pending_dues | Numeric(12,2) | receptionist-confirmed value |
| deductions | Numeric(12,2) | |
| deduction_reason | Text nullable | |
| refund_amount | Numeric(12,2) | |
| refund_mode | String(10) | cash / upi / bank |
| rejection_reason | Text nullable | filled by tenant on rejection |
| expires_at | Timestamptz | created_at + 2 hours |
| confirmed_at | Timestamptz nullable | |
| created_at | Timestamptz | default now() |

---

## API Endpoints

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/admin/checkout` | StaticFiles | Serves `checkout_admin.html` |
| GET | `/api/checkout/tenants` | `checkout_router` | Autocomplete — active tenants by name/room |
| GET | `/api/checkout/tenant/{tenancy_id}` | `checkout_router` | Pre-fetch deposit, dues, notice date |
| POST | `/api/checkout/create` | `checkout_router` | Create session, send WhatsApp to tenant |
| GET | `/api/checkout/status/{token}` | `checkout_router` | Poll session status (for admin page feedback) |

---

## WhatsApp Messages

### 1. `checkout_request` → tenant (sent on session create)

```
Hi [Name], your checkout from Room [X] on [Date] has been recorded.

Summary:
- Room key: Returned / Not returned
- Wardrobe key: Returned / Not returned
- Biometric: Removed / Not removed
- Room condition: OK / Damage noted
- Refund: ₹[amount] via [mode]

Reply YES to confirm.
If you disagree, reply NO followed by your reason (e.g. "NO the damage charge is wrong").
If no response in 2 hours, this will be auto-confirmed.
```

### 2. `checkout_confirmed` → tenant (on confirm or auto-confirm)

```
Your checkout from Room [X] on [Date] is confirmed.
Refund of ₹[amount] will be processed by receptionist now.
Thank you for staying with Cozeevo.
```

If refund = ₹0:
```
Your checkout from Room [X] on [Date] is confirmed.
Thank you for staying with Cozeevo.
```

### 3. Rejection notification → receptionist (free text, within 24hr window)

```
[Tenant name] (Room [X]) rejected the checkout.
Reason: [reason]
Please resolve and create a new checkout session.
```

---

## Intent Detection

Two new intents in `intent_detector.py`:

**`CHECKOUT_AGREE`** — tenant replies YES (case-insensitive) when there is an active `CheckoutSession` for their phone.

**`CHECKOUT_REJECT`** — tenant replies with a message starting with NO (case-insensitive) followed by a reason. If the tenant replies NO without a reason, bot replies: "Please provide a reason for rejection (e.g. NO the damage charge is wrong)."

Detection gated on active session: if no pending `CheckoutSession` exists for the sender's phone, YES/NO are not intercepted as checkout intents.

---

## Auto-Confirm (APScheduler)

Existing APScheduler instance gets a new job:

```python
@scheduler.scheduled_job('interval', minutes=15)
async def auto_confirm_expired_checkout_sessions():
    # Find all CheckoutSession where status='pending' and expires_at < now()
    # For each: run the same confirm logic (write CheckoutRecord, update tenancy, sync Sheet)
    # Send checkout_confirmed WhatsApp to tenant
    # Mark session status='auto_confirmed' (distinguished from 'confirmed' = explicit YES)
```

Session status `auto_confirmed` = timed-out without response (not explicitly agreed). Tracked separately from `confirmed` for audit. Checkout is fully executed in both cases.

---

## On Confirm (agree or auto-confirm)

Reuses existing checkout logic from `owner_handler.py`:

1. Create `CheckoutRecord` in DB
2. Create `Refund` record (status=`pending` if refund > 0, else `cancelled`)
3. Set `tenancy.status = TenancyStatus.exited`
4. Set `tenancy.actual_exit_date = checkout_date`
5. Sync to Google Sheet (EXIT row in TENANTS tab via `gsheets.update_tenant_field()`)
6. Send `checkout_confirmed` WhatsApp to tenant

---

## Files Changed

| File | Change |
|------|--------|
| `static/checkout_admin.html` | New — 3-step receptionist form |
| `static/admin_onboarding.html` | Add nav bar snippet |
| `src/api/checkout_router.py` | New — API routes |
| `src/database/models.py` | Add `CheckoutSession` model + `CheckoutSessionStatus` enum |
| `src/database/migrate_all.py` | Append migration for `checkout_sessions` table |
| `src/whatsapp/intent_detector.py` | Add `CHECKOUT_AGREE`, `CHECKOUT_REJECT` intents |
| `src/whatsapp/handlers/owner_handler.py` | Add handlers for agree/reject |
| `src/whatsapp/chat_api.py` | Wire new intents to handlers |
| `main.py` | Register `checkout_router` + APScheduler job |

---

## Non-Goals

- No tenant-facing web form (tenant agrees via WhatsApp only)
- No PDF receipt (WhatsApp confirmation message is sufficient)
- No signature capture on checkout form (tenant's YES reply is the confirmation record)

---

## Phase 2 — Fix WhatsApp Conversational Checkout

**Problem:** The current WhatsApp checkout flow (`RECORD_CHECKOUT` in `owner_handler.py`) writes to DB and Sheet immediately on confirmation without surfacing all financial details. Receptionist cannot see deposit/dues/refund amounts during the flow, and in some cases checkout is executing without full confirmation.

**Fix:** Rewrite the `RECORD_CHECKOUT` step sequence to:
1. Pull all financial data upfront (deposit, pending dues, notice status)
2. Collect all physical handover fields via step-by-step Q&A (already exists — keep as-is)
3. Show a complete summary with ALL details before writing anything to DB
4. Only write to DB + Sheet on explicit YES confirmation
5. On NO + reason → receptionist can restart with corrections noted

### New WhatsApp Checkout Flow (receptionist-side)

```
Receptionist: "checkout Ravi"
  → Bot: "Found Ravi Kumar (Room 305). Checkout date? (or reply 'today')"
Receptionist: "today"
  → Bot: "Room key returned? (yes/no)"
Receptionist: "yes"
  → Bot: "Wardrobe key returned? (yes/no)"
Receptionist: "yes"
  → Bot: "Biometric removed? (yes/no)"
Receptionist: "no"
  → Bot: "Room condition? (ok / not ok)"
Receptionist: "ok"
  → Bot: "Any deductions? Enter amount or 0"
Receptionist: "2000"
  → Bot: "Reason for deduction?"
Receptionist: "paint damage"
  → Bot shows full summary:

  Checkout Summary — Ravi Kumar, Room 305
  Exit date: 25 Apr 2026
  ─────────────────────────────
  Room key: Returned
  Wardrobe key: Returned
  Biometric: NOT removed
  Room condition: OK
  ─────────────────────────────
  Security deposit: ₹15,000
  Pending dues: ₹0
  Deductions: ₹2,000 (paint damage)
  Refund: ₹13,000
  ─────────────────────────────
  Reply YES to confirm and save.
  Reply NO to cancel (add reason if needed).

Receptionist: "YES"
  → Checkout saved → DB + Sheet updated
  → Tenant WhatsApp confirmation sent
```

### On NO reply

If receptionist replies NO (with or without reason):
- Session cleared, nothing written to DB
- Bot replies: "Checkout cancelled. [Reason noted.] Start again when ready."
- Receptionist can restart with "checkout Ravi"

### Deduction step (new)

The existing flow does not ask for deduction amount. Add two new steps after `ask_fingerprint`:
- `ask_deductions` → "Any deductions? Enter amount or 0"
- `ask_deduction_reason` → shown only if deductions > 0 → "Reason for deduction?"

Financial summary is then auto-calculated before the confirm step.

### Files Changed (Phase 2)

| File | Change |
|------|--------|
| `src/whatsapp/handlers/owner_handler.py` | Rewrite `RECORD_CHECKOUT` step sequence — add deduction steps, show full financial summary, defer all DB writes to confirm step |
| `src/whatsapp/conversation/handlers/checkout.py` | Minor: ensure no premature DB writes in disambiguation step |
