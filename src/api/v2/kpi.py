"""GET /api/v2/app/reporting/kpi and GET /api/v2/app/activity/recent."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, desc

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    Complaint, ComplaintStatus,
    DaywiseStay,
    Payment, PaymentFor,
    Room, Tenancy, TenancyStatus,
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
                .where(Room.is_staff_room == False, Room.room_number != "UNASSIGNED")
            ) or 0
        )

        # Occupied beds (active tenants, including premium=2 beds)
        from sqlalchemy import case, literal_column
        occupied_raw = await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (Tenancy.sharing_type == "premium", Room.max_occupancy),
                            else_=literal_column("1"),
                        )
                    ),
                    0,
                )
            )
            .select_from(Tenancy)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "UNASSIGNED",
                Tenancy.status == TenancyStatus.active,
            )
        )
        occupied_beds = int(occupied_raw or 0)

        # Add legacy day-wise guests (old daywise_stays table, migrated from Excel).
        # New day-wise use Tenancy(stay_type=daily) and are already included above.
        old_daywise = int(await session.scalar(
            select(func.count()).select_from(DaywiseStay)
            .where(
                DaywiseStay.checkin_date <= today,
                DaywiseStay.checkout_date > today,
                DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
            )
        ) or 0)
        occupied_beds += old_daywise

        vacant_beds = max(total_beds - occupied_beds, 0)
        occ_pct = round(occupied_beds / total_beds * 100, 1) if total_beds > 0 else 0.0

        # Active tenants (people, not beds)
        active_tenants = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "UNASSIGNED",
                    Tenancy.status == TenancyStatus.active,
                )
            ) or 0
        )

        # Check-ins today
        checkins_today = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .where(Tenancy.checkin_date == today)
            ) or 0
        )

        # Checkouts today
        checkouts_today = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .where(Tenancy.checkout_date == today)
            ) or 0
        )

        # Open complaints
        open_complaints = int(
            await session.scalar(
                select(func.count(Complaint.id))
                .where(Complaint.status == ComplaintStatus.open)
            ) or 0
        )

    return KpiResponse(
        occupied_beds=occupied_beds,
        total_beds=total_beds,
        vacant_beds=vacant_beds,
        occupancy_pct=occ_pct,
        active_tenants=active_tenants,
        checkins_today=checkins_today,
        checkouts_today=checkouts_today,
        open_complaints=open_complaints,
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
                .where(Tenancy.checkin_date == today)
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
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.checkout_date, Tenancy.stay_type)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(Tenancy.checkout_date == today)
                .order_by(Room.room_number)
            )).all()
            return {"type": type, "items": [
                {
                    "tenancy_id": r.id, "name": r.name, "room": r.room_number,
                    "detail": "Check-out today",
                    "stay_type": (r.stay_type.value if hasattr(r.stay_type, "value") else str(r.stay_type or "monthly")),
                }
                for r in rows
            ]}

        elif type == "vacant":
            # Rooms where occupied_count < max_occupancy (includes partial vacancies)
            occ_subq = (
                select(Tenancy.room_id, func.count(Tenancy.id).label("occ"))
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
                .where(Room.is_staff_room == False, Room.room_number != "UNASSIGNED")
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

            items = []
            for r in room_rows:
                free = r.max_occupancy - r.occupied_count
                gender = _room_gender(r.id, r.occupied_count)
                gender_label = {"male": "Male", "female": "Female", "mixed": "Mixed", "empty": "", "unknown": ""}.get(gender, "")
                detail_parts = [f"{free} bed{'s' if free > 1 else ''} free"]
                if gender_label:
                    detail_parts.append(gender_label)
                items.append({
                    "name": f"Room {r.room_number}",
                    "room": r.room_number,
                    "detail": " · ".join(detail_parts),
                    "free_beds": free,
                    "gender": gender,
                })
            return {"type": type, "items": items}

        elif type == "occupied":
            rows = (await session.execute(
                select(Tenancy.id, Tenant.name, Room.room_number, Tenancy.agreed_rent)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(Room.is_staff_room == False, Room.room_number != "UNASSIGNED", Tenancy.status == TenancyStatus.active)
                .order_by(Room.room_number)
            )).all()
            return {"type": type, "items": [
                {"tenancy_id": r.id, "name": r.name, "room": r.room_number,
                 "detail": f"₹{int(r.agreed_rent or 0):,}/mo", "rent": int(r.agreed_rent or 0)}
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
