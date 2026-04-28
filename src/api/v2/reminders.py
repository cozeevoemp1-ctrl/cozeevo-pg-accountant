"""GET /api/v2/app/reminders/overdue — list overdue tenants with reminder history.
POST /api/v2/app/reminders/send — send rent_reminder WhatsApp template to one or all overdue.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_, select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    Payment,
    PaymentFor,
    Property,
    Reminder,
    ReminderStatus,
    ReminderType,
    RentSchedule,
    Room,
    Tenancy,
    TenancyStatus,
    Tenant,
)
from src.whatsapp.reminder_sender import send_template

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reminders")


def _month_label(d: date) -> str:
    return d.strftime("%B %Y")  # e.g. "April 2026"


def _build_paid_subq(period: date, period_end: date):
    return (
        select(Payment.tenancy_id, func.sum(Payment.amount).label("paid"))
        .where(
            Payment.is_void == False,
            or_(
                and_(Payment.for_type == PaymentFor.rent, Payment.period_month == period),
                and_(
                    Payment.for_type.in_([PaymentFor.deposit, PaymentFor.booking]),
                    Payment.period_month == None,
                    Payment.payment_date >= period,
                    Payment.payment_date < period_end,
                ),
            ),
        )
        .group_by(Payment.tenancy_id)
        .subquery()
    )


async def _get_overdue_rows(session):
    today = date.today()
    period = date(today.year, today.month, 1)
    next_m = today.month % 12 + 1
    next_y = today.year + (1 if today.month == 12 else 0)
    period_end = date(next_y, next_m, 1)

    paid_subq = _build_paid_subq(period, period_end)
    eff_due_col = (RentSchedule.rent_due + func.coalesce(RentSchedule.adjustment, 0)).label("effective_due")

    rows = (await session.execute(
        select(
            Tenancy.id.label("tenancy_id"),
            Tenant.id.label("tenant_id"),
            Tenant.name,
            Tenant.phone,
            Room.room_number,
            eff_due_col,
            func.coalesce(paid_subq.c.paid, 0).label("paid"),
        )
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .join(Room, Room.id == Tenancy.room_id)
        .join(Property, Property.id == Room.property_id)
        .join(RentSchedule, RentSchedule.tenancy_id == Tenancy.id)
        .outerjoin(paid_subq, paid_subq.c.tenancy_id == Tenancy.id)
        .where(
            RentSchedule.period_month == period,
            Tenancy.status == TenancyStatus.active,
            (RentSchedule.rent_due + func.coalesce(RentSchedule.adjustment, 0)) > func.coalesce(paid_subq.c.paid, 0),
        )
    )).all()
    return rows, period


@router.get("/overdue")
async def get_overdue(user: AppUser = Depends(get_current_user)):
    async with get_session() as session:
        rows, period = await _get_overdue_rows(session)

        tenancy_ids = [r.tenancy_id for r in rows]

        # Reminder history per tenancy
        reminder_counts = {}
        reminder_last = {}
        if tenancy_ids:
            rem_rows = (await session.execute(
                select(
                    Reminder.tenancy_id,
                    func.count(Reminder.id).label("cnt"),
                    func.max(Reminder.sent_at).label("last_at"),
                )
                .where(
                    Reminder.tenancy_id.in_(tenancy_ids),
                    Reminder.reminder_type == ReminderType.rent_due,
                )
                .group_by(Reminder.tenancy_id)
            )).all()
            for rem in rem_rows:
                reminder_counts[rem.tenancy_id] = rem.cnt
                reminder_last[rem.tenancy_id] = rem.last_at

    result = []
    for r in rows:
        dues = int(r.effective_due - r.paid)
        last_at = reminder_last.get(r.tenancy_id)
        result.append({
            "tenancy_id": r.tenancy_id,
            "tenant_id": r.tenant_id,
            "name": r.name,
            "phone": r.phone,
            "room": r.room_number,
            "dues": dues,
            "reminder_count": reminder_counts.get(r.tenancy_id, 0),
            "last_reminded_at": last_at.isoformat() if last_at else None,
        })
    return result


@router.post("/send")
async def send_reminders(
    body: dict,
    user: AppUser = Depends(get_current_user),
):
    send_all: bool = body.get("send_all", False)
    tenancy_id: int | None = body.get("tenancy_id")

    if not send_all and tenancy_id is None:
        raise HTTPException(status_code=400, detail="Provide tenancy_id or send_all=true")

    now = datetime.utcnow()

    async with get_session() as session:
        rows, period = await _get_overdue_rows(session)

        if send_all:
            targets = rows
        else:
            targets = [r for r in rows if r.tenancy_id == tenancy_id]
            if not targets:
                raise HTTPException(status_code=404, detail=f"Tenancy {tenancy_id} not found or not overdue")

        sent = []
        failed = []
        for r in targets:
            ok = await send_template(
                r.phone,
                "rent_reminder",
                body_params=[r.name],
            )
            if ok:
                reminder = Reminder(
                    tenancy_id=r.tenancy_id,
                    reminder_type=ReminderType.rent_due,
                    sent_at=now,
                    status=ReminderStatus.sent,
                    created_by="pwa",
                    remind_at=now,
                )
                session.add(reminder)
                sent.append(r.tenancy_id)
            else:
                failed.append(r.tenancy_id)

        if sent:
            await session.commit()

    return {"sent": sent, "failed": failed}
