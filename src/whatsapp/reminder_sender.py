"""
Reminder Sender — Official WhatsApp Business Number
====================================================
Sends template-based messages via a SEPARATE WhatsApp Business number
(the official Indian number) used exclusively for outbound reminders.

Meta requires approved Message Templates for proactive messages sent
outside the 24-hour customer-service window. This module handles:
  - Sending approved templates with variable parameters
  - Sending free-form text (only works within 24hr window)
  - Falling back to the bot number if official number is not configured

Template Setup (one-time, in Meta Business Manager):
  1. Go to business.facebook.com → WhatsApp Manager → Message Templates
  2. Create templates (see TEMPLATE_CATALOG below for what we use)
  3. Wait for Meta approval (24-48 hrs)
  4. Fill in REMINDER_WHATSAPP_TOKEN + REMINDER_WHATSAPP_PHONE_NUMBER_ID in .env
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
# Official number for reminders (preferred)
_REMINDER_TOKEN    = os.getenv("REMINDER_WHATSAPP_TOKEN", "")
_REMINDER_PHONE_ID = os.getenv("REMINDER_WHATSAPP_PHONE_NUMBER_ID", "")

# Bot number (fallback if official not configured)
_BOT_TOKEN    = os.getenv("WHATSAPP_TOKEN", "")
_BOT_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

_API_VERSION = "v18.0"


def _get_reminder_creds() -> tuple[str, str]:
    """Return (token, phone_id) for the reminder number, fallback to bot."""
    if _REMINDER_TOKEN and _REMINDER_PHONE_ID:
        return _REMINDER_TOKEN, _REMINDER_PHONE_ID
    logger.warning("[Reminder] Official number not configured — falling back to bot number")
    return _BOT_TOKEN, _BOT_PHONE_ID


def _clean_phone(phone: str) -> str:
    """Strip +, spaces, dashes — Meta expects plain digits like 919876543210."""
    return phone.lstrip("+").replace(" ", "").replace("-", "")


# ── Template Sender ───────────────────────────────────────────────────────────

async def send_template(
    to_number: str,
    template_name: str,
    language_code: str = "en",
    body_params: Optional[list[str]] = None,
) -> bool:
    """
    Send an approved Message Template via the official reminder number.

    Args:
        to_number:     Recipient phone (e.g. "+917845952289" or "917845952289")
        template_name: Exact name from Meta Business Manager (e.g. "rent_reminder")
        language_code: Template language (default "en")
        body_params:   List of strings to fill {{1}}, {{2}}, etc. in the template body

    Returns:
        True if sent successfully, False otherwise.
    """
    token, phone_id = _get_reminder_creds()
    if not (token and phone_id):
        logger.error("[Reminder] No WhatsApp credentials available — cannot send template")
        return False

    to = _clean_phone(to_number)
    url = f"https://graph.facebook.com/{_API_VERSION}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Build template component
    components = []
    if body_params:
        components.append({
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(p)} for p in body_params
            ],
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": components,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            logger.info(f"[Reminder] Template '{template_name}' sent to {to}")
            return True
        else:
            logger.error(f"[Reminder] Template send failed {resp.status_code}: {resp.text[:300]}")
            return False
    except Exception as e:
        logger.error(f"[Reminder] Template send exception: {e}")
        return False


# ── Free-form Text (within 24hr window only) ─────────────────────────────────

async def send_reminder_text(to_number: str, message: str) -> bool:
    """
    Send a free-form text message from the official reminder number.
    NOTE: This only works within 24hrs of the recipient's last message to this number.
    For proactive outreach, use send_template() instead.
    """
    token, phone_id = _get_reminder_creds()
    if not (token and phone_id):
        logger.error("[Reminder] No WhatsApp credentials available")
        return False

    to = _clean_phone(to_number)
    url = f"https://graph.facebook.com/{_API_VERSION}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message[:4096]},
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            logger.info(f"[Reminder] Text sent to {to}")
            return True
        else:
            logger.error(f"[Reminder] Text send failed {resp.status_code}: {resp.text[:300]}")
            return False
    except Exception as e:
        logger.error(f"[Reminder] Text send exception: {e}")
        return False


# ── Template Catalog ──────────────────────────────────────────────────────────
# Create these templates in Meta Business Manager. Names must match exactly.
#
# Template: rent_reminder
# Category: UTILITY
# Language: en
# Body:     "Hi {{1}}, good day!
#            Quick reminder — your rent of Rs.{{2}} for {{3}} must be paid on or
#            before the 5th of every month without fail. Please try to make the
#            payment earlier and avoid waiting until the last moment.
#            Ensure your dues are cleared on time. Once you've made the payment,
#            share the transaction receipt immediately.
#            If already paid, please ignore this message.
#            Thanks for your cooperation. - Cozeevo Co-living"
# Params:   {{1}}=name, {{2}}=amount, {{3}}=month
#
# Template: rent_overdue
# Category: UTILITY
# Language: en
# Body:     "Hi {{1}}, your rent of Rs.{{2}} for {{3}} is overdue.
#            Outstanding balance: Rs.{{4}}. Please clear immediately.
#            - Cozeevo Co-living"
# Params:   {{1}}=name, {{2}}=rent, {{3}}=month, {{4}}=balance
#
# Template: checkout_reminder
# Category: UTILITY
# Language: en
# Body:     "Hi {{1}}, your checkout from room {{2}} is scheduled for {{3}}.
#            Please complete the checkout process at reception.
#            - Cozeevo Co-living"
# Params:   {{1}}=name, {{2}}=room, {{3}}=date
#
# Template: general_notice
# Category: UTILITY
# Language: en
# Body:     "Hi {{1}}, {{2}} - Cozeevo Co-living"
# Params:   {{1}}=name, {{2}}=message
