"""
src/whatsapp/handlers/_shared.py
=================================
Shared fuzzy-search and disambiguation helpers used by both
OwnerWorker (owner_handler) and AccountWorker (account_handler).

These functions are PURE DB helpers — no business logic, no HTTP calls.
Import them from here; never duplicate them in another handler.
"""
from __future__ import annotations

import difflib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import PendingAction, Room, Tenant, Tenancy, TenancyStatus, WhatsappLog

BOT_NAME = "Artha"
_IST_OFFSET = timedelta(hours=5, minutes=30)


def time_greeting() -> str:
    """Return time-appropriate greeting in IST."""
    hour = (datetime.now(timezone.utc) + _IST_OFFSET).hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    if 17 <= hour < 21:
        return "Good evening"
    return "Good night"


async def is_first_time(phone: str, session: AsyncSession) -> bool:
    """Return True if this phone has never messaged the bot before."""
    result = await session.execute(
        select(WhatsappLog.id).where(WhatsappLog.from_number == phone).limit(1)
    )
    return result.scalar() is None


def bot_intro(first_time: bool) -> str:
    """
    Return the one-time Artha intro paragraph (ends with blank line), or empty string.
    Usage:  f"*{greeting}, {name}!*\n{bot_intro(first_time)}Here's what..."
    """
    return f"I'm *{BOT_NAME}*, your PG assistant!\n\n" if first_time else ""


def parse_target_month(entities: dict) -> date:
    """
    Parse target month from intent entities dict.
    Handles 'date' (ISO string), 'month' (int 1-12), or defaults to current month.
    Never returns a future month — rolls back one year if month hasn't arrived yet.
    """
    today = date.today()
    date_str = entities.get("date", "")
    month_num = entities.get("month")
    if date_str:
        try:
            return date.fromisoformat(date_str).replace(day=1)
        except ValueError:
            pass
    if month_num:
        m = int(month_num)
        year = today.year
        candidate = date(year, m, 1)
        if candidate > today.replace(day=1):
            year -= 1
        return date(year, m, 1)
    return today.replace(day=1)


# ── Yes / No answer helpers ───────────────────────────────────────────────────

_AFFIRMATIVE = {"yes", "y", "confirm", "ok", "haan", "ha", "yeah", "sure", "proceed", "done", "returned"}
_NEGATIVE    = {"no", "n", "cancel", "nahi", "nope", "stop", "none", "nil"}


def is_affirmative(text: str) -> bool:
    return text.lower().strip() in _AFFIRMATIVE


def is_negative(text: str) -> bool:
    return text.lower().strip() in _NEGATIVE


# ── Fuzzy tenant search helpers ───────────────────────────────────────────────

async def _find_active_tenants_by_name(name: str, session: AsyncSession):
    """
    Returns list of (Tenant, Tenancy, Room) tuples matching the name.
    Deduplicates: one row per tenant (latest tenancy if multiple).
    Tries exact ilike first, then first-word prefix if no results.
    """
    async def _search(pattern: str):
        result = await session.execute(
            select(Tenant, Tenancy, Room)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Tenant.name.ilike(pattern),
                Tenancy.status == TenancyStatus.active,
            )
            .order_by(Tenant.name, Tenancy.checkin_date.desc())
        )
        # Deduplicate: keep first (latest) tenancy per tenant_id
        seen_tenants: set = set()
        unique = []
        for row in result.all():
            if row[0].id not in seen_tenants:
                seen_tenants.add(row[0].id)
                unique.append(row)
        return unique

    # Try broad match first
    rows = await _search(f"%{name}%")
    if rows:
        return rows

    # Try prefix of first word (min 3 chars)
    first_word = name.split()[0] if name else name
    if len(first_word) >= 3:
        rows = await _search(f"{first_word}%")
    return rows


async def _find_active_tenants_by_room(room_str: str, session: AsyncSession):
    """
    Find active tenants by room number using partial match.
    "203" matches "203", "203-A", "203-B", "203-C" — handles bed ambiguity.
    """
    result = await session.execute(
        select(Tenant, Tenancy, Room)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Room.room_number.ilike(f"%{room_str}%"),
            Tenancy.status == TenancyStatus.active,
        )
        .order_by(Room.room_number, Tenant.name)
    )
    seen: set = set()
    unique = []
    for row in result.all():
        if row[0].id not in seen:
            seen.add(row[0].id)
            unique.append(row)
    return unique


async def _find_similar_names(name: str, session: AsyncSession) -> list[str]:
    """
    Return up to 3 tenant names that are close to `name` (handles typos, spelling
    variants like Keerthan/Kirthan, partial nickname overlap).
    Uses difflib on all active tenant names.
    """
    result = await session.execute(
        select(Tenant.name)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .where(Tenancy.status == TenancyStatus.active)
        .distinct()
    )
    all_names = [row[0] for row in result.all()]
    name_lower_map = {n.lower(): n for n in all_names}
    all_lower = list(name_lower_map.keys())

    # Try full name match first
    cutoff = 0.55 if len(name) <= 5 else 0.62
    matches = difflib.get_close_matches(name.lower(), all_lower, n=3, cutoff=cutoff)

    # Also try matching just the first word of name against first words of DB names
    first_word = name.split()[0].lower()
    if len(first_word) >= 3:
        first_words = {n.split()[0].lower(): n for n in all_names}
        word_matches = difflib.get_close_matches(first_word, list(first_words.keys()), n=3, cutoff=0.7)
        for wm in word_matches:
            orig = first_words[wm].lower()
            if orig not in matches:
                matches.append(orig)

    return [name_lower_map[m] for m in matches if m in name_lower_map][:3]


async def _check_room_overlap(
    room_id: int,
    start_date: date,
    end_date: Optional[date],
    exclude_tenancy_id: Optional[int],
    session: AsyncSession,
) -> Optional[str]:
    """
    Return the conflicting tenant's name if the room is occupied during [start_date, end_date].
    Returns None if the room is free.
    """
    q = (
        select(Tenant.name, Tenancy.checkin_date, Tenancy.checkout_date)
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .where(
            Tenancy.room_id == room_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    if exclude_tenancy_id:
        q = q.where(Tenancy.id != exclude_tenancy_id)

    result = await session.execute(q)
    far_future = date(9999, 12, 31)
    period_end = end_date or far_future

    for name, checkin, checkout in result.all():
        existing_end = checkout or far_future
        # Overlap: start1 < end2 AND end1 > start2
        if start_date < existing_end and period_end > checkin:
            return name
    return None


def _make_choices(rows) -> list[dict]:
    """Convert (Tenant, Tenancy, Room) rows into numbered choice dicts."""
    choices = []
    for i, (tenant, tenancy, room) in enumerate(rows[:5], 1):
        choices.append({
            "seq": i,
            "tenant_id": tenant.id,
            "tenancy_id": tenancy.id,
            "label": f"{tenant.name} (Room {room.room_number})",
        })
    return choices


async def _save_pending(phone: str, intent: str, action_data: dict, choices: list, session: AsyncSession):
    """Save a pending disambiguation action with 30-minute expiry."""
    # Clear any existing unresolved pending actions for this phone
    existing = await session.execute(
        select(PendingAction).where(
            PendingAction.phone == phone,
            PendingAction.resolved == False,
        )
    )
    for pa in existing.scalars().all():
        pa.resolved = True  # expire old ones

    pa = PendingAction(
        phone=phone,
        intent=intent,
        action_data=json.dumps(action_data),
        choices=json.dumps(choices),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        resolved=False,
    )
    session.add(pa)


def _format_choices_message(name: str, choices: list, intent_label: str) -> str:
    lines = [f"Found {len(choices)} tenants matching *{name}* — which one?\n"]
    for c in choices:
        lines.append(f"{c['seq']}. {c['label']}")
    lines.append(f"\nReply *1* to *{len(choices)}* to {intent_label}.")
    return "\n".join(lines)


def _format_no_match_message(name: str, suggestions: list[str] | None = None) -> str:
    lines = [f"No active tenant found matching *{name}*."]
    if suggestions:
        lines.append("\nDid you mean?")
        for s in suggestions:
            lines.append(f"• {s}")
        lines.append("\nReply with the correct name, or:")
    else:
        lines.append("\nTry:")
    lines += [
        "• Use room number: *Room 201 paid 15000*",
        "• Full name: *Rajesh Kumar paid 15000 upi*",
        "• *[Name] balance* to look up a tenant",
    ]
    return "\n".join(lines)
