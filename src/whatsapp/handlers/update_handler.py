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
)
from src.whatsapp.role_service import CallerContext
from src.whatsapp.handlers._shared import _save_pending


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

    tenant, tenancy = await _find_active_tenant(name, session)
    if not tenant:
        return f"Couldn't find active tenant '{name}'. Check the spelling."

    raw = tenancy.sharing_type
    old_sharing = raw.value if hasattr(raw, "value") else (raw or "not set")
    if old_sharing == new_sharing:
        return f"*{tenant.name}* is already {new_sharing} sharing."

    room = await session.get(Room, tenancy.room_id)
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
        return f"Room {room_num} not found."

    desc_lower = desc.lower()

    # AC toggle
    if "ac" in desc_lower:
        if any(w in desc_lower for w in ("add ac", "has ac", "ac on", "ac yes", "with ac")):
            room.has_ac = True
            return f"Room *{room_num}* updated: AC = *Yes*"
        elif any(w in desc_lower for w in ("no ac", "remove ac", "ac off", "without ac")):
            room.has_ac = False
            return f"Room *{room_num}* updated: AC = *No*"

    # Room type
    for rt in ("single", "double", "triple", "premium"):
        if rt in desc_lower and "type" in desc_lower:
            room.room_type = rt
            return f"Room *{room_num}* updated: type = *{rt}*"

    # Maintenance mode
    if "maintenance" in desc_lower:
        if any(w in desc_lower for w in ("under maintenance", "maintenance on", "close", "block")):
            room.active = False
            return f"Room *{room_num}* marked as *under maintenance* (inactive)."
        elif any(w in desc_lower for w in ("maintenance done", "maintenance off", "open", "unblock", "ready")):
            room.active = True
            return f"Room *{room_num}* is now *active* again."

    return (
        f"Room *{room_num}* — what to change?\n"
        "• _room {num} add AC_\n"
        "• _room {num} type single_\n"
        "• _room {num} under maintenance_\n"
    )


# ── CONFIRM FIELD UPDATE (generic resolver) ──────────────────────────────────

async def resolve_field_update(
    choice: str,
    action_data: dict,
    session: AsyncSession,
) -> str:
    """Apply or cancel a field update after user confirms."""
    import json

    if choice == "1":
        field = action_data["field"]
        new_value = action_data["new_value"]
        tenant_name = action_data["tenant_name"]
        table = action_data.get("table", "tenancies")
        room_number = ""

        if table == "tenants":
            tenant_id = action_data["tenant_id"]
            tenancy_id = action_data.get("tenancy_id")
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
            tenancy = await session.get(Tenancy, tenancy_id)
            if tenancy:
                if field in ("agreed_rent", "security_deposit", "maintenance_fee", "booking_amount"):
                    new_value = Decimal(str(new_value))
                setattr(tenancy, field, new_value)
                if tenancy.room_id:
                    room = await session.get(Room, tenancy.room_id)
                    room_number = room.room_number if room else ""
                logger.info(f"[Update] {tenant_name}.{field} = {new_value}")
            else:
                return "Record not found. Update failed."

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

        return f"Updated *{tenant_name}*: {field} = *{new_value}*"

    return "Update cancelled."


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
