"""
WhatsApp webhook handler -- FastAPI router.
Receives POST from Meta WhatsApp Cloud API, processes via the bot brain, replies via Meta Graph API.

Meta Cloud API flow:
  1. Meta sends GET /webhook/whatsapp?hub.* for initial verification
  2. Meta sends POST /webhook/whatsapp with JSON payload for each message
  3. We call the same processing pipeline as /api/whatsapp/process
  4. We reply by calling POST https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from loguru import logger

router = APIRouter(prefix="/webhook", tags=["whatsapp"])


# -- Webhook verification (Meta requires this one-time GET) --------------------

@router.get("/whatsapp")
async def verify_whatsapp(
    hub_mode:         str = Query(None, alias="hub.mode"),
    hub_challenge:    str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Meta webhook verification handshake -- called once when you register the webhook URL."""
    expected = os.getenv("WHATSAPP_VERIFY_TOKEN", "pg-accountant-verify")
    if hub_mode == "subscribe" and hub_verify_token == expected:
        logger.info("[Webhook] Meta verification successful")
        return int(hub_challenge)
    logger.warning("[Webhook] Meta verification failed -- check WHATSAPP_VERIFY_TOKEN")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


# -- Main WhatsApp webhook -----------------------------------------------------

@router.post("/whatsapp")
async def receive_whatsapp(request: Request, background: BackgroundTasks):
    """
    Meta WhatsApp Cloud API webhook.
    1. Verify Meta HMAC signature (rejects fakes)
    2. Parse Meta's nested JSON payload
    3. Detect master-data approval reply (approve/reject <id>)
    4. Pass through the same bot brain as /api/whatsapp/process
    5. Send reply via Meta Graph API (background task)
    """
    raw_body = await request.body()

    # -- Verify Meta signature (skip only if APP_SECRET not set yet) ----------
    app_secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if app_secret and app_secret != "PASTE_YOUR_META_APP_SECRET_HERE":
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_meta_signature(raw_body, sig_header, app_secret):
            logger.warning("[Webhook] Signature verification failed — request rejected")
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        import json
        payload: dict = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Extract message from Meta's nested structure
    msg_data = _extract_message(payload)
    if not msg_data:
        # Meta also sends status updates (delivered, read) -- just acknowledge
        return {"status": "ok"}

    from_number = msg_data["from"]
    body        = msg_data.get("body", "")
    media_id    = msg_data.get("media_id")
    media_mime  = msg_data.get("media_mime")

    logger.info(f"[Webhook] From={from_number} | Body={body[:80]}")

    # -- Master data approval replies ------------------------------------------
    import re
    approve_m = re.match(r"approve\s+(\d+)", body.strip(), re.I)
    reject_m  = re.match(r"reject\s+(\d+)",  body.strip(), re.I)

    if approve_m:
        pid = int(approve_m.group(1))
        from src.database.db_manager import approve_pending_entity
        result = await approve_pending_entity(pid)
        reply = f"Approved: {result.get('name', pid)}" if result else f"Not found: #{pid}"
        background.add_task(_send_whatsapp, from_number, reply)
        return {"status": "ok"}

    if reject_m:
        pid = int(reject_m.group(1))
        from src.database.db_manager import reject_pending_entity
        await reject_pending_entity(pid)
        background.add_task(_send_whatsapp, from_number, f"Rejected: #{pid}")
        return {"status": "ok"}

    # -- Download media if attached --------------------------------------------
    if media_id:
        await _download_media(media_id, media_mime)

    # -- Route through the v2 LangGraph supervisor pipeline -------------------
    try:
        from src.database.db_manager import _session_factory
        from src.whatsapp.v2.chat_api_v2 import _process_v2_inner, InboundMessage
        async with _session_factory() as session:
            result = await _process_v2_inner(
                body=InboundMessage(phone=from_number, message=body, message_id=None),
                session=session,
            )
        reply = result.reply if not result.skip else None
    except Exception as e:
        logger.error(f"[Webhook] Processing error: {e}", exc_info=True)
        reply = None  # Never send error messages to users — log only

    if reply:
        if getattr(result, "interactive_payload", None):
            background.add_task(_send_whatsapp_interactive, from_number, result.interactive_payload)
        else:
            background.add_task(_send_whatsapp, from_number, reply)
    return {"status": "ok"}


# -- Meta signature verifier ---------------------------------------------------

def _verify_meta_signature(body: bytes, sig_header: str, app_secret: str) -> bool:
    """Verify X-Hub-Signature-256 from Meta. Returns True if valid."""
    if not sig_header.startswith("sha256="):
        return False
    expected = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    received = sig_header[len("sha256="):]
    return hmac.compare_digest(expected, received)


# -- Meta message extractor ----------------------------------------------------

def _extract_message(payload: dict) -> Optional[dict]:
    """Parse Meta WhatsApp Cloud API payload into a flat dict."""
    try:
        change_value = payload["entry"][0]["changes"][0]["value"]
        messages = change_value.get("messages")
        if not messages:
            return None   # status update (delivered/read), not a user message

        msg      = messages[0]
        from_num = msg["from"]
        msg_type = msg.get("type", "text")

        if msg_type == "text":
            return {"from": from_num, "body": msg["text"]["body"]}

        # Interactive: button tap or list selection — extract the id as the body
        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            itype = interactive.get("type", "")
            if itype == "button_reply":
                btn_id = interactive.get("button_reply", {}).get("id", "")
                return {"from": from_num, "body": btn_id}
            if itype == "list_reply":
                row_id = interactive.get("list_reply", {}).get("id", "")
                return {"from": from_num, "body": row_id}
            return None  # unknown interactive subtype — ignore

        # Document / image / audio / video
        media_obj = msg.get(msg_type, {})
        return {
            "from":       from_num,
            "body":       media_obj.get("caption", ""),
            "media_id":   media_obj.get("id"),
            "media_mime": media_obj.get("mime_type", ""),
        }
    except (KeyError, IndexError):
        return None


# -- Meta Graph API sender -----------------------------------------------------

async def _send_whatsapp(to_number: str, message: str):
    """Send WhatsApp reply via Meta Graph API (free, no Twilio needed)."""
    token    = os.getenv("WHATSAPP_TOKEN", "")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

    if not (token and phone_id):
        logger.warning("[Meta] WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID not set -- skipping send.")
        return

    # Meta expects plain digits (e.g. 919876543210), no + or spaces
    to = to_number.lstrip("+").replace(" ", "")

    import httpx
    url     = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body    = {
        "messaging_product": "whatsapp",
        "to":   to,
        "type": "text",
        "text": {"body": message[:4096]},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 200:
            logger.info(f"[Meta] Sent to {to}")
        else:
            logger.error(f"[Meta] Send failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[Meta] Send exception: {e}")


# -- Meta interactive message sender ------------------------------------------

async def _send_whatsapp_interactive(to_number: str, payload: dict):
    """Send a WhatsApp interactive message (buttons / list) via Meta Graph API."""
    token    = os.getenv("WHATSAPP_TOKEN", "")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

    if not (token and phone_id):
        logger.warning("[Meta] WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID not set -- skipping send.")
        return

    to = to_number.lstrip("+").replace(" ", "")
    url     = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, **payload}

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 200:
            logger.info(f"[Meta] Interactive sent to {to}")
        else:
            logger.error(f"[Meta] Interactive send failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[Meta] Interactive send exception: {e}")


# -- Meta media downloader -----------------------------------------------------

async def _download_media(media_id: str, media_mime: Optional[str]) -> Optional[str]:
    """Download media attachment via Meta API and save to data/raw/."""
    import uuid
    from pathlib import Path
    import httpx

    token = os.getenv("WHATSAPP_TOKEN", "")
    if not token:
        logger.warning("[Meta] WHATSAPP_TOKEN not set -- cannot download media.")
        return None

    raw_dir = Path(os.getenv("DATA_RAW_DIR", "./data/raw"))
    raw_dir.mkdir(parents=True, exist_ok=True)

    mime_ext = {
        "application/pdf": ".pdf",
        "text/csv":        ".csv",
        "application/vnd.ms-excel": ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }
    ext      = mime_ext.get(media_mime or "", ".bin")
    out_path = raw_dir / f"wa_{uuid.uuid4().hex[:8]}{ext}"
    headers  = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            meta_resp  = await client.get(
                f"https://graph.facebook.com/v18.0/{media_id}", headers=headers
            )
            media_url  = meta_resp.json()["url"]
            file_resp  = await client.get(media_url, headers=headers)
            out_path.write_bytes(file_resp.content)
        logger.info(f"[Webhook] Saved media: {out_path}")
        return str(out_path)
    except Exception as e:
        logger.error(f"[Webhook] Media download failed: {e}")
        return None
