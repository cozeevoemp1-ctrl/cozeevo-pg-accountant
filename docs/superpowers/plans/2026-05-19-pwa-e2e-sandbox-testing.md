# PWA End-to-End Sandbox Testing Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test every PWA flow end-to-end against live endpoints, validate data renders correctly, document all failures with logs — without touching real tenant data.

**Architecture:** Use Playwright MCP browser automation against `app.getkozzy.com`. Read-only flows test against live data directly. Write flows use a single test tenancy (phone `+919999000099`, name `TEST_AUTO`) created at the start and destroyed at the end. Results saved to `tests/e2e/results/YYYY-MM-DD.md`.

**Tech Stack:** Playwright MCP (`browser_*` tools), FastAPI REST API at `https://api.getkozzy.com`, Next.js PWA at `https://app.getkozzy.com`, Supabase auth JWT.

**Test account:** Kiran's admin account (`cozeevoemp1@gmail.com`) — admin role, sees all features.

**Test data sentinel:** All test-created records use phone `+919999000099` and name prefix `TEST_AUTO`. Grep for this before/after to verify cleanup.

**Failure format:** Every failure gets logged as:
```
[FAIL] <flow> — <what was expected> vs <what was seen>
API: <endpoint> → <status> <response snippet>
Screenshot: <filename>
```

---

## File Map

| File | Purpose |
|------|---------|
| `tests/e2e/results/2026-05-19.md` | Test run results (created during execution) |
| `tests/e2e/screenshots/` | Screenshots captured on failure |
| `scripts/_e2e_seed.py` | Creates test tenant + tenancy in DB |
| `scripts/_e2e_cleanup.py` | Deletes all `+919999000099` records |

---

## Task 1: Create Results File + Screenshot Dir

**Files:**
- Create: `tests/e2e/results/2026-05-19.md`
- Create: `tests/e2e/screenshots/` (directory)

- [ ] Create the results markdown file with this header:

```markdown
# PWA E2E Test Run — 2026-05-19

| Area | Flow | Status | Notes |
|------|------|--------|-------|
```

- [ ] Create screenshots directory:
```bash
mkdir -p tests/e2e/screenshots
```

---

## Task 2: Seed Test Data

**Files:**
- Create: `scripts/_e2e_seed.py`

- [ ] Write seed script:

```python
"""Seed one test tenant + tenancy for E2E write-flow tests. Idempotent."""
import asyncio, os, sys
from datetime import date
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import (
    Tenant, Tenancy, Room, RentSchedule,
    TenancyStatus, PaymentMode, StayType, RentStatus, SharingType,
)

TEST_PHONE = "+919999000099"
TEST_NAME = "TEST_AUTO E2E"
TEST_ROOM = "000"  # placeholder room already in DB

async def main():
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Find placeholder room 000
        room = await session.scalar(select(Room).where(Room.room_number == TEST_ROOM))
        if not room:
            print(f"ERROR: Room {TEST_ROOM} not found — cannot seed test data")
            return

        # Find or create test tenant
        tenant = await session.scalar(select(Tenant).where(Tenant.phone == TEST_PHONE))
        if tenant:
            print(f"Tenant already exists: id={tenant.id}")
        else:
            tenant = Tenant(name=TEST_NAME, phone=TEST_PHONE, gender="Male")
            session.add(tenant)
            await session.flush()
            print(f"Created tenant id={tenant.id}")

        # Find or create test tenancy
        tenancy = await session.scalar(
            select(Tenancy).where(
                Tenancy.tenant_id == tenant.id,
                Tenancy.status == TenancyStatus.active,
            )
        )
        if tenancy:
            print(f"Tenancy already exists: id={tenancy.id}")
        else:
            today = date.today()
            tenancy = Tenancy(
                tenant_id=tenant.id,
                room_id=room.id,
                stay_type=StayType.monthly,
                status=TenancyStatus.active,
                checkin_date=today,
                agreed_rent=Decimal("5000"),
                security_deposit=Decimal("5000"),
                booking_amount=Decimal("1000"),
                maintenance_fee=Decimal("500"),
                sharing_type=SharingType.triple,
                entered_by="e2e_test",
                org_id=1,
            )
            session.add(tenancy)
            await session.flush()
            # Seed rent schedule for current month
            period = today.replace(day=1)
            session.add(RentSchedule(
                tenancy_id=tenancy.id,
                period_month=period,
                rent_due=Decimal("5000"),
                maintenance_due=Decimal("0"),
                status=RentStatus.pending,
                due_date=period,
            ))
            await session.commit()
            print(f"Created tenancy id={tenancy.id}")

        print(f"\nSeed complete. Test tenancy_id={tenancy.id} tenant_id={tenant.id}")
        print("Use these IDs in write-flow tests.")

asyncio.run(main())
```

- [ ] Run seed:
```bash
venv/Scripts/python scripts/_e2e_seed.py
```
Expected output: `Seed complete. Test tenancy_id=XXXX tenant_id=YYYY`

- [ ] Note the tenancy_id and tenant_id — use them throughout write-flow tests below.

---

## Task 3: Auth Flows

**Test:** Login, logout, invalid credentials, session persistence.

- [ ] **3.1 — Login happy path**
  - Navigate to `https://app.getkozzy.com/login`
  - Fill email: `cozeevoemp1@gmail.com`, password from `.env` or ask Kiran
  - Click Sign In
  - Expected: redirects to `/` (home), KPI tiles visible
  - Log: `[PASS] Auth — Login happy path` or `[FAIL]` with screenshot

- [ ] **3.2 — Invalid credentials**
  - Navigate to `/login`
  - Fill email: `wrong@test.com`, password: `wrongpassword`
  - Click Sign In
  - Expected: error message shown, stays on `/login`
  - Log result

- [ ] **3.3 — Session persists after page reload**
  - While logged in, reload the page
  - Expected: still on home, not redirected to `/login`
  - Log result

- [ ] **3.4 — Logout**
  - Tap avatar button (top-right on home)
  - Expected: signs out, redirects to `/login`
  - Log result

- [ ] **3.5 — Unauthenticated redirect**
  - While logged out, navigate to `/tenants`
  - Expected: redirected to `/login`
  - Log result

---

## Task 4: Home Page — KPI Tiles

**Endpoints:** `GET /reporting/kpi`, `GET /reporting/collection`, `GET /activity/recent`, `GET /activity/recent-checkins`, `GET /reporting/kpi-detail`

- [ ] **4.1 — Page loads without error**
  - Log in, navigate to `/`
  - Expected: no error banners, tiles visible within 3s
  - Take screenshot

- [ ] **4.2 — Collection tile shows numbers**
  - Expected: "Collected ₹X of ₹Y" for current month, percentage shown
  - Capture network request to `/reporting/collection?period_month=2026-05`
  - Validate: `collected`, `expected`, `pct_collected` fields present and non-zero (May should have data)
  - Log result

- [ ] **4.3 — KPI tiles load (occupancy, dues, vacant, checkins)**
  - Expected: all 4 main KPI tiles show numbers (not "--" or 0 for all)
  - Capture `/reporting/kpi` response
  - Validate: `occupied_beds`, `total_beds`, `overdue_count`, `vacant_beds` all present
  - Log result

- [ ] **4.4 — KPI tile drill-down**
  - Tap the "Occupied" KPI tile
  - Expected: detail panel slides up showing list of tenants by room
  - Capture `/reporting/kpi-detail?type=occupied`
  - Validate: items array non-empty, each has `name`, `room`, `rent`
  - Log result

- [ ] **4.5 — Dues tile drill-down**
  - Tap "Dues" KPI tile
  - Expected: list of tenants with outstanding dues, amounts shown
  - Validate: items have `name`, `room`, `detail` (dues amount)
  - Log result

- [ ] **4.6 — Recent check-ins section**
  - Scroll down on home
  - Expected: recent check-ins list visible with name, room, amount paid, date
  - Capture `/activity/recent-checkins`
  - Validate: at least one entry (Pratham checked in today)
  - Log result

- [ ] **4.7 — Activity feed**
  - Expected: recent payment activity visible (Pratham's payments from today)
  - Capture `/activity/recent`
  - Validate: items array non-empty
  - Log result

- [ ] **4.8 — Month picker changes collection data**
  - Change month to April 2026 on home
  - Expected: collection numbers update (April should have historical data)
  - Capture `/reporting/collection?period_month=2026-04`
  - Validate: different values from May
  - Log result

---

## Task 5: Tenant Flows

**Endpoints:** `GET /tenants/search`, `GET /tenants/list`, `GET /tenants/{id}/dues`, `PATCH /tenants/{id}`

- [ ] **5.1 — Tenant list loads**
  - Navigate to `/tenants`
  - Expected: list of active tenants visible (hundreds of entries)
  - Capture `/tenants/list`
  - Validate: array length > 50, each item has `name`, `room_number`, `agreed_rent`
  - Log result

- [ ] **5.2 — Tenant search by name**
  - Search "Pratham"
  - Expected: Pratham S Kore in results, Room 420
  - Capture `/tenants/search?q=Pratham`
  - Validate: at least one result with `name` containing "Pratham"
  - Log result

- [ ] **5.3 — Tenant search by room number**
  - Search "420"
  - Expected: Pratham S Kore shown
  - Log result

- [ ] **5.4 — Dues page for test tenant**
  - Navigate to `/tenants/{test_tenancy_id}/edit` (use ID from seed step)
  - Expected: page loads with TEST_AUTO tenant details
  - Capture `/tenants/{test_tenancy_id}/dues`
  - Validate: `name`, `agreed_rent`, `rent_due`, `deposit_due` fields present
  - Log result

- [ ] **5.5 — Edit tenant notes (write flow)**
  - On TEST_AUTO tenant edit page
  - Change notes field to "E2E test note"
  - Save
  - Expected: PATCH `/tenants/{test_tenancy_id}` returns 200, notes updated
  - Reload page, confirm notes persisted
  - Log result

- [ ] **5.6 — Room check before transfer**
  - On TEST_AUTO edit page, type a room number (e.g. "420")
  - Expected: room check fires `GET /rooms/check?room=420`, shows occupancy
  - Validate response: `free_beds`, `max_occupancy`, `is_available` present
  - Log result

- [ ] **5.7 — Edge case: dues for first-month tenant**
  - Find a tenant who checked in this month (Pratham, checkin 2026-05-19)
  - View dues: `GET /tenants/{pratham_tenancy_id}/dues`
  - Expected: prorated rent shown, deposit_due accounts for booking_amount
  - Validate: `rent_due` < `agreed_rent` (prorated), `booking_amount` offset shown
  - Log result

- [ ] **5.8 — Edge case: dues for tenant on notice**
  - Find any tenant with `has_notice=true` from `/notices/active`
  - View their dues
  - Expected: notice date shown in edit page, deposit handling correct
  - Log result

---

## Task 6: Payment Flows

**Endpoints:** `POST /payments`, `GET /payments`, `PATCH /payments/{id}`, `DELETE /payments/{id}`

- [ ] **6.1 — Log new rent payment for test tenant**
  - Navigate to `/payment/new`
  - Search for "TEST_AUTO"
  - Set: amount=5000, method=Cash, type=Rent, period=2026-05
  - Submit
  - Expected: `POST /payments` returns 201 with `payment_id`
  - Note the payment_id for next tests
  - Log result

- [ ] **6.2 — Payment appears in history**
  - Navigate to `/payments/history`
  - Search for "TEST_AUTO"
  - Expected: the ₹5000 cash rent payment from 6.1 appears
  - Capture `GET /payments?tenancy_id={test_tenancy_id}`
  - Validate: at least one payment with `amount=5000`, `for_type=rent`
  - Log result

- [ ] **6.3 — Edit payment method**
  - Open the ₹5000 payment edit modal
  - Change method to UPI
  - Save
  - Expected: `PATCH /payments/{id}` returns 200, method shows as UPI in list
  - Log result

- [ ] **6.4 — Void/delete payment**
  - Open the same payment, tap Delete in header
  - Confirm
  - Expected: `DELETE /payments/{id}` returns 204, payment removed from list
  - Log result

- [ ] **6.5 — Log deposit payment**
  - New payment for TEST_AUTO: amount=5000, method=Cash, type=Deposit
  - Expected: succeeds, appears in history as "Deposit"
  - Log result

- [ ] **6.6 — Duplicate payment guard**
  - Attempt to log same rent payment twice: amount=5000, method=Cash, type=Rent, period=2026-05
  - Expected: second attempt returns 409 "Duplicate payment detected"
  - Log result

- [ ] **6.7 — Payment history all-tenants view**
  - `/payments/history` without selecting a tenant
  - Expected: last 30 payments across all tenants visible, Pratham's today payments at top
  - Log result

- [ ] **6.8 — Edge: zero amount rejected**
  - New payment: amount=0
  - Expected: validation error, not submitted
  - Log result

---

## Task 7: Onboarding + QR Flow

**Endpoints:** `POST /onboarding/create`, `GET /bookings/quick-book`, QR link `GET /onboard/{token}`

- [ ] **7.1 — Pre-register from PWA**
  - Navigate to `/tenants/pre-register`
  - Fill: name="TEST_AUTO QR", phone="+919999000098", room=empty (pre-register), rent=6000, checkin=2026-06-01
  - Submit
  - Expected: onboarding session created, confirmation shown
  - Note the token from response
  - Log result

- [ ] **7.2 — Booking appears in Bookings page**
  - Navigate to `/onboarding/bookings`
  - Expected: TEST_AUTO QR appears in pending list with room, rent, checkin date
  - Log result

- [ ] **7.3 — QR link is accessible**
  - Use token from 7.1, navigate to `https://api.getkozzy.com/onboard/{token}`
  - Expected: tenant onboarding form loads (HTML form, not 404)
  - Log result

- [ ] **7.4 — QR form fields visible**
  - On the QR form page
  - Expected: name pre-filled or editable, phone field, gender, DOB, ID proof fields visible
  - Log result

- [ ] **7.5 — Cancel no-show from Bookings page**
  - On `/onboarding/bookings`, find TEST_AUTO QR
  - Tap Cancel / No-show
  - Expected: `POST /tenancies/{id}/cancel-no-show` fires, session removed from bookings
  - Log result

- [ ] **7.6 — Approve + instant check-in via Bookings page**
  - Create another pre-register: name="TEST_AUTO CHECKIN", phone="+919999000097", room="000", rent=5000, checkin=today
  - On Bookings page, tap "Save & Check In"
  - Expected: tenancy activated, payment logged if booking_amount > 0
  - Log result

- [ ] **7.7 — Edge: duplicate phone blocked**
  - Attempt pre-register with phone `+919999000099` (already seeded)
  - Expected: error "phone already registered" or similar
  - Log result

- [ ] **7.8 — Edge: blacklisted phone blocked**
  - (Skip if no blacklisted phones in DB — document as N/A)
  - Expected: pre-register rejects with blacklist message
  - Log result

---

## Task 8: Physical Check-in Flow

**Endpoints:** `GET /tenants/{id}/checkin-preview`, `POST /checkin`

- [ ] **8.1 — Check-in preview for test tenant**
  - Navigate to `/checkin/new`
  - Search and select TEST_AUTO
  - Expected: preview shows prorated rent, deposit, total due, balance remaining
  - Capture `GET /tenants/{test_tenancy_id}/checkin-preview?actual_date=2026-05-19&prorate=true`
  - Validate: `prorated_rent`, `first_month_total`, `balance_remaining` present
  - Log result

- [ ] **8.2 — Prorate toggle changes amount**
  - Toggle prorate off
  - Expected: amount changes to full month rent (5000 vs prorated)
  - Validate: `prorated_rent` == `agreed_rent` when prorate=false
  - Log result

- [ ] **8.3 — Edge: check-in already done tenant**
  - Search for Pratham (already checked in physically today)
  - Expected: graceful handling (either disabled, or shows balance remaining)
  - Log result

---

## Task 9: Checkout Flow

**Endpoints:** `GET /checkout/tenant/{id}`, `POST /checkout/create`

- [ ] **9.1 — Checkout prefetch**
  - Navigate to `/checkout/new`
  - Search TEST_AUTO
  - Expected: `GET /checkout/tenant/{test_tenancy_id}` fires, shows deposit, maintenance, pending dues
  - Validate: `security_deposit`, `maintenance_fee`, `pending_rent_dues` present
  - Log result

- [ ] **9.2 — Checkout page renders refund calculation**
  - Expected: refund = deposit - pending dues - damage deductions shown
  - Log result

- [ ] **9.3 — Checkouts history page**
  - Navigate to `/checkouts`
  - Pick current month (2026-05)
  - Expected: any tenants checked out this month shown
  - Capture `GET /checkouts?month=2026-05`
  - Validate: array response (may be empty if no checkouts this month — mark as N/A not FAIL)
  - Log result

- [ ] **9.4 — Edge: checkout notice tenant vs no-notice tenant**
  - On checkout prefetch, find a tenant with notice (from notices page)
  - Expected: deposit shown as refundable (eligible since notice given)
  - Find a tenant without notice
  - Expected: deposit handling reflects no-notice policy
  - Log result

---

## Task 10: Notices Flow

**Endpoints:** `GET /notices/active`, `PATCH /tenants/{id}`

- [ ] **10.1 — Notices page loads**
  - Navigate to `/notices`
  - Expected: list of tenants on formal notice, each shows notice_date, expected checkout, deposit eligibility
  - Capture `GET /notices/active`
  - Validate: array of items with `tenant_name`, `notice_date`, `has_notice=true`, `deposit_eligible`
  - Log result

- [ ] **10.2 — Deposit eligible vs forfeited logic**
  - Find one tenant marked deposit eligible and one not (forfeited)
  - Expected: eligible = notice given any day; forfeited = zero notice given
  - Validate against `deposit_eligible` field in API response
  - Log result

- [ ] **10.3 — Set notice date on TEST_AUTO tenant**
  - Navigate to TEST_AUTO edit page
  - Set notice date to today (2026-05-19)
  - Save
  - Expected: PATCH fires, notice_date saved
  - Go to `/notices/active`, confirm TEST_AUTO appears
  - Log result

- [ ] **10.4 — Clear notice date**
  - On TEST_AUTO edit, clear notice date
  - Save
  - Expected: tenant no longer in `/notices/active`
  - Log result

---

## Task 11: Finance Flows (Admin read-only)

**Endpoints:** `GET /finance/pnl`, `GET /finance/cash`, `GET /analytics/occupancy`, `GET /finance/unit-economics`

- [ ] **11.1 — Finance page loads (admin only)**
  - Navigate to `/finance`
  - Expected: P&L tab visible (admin sees all tabs), not redirected
  - Log result

- [ ] **11.2 — P&L tab shows data**
  - Expected: income, opex, capex, net profit rows for current month
  - Capture `GET /finance/pnl?month=2026-05`
  - Validate: `income`, `opex_total`, `net_profit` fields present, income > 0 for April (verified month)
  - Switch to April 2026 and validate frozen figures load
  - Log result

- [ ] **11.3 — Cash tab**
  - Switch to Cash tab
  - Expected: collected amount, expenses, balance shown
  - Capture `GET /finance/cash?month=2026-05`
  - Validate: `collected`, `expenses`, `balance` present
  - Log result

- [ ] **11.4 — Occupancy tab charts render**
  - Switch to Occupancy tab
  - Expected: two Chart.js charts visible (type breakdown + occupancy %), data table below
  - Capture `GET /analytics/occupancy?months=12`
  - Validate: `months` array non-empty, each has `period_month`, `beds_occupied`, `occ_pct`
  - Log result

- [ ] **11.5 — Unit economics tile (admin)**
  - Expected: revenue/bed, EBITDA/bed, avg rent, collection rate tiles visible
  - Capture `GET /finance/unit-economics?month=2026-05`
  - Validate: `revenue_per_bed`, `ebitda_per_bed`, `collection_rate` present
  - Log result

- [ ] **11.6 — Edge: staff user blocked from /finance**
  - (Skip if no staff test account available — document as N/A)
  - Expected: staff role redirected away from `/finance`
  - Log result

---

## Task 12: Reminders Flow

**Endpoints:** `GET /reminders/overdue`, `POST /reminders/send`

- [ ] **12.1 — Overdue list loads**
  - Navigate to `/reminders`
  - Expected: list of tenants with outstanding dues and last reminder date
  - Capture `GET /reminders/overdue`
  - Validate: array, each item has `name`, `room`, `dues`, `tenancy_id`
  - Log result

- [ ] **12.2 — Send reminder does NOT fire (dry-run check)**
  - Do NOT tap "Send All" — this would send real WhatsApp messages
  - Instead, verify the send button is present and labelled clearly
  - Document: write flows for reminders are skipped to avoid messaging real tenants
  - Log as `[SKIP] Reminders — send flow skipped (would message real tenants)`

---

## Task 13: Collection Breakdown + History

**Endpoints:** `GET /reporting/collection`, `GET /reporting/collection-history`, `GET /reporting/deposits-held`

- [ ] **13.1 — Collection breakdown page**
  - Navigate to `/collection/breakdown`
  - Expected: expected vs collected for current month, method split (cash/UPI), pending list
  - Capture `/reporting/collection?period_month=2026-05`
  - Validate: `expected`, `collected`, `pending`, `cash_amount`, `upi_amount` present
  - Log result

- [ ] **13.2 — Deposits held**
  - Expected: security deposits held tile shows aggregate amount
  - Capture `GET /reporting/deposits-held`
  - Validate: `total_refundable`, `total_maintenance` present, values > 0
  - Log result

- [ ] **13.3 — Collection history (6 months)**
  - Navigate to `/collection/history`
  - Expected: 6-month bar/line chart with historical collection data
  - Capture `GET /reporting/collection-history?months=6`
  - Validate: array of 6 entries, each has `period_month`, `collected`, `expected`
  - Log result

---

## Task 14: Activity Feed

**Endpoints:** `GET /activity/feed`

- [ ] **14.1 — Activity feed loads**
  - Navigate to `/activity`
  - Expected: chronological list of all recent events (payments, check-ins, checkouts, rent changes, notices)
  - Capture `GET /activity/feed?limit=120`
  - Validate: array non-empty, items have `event_type`, `tenant_name`, `room`, `amount_or_detail`, `created_at`
  - Log result

- [ ] **14.2 — Pratham's events appear**
  - Expected: Pratham S Kore's check-in (today) + 3 payments visible in feed
  - Scroll/search for Pratham events
  - Log result

- [ ] **14.3 — Edge: activity feed includes booking/advance type**
  - Expected: Pratham's ₹2000 advance shows as type `booking` or `advance`
  - Validate `for_type` field in response
  - Log result

---

## Task 15: Cleanup Test Data

**Files:**
- Create: `scripts/_e2e_cleanup.py`

- [ ] Write cleanup script:

```python
"""Remove all E2E test data. Idempotent."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Tenant, Tenancy, Payment, RentSchedule, OnboardingSession

TEST_PHONES = ["+919999000099", "+919999000098", "+919999000097"]

async def main():
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        for phone in TEST_PHONES:
            tenant = await session.scalar(select(Tenant).where(Tenant.phone == phone))
            if not tenant:
                print(f"No tenant found for {phone} — skip")
                continue

            # Get all tenancies
            tenancies = (await session.execute(
                select(Tenancy).where(Tenancy.tenant_id == tenant.id)
            )).scalars().all()

            for tn in tenancies:
                # Delete payments
                await session.execute(delete(Payment).where(Payment.tenancy_id == tn.id))
                # Delete rent schedules
                await session.execute(delete(RentSchedule).where(RentSchedule.tenancy_id == tn.id))
                print(f"  Deleted payments+schedules for tenancy {tn.id}")

            # Delete tenancies
            await session.execute(delete(Tenancy).where(Tenancy.tenant_id == tenant.id))
            # Delete onboarding sessions
            await session.execute(delete(OnboardingSession).where(OnboardingSession.tenant_phone == phone))
            # Delete tenant
            await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
            print(f"Deleted tenant {phone} ({tenant.name})")

        await session.commit()
        print("Cleanup complete.")

asyncio.run(main())
```

- [ ] Run cleanup:
```bash
venv/Scripts/python scripts/_e2e_cleanup.py
```
Expected: all TEST_AUTO records removed.

- [ ] Verify no test data remains:
```bash
venv/Scripts/python -c "
import asyncio, os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Tenant

async def check():
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+asyncpg://', 1)
    engine = create_async_engine(url)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        t = await s.scalar(select(Tenant).where(Tenant.phone.in_(['+919999000099', '+919999000098', '+919999000097'])))
        print('CLEAN' if not t else f'STILL EXISTS: {t.phone}')
asyncio.run(check())
"
```
Expected: `CLEAN`

---

## Task 16: Compile Results Report

- [ ] Review `tests/e2e/results/2026-05-19.md`
- [ ] Count: PASS / FAIL / SKIP / N/A
- [ ] For each FAIL: paste the API response body and screenshot filename
- [ ] Add a summary section:

```markdown
## Summary

| Status | Count |
|--------|-------|
| PASS   | X     |
| FAIL   | X     |
| SKIP   | X     |
| N/A    | X     |

## Failures

### [FAIL] <flow name>
**Expected:** ...
**Got:** ...
**API:** `GET /endpoint` → `{...response...}`
**Screenshot:** `tests/e2e/screenshots/<file>.png`
**Likely cause:** ...
```

- [ ] Commit results:
```bash
git add tests/e2e/
git commit -m "test(e2e): PWA sandbox test run 2026-05-19"
```

---

## Edge Cases Across All Flows

These must be checked regardless of which task they appear in:

| Edge Case | Where to Test | Expected |
|-----------|---------------|----------|
| First-month tenant prorated dues | Task 5.7, 8.1 | rent_due < agreed_rent |
| Tenant with booking_amount offset | Task 5.7 | deposit_due reduced by booking_amount |
| Day-wise tenant in payment history | Task 6, any | stay_type=daily handled |
| Zero dues tenant in collection | Task 4.5 | not counted as overdue |
| Room 000 placeholder in search | Task 5.2 | doesn't appear in active tenant list |
| Admin sees Finance tab, staff doesn't | Task 11.6 | role-gated correctly |
| Notice → deposit eligible | Task 10.2 | deposit_eligible=true if notice given |
| Late notice (after 5th) | Task 10 | next month cycle, full month rent |
| Void payment → dues increase | Task 6.4 + 5.4 | after void, dues go up by voided amount |
| Month picker (April frozen data) | Task 4.8, 11.2 | frozen figures for Nov'25–Apr'26 |
