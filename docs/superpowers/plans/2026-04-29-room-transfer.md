# Room Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add room transfer to the tenant management PWA, sharing one `execute_room_transfer()` service with the WhatsApp bot so both always behave identically.

**Architecture:** Extract the bot's inline `_do_room_transfer` DB logic into `services/room_transfer.py`. Two new API endpoints handle availability checking and transfer execution. The PWA edit page gains a 4-step Transfer Room panel.

**Tech Stack:** FastAPI + SQLAlchemy async, Next.js 14 (app router), Tailwind CSS, existing `ConfirmationCard` component.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `services/room_transfer.py` | **Create** | Single source of truth for transfer DB logic |
| `src/api/v2/rooms.py` | **Create** | `GET /rooms/check` availability endpoint |
| `src/api/v2/tenants.py` | **Modify** | Add `POST /tenants/{id}/transfer-room` |
| `src/api/v2/app_router.py` | **Modify** | Register `rooms_router` |
| `src/whatsapp/handlers/owner_handler.py` | **Modify** | Replace `_do_room_transfer` body + remove redundant post-call code |
| `web/lib/api.ts` | **Modify** | Add `checkRoom()` and `transferRoom()` |
| `web/app/tenants/[tenancy_id]/edit/page.tsx` | **Modify** | Add Transfer Room panel (4 steps) |

---

## Task 1: Create `services/room_transfer.py`

**Files:**
- Create: `services/room_transfer.py`
- Test: `tests/test_room_transfer_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_room_transfer_service.py
"""Unit tests for execute_room_transfer — uses real DB session (test DB)."""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

# We test the return shape and that it raises no exceptions on a happy path.
# Full integration tests require the DB; these tests mock the session.

@pytest.mark.asyncio
async def test_execute_room_transfer_room_not_found():
    from services.room_transfer import execute_room_transfer
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)  # room not found

    result = await execute_room_transfer(
        tenancy_id=1,
        to_room_number="999",
        new_rent=15000,
        extra_deposit=0,
        changed_by="pwa",
        source="pwa",
        session=session,
    )
    assert result["success"] is False
    assert "not found" in result["message"].lower()


@pytest.mark.asyncio
async def test_execute_room_transfer_room_full():
    from services.room_transfer import execute_room_transfer
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()

    # Room found but full
    mock_room = MagicMock()
    mock_room.id = 10
    mock_room.room_number = "405"
    mock_room.max_occupancy = 2
    mock_room.active = True

    # Mock tenancy, tenant, current room
    mock_tenancy = MagicMock()
    mock_tenancy.id = 1
    mock_tenancy.room_id = 5
    mock_tenancy.agreed_rent = Decimal("14000")
    mock_tenancy.security_deposit = Decimal("15000")
    mock_tenancy.org_id = 1

    mock_tenant = MagicMock()
    mock_tenant.name = "Raj Kumar"
    mock_tenant.id = 42

    mock_current_room = MagicMock()
    mock_current_room.room_number = "302"

    # scalars: room lookup, tenancy lookup
    scalar_results = [mock_room, mock_tenancy]
    scalar_call_count = 0

    async def fake_scalar(stmt):
        nonlocal scalar_call_count
        idx = scalar_call_count
        scalar_call_count += 1
        return scalar_results[idx] if idx < len(scalar_results) else None

    session.scalar = fake_scalar

    # execute returns list with 2 occupants (room is full, max=2)
    mock_execute = AsyncMock()
    mock_execute.return_value.all = MagicMock(return_value=[
        ("Priya Sharma", "2026-06-01"),
        ("Anjali Rao", "2026-06-01"),
    ])
    # second execute for daywise
    mock_execute2 = AsyncMock()
    mock_execute2.return_value.all = MagicMock(return_value=[])

    call_count = 0
    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.all = MagicMock(return_value=[("Priya Sharma", "2026-06-01"), ("Anjali Rao", "2026-06-01")])
            return r
        r = MagicMock()
        r.all = MagicMock(return_value=[])
        r.first = MagicMock(return_value=(mock_tenancy, mock_tenant, mock_current_room))
        return r

    session.execute = fake_execute

    result = await execute_room_transfer(
        tenancy_id=1,
        to_room_number="405",
        new_rent=15000,
        extra_deposit=0,
        changed_by="pwa",
        source="pwa",
        session=session,
    )
    assert result["success"] is False
    assert "full" in result["message"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant"
venv/Scripts/python -m pytest tests/test_room_transfer_service.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'services.room_transfer'`

- [ ] **Step 3: Create `services/room_transfer.py`**

```python
"""
Shared room-transfer logic used by both the WhatsApp bot and the PWA API.
Single source of truth — change once, both callers updated.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    AuditLog,
    Room,
    RentRevision,
    RentSchedule,
    Tenancy,
    Tenant,
    TenancyStatus,
    StayType,
)


async def execute_room_transfer(
    tenancy_id: int,
    to_room_number: str,
    new_rent: float | None,
    extra_deposit: float,
    changed_by: str,
    source: str,
    session: AsyncSession,
) -> dict:
    """
    Transfer a tenant to a new room.

    Returns:
        { success: bool, message: str, from_room?, to_room?, new_rent?, extra_deposit? }

    Never raises — errors returned as success=False dict so callers can display inline.
    """
    to_room_number = to_room_number.upper().strip()

    # 1. Lookup destination room
    new_room = await session.scalar(
        select(Room).where(Room.room_number == to_room_number, Room.active == True)
    )
    if not new_room:
        return {"success": False, "message": f"Room {to_room_number} not found."}

    # 2. Load tenancy + tenant + current room
    row = (await session.execute(
        select(Tenancy, Tenant, Room)
        .join(Tenant, Tenancy.tenant_id == Tenant.id)
        .join(Room, Tenancy.room_id == Room.id)
        .where(Tenancy.id == tenancy_id)
    )).first()
    if not row:
        return {"success": False, "message": "Tenancy not found."}
    tenancy, tenant, current_room = row
    from_room = current_room.room_number
    tenant_name = tenant.name

    if from_room == to_room_number:
        return {"success": False, "message": f"Tenant is already in room {to_room_number}."}

    # 3. Occupancy check — active monthly tenants in new room
    today = date.today()
    occupied_rows = (await session.execute(
        select(Tenant.name, Tenancy.id)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .where(
            Tenancy.room_id == new_room.id,
            Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
        )
    )).all()

    # Active daywise guests in new room today
    daywise_count = (await session.scalar(
        select(func.count()).where(
            Tenancy.room_id == new_room.id,
            Tenancy.stay_type == StayType.daily,
            Tenancy.checkin_date <= today,
            Tenancy.checkout_date >= today,
            Tenancy.status == TenancyStatus.active,
        )
    )) or 0

    max_occ = int(new_room.max_occupancy or 1)
    total_occ = len(occupied_rows) + daywise_count
    if total_occ >= max_occ:
        names = ", ".join(r[0] for r in occupied_rows)
        return {
            "success": False,
            "message": f"Room {to_room_number} is full ({total_occ}/{max_occ} beds): {names}",
        }

    # 4. Resolve rent — keep current if new_rent not supplied
    old_rent = float(tenancy.agreed_rent or 0)
    resolved_rent = float(new_rent) if new_rent is not None else old_rent
    rent_changed = resolved_rent != old_rent

    # 5. DB writes (all within the passed session — caller commits)
    tenancy.room_id = new_room.id
    tenancy.agreed_rent = Decimal(str(resolved_rent))

    if rent_changed:
        session.add(RentRevision(
            tenancy_id=tenancy_id,
            old_rent=Decimal(str(old_rent)),
            new_rent=Decimal(str(resolved_rent)),
            effective_date=today,
            changed_by=changed_by,
            reason=f"Room transfer: {from_room} → {to_room_number}",
        ))
        # Update current month RentSchedule if it exists
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy_id,
                RentSchedule.period_month == today.replace(day=1),
            )
        )
        if rs:
            rs.rent_due = Decimal(str(resolved_rent))

    if extra_deposit and extra_deposit > 0:
        tenancy.security_deposit = (tenancy.security_deposit or Decimal("0")) + Decimal(str(extra_deposit))

    session.add(AuditLog(
        changed_by=changed_by,
        entity_type="tenancy",
        entity_id=tenancy_id,
        entity_name=tenant_name,
        field="room_id",
        old_value=from_room,
        new_value=to_room_number,
        room_number=to_room_number,
        source=source,
        note=f"Room transfer: {from_room} → {to_room_number}",
        org_id=tenancy.org_id,
    ))

    # 6. Sheet sync — fire-and-forget
    try:
        import asyncio as _aio
        from src.integrations import gsheets as _gs
        _aio.create_task(_gs.update_tenants_tab_field(
            from_room, tenant_name, "room", to_room_number
        ))
        if rent_changed:
            _aio.create_task(_gs.update_tenants_tab_field(
                to_room_number, tenant_name, "agreed_rent", int(resolved_rent)
            ))
        _gs.trigger_monthly_sheet_sync(today.month, today.year)
    except Exception:
        pass

    # Build message (matches bot format)
    rent_note = f"\nNew rent: Rs.{int(resolved_rent):,}/mo" if rent_changed else ""
    deposit_note = f"\nDeposit increased by Rs.{int(extra_deposit):,}" if extra_deposit and extra_deposit > 0 else ""

    return {
        "success": True,
        "message": f"Room transferred — {tenant_name}\nRoom {from_room} → {to_room_number}{rent_note}{deposit_note}\nSheet update queued",
        "from_room": from_room,
        "to_room": to_room_number,
        "new_rent": resolved_rent,
        "extra_deposit": float(extra_deposit or 0),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
venv/Scripts/python -m pytest tests/test_room_transfer_service.py -v 2>&1 | head -30
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/room_transfer.py tests/test_room_transfer_service.py
git commit -m "feat(room-transfer): add shared execute_room_transfer service"
```

---

## Task 2: Create `src/api/v2/rooms.py` — GET /rooms/check

**Files:**
- Create: `src/api/v2/rooms.py`
- Modify: `src/api/v2/app_router.py`

- [ ] **Step 1: Create `src/api/v2/rooms.py`**

```python
"""GET /api/v2/app/rooms/check?room=XXX — availability check for room transfer."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Room, Tenancy, Tenant, TenancyStatus, StayType

router = APIRouter()


@router.get("/rooms/check")
async def check_room_availability(
    room: str = Query(..., description="Room number to check"),
    _user: AppUser = Depends(get_current_user),
):
    """Check if a room exists and has free beds. Used by Transfer Room panel."""
    room_number = room.upper().strip()
    today = date.today()

    async with get_session() as session:
        db_room = await session.scalar(
            select(Room).where(Room.room_number == room_number, Room.active == True)
        )
        if not db_room:
            raise HTTPException(status_code=404, detail=f"Room {room_number} not found")

        # Active monthly tenants
        occupant_rows = (await session.execute(
            select(Tenant.name, Tenancy.id)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .where(
                Tenancy.room_id == db_room.id,
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
            )
        )).all()

        # Active daywise today
        daywise_count = (await session.scalar(
            select(func.count()).where(
                Tenancy.room_id == db_room.id,
                Tenancy.stay_type == StayType.daily,
                Tenancy.checkin_date <= today,
                Tenancy.checkout_date >= today,
                Tenancy.status == TenancyStatus.active,
            )
        )) or 0

    max_occ = int(db_room.max_occupancy or 1)
    total_occ = len(occupant_rows) + daywise_count
    free_beds = max(max_occ - total_occ, 0)

    return {
        "room_number": room_number,
        "max_occupancy": max_occ,
        "free_beds": free_beds,
        "is_available": free_beds > 0,
        "occupants": [{"name": r[0], "tenancy_id": r[1]} for r in occupant_rows],
    }
```

- [ ] **Step 2: Register rooms router in `src/api/v2/app_router.py`**

Add after `from src.api.v2.reminders import router as reminders_router`:

```python
from src.api.v2.rooms import router as rooms_router
```

Add after `router.include_router(reminders_router)`:

```python
router.include_router(rooms_router)
```

- [ ] **Step 3: Smoke-test the endpoint**

Start the API: `venv/Scripts/python main.py`

```bash
curl "http://localhost:8000/api/v2/app/rooms/check?room=302" \
  -H "Authorization: Bearer <token>"
```

Expected response shape:
```json
{"room_number": "302", "max_occupancy": 2, "free_beds": 1, "is_available": true, "occupants": [...]}
```

For a non-existent room: HTTP 404.

- [ ] **Step 4: Commit**

```bash
git add src/api/v2/rooms.py src/api/v2/app_router.py
git commit -m "feat(room-transfer): add GET /rooms/check availability endpoint"
```

---

## Task 3: Add `POST /tenants/{tenancy_id}/transfer-room`

**Files:**
- Modify: `src/api/v2/tenants.py`

- [ ] **Step 1: Add the endpoint at the bottom of `src/api/v2/tenants.py`**

Add after the existing imports (add `from pydantic import BaseModel` if not present — check first):

```python
class TransferRoomBody(BaseModel):
    to_room_number: str
    new_rent: float | None = None
    extra_deposit: float = 0.0
```

Add the endpoint:

```python
@router.post("/tenants/{tenancy_id}/transfer-room")
async def transfer_room(
    tenancy_id: int,
    body: TransferRoomBody,
    user: AppUser = Depends(get_current_user),
):
    """Execute room transfer — called after PWA user confirms the 4-step panel."""
    from services.room_transfer import execute_room_transfer

    async with get_session() as session:
        result = await execute_room_transfer(
            tenancy_id=tenancy_id,
            to_room_number=body.to_room_number,
            new_rent=body.new_rent,
            extra_deposit=body.extra_deposit,
            changed_by=user.user_id or "pwa",
            source="pwa",
            session=session,
        )
        if result["success"]:
            await session.commit()
    return result
```

Note: returns HTTP 200 with `success: false` on business errors (room full, not found) — intentional, lets the frontend display messages inline.

- [ ] **Step 2: Smoke-test the endpoint**

```bash
curl -X POST "http://localhost:8000/api/v2/app/tenants/123/transfer-room" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"to_room_number": "405", "new_rent": 15000, "extra_deposit": 0}'
```

Expected success: `{"success": true, "message": "Room transferred — ...", ...}`
Expected failure (full room): `{"success": false, "message": "Room 405 is full ..."}`

- [ ] **Step 3: Commit**

```bash
git add src/api/v2/tenants.py
git commit -m "feat(room-transfer): add POST /tenants/{id}/transfer-room endpoint"
```

---

## Task 4: Refactor `owner_handler.py` — bot uses the shared service

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py`

There are two changes:
1. Replace the body of `_do_room_transfer` (line ~6475) with a call to `execute_room_transfer`
2. Remove the post-call RentSchedule + extra_deposit code from the `ROOM_TRANSFER` step-by-step handler (lines ~2574–2598) — the service now handles these

- [ ] **Step 1: Replace `_do_room_transfer` body**

Find `async def _do_room_transfer(action_data: dict, session: AsyncSession) -> str:` (line ~6475).

Replace the entire function body with:

```python
async def _do_room_transfer(action_data: dict, session: AsyncSession) -> str:
    from services.room_transfer import execute_room_transfer
    result = await execute_room_transfer(
        tenancy_id=action_data["tenancy_id"],
        to_room_number=action_data["to_room_number"],
        new_rent=action_data.get("new_rent"),
        extra_deposit=action_data.get("extra_deposit", 0),
        changed_by=action_data.get("changed_by", "whatsapp"),
        source="whatsapp",
        session=session,
    )
    return result["message"]
```

- [ ] **Step 2: Remove redundant post-call code from ROOM_TRANSFER step-by-step handler**

Find the `if step == "final_confirm":` block (line ~2568). Currently it calls `_do_room_transfer` and then has additional code to update `RentSchedule` and `extra_deposit`. The service now handles both. Simplify to:

```python
        if step == "final_confirm":
            if is_affirmative(reply_text):
                action_data["changed_by"] = pending.phone
                return await _do_room_transfer(action_data, session)
            return "Room transfer cancelled."
```

The lines to remove are the block starting with `if new_rent and new_rent != action_data["current_rent"]:` and ending with the `if extra_deposit > 0:` block (approximately lines 2575–2598).

- [ ] **Step 3: Test bot transfer via WhatsApp test endpoint**

Start the API and send a test message:

```bash
curl -X POST "http://localhost:8000/api/test/message" \
  -H "Content-Type: application/json" \
  -d '{"phone": "917845952289", "message": "transfer room Raj Kumar to 405"}'
```

Walk through the multi-step flow. Confirm:
- Bot asks about rent (keep/change)
- Bot asks about extra deposit
- Final confirm shows correct summary
- Transfer saves to DB and sheet queued

- [ ] **Step 4: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "refactor(room-transfer): bot _do_room_transfer delegates to shared service"
```

---

## Task 5: Add API client functions to `web/lib/api.ts`

**Files:**
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add types and functions**

Find the `// ── Reminders ─────` comment block. Add before it:

```typescript
// ── Room Transfer ─────────────────────────────────────────────────────────────

export interface RoomCheckResult {
  room_number: string
  max_occupancy: number
  free_beds: number
  is_available: boolean
  occupants: { name: string; tenancy_id: number }[]
}

export interface TransferRoomBody {
  to_room_number: string
  new_rent: number | null
  extra_deposit: number
}

export interface TransferRoomResult {
  success: boolean
  message: string
  from_room?: string
  to_room?: string
  new_rent?: number
  extra_deposit?: number
}

export function checkRoom(roomNumber: string): Promise<RoomCheckResult> {
  return _get<RoomCheckResult>(`/api/v2/app/rooms/check?room=${encodeURIComponent(roomNumber)}`)
}

export function transferRoom(tenancyId: number, body: TransferRoomBody): Promise<TransferRoomResult> {
  return _post<TransferRoomResult>(`/api/v2/app/tenants/${tenancyId}/transfer-room`, body)
}
```

- [ ] **Step 2: Verify `_post` helper exists in `web/lib/api.ts`**

Search for `function _post` or `async function _post` in `web/lib/api.ts`. If it doesn't exist, add it alongside `_get` and `_patch`:

```typescript
async function _post<T>(path: string, body: unknown): Promise<T> {
  const headers = await _authHeaders()
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}
```

- [ ] **Step 3: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(room-transfer): add checkRoom and transferRoom API client functions"
```

---

## Task 6: Add Transfer Room panel to edit page

**Files:**
- Modify: `web/app/tenants/[tenancy_id]/edit/page.tsx`

The panel is a 4-step inline flow rendered below the existing form. It does NOT replace the existing save flow.

- [ ] **Step 1: Add state variables**

In the existing state block (after `const [success, setSuccess] = useState(false)`), add:

```typescript
// Transfer Room panel state
const [showTransfer, setShowTransfer] = useState(false)
const [transferStep, setTransferStep] = useState<1 | 2 | 3 | 4>(1)
const [destRoom, setDestRoom] = useState("")          // destination room number input
const [roomCheck, setRoomCheck] = useState<RoomCheckResult | null>(null)
const [roomCheckLoading, setRoomCheckLoading] = useState(false)
const [roomCheckError, setRoomCheckError] = useState("")
const [transferNewRent, setTransferNewRent] = useState("")
const [transferExtraDeposit, setTransferExtraDeposit] = useState("0")
const [transferSubmitting, setTransferSubmitting] = useState(false)
const [transferError, setTransferError] = useState("")
const [transferSuccess, setTransferSuccess] = useState(false)
```

- [ ] **Step 2: Add import for API functions**

Update the import line at the top of the file:

```typescript
import { getTenantDues, patchTenant, checkRoom, transferRoom, TenantDues, PatchTenantBody, RoomCheckResult } from "@/lib/api"
```

- [ ] **Step 3: Add handler functions**

Add before `function buildChanges()`:

```typescript
async function handleCheckRoom() {
  if (!destRoom.trim()) return
  setRoomCheckLoading(true)
  setRoomCheckError("")
  setRoomCheck(null)
  try {
    const result = await checkRoom(destRoom.trim())
    setRoomCheck(result)
    if (!result.is_available) setRoomCheckError(`Room ${result.room_number} is full (${result.max_occupancy - result.free_beds}/${result.max_occupancy} beds)`)
  } catch (err) {
    setRoomCheckError(err instanceof Error ? err.message : "Room not found")
  } finally {
    setRoomCheckLoading(false)
  }
}

async function handleTransferConfirm() {
  if (!original) return
  setTransferSubmitting(true)
  setTransferError("")
  try {
    const result = await transferRoom(tenancyId, {
      to_room_number: roomCheck!.room_number,
      new_rent: transferNewRent ? Number(transferNewRent) : null,
      extra_deposit: Number(transferExtraDeposit) || 0,
    })
    if (!result.success) {
      setTransferError(result.message)
      setTransferStep(1)
      setRoomCheck(null)
      return
    }
    setTransferSuccess(true)
    // Refresh page data to show new room number
    const updated = await getTenantDues(tenancyId)
    setOriginal(updated)
    setRoomNumber(updated.room_number)
    setAgreedRent(String(updated.rent))
    setSecurityDeposit(String(updated.security_deposit))
  } catch (err) {
    setTransferError(err instanceof Error ? err.message : "Transfer failed")
  } finally {
    setTransferSubmitting(false)
  }
}

function resetTransferPanel() {
  setShowTransfer(false)
  setTransferStep(1)
  setDestRoom("")
  setRoomCheck(null)
  setRoomCheckError("")
  setTransferNewRent("")
  setTransferExtraDeposit("0")
  setTransferError("")
  setTransferSuccess(false)
}
```

- [ ] **Step 4: Add Transfer Room button and panel to the JSX**

Find where the existing Save / Review Changes button is rendered (look for `handleReview`). Add the Transfer Room button directly below it, and the panel below that.

```tsx
{/* Transfer Room button */}
{!showTransfer && !transferSuccess && (
  <button
    type="button"
    onClick={() => {
      setShowTransfer(true)
      setTransferNewRent(String(original?.rent ?? ""))
    }}
    className="w-full mt-3 py-3 rounded-2xl border-2 border-brand-pink text-brand-pink font-bold text-base"
  >
    Transfer Room
  </button>
)}

{/* Transfer Room panel */}
{showTransfer && !transferSuccess && (
  <div className="mt-4 rounded-2xl border border-[#F0EDE9] bg-surface p-5 space-y-4">
    <div className="flex items-center justify-between">
      <h3 className="font-extrabold text-ink text-base">Transfer Room</h3>
      <button type="button" onClick={resetTransferPanel} className="text-ink-muted text-sm">Cancel</button>
    </div>

    {/* Step 1: Room number */}
    {transferStep === 1 && (
      <div className="space-y-3">
        <p className="text-sm text-ink-muted">Current room: <strong>{original?.room_number}</strong></p>
        <div className="flex gap-2">
          <input
            className="flex-1 border border-[#E2DEDD] rounded-xl px-4 py-3 text-base"
            placeholder="New room number"
            value={destRoom}
            onChange={e => { setDestRoom(e.target.value.toUpperCase()); setRoomCheck(null); setRoomCheckError("") }}
          />
          <button
            type="button"
            onClick={handleCheckRoom}
            disabled={roomCheckLoading || !destRoom.trim()}
            className="px-4 py-3 rounded-xl bg-brand-pink text-white font-bold text-sm disabled:opacity-50"
          >
            {roomCheckLoading ? "..." : "Check"}
          </button>
        </div>
        {roomCheckError && <p className="text-sm text-red-500">{roomCheckError}</p>}
        {roomCheck && roomCheck.is_available && (
          <div className="rounded-xl bg-green-50 border border-green-200 px-4 py-3">
            <p className="text-sm font-semibold text-green-700">
              Room {roomCheck.room_number} — {roomCheck.free_beds} bed{roomCheck.free_beds !== 1 ? "s" : ""} free
              {roomCheck.occupants.length > 0 && ` (sharing with ${roomCheck.occupants.map(o => o.name).join(", ")})`}
            </p>
          </div>
        )}
        {transferError && <p className="text-sm text-red-500">{transferError}</p>}
        <button
          type="button"
          onClick={() => setTransferStep(2)}
          disabled={!roomCheck?.is_available}
          className="w-full py-3 rounded-2xl bg-brand-pink text-white font-bold disabled:opacity-40"
        >
          Next
        </button>
      </div>
    )}

    {/* Step 2: Rent */}
    {transferStep === 2 && (
      <div className="space-y-3">
        <label className="text-sm text-ink-muted">Rent for new room <span className="text-ink">(current: ₹{Number(original?.rent ?? 0).toLocaleString("en-IN")}/mo)</span></label>
        <input
          type="number"
          className="w-full border border-[#E2DEDD] rounded-xl px-4 py-3 text-base"
          value={transferNewRent}
          onChange={e => setTransferNewRent(e.target.value)}
        />
        <div className="flex gap-2">
          <button type="button" onClick={() => setTransferStep(1)} className="flex-1 py-3 rounded-2xl border border-[#E2DEDD] text-ink font-bold">Back</button>
          <button type="button" onClick={() => setTransferStep(3)} disabled={!transferNewRent} className="flex-1 py-3 rounded-2xl bg-brand-pink text-white font-bold disabled:opacity-40">Next</button>
        </div>
      </div>
    )}

    {/* Step 3: Extra deposit */}
    {transferStep === 3 && (
      <div className="space-y-3">
        <label className="text-sm text-ink-muted">Additional deposit to collect <span className="text-ink">(current: ₹{Number(original?.security_deposit ?? 0).toLocaleString("en-IN")})</span></label>
        <input
          type="number"
          className="w-full border border-[#E2DEDD] rounded-xl px-4 py-3 text-base"
          value={transferExtraDeposit}
          onChange={e => setTransferExtraDeposit(e.target.value)}
          placeholder="0 = no change"
        />
        <div className="flex gap-2">
          <button type="button" onClick={() => setTransferStep(2)} className="flex-1 py-3 rounded-2xl border border-[#E2DEDD] text-ink font-bold">Back</button>
          <button type="button" onClick={() => setTransferStep(4)} className="flex-1 py-3 rounded-2xl bg-brand-pink text-white font-bold">Review</button>
        </div>
      </div>
    )}

    {/* Step 4: Confirm */}
    {transferStep === 4 && (
      <div className="space-y-3">
        {(() => {
          const rentChanged = Number(transferNewRent) !== original?.rent
          const depositAmt = Number(transferExtraDeposit) || 0
          const fields = [
            { label: "Room", value: `${original?.room_number} → ${roomCheck?.room_number}`, highlight: true },
            { label: "Rent", value: rentChanged
              ? `₹${Number(original?.rent).toLocaleString("en-IN")} → ₹${Number(transferNewRent).toLocaleString("en-IN")}/mo`
              : `₹${Number(transferNewRent).toLocaleString("en-IN")}/mo (no change)`,
              highlight: rentChanged },
            ...(depositAmt > 0 ? [{ label: "Extra deposit", value: `₹${depositAmt.toLocaleString("en-IN")}` }] : []),
          ]
          return (
            <>
              {fields.map(f => (
                <div key={f.label} className="flex justify-between py-2 border-b border-[#F0EDE9]">
                  <span className="text-sm text-ink-muted">{f.label}</span>
                  <span className={`text-sm font-semibold ${f.highlight ? "text-brand-pink font-extrabold" : "text-ink"}`}>{f.value}</span>
                </div>
              ))}
            </>
          )
        })()}
        {transferError && <p className="text-sm text-red-500">{transferError}</p>}
        <div className="flex gap-2 pt-2">
          <button type="button" onClick={() => setTransferStep(3)} className="flex-1 py-3 rounded-2xl border border-[#E2DEDD] text-ink font-bold">Back</button>
          <button
            type="button"
            onClick={handleTransferConfirm}
            disabled={transferSubmitting}
            className="flex-1 py-3 rounded-2xl bg-brand-pink text-white font-bold disabled:opacity-50"
          >
            {transferSubmitting ? "Transferring..." : "Confirm Transfer"}
          </button>
        </div>
      </div>
    )}
  </div>
)}

{/* Transfer success banner */}
{transferSuccess && (
  <div className="mt-4 rounded-2xl bg-green-50 border border-green-200 px-5 py-4 text-center">
    <p className="font-bold text-green-700">Room transferred successfully</p>
    <button type="button" onClick={resetTransferPanel} className="mt-2 text-sm text-ink-muted underline">Done</button>
  </div>
)}
```

- [ ] **Step 5: Build and test in browser**

```bash
cd web && npm run build 2>&1 | tail -20
```

Expected: build succeeds with no TypeScript errors.

Start dev server: `npm run dev`

Open `http://localhost:3000/tenants/<tenancy_id>/edit` in browser.

Test the golden path:
1. Click "Transfer Room"
2. Enter a valid room number → click Check → green availability shown
3. Click Next → adjust rent → Next
4. Enter extra deposit (or leave 0) → Review
5. Confirm → success banner appears, room number in header updates

Test error path:
1. Enter a full room → Check → red error shown, Next disabled
2. Enter non-existent room → Check → 404 error shown

- [ ] **Step 6: Commit**

```bash
git add web/app/tenants/
git commit -m "feat(room-transfer): add Transfer Room 4-step panel to tenant edit page"
```

---

## Task 7: Deploy and verify end-to-end

- [ ] **Step 1: Run golden test suite (bot must not regress)**

```bash
# API must be running with TEST_MODE=1
TEST_MODE=1 venv/Scripts/python main.py &
venv/Scripts/python tests/eval_golden.py 2>&1 | tail -20
```

Expected: pass rate same as baseline (no regression from the bot refactor).

- [ ] **Step 2: Push and deploy**

```bash
git push origin master
ssh kozzy "cd /opt/pg-accountant && git pull && systemctl restart pg-accountant && systemctl restart kozzy-pwa"
```

- [ ] **Step 3: Smoke-test on live VPS**

1. WhatsApp: send "transfer room [real tenant] to [real room]" → confirm bot flow still works
2. PWA: open tenant edit → Transfer Room → complete full flow on a test tenancy
3. Check Google Sheet: TENANTS tab + monthly tab should reflect the new room

- [ ] **Step 4: Final commit — update changelog and pending tasks**

```bash
# Update docs/CHANGELOG.md with this session's changes
# Update memory/project_pending_tasks.md
git add docs/CHANGELOG.md memory/project_pending_tasks.md
git commit -m "docs: update changelog and pending tasks for room transfer feature"
git push origin master
```
