"""
Standalone outbound WhatsApp sender for the demo bot.

Deliberately NOT reusing src/whatsapp/webhook_handler.py's `_send_whatsapp` —
that function logs every send to the production `whatsapp_log` table via
src.database.db_manager. Reusing it would write demo test traffic into the
Cozeevo production database. This is a minimal standalone copy pointed at
the demo's own WhatsApp test number/token.
"""
from __future__ import annotations

import os

import httpx
from loguru import logger


def _to_e164_for_meta(phone: str) -> str:
    to = phone.lstrip("+").replace(" ", "").replace("-", "")
    if len(to) == 10 and to[:1] in "6789":
        to = "91" + to
    return to


async def send_demo_whatsapp(to_number: str, message: str) -> None:
    token = os.getenv("HAVENLY_WHATSAPP_TOKEN") or os.getenv("WHATSAPP_TOKEN", "")
    phone_id = os.getenv("HAVENLY_WHATSAPP_PHONE_NUMBER_ID", "")

    if not (token and phone_id):
        logger.warning("[Demo] HAVENLY_WHATSAPP_TOKEN/HAVENLY_WHATSAPP_PHONE_NUMBER_ID not set — skipping send.")
        return

    to = _to_e164_for_meta(to_number)
    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message[:4096]},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 200:
            logger.info(f"[Demo] Sent to {to}")
        else:
            logger.error(f"[Demo] Send failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[Demo] Send exception: {e}")
