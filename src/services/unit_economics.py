"""
src/services/unit_economics.py
Unit economics KPIs — revenue per bed, cost per bed, avg rent, collection rate.
All monetary figures use True Revenue (gross income − security deposits held).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    BankTransaction, Payment, PaymentFor, PaymentMode,
    Room, RentSchedule, Tenancy, TenancyStatus, StayType,
)
from src.rules.pnl_classify import classify_txn

_TOTAL_INVESTMENT = 25_900_000  # ₹2.59Cr — Ashokan + Jitendra + Chandra&Team

_OPEX_CATS = {
    "Property Rent", "Electricity", "Water", "IT & Software", "Internet & WiFi",
    "Food & Groceries", "Fuel & Diesel", "Staff & Labour",
    "Maintenance & Repairs", "Cleaning Supplies", "Waste Disposal",
    "Shopping & Supplies", "Operational Expenses", "Marketing",
    "Govt & Regulatory", "Bank Charges", "Other Expenses",
}


async def get_unit_economics(month: date, session: AsyncSession) -> dict:
    """
    Compute unit economics for the given month (pass first day of month).
    Returns dict with all KPIs; bank_available=False if no bank data for month.
    """
    if month.month == 12:
        next_month = date(month.year + 1, 1, 1)
    else:
        next_month = date(month.year, month.month + 1, 1)

    # ── 1. Total revenue beds ─────────────────────────────────────────────────
    total_beds = int(await session.scalar(
        select(func.coalesce(func.sum(Room.max_occupancy), 0))
        .where(Room.is_staff_room == False, Room.room_number != "000")
    ) or 0)

    # ── 2. Occupied beds (premium tenant = full room, else 1 per tenant) ──────
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
    occupied_beds = int(await session.scalar(
        select(func.coalesce(func.sum(per_room_occ.c.capped_occ), 0))
    ) or 0)
    occupancy_pct = round(occupied_beds / total_beds * 100, 1) if total_beds > 0 else 0.0

    # ── 3. Active tenant count ─────────────────────────────────────────────────
    active_tenants = int(await session.scalar(
        select(func.count(Tenancy.id))
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status == TenancyStatus.active,
            Room.is_staff_room == False,
            Room.room_number != "000",
        )
    ) or 0)

    # ── 4. Avg agreed rent — monthly tenants only, True Rent (no deposits) ────
    avg_rent_scalar = await session.scalar(
        select(func.avg(Tenancy.agreed_rent))
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status == TenancyStatus.active,
            Tenancy.stay_type == StayType.monthly,
            Room.is_staff_room == False,
            Room.room_number != "000",
        )
    )
    avg_agreed_rent = round(float(avg_rent_scalar or 0))

    # ── 5. Collection rate (rent billed vs collected for this month) ──────────
    total_billed = float(await session.scalar(
        select(func.coalesce(func.sum(
            RentSchedule.rent_due + func.coalesce(RentSchedule.adjustment, 0)
        ), 0))
        .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
        .where(
            RentSchedule.period_month == month,
            Tenancy.status == TenancyStatus.active,
        )
    ) or 0)

    total_collected = float(await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(
            Payment.for_type == PaymentFor.rent,
            Payment.period_month == month,
            Payment.is_void == False,
        )
    ) or 0)
    collection_rate = round(total_collected / total_billed * 100, 1) if total_billed > 0 else 0.0

    # ── 6. Bank-based KPIs (True Revenue / OPEX / EBITDA) ────────────────────
    bank_rows = (await session.execute(
        select(
            BankTransaction.txn_type,
            BankTransaction.description,
            BankTransaction.amount,
        )
        .where(
            BankTransaction.txn_date >= month,
            BankTransaction.txn_date < next_month,
        )
    )).all()

    bank_available = len(bank_rows) > 0
    gross_bank_income = 0.0
    total_opex = 0.0

    for r in bank_rows:
        cat, _ = classify_txn(r.description or "", r.txn_type or "")
        if r.txn_type == "income" and cat != "Advance Deposit":
            gross_bank_income += float(r.amount)
        elif r.txn_type == "expense" and cat in _OPEX_CATS:
            total_opex += float(r.amount)

    # Cash rent from DB payments (not captured in bank CSV)
    cash_rent = float(await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(
            Payment.payment_mode == PaymentMode.cash,
            Payment.for_type == PaymentFor.rent,
            Payment.period_month == month,
            Payment.is_void == False,
        )
    ) or 0)

    # Security deposits held — active tenants checked in this month
    deposits_held = float(await session.scalar(
        select(func.coalesce(func.sum(Tenancy.security_deposit), 0))
        .where(
            Tenancy.status == "active",
            func.date_trunc("month", Tenancy.checkin_date) == month,
        )
    ) or 0)

    gross_income = gross_bank_income + cash_rent
    true_revenue = gross_income - deposits_held
    ebitda = true_revenue - total_opex

    revenue_per_bed = round(true_revenue / occupied_beds) if occupied_beds > 0 else 0
    opex_per_bed = round(total_opex / total_beds) if total_beds > 0 else 0
    ebitda_per_bed = round(ebitda / occupied_beds) if occupied_beds > 0 else 0
    ebitda_margin = round(ebitda / true_revenue * 100, 1) if true_revenue > 0 else 0.0

    # ── 7. Investment return (Concept A) ─────────────────────────────────────
    investment_yield_pct: Optional[float] = None
    payback_months: Optional[int] = None
    breakeven_occupancy_pct: Optional[float] = None
    if bank_available:
        annual_ebitda = ebitda * 12
        investment_yield_pct = round(annual_ebitda / _TOTAL_INVESTMENT * 100, 1)
        if ebitda > 0:
            payback_months = round(_TOTAL_INVESTMENT / ebitda)
        if true_revenue > 0 and occupied_beds > 0:
            rev_per_bed = true_revenue / occupied_beds
            breakeven_beds = total_opex / rev_per_bed
            breakeven_occupancy_pct = round(breakeven_beds / total_beds * 100, 1) if total_beds > 0 else None

    # ── 8. Revenue quality (Concept B) ───────────────────────────────────────
    potential_revenue = total_beds * avg_agreed_rent
    economic_occupancy_pct = round(total_collected / potential_revenue * 100, 1) if potential_revenue > 0 else 0.0
    revenue_leakage = round(total_billed - total_collected)

    return {
        "total_beds": total_beds,
        "occupied_beds": occupied_beds,
        "occupancy_pct": occupancy_pct,
        "active_tenants": active_tenants,
        "avg_agreed_rent": avg_agreed_rent,
        "total_billed": total_billed,
        "total_collected": total_collected,
        "collection_rate": collection_rate,
        "bank_available": bank_available,
        "gross_income": gross_income,
        "deposits_held": deposits_held,
        "true_revenue": true_revenue,
        "total_opex": total_opex,
        "ebitda": ebitda,
        "revenue_per_bed": revenue_per_bed,
        "opex_per_bed": opex_per_bed,
        "ebitda_per_bed": ebitda_per_bed,
        "ebitda_margin": ebitda_margin,
        "investment_yield_pct": investment_yield_pct,
        "payback_months": payback_months,
        "breakeven_occupancy_pct": breakeven_occupancy_pct,
        "economic_occupancy_pct": economic_occupancy_pct,
        "revenue_leakage": revenue_leakage,
    }
