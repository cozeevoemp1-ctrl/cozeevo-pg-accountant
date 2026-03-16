"""
Lead handler — natural sales conversation for unknown callers.
Queries room prices from rate_cards. Saves to leads table.
Never writes to tenants/tenancies — only leads table.
Notifies owner when a lead shows strong intent (VISIT_REQUEST).
"""
from __future__ import annotations

import os
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Lead, Property, RateCard, Room, RoomType
from src.whatsapp.role_service import CallerContext
from src.whatsapp.handlers._shared import BOT_NAME, time_greeting, is_first_time_today, bot_intro


async def handle_lead(
    intent: str,
    message: str,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:

    # Upsert lead record (track the conversation)
    await _upsert_lead(ctx.phone, intent, message, session)

    handlers = {
        "ROOM_PRICE":         _room_price,
        "AVAILABILITY":       _availability,
        "ROOM_TYPE":          _room_type_info,
        "VISIT_REQUEST":      _visit_request,
        "GET_WIFI_PASSWORD":  _wifi_blocked,
        "GENERAL":            _general_chat,
    }
    fn = handlers.get(intent, _general_chat)
    return await fn(message, ctx, session)


async def _room_price(message: str, ctx: CallerContext, session: AsyncSession) -> str:
    # Pull current active rate cards
    today = date.today()
    result = await session.execute(
        select(Room, RateCard, Property)
        .join(RateCard, RateCard.room_id == Room.id)
        .join(Property, Property.id == Room.property_id)
        .where(
            RateCard.effective_to.is_(None),   # currently active rate
            Room.active == True,
        )
        .order_by(RateCard.monthly_rent)
    )
    rows = result.all()

    if not rows:
        # Fallback: show properties
        return (
            "*Cozeevo PG — Room Prices*\n\n"
            "Single occupancy: Rs.20,000 – 29,000/month\n"
            "Double sharing:   Rs.12,500 – 17,000/month\n"
            "Triple sharing:   Rs.10,000 – 13,000/month\n"
            "Premium rooms:    Rs.25,000 – 35,000/month\n\n"
            "All rooms include:\n"
            "• WiFi • Water • 24/7 security\n"
            "• Daily housekeeping\n\n"
            "Interested in a specific type? Reply:\n"
            "*single*, *double*, *triple*, or *premium*"
        )

    # Group by room type
    type_prices: dict[str, list[int]] = {}
    for room, rate_card, prop in rows:
        rt = room.room_type.value
        price = int(rate_card.monthly_rent or 0)
        type_prices.setdefault(rt, []).append(price)

    lines = ["*Cozeevo PG — Current Rates*\n"]
    type_labels = {
        "single": "Single occupancy",
        "double": "Double sharing  ",
        "triple": "Triple sharing  ",
        "premium": "Premium room    ",
    }
    for rt in ["single", "double", "triple", "premium"]:
        if rt in type_prices:
            prices = sorted(type_prices[rt])
            if len(prices) == 1:
                lines.append(f"• {type_labels[rt]}: Rs.{prices[0]:,}/month")
            else:
                lines.append(f"• {type_labels[rt]}: Rs.{prices[0]:,} – Rs.{prices[-1]:,}/month")

    lines.append("\nIncludes WiFi, water, security & housekeeping.")
    lines.append("\nWant to book a visit? Just say *visit* or *tour*")
    return "\n".join(lines)


async def _availability(message: str, ctx: CallerContext, session: AsyncSession) -> str:
    return (
        "*Room Availability*\n\n"
        "We have rooms available in both our properties:\n"
        "• Cozeevo THOR\n"
        "• Cozeevo HULK\n\n"
        "Room types available:\n"
        "• Single occupancy\n"
        "• Double sharing\n"
        "• Triple sharing\n"
        "• Premium rooms\n\n"
        "What type are you looking for?\n"
        "Reply: *single*, *double*, *triple*, or *premium*\n\n"
        "Or book a viewing: *visit*"
    )


async def _room_type_info(message: str, ctx: CallerContext, session: AsyncSession) -> str:
    msg_lower = message.lower()
    if "single" in msg_lower or "private" in msg_lower:
        return (
            "*Single Occupancy Rooms*\n\n"
            "• Fully private room\n"
            "• Attached or shared bathroom\n"
            "• From Rs.20,000/month\n"
            "• Includes WiFi, housekeeping, water\n\n"
            "Security deposit: 1 month rent\n"
            "Maintenance: Rs.5,000/month\n\n"
            "Want to see the room? Say *visit*"
        )
    elif "double" in msg_lower or "sharing" in msg_lower:
        return (
            "*Double Sharing Rooms*\n\n"
            "• 2 people per room\n"
            "• Individual beds & wardrobes\n"
            "• From Rs.12,500/month per person\n"
            "• Includes WiFi, housekeeping, water\n\n"
            "Security deposit: 1 month rent\n"
            "Maintenance: Rs.5,000/month\n\n"
            "Want to see the room? Say *visit*"
        )
    elif "triple" in msg_lower:
        return (
            "*Triple Sharing Rooms*\n\n"
            "• 3 people per room\n"
            "• Most affordable option\n"
            "• From Rs.10,000/month per person\n"
            "• Includes WiFi, housekeeping, water\n\n"
            "Want to see the room? Say *visit*"
        )
    elif "premium" in msg_lower:
        return (
            "*Premium Rooms*\n\n"
            "• Spacious private rooms\n"
            "• Attached bathroom\n"
            "• From Rs.25,000/month\n"
            "• AC included\n"
            "• Priority housekeeping\n\n"
            "Want to see the room? Say *visit*"
        )
    return await _room_price(message, ctx, session)


async def _visit_request(message: str, ctx: CallerContext, session: AsyncSession) -> str:
    # Update lead with strong intent signal
    result = await session.execute(
        select(Lead).where(Lead.phone == ctx.phone)
    )
    lead = result.scalars().first()
    today_str = date.today().strftime("%d %b %Y")
    if lead:
        lead.notes = (lead.notes or "") + f" | Visit requested on {today_str}"

    admin_phone = os.getenv("ADMIN_PHONE", "")

    # Notify admin via WhatsApp (fire-and-forget, best-effort)
    if admin_phone:
        try:
            from src.whatsapp.webhook_handler import _send_whatsapp
            lead_name = ctx.name or ctx.phone
            await _send_whatsapp(
                admin_phone,
                f"🔔 *New Visit Request*\n"
                f"From  : {lead_name} ({ctx.phone})\n"
                f"Date  : {today_str}\n"
                f"Message: {message[:120]}\n\n"
                f"Reply to schedule the visit.",
            )
        except Exception:
            pass  # Don't fail the lead response if notification fails

    return (
        "*Great! Let's arrange a visit.* 🏠\n\n"
        "Please share:\n"
        "1. Your name\n"
        "2. Preferred date & time\n"
        "3. Which type of room you're interested in\n\n"
        "Our team will confirm the visit shortly.\n"
        f"You can also call us directly at {admin_phone or 'the number on our listing'}."
    )


async def _wifi_blocked(message: str, ctx: CallerContext, session: AsyncSession) -> str:
    return "WiFi details are only available to registered tenants. Please contact the owner or manager."


async def _general_chat(message: str, ctx: CallerContext, session: AsyncSession) -> str:
    header = bot_intro(await is_first_time_today(ctx.phone, session))
    return (
        f"{header}"
        "I can help you with:\n\n"
        "• Room prices → say *price* or *rent*\n"
        "• Availability → say *available*\n"
        "• Room types → say *single/double/triple/premium*\n"
        "• Book a visit → say *visit*\n\n"
        "What are you looking for?"
    )


async def _upsert_lead(phone: str, intent: str, message: str, session: AsyncSession):
    """Create or update lead record to track this conversation."""
    result = await session.execute(select(Lead).where(Lead.phone == phone))
    lead = result.scalars().first()
    now = datetime.utcnow()

    if lead:
        lead.last_message_at = now
        if intent == "ROOM_TYPE" and not lead.interested_in:
            lead.interested_in = message[:80]
    else:
        session.add(Lead(
            phone=phone,
            last_message_at=now,
            interested_in=message[:80] if intent in ("ROOM_TYPE", "ROOM_PRICE") else None,
        ))
