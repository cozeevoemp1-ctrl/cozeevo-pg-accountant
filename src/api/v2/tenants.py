"""GET /api/v2/app/tenants/search — tenant search for the Owner PWA.
GET /api/v2/app/tenants/{tenancy_id}/dues — dues for current month.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    AuditLog,
    Payment,
    PaymentFor,
    Property,
    RentRevision,
    RentSchedule,
    Room,
    SharingType,
    Tenancy,
    TenancyStatus,
    Tenant,
)
from services.room_transfer import execute_room_transfer

logger = logging.getLogger(__name__)
router = APIRouter()


def _building_code(property_name: str) -> str:
    """Extract building code from property name, e.g. 'Cozeevo THOR' → 'THOR'."""
    return property_name.split()[-1] if property_name else ""


@router.get("/tenants/list")
async def list_tenants(_user: AppUser = Depends(get_current_user)):
    """All active/no_show tenants with current month dues for the Manage hub."""
    today = date.today()
    period = date(today.year, today.month, 1)
    next_m = today.month % 12 + 1
    next_y = today.year + (1 if today.month == 12 else 0)
    period_end = date(next_y, next_m, 1)

    async with get_session() as session:
        paid_subq = (
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
        rows = (await session.execute(
            select(Tenancy, Tenant, Room, Property,
                   RentSchedule.rent_due, RentSchedule.adjustment,
                   func.coalesce(paid_subq.c.paid, 0).label("paid"))
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .join(Property, Room.property_id == Property.id)
            .outerjoin(RentSchedule, and_(
                RentSchedule.tenancy_id == Tenancy.id,
                RentSchedule.period_month == period,
            ))
            .outerjoin(paid_subq, paid_subq.c.tenancy_id == Tenancy.id)
            .where(Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
            .order_by(Room.room_number)
        )).all()

    result = []
    for tenancy, tenant, room, prop, rent_due, adjustment, paid in rows:
        rd = float(rent_due or tenancy.agreed_rent or 0)
        adj = float(adjustment or 0)
        dues = max(rd + adj - float(paid), 0.0)
        result.append({
            "tenancy_id": tenancy.id,
            "tenant_id": tenant.id,
            "name": tenant.name,
            "phone": tenant.phone,
            "room_number": room.room_number,
            "building_code": _building_code(prop.name),
            "rent": float(tenancy.agreed_rent or 0),
            "dues": dues,
            "status": tenancy.status.value,
        })
    return result


@router.get("/tenants/search")
async def search_tenants(
    q: str = Query(default=None),
    user: AppUser = Depends(get_current_user),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")

    term = q.strip().lower()
    # Numeric query → exact room match only (skip name/phone to avoid phone-number hits)
    if term.isdigit():
        match_clause = func.lower(Room.room_number) == term
    else:
        match_clause = or_(
            func.lower(Tenant.name).contains(term),
            func.lower(Room.room_number).contains(term),
            func.lower(Tenant.phone).contains(term),
        )

    async with get_session() as session:
        stmt = (
            select(Tenancy, Tenant, Room, Property)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .join(Property, Room.property_id == Property.id)
            .where(
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                match_clause,
            )
            .order_by(Tenant.name)
            .limit(10)
        )
        rows = (await session.execute(stmt)).all()

    return [
        {
            "tenancy_id": tenancy.id,
            "tenant_id": tenant.id,
            "name": tenant.name,
            "phone": tenant.phone,
            "room_number": room.room_number,
            "building_code": _building_code(prop.name),
            "rent": float(tenancy.agreed_rent) if tenancy.agreed_rent is not None else 0.0,
            "status": tenancy.status.value,
        }
        for tenancy, tenant, room, prop in rows
    ]


@router.get("/tenants/{tenancy_id}/dues")
async def get_tenant_dues(
    tenancy_id: int,
    user: AppUser = Depends(get_current_user),
):
    async with get_session() as session:
        row = await session.execute(
            select(Tenancy, Tenant, Room, Property)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .join(Property, Room.property_id == Property.id)
            .where(Tenancy.id == tenancy_id)
        )
        result = row.first()

    if result is None:
        raise HTTPException(status_code=404, detail=f"Tenancy {tenancy_id} not found")

    tenancy, tenant, room, prop = result

    # Current period: first day of current month
    today = date.today()
    period_month = date(today.year, today.month, 1)

    next_m = today.month % 12 + 1
    next_y = today.year + (1 if today.month == 12 else 0)
    period_end = date(next_y, next_m, 1)

    async with get_session() as session:
        # Rent paid this period — includes deposit/booking paid in same calendar month
        paid_result = await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,
                or_(
                    and_(Payment.for_type == PaymentFor.rent, Payment.period_month == period_month),
                    and_(
                        Payment.for_type.in_([PaymentFor.deposit, PaymentFor.booking]),
                        Payment.period_month == None,
                        Payment.payment_date >= period_month,
                        Payment.payment_date < period_end,
                    ),
                ),
            )
        )
        # RentSchedule for this period (has correct rent_due: rent+deposit for first month)
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy_id,
                RentSchedule.period_month == period_month,
            )
        )

    rent = float(tenancy.agreed_rent) if tenancy.agreed_rent is not None else 0.0
    paid = float(paid_result) if paid_result is not None else 0.0

    # rent_due from RentSchedule is the source of truth — already set from ops sheet
    # (fix_april_dues.py locked these to exact sheet balances, advance already factored in)
    rent_due   = float(rs.rent_due)   if rs else rent
    adjustment = float(rs.adjustment) if rs and rs.adjustment else 0.0

    effective_due = rent_due + adjustment
    dues = max(effective_due - paid, 0.0)
    credit = max(paid - effective_due, 0.0)
    booking_amount = float(tenancy.booking_amount) if tenancy.booking_amount else 0.0

    # Last payment (any type, not voided) for this tenancy
    async with get_session() as session:
        last_payment = await session.scalar(
            select(Payment)
            .where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,
            )
            .order_by(Payment.payment_date.desc())
            .limit(1)
        )

    return {
        "tenancy_id": tenancy.id,
        "tenant_id": tenant.id,
        "name": tenant.name,
        "phone": tenant.phone,
        "email": tenant.email or "",
        "room_number": room.room_number,
        "building_code": _building_code(prop.name),
        "rent": rent,
        "rent_due": rent_due,
        "adjustment": adjustment,
        "adjustment_note": rs.adjustment_note if rs else None,
        "booking_amount": booking_amount,
        "dues": dues,
        "credit": credit,
        "checkin_date": tenancy.checkin_date.isoformat() if tenancy.checkin_date else None,
        "security_deposit": float(tenancy.security_deposit) if tenancy.security_deposit is not None else 0.0,
        "maintenance_fee": float(tenancy.maintenance_fee) if tenancy.maintenance_fee is not None else 0.0,
        "lock_in_months": tenancy.lock_in_months or 0,
        "notes": tenancy.notes or "",
        "last_payment_date": last_payment.payment_date.isoformat() if last_payment else None,
        "last_payment_amount": float(last_payment.amount) if last_payment else None,
        "period_month": period_month.strftime("%Y-%m"),
        "notice_date": tenancy.notice_date.isoformat() if tenancy.notice_date else None,
        "expected_checkout": tenancy.expected_checkout.isoformat() if tenancy.expected_checkout else None,
    }


@router.patch("/tenants/{tenancy_id}")
async def update_tenant(
    tenancy_id: int,
    body: dict,
    user: AppUser = Depends(get_current_user),
):
    async with get_session() as session:
        row = await session.execute(
            select(Tenancy, Tenant)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .where(Tenancy.id == tenancy_id)
        )
        result = row.first()

    if result is None:
        raise HTTPException(status_code=404, detail=f"Tenancy {tenancy_id} not found")

    tenancy, tenant = result

    # Floor / ceiling checks — reject bad values before touching DB
    if "agreed_rent" in body and float(body["agreed_rent"]) <= 0:
        raise HTTPException(status_code=422, detail="agreed_rent must be > 0")
    if "security_deposit" in body and float(body["security_deposit"]) < 0:
        raise HTTPException(status_code=422, detail="security_deposit cannot be negative")
    if "maintenance_fee" in body and float(body["maintenance_fee"]) < 0:
        raise HTTPException(status_code=422, detail="maintenance_fee cannot be negative")
    if "lock_in_months" in body and int(body["lock_in_months"]) < 0:
        raise HTTPException(status_code=422, detail="lock_in_months cannot be negative")

    async with get_session() as session:
        # Re-fetch within the write session so SQLAlchemy tracks changes
        row2 = await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(Tenancy.id == tenancy_id)
        )
        tenancy, tenant, room = row2.first()

        # RentRevision if agreed_rent changes
        if "agreed_rent" in body:
            new_rent = body["agreed_rent"]
            current_rent = float(tenancy.agreed_rent) if tenancy.agreed_rent is not None else 0.0
            if float(new_rent) != current_rent:
                revision = RentRevision(
                    tenancy_id=tenancy_id,
                    old_rent=current_rent,
                    new_rent=new_rent,
                    effective_date=date.today(),
                    changed_by=user.user_id or "pwa",
                    reason=body.get("rent_change_reason", ""),
                    org_id=tenancy.org_id,
                )
                session.add(revision)

        # Tenant fields
        if "name" in body:
            tenant.name = body["name"]
        if "phone" in body:
            new_phone = body["phone"]
            if new_phone and new_phone != tenant.phone:
                conflict = await session.scalar(
                    select(Tenant.id).where(
                        Tenant.phone == new_phone,
                        Tenant.id != tenant.id,
                    )
                )
                if conflict:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Phone {new_phone} is already registered to another tenant.",
                    )
            tenant.phone = new_phone
        if "email" in body:
            tenant.email = body["email"]
        if "tenant_notes" in body:
            tenant.notes = body["tenant_notes"]

        # Tenancy fields
        if "agreed_rent" in body:
            tenancy.agreed_rent = body["agreed_rent"]
        if "security_deposit" in body:
            tenancy.security_deposit = body["security_deposit"]
        if "expected_checkout" in body:
            tenancy.expected_checkout = body["expected_checkout"]
        if "tenancy_notes" in body:
            tenancy.notes = body["tenancy_notes"]
        if "maintenance_fee" in body:
            tenancy.maintenance_fee = body["maintenance_fee"]
        if "lock_in_months" in body:
            tenancy.lock_in_months = body["lock_in_months"]
        if "notice_date" in body:
            val = body["notice_date"]
            tenancy.notice_date = date.fromisoformat(val) if val else None
        if "expected_checkout" in body:
            val = body["expected_checkout"]
            tenancy.expected_checkout = date.fromisoformat(val) if val else None
        if "checkin_date" in body:
            val = body["checkin_date"]
            tenancy.checkin_date = date.fromisoformat(val) if val else None

        # Room reassignment
        if "room_number" in body:
            new_rn = str(body["room_number"]).strip()
            if new_rn and new_rn != room.room_number:
                new_room_row = await session.execute(
                    select(Room).where(
                        func.lower(Room.room_number) == func.lower(new_rn),
                        Room.active == True,
                    )
                )
                new_room = new_room_row.scalars().first()
                if new_room is None:
                    raise HTTPException(status_code=404, detail=f"Room {new_rn} not found")
                # Count active occupants in new room, excluding this tenancy
                from src.services.room_occupancy import get_room_occupants
                occ = await get_room_occupants(session, new_room)
                active_in_new = occ.total_occupied
                # Check if tenant is already in that room (shouldn't count as extra)
                if new_room.id != tenancy.room_id and active_in_new >= (new_room.max_occupancy or 1):
                    raise HTTPException(
                        status_code=409,
                        detail=f"Room {new_rn} is full ({active_in_new}/{new_room.max_occupancy} beds)",
                    )
                tenancy.room_id = new_room.id
                _from_room = room.room_number
                room = new_room
                # Sync sharing_type to match new room's type
                try:
                    tenancy.sharing_type = SharingType(new_room.room_type.value)
                except (ValueError, AttributeError):
                    pass

                session.add(AuditLog(
                    changed_by=user.user_id or "pwa",
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="room_id",
                    old_value=_from_room,
                    new_value=new_rn,
                    room_number=new_rn,
                    source="pwa",
                    note=f"Room change: {_from_room} → {new_rn}",
                    org_id=tenancy.org_id,
                ))

                # Update current month RS — honour prorate_this_month choice if sent
                import calendar as _cal
                from src.services.rent_schedule import first_month_rent_due as _fmrd
                from decimal import Decimal as _D
                _today = date.today()
                _period = _today.replace(day=1)
                _rs = await session.scalar(
                    select(RentSchedule).where(
                        RentSchedule.tenancy_id == tenancy_id,
                        RentSchedule.period_month == _period,
                    )
                )
                if _rs:
                    _prorate_flag = body.get("prorate_this_month", None)
                    if _prorate_flag is False:
                        # Staff chose "full month"
                        _rs.rent_due = _D(str(int(float(tenancy.agreed_rent or 0))))
                    else:
                        # prorate_flag is True or absent (legacy: always prorate on room change)
                        _checkin = tenancy.checkin_date
                        _is_first = _checkin and _checkin.replace(day=1) == _period
                        if _is_first:
                            _rs.rent_due = _fmrd(tenancy, _period)
                        else:
                            _dim = _cal.monthrange(_today.year, _today.month)[1]
                            _remaining = _dim - _today.day + 1
                            _prorated = int(float(tenancy.agreed_rent or 0) * _remaining / _dim)
                            _rs.rent_due = _D(str(_prorated))

        # Rent-only RS update: when prorate_this_month is explicitly set and no room change
        if body.get("prorate_this_month") is not None and "agreed_rent" in body and "room_number" not in body:
            import calendar as _cal
            from decimal import Decimal as _D
            _today = date.today()
            _period = _today.replace(day=1)
            _new_rent = float(body["agreed_rent"])
            if body["prorate_this_month"]:
                _dim = _cal.monthrange(_today.year, _today.month)[1]
                _remaining = _dim - _today.day + 1
                _rs_amount = _D(str(int(_new_rent * _remaining / _dim)))
            else:
                _rs_amount = _D(str(int(_new_rent)))
            _rs = await session.scalar(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == tenancy_id,
                    RentSchedule.period_month == _period,
                )
            )
            if _rs:
                _rs.rent_due = _rs_amount
                session.add(_rs)
            else:
                session.add(RentSchedule(
                    tenancy_id=tenancy_id,
                    period_month=_period,
                    rent_due=_rs_amount,
                    org_id=tenancy.org_id,
                ))

        room_number = room.room_number
        session.add(tenancy)
        session.add(tenant)
        await session.commit()
        await session.refresh(tenancy)
        await session.refresh(tenant)

    today = date.today()
    from src.integrations.gsheets import (
        trigger_monthly_sheet_sync, trigger_daywise_sheet_sync, record_notice,
        sync_tenants_tab_field, sync_tenants_tab_notes,
    )
    import asyncio

    is_daily = tenancy.stay_type.value == "daily"

    if "notice_date" in body and not is_daily:
        notice_val = body["notice_date"] or ""
        checkout_val = body.get("expected_checkout") or ""
        asyncio.create_task(
            record_notice(room_number, tenant.name, notice_val, checkout_val)
        )

    # Mirror changed fields to TENANTS master tab
    if "agreed_rent" in body:
        asyncio.create_task(sync_tenants_tab_field(
            room_number, tenant.name, "Agreed Rent", str(int(float(body["agreed_rent"]))),
        ))
    if "maintenance_fee" in body:
        asyncio.create_task(sync_tenants_tab_field(
            room_number, tenant.name, "Maintenance", str(int(float(body["maintenance_fee"]))),
        ))
    if "security_deposit" in body:
        asyncio.create_task(sync_tenants_tab_field(
            room_number, tenant.name, "Deposit", str(int(float(body["security_deposit"]))),
        ))
    if "tenancy_notes" in body:
        asyncio.create_task(sync_tenants_tab_notes(
            room_number, tenant.name, body.get("tenancy_notes") or "",
        ))

    if is_daily:
        trigger_daywise_sheet_sync()
    else:
        trigger_monthly_sheet_sync(today.month, today.year)

    return {
        "tenancy_id": tenancy.id,
        "tenant_id": tenant.id,
        "name": tenant.name,
        "phone": tenant.phone,
        "email": tenant.email,
        "agreed_rent": float(tenancy.agreed_rent) if tenancy.agreed_rent is not None else 0.0,
        "security_deposit": float(tenancy.security_deposit) if tenancy.security_deposit is not None else 0.0,
        "expected_checkout": tenancy.expected_checkout.isoformat() if tenancy.expected_checkout else None,
        "notes": tenancy.notes,
    }


@router.patch("/tenants/{tenancy_id}/adjustment")
async def patch_adjustment(
    tenancy_id: int,
    body: dict,
    user: AppUser = Depends(get_current_user),
):
    """Set adjustment + note on the current month's RentSchedule.

    Positive amount = surcharge (dues go up).
    Negative amount = waive/concession (dues go down).
    Pass amount=0 to clear a prior adjustment.
    """
    amount = body.get("amount")
    note = (body.get("note") or "").strip()
    if amount is None:
        raise HTTPException(status_code=422, detail="amount is required")
    if not note:
        raise HTTPException(status_code=422, detail="note (reason) is required")

    from decimal import Decimal
    adj = Decimal(str(float(amount)))

    today = date.today()
    period_month = today.replace(day=1)

    async with get_session() as session:
        row = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(Tenancy.id == tenancy_id)
        )).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenancy not found")
        tenancy, tenant, room = row

        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy_id,
                RentSchedule.period_month == period_month,
            )
        )
        if rs:
            rs.adjustment = adj
            rs.adjustment_note = note
        else:
            session.add(RentSchedule(
                tenancy_id=tenancy_id,
                period_month=period_month,
                rent_due=Decimal(str(float(tenancy.agreed_rent or 0))),
                adjustment=adj,
                adjustment_note=note,
                org_id=tenancy.org_id,
            ))

        session.add(AuditLog(
            changed_by=user.user_id or "pwa",
            entity_type="rent_schedule",
            entity_id=tenancy_id,
            entity_name=tenant.name,
            field="adjustment",
            old_value=str(float(rs.adjustment)) if rs and rs.adjustment else "0",
            new_value=str(float(adj)),
            room_number=room.room_number,
            source="pwa",
            note=note,
            org_id=tenancy.org_id,
        ))
        await session.commit()

    from src.integrations.gsheets import trigger_monthly_sheet_sync, trigger_daywise_sheet_sync
    if tenancy.stay_type.value == "daily":
        trigger_daywise_sheet_sync()
    else:
        trigger_monthly_sheet_sync(today.month, today.year)

    rent_due = float(tenancy.agreed_rent or 0)
    effective_due = rent_due + float(adj)
    return {
        "tenancy_id": tenancy_id,
        "period_month": period_month.strftime("%Y-%m"),
        "adjustment": float(adj),
        "adjustment_note": note,
        "effective_due": effective_due,
    }


class TransferRoomBody(BaseModel):
    to_room_number: str
    new_rent: float | None = None
    extra_deposit: float = 0.0


@router.post("/tenants/{tenancy_id}/transfer-room")
async def transfer_room(
    tenancy_id: int,
    body: TransferRoomBody,
    user: AppUser = Depends(get_current_user),
):
    """Execute room transfer — called after PWA user confirms the 4-step panel."""
    async with get_session() as session:
        result = await execute_room_transfer(
            tenancy_id=tenancy_id,
            to_room_number=body.to_room_number,
            new_rent=body.new_rent,
            extra_deposit=body.extra_deposit,
            changed_by=user.user_id or "pwa",
            source="pwa",
            session=session,
        )
        if result["success"]:
            await session.commit()
    return result


@router.delete("/tenants/{tenancy_id}")
async def delete_tenant(
    tenancy_id: int,
    reason: str = Query(default=""),
    force: bool = Query(default=False),
    user: AppUser = Depends(get_current_user),
):
    """
    Hard-delete a tenancy + tenant.
    Writes an AuditLog entry with the reason before deleting.
    If force=true, voids all payment records first (use for erroneous entries).
    Without force, refuses with 409 if any non-voided payments exist.
    """
    if not reason.strip():
        raise HTTPException(status_code=422, detail="Deletion reason is required.")

    async with get_session() as session:
        row = (await session.execute(
            select(Tenancy, Tenant)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .where(Tenancy.id == tenancy_id)
        )).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenancy not found")
        tenancy, tenant = row

        payments = (await session.execute(
            select(Payment).where(Payment.tenancy_id == tenancy_id, Payment.is_void == False)
        )).scalars().all()

        if payments and not force:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete — {len(payments)} payment record(s) exist. Use force delete to void them first.",
            )

        # Write audit trail before deleting so there's a permanent record
        session.add(AuditLog(
            changed_by=user.user_id or "pwa",
            entity_type="tenancy",
            entity_id=tenancy_id,
            entity_name=tenant.name,
            field="deleted",
            old_value=tenancy.room_id and str(tenancy.room_id),
            new_value=None,
            room_number=None,
            source="pwa",
            note=f"Tenant deleted — {reason.strip()}" + (f" (voided {len(payments)} payment(s))" if payments else ""),
            org_id=tenancy.org_id,
        ))
        await session.flush()  # write audit log before cascade delete

        # Bypass frozen-month trigger for this transaction (erroneous-entry cleanup)
        await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        # Use raw SQL to delete child records. The ORM relationship on Tenancy
        # (no passive_deletes) would issue UPDATE SET tenancy_id=NULL before the
        # parent delete — but tenancy_id is NOT NULL on all these tables → 500.
        # Raw SQL bypasses ORM cascade entirely.
        for tbl in [
            "checkout_sessions",   # must come before checkout_records (no FK dep)
            "checkout_records",
            "rent_revisions",
            "rent_schedule",
            "payments",
            "refunds",
            "vacations",
            "complaints",
        ]:
            await session.execute(
                text(f"DELETE FROM {tbl} WHERE tenancy_id = :tid"),
                {"tid": tenancy_id},
            )
        # Nullable FK tables: just NULL them out
        # NOTE: "agreements" excluded — table does not exist in schema
        for tbl in ["reminders", "onboarding_sessions", "documents"]:
            await session.execute(
                text(f"UPDATE {tbl} SET tenancy_id = NULL WHERE tenancy_id = :tid"),
                {"tid": tenancy_id},
            )

        # Check before deleting tenancy (avoid FK issue from expunged ORM object)
        other = await session.scalar(
            select(func.count()).select_from(Tenancy)
            .where(Tenancy.tenant_id == tenant.id, Tenancy.id != tenancy_id)
        )

        # Expunge ORM objects so raw SQL delete doesn't conflict with identity map
        session.expunge(tenancy)
        for p in payments:
            try:
                session.expunge(p)
            except Exception:
                pass

        await session.execute(text("DELETE FROM tenancies WHERE id = :id"), {"id": tenancy_id})
        if not other:
            await session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant.id})

        await session.commit()

    return {"deleted": True, "tenancy_id": tenancy_id}


@router.post("/tenancies/{tenancy_id}/cancel-no-show")
async def cancel_no_show(tenancy_id: int, user: AppUser = Depends(get_current_user)):
    """Cancel a no-show booking — set status to cancelled, checkout_date to today."""
    today = date.today()
    async with get_session() as session:
        row = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.id == tenancy_id)
        )).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenancy not found")
        tenancy, tenant, room = row
        if tenancy.status != TenancyStatus.no_show:
            raise HTTPException(status_code=400, detail=f"Tenancy status is '{tenancy.status.value}', expected 'no_show'")

        await session.execute(
            text("UPDATE tenancies SET status='cancelled', checkout_date=:today WHERE id=:id"),
            {"today": today, "id": tenancy_id},
        )

        audit = AuditLog(
            changed_by=user.phone or user.user_id,
            entity_type="tenancy",
            entity_id=tenancy_id,
            entity_name=tenant.name if tenant else str(tenancy_id),
            field="status",
            old_value="no_show",
            new_value="cancelled",
            room_number=room.room_number if room else None,
            source="dashboard",
            note="Booking cancelled: tenant did not check in (no-show)",
        )
        session.add(audit)
        await session.commit()

    return {"ok": True, "tenancy_id": tenancy_id, "name": tenant.name if tenant else ""}
