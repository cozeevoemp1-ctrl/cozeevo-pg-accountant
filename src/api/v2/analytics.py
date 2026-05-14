"""GET /api/v2/app/analytics/occupancy — monthly occupancy dashboard data."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func, literal_column, select, and_, or_, text

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Room, Tenancy, TenancyStatus, StayType

router = APIRouter(prefix="/analytics")

START_MONTH = date(2025, 10, 1)
MONTH_ABBR = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


class MonthData(BaseModel):
    month: str
    label: str
    occ_beds: int
    fill_pct: float
    ci_single: int
    ci_double: int
    ci_triple: int
    ci_premium: int
    ci_daily: int
    checkouts: Optional[int]   # None = no checkout_date data in DB for this month
    avg_rent: int


class OccupancyKpi(BaseModel):
    today_occ_pct: float
    today_occ_beds: int
    total_beds: int
    current_avg_rent: int
    total_checkins: int
    total_checkouts: int


class OccupancyResponse(BaseModel):
    kpi: OccupancyKpi
    months: List[MonthData]


def _month_end(y: int, m: int) -> date:
    return date(y, m, monthrange(y, m)[1])


def _next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


async def _occ_at(session, target: date, total_beds: int) -> tuple[int, float]:
    """Occupied beds (premium=max_occ, else=1, per-room capped) at end of `target`."""
    per_room = (
        select(
            func.least(
                func.sum(
                    case(
                        (Tenancy.sharing_type == "premium", Room.max_occupancy),
                        else_=literal_column("1"),
                    )
                ),
                Room.max_occupancy,
            ).label("capped")
        )
        .select_from(Tenancy)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Room.is_staff_room == False,
            Room.room_number != "000",
            Tenancy.checkin_date <= target,
            or_(
                # Active tenant — still here
                Tenancy.status == TenancyStatus.active,
                # Exited but left AFTER the target date
                and_(
                    Tenancy.status == TenancyStatus.exited,
                    Tenancy.checkout_date != None,
                    Tenancy.checkout_date > target,
                ),
            ),
        )
        .group_by(Room.id, Room.max_occupancy)
        .subquery()
    )
    raw = await session.scalar(select(func.coalesce(func.sum(per_room.c.capped), 0)))
    beds = int(raw or 0)
    pct = round(beds / total_beds * 100, 1) if total_beds else 0.0
    return beds, pct


@router.get("/occupancy", response_model=OccupancyResponse)
async def get_occupancy(_user: AppUser = Depends(get_current_user)):
    today = date.today()

    async with get_session() as session:
        # Total revenue beds
        total_beds = int(
            await session.scalar(
                select(func.coalesce(func.sum(Room.max_occupancy), 0))
                .where(Room.is_staff_room == False, Room.room_number != "000")
            ) or 0
        )

        # Today's occupancy (active only)
        per_room_now = (
            select(
                func.least(
                    func.sum(
                        case(
                            (Tenancy.sharing_type == "premium", Room.max_occupancy),
                            else_=literal_column("1"),
                        )
                    ),
                    Room.max_occupancy,
                ).label("capped")
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
        today_beds = int(
            await session.scalar(select(func.coalesce(func.sum(per_room_now.c.capped), 0))) or 0
        )
        today_pct = round(today_beds / total_beds * 100, 1) if total_beds else 0.0

        # Current month avg rent (active monthly tenants)
        cur_avg = await session.scalar(
            select(func.avg(Tenancy.agreed_rent))
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.stay_type == StayType.monthly,
                Tenancy.status == TenancyStatus.active,
            )
        )
        current_avg_rent = int(cur_avg or 0)

        # Check-ins by month + sharing_type (monthly stays)
        ci_monthly_rows = (await session.execute(
            select(
                func.date_trunc(text("'month'"), Tenancy.checkin_date).label("m"),
                Tenancy.sharing_type,
                func.count().label("cnt"),
            )
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.stay_type == StayType.monthly,
                Tenancy.checkin_date >= START_MONTH,
            )
            .group_by(func.date_trunc(text("'month'"), Tenancy.checkin_date), Tenancy.sharing_type)
        )).all()

        # Check-ins by month (daily stays)
        ci_daily_rows = (await session.execute(
            select(
                func.date_trunc(text("'month'"), Tenancy.checkin_date).label("m"),
                func.count().label("cnt"),
            )
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.stay_type == StayType.daily,
                Tenancy.checkin_date >= START_MONTH,
            )
            .group_by(func.date_trunc(text("'month'"), Tenancy.checkin_date))
        )).all()

        # Checkouts by month (only populated checkout_date rows)
        co_rows = (await session.execute(
            select(
                func.date_trunc(text("'month'"), Tenancy.checkout_date).label("m"),
                func.count().label("cnt"),
            )
            .where(
                Tenancy.checkout_date != None,
                Tenancy.checkout_date >= START_MONTH,
            )
            .group_by(func.date_trunc(text("'month'"), Tenancy.checkout_date))
        )).all()

        # Avg agreed_rent by checkin month (monthly tenants)
        avg_rows = (await session.execute(
            select(
                func.date_trunc(text("'month'"), Tenancy.checkin_date).label("m"),
                func.avg(Tenancy.agreed_rent).label("avg_rent"),
            )
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.stay_type == StayType.monthly,
                Tenancy.checkin_date >= START_MONTH,
            )
            .group_by(func.date_trunc(text("'month'"), Tenancy.checkin_date))
        )).all()

        # Build lookup dicts keyed by (year, month)
        ci_type_map: dict[tuple, dict] = {}
        for r in ci_monthly_rows:
            ym = (r.m.year, r.m.month)
            ci_type_map.setdefault(ym, {k: 0 for k in ("single", "double", "triple", "premium")})
            st = r.sharing_type.value if hasattr(r.sharing_type, "value") else str(r.sharing_type or "single")
            ci_type_map[ym][st] = int(r.cnt)

        ci_daily_map = {(r.m.year, r.m.month): int(r.cnt) for r in ci_daily_rows}
        co_map = {(r.m.year, r.m.month): int(r.cnt) for r in co_rows}
        avg_map = {(r.m.year, r.m.month): int(r.avg_rent or 0) for r in avg_rows}

        # Enumerate months from START_MONTH to current
        months_out: list[MonthData] = []
        cur = START_MONTH
        while cur <= date(today.year, today.month, 1):
            ym = (cur.year, cur.month)
            occ_date = min(_month_end(cur.year, cur.month), today)
            occ_beds, fill_pct = await _occ_at(session, occ_date, total_beds)
            types = ci_type_map.get(ym, {})
            lbl = f"{MONTH_ABBR[cur.month]} '{str(cur.year)[2:]}"

            # checkouts: None means no DB data (historical tenants without checkout_date)
            # For months where DB has some data, return the count; otherwise None
            has_co_data = ym in co_map
            co_val: Optional[int] = co_map.get(ym) if has_co_data else None

            # avg_rent: use checkin-month avg; fallback to current for current month
            ar = avg_map.get(ym, current_avg_rent if ym == (today.year, today.month) else 0)

            months_out.append(MonthData(
                month=cur.strftime("%Y-%m"),
                label=lbl,
                occ_beds=occ_beds,
                fill_pct=fill_pct,
                ci_single=types.get("single", 0),
                ci_double=types.get("double", 0),
                ci_triple=types.get("triple", 0),
                ci_premium=types.get("premium", 0),
                ci_daily=ci_daily_map.get(ym, 0),
                checkouts=co_val,
                avg_rent=ar,
            ))
            cur = _next_month(cur)

        total_checkins = sum(
            m.ci_single + m.ci_double + m.ci_triple + m.ci_premium + m.ci_daily
            for m in months_out
        )
        total_checkouts = sum(m.checkouts or 0 for m in months_out)

    return OccupancyResponse(
        kpi=OccupancyKpi(
            today_occ_pct=today_pct,
            today_occ_beds=today_beds,
            total_beds=total_beds,
            current_avg_rent=current_avg_rent,
            total_checkins=total_checkins,
            total_checkouts=total_checkouts,
        ),
        months=months_out,
    )
