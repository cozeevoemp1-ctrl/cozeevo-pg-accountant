"""
Tenant (end_user) handler — read-only self-service.
Tenants can only see their own data. No writes allowed.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Complaint, ComplaintCategory, ComplaintStatus,
    OnboardingSession, Payment, PaymentMode, PendingAction, Property, RentSchedule, RentStatus,
    Room, Tenancy, TenancyStatus, Vacation,
)
import json
from src.whatsapp.role_service import CallerContext
from src.whatsapp.handlers._shared import BOT_NAME, time_greeting, is_first_time_today, bot_intro, parse_target_month
from src.whatsapp.intent_detector import _extract_date_entity as _parse_date
from services.property_logic import (
    NOTICE_BY_DAY as _NOTICE_BY_DAY,   # single source of truth
    calc_notice_last_day,
    is_deposit_eligible,
)


async def handle_tenant(
    intent: str,
    entities: dict,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:
    handlers = {
        "MY_BALANCE":        _my_balance,
        "MY_PAYMENTS":       _my_payments,
        "MY_DETAILS":        _my_details,
        "CHECKOUT_NOTICE":   _checkout_notice,
        "VACATION_NOTICE":   _vacation_notice,
        "GET_WIFI_PASSWORD":  _get_wifi_password,
        "COMPLAINT_REGISTER": _complaint_register,
        "REQUEST_RECEIPT":   _request_receipt,
        "RULES":             _rules,
        "HELP":              _help,
        "UNKNOWN":           _unknown,
    }
    fn = handlers.get(intent, _unknown)
    return await fn(entities, ctx, session)


async def _my_balance(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    import re as _re

    result = await session.execute(
        select(Tenancy).where(
            Tenancy.tenant_id == ctx.tenant_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    tenancy = result.scalars().first()
    if not tenancy:
        return "No active tenancy found for your account. Please contact the PG office."

    # Detect if a specific month was mentioned in the message
    _MONTH_MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    description = (entities.get("description") or "").lower()
    asked_month: Optional[date] = None
    m = _re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*", description)
    if m:
        mon_num = _MONTH_MAP.get(m.group(1))
        if mon_num:
            yr = date.today().year
            asked_month = date(yr, mon_num, 1)

    if asked_month:
        # Show balance for the asked month only
        result = await session.execute(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy.id,
                RentSchedule.period_month == asked_month,
            )
        )
        rs = result.scalars().first()
        if not rs:
            return (
                f"*Your Balance — {asked_month.strftime('%B %Y')}*\n\n"
                f"No rent record found for {asked_month.strftime('%B %Y')}.\n"
                "Please contact the PG office if you have questions."
            )
        result = await session.execute(
            select(func.sum(Payment.amount)).where(
                Payment.tenancy_id == tenancy.id,
                Payment.period_month == asked_month,
                Payment.is_void == False,
            )
        )
        paid = result.scalar() or Decimal("0")
        balance = (rs.rent_due or Decimal("0")) - paid
        status_msg = {
            RentStatus.paid:    "Fully paid ✓",
            RentStatus.partial: f"Partial — Rs.{int(balance):,} still due",
            RentStatus.pending: f"Due — Rs.{int(balance):,}",
            RentStatus.waived:  "Waived",
            RentStatus.na:      "Not applicable",
        }.get(rs.status, "Unknown")
        return (
            f"*Your Balance — {asked_month.strftime('%B %Y')}*\n\n"
            f"Rent due: Rs.{int(rs.rent_due or 0):,}\n"
            f"Paid so far: Rs.{int(paid):,}\n"
            f"Status: {status_msg}\n\n"
            "For payment receipts, say: *my payments*"
        )

    # No specific month asked — show all outstanding dues
    result = await session.execute(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy.id,
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
        ).order_by(RentSchedule.period_month)
    )
    pending_rows = result.scalars().all()

    if not pending_rows:
        return (
            "*Your Balance*\n\n"
            "No pending dues. You're all clear! ✓\n\n"
            "For payment receipts, say: *my payments*"
        )

    lines = ["*Your Outstanding Dues*\n"]
    total_due = Decimal("0")
    for rs in pending_rows:
        result = await session.execute(
            select(func.sum(Payment.amount)).where(
                Payment.tenancy_id == tenancy.id,
                Payment.period_month == rs.period_month,
                Payment.is_void == False,
            )
        )
        paid = result.scalar() or Decimal("0")
        balance = (rs.rent_due or Decimal("0")) - paid
        total_due += balance
        lines.append(
            f"• {rs.period_month.strftime('%b %Y')}: Rs.{int(rs.rent_due or 0):,}"
            + (f" (paid Rs.{int(paid):,}, due Rs.{int(balance):,})" if paid > 0 else "")
        )

    lines.append(f"\n*Total due: Rs.{int(total_due):,}*")
    lines.append("\nFor payment receipts, say: *my payments*")
    return "\n".join(lines)


async def _my_payments(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    # Always ask for month — never assume or show "last 6"
    month_num = entities.get("month")
    date_str  = entities.get("date", "")
    if not month_num and not date_str:
        return (
            "Which month would you like to see?\n\n"
            "Example: *my payments March 2026*\n"
            "or just say: *March payments*"
        )

    result = await session.execute(
        select(Tenancy).where(
            Tenancy.tenant_id == ctx.tenant_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    tenancy = result.scalars().first()
    if not tenancy:
        return "No active tenancy found."

    target_month = parse_target_month(entities)

    result = await session.execute(
        select(Payment).where(
            Payment.tenancy_id == tenancy.id,
            Payment.period_month == target_month,
            Payment.is_void == False,
        ).order_by(Payment.payment_date.desc())
    )
    payments = result.scalars().all()

    if not payments:
        return f"No payment records found for *{target_month.strftime('%B %Y')}*."

    total = sum((p.amount or Decimal("0")) for p in payments)
    lines = [f"*Your Payments — {target_month.strftime('%B %Y')}*\n"]
    for p in payments:
        dt = p.payment_date.strftime("%d %b %Y") if p.payment_date else "—"
        lines.append(f"• {dt}: Rs.{int(p.amount or 0):,}")
    lines.append(f"\n*Total paid: Rs.{int(total):,}*")
    return "\n".join(lines)


async def _my_details(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    result = await session.execute(
        select(Tenancy, Room).join(Room, Tenancy.room_id == Room.id).where(
            Tenancy.tenant_id == ctx.tenant_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    row = result.first()
    if not row:
        return "No active tenancy found for your account."

    tenancy, room = row

    return (
        f"*Your Stay Details*\n\n"
        f"Name: {ctx.name}\n"
        f"Room: {room.room_number} ({room.room_type.value})\n"
        f"Checkin: {tenancy.checkin_date.strftime('%d %B %Y')}\n"
        f"Monthly rent: Rs.{int(tenancy.agreed_rent or 0):,}\n"
        f"Deposit paid: Rs.{int(tenancy.security_deposit or 0):,}\n"
        f"Maintenance: Rs.{int(tenancy.maintenance_fee or 0):,}/month"
    )


async def _help(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    header = bot_intro(await is_first_time_today(ctx.phone, session), ctx.name)
    return (
        f"{header}"
        "Here's what you can ask me:\n\n"
        "• *my balance* — This month's dues\n"
        "• *my payments* — Payment history (by month)\n"
        "• *my details* — Room and stay info\n"
        "• *wifi password* — Get WiFi details\n"
        "• *complaint* — Report an issue\n"
        "• *rules* — PG rules & regulations\n\n"
        "For urgent issues, contact the PG office directly."
    )


async def _rules(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    return (
        "*COZEEVO — Rules & Regulations*\n"
        "No. 9, 7th Cross Road, EPIP Zone, Brookefield, Bangalore-560048\n\n"
        "1. Vacating notice must be given *30 days before*, before the *5th of the month*. "
        "Otherwise 30 days rent is charged. _(Vacate only on 30th or 31st of any month)_\n\n"
        "2. Rent must be paid *on or before the 5th* of every month.\n\n"
        "3. Advance & Rent once paid *cannot be refunded*.\n\n"
        "4. *Outsiders are strictly not allowed* inside the premises.\n\n"
        "5. Guest accommodation (with/without food) charged at *Rs. 1,200/- per day*.\n\n"
        "6. *Iron box, Kettle, Induction Stove* etc. are not allowed.\n\n"
        "7. Maintenance charges fixed at *Rs. 5,000/-*.\n\n"
        "8. Management is *not responsible* for your belongings.\n\n"
        "9. Switch OFF all *lights, fans and geysers* before leaving your room.\n\n"
        "10. *Smoking & Liquor* not allowed inside the PG.\n\n"
        "11. Do not throw garbage from windows. *Keep all premises clean*.\n\n"
        "12. Failure to follow rules → room must be vacated within *30 days*.\n\n"
        "13. Management may *immediately evict* anyone whose behaviour is disruptive or poses risk.\n\n"
        "14. Late arrival after *10:30 PM* — inform in-charge in advance.\n\n"
        "15. *Two-wheeler wheel lock* must be ensured.\n\n"
        "16. Parking provided; management *not responsible* for theft/damage to vehicles.\n\n"
        "17. Lost key replacement charge: *Rs. 1,000/-*.\n\n"
        "18. *Do not share PG food* with outsiders.\n\n"
        "19. Any damage to owner's belongings will be *deducted from your deposit*.\n\n"
        "⚠️ _Management is not responsible for Gold, Mobile, Laptop, Cash, Cards, Passport, "
        "Pancard or any other valuables. Keep them at your own risk._\n\n"
        "By staying at Cozeevo you agree to all the above rules."
    )


# ── Checkout notice ───────────────────────────────────────────────────────────

async def _checkout_notice(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Tenant giving notice to vacate.
    Rule: Notice must be given by the 5th of the month by 23:59 for deposit refund eligibility.
    """
    result = await session.execute(
        select(Tenancy, Room).join(Room, Tenancy.room_id == Room.id).where(
            Tenancy.tenant_id == ctx.tenant_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    row = result.first()
    if not row:
        return "No active tenancy found. Please contact the PG office."

    tenancy, room = row
    today = date.today()

    # Use centralised notice logic from services/property_logic.py
    eligible  = is_deposit_eligible(today)
    last_date = calc_notice_last_day(today)

    if eligible:
        deposit_msg = (
            f"✅ Your notice is *on time* (on/before {_NOTICE_BY_DAY}th).\n"
            f"Your deposit is *eligible for refund* after you vacate.\n"
            f"Your last day will be: *{last_date.strftime('%d %b %Y')}*"
        )
        closing = "The PG office has been notified. Please hand over keys on your last day."
    else:
        deposit_msg = (
            f"⚠️ *Notice received after the {_NOTICE_BY_DAY}th of the month.*\n\n"
            f"As per PG rules, notice must be given *on or before the {_NOTICE_BY_DAY}th* "
            f"for your deposit to be refunded.\n\n"
            f"Since notice was given on *{today.strftime('%d %b')}*, your deposit will *not* "
            f"be refunded as per the PG agreement.\n"
            f"Your notice period runs until: *{last_date.strftime('%d %b %Y')}*"
        )
        closing = "The PG office has been notified. For queries, contact us directly."

    # Record the notice
    tenancy.notice_date = today
    tenancy.expected_checkout = last_date
    return (
        f"*Notice Received — {ctx.name}*\n"
        f"Room: {room.room_number}\n"
        f"Notice date: {today.strftime('%d %b %Y')}\n\n"
        f"{deposit_msg}\n\n"
        f"{closing}"
    )


# ── WiFi password (floor-scoped) ──────────────────────────────────────────────

_FLOOR_NUM_TO_KEY = {0: "G", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6"}
_FLOOR_LABELS = {
    "G": "Ground Floor", "1": "1st Floor", "2": "2nd Floor",
    "3": "3rd Floor", "4": "4th Floor", "5": "5th Floor", "6": "6th Floor",
    "top": "Dining Area", "ws": "Work Area", "gym": "Gym",
}


async def _get_wifi_password(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show WiFi credentials for the tenant's floor (Thor + Hulk blocks)."""
    result = await session.execute(
        select(Tenancy, Room, Property)
        .join(Room, Tenancy.room_id == Room.id)
        .join(Property, Property.id == Room.property_id)
        .where(
            Tenancy.tenant_id == ctx.tenant_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    row = result.first()
    if not row:
        return "No active tenancy found. Please contact the PG office."
    tenancy, room, prop = row

    msg = entities.get("description", "").lower()
    floor_map: dict = prop.wifi_floor_map or {}
    thor: dict = floor_map.get("thor", {})
    hulk: dict = floor_map.get("hulk", {})

    # Special areas
    if any(w in msg for w in ("dining", "top", "terrace")):
        nets = thor.get("top", [])
        return _fmt_wifi_nets("Dining Area (TOP)", nets) if nets else "Dining WiFi not configured."
    if any(w in msg for w in ("work", "ws", "workspace")):
        nets = thor.get("ws", [])
        return _fmt_wifi_nets("Work Area (WS)", nets) if nets else "Work area WiFi not configured."
    if "gym" in msg:
        nets = thor.get("gym", [])
        return _fmt_wifi_nets("Gym", nets) if nets else "Gym WiFi not configured."

    # Derive floor key from room
    floor_key = _FLOOR_NUM_TO_KEY.get(room.floor) if room.floor is not None else None
    if not floor_key:
        return (
            "I couldn't find your floor details.\n"
            "Please contact the PG office for the WiFi password."
        )

    label = _FLOOR_LABELS.get(floor_key, f"Floor {floor_key}")
    lines = [f"*WiFi — {label}*\n"]
    lines.append("*Thor Block:*")
    for net in thor.get(floor_key, []):
        lines.append(f"  Network : `{net['ssid']}`")
        lines.append(f"  Password: `{net['password']}`")
    if hulk.get(floor_key):
        lines.append("\n*Hulk Block:*")
        for net in hulk.get(floor_key, []):
            lines.append(f"  Network : `{net['ssid']}`")
            lines.append(f"  Password: `{net['password']}`")
    lines.append("\n📶 _Use 5GHz for mobiles/laptops, 2.4GHz for TV_")
    lines.append("🔤 _All passwords are lowercase_")
    return "\n".join(lines)


def _fmt_wifi_nets(label: str, nets: list) -> str:
    lines = [f"*WiFi — {label}*\n"]
    for net in nets:
        lines.append(f"  Network : `{net['ssid']}`")
        lines.append(f"  Password: `{net['password']}`")
    lines.append("\n📶 _5GHz for mobiles/laptops, 2.4GHz for TV_")
    return "\n".join(lines)


# ── Vacation notice ────────────────────────────────────────────────────────────

_RE_FROM = re.compile(r"from\s+(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*)", re.I)
_RE_BACK = re.compile(r"(?:back\s+on|return(?:ing)?\s+on|till?|until|to)\s+(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*)", re.I)


async def _vacation_notice(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    result = await session.execute(
        select(Tenancy).where(
            Tenancy.tenant_id == ctx.tenant_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    tenancy = result.scalars().first()
    if not tenancy:
        return "No active tenancy found."

    # Try to extract from/to dates from entities or raw message
    raw_message = entities.get("description", "")
    from_date_str = entities.get("from_date") or entities.get("date")
    to_date_str   = entities.get("to_date") or entities.get("back_date")

    if not from_date_str:
        m = _RE_FROM.search(raw_message)
        if m:
            from_date_str = m.group(1)
    if not to_date_str:
        m = _RE_BACK.search(raw_message)
        if m:
            to_date_str = m.group(1)

    if not from_date_str or not to_date_str:
        return (
            f"*Going home, {ctx.name}?* 🏠\n\n"
            "Please let us know:\n"
            "• _From date_ (when you leave)\n"
            "• _Back on_ (when you return)\n\n"
            "Example: *going home from 20 Apr, back on 5 May*"
        )

    from_iso = _parse_date(from_date_str)
    to_iso   = _parse_date(to_date_str)
    if not from_iso or not to_iso:
        return (
            "Couldn't read the dates. Please use format: *going home from 20 Apr, back on 5 May*"
        )

    from_dt = date.fromisoformat(from_iso)
    to_dt   = date.fromisoformat(to_iso)
    if to_dt < from_dt:
        return "Return date can't be before departure date. Please check and resend."

    # Save vacation record
    vacation = Vacation(
        tenancy_id=tenancy.id,
        from_date=from_dt,
        to_date=to_dt,
        affects_billing=False,
        notes=f"Self-reported via WhatsApp",
    )
    session.add(vacation)

    days = (to_dt - from_dt).days
    return (
        f"✅ *Vacation Noted — {ctx.name}*\n\n"
        f"Away from : *{from_dt.strftime('%d %b %Y')}*\n"
        f"Back on   : *{to_dt.strftime('%d %b %Y')}* ({days} day{'s' if days != 1 else ''})\n\n"
        "Your room will be secured while you're away. Safe travels! 🙏"
    )


# ── Complaint / maintenance request ──────────────────────────────────────────

_COMPLAINT_KEYWORDS: dict[str, str] = {
    # plumbing
    "leak": "plumbing", "tap": "plumbing", "flush": "plumbing", "drain": "plumbing",
    "pipe": "plumbing", "water": "plumbing", "hot water": "plumbing",
    "geyser": "plumbing", "heater": "plumbing", "shower": "plumbing",
    # electricity
    "bulb": "electricity", "fan": "electricity", "switch": "electricity",
    "light": "electricity", "mcb": "electricity", "socket": "electricity",
    "power": "electricity", "current": "electricity",
    # wifi
    "wifi": "wifi", "wi-fi": "wifi", "internet": "wifi", "net": "wifi",
    "slow": "wifi", "signal": "wifi",
    # food
    "food": "food", "mess": "food", "meal": "food", "breakfast": "food",
    "lunch": "food", "dinner": "food", "cook": "food",
    # furniture
    "bed": "furniture", "mattress": "furniture", "pillow": "furniture",
    "sheet": "furniture", "chair": "furniture", "table": "furniture",
    "shelf": "furniture", "almirah": "furniture", "cupboard": "furniture",
    "mirror": "furniture",
}

_CATEGORY_ENUM = {
    "plumbing":    ComplaintCategory.plumbing,
    "electricity": ComplaintCategory.electricity,
    "wifi":        ComplaintCategory.wifi,
    "food":        ComplaintCategory.food,
    "furniture":   ComplaintCategory.furniture,
    "other":       ComplaintCategory.other,
}

_TICKET_PREFIX = {
    ComplaintCategory.plumbing:    "PLUM",
    ComplaintCategory.electricity: "ELEC",
    ComplaintCategory.wifi:        "WIFI",
    ComplaintCategory.food:        "FOOD",
    ComplaintCategory.furniture:   "FURN",
    ComplaintCategory.other:       "OTH",
}

def _ticket_number(category: ComplaintCategory, complaint_id: int) -> str:
    prefix = _TICKET_PREFIX.get(category, "OTH")
    return f"{prefix}-{complaint_id:03d}"


def _detect_complaint_category(text: str) -> ComplaintCategory:
    lower = text.lower()
    for keyword, cat in _COMPLAINT_KEYWORDS.items():
        if keyword in lower:
            return _CATEGORY_ENUM[cat]
    return ComplaintCategory.other


async def _complaint_register(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    result = await session.execute(
        select(Tenancy).where(
            Tenancy.tenant_id == ctx.tenant_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    tenancy = result.scalars().first()
    if not tenancy:
        return "No active tenancy found. Please contact the PG office directly."

    description = entities.get("description", "Issue reported via WhatsApp")
    category = _detect_complaint_category(description)

    # Dedup: same tenancy + same category already open/in_progress → ignore
    existing = await session.scalar(
        select(Complaint).where(
            Complaint.tenancy_id == tenancy.id,
            Complaint.category == category,
            Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.in_progress]),
        )
    )
    if existing:
        return (
            f"Your *{category.value}* complaint is already registered and being worked on.\n"
            "We'll notify you once it's resolved."
        )

    # Ask follow-up questions before logging — save state in PendingAction
    pending = PendingAction(
        phone=ctx.phone,
        intent="COMPLAINT_REGISTER",
        action_data=json.dumps({
            "description": description,
            "category": category.value,
            "tenancy_id": tenancy.id,
        }),
        choices=json.dumps([]),
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    session.add(pending)

    if category == ComplaintCategory.wifi:
        q1 = "1️⃣ *Room number + floor/area?* (e.g., room 624, 2nd floor corridor, common area, kitchen, router room?)"
    else:
        q1 = "1️⃣ *Which room or area?* (your room, bathroom, kitchen, common area?)"

    return (
        "Got your complaint. Two quick questions:\n\n"
        f"{q1}\n"
        "2️⃣ *Since when?* (e.g., since yesterday, since 2 days)\n\n"
        "Reply in one message, e.g.: _room 624 bathroom, since yesterday_"
    )


async def resolve_tenant_complaint(pending: PendingAction, reply: str, session: AsyncSession) -> str:
    """Complete a COMPLAINT_REGISTER that was waiting for room/area + since-when details."""
    data = json.loads(pending.action_data or "{}")
    tenancy_id = data.get("tenancy_id")
    original_desc = data.get("description", "")
    category_str = data.get("category", "other")
    category = ComplaintCategory(category_str)

    full_description = f"{original_desc} | Location/duration: {reply}"

    complaint = Complaint(
        tenancy_id=tenancy_id,
        category=category,
        description=full_description,
        status=ComplaintStatus.open,
    )
    session.add(complaint)
    await session.flush()   # get complaint.id before commit

    ticket = _ticket_number(category, complaint.id)

    cat_label = {
        ComplaintCategory.plumbing:    "Plumbing",
        ComplaintCategory.electricity: "Electricity",
        ComplaintCategory.wifi:        "Wi-Fi",
        ComplaintCategory.food:        "Food / Mess",
        ComplaintCategory.furniture:   "Furniture / Room item",
        ComplaintCategory.other:       "Other",
    }.get(category, "Other")

    return (
        f"✅ *Complaint Registered*\n"
        f"Ticket : *{ticket}*\n"
        f"Category: {cat_label}\n"
        f"Details: {original_desc}\n"
        f"Location/Duration: {reply}\n\n"
        "The PG team has been notified. We'll fix it ASAP!"
    )


# ── Request receipt ────────────────────────────────────────────────────────────

async def _request_receipt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    # Always ask for month — never assume
    month_num = entities.get("month")
    date_str  = entities.get("date", "")
    if not month_num and not date_str:
        return (
            "Which month's receipt do you need?\n\n"
            "Example: *receipt March 2026*\n"
            "or: *January receipt*"
        )

    result = await session.execute(
        select(Tenancy).where(
            Tenancy.tenant_id == ctx.tenant_id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    tenancy = result.scalars().first()
    if not tenancy:
        return "No active tenancy found."

    target_month = parse_target_month(entities)

    result = await session.execute(
        select(Payment).where(
            Payment.tenancy_id == tenancy.id,
            Payment.period_month == target_month,
            Payment.is_void == False,
        ).order_by(Payment.payment_date.desc())
    )
    payments = result.scalars().all()
    if not payments:
        return f"No payment records found for *{target_month.strftime('%B %Y')}*."

    total = sum((p.amount or Decimal("0")) for p in payments)
    lines = [f"*Payment Receipt — {ctx.name}*\n*{target_month.strftime('%B %Y')}*\n"]
    for p in payments:
        dt = p.payment_date.strftime("%d %b %Y") if p.payment_date else "—"
        lines.append(f"• {dt}: Rs.{int(p.amount or 0):,}")
    lines.append(f"\n*Total: Rs.{int(total):,}*")
    lines.append("\nFor a formal PDF receipt, please contact the PG office.")
    return "\n".join(lines)


async def _unknown(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    greeting = time_greeting()
    return (
        f"{greeting}, {ctx.name}! I didn't quite get that.\n\n"
        "I can help you with:\n"
        "• *my balance* — this month's dues\n"
        "• *my payments* — payment history (by month)\n"
        "• *my details* — your room info\n"
        "• *wifi password* — WiFi details\n"
        "• *complaint* — report an issue\n"
        "• *I'm leaving* — give notice to vacate\n\n"
        "Type *help* for full menu."
    )


# ── Onboarding form (called from chat_api before intent detection) ─────────────

_ONBOARDING_STEPS = [
    "ask_dob",
    "ask_father_name",
    "ask_father_phone",
    "ask_address",
    "ask_email",
    "ask_occupation",
    "ask_gender",
    "ask_emergency_name",
    "ask_emergency_relationship",
    "ask_emergency_phone",
    "ask_id_type",
    "ask_id_number",
    "done",
]

_ONBOARDING_QUESTIONS = {
    "ask_dob":                    "Your *date of birth* (DD/MM/YYYY):",
    "ask_father_name":            "Your *father's full name*:",
    "ask_father_phone":           "Your *father's phone number* (10 digits):",
    "ask_address":                "Your *permanent home address* (full address):",
    "ask_email":                  "Your *email address* (or type *skip*):",
    "ask_occupation":             "Your current *job or institution name* (e.g. Infosys / Christ University / skip):",
    "ask_gender":                 "Your *gender*?\nReply: *male* / *female* / *other*",
    "ask_emergency_name":         "Your *emergency contact name* (parent / sibling / friend):",
    "ask_emergency_relationship": "Their *relationship* to you?\n(e.g. Father / Mother / Sibling / Friend)",
    "ask_emergency_phone":        "Their *phone number* (10 digits):",
    "ask_id_type":                "Your *ID proof type*?\nReply: *aadhar* / *passport* / *pan* / *driving license*",
    "ask_id_number":       "Your *ID proof number*:",
}


async def get_active_onboarding(tenant_id: int, session: AsyncSession):
    """Return the active OnboardingSession for this tenant, or None."""
    result = await session.execute(
        select(OnboardingSession).where(
            OnboardingSession.tenant_id == tenant_id,
            OnboardingSession.completed == False,
            OnboardingSession.expires_at > datetime.utcnow(),
        ).order_by(OnboardingSession.created_at.desc())
    )
    return result.scalars().first()


async def handle_onboarding_step(
    ob: OnboardingSession,
    reply_text: str,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:
    """
    Process one step of the onboarding form.
    Saves the answer, advances to the next step, returns the next question.
    On the final step, saves all collected data to the Tenant record.
    """
    from src.database.models import Tenant as _Tenant  # avoid circular at module level

    step     = ob.step
    data     = json.loads(ob.collected_data or "{}")
    ans      = reply_text.strip()

    # Save the answer for the current step
    skip = ans.lower() in ("skip", "na", "n/a", "-", ".")
    if step == "ask_dob":
        data["dob"] = None if skip else ans
    elif step == "ask_father_name":
        data["father_name"] = None if skip else ans
    elif step == "ask_father_phone":
        if not skip:
            digits = "".join(filter(str.isdigit, ans))
            data["father_phone"] = digits[-10:] if len(digits) >= 10 else digits
    elif step == "ask_address":
        data["address"] = None if skip else ans
    elif step == "ask_email":
        data["email"] = None if skip else ans
    elif step == "ask_occupation":
        data["occupation"] = None if skip else ans
    elif step == "ask_gender":
        g = ans.lower()
        data["gender"] = "male" if "male" in g else ("female" if "female" in g else "other")
    elif step == "ask_emergency_name":
        data["emergency_name"] = ans
    elif step == "ask_emergency_relationship":
        data["emergency_relationship"] = None if skip else ans.title()
    elif step == "ask_emergency_phone":
        digits = "".join(filter(str.isdigit, ans))
        data["emergency_phone"] = digits[-10:] if len(digits) >= 10 else digits
    elif step == "ask_id_type":
        a = ans.lower()
        if "aadhar" in a or "aadhaar" in a or "adhar" in a:
            data["id_type"] = "Aadhar"
        elif "passport" in a:
            data["id_type"] = "Passport"
        elif "pan" in a:
            data["id_type"] = "PAN Card"
        elif "driving" in a or "license" in a or "dl" in a:
            data["id_type"] = "Driving License"
        elif "voter" in a or "voter id" in a:
            data["id_type"] = "Voter ID"
        elif "ration" in a:
            data["id_type"] = "Ration Card"
        else:
            data["id_type"] = ans.title()
    elif step == "ask_id_number":
        data["id_number"] = ans.upper()

    # Advance to next step
    try:
        next_step = _ONBOARDING_STEPS[_ONBOARDING_STEPS.index(step) + 1]
    except (ValueError, IndexError):
        next_step = "done"

    ob.step = next_step
    ob.collected_data = json.dumps(data)

    if next_step == "done":
        # Save all collected data to Tenant record
        tenant = await session.get(_Tenant, ob.tenant_id)
        if tenant:
            from datetime import date as _date
            tenant.gender                             = data.get("gender")
            tenant.father_name                        = data.get("father_name")
            tenant.father_phone                       = data.get("father_phone")
            tenant.permanent_address                  = data.get("address")
            tenant.email                              = data.get("email")
            tenant.occupation                         = data.get("occupation")
            tenant.emergency_contact_name             = data.get("emergency_name")
            tenant.emergency_contact_relationship     = data.get("emergency_relationship")
            tenant.emergency_contact_phone            = data.get("emergency_phone")
            tenant.id_proof_type                      = data.get("id_type")
            tenant.id_proof_number                    = data.get("id_number")
            # Parse DOB if provided (DD/MM/YYYY)
            dob_str = data.get("dob")
            if dob_str:
                try:
                    parts = dob_str.replace("-", "/").split("/")
                    if len(parts) == 3:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                        tenant.date_of_birth = _date(y, m, d)
                except (ValueError, AttributeError):
                    pass
        ob.completed = True
        return (
            f"*Thank you, {ctx.name}!* Your details have been saved.\n\n"
            "The PG team will confirm your check-in shortly.\n\n"
            "You can now use this number to:\n"
            "• Check your *balance*\n"
            "• View *payment history*\n"
            "• Register a *complaint*\n\n"
            "Welcome to the PG! "
        )

    return (
        f"Got it! ✓\n\n"
        f"*Step {_ONBOARDING_STEPS.index(next_step) + 1} of {len(_ONBOARDING_STEPS) - 1}*\n"
        f"{_ONBOARDING_QUESTIONS[next_step]}"
    )
