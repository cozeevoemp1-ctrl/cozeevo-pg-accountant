# Day-wise Handler Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every bot handler (checkout, update checkin/checkout date, query checkins/checkouts) must work identically for day-wise guests — both bot-added (`tenancies` with `stay_type=daily`) and historically-imported (`daywise_stays` table).

**Architecture:** Day-wise guests exist in two tables. Bot-added guests live in `tenancies` (`stay_type=daily`) and are already found by name/room searches — they only need sheet-sync fixes and RECORD_CHECKOUT bypass. Historical guests live in `daywise_stays` (no FK to `Tenant`) and are invisible to all current searches — they need new fallback search helpers and direct-table write paths. The pending-action `action_data` dict carries `record_type: "daywise_stays"` + `stay_id` to route daywise_stays confirmations separately from tenancy confirmations.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, Supabase PostgreSQL, gsheets integration (`trigger_daywise_sheet_sync`)

---

## File Map

| File | Changes |
|---|---|
| `src/services/occupants.py` | Add `stay_type == monthly` filter to first query (dedup fix) |
| `src/whatsapp/handlers/_shared.py` | Add `_find_daywise_by_name`, `_find_daywise_by_room`, `_make_daywise_choices` |
| `src/whatsapp/handlers/owner_handler.py` | Fix 3 `_do_*` functions + pending handlers + 2 query handlers + 3 `_prompt` fallbacks + 3 new `_do_daywise_*` functions |
| `src/whatsapp/intent_detector.py` | Extend UPDATE_CHECKOUT_DATE regex to match "change room 218 checkout date" |

---

## Task 1: Fix `find_occupants` dedup — `src/services/occupants.py`

**Files:** Modify `src/services/occupants.py:148-163`

The first query in `find_occupants` has no `stay_type` filter, so active day-stay tenancies appear twice (once as `kind="tenancy"`, once as `kind="daystay"`). Fix: restrict first query to monthly tenancies only.

- [ ] **Step 1: Apply fix**

In `src/services/occupants.py`, find the first query block (starts around line 148) and add `.where(Tenancy.stay_type == StayType.monthly)`:

```python
# ── Long-term tenancies ──
q = (
    select(Tenant, Tenancy, Room)
    .join(Tenancy, Tenancy.tenant_id == Tenant.id)
    .join(Room, Room.id == Tenancy.room_id)
    .where(Tenancy.stay_type == StayType.monthly)   # ← ADD THIS LINE
)
if active_only:
    q = q.where(Tenancy.status == TenancyStatus.active)
```

- [ ] **Step 2: Verify**

```bash
cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant"
python -c "
import asyncio
from src.database.connection import get_async_session
from src.services.occupants import find_occupants
async def test():
    async with get_async_session() as s:
        occs = await find_occupants(s, active_only=False)
        ids = [o.id for o in occs]
        assert len(ids) == len(set(ids)), 'DUPLICATE IDs FOUND'
        print(f'OK — {len(occs)} occupants, no duplicates')
asyncio.run(test())
"
```

Expected: `OK — N occupants, no duplicates`

- [ ] **Step 3: Commit**

```bash
git add src/services/occupants.py
git commit -m "fix(occupants): exclude stay_type=daily from long-term query to prevent duplicate day-stay rows"
```

---

## Task 2: Add day-wise search helpers — `src/whatsapp/handlers/_shared.py`

**Files:** Modify `src/whatsapp/handlers/_shared.py`

Add three helpers for searching `daywise_stays` and building choice dicts compatible with the existing pending-action framework.

- [ ] **Step 1: Add imports and helpers at end of `_shared.py`**

At the bottom of `src/whatsapp/handlers/_shared.py`, add:

```python
# ── Day-wise stay search helpers ─────────────────────────────────────────────

async def _find_daywise_by_name(name: str, session: AsyncSession) -> list:
    """Search daywise_stays by guest_name (case-insensitive substring)."""
    from src.database.models import DaywiseStay
    first_word = name.split()[0] if name else name
    result = await session.execute(
        select(DaywiseStay)
        .where(DaywiseStay.guest_name.ilike(f"{first_word}%"))
        .order_by(DaywiseStay.checkin_date.desc())
        .limit(5)
    )
    rows = result.scalars().all()
    if not rows and len(name) >= 3:
        result = await session.execute(
            select(DaywiseStay)
            .where(DaywiseStay.guest_name.ilike(f"%{name}%"))
            .order_by(DaywiseStay.checkin_date.desc())
            .limit(5)
        )
        rows = result.scalars().all()
    return list(rows)


async def _find_daywise_by_room(room: str, session: AsyncSession) -> list:
    """Search daywise_stays by room_number (case-insensitive)."""
    from src.database.models import DaywiseStay
    result = await session.execute(
        select(DaywiseStay)
        .where(DaywiseStay.room_number.ilike(f"%{room}%"))
        .order_by(DaywiseStay.checkin_date.desc())
        .limit(5)
    )
    return list(result.scalars().all())


def _make_daywise_choices(rows) -> list[dict]:
    """Convert DaywiseStay rows into numbered choice dicts.

    Uses stay_id + record_type so pending handlers can route to daywise_stays
    write paths instead of tenancy write paths.
    """
    choices = []
    for i, ds in enumerate(rows[:5], 1):
        checkin_str = ds.checkin_date.strftime("%d %b") if ds.checkin_date else "?"
        checkout_str = ds.checkout_date.strftime("%d %b") if ds.checkout_date else "?"
        choices.append({
            "seq": i,
            "stay_id": ds.id,
            "record_type": "daywise_stays",
            "label": f"{ds.guest_name} (Room {ds.room_number}, {checkin_str}–{checkout_str})",
        })
    return choices
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from src.whatsapp.handlers._shared import _find_daywise_by_name, _find_daywise_by_room, _make_daywise_choices; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/whatsapp/handlers/_shared.py
git commit -m "feat(daywise): add _find_daywise_by_name, _find_daywise_by_room, _make_daywise_choices helpers"
```

---

## Task 3: Fix `_do_checkout` sheet sync for day-wise tenancies — `owner_handler.py`

**Files:** Modify `src/whatsapp/handlers/owner_handler.py` around line 4305 (`_do_checkout`)

When a `tenancy` with `stay_type=daily` checks out, the current code calls `gsheets.record_checkout` which writes to the monthly sheet tab. Day-wise guests must use `trigger_daywise_sheet_sync()` instead.

- [ ] **Step 1: Locate and update `_do_checkout` sheet-sync block**

Find the `# ── Google Sheets write-back (fire-and-forget) ──` block inside `_do_checkout` (around line 4305). Replace it:

```python
    # ── Google Sheets write-back (fire-and-forget) ──
    gsheets_note = ""
    room_obj = await session.get(Room, tenancy.room_id) if tenancy.room_id else None
    is_daywise_stay = tenancy.stay_type == StayType.daily
    if is_daywise_stay:
        try:
            from src.integrations import gsheets as _gs
            _gs.trigger_daywise_sheet_sync()
            gsheets_note = "\nSheet updated: DAY WISE"
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning("trigger_daywise_sheet_sync failed: %s", e)
    elif room_obj:
        try:
            from src.integrations.gsheets import record_checkout as gsheets_checkout
            notice_str = tenancy.notice_date.strftime("%d/%m/%Y") if tenancy.notice_date else None
            gs_r = await gsheets_checkout(room_obj.room_number, tenant_name, notice_str)
            if gs_r.get("success"):
                gsheets_note = "\nSheet updated: EXIT"
            elif gs_r.get("error"):
                import logging as _log
                _log.getLogger(__name__).warning("GSheets checkout: %s", gs_r["error"])
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).error("GSheets checkout failed: %s", e)
            try:
                from src.integrations.gsheets import _queue_failed_write
                _queue_failed_write("record_checkout", {
                    "room_number": room_obj.room_number, "tenant_name": tenant_name,
                    "notice_date": tenancy.notice_date.strftime("%d/%m/%Y") if tenancy.notice_date else None,
                })
            except Exception:
                pass
```

- [ ] **Step 2: Verify import**

```bash
python -c "from src.whatsapp.handlers.owner_handler import _do_checkout; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "fix(checkout): use trigger_daywise_sheet_sync for day-wise tenancy checkout instead of monthly record_checkout"
```

---

## Task 4: Bypass RECORD_CHECKOUT checklist for day-wise tenancies — `owner_handler.py`

**Files:** Modify `src/whatsapp/handlers/owner_handler.py` around line 2803

Monthly checkout goes through a multi-step RECORD_CHECKOUT checklist (cupboard key, ID card, etc). Day-wise guests skip this — go straight to `_do_checkout`.

- [ ] **Step 1: Update pending CHECKOUT/SCHEDULE_CHECKOUT handler**

Find the block at line ~2803:
```python
if chosen is not None and pending.intent in ("CHECKOUT", "SCHEDULE_CHECKOUT"):
```

Insert a day-wise bypass BEFORE the existing `if checkout_date_val > date.today():` check:

```python
    if chosen is not None and pending.intent in ("CHECKOUT", "SCHEDULE_CHECKOUT"):
        date_str = action_data.get("checkout_date", "")
        try:
            checkout_date_val = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            checkout_date_val = date.today()

        # ── daywise_stays record (historical import) ──────────────────────
        if chosen.get("record_type") == "daywise_stays":
            return await _do_checkout_daywise(chosen["stay_id"], session)

        # ── tenancy day-wise (bot-added, stay_type=daily) ──────────────────
        tenancy_check = await session.get(Tenancy, chosen["tenancy_id"])
        if tenancy_check and tenancy_check.stay_type == StayType.daily:
            return await _do_checkout(
                tenancy_id=chosen["tenancy_id"],
                tenant_name=chosen["label"],
                checkout_date_val=checkout_date_val,
                session=session,
            )

        if checkout_date_val > date.today():
            # Future date → schedule only, no checklist yet
            return await _do_checkout(
                tenancy_id=chosen["tenancy_id"],
                tenant_name=chosen["label"],
                checkout_date_val=checkout_date_val,
                session=session,
            )

        # Today/past → start checklist (monthly tenants only)
        # ... rest of existing RECORD_CHECKOUT code unchanged ...
```

- [ ] **Step 2: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "fix(checkout): bypass RECORD_CHECKOUT checklist for day-wise tenancies"
```

---

## Task 5: Add `_do_checkout_daywise` for `daywise_stays` records — `owner_handler.py`

**Files:** Modify `src/whatsapp/handlers/owner_handler.py` (add new function near `_do_checkout`)

- [ ] **Step 1: Add `_do_checkout_daywise` after `_do_checkout`**

Add directly after the end of `_do_checkout` function (around line 4395):

```python
async def _do_checkout_daywise(stay_id: int, session: AsyncSession) -> str:
    """Mark a daywise_stays record as EXIT."""
    from src.database.models import DaywiseStay
    ds = await session.get(DaywiseStay, stay_id)
    if not ds:
        return "Day-stay record not found."
    ds.status = "EXIT"
    await session.commit()
    from src.integrations import gsheets as _gs
    _gs.trigger_daywise_sheet_sync()
    checkout_str = ds.checkout_date.strftime("%d %b %Y") if ds.checkout_date else "not set"
    return (
        f"*Checkout recorded — {ds.guest_name}*\n"
        f"Room: {ds.room_number}\n"
        f"Date: {checkout_str}\n\n"
        "Sheet updated: DAY WISE"
    )
```

- [ ] **Step 2: Add `daywise_stays` fallback in `_checkout_prompt`**

In `_checkout_prompt`, find the `if len(rows) == 0:` block (around line 4178) and replace:

```python
    if len(rows) == 0:
        # Fallback: search daywise_stays
        from src.whatsapp.handlers._shared import _find_daywise_by_name, _find_daywise_by_room, _make_daywise_choices
        dw_rows = await _find_daywise_by_name(name, session) if name else []
        if not dw_rows and room:
            dw_rows = await _find_daywise_by_room(room, session)
        if dw_rows:
            choices = _make_daywise_choices(dw_rows)
            intent_type = "SCHEDULE_CHECKOUT" if is_future_checkout else "CHECKOUT"
            action_data = {"name_raw": search_term, "checkout_date": date_str}
            await _save_pending(ctx.phone, intent_type, action_data, choices, session, state="awaiting_choice")
            if len(dw_rows) == 1:
                ds = dw_rows[0]
                checkin_str = ds.checkin_date.strftime("%d %b %Y") if ds.checkin_date else "?"
                date_line = f"\nCheckout date: {checkout_date_val.strftime('%d %b %Y')}" if checkout_date_val else ""
                return (
                    f"Confirm checkout for *{ds.guest_name}* (Room {ds.room_number})?\n\n"
                    f"Checkin: {checkin_str}{date_line}\n\n"
                    f"Reply *1* to confirm."
                )
            label = f"checkout on {checkout_date_val.strftime('%d %b %Y')}" if checkout_date_val else "checkout"
            return _format_choices_message(search_term, choices, label)
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)
```

- [ ] **Step 3: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "feat(checkout): add daywise_stays fallback in checkout prompt + _do_checkout_daywise handler"
```

---

## Task 6: Fix `_do_update_checkout_date` sheet sync — `owner_handler.py`

**Files:** Modify `src/whatsapp/handlers/owner_handler.py:4855-4862` (`_do_update_checkout_date`)

Currently calls `sync_tenant_all_fields` (monthly sync) for all tenancies. Day-wise must use `trigger_daywise_sheet_sync`.

- [ ] **Step 1: Update sheet-sync block in `_do_update_checkout_date`**

Find the sheet sync block (around line 4855):
```python
    try:
        import asyncio as _aio
        from src.integrations.gsheets import sync_tenant_all_fields as _sync
        _aio.create_task(_sync(tenancy.tenant_id))
    except Exception:
        pass  # fire-and-forget; DB is authoritative
```

Replace with:

```python
    if tenancy.stay_type == StayType.daily:
        try:
            from src.integrations import gsheets as _gs
            _gs.trigger_daywise_sheet_sync()
        except Exception:
            pass
    else:
        try:
            import asyncio as _aio
            from src.integrations.gsheets import sync_tenant_all_fields as _sync
            _aio.create_task(_sync(tenancy.tenant_id))
        except Exception:
            pass
```

- [ ] **Step 2: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "fix(update-checkout-date): use trigger_daywise_sheet_sync for day-wise tenancy instead of sync_tenant_all_fields"
```

---

## Task 7: Add `_do_update_daywise_checkout_date` + fallback in `_update_checkout_date` — `owner_handler.py`

**Files:** Modify `src/whatsapp/handlers/owner_handler.py`

- [ ] **Step 1: Add `_do_update_daywise_checkout_date` after `_do_update_checkout_date`**

Add directly after `_do_update_checkout_date` ends (around line 4870):

```python
async def _do_update_daywise_checkout_date(
    stay_id: int,
    guest_name: str,
    new_checkout_str: str,
    session: AsyncSession,
) -> str:
    """Update checkout_date on a daywise_stays record."""
    from src.database.models import DaywiseStay
    ds = await session.get(DaywiseStay, stay_id)
    if not ds:
        return "Day-stay record not found."
    try:
        new_checkout = date.fromisoformat(new_checkout_str)
    except (ValueError, TypeError):
        return "Invalid date. Please try again."
    if new_checkout <= ds.checkin_date:
        return (
            f"Cannot update: new checkout {new_checkout.strftime('%d %b %Y')} is on/before "
            f"checkin {ds.checkin_date.strftime('%d %b %Y')}."
        )
    old_str = ds.checkout_date.strftime("%d %b %Y") if ds.checkout_date else "not set"
    ds.checkout_date = new_checkout
    ds.num_days = (new_checkout - ds.checkin_date).days
    await session.commit()
    from src.integrations import gsheets as _gs
    _gs.trigger_daywise_sheet_sync()
    return (
        f"*Checkout date updated — {guest_name}*\n"
        f"Was: {old_str}\n"
        f"Now: {new_checkout.strftime('%d %b %Y')}\n\n"
        "Send *report* to verify."
    )
```

- [ ] **Step 2: Add `daywise_stays` fallback in `_update_checkout_date`**

In `_update_checkout_date` (around line 4789), find `if len(rows) == 0:` and replace:

```python
    if len(rows) == 0:
        from src.whatsapp.handlers._shared import _find_daywise_by_name, _find_daywise_by_room, _make_daywise_choices
        dw_rows = await _find_daywise_by_name(name, session) if name else []
        if not dw_rows and room:
            dw_rows = await _find_daywise_by_room(room, session)
        if dw_rows:
            choices = _make_daywise_choices(dw_rows)
            dw_action = {"name_raw": search_term, "new_checkout": date_str, "record_type": "daywise_stays"}
            if len(dw_rows) == 1:
                ds = dw_rows[0]
                old_str = ds.checkout_date.strftime("%d %b %Y") if ds.checkout_date else "not set"
                if date_str:
                    await _save_pending(ctx.phone, "UPDATE_CHECKOUT_DATE", dw_action, choices, session)
                    new_checkout = date.fromisoformat(date_str)
                    return (
                        f"Update checkout for *{ds.guest_name}* (Room {ds.room_number})?\n\n"
                        f"Current: {old_str}\n"
                        f"New:     {new_checkout.strftime('%d %b %Y')}\n\n"
                        f"Reply *1* to confirm."
                    )
                else:
                    await _save_pending(ctx.phone, "UPDATE_CHECKOUT_DATE_ASK", dw_action, choices, session)
                    return (
                        f"*{ds.guest_name}* (Room {ds.room_number})\n"
                        f"Current checkout: {old_str}\n\n"
                        f"*New checkout date?* (e.g. *15 April* or *15/04/2026*)"
                    )
            await _save_pending(ctx.phone, "UPDATE_CHECKOUT_DATE", dw_action, choices, session)
            action_label = f"update checkout to {date_str}" if date_str else "update checkout date"
            return _format_choices_message(search_term, choices, action_label)
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)
```

- [ ] **Step 3: Branch pending handlers to call daywise path**

**In the `UPDATE_CHECKOUT_DATE` choice-resolution handler** (around line 2885), add a branch at the top:

```python
    if chosen is not None and pending.intent == "UPDATE_CHECKOUT_DATE":
        if chosen.get("record_type") == "daywise_stays":
            new_checkout_str = action_data.get("new_checkout", "")
            if new_checkout_str:
                return await _do_update_daywise_checkout_date(
                    stay_id=chosen["stay_id"],
                    guest_name=chosen["label"],
                    new_checkout_str=new_checkout_str,
                    session=session,
                )
            # No date — ask for it
            from src.database.models import DaywiseStay
            ds = await session.get(DaywiseStay, chosen["stay_id"])
            old_str = ds.checkout_date.strftime("%d %b %Y") if (ds and ds.checkout_date) else "not set"
            action_data["stay_id"] = chosen["stay_id"]
            action_data["guest_name"] = chosen["label"]
            await _save_pending(pending.phone, "UPDATE_CHECKOUT_DATE_ASK", action_data, [], session)
            return (
                f"*{chosen['label']}*\n"
                f"Current checkout: {old_str}\n\n"
                f"*New checkout date?* (e.g. *15 April* or *15/04/2026*)"
            )
        # existing tenancy path below unchanged...
```

**In the `UPDATE_CHECKOUT_DATE_ASK` handler** (around line 1774), add a branch at the top:

```python
    if pending.intent == "UPDATE_CHECKOUT_DATE_ASK":
        from src.whatsapp.intent_detector import _extract_date_entity
        if is_negative(reply_text):
            return "Cancelled."
        date_iso = _extract_date_entity(reply_text.strip())
        if not date_iso:
            return "__KEEP_PENDING__Couldn't parse that date. Try: *15 April* or *15/04/2026*"
        if action_data.get("record_type") == "daywise_stays":
            stay_id = action_data.get("stay_id") or (choices[0].get("stay_id") if choices else None)
            guest_name = action_data.get("guest_name", action_data.get("name_raw", ""))
            if not stay_id:
                return "Something went wrong. Please try again: *change checkout date [Name] to [date]*"
            return await _do_update_daywise_checkout_date(stay_id, guest_name, date_iso, session)
        # existing tenancy path below unchanged...
```

- [ ] **Step 4: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "feat(update-checkout-date): add daywise_stays fallback search + _do_update_daywise_checkout_date + pending handler branches"
```

---

## Task 8: Fix `_do_update_checkin` sheet sync + add `daywise_stays` fallback — `owner_handler.py`

**Files:** Modify `src/whatsapp/handlers/owner_handler.py`

- [ ] **Step 1: Update sheet-sync block in `_do_update_checkin`** (around line 4743)

Find:
```python
    # Google Sheets write-back
    gsheets_note = ""
    try:
        room_obj = await session.get(Room, tenancy.room_id)
        if room_obj:
            from src.integrations.gsheets import update_checkin as gsheets_update_checkin
            gs_r = await gsheets_update_checkin(
                room_obj.room_number, tenant_name, new_checkin.strftime("%d/%m/%Y")
            )
            if gs_r.get("success"):
                gsheets_note = "\nSheet updated"
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).error("GSheets update_checkin failed: %s", e)
```

Replace with:

```python
    # Google Sheets write-back
    gsheets_note = ""
    if tenancy.stay_type == StayType.daily:
        try:
            from src.integrations import gsheets as _gs
            _gs.trigger_daywise_sheet_sync()
            gsheets_note = "\nSheet updated: DAY WISE"
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning("trigger_daywise_sheet_sync failed: %s", e)
    else:
        try:
            room_obj = await session.get(Room, tenancy.room_id)
            if room_obj:
                from src.integrations.gsheets import update_checkin as gsheets_update_checkin
                gs_r = await gsheets_update_checkin(
                    room_obj.room_number, tenant_name, new_checkin.strftime("%d/%m/%Y")
                )
                if gs_r.get("success"):
                    gsheets_note = "\nSheet updated"
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).error("GSheets update_checkin failed: %s", e)
```

Also update the return message — remove "Note: rent schedule rows are not auto-adjusted." for day-wise. Replace the final return:

```python
    if tenancy.stay_type == StayType.daily:
        return (
            f"*Checkin updated — {tenant_name}*\n"
            f"Was: {old_checkin.strftime('%d %b %Y')}\n"
            f"Now: {new_checkin.strftime('%d %b %Y')}"
            f"{gsheets_note}"
        )
    return (
        f"*Checkin updated — {tenant_name}*\n"
        f"Was: {old_checkin.strftime('%d %b %Y')}\n"
        f"Now: {new_checkin.strftime('%d %b %Y')}\n"
        f"{gsheets_note}\n\n"
        "Note: rent schedule rows are not auto-adjusted.\n"
        "Send *report* to verify dues."
    )
```

- [ ] **Step 2: Add `_do_update_daywise_checkin` function** (add after `_do_update_checkin`)

```python
async def _do_update_daywise_checkin(
    stay_id: int,
    guest_name: str,
    new_checkin_str: str,
    session: AsyncSession,
) -> str:
    """Update checkin_date on a daywise_stays record."""
    from src.database.models import DaywiseStay
    ds = await session.get(DaywiseStay, stay_id)
    if not ds:
        return "Day-stay record not found."
    try:
        new_checkin = date.fromisoformat(new_checkin_str)
    except (ValueError, TypeError):
        return "Invalid date. Please try again."
    if ds.checkout_date and new_checkin >= ds.checkout_date:
        return (
            f"Cannot update: new checkin {new_checkin.strftime('%d %b %Y')} is on/after "
            f"checkout {ds.checkout_date.strftime('%d %b %Y')}."
        )
    old_str = ds.checkin_date.strftime("%d %b %Y") if ds.checkin_date else "not set"
    ds.checkin_date = new_checkin
    if ds.checkout_date:
        ds.num_days = (ds.checkout_date - new_checkin).days
    await session.commit()
    from src.integrations import gsheets as _gs
    _gs.trigger_daywise_sheet_sync()
    return (
        f"*Checkin updated — {guest_name}*\n"
        f"Was: {old_str}\n"
        f"Now: {new_checkin.strftime('%d %b %Y')}"
    )
```

- [ ] **Step 3: Add `daywise_stays` fallback in `_update_checkin`** (around line 4573)

Find `if len(rows) == 0:` and replace:

```python
    if len(rows) == 0:
        from src.whatsapp.handlers._shared import _find_daywise_by_name, _find_daywise_by_room, _make_daywise_choices
        dw_rows = await _find_daywise_by_name(name, session) if name else []
        if not dw_rows and room:
            dw_rows = await _find_daywise_by_room(room, session)
        if dw_rows:
            choices = _make_daywise_choices(dw_rows)
            dw_action = {"name_raw": search_term, "new_checkin": date_str, "record_type": "daywise_stays"}
            if len(dw_rows) == 1:
                ds = dw_rows[0]
                if ds.checkout_date and new_checkin >= ds.checkout_date:
                    return (
                        f"Invalid: new checkin {new_checkin.strftime('%d %b %Y')} is on/after "
                        f"checkout {ds.checkout_date.strftime('%d %b %Y')}."
                    )
                await _save_pending(ctx.phone, "UPDATE_CHECKIN", dw_action, choices, session)
                return (
                    f"Update checkin for *{ds.guest_name}* (Room {ds.room_number})?\n\n"
                    f"Current: {ds.checkin_date.strftime('%d %b %Y') if ds.checkin_date else '?'}\n"
                    f"New:     {new_checkin.strftime('%d %b %Y')}\n\n"
                    f"Reply *1* to confirm."
                )
            await _save_pending(ctx.phone, "UPDATE_CHECKIN", dw_action, choices, session)
            return _format_choices_message(search_term, choices, f"update checkin to {new_checkin.strftime('%d %b %Y')}")
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)
```

- [ ] **Step 4: Branch pending `UPDATE_CHECKIN` handler** (around line 2877)

```python
    if chosen is not None and pending.intent == "UPDATE_CHECKIN":
        if chosen.get("record_type") == "daywise_stays":
            return await _do_update_daywise_checkin(
                stay_id=chosen["stay_id"],
                guest_name=chosen["label"],
                new_checkin_str=action_data.get("new_checkin", ""),
                session=session,
            )
        return await _do_update_checkin(
            tenancy_id=chosen["tenancy_id"],
            tenant_name=chosen["label"],
            new_checkin_str=action_data.get("new_checkin", ""),
            session=session,
        )
```

- [ ] **Step 5: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "feat(update-checkin): fix day-wise sheet sync + add daywise_stays fallback + _do_update_daywise_checkin"
```

---

## Task 9: Fix `_query_checkins` + `_query_checkouts` to include day-wise — `owner_handler.py`

**Files:** Modify `src/whatsapp/handlers/owner_handler.py:6781-6825`

Both query functions only look at `tenancies`. Add `daywise_stays` for the same month window and label those rows "(day-stay)".

- [ ] **Step 1: Replace `_query_checkins`**

```python
async def _query_checkins(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    from src.database.models import DaywiseStay
    today = date.today()
    month_start = today.replace(day=1)

    result = await session.execute(
        select(Tenant.name, Tenancy.checkin_date, Room.room_number, Tenancy.stay_type)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.checkin_date >= month_start,
            Tenancy.checkin_date <= today,
        )
        .order_by(Tenancy.checkin_date.desc())
    )
    rows = [(name, checkin, room_num, stay_type) for name, checkin, room_num, stay_type in result.all()]

    # Also include daywise_stays checkins this month
    dw_result = await session.execute(
        select(DaywiseStay.guest_name, DaywiseStay.checkin_date, DaywiseStay.room_number)
        .where(
            DaywiseStay.checkin_date >= month_start,
            DaywiseStay.checkin_date <= today,
        )
        .order_by(DaywiseStay.checkin_date.desc())
    )
    dw_rows = dw_result.all()

    if not rows and not dw_rows:
        return f"No new check-ins this month ({today.strftime('%B %Y')})."

    total = len(rows) + len(dw_rows)
    lines = [f"*Check-ins — {today.strftime('%B %Y')}* ({total} total)\n"]
    for name, checkin, room_num, stay_type in rows:
        tag = " (day-stay)" if stay_type and stay_type.value == "daily" else ""
        lines.append(f"• {name}{tag} (Room {room_num}) — {checkin.strftime('%d %b')}")
    for name, checkin, room_num in dw_rows:
        lines.append(f"• {name} (day-stay) (Room {room_num}) — {checkin.strftime('%d %b')}")
    return "\n".join(lines)
```

- [ ] **Step 2: Replace `_query_checkouts`**

```python
async def _query_checkouts(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    from src.database.models import DaywiseStay
    today = date.today()
    month_start = today.replace(day=1)

    result = await session.execute(
        select(Tenant.name, Tenancy.checkout_date, Room.room_number, Tenancy.stay_type)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status == TenancyStatus.exited,
            Tenancy.checkout_date >= month_start,
            Tenancy.checkout_date <= today,
        )
        .order_by(Tenancy.checkout_date.desc())
    )
    rows = [(name, checkout, room_num, stay_type) for name, checkout, room_num, stay_type in result.all()]

    # Also include daywise_stays checkouts this month
    dw_result = await session.execute(
        select(DaywiseStay.guest_name, DaywiseStay.checkout_date, DaywiseStay.room_number)
        .where(
            DaywiseStay.checkout_date >= month_start,
            DaywiseStay.checkout_date <= today,
        )
        .order_by(DaywiseStay.checkout_date.desc())
    )
    dw_rows = dw_result.all()

    if not rows and not dw_rows:
        return f"No check-outs this month ({today.strftime('%B %Y')})."

    total = len(rows) + len(dw_rows)
    lines = [f"*Check-outs — {today.strftime('%B %Y')}* ({total} total)\n"]
    for name, checkout, room_num, stay_type in rows:
        tag = " (day-stay)" if stay_type and stay_type.value == "daily" else ""
        lines.append(f"• {name}{tag} (Room {room_num}) — {checkout.strftime('%d %b')}")
    for name, checkout, room_num in dw_rows:
        chk = checkout.strftime("%d %b") if checkout else "?"
        lines.append(f"• {name} (day-stay) (Room {room_num}) — {chk}")
    return "\n".join(lines)
```

- [ ] **Step 3: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "feat(query): include daywise_stays in checkins/checkouts query with (day-stay) label"
```

---

## Task 10: Fix intent regex for UPDATE_CHECKOUT_DATE — `intent_detector.py`

**Files:** Modify `src/whatsapp/intent_detector.py:284`

"change room 218 checkout date" currently matches `QUERY_CHECKOUT_ROOM` because "room 218 checkout" appears mid-sentence. Extend UPDATE_CHECKOUT_DATE to catch the room-first form.

- [ ] **Step 1: Update the regex at line 284**

Find:
```python
    (re.compile(r"(?:update|correct|change|modify)\s+check.?out\s+(?:date\s+)?(?:for\s+|of\s+)?\w+|check.?out\s+date\s+(?:change|update|correct)|(?:change|update|correct)\s+(?:exit|leaving)\s+date|check.?out\s+was\s+(?:on\s+)?\d|\w+\s+check.?out\s+(?:was\s+)?(?:on\s+)?(?:\d|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))|actual\s+check.?out", re.I), "UPDATE_CHECKOUT_DATE", 0.94),
```

Replace with (adds `|(?:change|update|correct)\s+room\s+[\w-]+\s+check.?out` variant):

```python
    (re.compile(r"(?:update|correct|change|modify)\s+check.?out\s+(?:date\s+)?(?:for\s+|of\s+)?\w+|check.?out\s+date\s+(?:change|update|correct)|(?:change|update|correct)\s+(?:exit|leaving)\s+date|check.?out\s+was\s+(?:on\s+)?\d|\w+\s+check.?out\s+(?:was\s+)?(?:on\s+)?(?:\d|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))|actual\s+check.?out|(?:change|update|correct)\s+room\s+[\w-]+\s+check.?out", re.I), "UPDATE_CHECKOUT_DATE", 0.94),
```

This MUST be placed BEFORE the `QUERY_CHECKOUT_ROOM` rule (which is already the case at line 183 vs 284).

- [ ] **Step 2: Verify both forms match UPDATE_CHECKOUT_DATE and not QUERY_CHECKOUT_ROOM**

```bash
python -c "
import re
pattern = re.compile(r'(?:update|correct|change|modify)\s+check.?out\s+(?:date\s+)?(?:for\s+|of\s+)?\w+|check.?out\s+date\s+(?:change|update|correct)|(?:change|update|correct)\s+(?:exit|leaving)\s+date|check.?out\s+was\s+(?:on\s+)?\d|\w+\s+check.?out\s+(?:was\s+)?(?:on\s+)?(?:\d|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))|actual\s+check.?out|(?:change|update|correct)\s+room\s+[\w-]+\s+check.?out', re.I)
tests = [
    'change checkout date Raj to 15 April',
    'change room 218 checkout date',
    'update room 603 checkout to 30 Apr',
]
for t in tests:
    m = pattern.search(t)
    print(f'{\"MATCH\" if m else \"NO MATCH\":8} — {t}')
"
```

Expected: all three `MATCH`.

- [ ] **Step 3: Commit**

```bash
git add src/whatsapp/intent_detector.py
git commit -m "fix(intent): extend UPDATE_CHECKOUT_DATE regex to match 'change room N checkout' form"
```

---

## Task 11: End-to-end smoke test

- [ ] **Step 1: Start API in test mode**

```bash
TEST_MODE=1 venv/Scripts/python main.py
```

- [ ] **Step 2: Run golden test suite**

```bash
python tests/eval_golden.py
```

Expected: no regressions vs. baseline pass rate.

- [ ] **Step 3: Manual bot test — tenancy day-wise guest**

Using a test number, send each of these (replace "TestGuest" with a real `stay_type=daily` tenancy name from your DB):

```
checkout TestGuest
update checkin TestGuest to 20 Apr
change checkout date TestGuest to 30 Apr
who checked in this month
who checked out this month
```

For each: confirm the bot responds (not "no tenant found"), DB updates, and DAY WISE sheet refreshes.

- [ ] **Step 4: Manual bot test — daywise_stays historical guest**

Find a real guest name from `daywise_stays` table:
```sql
SELECT guest_name, room_number FROM daywise_stays LIMIT 5;
```

Send:
```
checkout <guest_name>
change checkout date <guest_name> to 30 Apr
update checkin <guest_name> to 15 Apr
```

Confirm bot responds with correct confirm prompt (not "no tenant found").

- [ ] **Step 5: Final push**

```bash
git push
```
