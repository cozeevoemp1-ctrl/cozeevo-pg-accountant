"""
GET  /api/v2/app/tenants/{tenancy_id}/checkin-preview  — live-calculate what's due
POST /api/v2/app/checkin                               — record physical check-in
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    Payment, PaymentFor, PaymentMode, Property, Room,
    RentSchedule, RentStatus, StayType, Tenancy, TenancyStatus, Tenant,
)
from src.services.payments import log_payment
from src.services.rent_schedule import first_month_rent_due, prorated_first_month_rent

logger = logging.getLogger(__name__)
router = APIRouter()

# Maps PWA method strings to PaymentMode enum (must stay in sync with PWA Method type)
_CHECKIN_METHOD_MAP: dict[str, PaymentMode] = {
    "CASH":          PaymentMode.cash,
    "UPI":           PaymentMode.upi,
    "BANK":          PaymentMode.bank_transfer,
    "BANK_TRANSFER": PaymentMode.bank_transfer,
    "OTHER":         PaymentMode.cash,
    "CHEQUE":        PaymentMode.cheque,
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid date: {s!r} — expected YYYY-MM-DD")


def _calc_monthly_preview(tenancy: Tenancy, actual_date: date) -> dict:
    """Return the first-month payment breakdown for a monthly tenant."""
    rent        = Decimal(str(tenancy.agreed_rent or 0))
    deposit     = Decimal(str(tenancy.security_deposit or 0))
    booking_amt = Decimal(str(tenancy.booking_amount or 0))
    prorated    = prorated_first_month_rent(rent, actual_date)
    first_month = prorated + deposit
    balance_due = first_month - booking_amt
    return {
        "stay_type":      "monthly",
        "agreed_rent":    float(rent),
        "security_deposit": float(deposit),
        "booking_amount": float(booking_amt),
        "prorated_rent":  float(prorated),
        "first_month_total": float(first_month),
        "balance_due":    float(max(balance_due, Decimal("0"))),
        "overpayment":    float(max(-balance_due, Decimal("0"))),
        "date_changed":   actual_date != tenancy.checkin_date,
        "agreed_checkin_date": tenancy.checkin_date.isoformat() if tenancy.checkin_date else None,
        # day-wise fields (null for monthly)
        "daily_rate": None,
        "num_days": None,
        "checkout_date": None,
        "total_stay_amount": None,
    }


def _calc_daily_preview(tenancy: Tenancy, actual_date: date) -> dict:
    """Return the stay payment breakdown for a daily tenant."""
    daily_rate  = Decimal(str(tenancy.agreed_rent or 0))   # agreed_rent = rate/day
    booking_amt = Decimal(str(tenancy.booking_amount or 0))
    checkout_dt = tenancy.checkout_date
    num_days    = max((checkout_dt - actual_date).days, 1) if checkout_dt else 1
    total_amt   = daily_rate * num_days
    balance_due = total_amt - booking_amt
    return {
        "stay_type":      "daily",
        "agreed_rent":    float(daily_rate),
        "security_deposit": 0.0,
        "booking_amount": float(booking_amt),
        "prorated_rent":  0.0,
        "first_month_total": float(total_amt),   # repurposed: total stay cost
        "balance_due":    float(max(balance_due, Decimal("0"))),
        "overpayment":    float(max(-balance_due, Decimal("0"))),
        "date_changed":   actual_date != tenancy.checkin_date,
        "agreed_checkin_date": tenancy.checkin_date.isoformat() if tenancy.checkin_date else None,
        # day-wise specific
        "daily_rate":        float(daily_rate),
        "num_days":          num_days,
        "checkout_date":     checkout_dt.isoformat() if checkout_dt else None,
        "total_stay_amount": float(total_amt),
    }


def _calc_preview(tenancy: Tenancy, actual_date: date) -> dict:
    if tenancy.stay_type == StayType.daily:
        return _calc_daily_preview(tenancy, actual_date)
    return _calc_monthly_preview(tenancy, actual_date)


# ── GET preview ──────────────────────────────────────────────────────────────

@router.get("/tenants/{tenancy_id}/checkin-preview")
async def checkin_preview(
    tenancy_id: int,
    actual_date: str = Query(default=None),
    user: AppUser = Depends(get_current_user),
):
    parsed_date = _parse_date(actual_date) if actual_date else date.today()

    async with get_session() as session:
        row = await session.execute(
            select(Tenancy, Tenant, Room, Property)
            .join(Tenant,   Tenancy.tenant_id == Tenant.id)
            .join(Room,     Tenancy.room_id   == Room.id)
            .join(Property, Room.property_id  == Property.id)
            .where(Tenancy.id == tenancy_id)
        )
        result = row.first()

    if result is None:
        raise HTTPException(status_code=404, detail=f"Tenancy {tenancy_id} not found")

    tenancy, tenant, room, prop = result

    preview = _calc_preview(tenancy, parsed_date)
    return {
        "tenancy_id":    tenancy.id,
        "tenant_id":     tenant.id,
        "name":          tenant.name,
        "phone":         tenant.phone,
        "room_number":   room.room_number,
        "building_code": prop.name.split()[-1] if prop.name else "",
        "actual_date":   parsed_date.isoformat(),
        **preview,
    }


# ── POST check-in ─────────────────────────────────────────────────────────────

class CheckinRequest(BaseModel):
    tenancy_id:        int
    actual_checkin_date: str        # YYYY-MM-DD — actual day tenant physically arrived
    amount_collected:  float        # what was collected today (can be 0)
    payment_method:    str          # CASH / UPI / BANK_TRANSFER / CHEQUE
    notes:             str = ""


class CheckinResponse(BaseModel):
    tenancy_id:          int
    checkin_date_used:   str
    date_changed:        bool
    prorated_rent:       float
    first_month_total:   float
    booking_amount:      float
    amount_collected:    float
    balance_remaining:   float
    payment_id:          int | None


@router.post("/checkin", response_model=CheckinResponse, status_code=201)
async def record_physical_checkin(
    body: CheckinRequest,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin or staff only")

    actual_date = _parse_date(body.actual_checkin_date)

    method = _CHECKIN_METHOD_MAP.get(body.payment_method.upper())
    if method is None:
        raise HTTPException(status_code=400, detail=f"Unknown payment method: {body.payment_method!r} — use CASH, UPI, BANK, or CHEQUE")

    async with get_session() as session:
        # Load tenancy + related
        row = await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room,   Tenancy.room_id   == Room.id)
            .where(
                Tenancy.id     == body.tenancy_id,
                Tenancy.status == TenancyStatus.active,
            )
        )
        result = row.first()

    if result is None:
        raise HTTPException(status_code=404, detail=f"No active tenancy {body.tenancy_id}")

    tenancy, tenant, room = result

    preview      = _calc_preview(tenancy, actual_date)
    date_changed = preview["date_changed"]
    is_daily     = tenancy.stay_type == StayType.daily

    async with get_session() as session:
        # Re-load tenancy in this session for mutation
        tenancy = await session.get(Tenancy, body.tenancy_id)
        tenant  = await session.get(Tenant, tenancy.tenant_id)
        room    = await session.get(Room,   tenancy.room_id)

        # Update check-in date if it changed
        if date_changed:
            tenancy.checkin_date = actual_date

        if not is_daily:
            # Monthly: recalculate first-month RentSchedule if date changed
            if date_changed:
                period = date(actual_date.year, actual_date.month, 1)
                rs = await session.scalar(
                    select(RentSchedule).where(
                        RentSchedule.tenancy_id   == tenancy.id,
                        RentSchedule.period_month == period,
                    )
                )
                new_rent_due = first_month_rent_due(tenancy, period)
                if rs:
                    rs.rent_due = new_rent_due
                else:
                    session.add(RentSchedule(
                        tenancy_id      = tenancy.id,
                        period_month    = period,
                        rent_due        = new_rent_due,
                        maintenance_due = tenancy.maintenance_fee or Decimal("0"),
                        status          = RentStatus.pending,
                        due_date        = period,
                    ))
            await session.flush()

        # Log payment if amount > 0
        payment_id = None
        if body.amount_collected > 0:
            period_month_str = actual_date.strftime("%Y-%m")
            result = await log_payment(
                tenancy_id   = tenancy.id,
                amount       = Decimal(str(body.amount_collected)),
                method       = method,
                for_type     = PaymentFor.rent,
                period_month = period_month_str,
                recorded_by  = user.phone or user.user_id,
                session      = session,
                notes        = body.notes or ("Daily stay check-in payment" if is_daily else "Physical check-in payment"),
                source       = "physical_checkin",
                room_number  = room.room_number if room else None,
                entity_name  = tenant.name if tenant else None,
            )
            payment_id = result.payment_id

        await session.commit()

        logger.info(
            "[PWA] physical check-in: tenancy=%s tenant=%s actual=%s amount=%s date_changed=%s",
            body.tenancy_id, tenancy.tenant_id, actual_date, body.amount_collected, date_changed,
        )

    # ── WhatsApp notification ─────────────────────────────────────────────
    _notify_checkin_bg(tenant, room, actual_date, body, preview)

    # ── Google Sheet write-back ───────────────────────────────────────────
    if body.amount_collected > 0 and room and tenant:
        try:
            from src.integrations.gsheets import update_payment as gsheets_update
            gsheets_method = method.value   # use the resolved PaymentMode enum value (e.g. "bank_transfer")
            await asyncio.wait_for(
                gsheets_update(
                    room_number  = room.room_number,
                    tenant_name  = tenant.name,
                    amount       = float(body.amount_collected),
                    method       = gsheets_method,
                    month        = actual_date.month,
                    year         = actual_date.year,
                    entered_by   = user.phone or user.user_id,
                    is_daily     = is_daily,
                ),
                timeout=10,
            )
        except asyncio.TimeoutError:
            logger.warning("[PWA] GSheets write-back timed out (10s) on checkin")
        except Exception as exc:
            logger.warning("[PWA] GSheets write-back failed on checkin: %s", exc)

    booking_amt = float(tenancy.booking_amount or 0)
    collected   = body.amount_collected
    first_total = preview["first_month_total"]
    balance_remaining = max(first_total - booking_amt - collected, 0.0)

    return CheckinResponse(
        tenancy_id        = body.tenancy_id,
        checkin_date_used = actual_date.isoformat(),
        date_changed      = date_changed,
        prorated_rent     = preview["prorated_rent"],
        first_month_total = first_total,
        booking_amount    = booking_amt,
        amount_collected  = collected,
        balance_remaining = balance_remaining,
        payment_id        = payment_id,
    )


def _notify_checkin_bg(tenant: Tenant, room: Room, actual_date: date,
                       body: CheckinRequest, preview: dict) -> None:
    """Fire-and-forget WhatsApp notification — does NOT block the response."""
    import asyncio as _asyncio

    async def _send():
        try:
            from src.whatsapp.webhook_handler import _send_whatsapp_template, _send_whatsapp

            phone = (tenant.phone or "").strip().lstrip("+").replace(" ", "")
            if not phone:
                return
            if not phone.startswith("91"):
                phone = "91" + phone

            room_number  = room.room_number if room else "—"
            date_str     = actual_date.strftime("%d %b %Y")
            # cozeevo_checkin_welcome: name, room, date, rent, deposit (PENDING approval)
            # Falls back to cozeevo_booking_confirmation (same vars, already APPROVED)
            rent_val    = preview["agreed_rent"]
            deposit_val = preview["security_deposit"]
            tpl_sent = await _send_whatsapp_template(
                phone,
                "cozeevo_checkin_welcome",
                [
                    tenant.name,
                    room_number,
                    date_str,
                    f"Rs.{int(rent_val):,}",
                    f"Rs.{int(deposit_val):,}",
                ],
            )
            if not tpl_sent:
                tpl_sent = await _send_whatsapp_template(
                    phone,
                    "cozeevo_booking_confirmation",
                    [
                        tenant.name,
                        room_number,
                        date_str,
                        f"Rs.{int(rent_val):,}",
                        f"Rs.{int(deposit_val):,}",
                    ],
                )

            # Supplementary free-text with payment details (works within 24hr window)
            collected   = body.amount_collected
            booking_amt = preview["booking_amount"]
            balance     = max(preview["first_month_total"] - booking_amt - collected, 0.0)
            date_changed_note = (
                f"\n\nNote: your check-in date has been updated from "
                f"{preview['agreed_checkin_date']} to {actual_date.isoformat()}. "
                f"Rent has been recalculated accordingly."
                if preview["date_changed"] else ""
            )
            await _send_whatsapp(
                phone,
                f"Check-in payment summary:\n"
                f"Collected today: Rs.{int(collected):,} ({body.payment_method})\n"
                f"Advance paid earlier: Rs.{int(booking_amt):,}\n"
                f"Balance remaining: Rs.{int(balance):,}"
                f"{date_changed_note}\n\n"
                f"— Cozeevo Help Desk",
                intent="CHECKIN_PAYMENT_SUMMARY",
            )
        except Exception as exc:
            logger.warning("[PWA] checkin notification failed: %s", exc)

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_send())
        else:
            loop.run_until_complete(_send())
    except Exception as exc:
        logger.warning("[PWA] checkin notification scheduling failed: %s", exc)
