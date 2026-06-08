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
                    # deposit payments only (not booking — booking is tracked via
                    # tenancy.booking_amount and would double-deduct against RS.rent_due)
                    and_(
                        Payment.for_type == PaymentFor.deposit,
                        Payment.period_month == None,
                        Payment.payment_date >= period,
                        Payment.payment_date < period_end,
                    ),
                ),
            )
            .group_by(Payment.tenancy_id)
            .subquery()
        )
        # Day-stay payments have no period_month — sum all non-voided payments per tenancy
        all_paid_subq = (
            select(Payment.tenancy_id, func.sum(Payment.amount).label("all_paid"))
            .where(Payment.is_void == False)
            .group_by(Payment.tenancy_id)
            .subquery()
        )
        rows = (await session.execute(
            select(Tenancy, Tenant, Room, Property,
                   RentSchedule.rent_due, RentSchedule.adjustment,
                   func.coalesce(paid_subq.c.paid, 0).label("paid"),
                   func.coalesce(all_paid_subq.c.all_paid, 0).label("all_paid"))
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .join(Property, Room.property_id == Property.id)
            .outerjoin(RentSchedule, and_(
                RentSchedule.tenancy_id == Tenancy.id,
                RentSchedule.period_month == period,
            ))
            .outerjoin(paid_subq, paid_subq.c.tenancy_id == Tenancy.id)
            .outerjoin(all_paid_subq, all_paid_subq.c.tenancy_id == Tenancy.id)
            .where(Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
            .order_by(Room.room_number)
        )).all()

    result = []
    for tenancy, tenant, room, prop, rent_due, adjustment, paid, all_paid in rows:
        if tenancy.stay_type and tenancy.stay_type.value == "daily":
            _nights = (tenancy.checkout_date - tenancy.checkin_date).days if tenancy.checkin_date and tenancy.checkout_date else 0
            _owed = _nights * float(tenancy.agreed_rent or 0)
            _total_paid = float(all_paid) + float(tenancy.booking_amount or 0)
            dues = max(0.0, _owed - _total_paid)
        else:
            rd = float(rent_due or tenancy.agreed_rent or 0)
            adj = float(adjustment or 0)
            not_yet_checked_in = tenancy.checkin_date and tenancy.checkin_date > today
            dues = 0 if not_yet_checked_in else max(rd + adj - float(paid), 0.0)
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
    active_only: bool = Query(default=True),
    user: AppUser = Depends(get_current_user),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")

    term = q.strip().lower()
    if term.isdigit() and len(term) <= 5:
        # Short numeric → room number substring (e.g. "111" finds room 111)
        match_clause = func.lower(Room.room_number).contains(term)
    else:
        # Name, room substring, or phone
        match_clause = or_(
            func.lower(Tenant.name).contains(term),
            func.lower(Room.room_number).contains(term),
            func.lower(Tenant.phone).contains(term),
        )

    statuses = (
        [TenancyStatus.active, TenancyStatus.no_show]
        if active_only
        else [TenancyStatus.active, TenancyStatus.no_show, TenancyStatus.exited]
        # cancelled excluded everywhere — cancelled = erroneous booking, nothing useful to show
    )

    async with get_session() as session:
        stmt = (
            select(Tenancy, Tenant, Room, Property)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .join(Property, Room.property_id == Property.id)
            .where(
                Tenancy.status.in_(statuses),
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


@router.get("/tenants/{tenancy_id}/previous-stays")
async def get_previous_stays(
    tenancy_id: int,
    user: AppUser = Depends(get_current_user),
):
    """Return past (exited/cancelled) tenancies for the same tenant — for the edit page history panel."""
    async with get_session() as session:
        tenancy = await session.get(Tenancy, tenancy_id)
        if not tenancy:
            raise HTTPException(status_code=404, detail="Tenancy not found")
        rows = (await session.execute(
            select(Tenancy, Room, Property)
            .join(Room, Tenancy.room_id == Room.id)
            .join(Property, Room.property_id == Property.id)
            .where(
                Tenancy.tenant_id == tenancy.tenant_id,
                Tenancy.id != tenancy_id,
                Tenancy.status.in_([TenancyStatus.exited, TenancyStatus.cancelled]),
                Room.room_number != "000",
            )
            .order_by(Tenancy.checkin_date.desc())
            .limit(5)
        )).all()
    return [
        {
            "tenancy_id": t.id,
            "room_number": r.room_number,
            "building_code": _building_code(p.name),
            "checkin_date": t.checkin_date.isoformat() if t.checkin_date else None,
            "checkout_date": (t.checkout_date or t.expected_checkout).isoformat() if (t.checkout_date or t.expected_checkout) else None,
            "agreed_rent": float(t.agreed_rent or 0),
            "stay_type": t.stay_type.value if t.stay_type else "monthly",
            "notes": t.notes or "",
            "status": t.status.value,
        }
        for t, r, p in rows
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

    # Day-wise stays: dues = booked_nights × daily_rate − total_paid
    if tenancy.stay_type.value == "daily":
        async with get_session() as session:
            total_paid_result = await session.scalar(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.tenancy_id == tenancy_id,
                    Payment.is_void == False,
                )
            )
            last_payment = await session.scalar(
                select(Payment)
                .where(Payment.tenancy_id == tenancy_id, Payment.is_void == False)
                .order_by(Payment.payment_date.desc(), Payment.id.desc())
                .limit(1)
            )
        daily_rate = float(tenancy.agreed_rent or 0)
        checkin = tenancy.checkin_date
        checkout = tenancy.checkout_date  # booked end date, updated on extension
        total_nights = (checkout - checkin).days if checkin and checkout else 0
        total_owed = total_nights * daily_rate
        # booking_amount is advance paid at booking time — not a Payment record, must add separately
        booking_amount = float(tenancy.booking_amount or 0)
        total_paid_f = float(total_paid_result or 0) + booking_amount
        dues = max(0.0, total_owed - total_paid_f)
        credit = max(0.0, total_paid_f - total_owed)
        return {
            "tenancy_id": tenancy.id,
            "tenant_id": tenant.id,
            "name": tenant.name,
            "phone": tenant.phone,
            "email": tenant.email or "",
            "room_number": room.room_number,
            "building_code": _building_code(prop.name),
            "rent": daily_rate,
            "rent_due": total_owed,
            "adjustment": 0.0,
            "adjustment_note": None,
            "booking_amount": float(tenancy.booking_amount) if tenancy.booking_amount else 0.0,
            "dues": dues,
            "credit": credit,
            "deposit_due": 0.0,
            "deposit_paid": 0.0,
            "checkin_date": tenancy.checkin_date.isoformat() if tenancy.checkin_date else None,
            "security_deposit": 0.0,
            "maintenance_fee": 0.0,
            "lock_in_months": 0,
            "notes": tenancy.notes or "",
            "last_payment_date": last_payment.payment_date.isoformat() if last_payment else None,
            "last_payment_amount": float(last_payment.amount) if last_payment else None,
            "period_month": date.today().strftime("%Y-%m"),
            "notice_date": None,
            "expected_checkout": tenancy.checkout_date.isoformat() if tenancy.checkout_date else None,
            "stay_type": tenancy.stay_type.value,
            "sharing_type": tenancy.sharing_type.value if tenancy.sharing_type else None,
        }

    # Current period: first day of current month
    today = date.today()
    period_month = date(today.year, today.month, 1)

    next_m = today.month % 12 + 1
    next_y = today.year + (1 if today.month == 12 else 0)
    period_end = date(next_y, next_m, 1)

    async with get_session() as session:
        # Rent-only payments this period (never bundle deposit here — tracked separately).
        rent_only_paid_result = await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
                Payment.period_month == period_month,
            )
        )
        # All deposit payments ever (for deposit_due calculation)
        deposit_paid_result = await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.deposit,
            )
        )
        # Advance/booking payments recorded via payment form
        booking_paid_result = await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.booking,
            )
        )
        # RentSchedule for this period
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy_id,
                RentSchedule.period_month == period_month,
            )
        )
        last_payment = await session.scalar(
            select(Payment)
            .where(Payment.tenancy_id == tenancy_id, Payment.is_void == False)
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
            .limit(1)
        )

    rent = float(tenancy.agreed_rent) if tenancy.agreed_rent is not None else 0.0
    rent_only_paid = float(rent_only_paid_result) if rent_only_paid_result is not None else 0.0
    deposit_agreed = float(tenancy.security_deposit) if tenancy.security_deposit else 0.0
    deposit_paid_direct = float(deposit_paid_result) if deposit_paid_result else 0.0
    booking_paid_via_pmts = float(booking_paid_result) if booking_paid_result else 0.0
    # Use payment records if they exist; fall back to tenancy.booking_amount for
    # Excel-imported tenants who have no corresponding Payment record.
    booking_amount = booking_paid_via_pmts if booking_paid_via_pmts > 0 else (float(tenancy.booking_amount) if tenancy.booking_amount else 0.0)

    rent_due   = float(rs.rent_due)   if rs else rent
    adjustment = float(rs.adjustment) if rs and rs.adjustment else 0.0
    not_yet_checked_in = tenancy.checkin_date and tenancy.checkin_date > today

    # First-month detection: RS.rent_due bundles prorated+deposit, so we split them
    # back out for display so rent and deposit show correctly when paid separately.
    checkin = tenancy.checkin_date
    is_check_in_month = checkin and checkin.replace(day=1) == period_month

    if is_check_in_month and not not_yet_checked_in:
        from src.services.rent_schedule import prorated_first_month_rent
        prorated = float(prorated_first_month_rent(tenancy.agreed_rent, checkin))
        effective_prorated = max(0.0, prorated + adjustment)  # apply waiver/adjustment
        # Any rent overpay beyond effective prorated carries over to deposit
        rent_overflow = max(0.0, rent_only_paid - effective_prorated)
        effective_deposit_paid = deposit_paid_direct + rent_overflow
        dues = max(0.0, effective_prorated - rent_only_paid)
        deposit_due = max(0.0, deposit_agreed - effective_deposit_paid - booking_amount)
        credit = max(0.0, rent_only_paid - effective_prorated) if rent_only_paid > effective_prorated and deposit_agreed == 0 else 0.0
    else:
        # Normal month: RS is the source of truth for rent; deposit tracked separately
        effective_due = rent_due + adjustment
        dues = 0.0 if not_yet_checked_in else max(effective_due - rent_only_paid, 0.0)
        credit = 0.0 if not_yet_checked_in else max(rent_only_paid - effective_due, 0.0)
        deposit_due = 0.0 if not_yet_checked_in else max(0.0, deposit_agreed - deposit_paid_direct - booking_amount)

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
        "deposit_due": deposit_due,
        "deposit_paid": deposit_paid_direct,
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
        "sharing_type": tenancy.sharing_type.value if tenancy.sharing_type else None,
    }


@router.patch("/tenants/{tenancy_id}")
async def update_tenant(
    tenancy_id: int,
    body: dict,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="Only admin and staff can edit tenants")

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
                    changed_by=user.actor,
                    reason=body.get("rent_change_reason", ""),
                    org_id=tenancy.org_id,
                )
                session.add(revision)

        # Tenant fields — log changes for audit trail
        if "name" in body:
            old_name = tenant.name
            tenant.name = body["name"]
            if old_name != body["name"]:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenant",
                    entity_id=tenant.id,
                    entity_name=tenant.name,
                    field="name",
                    old_value=old_name,
                    new_value=body["name"],
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "phone" in body:
            from src.services.room_occupancy import canonical_phone as _canon_phone, _normalize_phone as _norm_phone
            from sqlalchemy import func as _func
            old_phone = tenant.phone
            new_phone = _canon_phone(body["phone"]) if body["phone"] else body["phone"]
            last10 = _norm_phone(new_phone or "")
            if new_phone and last10 and last10 != _norm_phone(tenant.phone or ""):
                # Normalize both sides via RIGHT(digits, 10) so +91XXXXXXXXXX == XXXXXXXXXX
                conflict = await session.scalar(
                    select(Tenant.id).where(
                        Tenant.id != tenant.id,
                        _func.right(_func.regexp_replace(Tenant.phone, r"\D", "", "g"), 10) == last10,
                    )
                )
                if conflict:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Phone {new_phone} is already registered to another tenant.",
                    )
            tenant.phone = new_phone
            if old_phone != new_phone:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenant",
                    entity_id=tenant.id,
                    entity_name=tenant.name,
                    field="phone",
                    old_value=old_phone,
                    new_value=new_phone,
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "email" in body:
            old_email = tenant.email
            tenant.email = body["email"]
            if old_email != body["email"]:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenant",
                    entity_id=tenant.id,
                    entity_name=tenant.name,
                    field="email",
                    old_value=old_email,
                    new_value=body["email"],
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "tenant_notes" in body:
            old_notes = tenant.notes
            tenant.notes = body["tenant_notes"]
            if old_notes != body["tenant_notes"]:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenant",
                    entity_id=tenant.id,
                    entity_name=tenant.name,
                    field="tenant_notes",
                    old_value=old_notes,
                    new_value=body["tenant_notes"],
                    source="pwa",
                    org_id=tenancy.org_id,
                ))

        # Tenancy fields — log changes for audit trail
        if "agreed_rent" in body:
            # RentRevision already logged above; also add AuditLog for the field change itself
            old_rent = float(tenancy.agreed_rent) if tenancy.agreed_rent is not None else 0.0
            tenancy.agreed_rent = body["agreed_rent"]
            if old_rent != float(body["agreed_rent"]):
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="agreed_rent",
                    old_value=str(old_rent),
                    new_value=str(body["agreed_rent"]),
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "security_deposit" in body:
            old_deposit = float(tenancy.security_deposit) if tenancy.security_deposit is not None else 0.0
            tenancy.security_deposit = body["security_deposit"]
            if old_deposit != float(body["security_deposit"]):
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="security_deposit",
                    old_value=str(old_deposit),
                    new_value=str(body["security_deposit"]),
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "tenancy_notes" in body:
            old_notes = tenancy.notes
            tenancy.notes = body["tenancy_notes"]
            if old_notes != body["tenancy_notes"]:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="tenancy_notes",
                    old_value=old_notes,
                    new_value=body["tenancy_notes"],
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "maintenance_fee" in body:
            old_fee = float(tenancy.maintenance_fee) if tenancy.maintenance_fee is not None else 0.0
            tenancy.maintenance_fee = body["maintenance_fee"]
            if old_fee != float(body["maintenance_fee"]):
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="maintenance_fee",
                    old_value=str(old_fee),
                    new_value=str(body["maintenance_fee"]),
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "lock_in_months" in body:
            old_lock = tenancy.lock_in_months
            tenancy.lock_in_months = body["lock_in_months"]
            if old_lock != body["lock_in_months"]:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="lock_in_months",
                    old_value=str(old_lock),
                    new_value=str(body["lock_in_months"]),
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "notice_date" in body:
            old_notice = tenancy.notice_date.isoformat() if tenancy.notice_date else None
            val = body["notice_date"]
            tenancy.notice_date = date.fromisoformat(val) if val else None
            # Log notice date change
            new_notice = tenancy.notice_date.isoformat() if tenancy.notice_date else None
            if old_notice != new_notice:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="notice_date",
                    old_value=old_notice,
                    new_value=new_notice,
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
            # Clearing notice also clears the planned exit date — they're one action
            if not val:
                tenancy.expected_checkout = None
        if "expected_checkout" in body:
            old_checkout = tenancy.expected_checkout.isoformat() if tenancy.expected_checkout else None
            val = body["expected_checkout"]
            new_date = date.fromisoformat(val) if val else None
            if tenancy.stay_type.value == "daily":
                # Day-stays: extend the booked end date (checkout_date drives dues + extra-nights calc)
                tenancy.checkout_date = new_date
            else:
                tenancy.expected_checkout = new_date
            # Log expected_checkout change
            new_checkout = tenancy.expected_checkout.isoformat() if tenancy.expected_checkout else None
            if old_checkout != new_checkout:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="expected_checkout",
                    old_value=old_checkout,
                    new_value=new_checkout,
                    source="pwa",
                    org_id=tenancy.org_id,
                ))
        if "checkin_date" in body:
            old_checkin = tenancy.checkin_date.isoformat() if tenancy.checkin_date else None
            val = body["checkin_date"]
            tenancy.checkin_date = date.fromisoformat(val) if val else None
            # Log checkin_date change
            new_checkin = tenancy.checkin_date.isoformat() if tenancy.checkin_date else None
            if old_checkin != new_checkin:
                session.add(AuditLog(
                    changed_by=user.actor,
                    entity_type="tenancy",
                    entity_id=tenancy_id,
                    entity_name=tenant.name,
                    field="checkin_date",
                    old_value=old_checkin,
                    new_value=new_checkin,
                    source="pwa",
                    org_id=tenancy.org_id,
                ))

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
                    changed_by=user.actor,
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
                from src.services.rent_schedule import first_month_rent_due
                _checkin = tenancy.checkin_date
                _is_checkin_month = _checkin and _checkin.replace(day=1) == _period
                session.add(RentSchedule(
                    tenancy_id=tenancy_id,
                    period_month=_period,
                    rent_due=first_month_rent_due(tenancy, _period) if _is_checkin_month else _rs_amount,
                    org_id=tenancy.org_id,
                ))

        # Recalc first-month RS when security_deposit or checkin_date changes
        # (agreed_rent changes are handled above via prorate_this_month logic)
        if "security_deposit" in body or "checkin_date" in body:
            from src.services.rent_schedule import recalc_checkin_month_rs
            await recalc_checkin_month_rs(session, tenancy)

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
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="Only admin and staff can adjust rent")

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
            changed_by=user.actor,
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
            changed_by=user.actor,
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

        rs_count = await session.scalar(
            select(func.count()).select_from(RentSchedule).where(RentSchedule.tenancy_id == tenancy_id)
        )

        # Write audit trail before deleting so there's a permanent record
        note_parts = [f"Tenant deleted — {reason.strip()}"]
        if payments:
            note_parts.append(f"voided {len(payments)} payment(s)")
        if rs_count:
            note_parts.append(f"deleted {rs_count} RS row(s)")
        session.add(AuditLog(
            changed_by=user.actor,
            entity_type="tenancy",
            entity_id=tenancy_id,
            entity_name=tenant.name,
            field="deleted",
            old_value=tenancy.room_id and str(tenancy.room_id),
            new_value=None,
            room_number=None,
            source="pwa",
            note="; ".join(note_parts),
            org_id=tenancy.org_id,
        ))
        await session.flush()  # write audit log before cascade delete

        # Bypass frozen-month trigger for this transaction (erroneous-entry cleanup)
        await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        # Use raw SQL to delete child records. The ORM relationship on Tenancy
        # (no passive_deletes) would issue UPDATE SET tenancy_id=NULL before the
        # parent delete — but tenancy_id is NOT NULL on all these tables → 500.
        # Raw SQL bypasses ORM cascade entirely.
        # Null out payment_id in upi_collection_entries BEFORE deleting payments
        await session.execute(
            text("UPDATE upi_collection_entries SET payment_id = NULL WHERE tenancy_id = :tid"),
            {"tid": tenancy_id},
        )
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
        for tbl in ["reminders", "onboarding_sessions", "documents", "upi_collection_entries"]:
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
            # Null out tenant_id FKs in documents and onboarding_sessions before deleting tenant
            for tbl in ["documents", "onboarding_sessions"]:
                await session.execute(
                    text(f"UPDATE {tbl} SET tenant_id = NULL WHERE tenant_id = :tid"),
                    {"tid": tenant.id},
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant.id})

        await session.commit()

    return {"deleted": True, "tenancy_id": tenancy_id}


@router.post("/tenancies/{tenancy_id}/cancel-no-show")
async def cancel_no_show(tenancy_id: int, user: AppUser = Depends(get_current_user)):
    """Cancel a no-show booking — set status to cancelled, void RS rows, sync onboarding session."""
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="Only admin and staff can cancel bookings")

    from src.database.models import OnboardingSession, RentSchedule, RentStatus
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

        # Void all pending RS rows — cancelled tenancy has no rent obligation
        rs_rows = (await session.execute(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy_id,
                RentSchedule.status == RentStatus.pending,
            )
        )).scalars().all()
        for rs in rs_rows:
            rs.status = RentStatus.na

        await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
        await session.execute(
            text("UPDATE tenancies SET status='cancelled', checkout_date=:today WHERE id=:id"),
            {"today": today, "id": tenancy_id},
        )

        # Sync linked onboarding session so Bookings page reflects the cancellation
        await session.execute(
            text("UPDATE onboarding_sessions SET status='cancelled' WHERE tenancy_id=:tid AND status='approved'"),
            {"tid": tenancy_id},
        )

        rs_note = f"; voided {len(rs_rows)} RS row(s)" if rs_rows else ""
        audit = AuditLog(
            changed_by=user.actor,
            entity_type="tenancy",
            entity_id=tenancy_id,
            entity_name=tenant.name if tenant else str(tenancy_id),
            field="status",
            old_value="no_show",
            new_value="cancelled",
            room_number=room.room_number if room else None,
            source="dashboard",
            note=f"Booking cancelled: tenant did not check in (no-show){rs_note}",
        )
        session.add(audit)
        await session.commit()

    return {"ok": True, "tenancy_id": tenancy_id, "name": tenant.name if tenant else ""}
