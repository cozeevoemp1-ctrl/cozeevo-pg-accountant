# End-to-End Audit Progress Report

**Date:** 2026-06-08  
**Status:** IN PROGRESS — Phase 1 Complete, Phase 2 In Progress

---

## PHASE 1: Map Endpoints ✅ COMPLETE

- [x] Extracted 40+ unique endpoints
- [x] Mapped to 19 PWA pages
- [x] Identified critical operations (payments, tenants, checkout, bookings)
- [x] Created audit checklist (AUDIT_ENDPOINT_MAP.md)

---

## PHASE 2: Data Flow Verification 🔍 IN PROGRESS

### ✅ VERIFIED SAFE

#### Multi-table JOIN Deduplication
- ✅ `list_tenants` — Tenancy is primary key, 1:1 joins to Tenant/Room/Property → No dedup needed
- ✅ `search_tenants` — **FIXED:** Added dedup by `tenancy_id` in loop (commit b4cc097)
- ✅ `getActiveNotices` — Tenancy is primary key, 1:1 joins → No dedup needed
- ✅ `list_payments` (tenancy_id path) — Subquery aggregation by tenancy_id → No dedup needed
- ✅ `list_payments` (tenant_id path) — **FIXED:** Added dedup by `payment_id` in loop (commit 016e841)

#### Field Name Consistency
- ✅ `create_payment` → returns `PaymentResponse` (payment_id, new_balance, receipt_sent)
- ✅ `list_payments` → returns `PaymentListItem[]` (payment_id, amount, method, for_type, period_month, payment_date, notes, is_void, receipt_url, upi_reference)
- ✅ `edit_payment` → returns `PaymentListItem` (same fields as list)
- ✅ `void_payment` → returns `PaymentListItem` (same fields as list)
- **Consistency:** ✅ All payment returns use same field names

#### Role Checks
- ✅ `create_payment` — role check: admin/staff
- ✅ `list_payments` — role check: admin/staff
- ✅ `edit_payment` — role check: admin/staff (added Session B)
- ✅ `void_payment` — role check: admin/staff
- ✅ `create_checkout` — role check: admin/staff
- ✅ `PATCH /tenants/{id}` — role check: admin/staff (added Session B)
- ✅ `POST /tenants/{id}/adjustment` — role check: admin/staff (added Session B)
- ✅ `POST /cancel-no-show` — role check: admin/staff (added Session B)
- ✅ `GET/POST /reminders` — role check: staff roles (added Session B)

### 🔴 CRITICAL ISSUES TO VERIFY

#### 1. Refund Calculation Consistency
**Locations to check:**
- Backend: `src/api/v2/checkout.py:create_checkout()` (stores refund_amount from client)
- Frontend: `web/app/checkout/new/page.tsx` (calculates refund before sending)
- Formula: `max(deposit - maintenance - dues - deductions, 0)`

**Question:** Are they calculating the same way? Is there a discrepancy?

#### 2. Notice Logic Consistency  
**Locations to check:**
- `src/api/v2/notices.py:get_active_notices()` — deposit_eligible = `nd is not None` ✓
- `web/app/checkout/new/page.tsx` — depositForfeited = `!prefetch.notice_date OR manualForfeit` 
- `web/app/tenants/[tenancy_id]/edit/page.tsx` — notice setting logic
- `src/whatsapp/handlers/owner_handler.py` — notice logic in bot (need to verify)

**Question:** Are all notice calculations aligned on:
- Notice by day 5 → deposit refundable, vacate month-end?
- Late notice (after 5th) → next month cycle + full month rent due?
- No notice → deposit forfeited?

#### 3. Occupancy Check Consistency
**Locations to check:**
- `src/services/room_occupancy.py:check_room_bookable()` — main occupancy check
- `src/api/v2/bookings.py:quick_book()` — calls check_room_bookable()
- `src/api/onboarding_router.py:create()` — calls check_room_bookable()
- `web/app/tenants/pre-register/page.tsx` — calls checkRoomAvailability()

**Question:** Do all callers use the same occupancy logic? Are future bookings (checkin after existing checkout) allowed correctly?

#### 4. Payment Deduplication
**Locations to check:**
- `src/api/v2/bookings.py:quick_book()` — creates OnboardingSession + optional Tenancy + optional Payment
- `src/api/onboarding_router.py:approve()` — creates Tenancy + creates Payment if booking_amount > 0
- `src/api/v2/payments.py:create_payment()` — creates Payment

**Questions:**
- Can a payment be created twice for same amount/tenancy?
- Is there idempotency checking (payment_date + amount + tenancy_id unique)?
- What happens if user clicks "approve" twice on same booking?

#### 5. Database Orphans
**Potential issues:**
- Payment with no tenancy (deleted tenancy, stale foreign key)
- Tenancy with no Tenant (deleted tenant)
- CheckoutSession with no Tenancy
- OnboardingSession with orphaned data

**Need to check:** Are there FK constraints enforcing referential integrity?

---

## ISSUES FOUND & FIXED (Session B)

✅ **search_tenants:** Multi-table JOIN dedup by tenancy_id (commit b4cc097)  
✅ **list_payments:** Field mapping + dedup by payment_id (commit 016e841)  
✅ **quick_book:** Rejects room 000 (new)  
✅ **pre_register:** Requires room (no 000 fallback) (new)  
✅ **PATCH /tenants/{id}:** Role check added, 11 fields audit-logged (Session B)  
✅ **POST /adjustment:** Role check added (Session B)  
✅ **POST /cancel-no-show:** Role check added (Session B)  
✅ **GET/POST /reminders:** Role checks added (Session B)  
✅ **deposits_eligible:** Fixed to check notice_date (Session B)  

---

## REMAINING AUDIT WORK

### High Priority (likely bugs)
- [ ] **Verify refund calculation** — PWA vs backend alignment
- [ ] **Verify notice logic** — all 3 scenarios (by 5th, late, no notice)
- [ ] **Verify occupancy check** — room 000 rejection is working in all paths
- [ ] **Test payment idempotency** — no double-creation on double-click
- [ ] **Check database orphans** — FK constraints intact

### Medium Priority (consistency)
- [ ] **Audit bot handler logic** — WhatsApp payment/checkout/notice logic
- [ ] **Verify Sheet sync** — payment update triggers correct sheet rewrite
- [ ] **Check cascade deletes** — when tenancy deleted, what happens to payments/sessions/checkouts

### Documentation
- [ ] Create dependency matrix (which endpoint calls which)
- [ ] Document all business logic by feature (payments, notices, checkout, bookings)
- [ ] Add integration tests for multi-step flows

---

## NEXT IMMEDIATE STEPS

1. **Refund calculation audit** — Compare PWA calc code with backend expectation
2. **Notice logic audit** — Verify 3 scenarios across all 5 code locations
3. **Payment idempotency test** — Check if double-click creates duplicate payment
4. **Database integrity** — Query for orphaned records

These are the most likely places for bugs based on the patterns already found (multi-table JOINs, field mapping, role checks).
