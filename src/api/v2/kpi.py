"""GET /api/v2/app/reporting/kpi and GET /api/v2/app/activity/recent."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, literal_column, select, desc, or_, and_

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    OnboardingSession,
    Payment, PaymentFor,
    Property,
    RentSchedule,
    Room, Tenancy, TenancyStatus, StayType,
    Tenant,
)
from src.schemas.kpi import ActivityItem, ActivityResponse, KpiResponse
from src.services.rent_schedule import prorated_first_month_rent
from src.services.reporting import deposits_breakdown

router = APIRouter(prefix="/reporting")
activity_router = APIRouter(prefix="/activity")


@router.get("/kpi", response_model=KpiResponse)
async def get_kpi(user: AppUser = Depends(get_current_user)):
    today = date.today()
    async with get_session() as session:
        # Total revenue beds (exclude UNASSIGNED placeholder room)
        total_beds = int(
            await session.scalar(
                select(func.coalesce(func.sum(Room.max_occupancy), 0))
                .where(Room.is_staff_room == False, Room.room_number != "000")
            ) or 0
        )

        # Occupied beds — per-room sum capped at max_occupancy so overcrowded
        # rooms don't pull vacant_beds below the true available count.
        per_room_occ = (
            select(
                func.least(
                    func.sum(
                        case(
                            (Tenancy.sharing_type == "premium", Room.max_occupancy),
                            else_=literal_column("1"),
                        )
                    ),
                    Room.max_occupancy,
                ).label("capped_occ")
            )
            .select_from(Tenancy)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.status == TenancyStatus.active,
            )
            .group_by(Room.id, Room.max_occupancy)
            .subquery()
        )
        occupied_raw = await session.scalar(
            select(func.coalesce(func.sum(per_room_occ.c.capped_occ), 0))
        )
        occupied_beds = int(occupied_raw or 0)

        # No-shows whose checkin_date <= today are holding a bed (same as Sheet logic).
        # Future no-shows (checkin_date > today) do NOT occupy a bed tonight.
        noshow_beds = int(
            await session.scalar(
                select(func.coalesce(func.sum(
                    case(
                        (Tenancy.sharing_type == "premium", Room.max_occupancy),
                        else_=literal_column("1"),
                    )
                ), 0))
                .select_from(Tenancy)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.no_show,
                    Tenancy.checkin_date <= today,
                )
            ) or 0
        )
        occupied_beds += noshow_beds
        vacant_beds = max(total_beds - occupied_beds, 0)
        occ_pct = round(occupied_beds / total_beds * 100, 1) if total_beds > 0 else 0.0

        # Active tenants (people, not beds)
        active_tenants = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.active,
                )
            ) or 0
        )

        # No-show tenants (booked but not yet checked in)
        no_show_count = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.no_show,
                )
            ) or 0
        )

        # Pre-booked: pending_tenant (link sent) + pending_review (form filled, awaiting approval)
        # + no_show tenants in room 000 (pre-booked via old bot flow)
        # Count only valid replacements: pending_review in rooms with leaving tenants
        prebooked_form = (
            await session.scalar(
                select(func.count(OnboardingSession.id))
                .join(Room, Room.id == OnboardingSession.room_id)
                .where(
                    OnboardingSession.status == "pending_review",
                    OnboardingSession.room_id.isnot(None),
                    # Room has a leaving tenant (notice or expected checkout)
                    or_(
                        exists(
                            select(1).from_(Tenancy)
                            .where(
                                Tenancy.room_id == Room.id,
                                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.exited]),
                                or_(
                                    Tenancy.notice_date != None,
                                    Tenancy.expected_checkout.between(date.today() - timedelta(days=30), date.today() + timedelta(days=60))
                                )
                            )
                        ),
                        exists(
                            select(1).from_(Tenancy)
                            .where(
                                Tenancy.room_id == Room.id,
                                Tenancy.status == TenancyStatus.active,
                                Tenancy.stay_type == StayType.daily,
                                Tenancy.checkout_date >= date.today(),
                                Tenancy.checkout_date <= date.today() + timedelta(days=30)
                            )
                        )
                    )
                )
            ) or 0
        )
        prebooked_room000 = (
            await session.scalar(
                select(func.count(Tenancy.id))
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.room_number == "000",
                    Tenancy.status == TenancyStatus.no_show,
                )
            ) or 0
        )
        prebooked_count = prebooked_form + prebooked_room000

        # Monthly tenants with formal notice + day-stay checking out within 30 days
        _monthly_notices = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.stay_type == StayType.monthly,
                    or_(Tenancy.notice_date != None, Tenancy.expected_checkout.between(date.today() - timedelta(days=30), date.today() + timedelta(days=60))),
                )
            ) or 0
        )
        _daily_leaving = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.stay_type == StayType.daily,
                    Tenancy.checkout_date.isnot(None),
                    Tenancy.checkout_date >= today,
                    Tenancy.checkout_date <= today + timedelta(days=30),
                )
            ) or 0
        )
        notices_count = _monthly_notices + _daily_leaving

        # Check-ins today — no_show Tenancy OR pending OnboardingSession not already
        # linked to a no_show Tenancy (handles orphaned/cancelled tenancy edge cases).
        _no_show_today_ids = select(Tenancy.id).where(
            Tenancy.checkin_date == today,
            Tenancy.status == TenancyStatus.no_show,
        )
        _tenancy_checkins = int(
            await session.scalar(select(func.count()).select_from(_no_show_today_ids.subquery())) or 0
        )
        _session_checkins = int(
            await session.scalar(
                select(func.count(OnboardingSession.id))
                .where(
                    OnboardingSession.checkin_date == today,
                    OnboardingSession.status.in_(["pending_review", "pending_tenant"]),
                    or_(
                        OnboardingSession.tenancy_id == None,
                        OnboardingSession.tenancy_id.notin_(_no_show_today_ids),
                    ),
                )
            ) or 0
        )
        checkins_today = _tenancy_checkins + _session_checkins

        # Checkouts today — either already recorded or notice expected_checkout = today
        checkouts_today = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .where(
                    or_(
                        Tenancy.checkout_date == today,
                        and_(
                            Tenancy.expected_checkout == today,
                            Tenancy.status == TenancyStatus.active,
                        ),
                    )
                )
            ) or 0
        )

        # Overdue tenants — same logic as dues panel: rent_dues + deposit_due per tenant
        period = date(today.year, today.month, 1)
        rent_paid_subq = (
            select(Payment.tenancy_id, func.sum(Payment.amount).label("paid"))
            .where(
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
                Payment.period_month == period,
            )
            .group_by(Payment.tenancy_id)
            .subquery()
        )
        deposit_paid_subq = (
            select(Payment.tenancy_id, func.sum(Payment.amount).label("dep_paid"))
            .where(Payment.is_void == False, Payment.for_type == PaymentFor.deposit)
            .group_by(Payment.tenancy_id)
            .subquery()
        )
        eff_due_col = (RentSchedule.rent_due + func.coalesce(RentSchedule.adjustment, 0)).label("effective_due")
        dues_rows = (await session.execute(
            select(
                Tenancy.security_deposit,
                Tenancy.booking_amount,
                Tenancy.checkin_date,
                Tenancy.agreed_rent,
                eff_due_col,
                func.coalesce(rent_paid_subq.c.paid, 0).label("rent_paid"),
                func.coalesce(deposit_paid_subq.c.dep_paid, 0).label("dep_paid"),
            )
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .outerjoin(rent_paid_subq, rent_paid_subq.c.tenancy_id == RentSchedule.tenancy_id)
            .outerjoin(deposit_paid_subq, deposit_paid_subq.c.tenancy_id == Tenancy.id)
            .where(
                RentSchedule.period_month == period,
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
            )
        )).all()
        overdue_tenants = 0
        overdue_amount = 0.0
        for _r in dues_rows:
            _eff = float(_r.effective_due or 0)
            _rent_paid = float(_r.rent_paid or 0)
            _dep_paid = float(_r.dep_paid or 0)
            _booking = float(_r.booking_amount or 0)
            _dep_agreed = float(_r.security_deposit or 0)
            _checkin = _r.checkin_date
            if _checkin and _checkin.replace(day=1) == period:
                _prorated = float(prorated_first_month_rent(float(_r.agreed_rent or 0), _checkin))
                _overflow = max(0.0, _rent_paid - _prorated)
                _rent_dues = max(0.0, _prorated - _rent_paid)
                _dep_due = max(0.0, _dep_agreed - (_dep_paid + _overflow) - _booking)
            else:
                _rent_dues = max(0.0, _eff - _rent_paid)
                _dep_due = max(0.0, _dep_agreed - _dep_paid - _booking)
            _total = _rent_dues + _dep_due
            if _total > 0:
                overdue_tenants += 1
                overdue_amount += _total

        # Day-wise stays: no rent_schedule rows — dues = booked_nights × rate - (payments + advance)
        daily_rows = (await session.execute(
            select(
                Tenancy.agreed_rent,
                Tenancy.checkin_date,
                Tenancy.checkout_date,
                Tenancy.booking_amount,
                func.coalesce(func.sum(Payment.amount), 0).label("total_paid"),
            )
            .outerjoin(Payment, and_(Payment.tenancy_id == Tenancy.id, Payment.is_void == False))
            .where(Tenancy.stay_type == StayType.daily, Tenancy.status == TenancyStatus.active)
            .group_by(Tenancy.id)
        )).all()
        for _dr in daily_rows:
            _rate = float(_dr.agreed_rent or 0)
            _nights = (_dr.checkout_date - _dr.checkin_date).days if _dr.checkin_date and _dr.checkout_date else 0
            _owed = _nights * _rate
            _paid = float(_dr.total_paid or 0) + float(_dr.booking_amount or 0)
            _dues = max(0.0, _owed - _paid)
            if _dues > 0:
                overdue_tenants += 1
                overdue_amount += _dues

    return KpiResponse(
        occupied_beds=occupied_beds,
        total_beds=total_beds,
        vacant_beds=vacant_beds,
        occupancy_pct=occ_pct,
        active_tenants=active_tenants,
        no_show_count=no_show_count,
        prebooked_count=prebooked_count,
        notices_count=notices_count,
        checkins_today=checkins_today,
        checkouts_today=checkouts_today,
        overdue_tenants=overdue_tenants,
        overdue_amount=overdue_amount,
    )


@router.get("/kpi-detail")
async def get_kpi_detail(
    type: str,
    include_staff: bool = False,
    user: AppUser = Depends(get_current_user),
):
    """Return the underlying rows for a KPI tile."""
    today = date.today()
    async with get_session() as session:
        if type == "checkins_today":
            # Part 1: no_show tenancies with today's check-in
            tenancy_rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.checkin_date, Tenancy.agreed_rent, Tenancy.stay_type)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(Tenancy.checkin_date == today, Tenancy.status == TenancyStatus.no_show)
                .order_by(Room.room_number)
            )).all()
            # Part 2: pending OnboardingSessions with today's check-in not already in Part 1
            _no_show_ids = select(Tenancy.id).where(
                Tenancy.checkin_date == today, Tenancy.status == TenancyStatus.no_show
            )
            session_rows = (await session.execute(
                select(
                    OnboardingSession.tenancy_id,
                    OnboardingSession.tenant_data,
                    OnboardingSession.tenant_phone,
                    Room.room_number,
                    OnboardingSession.checkin_date,
                    OnboardingSession.agreed_rent,
                    OnboardingSession.stay_type,
                )
                .join(Room, Room.id == OnboardingSession.room_id)
                .where(
                    OnboardingSession.checkin_date == today,
                    OnboardingSession.status.in_(["pending_review", "pending_tenant"]),
                    or_(
                        OnboardingSession.tenancy_id == None,
                        OnboardingSession.tenancy_id.notin_(_no_show_ids),
                    ),
                )
                .order_by(Room.room_number)
            )).all()

            def _obs_name(r) -> str:
                import json as _json
                if r.tenant_data:
                    try:
                        d = _json.loads(r.tenant_data)
                        return d.get("name") or d.get("full_name") or ""
                    except Exception:
                        pass
                return r.tenant_phone or "Unknown"

            items = [
                {
                    "tenancy_id": r.id, "name": r.name, "room": r.room_number,
                    "detail": f"₹{int(r.agreed_rent or 0):,}/" + ("day" if getattr(r, "stay_type", None) and (r.stay_type.value if hasattr(r.stay_type, "value") else str(r.stay_type)) == "daily" else "mo"),
                    "rent": int(r.agreed_rent or 0),
                    "stay_type": (r.stay_type.value if hasattr(r.stay_type, "value") else str(r.stay_type or "monthly")),
                }
                for r in tenancy_rows
            ] + [
                {
                    "tenancy_id": r.tenancy_id,
                    "name": _obs_name(r) or "Unknown",
                    "room": r.room_number,
                    "detail": f"₹{int(r.agreed_rent or 0):,}/mo · pending",
                    "rent": int(r.agreed_rent or 0),
                    "stay_type": str(r.stay_type or "monthly"),
                    "is_pending_session": True,
                }
                for r in session_rows
            ]
            return {"type": type, "items": items}

        elif type == "checkouts_today":
            rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.checkout_date, Tenancy.expected_checkout, Tenancy.stay_type, Tenancy.status)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    or_(
                        Tenancy.checkout_date == today,
                        and_(
                            Tenancy.expected_checkout == today,
                            Tenancy.status == TenancyStatus.active,
                        ),
                    )
                )
                .order_by(Room.room_number)
            )).all()
            return {"type": type, "items": [
                {
                    "tenancy_id": r.id, "name": r.name, "room": r.room_number,
                    "detail": "Checked out" if (r.status.value if hasattr(r.status, "value") else str(r.status)) == "exited" else "Check-out today",
                    "stay_type": (r.stay_type.value if hasattr(r.stay_type, "value") else str(r.stay_type or "monthly")),
                    "is_checked_out": (r.status.value if hasattr(r.status, "value") else str(r.status)) == "exited",
                }
                for r in rows
            ]}

        elif type == "vacant":
            # Count occupied BEDS per room (premium tenant = max_occupancy beds, else 1)
            # so that premium-occupied rooms don't appear as having free beds.
            occ_subq = (
                select(
                    Tenancy.room_id,
                    func.sum(
                        case(
                            (Tenancy.sharing_type == "premium", Room.max_occupancy),
                            else_=literal_column("1"),
                        )
                    ).label("occ"),
                )
                .join(Room, Room.id == Tenancy.room_id)
                .where(Tenancy.status == TenancyStatus.active)
                .group_by(Tenancy.room_id)
                .subquery()
            )
            room_filter = [Room.room_number != "000"]
            if not include_staff:
                room_filter.append(Room.is_staff_room == False)
            room_rows = (await session.execute(
                select(
                    Room.id,
                    Room.room_number,
                    Room.max_occupancy,
                    Room.is_staff_room,
                    func.coalesce(occ_subq.c.occ, 0).label("occupied_count"),
                )
                .outerjoin(occ_subq, occ_subq.c.room_id == Room.id)
                .where(*room_filter)
                .having(func.coalesce(occ_subq.c.occ, 0) < Room.max_occupancy)
                .group_by(Room.id, Room.room_number, Room.max_occupancy, Room.is_staff_room, occ_subq.c.occ)
                .order_by(Room.room_number)
            )).all()

            # Fetch genders for partially-occupied rooms in one query
            room_ids = [r.id for r in room_rows if r.occupied_count > 0]
            gender_map: dict[int, set] = {}
            if room_ids:
                gender_rows = (await session.execute(
                    select(Tenancy.room_id, Tenant.gender)
                    .join(Tenant, Tenant.id == Tenancy.tenant_id)
                    .where(Tenancy.status == TenancyStatus.active, Tenancy.room_id.in_(room_ids))
                )).all()
                for gr in gender_rows:
                    gender_map.setdefault(gr.room_id, set()).add((gr.gender or "").lower())

            def _room_gender(room_id: int, occupied_count: int) -> str:
                if occupied_count == 0:
                    return "empty"
                genders = gender_map.get(room_id, set())
                genders.discard("")
                if not genders:
                    return "unknown"
                if genders == {"male"}:
                    return "male"
                if genders == {"female"}:
                    return "female"
                return "mixed"

            # Upcoming bookings for these rooms (no-show tenancies + pending onboarding sessions)
            vacant_room_ids = [r.id for r in room_rows]
            upcoming_map: dict[int, date] = {}
            if vacant_room_ids:
                upcoming_rows = (await session.execute(
                    select(Tenancy.room_id, func.min(Tenancy.checkin_date).label("next_checkin"))
                    .where(
                        Tenancy.room_id.in_(vacant_room_ids),
                        Tenancy.status == TenancyStatus.no_show,
                        Tenancy.checkin_date > today,
                    )
                    .group_by(Tenancy.room_id)
                )).all()
                for row in upcoming_rows:
                    upcoming_map[row.room_id] = row.next_checkin

                # Also include pre-bookings (OnboardingSession pending_tenant/pending_review)
                session_rows = (await session.execute(
                    select(OnboardingSession.room_id, func.min(OnboardingSession.checkin_date).label("next_checkin"))
                    .where(
                        OnboardingSession.room_id.in_(vacant_room_ids),
                        OnboardingSession.status.in_(["pending_tenant", "pending_review"]),
                        OnboardingSession.checkin_date > today,
                        or_(
                            OnboardingSession.status == "pending_review",
                            OnboardingSession.expires_at == None,
                            OnboardingSession.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
                        ),
                    )
                    .group_by(OnboardingSession.room_id)
                )).all()
                for row in session_rows:
                    if row.room_id not in upcoming_map or row.next_checkin < upcoming_map[row.room_id]:
                        upcoming_map[row.room_id] = row.next_checkin

            items = []
            for r in room_rows:
                free = r.max_occupancy - r.occupied_count
                gender = _room_gender(r.id, r.occupied_count)
                gender_label = {"male": "Male", "female": "Female", "mixed": "Mixed", "empty": "", "unknown": ""}.get(gender, "")
                detail_parts = [f"{free} bed{'s' if free > 1 else ''} free"]
                if gender_label:
                    detail_parts.append(gender_label)
                upcoming = upcoming_map.get(r.id)
                items.append({
                    "name": f"Room {r.room_number}",
                    "room": r.room_number,
                    "detail": " · ".join(detail_parts),
                    "free_beds": free,
                    "max_occupancy": r.max_occupancy,
                    "gender": gender,
                    "is_staff_room": bool(r.is_staff_room),
                    "upcoming_checkin": upcoming.isoformat() if upcoming else None,
                })
            return {"type": type, "items": items}

        elif type == "occupied":
            rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.agreed_rent, Tenancy.stay_type)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(Room.is_staff_room == False, Room.room_number != "000", Tenancy.status == TenancyStatus.active)
                .order_by(Room.room_number)
            )).all()
            return {"type": type, "items": [
                {"tenancy_id": r.id, "name": r.name, "room": r.room_number,
                 "detail": f"₹{int(r.agreed_rent or 0):,}/" + ("day" if r.stay_type and (r.stay_type.value if hasattr(r.stay_type, "value") else str(r.stay_type)) == "daily" else "mo"),
                 "rent": int(r.agreed_rent or 0), "stay_type": r.stay_type.value if hasattr(r.stay_type, "value") else str(r.stay_type or "monthly")}
                for r in rows
            ]}

        elif type == "dues":
            period = date(today.year, today.month, 1)

            rent_paid_subq = (
                select(Payment.tenancy_id, func.sum(Payment.amount).label("paid"))
                .where(
                    Payment.is_void == False,
                    Payment.for_type == PaymentFor.rent,
                    Payment.period_month == period,
                )
                .group_by(Payment.tenancy_id)
                .subquery()
            )
            deposit_paid_subq = (
                select(Payment.tenancy_id, func.sum(Payment.amount).label("dep_paid"))
                .where(Payment.is_void == False, Payment.for_type == PaymentFor.deposit)
                .group_by(Payment.tenancy_id)
                .subquery()
            )
            eff_due_col = (RentSchedule.rent_due + func.coalesce(RentSchedule.adjustment, 0)).label("effective_due")
            rows = (await session.execute(
                select(
                    Tenancy.id,
                    Tenancy.security_deposit,
                    Tenancy.booking_amount,
                    Tenancy.checkin_date,
                    Tenancy.agreed_rent,
                    Tenant.name,
                    Room.room_number,
                    Property.name.label("property_name"),
                    eff_due_col,
                    func.coalesce(rent_paid_subq.c.paid, 0).label("rent_paid"),
                    func.coalesce(deposit_paid_subq.c.dep_paid, 0).label("dep_paid"),
                )
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .join(Property, Property.id == Room.property_id)
                .join(RentSchedule, RentSchedule.tenancy_id == Tenancy.id)
                .outerjoin(rent_paid_subq, rent_paid_subq.c.tenancy_id == Tenancy.id)
                .outerjoin(deposit_paid_subq, deposit_paid_subq.c.tenancy_id == Tenancy.id)
                .where(
                    RentSchedule.period_month == period,
                    Tenancy.status == TenancyStatus.active,
                )
            )).all()
            items = []
            for r in rows:
                eff = float(r.effective_due or 0)
                rent_paid = float(r.rent_paid or 0)
                dep_paid = float(r.dep_paid or 0)
                booking_amt = float(r.booking_amount or 0)
                dep_agreed = float(r.security_deposit or 0)
                checkin = r.checkin_date
                if checkin and checkin.replace(day=1) == period:
                    prorated = float(prorated_first_month_rent(float(r.agreed_rent or 0), checkin))
                    overflow = max(0.0, rent_paid - prorated)
                    rent_dues = max(0.0, prorated - rent_paid)
                    dep_due = max(0.0, dep_agreed - (dep_paid + overflow) - booking_amt)
                else:
                    rent_dues = max(0.0, eff - rent_paid)
                    dep_due = max(0.0, dep_agreed - dep_paid - booking_amt)
                total_dues = rent_dues + dep_due
                if total_dues <= 0:
                    continue
                items.append({
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": r.room_number,
                    "building": (r.property_name or "").split()[-1] if r.property_name else "",
                    "detail": f"₹{total_dues:,}",
                    "dues": total_dues,
                })
            # Add day-wise stays with outstanding dues
            daily_detail_rows = (await session.execute(
                select(
                    Tenancy.id,
                    Tenancy.agreed_rent,
                    Tenancy.checkin_date,
                    Tenancy.checkout_date,
                    Tenancy.booking_amount,
                    Tenancy.stay_type,
                    Tenant.name,
                    Room.room_number,
                    Property.name.label("property_name"),
                    func.coalesce(func.sum(Payment.amount), 0).label("total_paid"),
                )
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .join(Property, Property.id == Room.property_id)
                .outerjoin(Payment, and_(Payment.tenancy_id == Tenancy.id, Payment.is_void == False))
                .where(Tenancy.stay_type == StayType.daily, Tenancy.status == TenancyStatus.active)
                .group_by(Tenancy.id, Tenant.name, Room.room_number, Property.name)
            )).all()
            for r in daily_detail_rows:
                _rate = float(r.agreed_rent or 0)
                _nights = (r.checkout_date - r.checkin_date).days if r.checkin_date and r.checkout_date else 0
                _owed = _nights * _rate
                _paid = float(r.total_paid or 0) + float(r.booking_amount or 0)
                _dues = max(0.0, _owed - _paid)
                if _dues <= 0:
                    continue
                items.append({
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": r.room_number,
                    "building": (r.property_name or "").split()[-1] if r.property_name else "",
                    "detail": f"₹{int(_dues):,}",
                    "dues": _dues,
                    "stay_type": "daily",
                })
            items.sort(key=lambda x: x["dues"], reverse=True)
            return {"type": type, "items": items}

        elif type == "no_show":
            rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.checkin_date)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.no_show,
                )
                .order_by(Tenancy.checkin_date)
            )).all()
            items = []
            for r in rows:
                overdue = r.checkin_date is not None and r.checkin_date < today
                days_late = (today - r.checkin_date).days if overdue and r.checkin_date else 0
                detail = (
                    f"{days_late}d overdue (was {r.checkin_date.strftime('%-d %b')})"
                    if overdue
                    else f"Check-in: {r.checkin_date.strftime('%-d %b') if r.checkin_date else '—'}"
                )
                items.append({
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": r.room_number,
                    "detail": detail,
                    "is_overdue": overdue,
                    "days_overdue": days_late,
                })
            return {"type": type, "items": items}

        elif type == "prebooked":
            import json as _json
            obs_rows = (await session.execute(
                select(
                    OnboardingSession.id,
                    OnboardingSession.tenant_data,
                    OnboardingSession.tenant_phone,
                    OnboardingSession.checkin_date,
                    OnboardingSession.expires_at,
                    OnboardingSession.status,
                    OnboardingSession.room_id,
                    Room.room_number,
                )
                .outerjoin(Room, Room.id == OnboardingSession.room_id)
                .where(
                    OnboardingSession.status.in_(["pending_tenant", "pending_review"]),
                    or_(
                        OnboardingSession.status == "pending_review",
                        OnboardingSession.expires_at == None,
                        OnboardingSession.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
                    ),
                )
                .order_by(OnboardingSession.checkin_date.asc().nulls_last())
            )).all()
            noshow000_rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Tenancy.checkin_date)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.room_number == "000",
                    Tenancy.status == TenancyStatus.no_show,
                )
                .order_by(Tenancy.checkin_date.asc().nulls_last())
            )).all()
            items = []
            for r in obs_rows:
                td = _json.loads(r.tenant_data) if r.tenant_data else {}
                name = td.get("name") or r.tenant_phone or "—"
                room = r.room_number or "TBD"
                expires = r.expires_at
                if r.status == "pending_review":
                    detail = "Ready to check in"
                else:
                    detail = f"Link expires {expires.strftime('%-d %b')}" if expires else "Link sent"
                checkin = r.checkin_date
                checkin_str = checkin.strftime("%-d %b") if checkin else "—"
                items.append({
                    "tenancy_id": None,
                    "name": name,
                    "room": room,
                    "detail": f"Check-in: {checkin_str}",
                    "sub_detail": detail,
                    "is_overdue": False,
                })
            for r in noshow000_rows:
                checkin = r.checkin_date
                overdue = checkin is not None and checkin < today
                days_late = (today - checkin).days if overdue and checkin else 0
                detail = (
                    f"{days_late}d overdue"
                    if overdue
                    else f"Check-in: {checkin.strftime('%-d %b') if checkin else '—'}"
                )
                items.append({
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": "TBD",
                    "detail": detail,
                    "is_overdue": overdue,
                })
            return {"type": type, "items": items}

        elif type == "notices":
            from collections import defaultdict
            from datetime import date as _date
            import json as _json
            today = _date.today()

            rows = (await session.execute(
                select(
                    Tenancy.id, Tenant.name, Tenant.gender, Room.room_number,
                    Tenancy.notice_date, Tenancy.expected_checkout,
                    Tenancy.sharing_type, Room.max_occupancy, Room.id.label("room_id"),
                )
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.stay_type == StayType.monthly,
                    or_(Tenancy.notice_date != None, Tenancy.expected_checkout.between(date.today() - timedelta(days=30), date.today() + timedelta(days=60))),
                )
                .order_by(Tenancy.expected_checkout.asc().nulls_last())
            )).all()

            # Total active monthly tenants per room
            room_active_rows = (await session.execute(
                select(Tenancy.room_id, func.count(Tenancy.id).label("cnt"))
                .join(Room, Tenancy.room_id == Room.id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.stay_type == StayType.monthly,
                )
                .group_by(Tenancy.room_id)
            )).all()
            room_active: dict[int, int] = {r.room_id: r.cnt for r in room_active_rows}

            room_notice: dict[int, int] = defaultdict(int)
            for r in rows:
                room_notice[r.room_id] += 1

            items = []
            # Track (room_id, expected_checkout) per item for prebooking lookup
            item_room_info: list[tuple[int | None, object]] = []

            for r in rows:
                is_premium = r.sharing_type is not None and r.sharing_type.value == "premium"
                beds_freed = r.max_occupancy if is_premium else 1
                room_active_count = room_active.get(r.room_id, 0)
                room_notice_count = room_notice[r.room_id]
                eco = r.expected_checkout
                days_remaining = (eco - today).days if eco else 9999
                items.append({
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": r.room_number,
                    "detail": eco.strftime("%-d %b") if eco else "—",
                    "deposit_eligible": True,
                    "gender": r.gender,
                    "expected_checkout_iso": eco.isoformat() if eco else None,
                    "days_remaining": days_remaining,
                    "beds_freed": beds_freed,
                    "sharing_type": r.sharing_type.value if r.sharing_type else None,
                    "is_full_exit": room_notice_count >= room_active_count > 0,
                    "is_single_room": int(r.max_occupancy or 1) == 1,
                    "room_active_count": room_active_count,
                    "room_notice_count": room_notice_count,
                    "prebookings": [],
                })
                item_room_info.append((r.room_id, eco))

            # Day-stay tenants checking out within 30 days
            daily_rows = (await session.execute(
                select(
                    Tenancy.id, Tenant.name, Tenant.gender, Room.room_number,
                    Room.id.label("room_id"), Tenancy.checkout_date,
                )
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.stay_type == StayType.daily,
                    Tenancy.checkout_date.isnot(None),
                    Tenancy.checkout_date >= today,
                    Tenancy.checkout_date <= today + timedelta(days=30),
                )
                .order_by(Tenancy.checkout_date.asc())
            )).all()
            for r in daily_rows:
                co = r.checkout_date
                days_remaining = (co - today).days if co else 9999
                items.append({
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": r.room_number,
                    "detail": co.strftime("%-d %b") if co else "—",
                    "deposit_eligible": False,
                    "gender": r.gender,
                    "expected_checkout_iso": co.isoformat() if co else None,
                    "days_remaining": days_remaining,
                    "beds_freed": 1,
                    "sharing_type": None,
                    "is_full_exit": False,
                    "room_active_count": 1,
                    "room_notice_count": 1,
                    "stay_type": "daily",
                    "prebookings": [],
                })
                item_room_info.append((r.room_id, co))

            # Attach prebookings: pending OnboardingSessions + no_show Tenancies
            # Uses per-bed assignment — one replacement per freed bed slot.
            # `assigned` set prevents one replacement tagging multiple notice items in shared rooms.
            notice_room_ids = {rid for rid, _ in item_room_info if rid is not None}
            if notice_room_ids:
                assigned = set()  # notice item indices already matched to a replacement

                session_rows2 = (await session.execute(
                    select(
                        OnboardingSession.room_id,
                        OnboardingSession.checkin_date,
                        OnboardingSession.tenant_data,
                        OnboardingSession.tenant_phone,
                    )
                    .where(
                        OnboardingSession.room_id.in_(list(notice_room_ids)),
                        OnboardingSession.status.in_(["pending_tenant", "pending_review"]),
                        or_(
                            OnboardingSession.status == "pending_review",
                            OnboardingSession.expires_at == None,
                            OnboardingSession.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
                        ),
                    )
                )).all()
                for sr in session_rows2:
                    td = _json.loads(sr.tenant_data) if sr.tenant_data else {}
                    pb_name = td.get("name") or sr.tenant_phone or "—"
                    ci = sr.checkin_date
                    for i, (rid, eco) in enumerate(item_room_info):
                        if i in assigned or rid != sr.room_id:
                            continue
                        if ci is None or eco is None or ci >= eco:
                            items[i]["prebookings"].append({
                                "name": pb_name,
                                "checkin_date": ci.strftime("%-d %b %Y") if ci else "—",
                            })
                            assigned.add(i)
                            break

                # Also include no_show tenancies (approved, room assigned, awaiting arrival)
                no_show_rows = (await session.execute(
                    select(Tenancy.room_id, Tenancy.checkin_date, Tenant.name)
                    .join(Room, Room.id == Tenancy.room_id)
                    .join(Tenant, Tenant.id == Tenancy.tenant_id)
                    .where(
                        Tenancy.room_id.in_(list(notice_room_ids)),
                        Tenancy.status == TenancyStatus.no_show,
                        Room.room_number != "000",
                    )
                )).all()
                for nr in no_show_rows:
                    ci = nr.checkin_date
                    if ci is None:
                        continue
                    for i, (rid, eco) in enumerate(item_room_info):
                        if i in assigned or rid != nr.room_id:
                            continue
                        if eco is None or ci >= eco:
                            items[i]["prebookings"].append({
                                "name": nr.name or "—",
                                "checkin_date": ci.strftime("%-d %b %Y") if ci else "—",
                            })
                            assigned.add(i)
                            break

            return {"type": type, "items": items}

    return {"type": type, "items": []}


@router.get("/deposits-held")
async def get_deposits_held(_user: AppUser = Depends(get_current_user)):
    """Security deposit breakdown from active tenancy agreements."""
    async with get_session() as session:
        data = await deposits_breakdown(session=session)
    return data


@activity_router.get("/recent", response_model=ActivityResponse)
async def get_recent_activity(
    limit: int = 20,
    user: AppUser = Depends(get_current_user),
):
    async with get_session() as session:
        rows = (
            await session.execute(
                select(
                    Tenant.name.label("tenant_name"),
                    Room.room_number.label("room_number"),
                    Payment.amount,
                    Payment.payment_mode,
                    Payment.for_type,
                    Payment.payment_date,
                )
                .select_from(Payment)
                .join(Tenancy, Tenancy.id == Payment.tenancy_id)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .outerjoin(Room, Room.id == Tenancy.room_id)
                .where(Payment.is_void == False)
                .order_by(desc(Payment.payment_date), desc(Payment.id))
                .limit(limit)
            )
        ).all()

    items = [
        ActivityItem(
            tenant_name=r.tenant_name or "",
            room_number=r.room_number or "—",
            amount=int(r.amount or 0),
            method=r.payment_mode.value if hasattr(r.payment_mode, "value") else str(r.payment_mode or ""),
            for_type=r.for_type.value if hasattr(r.for_type, "value") else str(r.for_type or ""),
            payment_date=r.payment_date.isoformat() if r.payment_date else "",
        )
        for r in rows
    ]
    return ActivityResponse(items=items)


@activity_router.get("/feed")
async def get_activity_feed(
    limit: int = 60,
    user: AppUser = Depends(get_current_user),
):
    """Global activity feed — payments, check-ins, check-outs, rent changes, room moves, voids."""
    from src.database.models import AuditLog, AuthorizedUser, Payment, Tenancy, Tenant

    NON_PAYMENT_FIELDS = {
        "agreed_rent", "status", "status+checkout_date",
        "room_id", "is_void", "adjustment", "rent_schedule_one_off",
    }
    async with get_session() as session:
        # Non-payment audit events (check-ins, rent changes, room moves, voids, adjustments)
        audit_rows = (await session.execute(
            select(
                AuditLog.id, AuditLog.entity_type, AuditLog.field,
                AuditLog.entity_name, AuditLog.old_value, AuditLog.new_value,
                AuditLog.room_number, AuditLog.note, AuditLog.changed_by,
                AuditLog.source, AuditLog.created_at,
            )
            .where(AuditLog.field.in_(NON_PAYMENT_FIELDS))
            .order_by(desc(AuditLog.created_at))
            .limit(limit * 3)
        )).all()

        # All payments directly from payments table — source of truth for payment activity
        payment_rows = (await session.execute(
            select(
                Payment.id, Payment.amount, Payment.payment_mode, Payment.for_type,
                Payment.payment_date, Payment.notes, Payment.period_month,
                Payment.created_at.label("pmt_created_at"),
                Tenant.name.label("tenant_name"),
                Room.room_number.label("pmt_room"),
            )
            .join(Tenancy, Payment.tenancy_id == Tenancy.id)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(Payment.is_void == False)
            .order_by(desc(Payment.created_at), desc(Payment.id))
            .limit(limit * 3)
        )).all()

        staff_rows = (await session.execute(
            select(AuthorizedUser.phone, AuthorizedUser.name, AuthorizedUser.supabase_auth_id)
        )).all()

        room_id_rows = (await session.execute(
            select(Room.id, Room.room_number)
        )).all()
        room_id_to_number: dict[int, str] = {r.id: str(r.room_number) for r in room_id_rows}

    phone_to_name: dict[str, str] = {}
    uuid_to_name:  dict[str, str] = {}
    for s in staff_rows:
        if s.phone and s.name:
            phone_to_name[s.phone.lstrip("+").lstrip("91")] = s.name
            phone_to_name[s.phone] = s.name
        if s.supabase_auth_id and s.name:
            uuid_to_name[s.supabase_auth_id] = s.name
            uuid_to_name[s.supabase_auth_id[:30]] = s.name

    def _resolve_name(changed_by: str) -> str:
        if not changed_by:
            return ""
        cb = changed_by.strip()
        if cb in phone_to_name:
            return phone_to_name[cb]
        bare = cb.lstrip("+").lstrip("91")
        if bare in phone_to_name:
            return phone_to_name[bare]
        if cb in uuid_to_name:
            return uuid_to_name[cb]
        if cb in ("system", "import", "onboarding_form", "onboarding", "dashboard", "whatsapp"):
            return cb.replace("_", " ").title()
        return cb

    raw_events = []

    # --- Payment events from payments table (direct source) ---
    for r in payment_rows:
        mode_str = r.payment_mode.value if hasattr(r.payment_mode, "value") else str(r.payment_mode or "")
        method = "UPI" if "upi" in mode_str.lower() else "Cash" if "cash" in mode_str.lower() else "Transfer" if "transfer" in mode_str.lower() else ""
        for_type_str = r.for_type.value if hasattr(r.for_type, "value") else str(r.for_type or "")
        for_what = ""
        if for_type_str == "rent":
            for_what = "rent"
        elif for_type_str == "deposit":
            for_what = "deposit"
        elif for_type_str == "maintenance":
            for_what = "maintenance"
        elif for_type_str in ("booking", "advance"):
            for_what = "advance"
        amt = int(float(r.amount or 0))
        period_str = r.period_month.strftime("%b '%y") if r.period_month else ""
        label_parts = [f"₹{amt:,}"]
        if method:
            label_parts.append(method)
        if for_what:
            label_parts.append(for_what)
        if period_str:
            label_parts.append(period_str)
        label = " · ".join(label_parts)
        sublabel = (r.tenant_name or "") + (f" · Room {r.pmt_room}" if r.pmt_room else "")
        # Use created_at (when recorded) not payment_date (tenant's check-in/due date)
        ts = r.pmt_created_at
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if not ts:
            ts = datetime.combine(r.payment_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        raw_events.append({
            "_sort_ts": ts,
            "id": f"pmt_{r.id}",
            "type": "payment",
            "label": label,
            "sublabel": sublabel,
            "detail": "",
            "entity_name": r.tenant_name or "",
            "room_number": str(r.pmt_room or ""),
            "changed_by": "",
            "source": "",
            "ts": ts.isoformat(),
        })

    # --- Non-payment audit events ---
    for r in audit_rows:
        ev_type = "other"
        label = ""
        detail = ""
        sublabel = r.entity_name or ""
        if r.room_number:
            sublabel += f" · Room {r.room_number}"

        if r.field in ("status", "status+checkout_date"):
            new_val = (r.new_value or "").lower()
            if new_val == "active":
                ev_type = "checkin"
                label = "Checked in"
            elif new_val in ("exited", "exit"):
                ev_type = "checkout"
                label = "Checked out"
            elif new_val == "on_notice":
                ev_type = "notice"
                label = "Notice given"
            else:
                continue

        elif r.field == "agreed_rent":
            ev_type = "rent_change"
            try:
                old_amt = int(float(r.old_value or 0))
                new_amt = int(float(r.new_value or 0))
                label = f"Rent ₹{old_amt:,} → ₹{new_amt:,}"
                detail = "increased" if new_amt > old_amt else "decreased"
            except (ValueError, TypeError):
                label = "Rent changed"

        elif r.field == "room_id":
            ev_type = "room_change"
            def _rn(val: str | None) -> str:
                if not val:
                    return "?"
                try:
                    return room_id_to_number.get(int(val), val)
                except ValueError:
                    return val
            old_r = _rn(r.old_value)
            new_r = _rn(r.new_value)
            label = f"Room {old_r} → {new_r}"

        elif r.field == "is_void":
            ev_type = "void"
            label = "Payment voided"
            if r.note:
                detail = r.note[:80]

        elif r.field in ("adjustment", "rent_schedule_one_off"):
            ev_type = "adjustment"
            try:
                amt = int(float(r.new_value or 0))
                label = f"Rent credit ₹{abs(amt):,}" if amt < 0 else f"Rent adjustment +₹{amt:,}"
            except (ValueError, TypeError):
                label = "Rent adjustment"

        else:
            continue

        ts = r.created_at
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        by_name = _resolve_name(r.changed_by or "")
        raw_events.append({
            "_sort_ts": ts,
            "id": r.id,
            "type": ev_type,
            "label": label,
            "sublabel": sublabel,
            "detail": detail,
            "entity_name": r.entity_name or "",
            "room_number": r.room_number or "",
            "changed_by": by_name,
            "source": r.source or "",
            "ts": ts.isoformat() if ts else "",
        })

    # Sort merged events by timestamp descending, trim to limit
    raw_events.sort(key=lambda e: e["_sort_ts"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    events = []
    for ev in raw_events:
        ev.pop("_sort_ts")
        events.append(ev)
        if len(events) >= limit:
            break

    return {"events": events}


@activity_router.get("/recent-checkins")
async def get_recent_checkins(
    limit: int = 10,
    user: AppUser = Depends(get_current_user),
):
    """Return recently checked-in tenants with first-month payment status."""
    today = date.today()
    since = today - timedelta(days=45)

    async with get_session() as session:
        rows = (await session.execute(
            select(
                Tenancy.id,
                Tenant.name,
                Room.room_number,
                Tenancy.checkin_date,
                Tenancy.agreed_rent,
                Tenancy.security_deposit,
                Tenancy.booking_amount,
                Tenancy.stay_type,
            )
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Tenancy.status == TenancyStatus.active,
                Tenancy.checkin_date >= since,
                Room.is_staff_room == False,
                Room.room_number != "000",
            )
            .order_by(desc(Tenancy.checkin_date))
            .limit(limit)
        )).all()

        if not rows:
            return {"items": []}

        tenancy_ids = [r.id for r in rows]

        # First-month rent_due per tenancy (earliest RentSchedule row)
        first_period_subq = (
            select(
                RentSchedule.tenancy_id,
                func.min(RentSchedule.period_month).label("first_period"),
            )
            .where(RentSchedule.tenancy_id.in_(tenancy_ids))
            .group_by(RentSchedule.tenancy_id)
            .subquery()
        )
        rs_rows = (await session.execute(
            select(
                RentSchedule.tenancy_id,
                (RentSchedule.rent_due + func.coalesce(RentSchedule.adjustment, 0)).label("due"),
                RentSchedule.period_month,
            )
            .join(first_period_subq, and_(
                RentSchedule.tenancy_id == first_period_subq.c.tenancy_id,
                RentSchedule.period_month == first_period_subq.c.first_period,
            ))
        )).all()
        rent_due_map: dict[int, tuple] = {
            rs.tenancy_id: (float(rs.due), rs.period_month)
            for rs in rs_rows
        }

        # Rent payments collected for the first month per tenancy
        pay_rows = (await session.execute(
            select(
                Payment.tenancy_id,
                Payment.amount,
                Payment.for_type,
                Payment.period_month,
            )
            .where(
                Payment.tenancy_id.in_(tenancy_ids),
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
            )
        )).all()
        pay_by_tenancy: dict[int, list] = defaultdict(list)
        for p in pay_rows:
            pay_by_tenancy[p.tenancy_id].append(p)

    items = []
    for r in rows:
        tid = r.id
        checkin = r.checkin_date
        first_period = date(checkin.year, checkin.month, 1)

        due_info = rent_due_map.get(tid)
        first_due = due_info[0] if due_info else (
            float(r.agreed_rent or 0) + float(r.security_deposit or 0)
            - float(r.booking_amount or 0)
        )

        first_paid = sum(
            float(p.amount or 0)
            for p in pay_by_tenancy.get(tid, [])
            if p.period_month == first_period
        )
        balance = max(first_due - first_paid, 0.0)

        items.append({
            "tenancy_id": tid,
            "name": r.name,
            "room": r.room_number,
            "checkin_date": checkin.isoformat(),
            "agreed_rent": int(r.agreed_rent or 0),
            "security_deposit": int(r.security_deposit or 0),
            "first_month_due": int(first_due),
            "first_month_paid": int(first_paid),
            "balance": int(balance),
            "stay_type": r.stay_type.value if hasattr(r.stay_type, "value") else str(r.stay_type or "monthly"),
        })

    return {"items": items}
