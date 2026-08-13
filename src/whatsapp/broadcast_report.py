"""Broadcast delivery report — the conversational "who actually got it" summary.

Why this exists (2026-08-13): Meta returns HTTP 200 + a message id even for
sends it later silently drops (TIER_250 messaging limit, unroutable numbers).
Real outcomes only arrive via `statuses` webhooks, captured on the VPS into
whatsapp_status_log. This module joins a broadcast's wamids against that table
and WhatsApps a one-paragraph summary to the operators via the same reliable
template path (custom_broadcast_notice) — e.g.:

    "Broadcast delivery report (bike parking notice): 264 messages — 248
     delivered (102 read), 2 accepted not yet delivered, 14 FAILED:
     Lakshmi Mam (7358341775) #131048 Spam rate limit hit; ..."

Ordering rule: broadcasts send OPERATORS FIRST (their conversation window is
then already open, so this report never falls past the messaging cap).

Usage from a broadcast script:
    wamids = {}                                   # wamid -> (name, phone)
    ok = await send_template(phone, TEMPLATE, ...)
    if isinstance(ok, str):
        wamids[ok] = (name, phone)
    ...
    await send_delivery_report(wamids, label="bike parking notice")
"""
from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import select

# Standing CC list — memory/rules_whatsapp_cc.md. Operators are sent FIRST in
# every broadcast; scripts import this list instead of redeclaring it.
OPERATORS: list[tuple[str, str]] = [
    ("Kiran", "7845952289"),
    ("Lokesh", "7680814628"),
    ("Lakshmi Mam", "7358341775"),
    ("Prabhakaran", "9444296681"),
]

REPORT_TEMPLATE = "custom_broadcast_notice"   # {{1}}=greeting, {{2}}=flat text
REPORT_GREETING = "Team"

_STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}


def summarize_statuses(
    rows: list[tuple],
    wamid_map: dict[str, tuple[str, str]],
    label: str,
) -> str:
    """Compile status rows into ONE flat paragraph (template params reject
    newlines/tabs — Meta error #132018). Pure function, unit-tested.

    rows:      (message_id, status, error_code, error_message) tuples
    wamid_map: wamid -> (recipient name, phone)
    """
    best: dict[str, str] = {}          # wamid -> highest non-failed status
    failed: dict[str, tuple] = {}      # wamid -> (code, message)
    for message_id, status, error_code, error_message in rows:
        if message_id not in wamid_map:
            continue
        if status == "failed":
            failed[message_id] = (error_code, error_message)
        elif _STATUS_RANK.get(status, 0) > _STATUS_RANK.get(best.get(message_id, ""), 0):
            best[message_id] = status

    total = len(wamid_map)
    read = [w for w, s in best.items() if s == "read" and w not in failed]
    delivered = [w for w, s in best.items()
                 if s in ("delivered", "read") and w not in failed]
    accepted_only = [w for w, s in best.items() if s == "sent" and w not in failed]
    no_status = [w for w in wamid_map
                 if w not in best and w not in failed]

    parts = [f"Broadcast delivery report ({label}): {total} messages — "
             f"{len(delivered)} delivered ({len(read)} read)"]
    if accepted_only:
        parts.append(f", {len(accepted_only)} accepted not yet delivered")
    if no_status:
        parts.append(f", {len(no_status)} no status yet")
    if failed:
        details = []
        for w, (code, msg) in failed.items():
            name, phone = wamid_map[w]
            reason = " ".join(str(x) for x in (f"#{code}" if code else "", msg or "") if x)
            details.append(f"{name} ({phone}) {reason}".strip())
        parts.append(f", {len(failed)} FAILED: " + "; ".join(details))
    else:
        parts.append(". No failures.")

    text = "".join(parts)
    # One flat paragraph, and leave room for the template's greeting/sign-off
    # inside Meta's 1024-char body limit.
    text = " ".join(text.split())
    if len(text) > 950:
        text = text[:935].rstrip() + " ...(truncated)"
    return text


async def send_delivery_report(
    wamid_map: dict[str, tuple[str, str]],
    label: str,
    wait_seconds: int = 180,
) -> str:
    """Wait for statuses to land, compile the summary, WhatsApp it to operators.

    Returns the summary text (also printed by callers). Statuses are written by
    the VPS webhook into the shared Supabase DB, so a locally-run broadcast
    script can still read them here.
    """
    from src.database.db_manager import get_session
    from src.database.models import WhatsappStatusLog
    from src.whatsapp.reminder_sender import send_template

    if not wamid_map:
        return "No accepted sends — nothing to report."

    logger.info(f"[BroadcastReport] Waiting {wait_seconds}s for status webhooks...")
    await asyncio.sleep(wait_seconds)

    async with get_session() as session:
        result = await session.execute(
            select(
                WhatsappStatusLog.message_id,
                WhatsappStatusLog.status,
                WhatsappStatusLog.error_code,
                WhatsappStatusLog.error_message,
            ).where(WhatsappStatusLog.message_id.in_(list(wamid_map)))
        )
        rows = result.all()

    summary = summarize_statuses(rows, wamid_map, label)

    for name, phone in OPERATORS:
        ok = await send_template(
            phone, REPORT_TEMPLATE, language_code="en",
            body_params=[REPORT_GREETING, summary],
        )
        logger.info(f"[BroadcastReport] report to {name}: {'ok' if ok else 'FAILED'}")
        await asyncio.sleep(0.4)
    return summary
