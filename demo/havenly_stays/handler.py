"""
Havenly Stays demo receptionist — main conversation handler.

Handles: room pricing, room availability, and booking a visit (with a real
Google Calendar invite). Asks exactly one question at a time when required
info is missing, using `LeadSession.pending_field` as the single source of
truth for what we're waiting to hear back next.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import dateparser
from sqlalchemy import select

from demo.havenly_stays import intents as ix
from demo.havenly_stays.calendar_booking import book_visit_event
from demo.havenly_stays.db import get_session
from demo.havenly_stays.models import Lead, LeadSession, Room, VisitBooking
from src.llm_gateway.claude_client import get_claude_client

PROPERTY_NAME = "Havenly Stays"
LOCATION = "Ariana"
IDLE_RESET_MINUTES = 30

GREETING_REPLY = (
    f"Hi! Welcome to {PROPERTY_NAME}, {LOCATION}.\n"
    "I can help with room pricing, availability, or booking a visit. What would you like to know?"
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


async def _route(text: str, lead: Lead, sess: LeadSession, db) -> str:
    if sess.pending_field:
        return await _handle_pending(text, lead, sess, db)

    intent = ix.classify(text)

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
        if not month:
            sess.pending_field = "month_for_availability"
            return "Which month are you looking to move in?"
        return await _availability_reply(month, db)

    if intent == ix.INTENT_VISIT_REQUEST:
        return await _start_visit_flow(lead, sess)

    ai = get_claude_client()
    return await ai.ask_clarification(
        context=(
            f"You are the WhatsApp receptionist for {PROPERTY_NAME}, a PG accommodation in {LOCATION}. "
            "You only handle three things: room pricing, room availability, and booking a visit. "
            "Ask exactly ONE short, friendly clarifying question to figure out what the person wants."
        ),
        message=text,
        unclear="the message doesn't clearly match pricing, availability, or a visit request",
    )


async def _price_reply(room_type: str, db) -> str:
    room = await db.scalar(select(Room).where(Room.room_type == room_type))
    if not room:
        return f"Sorry, I don't have pricing for {room_type} right now."
    return (
        f"*{room.room_type}* at {PROPERTY_NAME}, {LOCATION}: Rs. {room.price_monthly:,}/month.\n"
        "Want to check availability, or book a visit?"
    )


async def _availability_reply(month: int, db) -> str:
    today = date.today()
    year = today.year if month >= today.month else today.year + 1
    target = date(year, month, 1)

    rooms = (await db.execute(select(Room))).scalars().all()
    available = [r for r in rooms if r.available_beds > 0 and r.available_from <= target]

    if not available:
        return (
            f"Sorry, nothing is available from {target.strftime('%B %Y')} right now. "
            "Want me to note your interest for a callback?"
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
            return "Sorry, which month did you mean? (e.g. September)"
        sess.pending_field = None
        return await _availability_reply(month, db)

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
        return (
            f"Booked! Your visit to {PROPERTY_NAME}, {LOCATION} is confirmed for "
            f"{slot.strftime('%d %b %Y, %I:%M %p')}. A calendar invite has been sent to {lead.email}."
        )

    sess.pending_field = None
    return "Sorry, let's start over — are you asking about pricing, availability, or a visit?"
