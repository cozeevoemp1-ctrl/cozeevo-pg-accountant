# Room Transfer — Design Spec
**Date:** 2026-04-29  
**Status:** Approved

## Problem
Tenant management PWA has no room transfer capability. The WhatsApp bot has a full `ROOM_TRANSFER` flow but its DB write logic is inline in `owner_handler.py`. Both need to share identical behavior.

## Solution
Extract the bot's transfer logic into a shared service (`services/room_transfer.py`). Both the bot handler and a new PWA API endpoint call this service. One code path — no drift, no confusion.

---

## Architecture

```
services/room_transfer.py          ← NEW: single source of truth
  execute_room_transfer(
    tenancy_id, to_room_number,
    new_rent, extra_deposit,
    changed_by, source, session
  ) → dict

owner_handler.py                   ← UPDATED: _do_room_transfer calls execute_room_transfer()
POST /api/v2/app/tenants/{id}/transfer-room  ← NEW: calls execute_room_transfer()
GET  /api/v2/app/rooms/check       ← NEW: availability check
web/app/tenants/[tenancy_id]/edit  ← UPDATED: Transfer Room button + stepped panel
```

---

## Shared Service: `services/room_transfer.py`

**Function:** `execute_room_transfer(tenancy_id, to_room_number, new_rent, extra_deposit, changed_by, source, session)`

**Steps (mirrors current bot logic exactly):**
1. Lookup new room by `room_number` — 404 if not found
2. Occupancy check: count active monthly tenants + active daywise stays vs `room.max_occupancy` — error if full (same message format as bot)
3. DB writes (all in the passed session):
   - `tenancy.room_id = new_room.id`
   - `tenancy.agreed_rent = new_rent`
   - If `new_rent` changed: insert `RentRevision(old_rent, new_rent, effective_date=today, changed_by, source)`
   - If `extra_deposit > 0`: `tenancy.security_deposit += extra_deposit`
   - Update current month `RentSchedule.rent_due` if a schedule row exists
   - Insert `AuditLog(entity_type="tenancy", field="room_id", old_value=from_room, new_value=to_room, source=source)`
4. Sheet sync (fire-and-forget):
   - `update_tenants_tab_field(old_room, tenant_name, "room", new_room_number)`
   - If rent changed: `update_tenants_tab_field(new_room, tenant_name, "agreed_rent", new_rent)`
   - `trigger_monthly_sheet_sync(month, year)`
5. Return `{ success: True, message: "...", from_room, to_room, new_rent, extra_deposit }`

**Error returns** (not exceptions): `{ success: False, message: "Room 405 is full (2/2 beds): ..." }`

---

## New API Endpoints

### `GET /api/v2/app/rooms/check?room=XXX`
Checks if a room exists and has free beds.

**Response:**
```json
{
  "room_number": "405",
  "max_occupancy": 2,
  "free_beds": 1,
  "is_available": true,
  "occupants": [{"name": "Raj Kumar", "tenancy_id": 42}]
}
```
Returns 404 if room doesn't exist or is inactive.

### `POST /api/v2/app/tenants/{tenancy_id}/transfer-room`
Executes the transfer after user confirms.

**Request body:**
```json
{
  "to_room_number": "405",
  "new_rent": 15000,
  "extra_deposit": 2000
}
```

**Response (success):**
```json
{
  "success": true,
  "message": "Raj Kumar transferred from 302 → 405",
  "from_room": "302",
  "to_room": "405",
  "new_rent": 15000,
  "extra_deposit": 2000
}
```

**Response (failure — room full):**
```json
{
  "success": false,
  "message": "Room 405 is full (2/2 beds): Priya Sharma, Anjali Rao"
}
```
Returns HTTP 200 with `success: false` (not 4xx) so the frontend can display the message inline without error handling complexity.

---

## Bot Handler Update: `owner_handler.py`

Replace the body of `_do_room_transfer(action_data, session)` with a call to `execute_room_transfer()`. The pending-state multi-step flow (`ROOM_TRANSFER`, `ROOM_TRANSFER_WHO`, `ROOM_TRANSFER_DEST`) is **unchanged** — only the final DB commit step is extracted.

Before (inline DB writes ~60 lines):
```python
async def _do_room_transfer(action_data, session):
    tenancy.room_id = ...
    tenancy.agreed_rent = ...
    # audit log, sheet sync inline ...
```

After:
```python
async def _do_room_transfer(action_data, session):
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

---

## Frontend: Tenant Edit Page

**Entry point:** "Transfer Room" button in the edit page header/footer (distinct from the Save button).

**4-step inline panel** (no page navigation, panel slides in below the button):

### Step 1 — Destination Room
- Text input: room number
- "Check availability" button → calls `GET /rooms/check?room=XXX`
- Shows result inline:
  - Available: green — "Room 405 — 1 bed free (Raj Kumar sharing)"
  - Full: red — "Room 405 is full (2/2 beds)"
  - Not found: red — "Room 405 not found"
- Next button enabled only when a valid available room is selected

### Step 2 — Rent
- Number input pre-filled with current `agreed_rent`
- Label: "Rent for new room (current: ₹X,XXX/mo)"
- User changes or keeps — both are valid

### Step 3 — Extra Deposit
- Number input pre-filled with `0`
- Label: "Additional deposit to collect (current deposit: ₹X,XXX)"
- `0` = no change, skip

### Step 4 — Confirm
- `ConfirmationCard` (existing component) showing:
  - Room: `302 → 405`
  - Rent: `₹14,000 → ₹15,000/mo` (or "no change" if same)
  - Extra deposit: `₹2,000` (or hidden if 0)
- "Confirm Transfer" button → POST `/transfer-room`
- On success: close panel, refresh tenant header to show new room, show toast
- On failure: show error message inline, stay on Step 1

**Cancel:** available at every step — closes panel, no changes made.

---

## Data Consistency Rules (matching bot)

| Rule | Value |
|---|---|
| Deposit change | Incremental (`+= extra_deposit`), never overwrites total |
| Rent change | Absolute new value; RentRevision inserted if different |
| RentSchedule | Current month row updated if exists |
| AuditLog | Always written, `source` = "whatsapp" or "pwa" |
| Sheet sync | fire-and-forget; both TENANTS tab + monthly tab |
| Availability check | max_occupancy vs (active monthly + active daywise today) |

---

## Out of Scope
- Moving tenant to a room with a different stay type (daily vs monthly) — not handled
- Partial-month proration on room change — not handled (same as bot)
- Bulk transfers — not needed
