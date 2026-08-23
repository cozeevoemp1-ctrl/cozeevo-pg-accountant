"""
Havenly Stays demo receptionist — main conversation handler.

Handles: room pricing, room availability, and booking a visit (with a real
Cal.com booking). Asks exactly one question at a time when required info is
missing, using `LeadSession.pending_field` as the single source of truth for
what we're waiting to hear back next — but small talk, closing remarks, and
anything genuinely out of scope are handled conversationally rather than
forcing the caller back into a rigid slot-filling script.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import dateparser
from loguru import logger
from sqlalchemy import select

from demo.havenly_stays import intents as ix
from demo.havenly_stays.calendar_booking import book_visit_event
from demo.havenly_stays.db import get_session
from demo.havenly_stays.models import Lead, LeadSession, Room, VisitBooking
from demo.havenly_stays.whatsapp_send import send_demo_whatsapp
from src.llm_gateway.claude_client import get_claude_client

PROPERTY_NAME = "Havenly Stays"
LOCATION = "Ariana"
IDLE_RESET_MINUTES = 30
ADMIN_PHONE = os.getenv("HAVENLY_ADMIN_PHONE") or os.getenv("ADMIN_PHONE")

GREETING_REPLY = (
    f"Hi! Welcome to {PROPERTY_NAME}, {LOCATION}.\n"
    "I can help with room pricing, availability, or booking a visit. What would you like to know?"
)

_PERSONA_PROMPT = (
    f"You are the WhatsApp receptionist for {PROPERTY_NAME}, a PG (paying guest) accommodation "
    f"in {LOCATION}. Reply naturally and warmly in 1-2 short sentences, like a helpful human "
    "receptionist texting back — not a menu or a form. You only have real information about room "
    "pricing, room availability, and booking a visit. Never invent facts (amenities, policies, "
    "deposit rules, food, wifi, etc.) that weren't given to you. If the guest's message is small talk "
    "or a simple acknowledgement, just respond warmly and briefly. Do not use the phrase "
    "'clarify your request' or sound like an error message."
)


async def handle_demo_message(phone: str, text: str) -> str:
    text = (text or "").strip()
    async with get_session() as session:
        lead = await session.scalar(select(Lead).where(Lead.phone == phone))
        if lead is None:
            lead = Lead(phone=phone)
            session.add(lead)
            await session.flush()

        lead_session = await session.scalar(select(LeadSession).where(LeadSession.phone == phone))
        if lead_session is None:
            lead_session = LeadSession(phone=phone, context={})
            session.add(lead_session)
            await session.flush()

        if lead_session.last_active_at and (datetime.utcnow() - lead_session.last_active_at) > timedelta(minutes=IDLE_RESET_MINUTES):
            lead_session.pending_field = None
            lead_session.context = {}
        lead_session.last_active_at = datetime.utcnow()

        return await _route(text, lead, lead_session, session)


_REPROMPTS = {
    "room_type_for_pricing": "Which room type did you want pricing for — Single, Double Sharing, or Triple Sharing?",
    "month_for_availability": "Which month were you thinking of moving in?",
    "visit_name": "What's your name, so I can set up the visit?",
    "visit_email": "What email should I send the visit invite to?",
    "visit_datetime": "What date and time works for your visit?",
    "visit_confirm": "Should I go ahead and book that visit? (yes/no)",
    "escalate_confirm": "Should I pass your message along to the property owner? (yes/no)",
}


async def _route(text: str, lead: Lead, sess: LeadSession, db) -> str:
    intent = ix.classify(text)

    # Small talk short-circuits even mid-flow — a "thanks" shouldn't get
    # force-fit into whatever slot we were waiting on.
    if intent == ix.INTENT_THANKS:
        if sess.pending_field:
            return f"You're welcome! {_REPROMPTS.get(sess.pending_field, 'Anything else I can help with?')}"
        return "You're welcome! Anything else I can help with?"

    if intent == ix.INTENT_CLOSING:
        sess.pending_field = None
        sess.context = {}
        return "Sounds good — feel free to message anytime. Have a great day!"

    if sess.pending_field:
        return await _handle_pending(text, lead, sess, db)

    if intent == ix.INTENT_GREETING:
        return GREETING_REPLY

    if intent == ix.INTENT_PRICING:
        room_type = ix.extract_room_type(text)
        if not room_type:
            sess.pending_field = "room_type_for_pricing"
            return "Sure — which room type are you asking about? Single, Double Sharing, or Triple Sharing?"
        return await _price_reply(room_type, db)

    if intent == ix.INTENT_AVAILABILITY:
        month = ix.extract_month(text)
        room_type = ix.extract_room_type(text)
        if not month:
            sess.pending_field = "month_for_availability"
            sess.context = {**(sess.context or {}), "room_type_filter": room_type}
            return "Which month are you looking to move in?"
        return await _availability_reply(month, db, room_type=room_type)

    if intent == ix.INTENT_VISIT_REQUEST:
        return await _start_visit_flow(lead, sess)

    return await _handle_unclear(text, lead, sess)


async def _handle_unclear(text: str, lead: Lead, sess: LeadSession) -> str:
    """Anything that isn't a recognised intent: reply naturally via the LLM
    (never fabricating facts), then offer — once, with the guest's consent —
    to forward it to the property owner rather than dead-ending on a
    'please clarify' error."""
    ai = get_claude_client()
    try:
        natural_reply = await ai._call(f"{_PERSONA_PROMPT}\n\nGuest's message: {text}\n\nYour reply:")
        natural_reply = natural_reply.strip()
    except Exception as e:
        logger.warning(f"[Demo] persona reply failed: {e}")
        natural_reply = "I'm not totally sure about that one."

    sess.pending_field = "escalate_confirm"
    sess.context = {**(sess.context or {}), "escalate_text": text}
    return f"{natural_reply} Want me to pass this along to the property owner so they can help directly?"


async def _price_reply(room_type: str, db) -> str:
    room = await db.scalar(select(Room).where(Room.room_type == room_type))
    if not room:
        return f"Sorry, I don't have pricing for {room_type} right now."
    return (
        f"*{room.room_type}* at {PROPERTY_NAME}, {LOCATION}: Rs. {room.price_monthly:,}/month.\n"
        "Want to check availability, or book a visit?"
    )


async def _availability_reply(month: int, db, room_type: str = None) -> str:
    today = date.today()
    year = today.year if month >= today.month else today.year + 1
    target = date(year, month, 1)

    rooms = (await db.execute(select(Room))).scalars().all()
    if room_type:
        rooms = [r for r in rooms if r.room_type == room_type]
    # Compare by (year, month) — a room opening up mid-month (e.g. today,
    # the 23rd) still counts as "available this month," not just from day 1.
    available = [
        r for r in rooms
        if r.available_beds > 0 and (r.available_from.year, r.available_from.month) <= (target.year, target.month)
    ]

    if not available:
        subject = room_type or "a room"
        return (
            f"Sorry, {subject} isn't available from {target.strftime('%B %Y')}. "
            "Want me to note your interest for a callback, or check a different room type?"
        )

    if len(available) == 1:
        r = available[0]
        return (
            f"Yes — *{r.room_type}* is available from {target.strftime('%B %Y')} "
            f"(Rs. {r.price_monthly:,}/month, {r.available_beds} bed(s) open from {r.available_from.strftime('%d %b %Y')}).\n\n"
            "How long are you planning to stay, and would you like to book a visit?"
        )

    lines = [
        f"- {r.room_type}: Rs. {r.price_monthly:,}/month ({r.available_beds} bed(s) open from {r.available_from.strftime('%d %b %Y')})"
        for r in available
    ]
    return f"Available from {target.strftime('%B %Y')}:\n" + "\n".join(lines) + "\n\nWant to book a visit?"


async def _start_visit_flow(lead: Lead, sess: LeadSession) -> str:
    if not lead.name:
        sess.pending_field = "visit_name"
        return "Great, let's set up a visit! What's your name?"
    if not lead.email:
        sess.pending_field = "visit_email"
        return f"Thanks {lead.name}! What email should I send the visit invite to?"
    sess.pending_field = "visit_datetime"
    return "What date and time works for your visit? (e.g. '28 August 4pm')"


async def _notify_admin(text: str, lead: Lead) -> bool:
    if not ADMIN_PHONE:
        logger.warning("[Demo] No HAVENLY_ADMIN_PHONE/ADMIN_PHONE set — cannot forward to owner.")
        return False
    msg = (
        f"[Havenly Stays demo] A guest needs help:\n"
        f"From: {lead.name or 'Unknown'} ({lead.phone})\n"
        f"Message: {text}"
    )
    try:
        await send_demo_whatsapp(ADMIN_PHONE, msg)
        return True
    except Exception as e:
        logger.warning(f"[Demo] Admin notify failed: {e}")
        return False


async def _handle_pending(text: str, lead: Lead, sess: LeadSession, db) -> str:
    field = sess.pending_field

    if field == "room_type_for_pricing":
        room_type = ix.extract_room_type(text)
        if not room_type:
            return "Sorry, I didn't catch that — Single, Double Sharing, or Triple Sharing?"
        sess.pending_field = None
        return await _price_reply(room_type, db)

    if field == "month_for_availability":
        month = ix.extract_month(text)
        if not month:
            return "Sorry, which month did you mean? (e.g. September, or 'next month')"
        room_type = (sess.context or {}).get("room_type_filter")
        sess.pending_field = None
        sess.context = {}
        return await _availability_reply(month, db, room_type=room_type)

    if field == "visit_name":
        name = text.strip()
        if len(name) < 2:
            return "Sorry, what's your name?"
        lead.name = name
        return await _start_visit_flow(lead, sess)

    if field == "visit_email":
        email = ix.extract_email(text)
        if not email:
            return "That doesn't look like a valid email — could you share it again?"
        lead.email = email
        return await _start_visit_flow(lead, sess)

    if field == "visit_datetime":
        parsed = dateparser.parse(text, settings={"PREFER_DATES_FROM": "future"})
        if not parsed:
            return "Sorry, I couldn't understand that date/time — try something like '28 August 4pm'."
        ctx = sess.context or {}
        ctx["visit_datetime"] = parsed.isoformat()
        sess.context = ctx
        sess.pending_field = "visit_confirm"
        return (
            f"Just to confirm — visit on {parsed.strftime('%d %b %Y, %I:%M %p')} "
            f"at {PROPERTY_NAME}, {LOCATION}. Shall I book it? (yes/no)"
        )

    if field == "visit_confirm":
        intent = ix.classify(text)
        if intent == ix.INTENT_CANCEL:
            sess.pending_field = None
            sess.context = {}
            return "No problem — let me know whenever you'd like to reschedule."
        if intent != ix.INTENT_CONFIRM:
            return "Should I go ahead and book that visit? (yes/no)"

        ctx = sess.context or {}
        slot = datetime.fromisoformat(ctx["visit_datetime"])
        booking = VisitBooking(lead_id=lead.id, slot_datetime=slot)
        db.add(booking)
        await db.flush()

        price_context = ""
        room = await db.scalar(select(Room))
        if room:
            price_context = f"Discussed: {room.room_type} at Rs. {room.price_monthly:,}/month."

        event_id = await book_visit_event(
            lead_name=lead.name or "Guest",
            lead_phone=lead.phone,
            lead_email=lead.email or "",
            price_context=price_context,
            slot=slot,
        )
        booking.calendar_event_id = event_id

        sess.pending_field = None
        sess.context = {}

        if event_id:
            return (
                f"Booked! Your visit to {PROPERTY_NAME}, {LOCATION} is confirmed for "
                f"{slot.strftime('%d %b %Y, %I:%M %p')}. A calendar invite has been sent to {lead.email}."
            )

        # Booking call failed (slot taken / calendar not reachable) — don't
        # claim success. We still have the lead's intent recorded in our DB;
        # let the owner sort out the exact slot.
        await _notify_admin(
            f"Wants a visit on {slot.strftime('%d %b %Y, %I:%M %p')} but that slot didn't go through on the calendar — please confirm a time with them directly.",
            lead,
        )
        return (
            f"Hmm, that exact time didn't go through on our calendar — it might already be booked. "
            f"I've let the owner know you'd like a visit around {slot.strftime('%d %b %Y, %I:%M %p')} "
            "and they'll confirm a time with you directly."
        )

    if field == "escalate_confirm":
        intent = ix.classify(text)
        if intent == ix.INTENT_CANCEL:
            sess.pending_field = None
            sess.context = {}
            return "No problem! Anything else I can help with?"
        if intent != ix.INTENT_CONFIRM:
            return "Just to confirm — should I pass your message along to the property owner? (yes/no)"

        original_text = (sess.context or {}).get("escalate_text", "")
        sess.pending_field = None
        sess.context = {}
        sent = await _notify_admin(original_text, lead)
        if sent:
            return "Done — I've let the owner know, they'll follow up with you directly. Anything else I can help with?"
        return "I noted that down for the owner to review. Anything else I can help with?"

    sess.pending_field = None
    return "Sorry, let's start over — are you asking about pricing, availability, or a visit?"
