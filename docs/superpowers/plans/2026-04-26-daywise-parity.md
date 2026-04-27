# Day-Wise Stay Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge `DaywiseStay` records into `Tenant + Tenancy(stay_type=daily)` so all bot handlers, sheet columns, and payment flows treat day-wise guests identically to monthly tenants.

**Architecture:** Historical `DaywiseStay` rows are migrated once via script; all new day-wise records created through onboarding write to `Tenancy`; 11 occupancy callsites switch from `DaywiseStay` to `Tenancy WHERE stay_type=daily`; DAY WISE sheet tab switches to `MONTHLY_HEADERS`; `gsheets.update_payment()` routes daily-stay payments to the DAY WISE tab.

**Tech Stack:** SQLAlchemy async, gspread, FastAPI, pytest. All scripts use existing DB/sheet credentials from `.env`.

---

## File Map

| File | Action | What changes |
|---|---|---|
| `scripts/migrate_daywise_to_tenancy.py` | **Create** | One-time migration: DaywiseStay → Tenant + Tenancy + Payment |
| `tests/database/test_daywise_migration.py` | **Create** | Unit tests for migration logic |
| `src/api/onboarding_router.py` | **Modify** | `is_daily` approval path writes Tenancy instead of DaywiseStay |
| `scripts/import_daywise.py` | **Modify** | Excel import writes Tenancy instead of DaywiseStay |
| `src/integrations/gsheets.py` | **Modify** | `add_daywise_stay()` → MONTHLY_HEADERS format; `update_payment()` → routes daily to DAY WISE tab |
| `src/services/room_occupancy.py` | **Modify** | All DaywiseStay occupancy queries → Tenancy(stay_type=daily) |
| `src/services/occupants.py` | **Modify** | DaywiseStay reference in `get_occupants()` → Tenancy |
| `src/whatsapp/handlers/_shared.py` | **Modify** | Remove `_find_active_daywise_by_name`; `_find_active_tenants_by_name` already covers daily |
| `src/whatsapp/handlers/owner_handler.py` | **Modify** | Remove DAYWISE_RENT_CHANGE handlers; remove ROOM_TRANSFER_DW_* handlers + helper fns |
| `src/whatsapp/handlers/account_handler.py` | **Modify** | `_query_dues`: include daily tenants (no RentSchedule) |
| `scripts/sync_daywise_from_db.py` | **Rewrite** | Query `Tenancy WHERE stay_type=daily`, output MONTHLY_HEADERS |
| `src/database/migrate_all.py` | **Append** | No schema changes needed (`stay_type` enum + all Tenancy columns already exist) |

---

## Task 1 — Migration Script

**Files:**
- Create: `scripts/migrate_daywise_to_tenancy.py`
- Create: `tests/database/test_daywise_migration.py`

- [ ] **Step 1.1: Write failing unit tests**

Create `tests/database/test_daywise_migration.py`:

```python
"""Unit tests for DaywiseStay → Tenancy migration logic."""
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal


def _make_daywise(phone="9876543210", name="Test Guest", checkin=date(2026,4,1),
                   checkout=date(2026,4,3), daily_rate=500, total_amount=1000,
                   booking_amount=500, maintenance=0, room="101",
                   status="EXIT", source_file=None):
    dw = MagicMock()
    dw.phone = phone
    dw.guest_name = name
    dw.checkin_date = checkin
    dw.checkout_date = checkout
    dw.num_days = (checkout - checkin).days
    dw.daily_rate = Decimal(str(daily_rate))
    dw.total_amount = Decimal(str(total_amount))
    dw.booking_amount = Decimal(str(booking_amount))
    dw.maintenance = Decimal(str(maintenance))
    dw.room_number = room
    dw.status = status
    dw.comments = ""
    dw.payment_date = checkin
    dw.source_file = source_file
    return dw


@pytest.mark.asyncio
async def test_skip_no_phone():
    from scripts.migrate_daywise_to_tenancy import migrate_row
    dw = _make_daywise(phone=None)
    session = AsyncMock()
    result = await migrate_row(dw, session, dry_run=True)
    assert result == "skip_no_phone"


@pytest.mark.asyncio
async def test_skip_already_migrated():
    from scripts.migrate_daywise_to_tenancy import migrate_row
    dw = _make_daywise(source_file="MIGRATED")
    session = AsyncMock()
    result = await migrate_row(dw, session, dry_run=True)
    assert result == "skip_already"


@pytest.mark.asyncio
async def test_creates_tenancy_for_new_guest():
    from scripts.migrate_daywise_to_tenancy import _build_tenancy_data
    dw = _make_daywise()
    data = _build_tenancy_data(dw, tenant_id=42, room_id=7)
    assert data["stay_type"] == "daily"
    assert data["agreed_rent"] == Decimal("500")   # daily_rate
    assert data["booking_amount"] == Decimal("500")
    assert data["checkin_date"] == date(2026, 4, 1)
    assert data["checkout_date"] == date(2026, 4, 3)
    assert data["tenant_id"] == 42
    assert data["room_id"] == 7


@pytest.mark.asyncio
async def test_payment_created_when_total_positive():
    from scripts.migrate_daywise_to_tenancy import _build_payment_data
    dw = _make_daywise(total_amount=1000)
    data = _build_payment_data(dw, tenancy_id=99)
    assert data is not None
    assert data["amount"] == Decimal("1000")
    assert data["tenancy_id"] == 99


@pytest.mark.asyncio
async def test_no_payment_when_total_zero():
    from scripts.migrate_daywise_to_tenancy import _build_payment_data
    dw = _make_daywise(total_amount=0)
    data = _build_payment_data(dw, tenancy_id=99)
    assert data is None
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd "c:\Users\kiran\Desktop\AI Watsapp PG Accountant"
venv/Scripts/python -m pytest tests/database/test_daywise_migration.py -v
```
Expected: `ModuleNotFoundError` — `scripts.migrate_daywise_to_tenancy` doesn't exist yet.

- [ ] **Step 1.3: Create the migration script**

Create `scripts/migrate_daywise_to_tenancy.py`:

```python
"""
scripts/migrate_daywise_to_tenancy.py
======================================
One-time migration: DaywiseStay → Tenant + Tenancy(stay_type=daily) + Payment.

Usage:
  python scripts/migrate_daywise_to_tenancy.py           # dry run — shows what would change
  python scripts/migrate_daywise_to_tenancy.py --write   # apply to DB

Idempotent: rows with source_file='MIGRATED' are skipped. Safe to re-run.
Rows with no phone are skipped and logged to migration_skipped.txt.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    DaywiseStay, Tenant, Tenancy, TenancyStatus, StayType,
    Payment, PaymentMode, PaymentFor, Room,
)

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


def _build_tenancy_data(dw: DaywiseStay, tenant_id: int, room_id: int | None) -> dict:
    """Pure function — builds Tenancy kwargs from a DaywiseStay row. Testable."""
    status = TenancyStatus.active if str(dw.status or "").upper() in ("ACTIVE", "CHECKIN") else TenancyStatus.exited
    return {
        "tenant_id": tenant_id,
        "room_id": room_id,
        "stay_type": StayType.daily,
        "status": status,
        "checkin_date": dw.checkin_date,
        "checkout_date": dw.checkout_date,
        "expected_checkout": dw.checkout_date,
        "agreed_rent": dw.daily_rate or Decimal("0"),      # per-day rate
        "booking_amount": dw.booking_amount or Decimal("0"),
        "maintenance_fee": dw.maintenance or Decimal("0"),
        "notes": dw.comments or "",
        "entered_by": "excel_import",
    }


def _build_payment_data(dw: DaywiseStay, tenancy_id: int) -> dict | None:
    """Returns Payment kwargs or None if nothing to record."""
    total = float(dw.total_amount or 0)
    if total <= 0:
        return None
    return {
        "tenancy_id": tenancy_id,
        "amount": dw.total_amount,
        "mode": PaymentMode.cash,   # Excel imports don't track mode — default cash
        "payment_date": dw.payment_date or dw.checkin_date,
        "payment_for": PaymentFor.rent,
        "entered_by": "excel_import",
    }


async def migrate_row(dw: DaywiseStay, session: AsyncSession, dry_run: bool = False) -> str:
    """Migrate one DaywiseStay row. Returns outcome string."""
    if not dw.phone:
        return "skip_no_phone"
    if dw.source_file == "MIGRATED":
        return "skip_already"

    # Find or reuse existing Tenant by phone
    tenant = await session.scalar(select(Tenant).where(Tenant.phone == dw.phone))
    if not tenant:
        if dry_run:
            return "would_create_tenant"
        tenant = Tenant(name=dw.guest_name, phone=dw.phone)
        session.add(tenant)
        await session.flush()

    tenant_id = tenant.id if tenant else 0

    # Find room by room_number
    room = await session.scalar(select(Room).where(Room.room_number == dw.room_number))
    room_id = room.id if room else None

    # Skip if Tenancy for this stay already exists (idempotent)
    existing = await session.scalar(
        select(Tenancy).where(
            Tenancy.tenant_id == tenant_id,
            Tenancy.checkin_date == dw.checkin_date,
            Tenancy.stay_type == StayType.daily,
        )
    )
    if existing:
        if not dry_run:
            dw.source_file = "MIGRATED"
        return "skip_duplicate"

    if dry_run:
        return "would_migrate"

    # Create Tenancy
    tenancy_data = _build_tenancy_data(dw, tenant_id, room_id)
    tenancy = Tenancy(**tenancy_data)
    session.add(tenancy)
    await session.flush()

    # Create Payment if amount > 0
    pay_data = _build_payment_data(dw, tenancy.id)
    if pay_data:
        session.add(Payment(**pay_data))

    # Mark as migrated
    dw.source_file = "MIGRATED"
    return "migrated"


async def main(write: bool) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    skipped_no_phone = []

    async with Session() as session:
        rows = (await session.execute(
            select(DaywiseStay).order_by(DaywiseStay.checkin_date)
        )).scalars().all()

        print(f"Total DaywiseStay rows: {len(rows)}")
        counts = {"migrated": 0, "skip_no_phone": 0, "skip_already": 0,
                  "skip_duplicate": 0, "would_migrate": 0, "would_create_tenant": 0}

        for dw in rows:
            result = await migrate_row(dw, session, dry_run=not write)
            counts[result] = counts.get(result, 0) + 1
            if result == "skip_no_phone":
                skipped_no_phone.append(f"{dw.guest_name} | room {dw.room_number} | {dw.checkin_date}")
            if write and result == "migrated":
                await session.commit()
                await session.begin()

        if not write:
            print("\n[DRY RUN] No changes written.")

    print("\nResults:")
    for k, v in counts.items():
        if v:
            print(f"  {k}: {v}")

    if skipped_no_phone:
        Path("migration_skipped.txt").write_text("\n".join(skipped_no_phone), encoding="utf-8")
        print(f"\nSkipped (no phone) logged to migration_skipped.txt: {len(skipped_no_phone)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(write=args.write))
```

- [ ] **Step 1.4: Run tests — expect pass**

```bash
venv/Scripts/python -m pytest tests/database/test_daywise_migration.py -v
```
Expected: 5 tests pass.

- [ ] **Step 1.5: Dry-run against live DB**

```bash
venv/Scripts/python scripts/migrate_daywise_to_tenancy.py
```
Expected: Shows counts of "would_migrate" and "skip_no_phone". No DB writes.

- [ ] **Step 1.6: Commit**

```bash
git add scripts/migrate_daywise_to_tenancy.py tests/database/test_daywise_migration.py
git commit -m "feat: migration script DaywiseStay → Tenancy(stay_type=daily)"
```

---

## Task 2 — Update Onboarding Write Path

**Files:**
- Modify: `src/api/onboarding_router.py` lines ~1189–1241

The `is_daily` approval path currently creates a `DaywiseStay` object. Replace it with `Tenancy(stay_type=daily)` + optional `Payment`.

- [ ] **Step 2.1: Locate exact block to replace**

In `src/api/onboarding_router.py`, find the block starting at `if is_daily:` (around line 1189). It ends just before `else:` (the monthly path, ~line 1242). The `tenant` variable is already in scope (created by the common approval code above this block).

- [ ] **Step 2.2: Replace the is_daily block**

Replace from `if is_daily:` through the closing `else:` comment with:

```python
        if is_daily:
            # ── Daily stay path — writes Tenancy(stay_type=daily) ─────────────
            from src.database.models import StayType, TenancyStatus, Payment, PaymentMode, PaymentFor
            checkout = obs.checkout_date or (checkin + timedelta(days=obs.num_days or 1))
            num_days = obs.num_days or max(1, (checkout - checkin).days)

            tenancy = Tenancy(
                tenant_id=tenant.id,
                room_id=room.id if room else None,
                stay_type=StayType.daily,
                status=TenancyStatus.active,
                checkin_date=checkin,
                checkout_date=checkout,
                expected_checkout=checkout,
                agreed_rent=obs.daily_rate or 0,        # per-day rate
                booking_amount=obs.booking_amount or 0,
                maintenance_fee=obs.maintenance_fee or 0,
                notes=obs.special_terms or "",
                entered_by="onboarding_form",
            )
            session.add(tenancy)
            await session.flush()

            total_paid = float(obs.agreed_rent or 0)
            if total_paid > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=obs.agreed_rent,
                    mode=PaymentMode.cash,
                    payment_date=checkin,
                    payment_for=PaymentFor.rent,
                    entered_by="onboarding_form",
                ))

            obs.status = "approved"
            obs.approved_at = datetime.utcnow()
            obs.approved_by_phone = (req.approved_by_phone or "").strip() if req else ""
            obs.tenant_id = tenant.id
            obs.tenancy_id = tenancy.id

            # GSheets DAY WISE tab — write using MONTHLY_HEADERS format
            for attempt in range(3):
                try:
                    from src.integrations.gsheets import add_daywise_stay as gsheets_dw
                    gs_r = await gsheets_dw(
                        room_number=room.room_number if room else "TBD",
                        tenant_name=td["name"],
                        phone=phone_sheet,
                        building=room.building if room else "",
                        sharing=sharing,
                        daily_rate=float(obs.daily_rate or 0),
                        num_days=num_days,
                        booking_amount=float(obs.booking_amount or 0),
                        total_paid=total_paid,
                        maintenance=float(obs.maintenance_fee or 0),
                        checkin=checkin.strftime("%d/%m/%Y"),
                        checkout=checkout.strftime("%d/%m/%Y"),
                        status="ACTIVE",
                        notes=obs.special_terms or "",
                        entered_by="onboarding_form",
                    )
                    if gs_r.get("success"):
                        gsheets_note = " | DAY WISE Sheet updated"
                        break
                except Exception as e:
                    _logger.warning("GSheets DAY WISE attempt %d error: %s", attempt + 1, e)
                if attempt < 2:
                    await _aio.sleep(2 * (attempt + 1))
```

Note: Remove the `DaywiseStay` import inside this block if it exists. The `Tenancy` model is already imported at the top of `onboarding_router.py`.

- [ ] **Step 2.3: Verify server starts without error**

```bash
venv/Scripts/python main.py
```
Expected: No import errors. `Ctrl+C` to stop.

- [ ] **Step 2.4: Commit**

```bash
git add src/api/onboarding_router.py
git commit -m "feat(onboarding): daily stay writes Tenancy(stay_type=daily) not DaywiseStay"
```

---

## Task 3 — Update import_daywise.py (Excel Import)

**Files:**
- Modify: `scripts/import_daywise.py`

Currently writes `DaywiseStay` directly. Replace with `Tenant + Tenancy(stay_type=daily) + Payment`.

- [ ] **Step 3.1: Find the DaywiseStay write block in import_daywise.py**

```bash
grep -n "DaywiseStay\|session.add\|session.merge" scripts/import_daywise.py | head -20
```

Note the line range of the block that creates/upserts DaywiseStay objects.

- [ ] **Step 3.2: Replace DaywiseStay upsert with Tenancy upsert**

Find the row-building loop (it iterates parsed Excel rows and calls `session.add(DaywiseStay(...))`). Replace with:

```python
from src.database.models import (
    Tenant, Tenancy, StayType, TenancyStatus, Payment, PaymentMode, PaymentFor, Room
)
from sqlalchemy import select

# Inside the row loop — after parsing name, phone, checkin_date, checkout_date,
# daily_rate, total_amount, booking_amount, maintenance, room_number, status:

# Skip if no phone
if not phone:
    print(f"  SKIP (no phone): {name}")
    continue

# Find or create Tenant
tenant = await session.scalar(select(Tenant).where(Tenant.phone == phone))
if not tenant:
    tenant = Tenant(name=name, phone=phone)
    session.add(tenant)
    await session.flush()

# Find room
room_obj = await session.scalar(select(Room).where(Room.room_number == room_number))

# Skip duplicate (same tenant + checkin)
existing = await session.scalar(
    select(Tenancy).where(
        Tenancy.tenant_id == tenant.id,
        Tenancy.checkin_date == checkin_date,
        Tenancy.stay_type == StayType.daily,
    )
)
if existing:
    stats["skipped"] += 1
    continue

stay_status = TenancyStatus.active if str(status or "").upper() in ("ACTIVE", "CHECKIN") else TenancyStatus.exited
tenancy = Tenancy(
    tenant_id=tenant.id,
    room_id=room_obj.id if room_obj else None,
    stay_type=StayType.daily,
    status=stay_status,
    checkin_date=checkin_date,
    checkout_date=checkout_date,
    expected_checkout=checkout_date,
    agreed_rent=daily_rate or 0,
    booking_amount=booking_amount or 0,
    maintenance_fee=maintenance or 0,
    notes=comments or "",
    entered_by="excel_import",
)
session.add(tenancy)
await session.flush()

if float(total_amount or 0) > 0:
    session.add(Payment(
        tenancy_id=tenancy.id,
        amount=total_amount,
        mode=PaymentMode.cash,
        payment_date=payment_date or checkin_date,
        payment_for=PaymentFor.rent,
        entered_by="excel_import",
    ))
stats["imported"] += 1
```

Also remove the `DaywiseStay` import from the top of the file.

- [ ] **Step 3.3: Dry-run against the Excel file to verify no crash**

```bash
venv/Scripts/python scripts/import_daywise.py
```
Expected: shows counts without errors. (Add `--write` only when ready to apply.)

- [ ] **Step 3.4: Commit**

```bash
git add scripts/import_daywise.py
git commit -m "feat(import): import_daywise writes Tenancy(stay_type=daily) not DaywiseStay"
```

---

## Task 4 — Rewrite gsheets.add_daywise_stay() to MONTHLY_HEADERS

**Files:**
- Modify: `src/integrations/gsheets.py` lines 1477–1525

The current `_add_daywise_stay_sync` uses old DAY WISE column names. Replace with MONTHLY_HEADERS format.

- [ ] **Step 4.1: Write a test for the new signature**

Add to `tests/test_gsheets.py` (or create `tests/test_daywise_sheet.py`):

```python
def test_add_daywise_stay_builds_correct_row():
    """add_daywise_stay kwargs map correctly to MONTHLY_HEADERS positions."""
    from src.integrations.gsheets import MONTHLY_HEADERS, _build_daywise_row
    row = _build_daywise_row(
        room_number="305", tenant_name="Ramu", phone="9876543210",
        building="THOR", sharing="2-sharing", daily_rate=500.0,
        num_days=3, booking_amount=200.0, total_paid=1500.0,
        maintenance=0.0, checkin="01/04/2026", checkout="04/04/2026",
        status="ACTIVE", notes="", entered_by="onboarding_form",
    )
    h = {v: i for i, v in enumerate(MONTHLY_HEADERS)}
    assert row[h["Room"]] == "305"
    assert row[h["Name"]] == "Ramu"
    assert row[h["Rent"]] == 500.0          # daily rate
    assert row[h["Rent Due"]] == 1500.0     # 500 * 3 + 0 maintenance
    assert row[h["Total Paid"]] == 1500.0
    assert row[h["Balance"]] == 0.0
    assert row[h["Status"]] == "ACTIVE"
```

Run: `venv/Scripts/python -m pytest tests/test_daywise_sheet.py -v` — expect FAIL (function not found).

- [ ] **Step 4.2: Add `_build_daywise_row` helper and rewrite `_add_daywise_stay_sync`**

In `src/integrations/gsheets.py`, replace `_add_daywise_stay_sync` (lines 1477–1519) with:

```python
def _build_daywise_row(
    room_number: str, tenant_name: str, phone: str, building: str,
    sharing: str, daily_rate: float, num_days: int, booking_amount: float,
    total_paid: float, maintenance: float, checkin: str, checkout: str,
    status: str, notes: str, entered_by: str,
) -> list:
    """Build a MONTHLY_HEADERS-aligned row for a daily-stay tenant."""
    rent_due = round(daily_rate * num_days + maintenance, 2)
    balance = round(rent_due - total_paid, 2)
    # MONTHLY_HEADERS order:
    # Room|Name|Phone|Building|Sharing|Rent|Deposit|Rent Due|Cash|UPI|Total Paid|Balance|Status|Check-in|Notice Date|Event|Notes|Prev Due|Entered By
    return [
        room_number,            # Room
        tenant_name,            # Name
        f"'{phone}" if phone else "",  # Phone (prefix ' so Sheets treats as text)
        building,               # Building
        sharing,                # Sharing
        daily_rate,             # Rent (= daily rate)
        booking_amount,         # Deposit (= advance/booking)
        rent_due,               # Rent Due
        total_paid,             # Cash  (simplified: total shown as cash; split tracked in Payment table)
        0,                      # UPI
        total_paid,             # Total Paid
        balance,                # Balance
        status,                 # Status
        checkin,                # Check-in
        "",                     # Notice Date
        f"checkout: {checkout}", # Event
        notes,                  # Notes
        "",                     # Prev Due
        entered_by,             # Entered By
    ]


def _add_daywise_stay_sync(
    room_number: str, tenant_name: str, phone: str, building: str = "",
    sharing: str = "", daily_rate: float = 0, num_days: int = 0,
    booking_amount: float = 0, total_paid: float = 0, maintenance: float = 0,
    checkin: str = "", checkout: str = "", status: str = "ACTIVE",
    notes: str = "", entered_by: str = "",
    **_kwargs,   # swallow legacy keyword args gracefully
) -> dict:
    """Append a day-wise stay row to DAY WISE tab using MONTHLY_HEADERS format."""
    result = {"success": False, "row": None, "error": None}
    try:
        ws = _get_worksheet_sync("DAY WISE")
        all_vals = ws.get_all_values()

        # Ensure header row exists at row 1
        if not all_vals or [h.strip() for h in all_vals[0]] != MONTHLY_HEADERS:
            ws.update(values=[MONTHLY_HEADERS], range_name="A1",
                      value_input_option="USER_ENTERED")
            all_vals = ws.get_all_values()

        row = _build_daywise_row(
            room_number=room_number, tenant_name=tenant_name, phone=phone,
            building=building, sharing=sharing, daily_rate=daily_rate,
            num_days=num_days, booking_amount=booking_amount, total_paid=total_paid,
            maintenance=maintenance, checkin=checkin, checkout=checkout,
            status=status, notes=notes, entered_by=entered_by,
        )
        next_row = len(all_vals) + 1
        ws.update(values=[row], range_name=f"A{next_row}", value_input_option="USER_ENTERED")
        result["success"] = True
        result["row"] = next_row
    except Exception as e:
        result["error"] = str(e)
    return result


async def add_daywise_stay(**kwargs) -> dict:
    """Async wrapper for _add_daywise_stay_sync."""
    import asyncio
    return await asyncio.to_thread(_add_daywise_stay_sync, **kwargs)
```

Also add `MONTHLY_HEADERS` to the module-level import section (it may already be in `field_registry.py` — import from there if so, otherwise define it once here).

- [ ] **Step 4.3: Run tests — expect pass**

```bash
venv/Scripts/python -m pytest tests/test_daywise_sheet.py -v
```
Expected: 1 test passes.

- [ ] **Step 4.4: Commit**

```bash
git add src/integrations/gsheets.py tests/test_daywise_sheet.py
git commit -m "feat(gsheets): add_daywise_stay uses MONTHLY_HEADERS format"
```

---

## Task 5 — Update Occupancy Callsites

**Files:**
- Modify: `src/services/room_occupancy.py`
- Modify: `src/services/occupants.py`
- Modify: `src/whatsapp/handlers/account_handler.py` (lines ~1463–1466, ~1974–1976, ~2013–2016)
- Modify: `src/whatsapp/handlers/owner_handler.py` (lines ~6395–6398)

All 11 callsites that query `DaywiseStay` for active occupancy switch to `Tenancy WHERE stay_type=daily`.

The pattern to replace everywhere:

**Old pattern:**
```python
select(DaywiseStay).where(
    DaywiseStay.checkin_date <= <date>,
    DaywiseStay.checkout_date > <date>,
    DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
)
```

**New pattern:**
```python
select(Tenancy).join(Tenant).where(
    Tenancy.stay_type == StayType.daily,
    Tenancy.checkin_date <= <date>,
    Tenancy.checkout_date > <date>,
    Tenancy.status == TenancyStatus.active,
)
```

- [ ] **Step 5.1: Update `src/services/room_occupancy.py`**

Find every `DaywiseStay` reference. Replace the per-room query (lines ~137–146):

```python
# OLD
dw = (await session.execute(
    select(DaywiseStay).where(
        DaywiseStay.room_number == room.room_number,
        DaywiseStay.checkin_date <= when,
        DaywiseStay.checkout_date > when,
        DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
    )
)).scalars().all()
return RoomOccupants(tenancies=tenancies, daywise=list(dw))

# NEW
dw_tenancies = (await session.execute(
    select(Tenancy).where(
        Tenancy.room_id == room.id,
        Tenancy.stay_type == StayType.daily,
        Tenancy.checkin_date <= when,
        Tenancy.checkout_date > when,
        Tenancy.status == TenancyStatus.active,
    )
)).scalars().all()
return RoomOccupants(tenancies=tenancies, daywise=list(dw_tenancies))
```

Replace the count query (lines ~375–385):
```python
# OLD
occupied_dw = await session.scalar(
    select(func.count())
    .select_from(DaywiseStay)
    .join(Room, Room.room_number == DaywiseStay.room_number)
    .where(
        Room.is_staff_room == False,
        DaywiseStay.checkin_date <= when,
        DaywiseStay.checkout_date > when,
        DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
    )
) or 0

# NEW
occupied_dw = await session.scalar(
    select(func.count())
    .select_from(Tenancy)
    .join(Room, Room.id == Tenancy.room_id)
    .where(
        Room.is_staff_room == False,
        Tenancy.stay_type == StayType.daily,
        Tenancy.checkin_date <= when,
        Tenancy.checkout_date > when,
        Tenancy.status == TenancyStatus.active,
    )
) or 0
```

Update the `RoomOccupants` dataclass `daywise` field annotation from `list[DaywiseStay]` to `list[Tenancy]`. Also remove `DaywiseStay` from imports; add `StayType` if not already imported.

- [ ] **Step 5.2: Update `src/services/occupants.py`**

Find `d.guest_name for d in occ.daywise` (around line 182 of onboarding_router.py — the caller). After changing `occ.daywise` to `list[Tenancy]`, update callers that access `.guest_name` to use `.tenant.name` (needs `selectinload(Tenancy.tenant)` in the query).

In `room_occupancy.py`, add `selectinload` to the daily tenancy query:
```python
from sqlalchemy.orm import selectinload

dw_tenancies = (await session.execute(
    select(Tenancy)
    .options(selectinload(Tenancy.tenant))
    .where(
        Tenancy.room_id == room.id,
        Tenancy.stay_type == StayType.daily,
        Tenancy.checkin_date <= when,
        Tenancy.checkout_date > when,
        Tenancy.status == TenancyStatus.active,
    )
)).scalars().all()
```

In `src/api/onboarding_router.py` line ~182, change:
```python
# OLD
[d.guest_name for d in occ.daywise]
# NEW
[t.tenant.name for t in occ.daywise]
```

- [ ] **Step 5.3: Update account_handler.py and owner_handler.py callsites**

Grep for all remaining `DaywiseStay` imports and queries in handler files:
```bash
grep -n "DaywiseStay\|daywise_stays" src/whatsapp/handlers/account_handler.py src/whatsapp/handlers/owner_handler.py
```

For each, apply the same pattern: replace `DaywiseStay` filter with `Tenancy WHERE stay_type=daily, status=active`. Access `.tenant.name` instead of `.guest_name`, `.room_id` instead of `.room_number` (join Room if room_number needed).

- [ ] **Step 5.4: Run fast unit tests**

```bash
venv/Scripts/python -m pytest tests/ -v -x --ignore=tests/eval_golden.py --ignore=tests/benchmark_3way.py -q
```
Expected: all pass.

- [ ] **Step 5.5: Commit**

```bash
git add src/services/room_occupancy.py src/services/occupants.py src/whatsapp/handlers/account_handler.py src/whatsapp/handlers/owner_handler.py src/api/onboarding_router.py
git commit -m "refactor: all DaywiseStay occupancy queries → Tenancy(stay_type=daily)"
```

---

## Task 6 — Remove Dead Day-Wise Handler Branches

**Files:**
- Modify: `src/whatsapp/handlers/_shared.py`
- Modify: `src/whatsapp/handlers/owner_handler.py`
- Modify: `src/whatsapp/handlers/account_handler.py`

After Task 5, day-wise guests are found via `_find_active_tenants_by_name`. Remove the day-wise-specific branches.

- [ ] **Step 6.1: Remove `_find_active_daywise_by_name` from `_shared.py`**

Delete the entire `_find_active_daywise_by_name` function. Remove any callers — grep for them:
```bash
grep -rn "_find_active_daywise_by_name" src/
```
The only expected caller is the ROOM_TRANSFER flow in owner_handler.py (handled below).

- [ ] **Step 6.2: Remove DAYWISE_RENT_CHANGE handlers from `owner_handler.py`**

Delete the two blocks added in a recent session:
- `DAYWISE_RENT_CHANGE_WHO` handler block
- `DAYWISE_RENT_CHANGE` handler block

Also remove `"DAYWISE_RENT_CHANGE"` and `"DAYWISE_RENT_CHANGE_WHO"` from the negative-reply cancel list.

After removal, `UPDATE_RENT` on a daily tenant updates `Tenancy.agreed_rent` (the daily rate) through the same path as monthly — no special handling needed.

- [ ] **Step 6.3: Remove ROOM_TRANSFER_DW_* handlers from `owner_handler.py`**

Delete:
- `ROOM_TRANSFER_DW_WHO` handler block (lines ~2515–2524)
- `ROOM_TRANSFER_DW_DEST` handler block (lines ~2526–2532)
- `ROOM_TRANSFER_DW_CONFIRM` handler block (lines ~2534–2540)
- `_finalize_daywise_transfer()` function
- `_do_daywise_transfer()` function

The regular `ROOM_TRANSFER` flow handles both monthly and daily tenants after migration — `_find_active_tenants_by_name` returns daily stays too.

Verify the regular ROOM_TRANSFER flow has no monthly-only guard:
```bash
grep -n "stay_type\|monthly" src/whatsapp/handlers/owner_handler.py | grep -i "transfer" | head -10
```
If a guard exists, remove it.

- [ ] **Step 6.4: Run tests**

```bash
venv/Scripts/python -m pytest tests/ -q --ignore=tests/eval_golden.py --ignore=tests/benchmark_3way.py
```
Expected: all pass.

- [ ] **Step 6.5: Commit**

```bash
git add src/whatsapp/handlers/_shared.py src/whatsapp/handlers/owner_handler.py src/whatsapp/handlers/account_handler.py
git commit -m "refactor: remove DaywiseStay-specific handler branches — daily guests use Tenancy paths"
```

---

## Task 7 — QUERY_DUES for Daily Tenants

**Files:**
- Modify: `src/whatsapp/handlers/account_handler.py` function `_query_dues` (~line 1001)

Daily tenants have no `RentSchedule`. Their outstanding = `agreed_rent × num_days + maintenance_fee − total_paid`.

- [ ] **Step 7.1: Write failing test**

Add to `tests/test_dues_month_scope.py`:

```python
def test_daily_tenant_dues_no_rent_schedule(server_url, admin_phone, clear_pending):
    """A daily stay tenant with no RentSchedule still appears in dues query."""
    import requests
    r = requests.post(f"{server_url}/api/whatsapp/process",
                      json={"phone": admin_phone, "message": "daily stay dues"})
    # Should not crash; should return a reply (even if empty dues list)
    assert r.status_code == 200
    data = r.json()
    assert "reply" in data
```

(This is an integration test — run after server is up.)

- [ ] **Step 7.2: Add daily dues calculation to `_query_dues`**

In `src/whatsapp/handlers/account_handler.py`, after the existing RentSchedule query (line ~1039), append a daily-tenant dues query:

```python
    # ── Daily stays: compute dues on-the-fly (no RentSchedule) ──────────────
    daily_result = await session.execute(
        select(Tenant.name, Tenancy.agreed_rent, Tenancy.checkout_date,
               Tenancy.checkin_date, Tenancy.maintenance_fee, Tenancy.id.label("tenancy_id"))
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .where(
            Tenancy.stay_type == StayType.daily,
            Tenancy.status == TenancyStatus.active,
        )
    )
    daily_rows = daily_result.all()

    for dname, daily_rate, checkout, checkin, maint, t_id in daily_rows:
        num_days = max(1, (checkout - checkin).days) if checkout and checkin else 1
        rent_due = float(daily_rate or 0) * num_days + float(maint or 0)
        total_paid_q = await session.scalar(
            select(func.sum(Payment.amount)).where(
                Payment.tenancy_id == t_id,
                Payment.is_void == False,
            )
        )
        balance = rent_due - float(total_paid_q or 0)
        if balance > 0:
            lines.append(f"• {dname} (day-stay): Rs.{int(balance):,} outstanding")
            total += Decimal(str(round(balance, 2)))
```

Add `StayType` to the imports at the top of `account_handler.py` if not already present.

- [ ] **Step 7.3: Run fast tests**

```bash
venv/Scripts/python -m pytest tests/test_dues_month_scope.py -q
```

- [ ] **Step 7.4: Commit**

```bash
git add src/whatsapp/handlers/account_handler.py
git commit -m "feat: QUERY_DUES includes daily-stay tenants (computed, no RentSchedule)"
```

---

## Task 8 — Rewrite sync_daywise_from_db.py

**Files:**
- Rewrite: `scripts/sync_daywise_from_db.py`

Replace `DaywiseStay` source with `Tenancy WHERE stay_type=daily`. Output MONTHLY_HEADERS to DAY WISE tab.

- [ ] **Step 8.1: Rewrite the script**

Replace the entire content of `scripts/sync_daywise_from_db.py`:

```python
"""
scripts/sync_daywise_from_db.py
================================
Regenerate the 'DAY WISE' Google Sheet tab from Tenancy(stay_type=daily).

Usage:
    python scripts/sync_daywise_from_db.py           # dry run
    python scripts/sync_daywise_from_db.py --write   # write to sheet
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload

from src.database.models import Tenancy, StayType, TenancyStatus, Tenant, Room, Payment
from src.database.models import func  # noqa: F401 — available via sqlalchemy
from sqlalchemy import func as sa_func

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

TAB_NAME = "DAY WISE"

# Import MONTHLY_HEADERS from the canonical source
try:
    from src.database.field_registry import monthly_headers
    MONTHLY_HEADERS = monthly_headers()
except Exception:
    MONTHLY_HEADERS = [
        "Room", "Name", "Phone", "Building", "Sharing",
        "Rent", "Deposit", "Rent Due", "Cash", "UPI",
        "Total Paid", "Balance", "Status", "Check-in",
        "Notice Date", "Event", "Notes", "Prev Due", "Entered By",
    ]


async def main(args) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        rows = (await session.execute(
            select(Tenancy)
            .options(selectinload(Tenancy.tenant), selectinload(Tenancy.room), selectinload(Tenancy.payments))
            .where(Tenancy.stay_type == StayType.daily)
            .order_by(Tenancy.checkin_date.desc())
        )).scalars().all()

        print(f"DB daily tenancies: {len(rows)} rows")

        today = date.today()
        data_rows = []
        total_revenue = 0.0
        active_count = 0

        for t in rows:
            tenant = t.tenant
            room = t.room
            checkin = t.checkin_date.strftime("%d/%m/%Y") if t.checkin_date else ""
            checkout = t.checkout_date.strftime("%d/%m/%Y") if t.checkout_date else ""
            num_days = max(1, (t.checkout_date - t.checkin_date).days) if t.checkout_date and t.checkin_date else 0
            daily_rate = float(t.agreed_rent or 0)
            maintenance = float(t.maintenance_fee or 0)
            booking_amount = float(t.booking_amount or 0)
            rent_due = round(daily_rate * num_days + maintenance, 2)

            # Sum payments from Payment table
            cash_paid = sum(float(p.amount or 0) for p in t.payments
                            if not p.is_void and (p.mode or "").lower() not in ("upi", "bank", "online", "neft", "imps"))
            upi_paid = sum(float(p.amount or 0) for p in t.payments
                           if not p.is_void and (p.mode or "").lower() in ("upi", "bank", "online", "neft", "imps"))
            total_paid = round(cash_paid + upi_paid, 2)
            balance = round(rent_due - total_paid, 2)

            # Auto-fix status for display
            display_status = str(t.status.value if hasattr(t.status, 'value') else t.status).upper()
            if t.status == TenancyStatus.active and t.checkout_date and t.checkout_date < today:
                display_status = "EXIT"
            if t.status == TenancyStatus.active:
                active_count += 1
            total_revenue += total_paid

            phone = tenant.phone if tenant else ""
            row = [
                room.room_number if room else "",           # Room
                tenant.name if tenant else "",              # Name
                f"'{phone}" if phone else "",              # Phone
                room.building if room else "",              # Building
                str(t.sharing_type.value if t.sharing_type else ""),  # Sharing
                daily_rate,                                 # Rent
                booking_amount,                             # Deposit
                rent_due,                                   # Rent Due
                round(cash_paid, 2),                        # Cash
                round(upi_paid, 2),                         # UPI
                total_paid,                                 # Total Paid
                balance,                                    # Balance
                display_status,                             # Status
                checkin,                                    # Check-in
                "",                                         # Notice Date
                f"checkout: {checkout}" if checkout else "", # Event
                t.notes or "",                              # Notes
                "",                                         # Prev Due
                t.entered_by or "",                         # Entered By
            ]
            data_rows.append(row)

        # Summary stats
        print(f"  Active today: {active_count} | Total revenue: Rs.{int(total_revenue):,}")

        if not args.write:
            print("[DRY RUN] Not writing to sheet.")
            return

        from src.integrations.gsheets import _get_worksheet_sync, _get_spreadsheet_sync
        import gspread

        try:
            ws = _get_worksheet_sync(TAB_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ss = _get_spreadsheet_sync()
            ws = ss.add_worksheet(title=TAB_NAME, rows=500, cols=len(MONTHLY_HEADERS))

        # Write header + data rows
        all_rows = [MONTHLY_HEADERS] + data_rows
        ws.clear()
        if all_rows:
            ws.update(values=all_rows, range_name="A1", value_input_option="USER_ENTERED")
        print(f"Written {len(data_rows)} rows to '{TAB_NAME}' tab.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
```

- [ ] **Step 8.2: Dry-run**

```bash
venv/Scripts/python scripts/sync_daywise_from_db.py
```
Expected: prints row count, no crash. (Rows will be 0 until migration runs.)

- [ ] **Step 8.3: Commit**

```bash
git add scripts/sync_daywise_from_db.py
git commit -m "refactor(sync): sync_daywise_from_db reads Tenancy(stay_type=daily), writes MONTHLY_HEADERS"
```

---

## Task 9 — Route Daily-Stay Payments to DAY WISE Tab

**Files:**
- Modify: `src/integrations/gsheets.py` function `_update_payment_sync` and `update_payment`

When logging a payment for a daily-stay tenant, write to the DAY WISE tab (not a monthly tab).

- [ ] **Step 9.1: Add `is_daily` parameter to `update_payment` and `_update_payment_sync`**

In `src/integrations/gsheets.py`, update the `update_payment` async function signature:

```python
async def update_payment(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    entered_by: str = "",
    is_daily: bool = False,       # NEW — set True for stay_type=daily tenants
) -> dict:
    return await asyncio.to_thread(
        _update_payment_sync,
        room_number, tenant_name, amount, method, month, year, entered_by, is_daily,
    )
```

Update `_update_payment_sync` signature to accept `is_daily: bool = False`. Before the `tab_name = _month_tab_for(month, year)` line, add:

```python
    if is_daily:
        tab_name = "DAY WISE"
        # For DAY WISE tab: locate row by Room + Name (no month column)
        # The rest of the function (find row, update Cash/UPI, recalc Balance) works
        # identically because DAY WISE now uses MONTHLY_HEADERS.
    else:
        tab_name = _month_tab_for(month, year)
```

- [ ] **Step 9.2: Update payment callers to pass `is_daily=True` for daily tenants**

In `src/whatsapp/handlers/account_handler.py`, the payment write-back block (~line 492) calls `gsheets_update(...)`. After looking up the `tenancy`, pass `is_daily=(tenancy.stay_type == StayType.daily)`:

```python
        await _aio.wait_for(gsheets_update(
            room_number=room_obj.room_number,
            tenant_name=tenant.name,
            amount=float(amount_dec),
            method=mode,
            month=period_month.month,
            year=period_month.year,
            entered_by=ctx_name or "bot",
            is_daily=(tenancy.stay_type == StayType.daily),
        ), timeout=10)
```

- [ ] **Step 9.3: Run fast tests**

```bash
venv/Scripts/python -m pytest tests/ -q --ignore=tests/eval_golden.py --ignore=tests/benchmark_3way.py
```

- [ ] **Step 9.4: Commit**

```bash
git add src/integrations/gsheets.py src/whatsapp/handlers/account_handler.py
git commit -m "feat(gsheets): route daily-stay payments to DAY WISE tab"
```

---

## Task 10 — Run Migration + Full Verification

- [ ] **Step 10.1: Run migration dry-run on VPS DB via SSH**

```bash
ssh root@187.127.130.194 "cd /opt/pg-accountant && venv/bin/python scripts/migrate_daywise_to_tenancy.py"
```
Expected: prints counts. Review `would_migrate` vs `skip_no_phone`. Check `migration_skipped.txt` if it appears.

- [ ] **Step 10.2: Run migration with --write on VPS**

```bash
ssh root@187.127.130.194 "cd /opt/pg-accountant && venv/bin/python scripts/migrate_daywise_to_tenancy.py --write"
```
Expected: `migrated: N` rows, 0 errors.

- [ ] **Step 10.3: Run sync_daywise_from_db to populate DAY WISE sheet**

```bash
ssh root@187.127.130.194 "cd /opt/pg-accountant && venv/bin/python scripts/sync_daywise_from_db.py --write"
```
Expected: DAY WISE tab in Google Sheets now shows MONTHLY_HEADERS with daily tenant rows.

- [ ] **Step 10.4: Smoke-test via WhatsApp bot**

Send these messages as admin to the live bot and verify correct responses:

1. `how many guests today` — should include day-wise guests in count
2. `[DayWise GuestName] balance` — should return balance (dues − paid)
3. `change [DayWise GuestName] rent 600` — should update Tenancy.agreed_rent
4. `move [DayWise GuestName] to room 305` — should use regular ROOM_TRANSFER flow

- [ ] **Step 10.5: Run full test suite**

```bash
venv/Scripts/python -m pytest tests/ -q --ignore=tests/eval_golden.py --ignore=tests/benchmark_3way.py
```
Expected: all pass (or note any legitimate failures for follow-up).

- [ ] **Step 10.6: Deploy and final commit**

```bash
ssh root@187.127.130.194 "cd /opt/pg-accountant && git pull && systemctl restart pg-accountant"
```

```bash
git add -A
git commit -m "feat: day-wise parity complete — all guests in Tenancy(stay_type=daily)"
git push
```

---

## Self-Review Checklist

- [x] Migration script is idempotent (source_file=MIGRATED tombstone, duplicate check)
- [x] Phone mandatory — rows without phone skipped to migration_skipped.txt
- [x] Onboarding write path updated (Task 2)
- [x] Excel import updated (Task 3)
- [x] GSheets write uses MONTHLY_HEADERS (Task 4)
- [x] All 11 occupancy callsites covered (Task 5)
- [x] Dead DAYWISE_RENT_CHANGE handlers removed (Task 6)
- [x] Dead ROOM_TRANSFER_DW handlers removed (Task 6)
- [x] `_find_active_daywise_by_name` removed (Task 6)
- [x] QUERY_DUES includes daily tenants (Task 7)
- [x] sync_daywise_from_db.py rewritten (Task 8)
- [x] Payment routing for daily → DAY WISE tab (Task 9)
- [x] Migration run on VPS (Task 10)
- [x] DaywiseStay table left intact as read-only archive (no DROP)
