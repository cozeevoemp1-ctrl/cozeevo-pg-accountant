"""POST /api/v2/app/payments — log a payment via the Owner PWA."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import desc, select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from sqlalchemy.orm import aliased
from src.database.models import Payment, PaymentFor, PaymentMode, Room, StayType, Tenancy, TenancyStatus, Tenant
from src.integrations.gsheets import trigger_monthly_sheet_sync, trigger_daywise_sheet_sync, update_payment as gsheets_update
from src.schemas.payments import PaymentCreate, PaymentEdit, PaymentListItem, PaymentResponse
from src.services.payments import _resolve_payment_mode, log_payment
from src.services.storage import BUCKET_RECEIPTS
from src.services.storage import upload as storage_upload

logger = logging.getLogger(__name__)
router = APIRouter()

_METHOD_MAP = {
    "UPI": PaymentMode.upi,
    "CASH": PaymentMode.cash,
    "BANK": PaymentMode.bank_transfer,
    "CARD": PaymentMode.cheque,
    "OTHER": PaymentMode.cheque,
}


@router.post("/payments", response_model=PaymentResponse, status_code=201)
async def create_payment(body: PaymentCreate, user: AppUser = Depends(get_current_user)):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin or staff only")

    async with get_session() as session:
        # Resolve active tenancy for this tenant
        tenancy = await session.scalar(
            select(Tenancy).where(
                Tenancy.tenant_id == body.tenant_id,
                Tenancy.status == TenancyStatus.active,
            )
        )
        if tenancy is None:
            raise HTTPException(status_code=404, detail=f"No active tenancy for tenant {body.tenant_id}")

        # Resolve tenant name for audit trail
        tenant = await session.get(Tenant, body.tenant_id)
        entity_name = tenant.name if tenant else None

        try:
            result = await log_payment(
                tenancy_id=tenancy.id,
                amount=body.amount,
                method=body.method,
                for_type=body.for_type,
                period_month=body.period_month,
                recorded_by=(user.phone or user.user_id or "")[:30],
                session=session,
                notes=body.notes or None,
                source="pwa",
                room_number=None,
                entity_name=entity_name,
            )
        except ValueError as exc:
            if "duplicate_payment" in str(exc):
                raise HTTPException(status_code=409, detail="Duplicate payment detected")
            raise HTTPException(status_code=400, detail=str(exc))

        await session.commit()

        logger.info(
            "[PWA] payment logged: tenant=%s tenancy=%s amount=%s by=%s",
            body.tenant_id, tenancy.id, body.amount, user.phone,
        )

        # Mirror to Google Sheet (same pattern as WhatsApp handler — 10s timeout)
        # Only rent payments go to Cash/UPI column. Deposit/booking/maintenance are
        # tracked via deposit_credit / booking_credit in sync_sheet_from_db's balance
        # formula — adding them here inflates the Cash column then gets corrected by
        # the background full sync, causing visible temporary inflation on every payment.
        room = await session.get(Room, tenancy.room_id)
        if room and tenant and body.for_type == "rent":
            try:
                if body.period_month:
                    period = datetime.strptime(body.period_month, "%Y-%m")
                else:
                    period = date.today()
                resolved_method = _resolve_payment_mode(body.method).value
                await asyncio.wait_for(
                    gsheets_update(
                        room_number=room.room_number,
                        tenant_name=tenant.name,
                        amount=float(body.amount),
                        method=resolved_method,
                        month=period.month,
                        year=period.year,
                        entered_by=user.phone or user.user_id,
                        is_daily=(tenancy.stay_type == StayType.daily),
                    ),
                    timeout=10,
                )
            except asyncio.TimeoutError:
                logger.warning("[PWA] GSheets write-back timed out (10s)")
            except Exception as exc:
                logger.warning("[PWA] GSheets write-back failed: %s", exc)

        # Trigger full sync so COLLECTION summary row (Total Dues) stays correct
        if tenancy.stay_type == StayType.daily:
            trigger_daywise_sheet_sync()
        else:
            trigger_monthly_sheet_sync(period.month, period.year)

        return PaymentResponse(
            payment_id=result.payment_id,
            new_balance=float(result.new_balance),
            receipt_sent=False,
        )


@router.get("/payments", response_model=List[PaymentListItem])
async def list_payments(
    tenancy_id: Optional[int] = Query(None),
    tenant_id: Optional[int] = Query(None),
    limit: int = Query(default=30, le=100),
    user: AppUser = Depends(get_current_user),
):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin or staff only")

    async with get_session() as session:
        # Resolve tenant_id → tenancy_id
        if tenant_id and not tenancy_id:
            tenancy = await session.scalar(
                select(Tenancy).where(
                    Tenancy.tenant_id == tenant_id,
                    Tenancy.status == TenancyStatus.active,
                )
            )
            if tenancy is None:
                return []
            tenancy_id = tenancy.id

        # Build query — always join tenant+room for display names
        q = (
            select(
                Payment,
                Tenant.name.label("tenant_name"),
                Room.room_number.label("room_number"),
            )
            .join(Tenancy, Tenancy.id == Payment.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .outerjoin(Room, Room.id == Tenancy.room_id)
            .where(Payment.is_void == False)
        )
        if tenancy_id:
            q = q.where(Payment.tenancy_id == tenancy_id)

        q = q.order_by(desc(Payment.payment_date), desc(Payment.id)).limit(limit)
        rows = (await session.execute(q)).all()

    result = []
    for row in rows:
        p = row[0]
        pm = p.period_month.strftime("%Y-%m") if p.period_month else None
        result.append(PaymentListItem(
            payment_id=p.id,
            amount=float(p.amount),
            method=p.payment_mode.value.upper() if p.payment_mode else "CASH",
            for_type=p.for_type.value if p.for_type else "rent",
            period_month=pm,
            payment_date=p.payment_date.strftime("%Y-%m-%d"),
            notes=p.notes,
            is_void=p.is_void,
            receipt_url=p.receipt_url,
            upi_reference=p.upi_reference,
            tenant_name=row[1],
            room_number=row[2],
        ))
    return result


@router.patch("/payments/{payment_id}", response_model=PaymentListItem)
async def edit_payment(
    payment_id: int,
    body: PaymentEdit,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin or staff only")

    async with get_session() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")
        if payment.is_void:
            raise HTTPException(status_code=409, detail="Cannot edit a voided payment")

        changed = []
        if body.method is not None:
            payment.payment_mode = _METHOD_MAP.get(body.method, PaymentMode.cash)
            changed.append(f"method→{body.method}")
        if body.amount is not None:
            payment.amount = body.amount
            changed.append(f"amount→{body.amount}")
        if body.notes is not None:
            payment.notes = body.notes
            changed.append("notes updated")
        if body.for_type is not None:
            payment.for_type = PaymentFor(body.for_type)  # type: ignore[assignment]
            changed.append(f"for_type→{body.for_type}")

        await session.commit()
        await session.refresh(payment)

        logger.info("[PWA] payment edited: id=%s changes=%s by=%s", payment_id, changed, user.phone)

    # Re-sync sheet if method changed (affects Cash vs UPI column)
    if body.method is not None and payment.period_month:
        try:
            async with get_session() as session:
                tenancy = await session.get(Tenancy, payment.tenancy_id)
                if tenancy:
                    room = await session.get(Room, tenancy.room_id)
                    tenant = await session.get(Tenant, tenancy.tenant_id)
                    if room and tenant and payment.for_type and payment.for_type.value == "rent":
                        resolved = _resolve_payment_mode(body.method).value
                        await asyncio.wait_for(
                            gsheets_update(
                                room_number=room.room_number,
                                tenant_name=tenant.name,
                                amount=float(payment.amount),
                                method=resolved,
                                month=payment.period_month.month,
                                year=payment.period_month.year,
                                entered_by=user.phone or user.user_id,
                                is_daily=(tenancy.stay_type == StayType.daily),
                            ),
                            timeout=10,
                        )
                        if tenancy.stay_type == StayType.daily:
                            trigger_daywise_sheet_sync()
                        else:
                            trigger_monthly_sheet_sync(payment.period_month.month, payment.period_month.year)
        except Exception as exc:
            logger.warning("[PWA] sheet re-sync after edit failed: %s", exc)

    pm = str(payment.period_month.strftime("%Y-%m")) if payment.period_month else None
    return PaymentListItem(
        payment_id=payment.id,
        amount=float(payment.amount),
        method=payment.payment_mode.value.upper() if payment.payment_mode else "CASH",
        for_type=payment.for_type.value if payment.for_type else "rent",
        period_month=pm,
        payment_date=payment.payment_date.strftime("%Y-%m-%d"),
        notes=payment.notes,
        is_void=payment.is_void,
        receipt_url=payment.receipt_url,
        upi_reference=payment.upi_reference,
    )


_ALLOWED_RECEIPT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
_MAX_RECEIPT_BYTES = 8 * 1024 * 1024  # 8 MB


@router.post("/payments/ocr")
async def ocr_receipt_preview(
    file: UploadFile = File(...),
    user: AppUser = Depends(get_current_user),
):
    """Scan a payment screenshot before recording — returns extracted amount, txn ID, method hint."""
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin or staff only")
    if file.content_type not in _ALLOWED_RECEIPT_TYPES:
        raise HTTPException(status_code=400, detail="Image required (jpeg/png/webp/heic)")
    data = await file.read()
    if len(data) > _MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=413, detail="File too large — max 8 MB")

    result = await _ocr_receipt_full(data, file.content_type or "image/jpeg")
    return result


async def _ocr_receipt_full(image_data: bytes, content_type: str) -> dict:
    """Extract amount, transaction ID, and payment method from a receipt screenshot."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("PASTE_"):
        return {"amount": None, "transaction_id": None, "method": None}
    try:
        import anthropic
        media_type = content_type if content_type in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg"
        b64 = base64.standard_b64encode(image_data).decode("utf-8")
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                        {"type": "text", "text": (
                            "This is a UPI or bank payment screenshot/receipt from India. Extract:\n"
                            "1. amount: the payment amount as a number in rupees (digits only, no symbols)\n"
                            "2. transaction_id: the UTR / Transaction ID / Ref No (alphanumeric string)\n"
                            "3. method: one of UPI, NEFT, IMPS, RTGS, CASH — whichever applies\n"
                            "Return JSON only: {\"amount\": 15000, \"transaction_id\": \"T2026...\", \"method\": \"UPI\"}\n"
                            "Use null for any field you cannot find."
                        )},
                    ],
                }],
            ),
            timeout=15,
        )
        import json as _json
        raw = msg.content[0].text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = _json.loads(raw)
        txn = data.get("transaction_id")
        if txn and len(str(txn)) > 60:
            txn = None
        method = data.get("method", "").upper()
        if method not in ("UPI", "NEFT", "IMPS", "RTGS", "CASH", "BANK"):
            method = None
        if method in ("NEFT", "IMPS", "RTGS"):
            method = "BANK"
        amt = data.get("amount")
        if amt is not None:
            try:
                amt = int(float(str(amt).replace(",", "")))
            except Exception:
                amt = None
        return {"amount": amt, "transaction_id": txn, "method": method}
    except Exception as exc:
        logger.warning("[OCR] full receipt extraction failed: %s", exc)
        return {"amount": None, "transaction_id": None, "method": None}


async def _ocr_transaction_id(image_data: bytes, content_type: str) -> Optional[str]:
    """Call Claude Haiku vision to extract transaction/UPI reference ID from receipt image."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("PASTE_"):
        return None
    try:
        import anthropic
        media_type = content_type if content_type in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg"
        b64 = base64.standard_b64encode(image_data).decode("utf-8")
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=128,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Look at this payment receipt or UPI screenshot. "
                                "Extract ONLY the transaction reference ID. "
                                "It may be labeled: Transaction ID, UTR, Ref No, UPI Ref, IMPS Ref, Reference Number, or similar. "
                                "Return ONLY the alphanumeric ID string, nothing else. "
                                "If you cannot find any transaction ID, return the word null."
                            ),
                        },
                    ],
                }],
            ),
            timeout=15,
        )
        raw = msg.content[0].text.strip()
        if raw.lower() in ("null", "none", "", "not found", "n/a"):
            return None
        # Keep only alphanumeric + common separator chars; reject multi-line or long prose
        clean = raw.split("\n")[0].strip()
        return clean if len(clean) <= 50 else None
    except Exception as exc:
        logger.warning("[OCR] transaction ID extraction failed: %s", exc)
        return None


@router.post("/payments/{payment_id}/receipt")
async def upload_receipt(
    payment_id: int,
    file: UploadFile = File(...),
    user: AppUser = Depends(get_current_user),
):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin or staff only")

    if file.content_type not in _ALLOWED_RECEIPT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}. Allowed: jpeg, png, webp, heic")

    data = await file.read()
    if len(data) > _MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 8 MB")

    async with get_session() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")

        path = f"{payment.payment_date.strftime('%Y-%m')}/{payment_id}.jpg"
        url = await storage_upload(BUCKET_RECEIPTS, path, data, file.content_type)

        # OCR: extract transaction ID from receipt image (best-effort, 15s cap)
        txn_id = await _ocr_transaction_id(data, file.content_type or "image/jpeg")

        payment.receipt_url = url
        if txn_id:
            payment.upi_reference = txn_id
        await session.commit()

    logger.info(
        "[PWA] receipt uploaded: payment=%s txn_id=%s url=%s by=%s",
        payment_id, txn_id, url, user.phone,
    )
    return {"payment_id": payment_id, "receipt_url": url, "transaction_id": txn_id}
