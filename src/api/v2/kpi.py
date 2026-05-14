"""GET /api/v2/app/reporting/kpi and GET /api/v2/app/activity/recent."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

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

        # Monthly tenants with formal notice
        notices_count = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.stay_type == StayType.monthly,
                    Tenancy.notice_date != None,
                )
            ) or 0
        )

        # Check-ins today — only no_show tenants (pending physical arrival)
        checkins_today = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .where(
                    Tenancy.checkin_date == today,
                    Tenancy.status == TenancyStatus.no_show,
                )
            ) or 0
        )

        # Checkouts today
        checkouts_today = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .where(Tenancy.checkout_date == today)
            ) or 0
        )

        # Overdue tenants — active tenancies with rent_due > paid for current month
        period = date(today.year, today.month, 1)
        next_m = today.month % 12 + 1
        next_y = today.year + (1 if today.month == 12 else 0)
        period_end = date(next_y, next_m, 1)
        paid_subq = (
            select(Payment.tenancy_id, func.sum(Payment.amount).label("paid"))
            .where(
                Payment.is_void == False,
                or_(
                    # Regular rent payments for this period
                    and_(Payment.for_type == PaymentFor.rent, Payment.period_month == period),
                    # Deposit/booking paid in this calendar month (period_month=NULL for these)
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
        adj = func.coalesce(RentSchedule.adjustment, 0)
        effective_due = RentSchedule.rent_due + adj
        overdue_rows = (await session.execute(
            select(
                func.count(RentSchedule.id),
                func.coalesce(
                    func.sum(effective_due - func.coalesce(paid_subq.c.paid, 0)),
                    0,
                ),
            )
            .outerjoin(paid_subq, paid_subq.c.tenancy_id == RentSchedule.tenancy_id)
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .where(
                RentSchedule.period_month == period,
                Tenancy.status == TenancyStatus.active,
                effective_due > func.coalesce(paid_subq.c.paid, 0),
            )
        )).one()
        overdue_tenants = int(overdue_rows[0] or 0)
        overdue_amount = float(overdue_rows[1] or 0)

    return KpiResponse(
        occupied_beds=occupied_beds,
        total_beds=total_beds,
        vacant_beds=vacant_beds,
        occupancy_pct=occ_pct,
        active_tenants=active_tenants,
        no_show_count=no_show_count,
        notices_count=notices_count,
        checkins_today=checkins_today,
        checkouts_today=checkouts_today,
        overdue_tenants=overdue_tenants,
        overdue_amount=overdue_amount,
    )


@router.get("/kpi-detail")
async def get_kpi_detail(
    type: str,
    user: AppUser = Depends(get_current_user),
):
    """Return the underlying rows for a KPI tile."""
    today = date.today()
    async with get_session() as session:
        if type == "checkins_today":
            rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.checkin_date, Tenancy.agreed_rent, Tenancy.stay_type)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Tenancy.checkin_date == today,
                    Tenancy.status == TenancyStatus.no_show,
                )
                .order_by(Room.room_number)
            )).all()
            return {"type": type, "items": [
                {
                    "tenancy_id": r.id, "name": r.name, "room": r.room_number,
                    "detail": f"₹{int(r.agreed_rent or 0):,}/mo",
                    "rent": int(r.agreed_rent or 0),
                    "stay_type": (r.stay_type.value if hasattr(r.stay_type, "value") else str(r.stay_type or "monthly")),
                }
                for r in rows
            ]}

        elif type == "checkouts_today":
            rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.checkout_date, Tenancy.stay_type, Tenancy.status)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(Tenancy.checkout_date == today)
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
            room_rows = (await session.execute(
                select(
                    Room.id,
                    Room.room_number,
                    Room.max_occupancy,
                    func.coalesce(occ_subq.c.occ, 0).label("occupied_count"),
                )
                .outerjoin(occ_subq, occ_subq.c.room_id == Room.id)
                .where(Room.is_staff_room == False, Room.room_number != "000")
                .having(func.coalesce(occ_subq.c.occ, 0) < Room.max_occupancy)
                .group_by(Room.id, Room.room_number, Room.max_occupancy, occ_subq.c.occ)
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
                    "gender": gender,
                    "upcoming_checkin": upcoming.isoformat() if upcoming else None,
                })
            return {"type": type, "items": items}

        elif type == "occupied":
            rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.agreed_rent)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(Room.is_staff_room == False, Room.room_number != "000", Tenancy.status == TenancyStatus.active)
                .order_by(Room.room_number)
            )).all()
            return {"type": type, "items": [
                {"tenancy_id": r.id, "name": r.name, "room": r.room_number,
                 "detail": f"₹{int(r.agreed_rent or 0):,}/mo", "rent": int(r.agreed_rent or 0)}
                for r in rows
            ]}

        elif type == "dues":
            period = date(today.year, today.month, 1)
            next_m = today.month % 12 + 1
            next_y = today.year + (1 if today.month == 12 else 0)
            period_end = date(next_y, next_m, 1)
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
            eff_due_col = (RentSchedule.rent_due + func.coalesce(RentSchedule.adjustment, 0)).label("effective_due")
            rows = (await session.execute(
                select(
                    Tenancy.id,
                    Tenant.name,
                    Room.room_number,
                    Property.name.label("property_name"),
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
                .order_by(desc(RentSchedule.rent_due + func.coalesce(RentSchedule.adjustment, 0) - func.coalesce(paid_subq.c.paid, 0)))
            )).all()
            return {"type": type, "items": [
                {
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": r.room_number,
                    "building": (r.property_name or "").split()[-1] if r.property_name else "",
                    "detail": f"₹{int(r.effective_due - r.paid):,}",
                    "dues": int(r.effective_due - r.paid),
                }
                for r in rows
            ]}

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

        elif type == "notices":
            rows = (await session.execute(
                select(
                    Tenancy.id, Tenant.name, Room.room_number,
                    Tenancy.notice_date, Tenancy.expected_checkout,
                )
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "000",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.stay_type == StayType.monthly,
                    Tenancy.notice_date != None,
                )
                .order_by(Tenancy.expected_checkout.asc().nulls_last())
            )).all()
            return {"type": type, "items": [
                {
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": r.room_number,
                    "detail": r.expected_checkout.strftime("%-d %b") if r.expected_checkout else "—",
                    "deposit_eligible": (r.notice_date.day <= 5) if r.notice_date else None,
                }
                for r in rows
            ]}

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
