"""
Generic update handlers for tenant, room, and payment modifications.

Covers all field-level updates that a receptionist might need:
- Tenant: sharing_type, rent, phone, gender, deposit, food_plan
- Room: room_type, AC, maintenance mode
- Payment: correct mode

Each update follows: find entity → confirm change → apply.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Tenancy, Tenant, Room, TenancyStatus, Property,
    AuditLog, RentRevision, Staff,
)
from src.whatsapp.role_service import CallerContext
from src.whatsapp.handlers._shared import (
    _save_pending, _find_active_tenants_by_name, _find_similar_names,
    _make_choices, _format_choices_message, _format_no_match_message,
)


async def _disambiguate_or_pick(
    name: str,
    ctx: CallerContext,
    session: AsyncSession,
    field: str,
    new_value,
    verb: str,
):
    """Return (tenant, tenancy, room, early_reply).

    early_reply is non-None when the caller should return it immediately
    (no match / saved pending for disambiguation). Avoids the prior
    LIMIT-1 silent-pick bug: when >1 active tenants match the name, we
    save a FIELD_UPDATE_WHO pending and show the choice list instead of
    committing to the first match.
    """
    rows = await _find_active_tenants_by_name(name, session)
    if not rows:
        suggestions = await _find_similar_names(name, session)
        return None, None, None, _format_no_match_message(name, suggestions)
    if len(rows) > 1:
        choices = _make_choices(rows)
        await _save_pending(
            ctx.phone, "FIELD_UPDATE_WHO",
            {"field": field, "new_value": new_value},
            choices, session,
        )
        return None, None, None, _format_choices_message(name, choices, verb)
    tenant, tenancy, room = rows[0]
    return tenant, tenancy, room, None


# ── UPDATE SHARING TYPE ─────────────────────────────────────────────────────

async def update_sharing_type(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Change a tenant's sharing type (double/single/triple/premium)."""
    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    name = entities.get("name", "").strip()

    # Extract sharing type from message
    new_sharing = None
    for st in ("premium", "single", "double", "triple"):
        if st in desc.lower():
            new_sharing = st
            break

    if not new_sharing:
        return (
            "What sharing type? Reply with:\n"
            "*[Name] [sharing type]*\n"
            "Example: _Anukriti premium_ or _Raj double_"
        )

    # Find tenant
    if not name:
        # Try to extract name from description
        clean = re.sub(r"\b(change|update|set|modify|sharing|type|to|for|is|in|premium|single|double|triple)\b", "", desc, flags=re.I).strip()
        name = clean

    if not name or len(name) < 2:
        return "Which tenant? Reply: *[Name] [sharing type]*"

    tenant, tenancy, room, early = await _disambiguate_or_pick(
        name, ctx, session, "sharing_type", new_sharing,
        f"change sharing to {new_sharing}",
    )
    if early:
        return early

    raw = tenancy.sharing_type
    old_sharing = raw.value if hasattr(raw, "value") else (raw or "not set")
    if old_sharing == new_sharing:
        return f"*{tenant.name}* is already {new_sharing} sharing."

    room_label = f" (Room {room.room_number})" if room and hasattr(room, "room_number") else ""

    # Confirm
    action_data = {
        "tenancy_id": tenancy.id,
        "field": "sharing_type",
        "old_value": old_sharing,
        "new_value": new_sharing,
        "tenant_name": tenant.name,
    }
    choices = [
        {"seq": 1, "intent": "CONFIRM_UPDATE", "label": "Yes, update"},
        {"seq": 2, "intent": "CANCEL_UPDATE", "label": "No, cancel"},
    ]
    await _save_pending(ctx.phone, "CONFIRM_FIELD_UPDATE", action_data, choices, session)

    return (
        f"Update *{tenant.name}*{room_label}?\n\n"
        f"Sharing: {old_sharing} → *{new_sharing}*\n\n"
        f"Reply *1* to confirm or *2* to cancel."
    )


# ── UPDATE RENT ──────────────────────────────────────────────────────────────

async def update_rent(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Change a tenant's agreed rent amount."""
    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    name = entities.get("name", "").strip()
    amount = entities.get("amount")

    # Extract amount from description if not in entities
    if not amount:
        m = re.search(r"(\d[\d,]*)\s*(?:rs|rupees|/-|per\s+month)?", desc, re.I)
        if m:
            amount = m.group(1).replace(",", "")

    if not amount:
        return "What's the new rent? Reply: *[Name] rent [amount]*\nExample: _Raj rent 14000_"

    # Extract name from description
    if not name:
        clean = re.sub(r"\b(change|update|set|modify|rent|amount|to|for|is|rs|rupees|per|month|\d+)\b", "", desc, flags=re.I).strip()
        name = clean.strip(".,! ")

    if not name or len(name) < 2:
        return "Which tenant? Reply: *[Name] rent [amount]*"

    tenant, tenancy, room, early = await _disambiguate_or_pick(
        name, ctx, session, "agreed_rent", int(amount),
        f"change rent to Rs.{int(amount):,}",
    )
    if early:
        return early

    old_rent = int(tenancy.agreed_rent or 0)
    new_rent = int(amount)
    if old_rent == new_rent:
        return f"*{tenant.name}*'s rent is already Rs.{new_rent:,}."

    room_label = f" (Room {room.room_number})" if room and hasattr(room, "room_number") else ""

    action_data = {
        "tenancy_id": tenancy.id,
        "field": "agreed_rent",
        "old_value": old_rent,
        "new_value": new_rent,
        "tenant_name": tenant.name,
    }
    choices = [
        {"seq": 1, "intent": "CONFIRM_UPDATE", "label": "Yes, update"},
        {"seq": 2, "intent": "CANCEL_UPDATE", "label": "No, cancel"},
    ]
    await _save_pending(ctx.phone, "CONFIRM_FIELD_UPDATE", action_data, choices, session)

    return (
        f"Update *{tenant.name}*{room_label}?\n\n"
        f"Rent: Rs.{old_rent:,} → *Rs.{new_rent:,}*\n\n"
        f"Reply *1* to confirm or *2* to cancel."
    )


# ── UPDATE PHONE ─────────────────────────────────────────────────────────────

async def update_phone(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Change a tenant's phone number."""
    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    name = entities.get("name", "").strip()

    # Extract phone from description
    phone_match = re.search(r"(\+?\d{10,13})", desc)
    new_phone = phone_match.group(1) if phone_match else None

    if not new_phone:
        return "What's the new phone number? Reply: *[Name] phone [number]*"

    if not name:
        clean = re.sub(r"\b(change|update|set|modify|phone|number|mobile|cell|to|for|is|\+?\d{10,13})\b", "", desc, flags=re.I).strip()
        name = clean.strip(".,! ")

    if not name or len(name) < 2:
        return "Which tenant? Reply: *[Name] phone [number]*"

    tenant, tenancy, room, early = await _disambiguate_or_pick(
        name, ctx, session, "phone", new_phone,
        f"change phone to {new_phone}",
    )
    if early:
        return early

    old_phone = tenant.phone or "not set"

    action_data = {
        "tenant_id": tenant.id,
        "tenancy_id": tenancy.id,
        "field": "phone",
        "old_value": old_phone,
        "new_value": new_phone,
        "tenant_name": tenant.name,
        "table": "tenants",
    }
    choices = [
        {"seq": 1, "intent": "CONFIRM_UPDATE", "label": "Yes, update"},
        {"seq": 2, "intent": "CANCEL_UPDATE", "label": "No, cancel"},
    ]
    await _save_pending(ctx.phone, "CONFIRM_FIELD_UPDATE", action_data, choices, session)

    return (
        f"Update *{tenant.name}*'s phone?\n\n"
        f"Phone: {old_phone} → *{new_phone}*\n\n"
        f"Reply *1* to confirm or *2* to cancel."
    )


# ── UPDATE GENDER ────────────────────────────────────────────────────────────

async def update_gender(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Change a tenant's gender."""
    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    name = entities.get("name", "").strip()

    new_gender = None
    if re.search(r"\b(female|woman|girl|lady)\b", desc, re.I):
        new_gender = "female"
    elif re.search(r"\b(male|man|boy|gent)\b", desc, re.I):
        new_gender = "male"

    if not new_gender:
        return "Specify gender: *[Name] gender [male/female]*"

    if not name:
        clean = re.sub(r"\b(change|update|set|gender|to|for|is|male|female|woman|man|boy|girl)\b", "", desc, flags=re.I).strip()
        name = clean.strip(".,! ")

    if not name or len(name) < 2:
        return "Which tenant? Reply: *[Name] gender [male/female]*"

    tenant, tenancy, room, early = await _disambiguate_or_pick(
        name, ctx, session, "gender", new_gender,
        f"change gender to {new_gender}",
    )
    if early:
        return early

    old_gender = tenant.gender or "not set"

    action_data = {
        "tenant_id": tenant.id,
        "tenancy_id": tenancy.id,
        "field": "gender",
        "old_value": old_gender,
        "new_value": new_gender,
        "tenant_name": tenant.name,
        "table": "tenants",
    }
    choices = [
        {"seq": 1, "intent": "CONFIRM_UPDATE", "label": "Yes"},
        {"seq": 2, "intent": "CANCEL_UPDATE", "label": "Cancel"},
    ]
    await _save_pending(ctx.phone, "CONFIRM_FIELD_UPDATE", action_data, choices, session)

    return (
        f"Update *{tenant.name}*'s gender?\n\n"
        f"Gender: {old_gender} → *{new_gender}*\n\n"
        f"Reply *1* to confirm or *2* to cancel."
    )


# ── UPDATE DEPOSIT ───────────────────────────────────────────────────────────

async def update_deposit(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Change a tenant's security deposit amount."""
    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    name = entities.get("name", "").strip()

    m = re.search(r"(\d[\d,]*)", desc)
    amount = m.group(1).replace(",", "") if m else None

    if not amount:
        return "What's the deposit amount? Reply: *[Name] deposit [amount]*"

    if not name:
        clean = re.sub(r"\b(change|update|set|deposit|security|amount|to|for|is|rs|\d+)\b", "", desc, flags=re.I).strip()
        name = clean.strip(".,! ")

    if not name or len(name) < 2:
        return "Which tenant? Reply: *[Name] deposit [amount]*"

    tenant, tenancy, room, early = await _disambiguate_or_pick(
        name, ctx, session, "security_deposit", int(amount),
        f"change deposit to Rs.{int(amount):,}",
    )
    if early:
        return early

    old_dep = int(tenancy.security_deposit or 0)
    new_dep = int(amount)

    action_data = {
        "tenancy_id": tenancy.id,
        "field": "security_deposit",
        "old_value": old_dep,
        "new_value": new_dep,
        "tenant_name": tenant.name,
    }
    choices = [
        {"seq": 1, "intent": "CONFIRM_UPDATE", "label": "Yes"},
        {"seq": 2, "intent": "CANCEL_UPDATE", "label": "Cancel"},
    ]
    await _save_pending(ctx.phone, "CONFIRM_FIELD_UPDATE", action_data, choices, session)

    return (
        f"Update *{tenant.name}*'s deposit?\n\n"
        f"Deposit: Rs.{old_dep:,} → *Rs.{new_dep:,}*\n\n"
        f"Reply *1* to confirm or *2* to cancel."
    )


# ── UPDATE ROOM (AC, type, maintenance) ──────────────────────────────────────

# Staff-room toggle phrase patterns. UNMARK is checked before MARK so
# phrases like "not staff rooms 114 and 618" or "114 not staff room"
# (where "staff room" is a substring of "staff rooms" / "not staff room")
# don't hijack the MARK branch via substring match.
_STAFF_UNMARK_PATTERNS = (
    "not staff", "remove staff", "no staff", "unmark staff",
    "revenue room", "tenant room",
)
_STAFF_MARK_PATTERNS = (
    "staff room", "mark staff", "is staff", "make staff",
    "set staff", "staff yes",
)


def _is_confirm_choice(text: str) -> bool:
    """True if `text` is a confirm-style reply for a 1/2 or Yes/No prompt.

    Accepts "1", "yes"/"y" (any case), and common variants like "confirm",
    "ok", "sure". Returns False for cancel words, numeric "2", unknown
    text, and empty input (safe default: don't apply a change when the
    user's intent is unclear).
    """
    if not text:
        return False
    stripped = text.strip().rstrip(".").strip()
    if not stripped:
        return False
    if stripped == "1":
        return True
    from src.whatsapp.handlers._shared import is_affirmative
    return is_affirmative(stripped)


def _classify_staff_toggle(desc_lower: str) -> Optional[str]:
    """Return "mark" / "unmark" / None for a staff-room toggle phrase.

    `desc_lower` must be the message already lower-cased. UNMARK wins when
    both patterns appear so "not staff room" → unmark, not mark.
    """
    if any(p in desc_lower for p in _STAFF_UNMARK_PATTERNS):
        return "unmark"
    if any(p in desc_lower for p in _STAFF_MARK_PATTERNS):
        return "mark"
    return None


async def update_room(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Update room properties: AC, room type, maintenance mode, staff flag.

    Supports multi-room commands like "not staff rooms 114 and 618" —
    each room number in the message gets the same update applied.
    """
    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    room_num_entity = entities.get("room", "").strip()

    # Collect all candidate room numbers — multi-room commands like
    # "not staff rooms 114 and 618" should update both.
    nums = re.findall(r"\b([A-Za-z]?\d{1,4})\b", desc)
    # De-dupe preserving order
    seen = set()
    room_nums: list[str] = []
    for n in ([room_num_entity] + nums) if room_num_entity else nums:
        if n and n not in seen:
            seen.add(n); room_nums.append(n)

    if not room_nums:
        return "Which room? Reply: *room [number] [what to change]*"

    # Single-room path (original behaviour) — keep the old return
    # messages. Multi-room: loop and join.
    if len(room_nums) == 1:
        return await _update_single_room(room_nums[0], desc, ctx, session)

    results: list[str] = []
    for rn in room_nums:
        results.append(await _update_single_room(rn, desc, ctx, session))
    return "\n".join(results)


async def _update_single_room(room_num: str, desc: str, ctx: CallerContext, session: AsyncSession) -> str:
    """Apply one room-level update to one room."""
    room = await session.scalar(
        select(Room).where(Room.room_number == room_num, Room.active == True)
    )
    if not room:
        # Also check inactive rooms for maintenance-done
        room = await session.scalar(
            select(Room).where(Room.room_number == room_num)
        )
        if not room:
            return f"Room {room_num} not found."

    desc_lower = desc.lower()

    def _audit_room(field: str, old_val, new_val):
        session.add(AuditLog(
            changed_by=ctx.phone,
            entity_type="room",
            entity_id=room.id,
            entity_name=f"Room {room_num}",
            field=field,
            old_value=str(old_val),
            new_value=str(new_val),
            room_number=room_num,
            source="whatsapp",
        ))

    # AC toggle
    if "ac" in desc_lower:
        if any(w in desc_lower for w in ("add ac", "has ac", "ac on", "ac yes", "with ac")):
            old = room.has_ac
            room.has_ac = True
            _audit_room("has_ac", old, True)
            return f"Room *{room_num}* updated: AC = *Yes*"
        elif any(w in desc_lower for w in ("no ac", "remove ac", "ac off", "without ac")):
            old = room.has_ac
            room.has_ac = False
            _audit_room("has_ac", old, False)
            return f"Room *{room_num}* updated: AC = *No*"

    # Room type
    for rt in ("single", "double", "triple", "premium"):
        if rt in desc_lower and "type" in desc_lower:
            old = room.room_type
            room.room_type = rt
            _audit_room("room_type", old, rt)
            return f"Room *{room_num}* updated: type = *{rt}*"

    # Maintenance mode
    if "maintenance" in desc_lower:
        if any(w in desc_lower for w in ("under maintenance", "maintenance on", "close", "block")):
            old = room.active
            room.active = False
            _audit_room("active", old, False)
            return f"Room *{room_num}* marked as *under maintenance* (inactive)."
        elif any(w in desc_lower for w in ("maintenance done", "maintenance off", "open", "unblock", "ready")):
            old = room.active
            room.active = True
            _audit_room("active", old, True)
            return f"Room *{room_num}* is now *active* again."

    # Staff room toggle (no revenue)
    toggle = _classify_staff_toggle(desc_lower)
    if toggle in ("mark", "unmark"):
        new_val = (toggle == "mark")
        old = room.is_staff_room
        room.is_staff_room = new_val
        _audit_room("is_staff_room", old, new_val)
        # Toggling is_staff_room changes the total-beds denominator used in the
        # monthly tab summary banner (Active / Beds / Vacant / Occupancy). Fire
        # a monthly sheet sync so those cells refresh immediately rather than
        # waiting for the next tenant-level mutation. Per sop_db_sheet_financial:
        # any DB change visible in the sheet must trigger a sheet write.
        try:
            from src.integrations import gsheets as _gs
            from datetime import date as _date
            _today = _date.today()
            _gs.trigger_monthly_sheet_sync(_today.month, _today.year)
        except Exception:
            pass
        if new_val:
            return f"Room *{room_num}* marked as *staff room* (excluded from revenue calculations)."
        return f"Room *{room_num}* is now a *revenue room* (included in calculations)."

    return (
        f"Room *{room_num}* — what to change?\n"
        "• _room {num} add AC_\n"
        "• _room {num} type single_\n"
        "• _room {num} under maintenance_\n"
        "• _room {num} staff room_ / _not staff_\n"
    )


# ── CONFIRM FIELD UPDATE (generic resolver) ──────────────────────────────────

async def resolve_field_update(
    choice: str,
    action_data: dict,
    session: AsyncSession,
    changed_by: str = "system",
) -> str:
    """Apply or cancel a field update after user confirms."""
    from datetime import date as _date

    if choice == "1":
        field = action_data["field"]
        old_value = action_data.get("old_value")
        new_value = action_data["new_value"]
        tenant_name = action_data["tenant_name"]
        table = action_data.get("table", "tenancies")
        room_number = ""
        entity_id = 0

        if table == "tenants":
            tenant_id = action_data["tenant_id"]
            tenancy_id = action_data.get("tenancy_id")
            entity_id = tenant_id
            tenant = await session.get(Tenant, tenant_id)
            if tenant:
                setattr(tenant, field, new_value)
                if tenancy_id:
                    tenancy = await session.get(Tenancy, tenancy_id)
                    if tenancy and tenancy.room_id:
                        room = await session.get(Room, tenancy.room_id)
                        room_number = room.room_number if room else ""
                logger.info(f"[Update] {tenant_name}.{field} = {new_value}")
            else:
                return "Record not found. Update failed."
        else:
            tenancy_id = action_data["tenancy_id"]
            entity_id = tenancy_id
            tenancy = await session.get(Tenancy, tenancy_id)
            if tenancy:
                if field in ("agreed_rent", "security_deposit", "maintenance_fee", "booking_amount"):
                    new_value = Decimal(str(new_value))
                setattr(tenancy, field, new_value)
                if tenancy.room_id:
                    room = await session.get(Room, tenancy.room_id)
                    room_number = room.room_number if room else ""
                logger.info(f"[Update] {tenant_name}.{field} = {new_value}")

                # ── Rent revision tracking ──────────────────────────────
                if field == "agreed_rent":
                    session.add(RentRevision(
                        tenancy_id=tenancy_id,
                        old_rent=Decimal(str(old_value or 0)),
                        new_rent=Decimal(str(new_value)),
                        effective_date=_date.today(),
                        changed_by=changed_by,
                        reason=action_data.get("reason", "manual update via bot"),
                    ))
            else:
                return "Record not found. Update failed."

        # ── Audit log ───────────────────────────────────────────────────
        session.add(AuditLog(
            changed_by=changed_by,
            entity_type="tenant" if table == "tenants" else "tenancy",
            entity_id=entity_id,
            entity_name=tenant_name,
            field=field,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value),
            room_number=room_number or None,
            source="whatsapp",
        ))

        # ── Sync to Google Sheet (BOTH tabs) ────────────────────────────
        # Fast path: single-cell write to the current monthly tab for instant
        # visibility. Then systemic sync pushes the same field to TENANTS
        # master tab so the dashboard KPIs stay accurate. Without the second
        # call the TENANTS row would go stale on every confirm.
        if room_number:
            try:
                import asyncio as _aio
                from src.integrations.gsheets import (
                    update_tenant_field, sync_tenant_all_fields as _sync,
                )
                sheet_value = str(new_value)
                if field == "sharing_type":
                    sheet_value = str(new_value).replace("SharingType.", "").capitalize()
                await _aio.wait_for(
                    update_tenant_field(room_number, tenant_name, field, sheet_value),
                    timeout=10,
                )
                # Systemic sync (both tabs) — fire-and-forget, resolves any
                # ripple cells the per-field write missed.
                resolved_tenant_id = None
                if table == "tenants":
                    resolved_tenant_id = action_data.get("tenant_id")
                else:
                    tenancy_for_sync = await session.get(Tenancy, action_data.get("tenancy_id"))
                    if tenancy_for_sync:
                        resolved_tenant_id = tenancy_for_sync.tenant_id
                if resolved_tenant_id:
                    _aio.create_task(_sync(resolved_tenant_id))
            except Exception as e:
                logger.warning(f"[Update] Sheet sync failed for {tenant_name}.{field}: {e}")

        result = f"Updated *{tenant_name}*: {field} = *{new_value}*"

        # ── If sharing type changed, prompt to update rent too ──────────
        if field == "sharing_type":
            tenancy_id = action_data.get("tenancy_id")
            if tenancy_id:
                tenancy = await session.get(Tenancy, tenancy_id)
                if tenancy:
                    current_rent = int(tenancy.agreed_rent or 0)
                    result += (
                        f"\n\nRent is currently *Rs.{current_rent:,}*.\n"
                        f"Want to update rent too?\n"
                        f"Reply: *{tenant_name} rent [new amount]*"
                    )

        return result

    return "Update cancelled."


# ── QUERY STAFF ROOMS ──────────────────────────────────────────────────────

async def query_staff_rooms(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """List all staff rooms grouped with the staff living in each."""
    rows = (await session.execute(
        select(Room, Property.name)
        .join(Property, Property.id == Room.property_id, isouter=True)
        .where(Room.is_staff_room == True)
        .order_by(Property.name, Room.room_number)
    )).all()

    if not rows:
        return "No staff rooms configured."

    # Fetch all active staff with a room assignment in one shot
    staff_rows = (await session.execute(
        select(Staff).where(Staff.active == True, Staff.room_id.isnot(None))
    )).scalars().all()
    by_room: dict[int, list[Staff]] = {}
    for s in staff_rows:
        by_room.setdefault(s.room_id, []).append(s)

    lines = []
    for room, bldg in rows:
        occupants = by_room.get(room.id, [])
        if occupants:
            names = ", ".join(
                f"{s.name}" + (f" ({s.role})" if s.role else "")
                for s in occupants
            )
            occ = f"{len(occupants)} staff — {names}"
        else:
            occ = "_vacant_"
        status = "" if room.active else " [inactive]"
        lines.append(f"• *{room.room_number}* ({bldg or '?'}){status} — {occ}")

    return (
        f"*Staff Rooms* ({len(rows)} rooms, excluded from revenue):\n\n"
        + "\n".join(lines)
        + "\n\nAssign: _staff [name] room [num]_ • Exit: _staff [name] exit_"
    )


# ── ASSIGN / EXIT STAFF TO ROOM ────────────────────────────────────────────

async def assign_staff_to_room(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Link a staff member to a room. Auto-flips room to staff-room.
    Many staff may share a single room — sharing type / max occupancy is not enforced.

    Expected entities: name, room_number, role (optional), phone (optional)
    """
    name = (entities.get("name") or "").strip()
    room_num = (entities.get("room_number") or entities.get("room") or "").strip()
    role = (entities.get("role") or "").strip() or None
    phone = (entities.get("phone") or "").strip() or None

    if not name or not room_num:
        return ("To assign a staff member to a room, send:\n"
                "_staff [name] room [num]_\n"
                "e.g. _staff Rajesh room G05_")

    room = (await session.execute(
        select(Room).where(Room.room_number == room_num)
    )).scalar_one_or_none()
    if not room:
        return f"Room *{room_num}* not found."

    # Find or create staff by case-insensitive name
    existing = (await session.execute(
        select(Staff).where(Staff.active == True)
    )).scalars().all()
    exact_matches = [s for s in existing if s.name.lower() == name.lower()]

    if len(exact_matches) > 1:
        # Disambiguate — save pending and show numbered choices
        choices = [
            {"seq": i + 1, "intent": "ASSIGN_STAFF_PICK",
             "label": f"{s.name}" + (f" ({s.role})" if s.role else ""),
             "staff_id": s.id}
            for i, s in enumerate(exact_matches)
        ]
        await _save_pending(
            ctx.phone, "ASSIGN_STAFF_WHO",
            {"name": name, "room_id": room.id, "room_number": room.room_number,
             "role": role, "phone": phone},
            choices, session,
        )
        lines = [f"Multiple active staff match *{name}* — which one to assign to room {room.room_number}?\n"]
        for c in choices:
            lines.append(f"*{c['seq']}.* {c['label']}")
        lines.append(f"\nOr reply *cancel* to abort.")
        return "\n".join(lines)

    staff = exact_matches[0] if exact_matches else None
    return await _apply_staff_assignment(staff, name, room, role, phone, ctx, session)


async def _apply_staff_assignment(
    staff, name: str, room, role, phone, ctx: CallerContext, session: AsyncSession,
) -> str:
    """Create-or-link a staff member to a room + flip room to staff."""
    created = False
    if staff is None:
        staff = Staff(
            name=name, property_id=room.property_id, room_id=room.id,
            role=role, phone=phone, active=True,
        )
        session.add(staff)
        created = True
    else:
        old_room = staff.room_id
        staff.room_id = room.id
        if role:
            staff.role = role
        if phone:
            staff.phone = phone
        if old_room != room.id:
            session.add(AuditLog(
                changed_by=ctx.phone or "system",
                entity_type="staff", entity_id=staff.id,
                entity_name=staff.name, field="room_id",
                old_value=str(old_room) if old_room else None,
                new_value=str(room.id), room_number=room.room_number,
                source="whatsapp",
            ))

    room_flag_changed = False
    if not room.is_staff_room:
        room.is_staff_room = True
        room_flag_changed = True
        session.add(AuditLog(
            changed_by=ctx.phone or "system",
            entity_type="room", entity_id=room.id,
            entity_name=room.room_number, field="is_staff_room",
            old_value="False", new_value="True",
            room_number=room.room_number, source="whatsapp",
        ))

    if room_flag_changed:
        try:
            from src.integrations import gsheets as _gs
            from datetime import date as _d
            _t = _d.today()
            _gs.trigger_monthly_sheet_sync(_t.month, _t.year)
        except Exception:
            pass

    verb = "Added" if created else "Assigned"
    return (f"{verb} *{staff.name}*"
            + (f" ({staff.role})" if staff.role else "")
            + f" to room *{room.room_number}*. Room is now a staff room "
              "(excluded from availability).")


async def exit_staff_from_room(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Mark a staff member as exited. Clears their room link.
    If this was the LAST staff in that room, the room flips back to revenue
    and re-appears in available rooms automatically.

    Expected entities: name (required)
    """
    name = (entities.get("name") or "").strip()
    if not name:
        return ("To mark a staff exit, send:\n"
                "_staff [name] exit_\n"
                "e.g. _staff Rajesh exit_")

    candidates = (await session.execute(
        select(Staff).where(Staff.active == True)
    )).scalars().all()
    matches = [s for s in candidates if s.name.lower() == name.lower()]
    if not matches:
        # Loose match — substring
        matches = [s for s in candidates if name.lower() in s.name.lower()]
    if not matches:
        return f"No active staff matching *{name}*."
    if len(matches) > 1:
        # Pre-fetch rooms so the choice list can show each staff's room
        room_ids = {s.room_id for s in matches if s.room_id}
        rooms_by_id: dict[int, Room] = {}
        if room_ids:
            room_rows = (await session.execute(
                select(Room).where(Room.id.in_(room_ids))
            )).scalars().all()
            rooms_by_id = {r.id: r for r in room_rows}

        choices = []
        for i, s in enumerate(matches):
            suffix = f" ({s.role})" if s.role else ""
            if s.room_id and s.room_id in rooms_by_id:
                suffix += f" — room {rooms_by_id[s.room_id].room_number}"
            choices.append({
                "seq": i + 1, "intent": "EXIT_STAFF_PICK",
                "label": f"{s.name}{suffix}", "staff_id": s.id,
            })
        await _save_pending(
            ctx.phone, "EXIT_STAFF_WHO", {"name": name}, choices, session,
        )
        lines = [f"Multiple active staff match *{name}* — which one is exiting?\n"]
        for c in choices:
            lines.append(f"*{c['seq']}.* {c['label']}")
        lines.append("\nOr reply *cancel* to abort.")
        return "\n".join(lines)

    staff = matches[0]
    return await _apply_staff_exit(staff, ctx, session)


async def _apply_staff_exit(staff, ctx: CallerContext, session: AsyncSession) -> str:
    """Mark a staff as exited; flip their room to revenue if now empty."""
    old_room_id = staff.room_id
    staff.active = False
    from datetime import date as _d
    staff.exit_date = _d.today()
    staff.room_id = None

    msg_room_freed = ""
    if old_room_id:
        room = await session.get(Room, old_room_id)
        if room:
            # Are there any other active staff still in this room?
            remaining = (await session.execute(
                select(Staff).where(
                    Staff.room_id == old_room_id,
                    Staff.active == True,
                    Staff.id != staff.id,
                )
            )).scalars().first()
            if remaining is None and room.is_staff_room:
                room.is_staff_room = False
                session.add(AuditLog(
                    changed_by=ctx.phone or "system",
                    entity_type="room", entity_id=room.id,
                    entity_name=room.room_number, field="is_staff_room",
                    old_value="True", new_value="False",
                    room_number=room.room_number, source="whatsapp",
                ))
                try:
                    from src.integrations import gsheets as _gs
                    from datetime import date as _d
                    _t = _d.today()
                    _gs.trigger_monthly_sheet_sync(_t.month, _t.year)
                except Exception:
                    pass
                msg_room_freed = (f"\nRoom *{room.room_number}* is now a revenue room "
                                  "and will appear in available rooms.")
            elif remaining is not None:
                msg_room_freed = (f"\nRoom *{room.room_number}* still has other staff — "
                                  "kept as staff room.")

    session.add(AuditLog(
        changed_by=ctx.phone or "system",
        entity_type="staff", entity_id=staff.id,
        entity_name=staff.name, field="active",
        old_value="True", new_value="False",
        source="whatsapp",
    ))

    return f"*{staff.name}* marked as exited." + msg_room_freed


# ── QUERY AUDIT LOG ─────────────────────────────────────────────────────────

async def query_audit(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show recent changes for a tenant, room, or all."""
    from datetime import datetime as _dt, timedelta

    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    name = entities.get("name", "").strip()

    # Extract room number
    room_match = re.search(r"room\s*(\w+)", desc, re.I)
    room_num = room_match.group(1) if room_match else ""

    # Extract name from description
    if not name:
        clean = re.sub(
            r"\b(show|changes|history|audit|log|who|changed|updated|modified|for|room|recent|last|all|\d+)\b",
            "", desc, flags=re.I,
        ).strip().strip(".,! ")
        if len(clean) >= 2:
            name = clean

    # Build query
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(15)

    if room_num:
        q = q.where(AuditLog.room_number == room_num)
    elif name:
        q = q.where(AuditLog.entity_name.ilike(f"%{name}%"))

    rows = (await session.execute(q)).scalars().all()

    if not rows:
        target = f"room {room_num}" if room_num else (name or "anything")
        return f"No audit records found for *{target}*."

    lines = []
    for r in rows:
        ts = r.created_at.strftime("%d-%b %H:%M") if r.created_at else "?"
        room_tag = f" [Room {r.room_number}]" if r.room_number else ""
        lines.append(
            f"• {ts} — *{r.entity_name}*{room_tag}\n"
            f"  {r.field}: {r.old_value} → *{r.new_value}*\n"
            f"  by {r.changed_by}"
        )

    header = "Recent changes"
    if room_num:
        header = f"Changes for Room {room_num}"
    elif name:
        header = f"Changes for {name}"

    return f"*{header}* (last {len(rows)}):\n\n" + "\n\n".join(lines)


async def query_rent_history(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show rent revision history for a tenant."""
    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    name = entities.get("name", "").strip()

    if not name:
        clean = re.sub(
            r"\b(show|rent|history|revisions?|changes|for)\b",
            "", desc, flags=re.I,
        ).strip().strip(".,! ")
        if len(clean) >= 2:
            name = clean

    if not name:
        return "Which tenant? Reply: *rent history [name]*"

    tenant, tenancy = await _find_active_tenant(name, session)
    if not tenant:
        return f"Couldn't find active tenant '{name}'."

    revisions = (await session.execute(
        select(RentRevision)
        .where(RentRevision.tenancy_id == tenancy.id)
        .order_by(RentRevision.effective_date.desc())
        .limit(10)
    )).scalars().all()

    if not revisions:
        current = int(tenancy.agreed_rent or 0)
        return f"*{tenant.name}* — no rent changes on record. Current rent: *Rs.{current:,}*"

    lines = []
    for rev in revisions:
        dt = rev.effective_date.strftime("%d-%b-%Y") if rev.effective_date else "?"
        reason = f" ({rev.reason})" if rev.reason else ""
        lines.append(
            f"• {dt}: Rs.{int(rev.old_rent):,} → *Rs.{int(rev.new_rent):,}*{reason}"
        )

    current = int(tenancy.agreed_rent or 0)
    return (
        f"*{tenant.name}* — Rent History:\n"
        f"Current: *Rs.{current:,}*\n\n"
        + "\n".join(lines)
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _find_active_tenant(name: str, session: AsyncSession) -> tuple[Optional[Tenant], Optional[Tenancy]]:
    """Fuzzy-find an active tenant by name."""
    result = await session.execute(
        select(Tenant, Tenancy)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .where(
            Tenancy.status == TenancyStatus.active,
            Tenant.name.ilike(f"%{name}%"),
        )
        .limit(1)
    )
    row = result.first()
    if row:
        return row[0], row[1]

    return None, None
