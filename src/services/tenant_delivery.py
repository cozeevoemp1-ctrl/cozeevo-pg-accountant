"""Reliable tenant messaging — single source of truth for anything we send a tenant
who may never have messaged us.

Why this exists (5 Sep 2026, Room 223 / Ashfaaq Ahmed):
Meta's 24-hour window opens only when the *customer replies*. Sending an approved
template does NOT open it. So the signed agreement, which went out as a free-form
document one second after the confirmation template, was rejected with error 131047
for every first-time tenant — 57 such failures in the previous 45 days.

The failure is invisible at send time: Meta answers 200 and the rejection arrives
seconds later on the status webhook. So this cannot be a send-and-fall-back — we
decide BEFORE sending, by checking whether the tenant has written to us in the
last 24 hours.

**Kiran's rule (5 Sep 2026): the agreement goes as a PDF ATTACHMENT or not at all.**
Never a download link. No URL of ours — storage, API or otherwise — is ever put in
a message to a tenant: it exposes our infrastructure, it is forwardable, and it
outlives the conversation. When a document cannot be attached, we report that to
staff instead of substituting a link.

Meta fetches the attachment server-to-server at send time, so the tenant never sees
a URL and a short 1-hour signature is all that is needed.

Outside the 24-hr window a free-form document is impossible. Attaching a PDF there
needs a template with a DOCUMENT header (e.g. `cozeevo_agreement_document`), which
must be created and approved on the WABA first — see docs/specs/current-issues.md.
Until that exists, `send_agreement` returns `no_window` and the caller tells staff.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func

logger = logging.getLogger(__name__)


def tpl_param(text: str) -> str:
    """Meta rejects template body params containing newlines, tabs, or 4+ spaces
    with `(#132018) Param text cannot have new-line/tab characters...` — a 400 at
    send time, so the message simply never goes out. Flatten to one line.
    """
    return " ".join((text or "").split())


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
    """Deliver the signed agreement as a PDF attachment. Returns (delivered, how).

    `how` is "document" when attached, "no_window" when the tenant has not written
    to us in 24 hours (nothing sent — a free-form document would be rejected), or
    "missing phone or pdf". Never sends a link.
    """
    from src.services.storage import sign_stored_url
    from src.whatsapp.webhook_handler import _send_whatsapp_document

    phone_wa = normalize_wa(phone)
    if not (phone_wa and pdf_stored):
        return False, "missing phone or pdf"

    if not await has_open_window(phone_wa):
        # Free-form documents are rejected outside the window (131047). Do NOT
        # substitute a link — staff handle it instead.
        logger.info("[delivery] agreement NOT sent to %s — no open 24-hr window", phone_wa)
        return False, "no_window"

    filename = f"Cozeevo_Agreement_{(tenant_name or 'tenant').replace(' ', '_')}.pdf"
    # 1 hour: Meta fetches this server-to-server within seconds and the tenant
    # never sees the URL. Nothing long-lived is handed out.
    pdf_url = await sign_stored_url(pdf_stored, expires_in=3600)
    await _send_whatsapp_document(
        phone_wa, pdf_url, filename,
        caption=("Your Cozeevo Co-living rental agreement (re-sent)."
                 if resend else "Your signed rental agreement"),
    )
    return True, "document"
