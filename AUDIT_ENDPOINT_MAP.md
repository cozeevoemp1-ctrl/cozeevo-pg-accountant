# End-to-End Endpoint Audit — Pages → API → DB

**Date:** 2026-06-08  
**Goal:** Map every PWA page to endpoints it calls, verify no duplicate creation, no unconnected operations

---

## CRITICAL OPERATIONS (High Risk)

### 1. PAYMENTS — Create + View + Edit

#### Pages:
- `/payment/new` → Create payment for tenant
- `/payments/history` → List all payments for tenant/tenancy
- `/tenants` → Quick collect (inline payment create)

#### Endpoints:
| Endpoint | Method | Called By | Purpose | Issues to Check |
|----------|--------|-----------|---------|-----------------|
| `POST /api/v2/app/payments` | POST | payment/new | Log single payment | Dedup? Field mapping? |
| `GET /api/v2/app/payments?tenancy_id=X` | GET | payments/history | List payments for tenancy | **KNOWN BUG:** Multi-table JOIN duplicates (tenant_id path) |
| `GET /api/v2/app/payments?tenant_id=X` | GET | payments/history | List payments across all tenancies | **KNOWN BUG:** Dedup by tenancy_id added, but verify |
| `PATCH /api/v2/app/payments/{id}` | PATCH | payments/history (edit modal) | Edit payment amount/method/type/notes | Audit logged? Field validation? |
| `POST /api/v2/app/reminders/send` | POST | reminders page | Send payment reminder | Role check added |

#### Data Flow Check:
- [ ] Create payment → stored in DB → appears in list
- [ ] List deduplicates properly across tenant/tenancy paths
- [ ] Payment edit updates DB → reflected in next list call
- [ ] Payment void (is_void=True) hides from collection
- [ ] No double payment creation (idempotency)

---

### 2. TENANTS — Create + Edit + View

#### Pages:
- `/tenants` → List all tenants, search, view dues
- `/tenants/[tenancy_id]/edit` → Edit personal/financial fields
- `/tenants/pre-register` → Pre-register future tenant (NOW REQUIRES ROOM)
- `/onboarding/bookings` → Quick-book into room

#### Endpoints:
| Endpoint | Method | Called By | Purpose | Issues to Check |
|----------|--------|-----------|---------|-----------------|
| `GET /api/v2/app/tenants/list` | GET | tenants page | List active/no_show tenants with dues | Dedup? Field names? |
| `GET /api/v2/app/tenants/search?q=X` | GET | tenants page (search) | Search tenants by name/phone/room | **KNOWN BUG:** Multi-table JOIN duplicates (dedup by tenancy_id added) |
| `GET /api/v2/app/tenants/{tenancy_id}/dues` | GET | payment/new, edit page | Get current month dues | Deposit double-count fixed? |
| `PATCH /api/v2/app/tenants/{tenancy_id}` | PATCH | tenants/edit page | Edit name, phone, rent, deposit, notice, etc. | **NEW:** Audit logging added for 11 fields |
| `POST /api/v2/app/tenants/{tenancy_id}/adjustment` | POST | edit page (rent waive) | Add rent adjustment/surcharge | **NEW:** Role check added |
| `POST /api/v2/app/tenants/{tenancy_id}/transfer-room` | POST | edit page | Move tenant to different room | Room occupancy check? |
| `POST /api/v2/app/tenancies/{tenancy_id}/cancel-no-show` | POST | bookings page | Cancel pending no-show booking | **NEW:** Role check added |
| `POST /api/v2/app/bookings/quick-book` | POST | bookings page, pre-register | Create quick booking (with optional payment) | **NEW:** Rejects room 000 |

#### Data Flow Check:
- [ ] Edit tenant name → audit logged → appears in list search
- [ ] Edit agreed_rent → rent_revision created → audit logged
- [ ] Edit security_deposit → recalc first-month RS → audit logged
- [ ] Edit notice_date → expected_checkout set → audit logged
- [ ] Cancel no-show → voids pending RS rows → syncs to cancelled status
- [ ] Quick-book with payment → both tenancy + payment created
- [ ] No double booking (overlapping dates rejected)
- [ ] Room 000 pre-booking rejected ✓

---

### 3. CHECKOUTS — Create + View

#### Pages:
- `/checkout/new` → Record physical checkout
- `/checkouts` → List all checkouts by month

#### Endpoints:
| Endpoint | Method | Called By | Purpose | Issues to Check |
|----------|--------|-----------|---------|-----------------|
| `GET /api/v2/app/checkout/tenant/{tenancy_id}` | GET | checkout/new (prefetch) | Pre-fill checkout form (current dues, deposit, etc.) | Data accurate? |
| `POST /api/v2/app/checkout/create` | POST | checkout/new (submit) | Record checkout, calculate refund | Audit logged? Notice logic? |
| `GET /api/v2/app/checkouts?month=X` | GET | checkouts page | List all checkouts for month | Field mapping correct? |

#### Data Flow Check:
- [ ] Checkout create → CheckoutRecord stored → CheckoutLog audit entries
- [ ] Checkout refund calculation: deposit - maintenance - dues - deductions
- [ ] Notice logic: no notice → forfeit deposit, late notice → rent owed
- [ ] Checkout updates tenancy.checkout_date + status
- [ ] Tenancy shows in "exited" status after checkout

---

### 4. NOTICES — View + Edit

#### Pages:
- `/notices` → List tenants with exit notices
- `/tenants/[tenancy_id]/edit` → Set/clear notice

#### Endpoints:
| Endpoint | Method | Called By | Purpose | Issues to Check |
|----------|--------|-----------|---------|-----------------|
| `GET /api/v2/app/notices/active` | GET | notices page | List active tenants with notice or lock-in | **FIXED:** deposits_eligible now checks notice_date |
| `PATCH /api/v2/app/tenants/{tenancy_id}` | PATCH | edit page "Remove notice" | Clear notice_date → expected_checkout | Audit logged? |

#### Data Flow Check:
- [ ] Set notice → expected_checkout calculated
- [ ] Clear notice → expected_checkout cleared
- [ ] deposits_eligible correctly reflects notice status
- [ ] Late notice (after 5th) calculated correctly

---

### 5. BOOKINGS / ONBOARDING — Create + View + Approve

#### Pages:
- `/onboarding/bookings` → View pending sessions, approve check-in
- `/tenants/pre-register` → Create future tenant pre-booking (NOW REQUIRES ROOM)

#### Endpoints:
| Endpoint | Method | Called By | Purpose | Issues to Check |
|----------|--------|-----------|---------|-----------------|
| `POST /api/v2/app/bookings/quick-book` | POST | bookings, pre-register | Create onboarding session + optional tenancy | **FIXED:** Rejects room 000 |
| `GET /api/onboarding/pending` | GET | bookings page | List pending onboarding sessions | All sessions shown? |
| `POST /api/onboarding/{token}/approve` | POST | bookings "Save & Check In" | Approve session, activate tenancy, create payment | Room check? Payment dedup? RS creation? |
| `POST /api/onboarding/{token}/cancel` | POST | bookings page (2-tap) | Cancel pending session | Syncs to cancelled? |
| `PATCH /api/onboarding/admin/{token}` | PATCH | bookings edit panel | Edit session before approval | Field validation? Room check? |

#### Data Flow Check:
- [ ] Quick-book → OnboardingSession created (pending_tenant)
- [ ] Tenant fills form → pending_review
- [ ] Approve → Tenancy created (no_show or active based on checkin_date)
- [ ] Check-in date in past → active immediately
- [ ] Check-in date future → no_show until manual check-in
- [ ] Payment created at approval if booking_amount > 0
- [ ] Cancel → onboarding_session.status = cancelled
- [ ] No double-booking (phone dedup, occupancy check)
- [ ] Room 000 rejected ✓

---

## DATA CONSISTENCY RULES

### Rule: No Duplicate Rows
- **Multi-table JOINs:** Must dedup by primary key (tenancy_id, payment_id, etc.)
- **Endpoints affected:** 
  - `search_tenants` → **FIXED:** dedup by tenancy_id ✓
  - `list_payments` (tenant_id path) → **FIXED:** dedup by payment_id ✓
  - `list_tenants` → Check for dedup
  - `getActiveNotices` → Check for dedup

### Rule: Field Name Consistency
- **Payment fields:** payment_id, amount, payment_mode, for_type, period_month
- **Tenant fields:** tenant_id, name, phone, email, room_number, agreed_rent, security_deposit
- **Tenancy fields:** tenancy_id, status, checkin_date, checkout_date, notice_date, expected_checkout
- **Audit:** Check all endpoints return same field names

### Rule: Business Logic Alignment
- **Deposit calculation:** identical across `/dues`, `/checkout/prefetch`, `/checkout/create`
- **Notice logic:** identical across `/notices`, `/checkout/new`, `/edit`
- **Occupancy check:** identical across `/quick-book`, `/rooms/check`, `/bookings/pre-book`

---

## AUDIT CHECKLIST

### Phase 1: Map Endpoints (In Progress)
- [x] Extract all endpoints
- [x] Extract all pages
- [ ] Link pages → endpoints
- [ ] Identify data flow for each endpoint

### Phase 2: Check Data Flows
- [ ] Create operations: verify no double-creation
- [ ] Read operations: verify no duplicate rows
- [ ] Update operations: verify audit logging
- [ ] Delete operations: verify cascading + audit logging

### Phase 3: Verify DB Consistency
- [ ] Foreign key relationships intact
- [ ] No orphaned records
- [ ] Deduplication logic correct
- [ ] Audit log entries complete

### Phase 4: Business Logic Alignment
- [ ] Deposit calculation consistent across 3+ code paths
- [ ] Notice logic consistent across 3+ code paths
- [ ] Occupancy check consistent across 3+ code paths
- [ ] Payment dedup consistent across 3+ code paths

---

## KNOWN BUGS FIXED (Session B + Just Now)

✅ search_tenants: Multi-table JOIN dedup (commit b4cc097)  
✅ list_payments (tenant_id): Broken field names + dedup (commit 016e841)  
✅ quick_book: Rejects room 000 now  
✅ pre_register: Requires room (no 000 fallback)  
✅ PATCH /tenants/{id}: Role check + audit logging added  
✅ deposits_eligible: Fixed to check notice_date  

---

## NEXT STEPS

1. **Verify all endpoints for dedup logic** (multi-table JOINs)
2. **Check field name consistency** across similar endpoints
3. **Trace full data flows** for critical operations (payment, tenant, checkout)
4. **Verify audit logging** on all write operations
5. **Test for orphaned records** (e.g., payment with no tenancy)
