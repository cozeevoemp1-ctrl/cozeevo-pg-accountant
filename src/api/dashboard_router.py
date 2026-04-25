"""
src/api/dashboard_router.py
============================
REST API powering the Cozeevo web dashboard.

All endpoints require Authorization: Bearer <DASHBOARD_TOKEN> (set in .env).
If DASHBOARD_TOKEN is empty, auth is skipped (dev mode).

Endpoints:
  GET /api/dashboard/kpis              — headline KPIs for a given month
  GET /api/dashboard/pnl_trend         — last N months income vs expense
  GET /api/dashboard/expense_breakdown — category split for a month
  GET /api/dashboard/dues              — tenants with outstanding dues
  GET /api/dashboard/transactions      — filterable bank transaction table
  GET /api/dashboard/deposits          — deposit match summary
"""
from __future__ import annotations

import calendar
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select, func, and_, or_, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.db_manager import get_db_session
from src.database.models import (
    BankTransaction, BankUpload,
    Complaint, ComplaintStatus,
    Property, Room, Tenancy, TenancyStatus, Tenant,
    RentSchedule, RentStatus, Payment,
)

# Subquery: total payments per (tenancy_id, period_month)
def _paid_subquery():
    return (
        select(
            Payment.tenancy_id,
            Payment.period_month,
            func.sum(Payment.amount).label("paid"),
        )
        .where(Payment.is_void == False)
        .group_by(Payment.tenancy_id, Payment.period_month)
        .subquery()
    )

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# ── Token auth ────────────────────────────────────────────────────────────────

_TOKEN = os.getenv("DASHBOARD_TOKEN", "")


def _auth(authorization: str = Header("", alias="Authorization")):
    if not _TOKEN:
        return  # dev mode — no token configured
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authorization: Bearer <token> required")
    if authorization[7:] != _TOKEN:
        raise HTTPException(403, "Invalid dashboard token")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _month_range(month: int, year: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _prev_months(n: int) -> list[tuple[int, int]]:
    """Return last n (month, year) pairs including current month."""
    today = date.today()
    result = []
    m, y = today.month, today.year
    for _ in range(n):
        result.insert(0, (m, y))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return result


# ── KPI endpoint ──────────────────────────────────────────────────────────────

@router.get("/kpis")
async def get_kpis(
    month: int = Query(default=None),
    year:  int = Query(default=None),
    _=Depends(_auth),
    session: AsyncSession = Depends(get_db_session),
):
    today = date.today()
    m = month or today.month
    y = year  or today.year
    from_date, to_date = _month_range(m, y)

    # ── Occupancy ─────────────────────────────────────────────────────────────
    # Dynamic total from rooms table (excluding staff rooms).
    TOTAL_BEDS = await session.scalar(
        select(func.coalesce(func.sum(Room.max_occupancy), 0))
        .where(Room.is_staff_room == False)
    ) or 0
    TOTAL_BEDS = int(TOTAL_BEDS)

    # Occupied beds during the selected month, via single source of truth
    # (long-term tenancies + day-stays). See src/services/room_occupancy.py.
    from src.services.room_occupancy import count_occupied_beds
    occupied_beds = await count_occupied_beds(session, from_date, to_date)

    vacant_beds = TOTAL_BEDS - int(occupied_beds)
    occ_pct     = round(int(occupied_beds) / TOTAL_BEDS * 100, 1) if TOTAL_BEDS > 0 else 0

    # ── Bank P&L for the month ─────────────────────────────────────────────
    bank_rows = (await session.execute(
        select(BankTransaction.txn_type, func.sum(BankTransaction.amount).label("total"))
        .where(BankTransaction.txn_date >= from_date, BankTransaction.txn_date <= to_date)
        .group_by(BankTransaction.txn_type)
    )).all()

    revenue  = next((float(r.total) for r in bank_rows if r.txn_type == "income"),  0.0)
    expenses = next((float(r.total) for r in bank_rows if r.txn_type == "expense"), 0.0)
    net      = revenue - expenses

    # ── Dues outstanding — only the selected month, only prior check-ins ──────
    # Exclude same-month check-ins (they haven't had time to pay yet).
    # Use period_month == from_date (not <=) so we show THIS month's dues only.
    _paid_sq = _paid_subquery()
    dues_outstanding = await session.scalar(
        select(func.sum(
            RentSchedule.rent_due + RentSchedule.maintenance_due + RentSchedule.adjustment
            - func.coalesce(_paid_sq.c.paid, 0)
        ))
        .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
        .outerjoin(_paid_sq, and_(
            _paid_sq.c.tenancy_id  == RentSchedule.tenancy_id,
            _paid_sq.c.period_month == RentSchedule.period_month,
        ))
        .where(
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
            RentSchedule.period_month == from_date,
            Tenancy.status == TenancyStatus.active,
            Tenancy.checkin_date < from_date,
        )
    ) or 0

    # ── Property-level occupancy ─────────────────────────────────────────
    # Dynamic per-property bed totals from rooms table (excluding staff rooms).
    PROP_BEDS = {}
    prop_bed_rows = (await session.execute(
        select(
            Room.property_id,
            Property.name,
            func.coalesce(func.sum(Room.max_occupancy), 0).label("total_beds"),
        )
        .join(Property, Property.id == Room.property_id)
        .where(Room.is_staff_room == False)
        .group_by(Room.property_id, Property.name)
    )).all()
    for row in prop_bed_rows:
        pname = (row.name or "").upper()
        short = "THOR" if "THOR" in pname else ("HULK" if "HULK" in pname else row.name)
        PROP_BEDS[row.property_id] = {"name": short, "total": int(row.total_beds)}

    prop_occ_rows = (await session.execute(
        select(
            Room.property_id,
            func.coalesce(func.sum(
                case(
                    (Tenancy.sharing_type == "premium", Room.max_occupancy),
                    else_=literal_column("1"),
                )
            ), 0).label("occupied"),
        )
        .select_from(Tenancy)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Room.is_staff_room == False,
            Tenancy.checkin_date <= to_date,
            or_(
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                Tenancy.checkout_date >= from_date,
            ),
        )
        .group_by(Room.property_id)
    )).all()

    properties = []
    for row in prop_occ_rows:
        info = PROP_BEDS.get(row.property_id)
        if not info:
            continue
        occ = int(row.occupied)
        tot = info["total"]
        properties.append({
            "name": info["name"],
            "occupied": occ,
            "total": tot,
            "vacant": tot - occ,
            "pct": round(occ / tot * 100, 1),
        })

    # ── At a glance stats ─────────────────────────────────────────────────
    # New check-ins this month
    new_checkins = await session.scalar(
        select(func.count(Tenancy.id))
        .where(
            Tenancy.checkin_date >= from_date,
            Tenancy.checkin_date <= to_date,
        )
    ) or 0

    # Checkouts this month
    checkouts = await session.scalar(
        select(func.count(Tenancy.id))
        .where(
            Tenancy.checkout_date >= from_date,
            Tenancy.checkout_date <= to_date,
        )
    ) or 0

    # Open complaints
    open_complaints = await session.scalar(
        select(func.count(Complaint.id))
        .where(Complaint.status == ComplaintStatus.open)
    ) or 0

    # Avg rent per bed (from active rent_schedule for this month)
    avg_rent = await session.scalar(
        select(func.avg(RentSchedule.rent_due))
        .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
        .where(
            RentSchedule.period_month == from_date,
            Tenancy.status == TenancyStatus.active,
        )
    )
    avg_rent = round(float(avg_rent)) if avg_rent else 0

    # Collection rate: paid / (paid + outstanding) for this month
    total_due_month = await session.scalar(
        select(func.sum(RentSchedule.rent_due + RentSchedule.maintenance_due + RentSchedule.adjustment))
        .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
        .where(
            RentSchedule.period_month == from_date,
            Tenancy.status == TenancyStatus.active,
            Tenancy.checkin_date < from_date,
        )
    ) or 0
    total_due_f = float(total_due_month)
    dues_f = float(dues_outstanding)
    collected = total_due_f - dues_f
    collection_pct = round(collected / total_due_f * 100) if total_due_f > 0 else 0

    # ── Bank data coverage ─────────────────────────────────────────────────
    last_upload = (await session.execute(
        select(BankUpload.uploaded_at, BankUpload.to_date)
        .order_by(BankUpload.uploaded_at.desc())
        .limit(1)
    )).first()

    bank_coverage = None
    if last_upload and last_upload.to_date:
        bank_coverage = last_upload.to_date.strftime("%d %b %Y")

    # ── Active vs no-show breakdown ──────────────────────────────────────────
    active_people = await session.scalar(
        select(func.count(Tenancy.id))
        .select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(Room.is_staff_room == False, Tenancy.status == TenancyStatus.active,
               Tenancy.checkin_date <= to_date)
    ) or 0
    premium_people = await session.scalar(
        select(func.count(Tenancy.id))
        .select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(Room.is_staff_room == False, Tenancy.status == TenancyStatus.active,
               Tenancy.sharing_type == "premium", Tenancy.checkin_date <= to_date)
    ) or 0
    noshow_people = await session.scalar(
        select(func.count(Tenancy.id))
        .select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(Room.is_staff_room == False, Tenancy.status == TenancyStatus.no_show)
    ) or 0
    noshow_premium = await session.scalar(
        select(func.count(Tenancy.id))
        .select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(Room.is_staff_room == False, Tenancy.status == TenancyStatus.no_show,
               Tenancy.sharing_type == "premium")
    ) or 0
    regular_people = int(active_people) - int(premium_people)
    active_beds = regular_people + int(premium_people) * 2
    noshow_regular = int(noshow_people) - int(noshow_premium)
    noshow_beds = noshow_regular + int(noshow_premium) * 2

    return {
        "month": m, "year": y,
        "occupancy": {
            "beds_total":    TOTAL_BEDS,
            "beds_occupied": int(occupied_beds),
            "beds_vacant":   vacant_beds,
            "pct":           occ_pct,
            "checked_in":    int(active_people),
            "premium":       int(premium_people),
            "active_beds":   active_beds,
            "no_show":       int(noshow_people),
            "no_show_beds":  noshow_beds,
        },
        "properties":       properties,
        "revenue":          round(revenue),
        "expenses":         round(expenses),
        "net":              round(net),
        "dues_outstanding": round(float(dues_outstanding)),
        "at_a_glance": {
            "new_checkins":     int(new_checkins),
            "checkouts":        int(checkouts),
            "open_complaints":  int(open_complaints),
            "avg_rent":         avg_rent,
            "collection_pct":   collection_pct,
        },
        "bank_coverage":    bank_coverage,
    }


# ── P&L trend (last N months) ─────────────────────────────────────────────────

@router.get("/pnl_trend")
async def get_pnl_trend(
    months: int = Query(default=6, le=24),
    _=Depends(_auth),
    session: AsyncSession = Depends(get_db_session),
):
    periods = _prev_months(months)
    result  = []

    for m, y in periods:
        from_date, to_date = _month_range(m, y)
        rows = (await session.execute(
            select(BankTransaction.txn_type, func.sum(BankTransaction.amount).label("total"))
            .where(BankTransaction.txn_date >= from_date, BankTransaction.txn_date <= to_date)
            .group_by(BankTransaction.txn_type)
        )).all()
        income  = next((float(r.total) for r in rows if r.txn_type == "income"),  0.0)
        expense = next((float(r.total) for r in rows if r.txn_type == "expense"), 0.0)
        result.append({
            "label":   date(y, m, 1).strftime("%b %Y"),
            "income":  round(income),
            "expense": round(expense),
            "net":     round(income - expense),
        })

    return result


# ── Expense breakdown ─────────────────────────────────────────────────────────

@router.get("/expense_breakdown")
async def get_expense_breakdown(
    month: int = Query(default=None),
    year:  int = Query(default=None),
    _=Depends(_auth),
    session: AsyncSession = Depends(get_db_session),
):
    today = date.today()
    m = month or today.month
    y = year  or today.year
    from_date, to_date = _month_range(m, y)

    rows = (await session.execute(
        select(BankTransaction.category, func.sum(BankTransaction.amount).label("total"))
        .where(
            BankTransaction.txn_type == "expense",
            BankTransaction.txn_date >= from_date,
            BankTransaction.txn_date <= to_date,
        )
        .group_by(BankTransaction.category)
        .order_by(func.sum(BankTransaction.amount).desc())
    )).all()

    return [{"category": r.category, "amount": round(float(r.total))} for r in rows]


# ── Dues ──────────────────────────────────────────────────────────────────────

@router.get("/dues")
async def get_dues(
    month: int = Query(default=None),
    year:  int = Query(default=None),
    _=Depends(_auth),
    session: AsyncSession = Depends(get_db_session),
):
    today = date.today()
    m = month or today.month
    y = year  or today.year
    from_date, _ = _month_range(m, y)

    paid_sq = _paid_subquery()
    _outstanding = (
        RentSchedule.rent_due + RentSchedule.maintenance_due + RentSchedule.adjustment
        - func.coalesce(paid_sq.c.paid, 0)
    )

    rows = (await session.execute(
        select(
            Tenant.name,
            Room.room_number,
            func.sum(_outstanding).label("outstanding"),
            func.count(RentSchedule.id).label("months_pending"),
            func.max(RentSchedule.period_month).label("latest_period"),
        )
        .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
        .join(Tenant,  Tenant.id  == Tenancy.tenant_id)
        .join(Room,    Room.id    == Tenancy.room_id)
        .outerjoin(paid_sq, and_(
            paid_sq.c.tenancy_id   == RentSchedule.tenancy_id,
            paid_sq.c.period_month == RentSchedule.period_month,
        ))
        .where(
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
            RentSchedule.period_month == from_date,
            Tenancy.status == TenancyStatus.active,
            Tenancy.checkin_date < from_date,
        )
        .group_by(Tenant.name, Room.room_number)
        .having(func.sum(_outstanding) > 0)
        .order_by(func.sum(_outstanding).desc())
    )).all()

    return [
        {
            "tenant":         r.name,
            "room":           r.room_number,
            "outstanding":    round(float(r.outstanding)),
            "months_pending": r.months_pending,
            "latest_period":  r.latest_period.strftime("%b %Y") if r.latest_period else "",
        }
        for r in rows
    ]


# ── Transactions table ────────────────────────────────────────────────────────

@router.get("/transactions")
async def get_transactions(
    from_date: Optional[str] = Query(default=None),
    to_date:   Optional[str] = Query(default=None),
    txn_type:  Optional[str] = Query(default=None),
    category:  Optional[str] = Query(default=None),
    page:      int = Query(default=1, ge=1),
    per_page:  int = Query(default=50, le=200),
    _=Depends(_auth),
    session: AsyncSession = Depends(get_db_session),
):
    today   = date.today()
    fd      = date.fromisoformat(from_date) if from_date else today.replace(day=1)
    td      = date.fromisoformat(to_date)   if to_date   else today

    filters = [
        BankTransaction.txn_date >= fd,
        BankTransaction.txn_date <= td,
    ]
    if txn_type in ("income", "expense"):
        filters.append(BankTransaction.txn_type == txn_type)
    if category:
        filters.append(BankTransaction.category == category)

    total = await session.scalar(
        select(func.count(BankTransaction.id)).where(*filters)
    ) or 0

    rows = (await session.execute(
        select(BankTransaction)
        .where(*filters)
        .order_by(BankTransaction.txn_date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "items": [
            {
                "date":         r.txn_date.strftime("%d %b %Y"),
                "description":  r.description[:60] if r.description else "",
                "amount":       float(r.amount),
                "type":         r.txn_type,
                "category":     r.category,
                "sub_category": r.sub_category,
            }
            for r in rows
        ],
    }


# ── Deposit match summary ─────────────────────────────────────────────────────

@router.get("/deposits")
async def get_deposits(
    _=Depends(_auth),
    session: AsyncSession = Depends(get_db_session),
):
    """Quick summary: tenancies with security deposit vs bank income matches."""
    today = date.today()
    thirty_ago = today - timedelta(days=90)

    # Recent tenancies with security deposit
    tenancy_rows = (await session.execute(
        select(Tenant.name, Room.room_number, Tenancy.security_deposit, Tenancy.checkin_date)
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .join(Room,   Room.id   == Tenancy.room_id)
        .where(
            Tenancy.security_deposit > 0,
            Tenancy.checkin_date >= thirty_ago,
        )
        .order_by(Tenancy.checkin_date.desc())
        .limit(30)
    )).all()

    # Bank income in same period
    income_txns = (await session.execute(
        select(BankTransaction)
        .where(
            BankTransaction.txn_type == "income",
            BankTransaction.txn_date >= thirty_ago,
        )
        .order_by(BankTransaction.txn_date)
    )).scalars().all()

    used = set()
    result = []

    for name, room, dep, checkin in tenancy_rows:
        dep_f = float(dep or 0)
        first = (name or "").split()[0].lower()
        best  = None
        for t in income_txns:
            if t.id in used:
                continue
            if abs(float(t.amount) - dep_f) / max(dep_f, 1) > 0.10:
                continue
            days = abs((t.txn_date - checkin).days) if checkin else 999
            desc = (t.description or "").lower()
            if days <= 45 or (first and first in desc):
                best = t
                break
        if best:
            used.add(best.id)
        result.append({
            "tenant":   name,
            "room":     room,
            "deposit":  round(dep_f),
            "checkin":  checkin.strftime("%d %b %Y") if checkin else "",
            "matched":  best is not None,
            "bank_date": best.txn_date.strftime("%d %b %Y") if best else None,
            "bank_amt":  round(float(best.amount)) if best else None,
        })

    return result
