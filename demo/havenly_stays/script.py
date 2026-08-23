"""
Deterministic scripted flow for a reliable, camera-ready demo.

Every step advances unconditionally on the next message — it does NOT try
to understand what you typed, it just plays the next line, except where it
genuinely needs to capture real data (name, email, date/time), which is
parsed deterministically (regex email, dateparser date — both already
proven reliable in isolation). The final visit booking still calls the
REAL Cal.com API with your real name/email/date — only the conversational
routing is scripted, not the underlying data.

This trades "understands anything you say" for "never breaks on camera."
Toggle with HAVENLY_SCRIPTED_DEMO=0 to go back to the LLM-driven handler
in handler.py.
"""
from __future__ import annotations

from datetime import datetime

import dateparser
from sqlalchemy import select

from demo.havenly_stays import intents as ix
from demo.havenly_stays.calendar_booking import book_visit_event
from demo.havenly_stays.models import Lead, LeadSession, Room, VisitBooking

PROPERTY_NAME = "Havenly Stays"
LOCATION = "Ariana"

STEP_GREETING = 0
STEP_PRICE_SINGLE = 1
STEP_AVAILABILITY_SEPT = 2
STEP_VISIT_START = 3
STEP_NAME = 4
STEP_EMAIL = 5
STEP_DATETIME = 6
STEP_CONFIRM = 7
STEP_DONE = 8

_FALLBACK_SLOT = datetime(2026, 8, 28, 16, 0)  # used only if date parsing somehow fails


async def run_script(text: str, lead: Lead, sess: LeadSession, db) -> str:
    step = (sess.context or {}).get("script_step", STEP_GREETING)
    text = (text or "").strip()

    if step == STEP_GREETING:
        sess.context = {**(sess.context or {}), "script_step": STEP_PRICE_SINGLE}
        return (
            f"Hi! Welcome to {PROPERTY_NAME}, {LOCATION}.\n"
            "I can help with room pricing, availability, or booking a visit. What would you like to know?"
        )

    if step == STEP_PRICE_SINGLE:
        room = await db.scalar(select(Room).where(Room.room_type == "Single"))
        price = f"Rs. {room.price_monthly:,}" if room else "Rs. 12,000"
        sess.context = {**(sess.context or {}), "script_step": STEP_AVAILABILITY_SEPT}
        return (
            f"*Single* at {PROPERTY_NAME}, {LOCATION}: {price}/month.\n"
            "Want to check availability, or book a visit?"
        )

    if step == STEP_AVAILABILITY_SEPT:
        room = await db.scalar(select(Room).where(Room.room_type == "Single"))
        price = f"Rs. {room.price_monthly:,}" if room else "Rs. 12,000"
        sess.context = {**(sess.context or {}), "script_step": STEP_VISIT_START}
        return (
            f"Yes — *Single* is available from September 2026 ({price}/month).\n\n"
            "Would you like to book a visit?"
        )

    if step == STEP_VISIT_START:
        sess.context = {**(sess.context or {}), "script_step": STEP_NAME}
        return "Great, let's set up a visit! What's your name?"

    if step == STEP_NAME:
        lead.name = text or "Guest"
        sess.context = {**(sess.context or {}), "script_step": STEP_EMAIL}
        return f"Thanks {lead.name}! What email should I send the visit invite to?"

    if step == STEP_EMAIL:
        lead.email = ix.extract_email(text) or text
        sess.context = {**(sess.context or {}), "script_step": STEP_DATETIME}
        return "What date and time works for your visit? (e.g. '28 August 4pm')"

    if step == STEP_DATETIME:
        parsed = dateparser.parse(text, settings={"PREFER_DATES_FROM": "future"}) or _FALLBACK_SLOT
        sess.context = {
            **(sess.context or {}),
            "script_step": STEP_CONFIRM,
            "visit_datetime": parsed.isoformat(),
        }
        return (
            f"Just to confirm — visit on {parsed.strftime('%d %b %Y, %I:%M %p')} "
            f"at {PROPERTY_NAME}, {LOCATION}. Shall I book it? (yes/no)"
        )

    if step == STEP_CONFIRM:
        ctx = sess.context or {}
        slot = datetime.fromisoformat(ctx["visit_datetime"])
        booking = VisitBooking(lead_id=lead.id, slot_datetime=slot)
        db.add(booking)
        await db.flush()

        room = await db.scalar(select(Room).where(Room.room_type == "Single"))
        price_context = f"Discussed: Single at Rs. {room.price_monthly:,}/month." if room else ""

        event_id = await book_visit_event(
            lead_name=lead.name or "Guest",
            lead_phone=lead.phone,
            lead_email=lead.email or "",
            price_context=price_context,
            slot=slot,
        )
        booking.calendar_event_id = event_id
        sess.context = {**(sess.context or {}), "script_step": STEP_DONE}

        if event_id:
            return (
                f"Booked! Your visit to {PROPERTY_NAME}, {LOCATION} is confirmed for "
                f"{slot.strftime('%d %b %Y, %I:%M %p')}. A calendar invite has been sent to {lead.email}."
            )
        return (
            f"Booked in our system for {slot.strftime('%d %b %Y, %I:%M %p')} — the calendar invite "
            "hit a snag, but the owner has the details and will confirm with you directly."
        )

    # STEP_DONE or anything unexpected — reset so another take can be recorded immediately.
    sess.context = {"script_step": STEP_GREETING}
    return (
        f"Hi again! Welcome back to {PROPERTY_NAME}, {LOCATION}. "
        "Ask me about pricing, availability, or say you'd like to book a visit."
    )
