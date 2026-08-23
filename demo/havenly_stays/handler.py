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

import json
import os
import re
from datetime import date, datetime, timedelta

import dateparser
from loguru import logger
from sqlalchemy import select

from demo.havenly_stays import intents as ix
from demo.havenly_stays.calendar_booking import book_visit_event
from demo.havenly_stays.db import get_session
from demo.havenly_stays.llm import call_groq_json
from demo.havenly_stays.models import Lead, LeadSession, Message, Room, VisitBooking
from demo.havenly_stays.whatsapp_send import send_demo_whatsapp

PROPERTY_NAME = "Havenly Stays"
LOCATION = "Ariana"
IDLE_RESET_MINUTES = 30
HISTORY_LIMIT = 30
OWNER_PHONE = os.getenv("HAVENLY_OWNER_PHONE") or os.getenv("HAVENLY_ADMIN_PHONE") or os.getenv("ADMIN_PHONE")

GREETING_REPLY = (
    f"Hi there! 👋 Welcome to {PROPERTY_NAME}, {LOCATION}! 🏠\n"
    "I'd love to help — ask me about room pricing, availability, or let's book you a visit! 😊"
)

_INTERPRET_PROMPT = (
    f"You are extracting structured info from a WhatsApp message sent to {PROPERTY_NAME}, "
    f"a PG accommodation in {LOCATION}. Today's date is __TODAY__.\n\n"
    'Respond with ONLY strict JSON, no markdown fences: {"intent": "GREETING"|"PRICING"|"AVAILABILITY"|"VISIT_REQUEST"|"OTHER", '
    '"room_type": "Single"|"Double Sharing"|"Triple Sharing"|null, "month": <1-12 integer or null>, '
    '"visit_date": "<YYYY-MM-DD or null>", "visit_time": "<HH:MM 24hr or null>"}\n\n'
    "room_type: match ANY natural phrasing, not just exact words — \"a single\", \"solo stay\", \"single sharing\", "
    "\"1 person room\" all mean Single; \"sharing with one other person\", \"2 sharing\" mean Double Sharing; "
    "\"3 sharing\" means Triple Sharing. null if no room type is mentioned or implied.\n\n"
    "month: the move-in month as 1-12, resolving relative phrases (\"next month\", \"this month\", \"in 3 weeks\") "
    "against today's date above. null if no timeframe is mentioned.\n\n"
    "visit_date / visit_time: if the guest has stated (in this message OR earlier in the conversation "
    "below) a specific date/time they'd like to visit — e.g. \"1st of September\", \"next Friday at 3pm\" — "
    "resolve it against today's date and fill these in. Only fill visit_time if a clock time was actually "
    "given. null/null if no specific visit date was ever mentioned.\n\n"
    "intent: GREETING = just a hello with no question. PRICING = asking cost/rent. "
    "AVAILABILITY = asking if/when a room is free. VISIT_REQUEST = wants to visit/tour in person. "
    "OTHER = anything else (small talk is handled separately before this).\n\n"
    "Use the recent conversation below to resolve references like 'it', 'that one', or a bare "
    "follow-up question — if a room type or visit date was already established earlier, carry it "
    "forward even if this message doesn't restate it.\n\n"
    "Recent conversation (oldest first, may be empty for a new guest):\n__HISTORY__\n\n"
    "Guest's latest message: __MESSAGE__"
)

_UNCLEAR_PROMPT = (
    f"You are the WhatsApp receptionist for {PROPERTY_NAME}, a PG (paying guest) accommodation "
    f"in {LOCATION}. Your personality is warm, friendly, and casual — like a helpful human texting "
    "back, not a formal bot. Use light, natural emoji occasionally (never more than one or two per "
    "message, never forced). You only have real information about room pricing, room availability, "
    "and booking a visit. Never invent facts (amenities, policies, deposit rules, food, wifi, pets, "
    "negotiating price, etc.) that weren't given to you.\n\n"
    "A guest just sent a message that didn't match your normal pricing/availability/visit flow. "
    "Decide exactly ONE of two actions:\n"
    '- "clarify": the message is still about pricing, availability, or a visit, but you need ONE '
    "more piece of information to help (e.g. they mentioned a stay duration and check-in date but "
    "no room type). Ask exactly one short, warm, natural question — never two questions in one message.\n"
    '- "escalate": the message needs something you genuinely can\'t answer (policies, negotiating, '
    "complaints, anything outside pricing/availability/visit-booking). Write one short, warm sentence "
    "acknowledging what they asked, with no question in it — the caller will separately ask permission "
    "to forward it to the owner.\n\n"
    'Respond with ONLY strict JSON, no markdown fences: {"action": "clarify"|"escalate", "reply": "..."}\n\n'
    "Recent conversation (oldest first, may be empty for a new guest):\n__HISTORY__\n\n"
    "Guest's latest message: __MESSAGE__"
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

        # Cross-process serialization: this server runs multiple uvicorn
        # workers, and Meta's duplicate webhook deliveries can land on
        # different processes at nearly the same time — the in-memory
        # per-phone lock in webhook_handler.py only protects within one
        # process. A row lock blocks a concurrent transaction on this same
        # LeadSession row until this one commits, closing that gap (this is
        # exactly what caused a confirmed booking's datetime to vanish from
        # context between two messages). No-op on SQLite (local dev/tests).
        if session.bind.dialect.name != "sqlite":
            await session.execute(
                select(LeadSession).where(LeadSession.id == lead_session.id).with_for_update()
            )

        if lead_session.last_active_at and (datetime.utcnow() - lead_session.last_active_at) > timedelta(minutes=IDLE_RESET_MINUTES):
            lead_session.pending_field = None
            lead_session.context = {}
        lead_session.last_active_at = datetime.utcnow()

        session.add(Message(phone=phone, role="guest", text=text[:2000]))

        if os.getenv("HAVENLY_SCRIPTED_DEMO", "1") == "1":
            from demo.havenly_stays.script import run_script
            reply = await run_script(text, lead, lead_session, session)
        else:
            history = await _load_history(session, phone)
            reply = await _route(text, lead, lead_session, session, history)

        session.add(Message(phone=phone, role="bot", text=reply[:2000]))
        return reply


async def _load_history(db, phone: str) -> str:
    """Last HISTORY_LIMIT messages for this phone, oldest first — so a
    returning guest (same session or days later) gets replies informed by
    what was already discussed, not a blank slate."""
    rows = (await db.execute(
        select(Message).where(Message.phone == phone).order_by(Message.created_at.desc()).limit(HISTORY_LIMIT)
    )).scalars().all()
    rows = list(reversed(rows))
    if not rows:
        return "(no prior messages)"
    return "\n".join(f"{'Guest' if r.role == 'guest' else 'You'}: {r.text}" for r in rows)


_REPROMPTS = {
    "room_type_for_pricing": "Which room type did you want pricing for — Single, Double Sharing, or Triple Sharing?",
    "month_for_availability": "Which month were you thinking of moving in?",
    "visit_name": "What's your name, so I can set up the visit?",
    "visit_email": "What email should I send the visit invite to?",
    "visit_datetime": "What date and time works for your visit? (Mon-Fri, 12:30 PM - 8:30 PM)",
    "visit_time_only": "What time works for you? (12:30 PM - 8:30 PM)",
    "visit_confirm": "Should I go ahead and book that visit? (yes/no)",
    "escalate_confirm": "Should I pass your message along to the property owner? (yes/no)",
}


async def _interpret(text: str, history: str = "(no prior messages)") -> dict:
    """Single LLM call replacing brittle keyword matching for topic + entity
    detection — understands 'a single', 'solo stay', 'sharing with one other
    person', 'next month', etc. instead of requiring exact keywords. `history`
    lets it resolve references to earlier turns instead of treating every
    message as a blank slate."""
    default = {"intent": "OTHER", "room_type": None, "month": None, "visit_date": None, "visit_time": None}
    try:
        prompt = (
            _INTERPRET_PROMPT.replace("__TODAY__", date.today().isoformat())
            .replace("__HISTORY__", history)
            .replace("__MESSAGE__", text)
        )
        raw = await call_groq_json(prompt)
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)

        visit_date = None
        if re.match(r"^\d{4}-\d{2}-\d{2}$", str(parsed.get("visit_date") or "")):
            try:
                visit_date = date.fromisoformat(parsed["visit_date"])
            except ValueError:
                visit_date = None
        visit_time = parsed.get("visit_time") if re.match(r"^\d{2}:\d{2}$", str(parsed.get("visit_time") or "")) else None

        return {
            "intent": parsed.get("intent") if parsed.get("intent") in
                ("GREETING", "PRICING", "AVAILABILITY", "VISIT_REQUEST", "OTHER") else "OTHER",
            "room_type": parsed.get("room_type") if parsed.get("room_type") in
                ("Single", "Double Sharing", "Triple Sharing") else None,
            "month": parsed.get("month") if isinstance(parsed.get("month"), int) and 1 <= parsed.get("month") <= 12 else None,
            "visit_date": visit_date,
            "visit_time": visit_time,
        }
    except Exception as e:
        logger.warning(f"[Demo] interpret failed: {e}")
        return default


_GREETING_RESET_RE = re.compile(r"^\s*(hi+|hello+|hey+|helo)[.!]*\s*$", re.I)


async def _route(text: str, lead: Lead, sess: LeadSession, db, history: str) -> str:
    # A bare greeting ALWAYS restarts the conversation, no matter what we
    # were mid-flow waiting on — a guest typing "hi" expects to start fresh,
    # not have it swallowed as an answer to some earlier question.
    if _GREETING_RESET_RE.match(text or ""):
        sess.pending_field = None
        sess.context = {}
        return GREETING_REPLY

    intent = ix.classify(text)

    # Small talk stays regex-only — cheap, reliable, no need for an LLM call
    # to recognise "thanks". Short-circuits even mid-flow so it doesn't get
    # force-fit into whatever slot we were waiting on.
    if intent == ix.INTENT_THANKS:
        if sess.pending_field:
            return f"You're welcome! 😊 {_REPROMPTS.get(sess.pending_field, 'Anything else I can help with?')}"
        return "You're welcome! 😊 Anything else I can help with?"

    if intent == ix.INTENT_CLOSING:
        sess.pending_field = None
        sess.context = {}
        return "Sounds good — feel free to message anytime! Have a great day! 👋"

    if sess.pending_field:
        return await _handle_pending(text, lead, sess, db, history)

    # A bare "yes"/"ok" right after we suggested booking a visit means:
    # accept that offer — not a fresh, context-free message.
    if ix.classify(text) == ix.INTENT_CONFIRM and (sess.context or {}).get("suggested_action") == "visit":
        sess.context = {**(sess.context or {}), "suggested_action": None}
        return await _start_visit_flow(lead, sess)

    parsed = await _interpret(text, history)
    topic, room_type, month = parsed["intent"], parsed["room_type"], parsed["month"]

    # If this message doesn't restate a room type, fall back to whichever
    # one was already established earlier in the conversation — "is it
    # available from the 10th?" after discussing Single shouldn't forget.
    room_type = room_type or (sess.context or {}).get("interest")

    if topic == "GREETING":
        return GREETING_REPLY

    if topic == "PRICING":
        if not room_type:
            sess.pending_field = "room_type_for_pricing"
            return "Sure — which room type are you asking about? Single, Double Sharing, or Triple Sharing?"
        sess.context = {**(sess.context or {}), "interest": room_type}
        return _mark_visit_suggested(sess, await _price_reply(room_type, db))

    if topic == "AVAILABILITY":
        if room_type:
            sess.context = {**(sess.context or {}), "interest": room_type}
        if not month:
            sess.pending_field = "month_for_availability"
            sess.context = {**(sess.context or {}), "room_type_filter": room_type}
            return "Which month are you looking to move in?"
        return _mark_visit_suggested(sess, await _availability_reply(month, db, room_type=room_type))

    if topic == "VISIT_REQUEST":
        if parsed["visit_date"]:
            ctx = {**(sess.context or {}), "known_visit_date": parsed["visit_date"].isoformat()}
            if parsed["visit_time"]:
                ctx["known_visit_time"] = parsed["visit_time"]
            sess.context = ctx
        return await _start_visit_flow(lead, sess)

    return await _handle_unclear(text, lead, sess, history)


def _mark_visit_suggested(sess: LeadSession, reply: str) -> str:
    """Remember that we just offered a visit booking, so a bare 'yes' next
    turn is understood as accepting it rather than falling through to the
    LLM's generic unclear-message handling."""
    if "book a visit" in reply.lower():
        sess.context = {**(sess.context or {}), "suggested_action": "visit"}
    return reply


async def _handle_unclear(text: str, lead: Lead, sess: LeadSession, history: str) -> str:
    """Anything that isn't a recognised intent: the LLM decides between
    asking ONE clarifying question (still in scope: pricing/availability/
    visit, just missing a detail) or escalating (genuinely out of scope) —
    never both in the same message."""
    action, reply = "escalate", "I'm not totally sure about that one."
    try:
        raw = await call_groq_json(_UNCLEAR_PROMPT.replace("__HISTORY__", history).replace("__MESSAGE__", text))
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        if parsed.get("action") in ("clarify", "escalate") and parsed.get("reply"):
            action, reply = parsed["action"], parsed["reply"].strip()
    except Exception as e:
        logger.warning(f"[Demo] unclear-message decision failed: {e}")

    if action == "clarify":
        # No pending_field set — the guest's next message may answer with
        # new entities (room type, date, etc.) that re-enter the normal
        # regex flow on its own, or land here again for another single
        # clarifying question. Never a second question stacked on top.
        return reply

    sess.pending_field = "escalate_confirm"
    sess.context = {**(sess.context or {}), "escalate_text": text}
    return f"{reply} Want me to pass this along to the property owner so they can help directly? 🙋"


async def _price_reply(room_type: str, db) -> str:
    room = await db.scalar(select(Room).where(Room.room_type == room_type))
    if not room:
        return f"Sorry, I don't have pricing for {room_type} right now."
    return (
        f"💰 *{room.room_type}* at {PROPERTY_NAME}, {LOCATION}: Rs. {room.price_monthly:,}/month.\n"
        "Want to check availability, or book a visit? 🙂"
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
            f"✅ Yes — *{r.room_type}* is available from {target.strftime('%B %Y')} "
            f"(Rs. {r.price_monthly:,}/month).\n\n"
            "How long are you planning to stay, and would you like to book a visit? 🏡"
        )

    lines = [f"- {r.room_type}: Rs. {r.price_monthly:,}/month" for r in available]
    return f"Available from {target.strftime('%B %Y')}:\n" + "\n".join(lines) + "\n\nWant to book a visit? 🙂"


async def _start_visit_flow(lead: Lead, sess: LeadSession) -> str:
    if not lead.name:
        sess.pending_field = "visit_name"
        return "Great, let's set up a visit! 🎉 What's your name?"
    if not lead.email:
        sess.pending_field = "visit_email"
        return f"Thanks {lead.name}! 😊 What email should I send the visit invite to? 📧"

    # If a date/time was already mentioned (this message or earlier in the
    # conversation), don't re-ask for it — only ask for whatever's missing.
    ctx = sess.context or {}
    known_date = ctx.get("known_visit_date")
    known_time = ctx.get("known_visit_time")

    if known_date and known_time:
        dt = datetime.fromisoformat(f"{known_date}T{known_time}:00")
        sess.context = {**ctx, "visit_datetime": dt.isoformat()}
        sess.pending_field = "visit_confirm"
        return (
            f"Just to confirm — visit on {dt.strftime('%d %b %Y, %I:%M %p')} "
            f"at {PROPERTY_NAME}, {LOCATION}. Shall I book it? ✅ (yes/no)"
        )

    if known_date:
        sess.pending_field = "visit_time_only"
        return (
            f"Got it, {date.fromisoformat(known_date).strftime('%d %b %Y')} works! "
            "🕒 We do visits 12:30 PM – 8:30 PM — what time works for you?"
        )

    sess.pending_field = "visit_datetime"
    return (
        "🕒 We do visits Monday to Friday, 12:30 PM – 8:30 PM. "
        "What date and time works for you? (e.g. '28 August 4pm')"
    )


async def _notify_owner(text: str, lead: Lead, interest: str = None) -> bool:
    if not OWNER_PHONE:
        logger.warning("[Demo] No HAVENLY_OWNER_PHONE/HAVENLY_ADMIN_PHONE/ADMIN_PHONE set — cannot forward to owner.")
        return False
    interest = interest or "Not specified"
    msg = (
        f"[Havenly Stays demo] A guest needs your help:\n"
        f"Name: {lead.name or 'Not provided'}\n"
        f"Phone: {lead.phone}\n"
        f"Interested in: {interest}\n"
        f"Concern: {text}"
    )
    try:
        await send_demo_whatsapp(OWNER_PHONE, msg)
        return True
    except Exception as e:
        logger.warning(f"[Demo] Owner notify failed: {e}")
        return False


async def _handle_pending(text: str, lead: Lead, sess: LeadSession, db, history: str) -> str:
    field = sess.pending_field

    if field == "room_type_for_pricing":
        parsed = await _interpret(text, history)
        room_type = parsed["room_type"]
        if not room_type:
            return "Sorry, I didn't catch that — Single, Double Sharing, or Triple Sharing?"
        sess.pending_field = None
        sess.context = {**(sess.context or {}), "interest": room_type}
        return _mark_visit_suggested(sess, await _price_reply(room_type, db))

    if field == "month_for_availability":
        parsed = await _interpret(text, history)
        month = parsed["month"]
        if not month:
            return "Sorry, which month did you mean? (e.g. September, or 'next month')"
        room_type = (sess.context or {}).get("room_type_filter") or parsed["room_type"]
        sess.pending_field = None
        sess.context = {"interest": room_type} if room_type else {}
        return _mark_visit_suggested(sess, await _availability_reply(month, db, room_type=room_type))

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
        sess.context = {**(sess.context or {}), "visit_datetime": parsed.isoformat()}
        sess.pending_field = "visit_confirm"
        return (
            f"Just to confirm — visit on {parsed.strftime('%d %b %Y, %I:%M %p')} "
            f"at {PROPERTY_NAME}, {LOCATION}. Shall I book it? ✅ (yes/no)"
        )

    if field == "visit_time_only":
        parsed_time = dateparser.parse(text, settings={"PREFER_DATES_FROM": "future"})
        if not parsed_time:
            return "Sorry, what time works for you? (e.g. '3pm')"
        ctx = sess.context or {}
        known_date = date.fromisoformat(ctx["known_visit_date"])
        dt = datetime.combine(known_date, parsed_time.time())
        sess.context = {**ctx, "visit_datetime": dt.isoformat()}
        sess.pending_field = "visit_confirm"
        return (
            f"Just to confirm — visit on {dt.strftime('%d %b %Y, %I:%M %p')} "
            f"at {PROPERTY_NAME}, {LOCATION}. Shall I book it? ✅ (yes/no)"
        )

    if field == "visit_confirm":
        intent = ix.classify(text)
        if intent == ix.INTENT_CANCEL:
            sess.pending_field = None
            sess.context = {}
            return "No problem — let me know whenever you'd like to reschedule! 🙂"
        if intent != ix.INTENT_CONFIRM:
            return "Should I go ahead and book that visit? (yes/no)"

        ctx = sess.context or {}
        interest = ctx.get("interest")
        visit_datetime = ctx.get("visit_datetime")
        if not visit_datetime:
            # Defensive: should always be set by the previous step, but never
            # crash the conversation if it's somehow missing — that traps the
            # guest in a dead end (every retry hits the same error).
            sess.pending_field = "visit_datetime"
            return "Sorry, I lost track of the date for a second there — what date and time works for your visit?"
        slot = datetime.fromisoformat(visit_datetime)
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
                f"🎉 Booked! Your visit to {PROPERTY_NAME}, {LOCATION} is confirmed for "
                f"{slot.strftime('%d %b %Y, %I:%M %p')}. A calendar invite has been sent to {lead.email} 📅✨\n"
                "Looking forward to seeing you!"
            )

        # Booking call failed (slot taken / calendar not reachable) — don't
        # claim success. We still have the lead's intent recorded in our DB;
        # let the owner sort out the exact slot.
        await _notify_owner(
            f"Wants a visit on {slot.strftime('%d %b %Y, %I:%M %p')} but that slot didn't go through on the calendar — please confirm a time with them directly.",
            lead,
            interest,
        )
        return (
            f"Hmm, that exact time didn't go through on our calendar — it might already be booked. 🙏 "
            f"I've let the owner know you'd like a visit around {slot.strftime('%d %b %Y, %I:%M %p')} "
            "and they'll confirm a time with you directly."
        )

    if field == "escalate_confirm":
        intent = ix.classify(text)
        if intent == ix.INTENT_CANCEL:
            sess.pending_field = None
            sess.context = {}
            return "No problem! Anything else I can help with? 😊"
        if intent != ix.INTENT_CONFIRM:
            return "Just to confirm — should I pass your message along to the property owner? (yes/no)"

        ctx = sess.context or {}
        original_text = ctx.get("escalate_text", "")
        interest = ctx.get("interest")
        sess.pending_field = None
        sess.context = {}
        sent = await _notify_owner(original_text, lead, interest)
        if sent:
            return "Done! ✅ I've let the owner know, they'll follow up with you directly. Anything else I can help with?"
        return "I noted that down for the owner to review. Anything else I can help with?"

    sess.pending_field = None
    return "Sorry, let's start over — are you asking about pricing, availability, or a visit?"
