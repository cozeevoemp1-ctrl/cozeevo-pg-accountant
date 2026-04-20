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
    AuditLog, RentRevision,
)
from src.whatsapp.role_service import CallerContext
from src.whatsapp.handlers._shared import (
    _save_pending, _find_active_tenants_by_name, _find_similar_names,
    _make_choices, _format_choices_message, _format_no_match_message,
)


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

    # Disambiguate when multiple active tenants share the name.
    rows = await _find_active_tenants_by_name(name, session)
    if not rows:
        suggestions = await _find_similar_names(name, session)
        return _format_no_match_message(name, suggestions)

    if len(rows) > 1:
        choices = _make_choices(rows)
        await _save_pending(
            ctx.phone, "SHARING_CHANGE_WHO",
            {"new_sharing": new_sharing}, choices, session,
        )
        return _format_choices_message(name, choices, f"change sharing to {new_sharing}")

    tenant, tenancy, room = rows[0]

    raw = tenancy.sharing_type
    old_sharing = raw.value if hasattr(raw, "value") else (raw or "not set")
    if old_sharing == new_sharing:
        return f"*{tenant.name}* is already {new_sharing} sharing."

    room_label = f" (Room {room.room_number})" if room else ""

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

    tenant, tenancy = await _find_active_tenant(name, session)
    if not tenant:
        return f"Couldn't find active tenant '{name}'."

    old_rent = int(tenancy.agreed_rent or 0)
    new_rent = int(amount)
    if old_rent == new_rent:
        return f"*{tenant.name}*'s rent is already Rs.{new_rent:,}."

    room = await session.get(Room, tenancy.room_id)
    room_label = f" (Room {room.room_number})" if room else ""

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

    tenant, tenancy = await _find_active_tenant(name, session)
    if not tenant:
        return f"Couldn't find active tenant '{name}'."

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

    tenant, tenancy = await _find_active_tenant(name, session)
    if not tenant:
        return f"Couldn't find active tenant '{name}'."

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

    tenant, tenancy = await _find_active_tenant(name, session)
    if not tenant:
        return f"Couldn't find active tenant '{name}'."

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

async def update_room(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Update room properties: AC, room type, maintenance mode."""
    desc = (entities.get("description") or entities.get("_raw_message") or "").strip()
    room_num = entities.get("room", "").strip()

    if not room_num:
        m = re.search(r"room\s*(\w+)", desc, re.I)
        room_num = m.group(1) if m else ""

    if not room_num:
        return "Which room? Reply: *room [number] [what to change]*"

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
    if "staff" in desc_lower:
        if any(w in desc_lower for w in ("staff room", "mark staff", "is staff", "make staff", "set staff", "staff yes")):
            old = room.is_staff_room
            room.is_staff_room = True
            _audit_room("is_staff_room", old, True)
            return f"Room *{room_num}* marked as *staff room* (excluded from revenue calculations)."
        elif any(w in desc_lower for w in ("not staff", "remove staff", "no staff", "unmark staff", "revenue room", "tenant room")):
            old = room.is_staff_room
            room.is_staff_room = False
            _audit_room("is_staff_room", old, False)
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

        # ── Sync to Google Sheet ─────────────────────────────────────────
        if room_number:
            try:
                import asyncio as _aio
                from src.integrations.gsheets import update_tenant_field
                sheet_value = str(new_value)
                if field == "sharing_type":
                    sheet_value = str(new_value).replace("SharingType.", "").capitalize()
                await _aio.wait_for(
                    update_tenant_field(room_number, tenant_name, field, sheet_value),
                    timeout=10,
                )
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
    """List all staff rooms (not counted in revenue)."""
    from src.database.models import Property

    rows = (await session.execute(
        select(Room, Property.name)
        .join(Property, Property.id == Room.property_id, isouter=True)
        .where(Room.is_staff_room == True)
        .order_by(Property.name, Room.room_number)
    )).all()

    if not rows:
        return "No staff rooms configured."

    lines = []
    for room, bldg in rows:
        status = "active" if room.active else "inactive"
        lines.append(f"• Room *{room.room_number}* ({bldg or '?'}) — {status}")

    return (
        f"*Staff Rooms* ({len(rows)} rooms, excluded from revenue):\n\n"
        + "\n".join(lines)
        + "\n\nTo change: _room [num] not staff_ or _room [num] staff room_"
    )


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
