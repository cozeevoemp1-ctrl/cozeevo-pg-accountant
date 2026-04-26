"""
src/api/v2/auth_hooks.py
========================
Custom Supabase SMS provider webhook.

Supabase Auth → POST /api/v2/auth/send-otp with {"phone": "+91...", "otp": "123456"}
We send the OTP via WhatsApp instead of SMS (no Twilio required).

Configure in Supabase Dashboard:
  Authentication → SMS Provider → Custom → Webhook URL:
    https://api.getkozzy.com/api/v2/auth/send-otp
"""
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# Shared secret Supabase sends in Authorization header.
# Set SUPABASE_SMS_HOOK_SECRET in .env to any strong random string.
# In Supabase dashboard: SMS Provider → Custom → "HTTP Bearer Token" = this value.
_HOOK_SECRET = os.environ.get("SUPABASE_SMS_HOOK_SECRET", "")


class _OtpPayload(BaseModel):
    phone: str
    otp: str


@router.post("/auth/send-otp", status_code=200)
async def send_otp_via_whatsapp(payload: _OtpPayload, request: Request):
    """Receive OTP from Supabase and deliver it via WhatsApp."""
    # Verify bearer token if secret is configured
    if _HOOK_SECRET:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ").strip() != _HOOK_SECRET:
            raise HTTPException(status_code=401, detail="invalid hook secret")

    phone = payload.phone.strip()
    otp = payload.otp.strip()

    if not phone or not otp:
        raise HTTPException(status_code=400, detail="phone and otp required")

    message = f"Your Kozzy login code is: *{otp}*\n\nValid for 10 minutes. Do not share this code."

    try:
        from src.whatsapp.webhook_handler import _send_whatsapp
        await _send_whatsapp(phone, message, intent="AUTH_OTP")
        logger.info("[Auth] OTP sent via WhatsApp to %s", phone[-4:])
    except Exception as exc:
        logger.error("[Auth] Failed to send OTP via WhatsApp to %s: %s", phone[-4:], exc)
        raise HTTPException(status_code=500, detail="failed to deliver OTP")

    return {"message": "otp_sent"}
