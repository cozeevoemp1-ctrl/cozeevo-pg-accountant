"""
Real visit booking via the Cal.com API v2 for a confirmed Havenly Stays visit.

Cal.com handles the invite/confirmation email itself (and syncs to a real
Google Calendar too, if you've connected one inside Cal.com) — no GCP service
account or Calendar API setup needed. See demo/havenly_stays/README.md.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

CALCOM_API_KEY = os.getenv("HAVENLY_CALCOM_API_KEY")
CALCOM_EVENT_TYPE_ID = os.getenv("HAVENLY_CALCOM_EVENT_TYPE_ID")
CALCOM_API_URL = "https://api.cal.com/v2/bookings"
CALCOM_API_VERSION = "2024-08-13"
DEFAULT_TIMEZONE = "Asia/Kolkata"


async def book_visit_event(lead_name: str, lead_phone: str, lead_email: str, price_context: str, slot: datetime) -> Optional[str]:
    """Creates a real Cal.com booking (Cal.com emails the invite). Returns the
    booking uid, or None if not configured / on failure — booking still
    succeeds in our own DB either way."""
    if not (CALCOM_API_KEY and CALCOM_EVENT_TYPE_ID):
        logger.warning("[Demo] HAVENLY_CALCOM_API_KEY / HAVENLY_CALCOM_EVENT_TYPE_ID not set — skipping real booking.")
        return None
    if not lead_email:
        logger.warning("[Demo] No lead email — skipping Cal.com booking.")
        return None

    # `slot` is a naive datetime in DEFAULT_TIMEZONE (from dateparser) — Cal.com
    # requires the start time in UTC.
    slot_local = slot.replace(tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
    start_iso = slot_local.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")

    headers = {
        "Authorization": f"Bearer {CALCOM_API_KEY}",
        "cal-api-version": CALCOM_API_VERSION,
        "Content-Type": "application/json",
    }
    body = {
        "eventTypeId": int(CALCOM_EVENT_TYPE_ID),
        "start": start_iso,
        "attendee": {
            "name": lead_name,
            "email": lead_email,
            "timeZone": DEFAULT_TIMEZONE,
            "phoneNumber": lead_phone,
        },
        "metadata": {"source": "havenly_stays_whatsapp_demo"},
        "bookingFieldsResponses": {"notes": price_context} if price_context else {},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(CALCOM_API_URL, json=body, headers=headers)
        if resp.status_code in (200, 201):
            data = resp.json()
            return (data.get("data") or {}).get("uid") or data.get("uid")
        logger.warning(f"[Demo] Cal.com booking failed {resp.status_code}: {resp.text[:300]}")
        return None
    except Exception as e:
        logger.warning(f"[Demo] Cal.com booking exception: {e}")
        return None
