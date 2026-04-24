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
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import PendingAction, Room, Tenant, Tenancy, TenancyStatus, WhatsappLog, RentSchedule, RentStatus, Payment, PaymentFor
from src.whatsapp.role_service import _normalize as _norm_phone

BOT_NAME = "Cozeevo Help Desk"
_IST_OFFSET = timedelta(hours=5, minutes=30)

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# 5 greeting styles per role — index 0-4
# {name} = first name, {tod} = time of day, {dow} = day of week
_GREETINGS: dict[str, list[str]] = {
    "owner": [
        "👋 {tod}, {name}! Cozeevo Help Desk — dashboard is ready, what are we working on today?",  # 0 Professional
        "⚡ {name}! Cozeevo Help Desk. What do you need?",                                # 1 Minimalist
        "🚀 Hey {name}! Cozeevo Help Desk — it's {dow}, let's crush it!",               # 2 Energetic
        "🏠 {tod}, {name}! Cozeevo Help Desk — your property is in good hands. How can I help?",  # 3 Supportive
        "🤖 {name}! Cozeevo Help Desk at your service. First order of business?",           # 4 Witty
    ],
    "tenant": [
        "👋 {tod}, {name}! Cozeevo Help Desk — how can I help you today?",               # 0 Professional
        "😊 Hi {name}! Cozeevo Help Desk. Good to hear from you.",                        # 1 Minimalist
        "🎉 Hey {name}! Cozeevo Help Desk — happy {dow}, what's up?",                   # 2 Energetic
        "🏡 {tod}, {name}! Cozeevo Help Desk — hope you're comfortable and settling in well.",  # 3 Supportive
        "✨ Look who's here! Cozeevo Help Desk at your service, {name}. What can I do for you?",     # 4 Witty
    ],
    "lead": [
        "👋 {tod}! Welcome to Cozeevo Co-living — Welcome to Cozeevo Help Desk, your virtual guide! 🏠",     # 0 Professional
        "😊 Hi there! Welcome to Cozeevo Help Desk — looking for a great PG? You're in the right place!",    # 1 Minimalist
        "🎯 Hey! Welcome to Cozeevo Help Desk — let me help you find your perfect room at Cozeevo! 🏠",     # 2 Energetic
        "🤝 {tod}! Welcome to Cozeevo Help Desk — finding the right PG can be tough, I'm here to make it easy.", # 3 Supportive
        "✨ Hello! Welcome to Cozeevo Help Desk — welcome to Cozeevo Co-living! Let me show you around.",    # 4 Witty
    ],
}


def _greeting_style(role: str) -> int:
    """Deterministic style index for today × role. Rotates daily, never same two consecutive days."""
    bucket = "owner" if role in ("admin", "owner", "receptionist") else (
        "tenant" if role == "tenant" else "lead"
    )
    raw = hashlib.md5(f"{date.today().isoformat()}:{bucket}".encode()).hexdigest()
    return int(raw, 16) % 5


def _make_greeting(role: str, name: str) -> str:
    """Build a role-appropriate, daily-rotating greeting line."""
    bucket = "owner" if role in ("admin", "owner", "receptionist") else (
        "tenant" if role == "tenant" else "lead"
    )
    style    = _greeting_style(role)
    template = _GREETINGS[bucket][style]
    tod_hour = (datetime.now(timezone.utc) + _IST_OFFSET).hour
    tod = "Good morning" if 5 <= tod_hour < 12 else "Good afternoon" if tod_hour < 17 else "Good evening"
    first    = name.split()[0] if name else ("boss" if bucket == "owner" else "there")
    dow      = _DAYS[date.today().weekday()]
    return template.format(name=first, tod=tod, dow=dow)


def time_greeting() -> str:
    """Return time-appropriate greeting in IST. Never 'Good night' — that's a farewell, not a greeting."""
    hour = (datetime.now(timezone.utc) + _IST_OFFSET).hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    return "Good evening"


async def is_first_time_today(phone: str, session: AsyncSession) -> bool:
    """Return True if this phone hasn't messaged the bot yet today (IST)."""
    ist_now = datetime.now(timezone.utc) + _IST_OFFSET
    # Strip tzinfo before subtracting — DB column is TIMESTAMP WITHOUT TIME ZONE
    ist_today_start = (ist_now.replace(hour=0, minute=0, second=0, microsecond=0) - _IST_OFFSET).replace(tzinfo=None)
    result = await session.execute(
        select(WhatsappLog.id)
        .where(WhatsappLog.from_number == phone)
        .where(WhatsappLog.created_at >= ist_today_start)
        .limit(1)
    )
    return result.scalar() is None


def bot_intro(first_time_today: bool, name: str = "", role: str = "owner") -> str:
    """
    Return greeting header.
    First time today: rotating style (5 variants, changes daily).
    Returning (already messaged today): short time-based greeting only.
    Always ends with \\n\\n so caller can append menu directly.
    role param added for style routing — defaults to "owner" for backward compat.
    """
    if first_time_today:
        line = _make_greeting(role, name)
        return f"*{line}*\n\n"
    greeting = time_greeting()
    first = name.split()[0] if name else ""
    if first:
        return f"*{greeting}, {first}! {BOT_NAME} here — what do you need?*\n\n"
    return f"*{greeting}! {BOT_NAME} here — what do you need?*\n\n"


def is_owner_role(role: str) -> bool:
    """Return True if the role has owner-level access (including receptionist)."""
    return role in ("admin", "owner", "receptionist")


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

_AFFIRMATIVE = {"yes", "y", "confirm", "ok", "haan", "ha", "yeah", "sure", "proceed", "done", "returned", "theek hai", "thik hai", "sahi hai"}
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
    Tries exact ilike first, then first-word prefix, then fuzzy match on spelling.
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

    # 1. Exact first-name match: "Arun" matches "Arun Vasavan" but not "Tarun" or "Varunlal"
    first_word = name.split()[0] if name else name
    if len(first_word) >= 3:
        rows = await _search(f"{first_word}%")
        if rows:
            return rows

    # 2. Full name contains match (multi-word queries like "Arun Vas")
    if " " in name.strip():
        rows = await _search(f"%{name}%")
        if rows:
            return rows

    # 3. Broad substring match as last resort (catches typos/partial)
    rows = await _search(f"%{name}%")
    if rows:
        return rows

    # 4. Fuzzy match on spelling (handles "Divakra" vs "Divekar")
    # Get all active tenants and score by similarity
    result = await session.execute(
        select(Tenant, Tenancy, Room)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(Tenancy.status == TenancyStatus.active)
        .order_by(Tenant.name, Tenancy.checkin_date.desc())
    )

    candidates = []
    seen_tenants = set()
    for tenant, tenancy, room in result.all():
        if tenant.id not in seen_tenants:
            seen_tenants.add(tenant.id)
            # Score by similarity (0.0-1.0)
            ratio = difflib.SequenceMatcher(None, name.lower(), tenant.name.lower()).ratio()
            if ratio >= 0.75:  # 75%+ similarity (e.g., "Divakra" vs "Divekar")
                candidates.append((ratio, (tenant, tenancy, room)))

    if candidates:
        # Return matches sorted by similarity (best first)
        candidates.sort(reverse=True, key=lambda x: x[0])
        return [match[1] for match in candidates]

    return []


async def _find_active_daywise_by_name(name: str, session: AsyncSession):
    """Return DaywiseStay rows for guests whose name matches and whose stay
    covers today. Used by ROOM_TRANSFER when no monthly tenancy matches —
    Lokesh still says "move X to Y" for day-wise guests.
    """
    from datetime import date as _date
    from src.database.models import DaywiseStay
    today = _date.today()

    async def _search(pattern: str):
        result = await session.execute(
            select(DaywiseStay)
            .where(
                DaywiseStay.guest_name.ilike(pattern),
                DaywiseStay.checkin_date <= today,
                DaywiseStay.checkout_date >= today,
                DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
            )
            .order_by(DaywiseStay.checkin_date.desc())
        )
        return list(result.scalars().all())

    first_word = name.split()[0] if name else name
    if len(first_word) >= 3:
        rows = await _search(f"{first_word}%")
        if rows:
            return rows
    if " " in name.strip():
        rows = await _search(f"%{name}%")
        if rows:
            return rows
    return await _search(f"%{name}%")


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
    """Return conflicting occupant name if the room is booked during
    [start_date, end_date], else None.

    Thin wrapper over the canonical helper so BOTH long-term tenancies
    AND day-stays are checked — see src/services/room_occupancy.py.
    """
    from src.services.room_occupancy import find_overlap_conflict
    return await find_overlap_conflict(
        session, room_id, start_date, end_date, exclude_tenancy_id
    )


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


async def _save_pending(phone: str, intent: str, action_data: dict, choices: list, session: AsyncSession, state: str | None = None):
    """Save a pending disambiguation action with 30-minute expiry.

    `state` is a ConversationState value (e.g. "awaiting_choice"). Framework-
    managed intents set this; legacy callers leave it None and rely on the
    legacy resolve_pending_action cascade.
    """
    phone = _norm_phone(phone)  # canonical 10-digit form so get/save always match
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
        state=state,   # None = legacy cascade; set = framework-routed
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


# ── Dues snapshot + allocation helpers ────────────────────────────────────────


async def build_dues_snapshot(
    tenancy_id: int,
    tenant_name: str,
    room_number: str,
    session: AsyncSession,
) -> dict:
    """
    Build a complete dues snapshot for a tenant.
    Returns:
        {
            "text": str,              # formatted snapshot string
            "months": [               # list of pending months
                {"period": date, "due": Decimal, "paid": Decimal, "remaining": Decimal,
                 "status": str, "notes": str|None},
            ],
            "total_outstanding": Decimal,
            "tenant_notes": str|None,  # permanent tenancy.notes
        }
    """
    tenancy = await session.get(Tenancy, tenancy_id)
    tenant_notes = tenancy.notes if tenancy else None

    # Get all pending/partial rent_schedule rows, ordered oldest first
    rs_result = await session.execute(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy_id,
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
        ).order_by(RentSchedule.period_month.asc())
    )
    months = []
    total_outstanding = Decimal("0")

    for rs in rs_result.scalars().all():
        paid = await session.scalar(
            select(func.sum(Payment.amount)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.period_month == rs.period_month,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
            )
        ) or Decimal("0")
        effective_due = (rs.rent_due or Decimal("0")) + (rs.adjustment or Decimal("0"))
        remaining = max(Decimal("0"), effective_due - paid)
        total_outstanding += remaining
        status_label = "partial" if paid > 0 else "unpaid"
        months.append({
            "period": rs.period_month,
            "due": effective_due,
            "paid": paid,
            "remaining": remaining,
            "status": status_label,
            "notes": rs.notes,
        })

    # Build text
    lines = [f"*{tenant_name}* (Room {room_number})"]
    if tenant_notes:
        lines.append(f"\nTenant notes: {tenant_notes}")
    if months:
        lines.append("\nDues:")
        for m in months:
            month_str = m["period"].strftime("%b %Y")
            status_str = f"({m['status']}"
            if m["paid"] > 0:
                status_str += f" -- Rs.{int(m['paid']):,} of Rs.{int(m['due']):,} paid"
            status_str += ")"
            line = f"  {month_str}: Rs.{int(m['remaining']):,} {status_str}"
            if m["notes"]:
                line += f' -- "{m["notes"]}"'
            lines.append(line)
        lines.append(f"  *Total outstanding: Rs.{int(total_outstanding):,}*")
    else:
        lines.append("\nAll paid up!")

    return {
        "text": "\n".join(lines),
        "months": months,
        "total_outstanding": total_outstanding,
        "tenant_notes": tenant_notes,
    }


def compute_allocation(
    amount: Decimal,
    months: list[dict],
) -> list[dict]:
    """
    Allocate payment amount oldest-first across pending months.
    Returns list of {"period": date, "amount": Decimal, "clears": bool} dicts.
    """
    remaining = Decimal(str(amount))
    allocation = []
    for m in months:
        if remaining <= 0:
            break
        apply = min(remaining, m["remaining"])
        if apply > 0:
            allocation.append({
                "period": m["period"],
                "amount": apply,
                "clears": apply >= m["remaining"],
            })
            remaining -= apply
    return allocation


def format_allocation(allocation: list[dict], amount, mode: str) -> str:
    """Format allocation into a confirmation message section."""
    mode_label = (mode or "cash").upper()
    lines = [f"\nSuggested allocation for Rs.{int(amount):,} {mode_label}:"]
    for a in allocation:
        month_str = a["period"].strftime("%b %Y")
        label = "clears balance" if a["clears"] else "partial"
        lines.append(f"  -> {month_str}: Rs.{int(a['amount']):,} ({label})")
    return "\n".join(lines)


def parse_allocation_override(text: str, months: list[dict]) -> list[dict] | None:
    """
    Parse receptionist override like "all to march" or "feb 3000 march 5000".
    Returns list of {"period": date, "amount": Decimal} or None if unparseable.
    """
    import re as _re
    text_lower = text.strip().lower()

    # Build month name -> period map from available months
    month_map = {}
    for m in months:
        month_map[m["period"].strftime("%b").lower()] = m["period"]
        month_map[m["period"].strftime("%B").lower()] = m["period"]

    # "all to march" / "all to feb"
    match = _re.match(r"all\s+to\s+(\w+)", text_lower)
    if match:
        month_name = match.group(1)
        period = month_map.get(month_name)
        if period:
            return [{"period": period, "amount": None}]  # None = full amount
        return None

    # "feb 3000 march 5000" or "feb 3000, march 5000"
    parts = _re.findall(r"(\w+)\s+([\d,]+)", text_lower)
    if parts:
        result = []
        for month_name, amt_str in parts:
            period = month_map.get(month_name)
            if not period:
                return None
            amt = Decimal(amt_str.replace(",", ""))
            result.append({"period": period, "amount": amt})
        return result

    return None
