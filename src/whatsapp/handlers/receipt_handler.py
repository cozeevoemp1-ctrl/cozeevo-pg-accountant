"""
Media upload handler — classifies and routes uploaded photos/documents.

Supports:
  - Payment receipts (UPI screenshots, cash receipts)
  - Expense bills (electricity, plumber invoices)
  - Tenant ID proofs (Aadhaar, passport)
  - Licenses/documents (FSSAI, trade cert)
  - Vendor delivery slips
  - Property photos (room damage, maintenance)

Flow:
  1. Check caption keywords to auto-classify
  2. If no caption or unclear → ask user what type
  3. Route to appropriate sub-handler

Uses existing media_handler.py for downloading WhatsApp media.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from loguru import logger
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Payment, Tenancy, Tenant, Room, TenancyStatus, Document, DocumentType,
)
from src.whatsapp.role_service import CallerContext
from src.whatsapp.handlers._shared import _save_pending

# ── Keyword patterns for auto-classification ─────────────────────────────

_RECEIPT_KW = re.compile(
    r"\b(receipt|paid|payment|upi|cash|rent|deposit|gpay|phonepe|paytm|neft|imps)\b", re.I)
_EXPENSE_KW = re.compile(
    r"\b(bill|invoice|eb|electricity|water|internet|salary|plumber|repair|maintenance|groceries?|cleaning|diesel|generator)\b", re.I)
_ID_PROOF_KW = re.compile(
    r"\b(aadhaar|aadhar|passport|driving\s+licen[cs]e|pan\s+card|voter\s+id|id\s+proof|id\s+card)\b", re.I)
_LICENSE_KW = re.compile(
    r"\b(fssai|trade\s+licen[cs]e|fire\s+safety|noc|certificate|permit|registration)\b", re.I)
_VENDOR_KW = re.compile(
    r"\b(delivery|slip|challan|vendor|supplier|stock|inventory|order)\b", re.I)


async def handle_media_upload(
    media_id: str,
    media_mime: str,
    caption: str,
    phone: str,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:
    """
    Main entry point for any photo/document upload.
    Classifies the upload and routes to the right handler.
    """
    caption = (caption or "").strip()

    # ── Auto-classify from caption keywords ──────────────────────────────
    if caption:
        if _EXPENSE_KW.search(caption):
            return await _handle_expense_receipt(media_id, media_mime, caption, phone, ctx, session)
        if _ID_PROOF_KW.search(caption):
            return await _handle_id_proof(media_id, media_mime, caption, phone, session)
        if _LICENSE_KW.search(caption):
            return await _handle_license_doc(media_id, media_mime, caption, phone, session)
        if _VENDOR_KW.search(caption):
            return await _handle_vendor_slip(media_id, media_mime, caption, phone, session)
        if _RECEIPT_KW.search(caption):
            return await handle_receipt_upload(media_id, media_mime, caption, phone, ctx, session)
        # Caption exists but no keyword match → could still be a receipt with tenant name
        return await handle_receipt_upload(media_id, media_mime, caption, phone, ctx, session)

    # ── No caption → check if there's a recent payment (likely receipt) ──
    recent = await _get_recent_unattached_payments(phone, session, minutes=15)
    if recent:
        # Very likely a receipt for the recent payment
        return await handle_receipt_upload(media_id, media_mime, "", phone, ctx, session)

    # ── No caption, no recent payment → use Gemini Vision to read the image ──
    vision_result = await _gemini_read_image(media_id, media_mime)

    if vision_result:
        doc_type = vision_result.get("type", "other")
        logger.info(f"[Media] Gemini classified as: {doc_type} | {vision_result}")

        # Auto-route based on Gemini classification
        if doc_type == "payment_receipt":
            # Gemini extracted payment details — try to match and log
            return await _handle_gemini_receipt(vision_result, media_id, media_mime, phone, ctx, session)
        elif doc_type == "expense_bill":
            return await _handle_expense_receipt(media_id, media_mime, vision_result.get("summary", ""), phone, ctx, session)
        elif doc_type == "id_proof":
            return await _handle_id_proof(media_id, media_mime, vision_result.get("summary", ""), phone, session)
        elif doc_type == "license":
            return await _handle_license_doc(media_id, media_mime, vision_result.get("summary", ""), phone, session)
        elif doc_type == "vendor_slip":
            return await _handle_vendor_slip(media_id, media_mime, vision_result.get("summary", ""), phone, session)

    # ── Gemini failed or unavailable → fallback: ask the user ────────────
    action_data = {"media_id": media_id, "media_mime": media_mime}
    choices = [
        {"seq": 1, "intent": "MEDIA_RECEIPT",  "label": "Payment receipt"},
        {"seq": 2, "intent": "MEDIA_EXPENSE",  "label": "Expense bill / invoice"},
        {"seq": 3, "intent": "MEDIA_ID_PROOF", "label": "Tenant ID proof"},
        {"seq": 4, "intent": "MEDIA_LICENSE",  "label": "License / document"},
        {"seq": 5, "intent": "MEDIA_OTHER",    "label": "Other (save for later)"},
    ]
    await _save_pending(phone, "MEDIA_CLASSIFY", action_data, choices, session)

    return (
        "What is this?\n\n"
        "1. Payment receipt\n"
        "2. Expense bill / invoice\n"
        "3. Tenant ID proof\n"
        "4. License / document\n"
        "5. Other\n\n"
        "Reply *1-5*"
    )


async def handle_receipt_upload(
    media_id: str,
    media_mime: str,
    caption: str,
    phone: str,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:
    """
    Handle payment receipt upload specifically.
    """
    from src.whatsapp.media_handler import download_whatsapp_media

    # ── Try to determine which payment this receipt belongs to ────────────

    # Option 1: Caption has tenant name → match to recent payment
    if caption:
        payment, match_info = await _match_from_caption(caption, session)
        if payment:
            file_path = await download_whatsapp_media(
                media_id, media_mime, "receipts",
                filename_prefix=f"pay{payment.id}",
            )
            if file_path:
                await _attach_receipt(payment, file_path, media_mime, phone, session)
                return (
                    f"Receipt saved for *{match_info}*\n"
                    f"Amount: Rs.{int(payment.amount):,} ({payment.payment_mode.value.upper()})\n"
                    f"Month: {payment.period_month.strftime('%B %Y') if payment.period_month else 'N/A'}"
                )
            return "Could not download the image. Please try sending again."

    # Option 2: No caption or caption didn't match → check recent payments from this phone
    recent_unattached = await _get_recent_unattached_payments(phone, session, minutes=30)

    if len(recent_unattached) == 1:
        # Only one recent payment without receipt → auto-attach
        payment = recent_unattached[0]
        tenant = await _get_tenant_for_payment(payment, session)
        file_path = await download_whatsapp_media(
            media_id, media_mime, "receipts",
            filename_prefix=f"pay{payment.id}",
        )
        if file_path:
            await _attach_receipt(payment, file_path, media_mime, phone, session)
            name = tenant.name if tenant else "Unknown"
            return (
                f"Receipt saved for *{name}*\n"
                f"Amount: Rs.{int(payment.amount):,} ({payment.payment_mode.value.upper()})\n"
                f"Month: {payment.period_month.strftime('%B %Y') if payment.period_month else 'N/A'}"
            )
        return "Could not download the image. Please try sending again."

    if len(recent_unattached) > 1:
        # Multiple recent payments → ask which one
        # Save media_id to pending so we can attach after selection
        choices = []
        for i, p in enumerate(recent_unattached[:5]):
            tenant = await _get_tenant_for_payment(p, session)
            name = tenant.name if tenant else "Unknown"
            month = p.period_month.strftime('%b %Y') if p.period_month else ""
            choices.append({
                "seq": i + 1,
                "intent": "ATTACH_RECEIPT",
                "label": f"{name} — Rs.{int(p.amount):,} {p.payment_mode.value.upper()} {month}",
                "payment_id": p.id,
            })

        action_data = {
            "media_id": media_id,
            "media_mime": media_mime,
        }
        await _save_pending(phone, "RECEIPT_SELECT", action_data, choices, session)

        lines = ["Which payment is this receipt for?\n"]
        for c in choices:
            lines.append(f"{c['seq']}. {c['label']}")
        lines.append(f"\nReply *1-{len(choices)}* or type a tenant name.")
        return "\n".join(lines)

    # Option 3: No recent payments at all → show wider search or ask
    wider_unattached = await _get_recent_unattached_payments(phone, session, minutes=1440)  # last 24h

    if wider_unattached:
        choices = []
        for i, p in enumerate(wider_unattached[:5]):
            tenant = await _get_tenant_for_payment(p, session)
            name = tenant.name if tenant else "Unknown"
            month = p.period_month.strftime('%b %Y') if p.period_month else ""
            choices.append({
                "seq": i + 1,
                "intent": "ATTACH_RECEIPT",
                "label": f"{name} — Rs.{int(p.amount):,} {month}",
                "payment_id": p.id,
            })

        action_data = {
            "media_id": media_id,
            "media_mime": media_mime,
        }
        await _save_pending(phone, "RECEIPT_SELECT", action_data, choices, session)

        lines = ["No recent payment in the last 30 min. These payments from today have no receipt:\n"]
        for c in choices:
            lines.append(f"{c['seq']}. {c['label']}")
        lines.append(f"\nReply *1-{len(choices)}* or type a tenant name.")
        return "\n".join(lines)

    # Option 4: No unattached payments at all → save image, ask to log payment
    file_path = await download_whatsapp_media(
        media_id, media_mime, "receipts",
        filename_prefix="unlinked",
    )

    if file_path:
        action_data = {
            "media_id": media_id,
            "media_mime": media_mime,
            "file_path": file_path,
        }
        await _save_pending(phone, "RECEIPT_NO_PAYMENT", action_data, [], session)
        return (
            "Receipt saved but no recent payment found to attach it to.\n\n"
            "To link it, type the payment details:\n"
            "*[Name] [Amount] [cash/upi] [month]*\n"
            "Example: _Raj 15000 cash april_"
        )

    return "Could not download the image. Please try sending again."


async def resolve_receipt_selection(
    choice_idx: int,
    choices: list[dict],
    action_data: dict,
    phone: str,
    session: AsyncSession,
) -> str:
    """Called when user selects which payment a receipt belongs to (from pending RECEIPT_SELECT)."""
    from src.whatsapp.media_handler import download_whatsapp_media

    if choice_idx < 0 or choice_idx >= len(choices):
        return f"Invalid choice. Reply *1-{len(choices)}*."

    selected = choices[choice_idx]
    payment_id = selected.get("payment_id")
    if not payment_id:
        return "Could not find the payment. Please try again."

    payment = await session.get(Payment, payment_id)
    if not payment:
        return "Payment not found in database."

    media_id = action_data.get("media_id")
    media_mime = action_data.get("media_mime", "image/jpeg")

    file_path = await download_whatsapp_media(
        media_id, media_mime, "receipts",
        filename_prefix=f"pay{payment.id}",
    )

    if file_path:
        await _attach_receipt(payment, file_path, media_mime, phone, session)
        tenant = await _get_tenant_for_payment(payment, session)
        name = tenant.name if tenant else "Unknown"
        return (
            f"Receipt saved for *{name}*\n"
            f"Amount: Rs.{int(payment.amount):,}\n"
            f"Month: {payment.period_month.strftime('%B %Y') if payment.period_month else 'N/A'}"
        )

    return "Could not download the image. Please try sending again."


# ── Document type sub-handlers ───────────────────────────────────────────────

async def _handle_expense_receipt(
    media_id: str, media_mime: str, caption: str,
    phone: str, ctx: CallerContext, session: AsyncSession,
) -> str:
    """Save expense bill and route to ADD_EXPENSE flow."""
    from src.whatsapp.media_handler import download_whatsapp_media

    file_path = await download_whatsapp_media(media_id, media_mime, "invoices")
    if not file_path:
        return "Could not download the image. Please try again."

    doc = Document(
        doc_type=DocumentType.invoice,
        file_path=file_path,
        mime_type=media_mime,
        uploaded_by=phone,
        notes=f"Expense bill: {caption[:200]}",
    )
    session.add(doc)
    logger.info(f"[Media] Expense bill saved: {file_path}")

    return (
        f"Expense bill saved.\n\n"
        f"To log this expense, type:\n"
        f"*[category] [amount]*\n"
        f"Example: _electricity 5000_"
    )


async def _handle_id_proof(
    media_id: str, media_mime: str, caption: str,
    phone: str, session: AsyncSession,
) -> str:
    """Save tenant ID proof document."""
    from src.whatsapp.media_handler import download_whatsapp_media

    file_path = await download_whatsapp_media(media_id, media_mime, "id_proofs")
    if not file_path:
        return "Could not download the image. Please try again."

    doc = Document(
        doc_type=DocumentType.id_proof,
        file_path=file_path,
        mime_type=media_mime,
        uploaded_by=phone,
        notes=f"ID proof: {caption[:200]}",
    )
    session.add(doc)
    logger.info(f"[Media] ID proof saved: {file_path}")

    return (
        "ID proof saved.\n\n"
        "To link it to a tenant, type the tenant name.\n"
        "Or it will stay in the document archive."
    )


async def _handle_license_doc(
    media_id: str, media_mime: str, caption: str,
    phone: str, session: AsyncSession,
) -> str:
    """Save license/certificate document."""
    from src.whatsapp.media_handler import download_whatsapp_media

    file_path = await download_whatsapp_media(media_id, media_mime, "licenses")
    if not file_path:
        return "Could not download the image. Please try again."

    doc = Document(
        doc_type=DocumentType.license,
        file_path=file_path,
        mime_type=media_mime,
        uploaded_by=phone,
        notes=f"License/cert: {caption[:200]}",
    )
    session.add(doc)
    logger.info(f"[Media] License doc saved: {file_path}")
    return "License/document saved to archive."


async def _handle_vendor_slip(
    media_id: str, media_mime: str, caption: str,
    phone: str, session: AsyncSession,
) -> str:
    """Save vendor delivery slip."""
    from src.whatsapp.media_handler import download_whatsapp_media

    file_path = await download_whatsapp_media(media_id, media_mime, "invoices")
    if not file_path:
        return "Could not download the image. Please try again."

    doc = Document(
        doc_type=DocumentType.invoice,
        file_path=file_path,
        mime_type=media_mime,
        uploaded_by=phone,
        notes=f"Vendor slip: {caption[:200]}",
    )
    session.add(doc)
    logger.info(f"[Media] Vendor slip saved: {file_path}")
    return "Delivery slip saved to archive."


async def handle_media_classify_selection(
    choice_idx: int,
    choices: list[dict],
    action_data: dict,
    phone: str,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:
    """Called when user selects document type from MEDIA_CLASSIFY pending."""
    media_id = action_data.get("media_id")
    media_mime = action_data.get("media_mime", "image/jpeg")

    if choice_idx < 0 or choice_idx >= len(choices):
        return f"Invalid choice. Reply *1-{len(choices)}*."

    selected = choices[choice_idx]["intent"]

    if selected == "MEDIA_RECEIPT":
        return await handle_receipt_upload(media_id, media_mime, "", phone, ctx, session)
    elif selected == "MEDIA_EXPENSE":
        return await _handle_expense_receipt(media_id, media_mime, "", phone, ctx, session)
    elif selected == "MEDIA_ID_PROOF":
        return await _handle_id_proof(media_id, media_mime, "", phone, session)
    elif selected == "MEDIA_LICENSE":
        return await _handle_license_doc(media_id, media_mime, "", phone, session)
    else:
        # MEDIA_OTHER — just save
        from src.whatsapp.media_handler import download_whatsapp_media
        file_path = await download_whatsapp_media(media_id, media_mime, "photos")
        if file_path:
            doc = Document(
                doc_type=DocumentType.other,
                file_path=file_path,
                mime_type=media_mime,
                uploaded_by=phone,
                notes="Unclassified upload",
            )
            session.add(doc)
            return "File saved to archive."
        return "Could not download the image."


# ── Gemini Vision ────────────────────────────────────────────────────────────

async def _gemini_read_image(media_id: str, media_mime: str) -> Optional[dict]:
    """
    Download image from WhatsApp, send to Gemini Flash for classification + extraction.
    Returns dict with: type, amount, name, date, upi_ref, summary — or None on failure.
    """
    import httpx
    import base64
    import os
    import json

    api_key = os.getenv("GEMINI_API_KEY", "")
    wa_token = os.getenv("WHATSAPP_TOKEN", "")
    if not api_key or not wa_token:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Get media URL from WhatsApp
            resp = await client.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers={"Authorization": f"Bearer {wa_token}"},
            )
            resp.raise_for_status()
            media_url = resp.json().get("url")
            if not media_url:
                return None

            # Step 2: Download image bytes
            img_resp = await client.get(media_url, headers={"Authorization": f"Bearer {wa_token}"})
            img_resp.raise_for_status()
            img_bytes = img_resp.content
            img_b64 = base64.b64encode(img_bytes).decode()

            # Step 3: Send to Gemini Flash
            gemini_resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                json={
                    "contents": [{
                        "parts": [
                            {"inline_data": {"mime_type": media_mime or "image/jpeg", "data": img_b64}},
                            {"text": """Analyze this image and respond in JSON only. Classify it as one of:
- payment_receipt (UPI screenshot, bank transfer, cash receipt, payment confirmation)
- expense_bill (electricity bill, water bill, vendor invoice, plumber receipt)
- id_proof (Aadhaar, passport, driving license, PAN card, voter ID)
- license (FSSAI, trade license, fire safety certificate, NOC)
- vendor_slip (delivery challan, stock receipt, order slip)
- other (anything else)

Extract whatever you can read from the image.

Respond ONLY with this JSON:
{
  "type": "payment_receipt|expense_bill|id_proof|license|vendor_slip|other",
  "amount": 0,
  "name": "",
  "date": "",
  "upi_ref": "",
  "payment_mode": "upi|cash|bank_transfer|unknown",
  "summary": "one line description of what this image shows"
}"""}
                        ]
                    }],
                    "generationConfig": {"temperature": 0.0, "maxOutputTokens": 300},
                },
                timeout=15,
            )
            gemini_resp.raise_for_status()

            # Parse response
            text = gemini_resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            # Clean markdown fences
            text = text.strip().strip("`").lstrip("json").strip()
            if text.startswith("```"):
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()

            result = json.loads(text)
            logger.info(f"[Gemini] Image classified: {result.get('type')} | {result.get('summary', '')}")
            return result

    except Exception as e:
        logger.warning(f"[Gemini] Vision failed: {e}")
        return None


async def _handle_gemini_receipt(
    vision: dict,
    media_id: str,
    media_mime: str,
    phone: str,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:
    """Handle a receipt identified by Gemini — try to match tenant and attach."""
    from src.whatsapp.media_handler import download_whatsapp_media

    amount = vision.get("amount", 0)
    name = vision.get("name", "")
    upi_ref = vision.get("upi_ref", "")
    pay_mode = vision.get("payment_mode", "unknown")
    summary = vision.get("summary", "")

    # Save the image first
    file_path = await download_whatsapp_media(media_id, media_mime, "receipts", filename_prefix="gemini")
    if not file_path:
        return "Could not download the image. Please try again."

    # Try to match tenant by name
    matched_payment = None
    match_info = ""
    if name:
        matched_payment, match_info = await _match_from_caption(name, session)

    if matched_payment:
        await _attach_receipt(matched_payment, file_path, media_mime, phone, session)
        lines = [
            f"Receipt auto-detected and saved!\n",
            f"*{match_info}*",
            f"Amount: Rs.{int(amount):,}" if amount else "",
            f"Mode: {pay_mode.upper()}" if pay_mode != "unknown" else "",
            f"UPI Ref: {upi_ref}" if upi_ref else "",
        ]
        return "\n".join(l for l in lines if l)

    # No tenant match — save receipt, show what Gemini found, ask to link
    action_data = {
        "file_path": file_path,
        "gemini": vision,
    }
    await _save_pending(phone, "RECEIPT_NO_PAYMENT", action_data, [], session)

    lines = [
        f"Receipt detected:\n",
        f"Amount: Rs.{int(amount):,}" if amount else "",
        f"Name: {name}" if name else "",
        f"Mode: {pay_mode.upper()}" if pay_mode != "unknown" else "",
        f"UPI Ref: {upi_ref}" if upi_ref else "",
        f"\n_{summary}_" if summary else "",
        f"\nReceipt saved. To link it to a payment, type:",
        f"*[Name] [Amount] [cash/upi] [month]*",
        f"Example: _Raj 15000 upi april_",
    ]
    return "\n".join(l for l in lines if l)


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _match_from_caption(caption: str, session: AsyncSession) -> tuple[Optional[Payment], str]:
    """Try to find a payment matching the caption (tenant name + optional month)."""
    from src.whatsapp.handlers._shared import _fuzzy_match_tenant

    # Extract name-like words from caption (skip numbers, "receipt", "payment" etc.)
    clean = re.sub(r"\b(receipt|payment|paid|cash|upi|april|march|may|jan|feb|jun|jul|aug|sep|oct|nov|dec|\d+)\b", "", caption, flags=re.I).strip()
    if len(clean) < 2:
        return None, ""

    # Try fuzzy tenant match
    rows = await session.execute(
        select(Tenant, Tenancy)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .where(Tenancy.status == TenancyStatus.active)
    )
    all_tenants = rows.all()

    # Simple name matching
    best_match = None
    best_score = 0
    for tenant, tenancy in all_tenants:
        name_lower = (tenant.name or "").lower()
        caption_lower = clean.lower()
        if caption_lower in name_lower or name_lower in caption_lower:
            score = len(name_lower)
            if score > best_score:
                best_match = (tenant, tenancy)
                best_score = score

    if not best_match:
        return None, ""

    tenant, tenancy = best_match

    # Find most recent unattached payment for this tenant
    payment = await session.scalar(
        select(Payment)
        .where(
            Payment.tenancy_id == tenancy.id,
            Payment.is_void == False,
            Payment.receipt_url.is_(None),
        )
        .order_by(desc(Payment.created_at))
        .limit(1)
    )

    if payment:
        room = await session.get(Room, tenancy.room_id)
        room_label = f" (Room {room.room_number})" if room else ""
        return payment, f"{tenant.name}{room_label}"

    return None, ""


async def _get_recent_unattached_payments(
    phone: str, session: AsyncSession, minutes: int = 30,
) -> list[Payment]:
    """Get recent payments logged by this phone that have no receipt attached."""
    from src.database.models import WhatsappLog, MessageDirection

    cutoff = datetime.utcnow() - timedelta(minutes=minutes)

    # Find payments logged recently (by checking whatsapp_log for PAYMENT_LOG from this phone)
    result = await session.execute(
        select(Payment)
        .where(
            Payment.is_void == False,
            Payment.receipt_url.is_(None),
            Payment.created_at >= cutoff,
        )
        .order_by(desc(Payment.created_at))
        .limit(10)
    )
    return list(result.scalars().all())


async def _get_tenant_for_payment(payment: Payment, session: AsyncSession) -> Optional[Tenant]:
    """Get the tenant associated with a payment."""
    tenancy = await session.get(Tenancy, payment.tenancy_id)
    if tenancy:
        return await session.get(Tenant, tenancy.tenant_id)
    return None


async def _attach_receipt(
    payment: Payment,
    file_path: str,
    mime_type: str,
    uploaded_by: str,
    session: AsyncSession,
) -> None:
    """Attach receipt file to a payment and create document record."""
    # Update payment with receipt URL
    payment.receipt_url = file_path

    # Create document registry entry
    tenancy = await session.get(Tenancy, payment.tenancy_id)
    doc = Document(
        doc_type=DocumentType.receipt,
        file_path=file_path,
        original_name=f"receipt_pay{payment.id}",
        mime_type=mime_type,
        tenancy_id=payment.tenancy_id,
        tenant_id=tenancy.tenant_id if tenancy else None,
        uploaded_by=uploaded_by,
        notes=f"Payment #{payment.id} — Rs.{int(payment.amount):,} {payment.payment_mode.value}",
    )
    session.add(doc)
    logger.info(f"[Receipt] Attached {file_path} to payment #{payment.id}")
