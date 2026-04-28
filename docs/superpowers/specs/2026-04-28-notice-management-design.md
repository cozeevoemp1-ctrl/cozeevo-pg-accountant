# Notice Management — Design Spec
Date: 2026-04-28

## Overview
Add notice management to the PWA dashboard and tenant edit flow. Notices are already recorded via the WhatsApp bot (NOTICE_GIVEN intent), stored in `tenancies.notice_date` and `tenancies.expected_checkout`. This spec adds:
1. Dashboard KPI tile showing all tenants on notice with deposit eligibility
2. Tenant edit page — notice section (view, edit, withdraw)
3. Checkout page — notice auto-fill + conditional refund display
4. Bot — NOTICE_WITHDRAWN intent to cancel a notice

## Business Rules (unchanged)
- `NOTICE_BY_DAY = 5`
- `notice_date.day <= 5` → deposit **Refundable**, last day = end of current month
- `notice_date.day > 5` → deposit **Forfeited**, last day = end of next month
- Withdrawal = set `notice_date = NULL`, `expected_checkout = NULL` in DB + Sheet

---

## 1. Dashboard KPI Tile

### Behaviour
- Full-width tile (col-span-2), same pattern as the "Awaiting check-in" no-show tile
- Label: "📋 On notice · {count}" — only visible when count > 0
- Colour: orange
- Click → inline dropdown, sorted by `expected_checkout ASC`
- Each row: tenant name | Room {number} | badge (green "Refundable" / red "Forfeited") | expected checkout date
- Name/room search filter at top of dropdown
- Click a row → loads existing TenantDetailCard (same as dues/occupied tiles)

### Backend changes
**`src/schemas/kpi.py`**
- Add `notices_count: int`

**`src/api/v2/kpi.py` — `get_kpi()`**
- Query: active tenancies with `notice_date IS NOT NULL` (exclude exited/cancelled)

**`src/api/v2/kpi.py` — `get_kpi_detail(type="notices")`**
```
SELECT tenancy_id, name, room_number, notice_date, expected_checkout
FROM tenancies JOIN tenants JOIN rooms
WHERE status = 'active' AND notice_date IS NOT NULL
ORDER BY expected_checkout ASC NULLS LAST
```
- Return: `{ tenancy_id, name, room, detail: "<day> <Mon>", deposit_eligible: bool }`
- `detail` = formatted expected_checkout date (e.g. "30 Apr")
- `deposit_eligible` = notice_date.day <= 5

### Frontend changes
**`web/lib/api.ts`**
- Add `notices_count: number` to `KpiResponse`
- Add `deposit_eligible?: boolean` to `KpiDetailItem`

**`web/components/home/kpi-grid.tsx`**
- Add `"notices"` to `TileKey`
- Add tile (col-span-2, only when count > 0)
- Add name search filter bar for notices panel
- Add `filtered` logic for notices
- In the row render: show deposit badge alongside detail text
  - `deposit_eligible = true` → green pill "Refundable"
  - `deposit_eligible = false` → red pill "Forfeited"

---

## 2. Tenant Edit Page — Notice Section

### Behaviour
- New card "Notice" inserted below "Stay Details" card
- If tenant has no notice on file: show date inputs blank + placeholder "No notice recorded"
- If tenant has notice: inputs pre-filled, deposit eligibility badge shown immediately
- Deposit badge auto-recalculates live as `notice_date` changes (client-side, day ≤ 5 rule)
- "Withdraw notice" button (only shown when notice_date is set): clears both fields, triggers PATCH with `notice_date: null, expected_checkout: null`
- Expected checkout also removed from "Stay Details" card (avoid duplicate field)
- On save via "Review Changes →": notice_date and expected_checkout included if changed

### Backend changes
**`src/api/v2/tenants.py` (PATCH endpoint)**
- Accept `notice_date: date | None` in patch body
- Accept `expected_checkout: date | None` (already exists, ensure null clears)
- Write to `tenancies.notice_date` and `tenancies.expected_checkout`
- Call `gsheets.record_notice(...)` if notice_date set, or clear notice columns if null

**`src/api/v2/tenants.py` (GET dues)**
- Include `notice_date: str | None` and `deposit_eligible: bool | None` in TenantDues response

**`web/lib/api.ts`**
- Add `notice_date?: string | null` to `TenantDues`
- Add `notice_date?: string | null` and `expected_checkout?: string | null` to `PatchTenantBody`

**`web/app/tenants/[tenancy_id]/edit/page.tsx`**
- Add `noticeDate` and `expectedCheckout` state (loaded from TenantDues)
- New "Notice" card section with:
  - Notice date input (date)
  - Expected checkout input (date)
  - Live deposit eligibility badge (computed: `noticeDate && new Date(noticeDate).getDate() <= 5`)
  - "Withdraw notice" button (shown only when noticeDate non-empty): sets both to ""
- Move `expectedCheckout` out of "Stay Details" into this card
- Include both in `buildChanges()` and `buildConfirmFields()`

---

## 3. Checkout Page — Notice Auto-fill

### Behaviour
- When a tenant is selected and `prefetch.notice_date` is set:
  - Show notice banner (pink border card) above the checklist
  - Pre-fill `checkoutDate` from `prefetch.expected_checkout` (if set)
  - Banner content:
    - Notice given: {formatted date}
    - Deposit: **Refundable — ₹{refund_amount}** (if `notice_date.day <= 5`)
    - Deposit: **Forfeited** (if `notice_date.day > 5`) — no amount shown

### Backend changes
- `src/api/v2/checkout.py` prefetch already returns `notice_date`
- Ensure `expected_checkout` is also returned in CheckoutPrefetch

### Frontend changes
**`web/lib/api.ts`**
- Add `expected_checkout?: string | null` to `CheckoutPrefetch` (if missing)

**`web/app/checkout/new/page.tsx`**
- After prefetch loads, if `prefetch.notice_date` set: pre-fill `checkoutDate = prefetch.expected_checkout`
- Render notice banner between tenant search and checklist:
  ```
  if prefetch.notice_date:
    notice_day = day of notice_date
    if notice_day <= 5:
      show green banner: "Notice on file · {date} — Deposit Refundable ₹{net_refund}"
    else:
      show orange banner: "Notice on file · {date} — Deposit Forfeited"
  ```
- `net_refund` = `prefetch.security_deposit - prefetch.pending_dues` (clamped to 0)

---

## 4. Bot — NOTICE_WITHDRAWN Intent

### Intent detection (`src/whatsapp/intent_detector.py`)
New pattern (owner/admin scope):
```
cancel notice|withdraw notice|remove notice|revoke notice|
not leaving|changed mind|won't be leaving|will not leave|
notice cancel|take back notice
```
Confidence: 0.93. Requires fuzzy tenant name/room in message or pending state follow-up.

### Handler (`src/whatsapp/handlers/owner_handler.py`)
Flow:
1. Parse tenant name/room from message
2. Fuzzy match to active tenancy with `notice_date IS NOT NULL`
3. If no match: "No notice found for [name]"
4. If match: enter pending state AWAITING_CHOICE with confirmation:
   "Withdraw notice for {name} (Room {room})?\nNotice given: {date}\nExpected out: {date}\n\nReply *yes* to confirm."
5. On confirm:
   - `tenancy.notice_date = None`
   - `tenancy.expected_checkout = None`
   - `await gsheets.record_notice(room, name, notice_date=None, expected_exit=None)` (clears sheet columns)
   - Reply: "Notice withdrawn for {name}. They remain active in Room {room}."

### Sheet sync (`src/integrations/gsheets.py`)
- Extend `record_notice()` to handle `notice_date=None` case: write empty string to M_NOTICE_DATE, T_NOTICE_DATE, T_EXPECTED_EXIT columns

---

## Data Flow Summary
```
Bot NOTICE_WITHDRAWN
  → owner_handler._withdraw_notice()
  → DB: notice_date=NULL, expected_checkout=NULL
  → gsheets.record_notice(notice_date=None)  ← clears sheet

PWA Tenant Edit "Withdraw notice" button
  → PATCH /api/v2/app/tenants/{id} {notice_date: null, expected_checkout: null}
  → DB update + gsheets.record_notice(notice_date=None)

Dashboard tile
  → GET /api/v2/app/reporting/kpi  ← notices_count
  → GET /api/v2/app/reporting/kpi-detail?type=notices  ← list

Checkout auto-fill
  → GET /api/v2/app/tenants/{id}/checkin-preview  ← notice_date + expected_checkout
  → client-side deposit eligibility + auto-fill
```

## Files to Touch
| File | Change |
|---|---|
| `src/schemas/kpi.py` | Add `notices_count` |
| `src/api/v2/kpi.py` | Add notices query + kpi-detail branch |
| `src/api/v2/tenants.py` | PATCH accepts notice_date; GET dues returns notice_date |
| `src/api/v2/checkout.py` | Ensure expected_checkout in prefetch |
| `src/integrations/gsheets.py` | record_notice handles None (clears sheet) |
| `src/whatsapp/intent_detector.py` | NOTICE_WITHDRAWN pattern |
| `src/whatsapp/handlers/owner_handler.py` | _withdraw_notice() handler |
| `web/lib/api.ts` | notices_count, deposit_eligible, notice_date on TenantDues + PatchTenantBody |
| `web/components/home/kpi-grid.tsx` | notices tile + deposit badge |
| `web/app/tenants/[tenancy_id]/edit/page.tsx` | Notice card section |
| `web/app/checkout/new/page.tsx` | Notice banner + auto-fill |
