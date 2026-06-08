# Critical Audit Findings — What Works vs What Needs Verification

**Session B Audit Status:** Partway through proper end-to-end audit

---

## ✅ VERIFIED SAFE (Checked thoroughly)

1. **Multi-table JOIN deduplication**
   - search_tenants: Dedup by tenancy_id ✓ (commit b4cc097)
   - list_payments (tenant_id path): Dedup by payment_id ✓ (commit 016e841)
   - list_tenants: No dedup needed (1:1 joins) ✓
   - getActiveNotices: No dedup needed (1:1 joins) ✓

2. **Payment idempotency**
   - unique_hash prevents same-day same-amount duplicates ✓
   - Hash includes: tenancy_id + date + amount + mode + for_type + period ✓

3. **Role checks**
   - All critical create/edit/delete endpoints protected ✓
   - Added Session B: /tenants/{id}, /adjustment, /cancel-no-show, /reminders ✓

4. **Audit logging**
   - Tenant updates: 11 fields logged ✓ (Session B)
   - Payment edits: 4 fields logged ✓ (Session B)
   - Room transfers: Logged ✓
   - Adjustments: Logged ✓

5. **Room 000 blocking**
   - quick_book rejects room 000 ✓ (Session B)
   - pre_register requires real room (no fallback) ✓ (Session B)

---

## 🔴 CRITICAL — NOT YET VERIFIED

### 1. **Refund Calculation Alignment**

**PWA calculation** (web/app/checkout/new/page.tsx):
```
autoRefund = (deposit - maintenance - dues - deductions) if !depositForfeited else 0
```

**Backend storage** (src/api/v2/checkout.py):
```
refund_amount = body.refund_amount  # Client-supplied value, stored as-is
```

**Risk:** Client calculates refund, backend doesn't validate it.  
**Questions:**
- Is PWA refund calculation correct?
- Does checkout confirmation process validate the refund amount?
- Are deposits showing correctly in payment history?
- Do refund amounts match accounting records?

**Action needed:** Trace one complete checkout flow end-to-end, verify refund calculated same way at each stage.

---

### 2. **Notice Logic Consistency**

**Three different scenarios:**
1. Notice by day 5 → deposit refundable, vacate month-end
2. Notice after 5th → deposit still refundable, extra month's rent due
3. No notice → deposit forfeited

**Code locations to verify:**
- [ ] `src/api/v2/notices.py` — `deposit_eligible = notice_date is not None` (FIXED Session B ✓)
- [ ] `src/api/v2/checkout.py` — forfeiture logic
- [ ] `web/app/checkout/new/page.tsx` — client-side calculation
- [ ] `src/whatsapp/handlers/owner_handler.py` — bot notice handler (UNKNOWN)
- [ ] `web/app/tenants/[tenancy_id]/edit/page.tsx` — notice setting (UNKNOWN)

**Risk:** Notice logic might differ across these 5 places, causing incorrect refunds.  
**Action needed:** Map the notice logic in owner_handler.py and verify it matches the others.

---

### 3. **Occupancy Check Consistency**

**Multiple call sites:**
- quick_book calls `check_room_bookable()`
- onboarding_router.create() calls `check_room_bookable()`
- PWA pre-register calls `checkRoomAvailability()`

**Key question:** When Person A checks out June 30, can Person B be booked July 1?
- Expected: YES (no overlap, July 1 > June 30)
- Actual: Need to verify in code

**Risk:** Inconsistent occupancy logic could allow double-booking or incorrectly reject valid bookings.  
**Action needed:** Trace occupancy check logic, verify boundary conditions (same-day checkout/checkin rejected, next-day allowed).

---

### 4. **Payment Creation Double-Click**

**Scenario:** User clicks "submit payment" twice quickly
- Expected: Second click shows error ("payment already logged") or is ignored
- Actual: First payment succeeds, second is checked against unique_hash

**Verification:** The unique_hash uses `date.today()`, so two payments submitted same day with same amount = rejected. ✓

**But:** What if user submits at 11:59 PM then again at 12:01 AM next day?
- Expected: Two different days = two payments allowed (this is OK, legitimate use case)
- Actual: Hash changes (different date) = creates two payments ✓

**Status:** ✅ Appears safe (idempotency is day-scoped, which makes sense)

---

### 5. **Database Referential Integrity**

**Potential orphans:**
- Payment with deleted Tenancy?
- Tenancy with deleted Tenant?
- CheckoutSession with deleted Tenancy?
- OnboardingSession with deleted Tenant?

**Action needed:**
```sql
-- Check for orphaned payments
SELECT * FROM payments WHERE tenancy_id NOT IN (SELECT id FROM tenancies);

-- Check for orphaned tenancies
SELECT * FROM tenancies WHERE tenant_id NOT IN (SELECT id FROM tenants);

-- Check for orphaned checkout sessions
SELECT * FROM checkout_session WHERE tenancy_id NOT IN (SELECT id FROM tenancies);

-- Check for orphaned onboarding sessions
SELECT * FROM onboarding_sessions WHERE tenant_id IS NOT NULL AND tenant_id NOT IN (SELECT id FROM tenants);
```

---

## SUMMARY

**Safe to deploy:** 
- Role checks ✓
- Deduplication ✓
- Audit logging ✓
- Room 000 blocking ✓
- Payment idempotency ✓

**High risk — need immediate investigation:**
1. Refund calculation correctness (client-calculated, backend unvalidated)
2. Notice logic consistency across 5 code paths (most complex business logic)
3. Occupancy boundary conditions (is June 30 checkout → July 1 check-in allowed?)
4. Database orphans (FK constraints working?)

**Estimated effort for full audit:** 2-3 hours of code tracing + spot checks

---

## NEXT STEPS

**Immediate (30 min):**
1. Check owner_handler.py notice logic vs notices.py
2. Verify occupancy boundary condition (same-day vs next-day)
3. Run orphan check queries

**If issues found:**
1. Fix and test
2. Create regression tests
3. Document findings

**If no issues found:**
1. Declare audit complete
2. Note what was checked
3. Document any architectural concerns (client-calculated refunds)
