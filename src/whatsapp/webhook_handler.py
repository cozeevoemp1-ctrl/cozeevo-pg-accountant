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


# -- Message dedup cache (prevents duplicate webhook processing) ---------------
# Meta sends the same message from multiple IPs. First one processes, rest skip.
# Uses asyncio.Lock to prevent race condition where two duplicates both pass check.
import time as _time
import asyncio as _asyncio
_SEEN_MSG_IDS: dict[str, float] = {}  # msg_id → timestamp
_DEDUP_TTL = 60  # seconds to remember a message ID
_DEDUP_LOCK = _asyncio.Lock()

# Per-phone processing lock — ensures only one message processes at a time per phone
_PHONE_LOCKS: dict[str, _asyncio.Lock] = {}


async def _is_duplicate(msg_id: str) -> bool:
    """Return True if we've already processed this message ID. Thread-safe."""
    if not msg_id:
        return False
    async with _DEDUP_LOCK:
        now = _time.time()
        # Purge old entries
        stale = [k for k, v in _SEEN_MSG_IDS.items() if now - v > _DEDUP_TTL]
        for k in stale:
            del _SEEN_MSG_IDS[k]
        if msg_id in _SEEN_MSG_IDS:
            return True
        _SEEN_MSG_IDS[msg_id] = now
        return False


def _get_phone_lock(phone: str) -> _asyncio.Lock:
    """Get or create a per-phone lock to serialize message processing."""
    if phone not in _PHONE_LOCKS:
        _PHONE_LOCKS[phone] = _asyncio.Lock()
    return _PHONE_LOCKS[phone]


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
    msg_id      = msg_data.get("msg_id", "")
    media_id    = msg_data.get("media_id")
    media_mime  = msg_data.get("media_mime")
    media_name  = msg_data.get("media_name", "")   # original filename (for type sniffing)

    logger.info(f"[Webhook] From={from_number} | Body={body[:80]} | MsgId={msg_id[:20] if msg_id else '-'}")

    # File-based debug log — journald not working
    with open("/tmp/pg_webhook_debug.log", "a") as _wdbg:
        _wdbg.write(f"[{from_number}] msg={body[:60]} msg_id={msg_id[:30] if msg_id else '-'}\n")

    # -- Dedup: skip if we've already processed this exact message ----------------
    if await _is_duplicate(msg_id):
        with open("/tmp/pg_webhook_debug.log", "a") as _wdbg:
            _wdbg.write(f"  DUPLICATE SKIPPED: {msg_id}\n")
        return {"status": "ok"}

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

    # -- Handle media ---------------------------------------------------------
    _STATEMENT_MIMES = {
        "application/pdf",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "text/plain",
        "application/octet-stream",   # WhatsApp often sends CSV/Excel as this
    }
    _STATEMENT_EXTS = {".pdf", ".xlsx", ".xls", ".csv", ".txt"}

    if media_id:
        base_mime = (media_mime or "").split(";")[0].strip()
        fname_ext = ("." + media_name.rsplit(".", 1)[-1].lower()) if "." in media_name else ""

        if base_mime.startswith("audio/"):
            # Voice message: stream bytes in memory directly to Whisper — no disk I/O
            audio_bytes = await _fetch_media_bytes(media_id)
            if not audio_bytes:
                logger.warning("[Webhook] Voice download failed — ignoring message")
                return {"status": "ok"}
            transcribed = await _transcribe_audio_bytes(audio_bytes, base_mime)
            if transcribed:
                logger.info(f"[Webhook] Voice transcribed: {transcribed[:80]}")
                body = transcribed
            else:
                logger.warning("[Webhook] Voice transcription failed — notifying user")
                background.add_task(
                    _send_whatsapp,
                    from_number,
                    "Sorry, I couldn't understand the voice note. Please type your message instead.",
                )
                return {"status": "ok"}
        elif base_mime in _STATEMENT_MIMES or fname_ext in _STATEMENT_EXTS:
            # ── Bank statement PDF / Excel / CSV upload (admin / power_user only)
            # Pass actual filename extension so downloader saves with correct ext
            effective_mime = base_mime if base_mime != "application/octet-stream" else (
                {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "xls":  "application/vnd.ms-excel",
                 "csv":  "text/csv",
                 "pdf":  "application/pdf",
                 }.get(fname_ext.lstrip("."), base_mime)
            )
            background.add_task(_handle_pdf_upload, from_number, media_id, body, effective_mime)
            return {"status": "ok"}
        else:
            # Non-audio, non-statement media (image, etc.)
            # Don't download here — let chat_api handle via media_handler
            # for onboarding photo uploads
            pass

    # Detect media type for InboundMessage
    _media_type = None
    if media_id:
        base = (media_mime or "").split(";")[0].strip()
        if base.startswith("image/"):
            _media_type = "image"
        elif base.startswith("video/"):
            _media_type = "video"
        elif base.startswith("application/"):
            _media_type = "document"

    # -- Route through the v1 regex-first pipeline ----------------------------
    # Per-phone lock prevents concurrent DB session corruption from Meta duplicates
    phone_lock = _get_phone_lock(from_number)
    try:
        async with phone_lock:
            from src.database.db_manager import _session_factory
            from src.whatsapp.chat_api import process_message, InboundMessage
            async with _session_factory() as session:
                result = await process_message(
                    body=InboundMessage(
                        phone=from_number, message=body, message_id=None,
                        media_type=_media_type,
                        media_id=media_id if _media_type else None,
                        media_mime=media_mime if _media_type else None,
                        media_filename=media_name if _media_type else None,
                    ),
                    session=session,
                )
            reply = result.reply if not result.skip else None
    except Exception as e:
        logger.error(f"[Webhook] Processing error: {e}", exc_info=True)
        reply = "Sorry, something went wrong. Please try again or type *hi* to start fresh."

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

        msg_id = msg.get("id", "")  # wamid — unique per message, for dedup

        if msg_type == "text":
            return {"from": from_num, "body": msg["text"]["body"], "msg_id": msg_id}

        # Interactive: button tap or list selection — extract the id as the body
        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            itype = interactive.get("type", "")
            if itype == "button_reply":
                btn_id = interactive.get("button_reply", {}).get("id", "")
                return {"from": from_num, "body": btn_id, "msg_id": msg_id}
            if itype == "list_reply":
                row_id = interactive.get("list_reply", {}).get("id", "")
                return {"from": from_num, "body": row_id, "msg_id": msg_id}
            return None  # unknown interactive subtype — ignore

        # Document / image / audio / video
        media_obj = msg.get(msg_type, {})
        return {
            "from":       from_num,
            "body":       media_obj.get("caption", ""),
            "media_id":   media_obj.get("id"),
            "media_mime": media_obj.get("mime_type", ""),
            "media_name": media_obj.get("filename", ""),
            "msg_id":     msg_id,
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
        # Audio — WhatsApp voice notes come as ogg/opus; Whisper accepts ogg, mp4, m4a, webm
        "audio/ogg":       ".ogg",
        "audio/mpeg":      ".mp3",
        "audio/mp4":       ".m4a",
        "audio/webm":      ".webm",
        "audio/wav":       ".wav",
        "audio/aac":       ".aac",
    }
    # Handle compound MIME like "audio/ogg; codecs=opus" → match on base part
    base_mime = (media_mime or "").split(";")[0].strip()
    ext       = mime_ext.get(base_mime) or mime_ext.get(media_mime or "", ".bin")
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


# -- Groq Whisper voice transcription (in-memory, no disk I/O) ----------------

_MIME_TO_EXT = {
    "audio/ogg":  ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4":  ".m4a",
    "audio/webm": ".webm",
    "audio/wav":  ".wav",
    "audio/aac":  ".aac",
}


async def _fetch_media_bytes(media_id: str) -> Optional[bytes]:
    """Fetch raw media bytes from Meta CDN into memory (no disk write)."""
    import httpx
    token = os.getenv("WHATSAPP_TOKEN", "")
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            meta_resp = await client.get(
                f"https://graph.facebook.com/v18.0/{media_id}", headers=headers
            )
            media_url = meta_resp.json()["url"]
            file_resp = await client.get(media_url, headers=headers)
        return file_resp.content
    except Exception as e:
        logger.error(f"[Webhook] Media fetch failed: {e}")
        return None


async def _transcribe_audio_bytes(audio_bytes: bytes, mime_type: str) -> Optional[str]:
    """
    Transcribe audio bytes via Groq Whisper — no disk I/O.
    Supports Hindi, English, Hinglish, Telugu, Kannada (auto-detected).
    """
    import asyncio
    from io import BytesIO

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        logger.warning("[Whisper] GROQ_API_KEY not set — cannot transcribe audio")
        return None

    ext = _MIME_TO_EXT.get(mime_type, ".ogg")
    filename = f"voice{ext}"

    def _sync_transcribe() -> str:
        from groq import Groq
        client = Groq(api_key=api_key)
        result = client.audio.transcriptions.create(
            file=(filename, BytesIO(audio_bytes)),
            model="whisper-large-v3-turbo",
            response_format="text",
            language=None,   # auto-detect
        )
        return result if isinstance(result, str) else getattr(result, "text", "")

    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _sync_transcribe)
        return text.strip() if text else None
    except Exception as e:
        logger.error(f"[Whisper] Transcription error: {e}")
        return None


# -- Bank statement PDF upload handler -----------------------------------------

async def _handle_pdf_upload(from_number: str, media_id: str, caption: str, mime_type: str = "application/pdf"):
    """
    Background task: download PDF/Excel/CSV → role-check → parse → save → reply.
    Only admin / power_user may upload bank statements.
    """
    from src.database.db_manager import _session_factory
    from src.whatsapp.role_service import get_caller_context
    from src.whatsapp.handlers.finance_handler import handle_bank_upload

    try:
        async with _session_factory() as session:
            ctx = await get_caller_context(from_number, session)

        if ctx.role not in ("admin", "owner"):
            await _send_whatsapp(
                from_number,
                "Bank statement uploads are only available for admins.",
            )
            return

        saved_path = await _download_media(media_id, mime_type)
        if not saved_path:
            await _send_whatsapp(from_number, "Could not download the file. Please try again.")
            return

        async with _session_factory() as session:
            reply = await handle_bank_upload(saved_path, from_number, caption, session)
            await session.commit()

        await _send_whatsapp(from_number, reply)

    except Exception as e:
        logger.error(f"[PDF Upload] Error for {from_number}: {e}", exc_info=True)
