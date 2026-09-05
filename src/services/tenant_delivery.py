"""Reliable tenant messaging — single source of truth for anything we send a tenant
who may never have messaged us.

Why this exists (5 Sep 2026, Room 223 / Ashfaaq Ahmed):
Meta's 24-hour window opens only when the *customer replies*. Sending an approved
template does NOT open it. So the signed agreement, which went out as a free-form
document one second after the confirmation template, was rejected with error 131047
for every first-time tenant — 57 such failures in the previous 45 days.

Worse, the failure is invisible at send time: Meta answers 200 and the rejection
arrives seconds later on the status webhook. So we cannot "send and fall back on
error" — we have to decide BEFORE sending, by checking whether the tenant has
actually written to us in the last 24 hours.

Rule: free-form (documents, plain text) only inside an open window. Outside it,
everything goes through an approved template.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func

logger = logging.getLogger(__name__)

# Approved evergreen wrapper: {{1}}=greeting name, {{2}}=free text.
# See memory reference_whatsapp_templates.md.
_FREE_TEXT_TEMPLATE = "custom_broadcast_notice"


def normalize_wa(phone: str) -> str:
    """Bare digits with the 91 country code, the way whatsapp_log stores numbers."""
    p = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(p) == 10:
        p = "91" + p
    return p


async def has_open_window(phone: str, hours: int = 24) -> bool:
    """True if the tenant has sent US a message within `hours` — i.e. free-form is allowed.

    A template we sent does not count; only an inbound message opens the window.
    """
    from src.database.db_manager import get_session
    from src.database.models import WhatsappLog, MessageDirection

    digits = normalize_wa(phone)
    if not digits:
        return False
    last10 = digits[-10:]
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    try:
        async with get_session() as session:
            found = await session.scalar(
                select(func.count(WhatsappLog.id)).where(
                    WhatsappLog.direction == MessageDirection.inbound,
                    WhatsappLog.from_number.like(f"%{last10}"),
                    WhatsappLog.created_at >= cutoff,
                )
            )
        return bool(found)
    except Exception as e:  # never let a window check block a send decision
        logger.warning("[delivery] window check failed for %s: %s", last10, e)
        return False


async def send_agreement(
    phone: str,
    tenant_name: str,
    pdf_stored: str,
    *,
    resend: bool = False,
) -> tuple[bool, str]:
    """Deliver the signed agreement. Returns (delivered, how).

    Inside the 24-hr window → the PDF as a real WhatsApp document attachment.
    Outside it → the download link inside the approved free-text template, which
    reaches a tenant who has never messaged us. Never a bare free-form send.

    `pdf_stored` is the stored bucket URL; it is signed here, with an expiry that
    matches how the tenant receives it: Meta fetches an attachment within seconds,
    but a link the tenant taps two days later needs to still work.
    """
    from src.services.storage import sign_stored_url
    from src.whatsapp.webhook_handler import _send_whatsapp_document, _send_whatsapp_template

    phone_wa = normalize_wa(phone)
    if not (phone_wa and pdf_stored):
        return False, "missing phone or pdf"

    first_name = (tenant_name or "Resident").strip().split(" ")[0] or "Resident"
    filename = f"Cozeevo_Agreement_{(tenant_name or 'tenant').replace(' ', '_')}.pdf"

    if await has_open_window(phone_wa):
        pdf_url = await sign_stored_url(pdf_stored, expires_in=3600)
        await _send_whatsapp_document(
            phone_wa, pdf_url, filename,
            caption=("Your Cozeevo Co-living rental agreement (re-sent)."
                     if resend else "Your signed rental agreement"),
        )
        return True, "document"

    # 14 days — the tenant may open this days after check-in.
    pdf_url = await sign_stored_url(pdf_stored, expires_in=14 * 24 * 3600)
    body = (
        ("Here is your signed Cozeevo Co-living rental agreement again:\n"
         if resend else
         "Your signed Cozeevo Co-living rental agreement is ready:\n")
        + pdf_url
        + "\n\nReply to this message if you would like it sent as a PDF attachment."
    )
    sent = await _send_whatsapp_template(phone_wa, _FREE_TEXT_TEMPLATE, [first_name, body])
    if sent:
        return True, "template_link"
    logger.error("[delivery] agreement template send failed for %s", phone_wa)
    return False, "failed"
