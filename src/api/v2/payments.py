"""POST /api/v2/app/payments — log a payment via the Owner PWA."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Room, StayType, Tenancy, TenancyStatus, Tenant
from src.schemas.payments import PaymentCreate, PaymentResponse
from src.services.payments import log_payment

logger = logging.getLogger(__name__)
router = APIRouter()


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
                recorded_by=user.phone or user.user_id,
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
        room = await session.get(Room, tenancy.room_id)
        if room and tenant:
            try:
                from src.integrations.gsheets import update_payment as gsheets_update
                period = datetime.strptime(body.period_month, "%Y-%m")
                from src.services.payments import _resolve_payment_mode
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

        return PaymentResponse(
            payment_id=result.payment_id,
            new_balance=float(result.new_balance),
            receipt_sent=False,
        )
