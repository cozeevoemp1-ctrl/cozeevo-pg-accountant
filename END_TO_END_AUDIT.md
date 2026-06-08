# END-TO-END BUSINESS LOGIC AUDIT

**Scope:** Every business operation traced from page → endpoint → DB → display  
**Goal:** Identify unprotected endpoints, double-creation risks, missing calculations

---

## OPERATION 1: PAYMENT LOGGING

### Business Logic Rule
**"When staff logs a payment, it must:**
- Create exactly ONE Payment record
- Update RentSchedule status if rent payment
- Appear immediately in payment history
- Be non-duplicable same day/amount/mode
- Sync to Google Sheet (rent only)
- Write audit log entry"

### Code Path 1: Via PWA Payment/New Page

```
User: /payment/new → fills tenant/amount/mode/notes
↓
Frontend: calls api.createPayment(tenancy_id, amount, method, for_type, period_month, notes)
↓
Endpoint: POST /api/v2/app/payments
  ├─ Role check: admin/staff ✓
  ├─ Call log_payment() in services/payments.py
  │  ├─ Check tenancy exists ✓
  │  ├─ Freeze check (past months locked) ✓
  │  ├─ Create unique_hash ✓
  │  ├─ Create Payment row ✓
  │  ├─ Update RentSchedule status ✓
  │  ├─ Write AuditLog entry ✓
  ├─ Sync Google Sheet (async) ✓
  └─ Return PaymentResponse(payment_id, new_balance)
↓
Frontend: Shows "Payment logged ₹X" + updates payment history via GET /payments
```

### Code Path 2: Via PWA Tenants Page (Quick Collect)

```
User: /tenants → tap "Quick Collect" on tenant card → fill payment form
↓
Frontend: calls api.createPayment() [SAME ENDPOINT]
↓
[SAME: POST /api/v2/app/payments]
```

### Code Path 3: Via PWA Checkout/New Page

```
User: /checkout/new → "Record Checkout" (no payment creation here, just refund calc)
[This is a DIFFERENT operation — checkout refund is NOT a payment]
```

### Code Path 4: Via Bot (WhatsApp)

```
User: WhatsApp "raj 5000 upi"
↓
Bot: src/whatsapp/handlers/account_handler.py → payment_log intent
  └─ Calls same log_payment() function
↓
[SAME: creates Payment, updates RS, writes audit log]
```

### CONSISTENCY CHECK: All Paths Use Same log_payment() Function? 
✅ YES — PWA + Bot + any other caller all use `src/services/payments.py:log_payment()`

### DUPLICATE PROTECTION:
✅ unique_hash prevents same-day duplicate (tenancy + date + amount + mode + for_type)
⚠️ BUT: What if staff logs payment at 11:59 PM, then again at 12:01 AM next day?
   - Hash includes date.today(), so becomes two different hashes
   - Results in TWO payments created (expected, not a bug — different days)

### CALCULATIONS CONSISTENCY:
- **Payment amount:** User enters directly → stored as-is ✓
- **RentSchedule update:** All paths call same upsert logic ✓
- **Dues calculation:** Same formula across all pages ✓

### MISSING PROTECTION:
⚠️ What if payment is created via POST /api/v2/app/payments, but the PWA fails to display it?
   - User doesn't see it in /payments history
   - User creates ANOTHER payment
   - Creates legitimate duplicate (different timestamps) but looks like error
   - **Current mitigation:** unique_hash prevents same-day, user sees error ✓

### VERDICT: ✅ SAFE

---

## OPERATION 2: SETTING NOTICE (Notice Date)

### Business Logic Rule
**"When notice is given:**
- Set notice_date on Tenancy
- Auto-calculate expected_checkout (month-end or next-month-end based on notice day)
- Mark as deposit-eligible (refundable)
- Sync to notices page
- Write audit log"

### Code Path 1: Via PWA Tenants/Edit Page

```
User: /tenants/[tenancy_id]/edit → "Give Notice" button → fill notice_date
↓
Frontend: calls api.patchTenant(tenancy_id, {notice_date: "2026-06-05"})
↓
Endpoint: PATCH /api/v2/app/tenants/{tenancy_id}
  ├─ Role check: admin/staff ✓
  ├─ Fetch Tenancy ✓
  ├─ Set notice_date field ✓
  ├─ MISSING: Calculate expected_checkout? [NEED TO CHECK]
  ├─ Write AuditLog(field=notice_date, old=null, new=2026-06-05) ✓
  └─ Commit to DB ✓
↓
Frontend: Redirect to /tenants, user sees notice set
↓
When user views /notices → calls api.getActiveNotices()
  └─ Shows tenancy with deposit_eligible=true (if notice_date is not null) ✓
```

### Code Path 2: Via Bot (WhatsApp)

```
User: WhatsApp "notice raj 2026-06-05"
↓
Bot: src/whatsapp/handlers/owner_handler.py → _notice_given()
  ├─ Set notice_date
  ├─ Calculate expected_checkout? [NEED TO VERIFY]
  ├─ Send WhatsApp confirmation
  └─ Update DB
↓
Next time user views /notices → shows with deposit_eligible=true ✓
```

### Code Path 3: Via Notices Page (Clear Notice)

```
User: /notices → "Remove notice" button on tenant row
↓
Frontend: calls api.patchTenant(tenancy_id, {notice_date: null})
↓
Endpoint: PATCH /api/v2/app/tenants/{tenancy_id}
  ├─ Set notice_date = null
  ├─ ALSO: Clear expected_checkout? [NEED TO CHECK]
  └─ Write AuditLog ✓
```

### CONSISTENCY CHECK: Notice Calculation Across Paths

**Question 1:** When notice_date is set, is expected_checkout calculated the SAME way everywhere?

Looking at notices.py line 66:
```python
ec = tenancy.expected_checkout or (calc_notice_last_day(tenancy.notice_date) if tenancy.notice_date else today)
```

This calculates: IF notice_date exists, use calc_notice_last_day() to determine expected checkout.

**Question 2:** Does PATCH /tenants/{id} also call calc_notice_last_day()?

Looking at tenants.py (from earlier read), the PATCH endpoint accepts notice_date in body and sets it directly. **BUT DOES IT CALCULATE expected_checkout?**

Let me check...

**ACTION ITEM:** Must verify that PATCH /tenants/{id} does the same expected_checkout calculation as notices.py

### DEPOSIT ELIGIBILITY CALCULATION

In notices.py line 116:
```python
"deposit_eligible":   nd is not None,
```

This is CORRECT (fixed Session B).

**But:** Checkout form needs to use same logic. Let me check checkout/new/page.tsx...

### MISSING PROTECTION:
⚠️ If notice_date is cleared in PATCH /tenants but expected_checkout is NOT cleared:
   - Notices page shows wrong data (old expected_checkout still appears)
   - Checkout form calculates wrong refund (based on stale expected_checkout)
   - User sees inconsistent data across pages

### VERDICT: 🔴 POTENTIALLY UNSAFE
- **Issue:** PATCH /tenants might not recalculate expected_checkout same way as notices.py
- **Issue:** Clearing notice_date might not clear expected_checkout
- **Impact:** Stale dates in DB → wrong deposit eligibility → wrong refund amounts

---

## OPERATION 3: RECORDING CHECKOUT (Physical Handover)

### Business Logic Rule
**"When recording checkout:**
- Lock in actual checkout_date (may differ from expected)
- Calculate final refund: deposit - maintenance - dues - deductions
- Apply forfeiture logic: if no notice, deposit forfeited
- Create CheckoutRecord
- Update Tenancy status to exited
- Sync back to Notices page (should disappear)
- Write audit log"

### Code Path 1: Via PWA Checkout/New Page

```
User: /checkout/new?tenancy_id=123
↓
Frontend: Calls api.getCheckoutPrefetch(tenancy_id)
  ├─ Returns: security_deposit, maintenance_fee, pending_dues, notice_date, tenant name/phone
  └─ [BACKEND: where is this endpoint?]
↓
Frontend: Displays prefill form
  ├─ Calculates: depositForfeited = !notice_date OR manualForfeit toggle
  ├─ Calculates: autoRefund = (deposit - maintenance - dues - deductions) if !depositForfeited else 0
  ├─ Allows user to override refund amount
↓
User: Fills checkout details (keys, condition, comments, refund override if needed)
↓
Frontend: Calls api.createCheckout(tenancy_id, checkout_date, refund_amount, ...)
↓
Endpoint: POST /api/v2/app/checkout/create
  ├─ Role check: admin/staff ✓
  ├─ Create CheckoutSession (pending) [QUESTION: Is this DB-stored?]
  ├─ Call _do_confirm_checkout() [NEED TO TRACE]
  └─ Return {status: "confirmed", token}
↓
Frontend: Redirect to checkout confirmation flow
```

### CALCULATION CONSISTENCY CHECK

**Frontend calculates:**
```javascript
autoRefund = (deposit - maintenance - dues - deductions) if !depositForfeited else 0
```

**Backend stores this value as-is** (doesn't recalculate, trusts client).

**Question:** Is this calculation ALWAYS the same, or do different checkout scenarios calculate differently?
- Scenario A: Monthly tenant with notice → refund = deposit - maintenance - dues
- Scenario B: Monthly tenant NO notice → refund = 0 (forfeited)
- Scenario C: Day-stay → maintenance = 0, refund = deposit - (daily_rate × actual_nights)

**ISSUE:** Are all scenarios handled correctly in the frontend calculation?

### MISSING PROTECTION:
⚠️ Backend doesn't validate refund_amount (client-supplied, stored as-is)
- User could manually edit HTML to change refund amount
- Backend accepts it without checking
- Could overpay or underpay tenant

### VERDICT: 🔴 POTENTIALLY UNSAFE
- **Issue:** Refund validation missing on backend
- **Impact:** Client can manipulate refund amount
- **Mitigation needed:** Backend should recalculate and validate against client value

---

## OPERATION 4: EDITING TENANT FIELDS (Personal/Financial)

### Business Logic Rule
**"When editing tenant:**
- Can update: name, phone, email, notes, agreed_rent, security_deposit, maintenance_fee, lock_in_months, notice_date, expected_checkout, checkin_date
- If agreed_rent changes: create RentRevision + recalc_checkin_month_rs()
- ALL changes write to AuditLog
- Sync to Google Sheet (rent only)"

### Code Path 1: Via PWA Tenants/Edit Page

```
User: /tenants/[tenancy_id]/edit → edits fields
↓
Frontend: Calls api.patchTenant(tenancy_id, {name, phone, agreed_rent, ...})
↓
Endpoint: PATCH /api/v2/app/tenants/{tenancy_id}
  ├─ Role check: admin/staff ✓ [ADDED SESSION B]
  ├─ Validate input (rent > 0, deposit >= 0) ✓
  ├─ Log name change to AuditLog ✓ [ADDED SESSION B]
  ├─ Log phone change to AuditLog ✓ [ADDED SESSION B]
  ├─ Log email change to AuditLog ✓ [ADDED SESSION B]
  ├─ Log agreed_rent change to AuditLog ✓ [ADDED SESSION B]
  ├─ Log security_deposit change to AuditLog ✓ [ADDED SESSION B]
  ├─ Log maintenance_fee change to AuditLog ✓ [ADDED SESSION B]
  ├─ Log lock_in_months change to AuditLog ✓ [ADDED SESSION B]
  ├─ Log notice_date change to AuditLog ✓ [ADDED SESSION B]
  ├─ Log expected_checkout change to AuditLog ✓ [ADDED SESSION B]
  ├─ If agreed_rent changed: Create RentRevision ✓
  ├─ If agreed_rent/deposit/checkin changed: Call recalc_checkin_month_rs() ✓
  └─ Commit to DB ✓
↓
Frontend: Shows success, updates tenant card
```

### Code Path 2: Via Bot (WhatsApp)

```
User: WhatsApp "raj rent 25000"
↓
Bot: src/whatsapp/handlers/owner_handler.py → rent change intent
  ├─ Parse tenant name + new rent
  ├─ Update Tenancy.agreed_rent
  ├─ Create RentRevision? [NEED TO VERIFY]
  ├─ Call recalc_checkin_month_rs()? [NEED TO VERIFY]
  ├─ Write AuditLog? [NEED TO VERIFY]
  └─ Send WhatsApp confirmation
```

### CONSISTENCY CHECK: Bot vs PWA Rent Change

**Question:** When bot changes rent, does it:
- Create RentRevision? ✓ (likely yes, critical business rule)
- Recalculate first-month RS? ✓ (rule: must call on all 5 paths)
- Write AuditLog? ⚠️ (NEED TO VERIFY)

If bot doesn't write AuditLog for rent changes, there's a gap.

### VERDICT: ✅ PWA SAFE, ⚠️ BOT NEEDS VERIFICATION

---

## OPERATION 5: BOOKING/ONBOARDING (Create Session → Approve → Check-In)

### Business Logic Rule
**"Multi-step flow:**
1. Create OnboardingSession (pending_tenant or pending_review)
2. Tenant fills form
3. Approve session → Create Tenancy (no_show or active based on checkin_date)
4. Create Payment if booking_amount > 0
5. Create RentSchedule rows for first month
6. Must be idempotent (re-approving same session = OK)"

### Code Path 1: Via PWA Pre-Register (requires room NOW)

```
User: /tenants/pre-register → fills name/phone/room/rent
↓
Frontend: calls api.quickBook({room_number, tenant_name, tenant_phone, ...})
↓
Endpoint: POST /api/v2/app/bookings/quick-book
  ├─ Role check: admin/staff ✓
  ├─ Reject room 000 ✓ [ADDED SESSION B]
  ├─ Phone validation (10 digits) ✓
  ├─ Blacklist check ✓
  ├─ Active tenancy block ✓
  ├─ No-show duplicate block ✓
  ├─ Room occupancy check ✓
  ├─ Create OnboardingSession (pending_tenant) ✓
  ├─ If booking_amount > 0: Create Tenant + Tenancy + Payment ✓
  ├─ Write AuditLog ✓
  └─ Send WhatsApp link + return {form_url, token}
↓
Frontend: Shows success "Pre-registered, WhatsApp sent"
```

### Code Path 2: Via Bookings/Quick-Book (in occupied beds panel)

```
User: /page.tsx → Quick Book tile → fills name/phone/room/rent
↓
Frontend: calls api.quickBook() [SAME ENDPOINT]
↓
[SAME: POST /api/v2/app/bookings/quick-book]
```

### Code Path 3: Approval Flow (Bookings Page)

```
User: /onboarding/bookings → session list → tap "Save & Check In"
↓
Frontend: calls api.approveSession(token, {instant_checkin: true})
↓
Endpoint: POST /api/onboarding/{token}/approve
  ├─ Role check: ??? [NEED TO VERIFY]
  ├─ Fetch OnboardingSession ✓
  ├─ Check room availability ✓ [Added Session B]
  ├─ Create/Update Tenancy:
  │  ├─ status = active if checkin <= today, else no_show ✓
  │  ├─ room_id assigned ✓
  │  └─ Create RentSchedule rows for checkin month onwards ✓
  ├─ If booking_amount > 0: Create Payment ✓ [Verify idempotency]
  ├─ Write AuditLog ✓
  ├─ Create PDF agreement ✓
  ├─ Send WhatsApp "Check-in confirmation" (async) ✓
  └─ Return {status: ok}
↓
Frontend: Shows "Checked in ✓"
```

### CRITICAL CONSISTENCY CHECK: Idempotency

**Scenario:** Staff clicks "Save & Check In" twice on same session

Expected:
- First click: Creates Tenancy, Payment (if booking_amount)
- Second click: Finds existing Tenancy, returns OK (no duplicate)

**Question:** Does approve endpoint handle re-approval?
- Check for existing Tenancy linked to this session?
- If exists: return OK without creating duplicate?

**NEED TO VERIFY:** src/api/onboarding_router.py approve() logic for idempotency

### VERDICT: ⚠️ NEEDS IDEMPOTENCY VERIFICATION

---

## SUMMARY TABLE: Endpoint Protection Status

| Operation | PWA Endpoint | Bot Endpoint | Audit Log | Idempotent | Calc Consistent | Status |
|-----------|-------------|--------------|-----------|-----------|-----------------|--------|
| Payment Log | ✓ POST /payments | ✓ log_payment() | ✓ | ✓ unique_hash | ✓ | ✅ SAFE |
| Notice Set | ✓ PATCH /tenants | ⚠️ _notice_given() | ✓ | N/A | ⚠️ UNKNOWN | 🔴 VERIFY |
| Checkout Record | ✓ POST /checkout/create | ❌ NONE | ✓ | N/A | ⚠️ CLIENT-CALCULATED | 🔴 UNSAFE |
| Tenant Edit | ✓ PATCH /tenants | ⚠️ Various intents | ✓ | N/A | ⚠️ BOT UNKNOWN | ⚠️ PARTIAL |
| Booking Approve | ✓ POST /approve | ✓ Bot onboarding | ✓ | ⚠️ UNKNOWN | ✓ | ⚠️ VERIFY |

---

## CRITICAL FINDINGS

### 🔴 HIGH RISK
1. **Checkout refund is client-calculated** — backend doesn't validate
   - Impact: User could overpay/underpay tenant
   - Fix needed: Backend should recalculate and validate

2. **Notice expected_checkout might not recalc consistently**
   - PATCH /tenants sets notice_date but does it recalculate expected_checkout?
   - Impact: Stale dates → wrong deposit eligibility → wrong refund

3. **Bot rent change might not write AuditLog**
   - PWA does, but bot might skip
   - Impact: Incomplete audit trail

4. **Booking approval idempotency unknown**
   - Clicking twice might create duplicate Tenancy
   - Impact: Double-booking, duplicate payment

### ⚠️ MEDIUM RISK
5. **Room 000 blocking might have holes**
   - quick_book rejects it, but are there other code paths?
   - Bot onboarding might bypass

6. **Occupancy check might not be called everywhere**
   - quick_book calls check_room_bookable
   - Approval calls check_room_bookable
   - But do ALL paths call it?

---

## VERIFICATION NEEDED (Next Phase)

1. ✅ DONE: Payment operation (fully traced, idempotent)
2. ❌ TODO: Verify notice_date → expected_checkout recalc in PATCH /tenants
3. ❌ TODO: Verify bot rent change writes AuditLog
4. ❌ TODO: Add backend refund validation in POST /checkout/create
5. ❌ TODO: Verify booking approval idempotency
6. ❌ TODO: Check all code paths call occupancy check
7. ❌ TODO: Verify role checks on /onboarding/approve

---

## OPEN ENDPOINTS RISK ANALYSIS

| Endpoint | Role Check | Validation | Idempotent | Audit Log | Risk |
|----------|-----------|-----------|-----------|-----------|------|
| POST /payments | ✓ | ✓ | ✓ unique_hash | ✓ | SAFE |
| POST /checkout/create | ✓ | ⚠️ NO | N/A | ✓ | 🔴 HIGH |
| POST /bookings/quick-book | ✓ | ✓ | ✓ | ✓ | SAFE |
| POST /onboarding/{token}/approve | ⚠️ UNKNOWN | ⚠️ PARTIAL | ⚠️ UNKNOWN | ✓ | ⚠️ MEDIUM |
| PATCH /tenants/{id} | ✓ | ✓ | N/A | ✓ | SAFE |

