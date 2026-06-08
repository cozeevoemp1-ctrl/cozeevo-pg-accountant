# Financial Domain Audit — PWA Pages & API Endpoints
**Date:** 2026-06-08  
**Scope:** Notices, Checkout, Checkouts, Payments History, Finance pages + backend endpoints  
**Status:** COMPLETE with findings

---

## 1. FINANCIAL PAGES INVENTORY

### 1.1 /notices — Active Tenants with Notice/Checkout in 30 days

**What it does:**
- Lists all active monthly tenants with formal notice OR lock-in exits within 60-day window
- Day-stay tenants within 30 days of checkout
- Separates "Deposit Eligible" vs "Deposit Forfeited" sections
- Filters by month, type (full-room, premium, gender, day-stay)
- Allows editing expected_checkout date

**Endpoints called:**
```
GET /api/v2/app/notices/active
PATCH /api/v2/app/tenants/{tenancy_id} (notice_date, expected_checkout)
```

**Business logic used:**
- `deposit_eligible`: hardcoded `True` for all monthly tenants in response (line 116)
  - **⚠️ BUG FOUND** (see §3.1) — deposits should be forfeited if NO notice, but code returns True for all
- `days_remaining`: `(expected_checkout - today).days` (line 95)
- `expected_checkout`: calculated from `notice_date` using `calc_notice_last_day()` if no explicit checkout (line 66)
- Notice rule: Given on/before 5th → vacate by month-end. After 5th → next month

**Related rules (docs/REPORTING.md, docs/BUSINESS_LOGIC.md):**
- Notice by day 5 of month → eligible for refund, vacate by month-end
- Late notice (after 5th) → deposit still refundable, but extra month's rent due
- No notice → deposit forfeited (but page doesn't show this correctly)

**Data flow:**
```
API getActiveNotices()
  ↓
Notices page useState(items)
  ↓
NoticeCard component — shows deposit_eligible badge
  ↓ (user clicks "Edit notice")
patchTenant() → api.ts PATCH /api/v2/app/tenants/{tenancy_id}
```

---

### 1.2 /checkout/new — Create New Physical Checkout

**What it does:**
- Record physical handover (keys, biometric, room condition)
- Calculate refund: `max(deposit - maintenance - unpaid_dues - deductions, 0)`
- Handle day-wise: recalculate dues based on actual vs booked checkout date
- Support manual forfeit toggle for emergency exits
- Support refund override for anomalies

**Endpoints called:**
```
GET /api/v2/app/tenants/{tenancy_id}/dues (URL param prefill)
GET /api/v2/app/checkout/tenant/{tenancy_id} (get prefetch data)
POST /api/v2/app/checkout/create (submit checkout)
PATCH /api/v2/app/tenants/{tenancy_id} (URL param auto-load)
```

**Business logic used:**
- **Notice & deposit forfeiture** (lines 115–120):
  ```typescript
  const depositForfeited = prefetch && !isDaily 
    ? (!prefetch.notice_date || manualForfeit) 
    : false
  ```
  - Monthly tenants: forfeited if NO notice OR user toggles emergency exit
  - Day-wise: never forfeited (no notice period)

- **Refund calculation** (lines 140–144):
  ```typescript
  const autoRefund = prefetch && !depositForfeited
    ? Math.max(prefetch.security_deposit - prefetch.maintenance_fee 
                - totalPendingDues - deductionsNum, 0)
    : 0
  ```

- **Day-wise adjustment** (lines 128–136):
  ```
  nightsDiff = (actual_checkout - booked_checkout) days
  nightsAdjustment = nightsDiff * daily_rate
  totalPendingDues = max(0, pending_dues + nightsAdjustment)
  ```

- **Notice last-day rule** (lines 118–125):
  ```typescript
  function calcLastDay(noticeDateISO: string): string {
    const noticeDay = date.getDate()
    const eligible = noticeDay <= 5  // NOTICE_BY_DAY = 5
    const ld = new Date(year, eligible ? m : m+1, 0)  // month-end of eligible/next month
  }
  ```

**Related rules:**
- Deposit = security_deposit - maintenance_fee - unpaid_rent - deductions (MIN 0)
- No notice → auto-forfeited (refund = 0, override available)
- Maintenance fee always deducted (never refunded)
- Days of unpaid rent deducted from deposit
- Deductions (damage/other) deducted from deposit

**Data flow:**
```
1. User searches tenant (TenantSearch component)
2. getCheckoutPrefetch() → prefill deposit/dues/notice
3. User fills form:
   - checkout_date (+ time for day-wise)
   - handover checklist
   - deductions (if applicable)
   - refund_mode (Cash/UPI/Bank)
4. createCheckout() → POST /api/v2/app/checkout/create
5. Success screen shows confirmation + waits for tenant consent
```

---

### 1.3 /checkouts — History of Completed Checkouts

**What it does:**
- Lists all tenants who checked out in a selected month (default current)
- Shows security deposit + refund amount per checkout
- Filters by stay type (All/Regular/Day-wise)
- Month picker (can go back, not forward)

**Endpoints called:**
```
GET /api/v2/app/checkouts?month=YYYY-MM
```

**Business logic used:**
- Filters by month (start/end inclusive)
- Counts refund_amount from checkout_records table
- Joins Tenancy (status=exited) + Tenant + Room

**Related rules:**
- Only exited tenancies (status='exited')
- Excludes staff rooms (is_staff_room=False)
- Excludes placeholder room 000

**Data flow:**
```
Checkouts page
  ↓
getCheckouts(month) with URLSearchParams
  ↓
Display list, summary (count + total refunded)
```

---

### 1.4 /payments/history — Payment Log & Edit

**What it does:**
- Show recent payments (30 limit)
- Tenant-scoped search: select tenant → show their payments only
- Edit payment: method, amount, for_type, notes
- Void payment (soft-delete with is_void=true)

**Endpoints called:**
```
GET /api/v2/app/payments (all recent, or tenant-scoped)
GET /api/v2/app/tenants/search (tenant picker)
PATCH /api/v2/app/payments/{payment_id}
DELETE /api/v2/app/payments/{payment_id} (void)
```

**Business logic used:**
- None specific; payment editing is operational (logging, not financial rule)
- Void flag preserves audit trail (never hard-delete)

**Related rules:**
- Payment methods: UPI, CASH, BANK
- Payment types: rent, deposit, booking, maintenance, food, penalty, other
- All voids must write AuditLog (enforced in backend)

**Data flow:**
```
Page loads → getPaymentHistory(undefined, 30) → show recent
User selects tenant → getPaymentHistory(tenancy_id, 30) → show tenant-scoped
User edits → editPayment() → PATCH
User voids → voidPayment() → DELETE (is_void flag)
```

---

### 1.5 /finance — Owner Dashboard (Admin-only)

**What it does:**
- Three-statement tab: P&L (income, expenses, profit)
- Occupancy tab: KPIs + charts (check-ins/checkouts, occupancy %)
- Investment section: per-investor breakdown (collapsible)
- CSV upload for bank statements

**Endpoints called:**
```
GET /api/v2/app/finance/pnl?month=YYYY-MM
GET /api/v2/app/finance/pnl/excel (download verified P&L)
GET /api/v2/app/finance/pnl/live (download live P&L)
GET /api/v2/app/analytics/occupancy?months=N
GET /api/v2/app/finance/unit-economics?month=YYYY-MM
GET /api/v2/app/finance/investments
POST /api/v2/app/finance/upload (CSV batch/bank upload)
GET /api/v2/app/finance/cash?month=YYYY-MM
GET /api/v2/app/finance/cash/expenses
POST /api/v2/app/finance/cash/expenses
GET /api/v2/app/finance/reconcile?month=YYYY-MM
POST /api/v2/app/finance/upi-reconcile (UPI file upload)
GET /api/v2/app/finance/upi-reconcile/unmatched
```

**Business logic used:**
- **P&L structure** (from docs/REPORTING.md):
  - Gross inflows: bank UPI (THOR/HULK) + cash
  - Less: security deposits (refundable) = True Revenue
  - Opex: expense categories (Property Rent, Electricity, etc.)
  - Operating Profit = True Revenue − Opex
  - Capex: furniture, capital investment
  - Net Profit = Operating Profit − Capex

- **Occupancy KPI** (from docs/BUSINESS_LOGIC.md):
  - Total beds = SUM(max_occupancy WHERE is_staff_room=False)
  - Occupied = SUM(1 for regular tenants, max_occupancy for premium)
  - Occupancy % = occupied / total * 100

- **Unit Economics** (src/services/unit_economics.py):
  - Revenue/bed, opex/bed, EBITDA/bed
  - Collection rate = collected / billed
  - Investment return metrics (yield %, payback months)

**Related rules:**
- Admin-only (JWT role check on line 17)
- Verified P&L (Oct'25–Apr'26) is hardcoded and frozen
- Live P&L updates with new uploads
- Investment expenses tracked separately

**Data flow:**
```
Finance page mounted → auth check (admin?)
  ↓
ThreeStatementTab → getFinancePnl() → draw P&L cards
OccupancyTab → getOccupancyData() → KPI cards + charts
InvestmentSection → getInvestments() → collapsible per-investor
CashTab → getCashPosition() → expenses + balance
```

---

## 2. ENDPOINT AUDIT MATRIX

| Endpoint | File | What Returns | Rule Implemented | Code Match Docs? |
|---|---|---|---|---|
| **GET /notices/active** | src/api/v2/notices.py:23–176 | NoticeItem[] (monthly + daily) | Notice rule (day 5), deposit eligibility | ⚠️ **CONFLICT** (see §3.1) |
| **GET /checkouts** | src/api/v2/checkouts.py:19–75 | CheckoutListItem[] with refund_amount | Filter by exited status + month | ✅ Correct |
| **GET /checkout/tenant/{id}** | src/api/v2/checkout.py:32–64 | CheckoutPrefetch (deposit, dues, notice) | Prefill for form | ✅ Correct |
| **POST /checkout/create** | src/api/v2/checkout.py:87–200+ | CheckoutCreateResponse (token, confirm_link) | Store checklist + financial details | ✅ Correct |
| **GET /checkout/status/{token}** | src/api/v2/checkout.py:200+ | CheckoutStatusResponse (status, dates) | Poll session status | ✅ Correct |
| **GET /tenants/{id}/dues** | src/api/v2/tenants.py:180+ | TenantDues (rent, deposit, adjustment) | Monthly dues formula | ✅ Correct (see §2.2) |
| **PATCH /tenants/{id}** | src/api/v2/tenants.py:250+ | PatchTenantResponse (updated fields) | Update personal + financial fields, trigger recalc_checkin_month_rs() | ⚠️ **WARN** (see §3.4) |
| **GET /payments** | src/api/v2/payments.py:50+ | PaymentListItem[] | Recent payments (30 limit) or tenant-scoped | ✅ Correct |
| **PATCH /payments/{id}** | src/api/v2/payments.py:130+ | PaymentListItem | Edit payment (method, amount, notes) | ✅ Correct |
| **DELETE /payments/{id}** | src/api/v2/payments.py:160+ | 204 No Content | Void payment (is_void=true) | ✅ Correct (AuditLog written) |
| **GET /finance/pnl** | src/api/v2/finance.py:200+ | FinancePnlResponse (months, data) | P&L by month | ✅ Correct |
| **GET /finance/pnl/excel** | src/api/v2/finance.py:250+ | Excel bytes | Verified P&L (Oct'25–Apr'26 hardcoded) | ✅ Correct |
| **GET /analytics/occupancy** | src/api/v2/analytics.py:30+ | OccupancyData (KPI + monthly breakdown) | Occupancy % + check-in/checkout counts | ✅ Correct |
| **GET /finance/unit-economics** | src/api/v2/finance.py:300+ | UnitEconomics | Revenue/bed, EBITDA, collection %, ROI | ✅ Correct |
| **GET /finance/investments** | src/api/v2/finance.py:350+ | InvestmentsData (per-investor groups) | Investment tracking | ✅ Correct |

---

## 3. INCONSISTENCIES & BUGS FOUND

### 3.1 🔴 CRITICAL: Notices Page Returns Wrong `deposit_eligible` Value

**Location:** `web/app/notices/page.tsx:126–127`; `src/api/v2/notices.py:116`

**What's wrong:**
```typescript
// In notices page (tsx):
const eligible  = monthlyItems.filter(i => i.deposit_eligible)
const forfeited = monthlyItems.filter(i => !i.deposit_eligible)
```

But the backend **always** returns `deposit_eligible: True` for ALL monthly tenants (notices.py:116), regardless of whether they gave notice.

**Expected behavior (docs/REPORTING.md, /checkout/new page logic):**
```
Monthly tenants WITH notice (on/before 5th):       deposit_eligible = True
Monthly tenants WITH late notice (after 5th):      deposit_eligible = True
Monthly tenants WITH NO notice:                    deposit_eligible = False
Day-wise tenants (any):                            deposit_eligible = False
```

**Current behavior:**
```
All monthly tenants:    deposit_eligible = True  ← WRONG
Day-wise tenants:       deposit_eligible = False ✅
```

**Impact:**
- Notices page shows "Deposit Eligible" and "Deposit Forfeited" sections, but ALL monthly tenants fall into "Eligible"
- "Deposit Forfeited" section is always empty for monthly tenants
- User sees wrong refund expectation (forfeited deposits shown as refundable)
- Checkout page DOES correctly handle this (line 116 in checkout/new: `depositForfeited = !prefetch.notice_date`)

**Root cause:**
- Backend doesn't calculate deposit eligibility; returns hardcoded `True`
- Frontend notices page tries to filter by a field that's always the same value

**Fix recommendation:**
1. Backend: Calculate `deposit_eligible` in notices.py based on `notice_date`:
   ```python
   # Line 115–120
   deposit_eligible = tenancy.notice_date is not None
   ```
   
2. Frontend notices page: Use actual deposit_eligible value from API (already does this; just fix backend)

**Severity:** CRITICAL — Shows wrong data to user (confuses checkout eligibility)

**Affected pages:**
- /notices (filtering broken; section always empty)
- No impact on /checkout/new (uses notice_date directly, logic correct)
- No impact on /checkouts (refund_amount from checkout_records, not notices)

---

### 3.2 ⚠️ MEDIUM: Notices Page Doesn't Distinguish Late Notice From On-Time

**Location:** `web/app/notices/page.tsx:126–127`

**What's wrong:**
```typescript
const eligible  = monthlyItems.filter(i => i.deposit_eligible)
const forfeited = monthlyItems.filter(i => !i.deposit_eligible)
```

Page splits only into "Deposit Eligible" vs "Forfeited", but docs/REPORTING.md rule is:
- Notice on/before 5th → refundable, vacate by month-end
- Notice after 5th → still refundable, but extra month's rent applies

The page doesn't show the "extra month's rent" warning for late notices.

**Expected:** Three sections:
1. On-time notice (eligible, month-end exit)
2. Late notice (eligible, but +1 month rent)
3. No notice (forfeited)

**Current:** Two sections (after fixing 3.1):
1. Eligible (both on-time + late)
2. Forfeited (no notice)

**Checkout page (line 468–484) DOES show this correctly:**
```typescript
if (lateNotice) {
  return "Notice on {date} (after 5th) — extra month's rent applies"
}
```

**Impact:** Medium — notices page doesn't warn users about late notice implications, but checkout page does.

**Fix recommendation:**
- Add a third section or badge in notices page for late notices
- Show "Extra month's rent applies" banner

**Severity:** MEDIUM

---

### 3.3 ⚠️ MEDIUM: Occupancy Chart Data Type Mismatch

**Location:** `web/components/finance/occupancy-tab.tsx`; `src/api/v2/analytics.py`

**What's wrong:**
API returns `OccupancyMonthData.checkouts` as `number | null`:
```typescript
checkouts: number | null  // null = no DB data (historical import)
```

But the occupancy chart tries to use it directly in Chart.js without null-check:
```typescript
datasets: [{
  label: "Checkouts",
  data: data.months.map(m => m.checkouts ?? 0)  // Fallback to 0, correct
}]
```

**Actually, the page IS correctly handling nulls** (line uses `?? 0` fallback). So this is NOT a bug, but a fragile pattern.

**Impact:** Low — works as intended, but could break if someone removes the `?? 0` fallback.

**Fix recommendation:**
- Document why checkouts can be null (historical data doesn't have checkout records)
- Add a comment in the component

**Severity:** LOW (working as intended, but fragile)

---

### 3.4 ⚠️ MEDIUM: Missing First-Month Rent Recalculation on PATCH /tenants/{id}

**Location:** `web/app/tenants/[tenancy_id]/edit/page.tsx` (PWA edit form); `src/api/v2/tenants.py` PATCH handler

**What's wrong:**
When user edits a tenant's `agreed_rent`, `security_deposit`, or `checkin_date`, the first month's rent schedule must be recalculated (from docs/CLAUDE.md, project instructions):

> "First-month RS auto-recalc — whenever security_deposit/checkin_date/agreed_rent changes, call `recalc_checkin_month_rs()` from `src/services/rent_schedule.py`; 5 call-sites must stay in sync"

But the PATCH endpoint doesn't call `recalc_checkin_month_rs()` after updating these fields.

**Expected:**
```python
# In src/api/v2/tenants.py PATCH handler
if body.agreed_rent or body.security_deposit or body.checkin_date:
    await recalc_checkin_month_rs(tenancy_id, session)
```

**Current:**
- API just updates fields without recalculation
- First-month rent_schedule becomes stale if these fields change

**Impact:** Users editing tenants on PWA get wrong first-month dues until next bot interaction.

**Test case:**
1. Create monthly tenant with ₹12K rent, ₹3K deposit, checkin 2026-06-10
2. Edit form changes rent to ₹15K
3. First-month RS still shows old ₹12K prorated amount

**Fix recommendation:**
1. Add to PATCH /tenants/{id} handler (before commit):
   ```python
   if tenancy.stay_type == StayType.monthly:
       if body.agreed_rent or body.security_deposit or body.checkin_date:
           await recalc_checkin_month_rs(tenancy.id, session)
   ```

2. Add test in tests/api/v2/test_v2_tenants.py

**Severity:** MEDIUM — affects first-month rent calculation on PWA edits

**Related:** CLAUDE.md line "5 call-sites must stay in sync" — need to check all 5 are updated

---

### 3.5 ⚠️ LOW: Checkout Page Hard-Coded NOTICE_BY_DAY Constant

**Location:** `web/app/checkout/new/page.tsx:18`; `web/app/notices/page.tsx:9`

**What's wrong:**
Notice cutoff date is hardcoded as `5` in two places:
- web/app/checkout/new/page.tsx:18
- web/app/notices/page.tsx:9

But it should come from a single source of truth (either backend or shared constant).

**Current:**
```typescript
const NOTICE_BY_DAY = 5  // duplicated in 2 files
```

**Docs:** docs/REPORTING.md:384 mentions "5th" but doesn't hardcode it.

**Backend:** `src/property_logic.py` has `calc_notice_last_day()` which uses the day 5 rule (line 12).

**Risk:** If rule changes to day 3, both FE files must be updated (easy to miss one).

**Fix recommendation:**
- Create shared constant: `web/lib/constants.ts:NOTICE_BY_DAY = 5`
- Import in both pages

**Severity:** LOW — low-risk change, but good refactor

---

## 4. TEST COVERAGE GAPS

### 4.1 Deposit Eligibility Tests

**Rule:** Deposit eligible = has notice (True) or no notice (False)

**Current tests:**
```
grep -r "deposit_eligible" tests/
```
**Result:** 0 matches in test files

**Missing:**
- Unit test: `test_deposit_eligible_on_time_notice()` — verify backend returns True
- Unit test: `test_deposit_eligible_no_notice()` — verify backend returns False
- Unit test: `test_deposit_eligible_late_notice()` — verify backend returns True
- E2E test: Flow from notice → checkout → refund calculation

**Impact:** CRITICAL rule with zero test coverage

---

### 4.2 Notice Last-Day Calculation Tests

**Rule:** Notice on/before 5th → month-end. After 5th → next month-end.

**Current tests:**
```
grep -r "calc_notice_last_day\|NOTICE_BY_DAY" tests/
```
**Result:** 0 matches

**Missing:**
- `test_notice_on_time()` — 5 days or earlier → this month-end
- `test_notice_late()` — 6+ days → next month-end
- `test_notice_last_day_edge()` — day 5, day 6, month end-of-month, etc.

**Impact:** HIGH — core notice logic untested

---

### 4.3 Day-Wise Checkout Recalculation Tests

**Rule:** Extra/early nights → adjust dues by (nights × daily_rate)

**Current tests:**
```
grep -r "nightsDiff\|nightsAdjustment\|daily_rate" tests/
```
**Result:** 0 matches

**Missing:**
- `test_daywise_extra_nights()` — stay 2 days extra → +2*daily_rate to dues
- `test_daywise_early_checkout()` — leave 3 days early → no refund, recalc dues
- `test_daywise_exact_checkout()` — leave on booked date → no adjustment

**Impact:** MEDIUM — day-wise logic in checkout is untested

---

### 4.4 Refund Calculation Tests

**Rule:** Refund = max(deposit - maintenance - unpaid_rent - deductions, 0)

**Current tests:**
```
grep -r "refund\|deposit.*deduction" tests/
```
**Result:** Some paymentservice tests, but NOT for checkout refund formula

**Missing:**
- `test_refund_calculation_normal()` — deposit ₹5K, maintenance ₹500, no dues → refund ₹4.5K
- `test_refund_calculation_with_dues()` — deposit ₹5K, dues ₹2K → refund ₹3K
- `test_refund_calculation_with_deductions()` — deposit ₹5K, deductions ₹500 → refund ₹4.5K
- `test_refund_calculation_zero()` — deposit ₹5K, dues ₹8K → refund ₹0
- `test_refund_override_forfeited()` — deposit forfeited, user overrides to ₹1K → refund ₹1K

**Impact:** CRITICAL — refund calculation is user-facing financial operation, zero E2E tests

---

### 4.5 Occupancy KPI Tests

**Rule:** Occupied beds = SUM(1 for regular, max_occupancy for premium)

**Current tests:**
```
grep -r "occupancy\|occupied_beds" tests/
```
**Result:** Some occupancy tests exist, but not comprehensive

**Missing:**
- `test_occupancy_only_regular()` — 10 regular tenants in double rooms → 10 beds
- `test_occupancy_only_premium()` — 5 premium tenants in double rooms → 10 beds
- `test_occupancy_mixed()` — 5 regular + 3 premium in double rooms → 11 beds
- `test_occupancy_excludes_staff()` — exclude is_staff_room=True
- `test_occupancy_excludes_noshow_if_future()` — depends on checkin_date

**Impact:** HIGH — displayed to owner on Finance page

---

## 5. BUGS SUMMARY

### 🔴 CRITICAL

1. **Notices page deposit_eligible always True** (§3.1)
   - Backend returns deposit_eligible=True for all monthly tenants
   - Should be False for no-notice tenants
   - Pages affected: /notices (filtering broken), impact LOW on /checkout (uses direct logic)
   - Effort: 1 hour (backend fix + test)

### ⚠️ MEDIUM

2. **Missing late-notice distinction in Notices page** (§3.2)
   - Page doesn't warn about extra month's rent for late notices
   - /checkout/new page DOES warn (correct)
   - Effort: 30 min (add badge + section in notices page)

3. **Missing recalc_checkin_month_rs on PATCH /tenants** (§3.4)
   - Editing agreed_rent/security_deposit/checkin_date doesn't recalculate first-month RS
   - Users see stale dues until next bot interaction
   - Effort: 30 min (add recalc call + test)

### ⚠️ LOW

4. **Hard-coded NOTICE_BY_DAY constant** (§3.5)
   - Duplicated in 2 files instead of single source
   - Low risk, good refactor
   - Effort: 15 min

---

## 6. DESIGN DECISIONS & OBSERVATIONS

### 6.1 Deposit Eligibility Logic — Two Implementations

**Notices page (backend):**
```python
# Always returns True — no filtering
deposit_eligible: True  # Line 116
```

**Checkout page (frontend):**
```typescript
// Correctly derives from notice_date
const depositForfeited = !prefetch.notice_date || manualForfeit
const autoRefund = !depositForfeited ? math.max(...) : 0
```

**Design choice:** Checkout page uses client-side logic (correct), but notices page relies on backend (incorrect). Should standardize on backend calculation.

---

### 6.2 Maintenance Fee Treatment

**Checkout page calculation (line 530–531):**
```
Security deposit: ₹5000
Less: Maintenance fee: −₹500
```

Shows deduction clearly. Maintenance is NEVER refunded, always retained by property.

**Docs:** REPORTING.md line 63: "Maintenance fees (non-refundable) are retained income and stay in Gross Inflows."

**Code matches docs:** ✅

---

### 6.3 Day-Wise Vs Monthly Occupancy

**Notices page:**
- Separates monthly (notice-based) from day-wise (checkout-date-based)
- Monthly: 30–60 day lookahead window
- Day-wise: within 30 days of checkout

**Design is sound.** Allows owner to plan differently for each stay type.

---

### 6.4 Refund Override Pattern

**Checkout page (lines 105–109):**
```typescript
// Manual forfeit toggle — for emergency early exits
const [manualForfeit, setManualForfeit] = useState(false)

// Manual refund override (for anomalies when deposit is forfeited)
const [refundOverride, setRefundOverride] = useState<number | null>(null)
```

Allows owner to:
1. Emergency-forfeit deposits (manual toggle)
2. Override refund amount (numpad input)

**Design choice:** Supports edge cases without requiring backend changes. Good UX.

**Risk:** No audit log for overrides. Should add: "Refund overridden from ₹X to ₹Y" in checkout_records.other_comments.

---

## 7. ENDPOINT DATA CONSISTENCY CHECK

### 7.1 Notice Status Fields

| Field | Notices API | Checkout API | Match? |
|---|---|---|---|
| `tenancy_id` | ✅ | ✅ | Yes |
| `tenant_name` | ✅ | ✅ | Yes |
| `notice_date` | ✅ | ✅ | Yes |
| `expected_checkout` | ✅ (calculated) | ✅ (from DB) | Yes, different source but same value |
| `security_deposit` | ✅ | ✅ | Yes |
| `maintenance_fee` | ✅ | ✅ | Yes |
| `agreed_rent` | ✅ | ✅ | Yes |
| `pending_dues` | ❌ | ✅ | **MISMATCH** — notices doesn't return dues |

**Impact:** Notices page can't show "Pending dues will reduce refund". Checkout page correctly shows it.

**Risk:** Low, since checkout page fetches its own data. But could unify for performance.

---

### 7.2 Checkout Record Completeness

**What gets written on checkout:**
```python
CheckoutSession fields (checkout.py:128–148):
- token, status, created_by_phone, tenant_phone
- tenancy_id, checkout_date
- room_key_returned, wardrobe_key_returned, biometric_removed, room_condition_ok
- damage_notes, other_comments
- security_deposit, pending_dues, deductions, deduction_reason
- refund_amount, refund_mode
```

**What gets displayed in /checkouts:**
```typescript
CheckoutListItem fields (checkouts.page.tsx:166–202):
- tenancy_id, name, phone, room_number, checkout_date
- stay_type, security_deposit, refund_amount, agreed_rent
```

**Match:** ✅ Refund amount is written and read correctly. Data consistency good.

---

## 8. RULES REFERENCE

### From docs/REPORTING.md

| Rule | Implemented In | Code File | Correct? |
|---|---|---|---|
| Dues = rent_due + maintenance - paid (monthly) | Notices, Checkout, Tenants | src/api/v2/tenants.py, checkout.py | ✅ |
| First-month rent = prorated × days_remaining / days_in_month | Tenants (get_tenant_dues) | src/api/v2/tenants.py | ✅ (if recalc called) |
| Occupancy = occupied_beds / total_beds × 100 | Finance, Analytics | src/api/v2/analytics.py | ✅ |
| Premium = 1 tenant occupies max_occupancy beds | Finance, KPI | src/api/v2/kpi.py | ✅ |
| Maintenance fee is non-refundable | Checkout | web/app/checkout/new/page.tsx:530–531 | ✅ |
| Deposit refund = max(deposit - maintenance - dues - deductions, 0) | Checkout | web/app/checkout/new/page.tsx:140–144 | ✅ |
| No notice → deposit forfeited | Checkout | web/app/checkout/new/page.tsx:116 | ✅ |
| Notice by day 5 → refundable, vacate month-end | Notices, Checkout | src/api/v2/notices.py:66, checkout/new.tsx:118–125 | ⚠️ Partial (see 3.1) |
| Late notice (6+ days) → refundable, next month-end | Checkout page | web/app/checkout/new/page.tsx:468–484 | ✅ (frontend shows warning) |

---

## 9. RECOMMENDATIONS PRIORITY

### P0 (Do immediately)
1. Fix notices API `deposit_eligible` calculation (§3.1)
   - Effort: 1 hour
   - Risk: Low (data bug, no schema change)
   - Impact: Critical (shows wrong status to user)

2. Add recalc_checkin_month_rs to PATCH /tenants endpoint (§3.4)
   - Effort: 30 min
   - Risk: Low
   - Impact: Medium (first-month dues on PWA edits)

### P1 (Next session)
3. Add late-notice section to notices page (§3.2)
   - Effort: 30 min
   - Risk: Low (UI change)
   - Impact: Medium (UX improvement)

4. Create unit tests for deposit eligibility (§4.1–4.5)
   - Effort: 2 hours
   - Risk: None (adds coverage)
   - Impact: High (critical rules untested)

### P2 (Backlog)
5. Extract NOTICE_BY_DAY constant (§3.5)
   - Effort: 15 min
   - Risk: None
   - Impact: Low (maintainability)

---

## 10. CONCLUSION

**Overall assessment:** Financial pages are **mostly correct** with solid data flow, but **critical data bug** in notices API + missing test coverage for core rules.

**Health score:** 7/10
- ✅ Core checkout refund logic correct
- ✅ Notice date calculation correct
- ✅ Day-wise adjustment logic correct
- ❌ Deposit eligibility always True (breaks notices filtering)
- ❌ First-month recalc missing on PWA edits
- ❌ Zero test coverage for critical rules

**Next actions:**
1. Fix deposits_eligible in notices API (immediately)
2. Add recalc_checkin_month_rs to PATCH /tenants (immediately)
3. Write comprehensive test suite for financial rules (this sprint)
4. Add late-notice UI section (next sprint)
