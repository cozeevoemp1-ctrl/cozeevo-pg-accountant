"""Single source of truth for MONTHLY tenant dues.

Why this module exists: the monthly dues formula was inlined in 7 API
endpoints and 3 bot helpers (audit docs/audits/2026-08-06-connectivity.md
D-2). They drifted — some copies credited the booking advance, some didn't,
and the Manage list disagreed with the dues page (D-3). Mirrors the
services/daily_dues.py consolidation: every caller MUST use these helpers
so the math can never diverge again.

Two shapes, both defined ONCE here:

1. monthly_dues() — the SPLIT view (rent vs deposit tracked separately,
   first-month proration with rent→deposit overflow). Used by the PWA
   current-month surfaces: get_tenant_dues, tenants list, KPI tile,
   KPI dues panel.

2. paid_toward_period_clause() + period_remaining() + outstanding_months()
   — the BUNDLED per-RentSchedule-row view (first-month rent_due bundles
   deposit − booking field; see first_month_rent_due). Used by the bot
   snapshot/checkout math, monthly rollover carry-forward, reporting
   pending, reminders overdue.

Day-stay dues stay in services/daily_dues.py (re-exported here so callers
have one import point).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, or_, select, func

from src.database.models import Payment, PaymentFor, RentSchedule, RentStatus
from src.services.daily_dues import booking_credit, daily_dues, daily_owed  # noqa: F401 (re-export)
from src.services.rent_schedule import prorated_first_month_rent


# ── Period helpers ────────────────────────────────────────────────────────────

def period_bounds(period: date) -> tuple[date, date]:
    """First day of period's month, first day of next month."""
    start = period.replace(day=1)
    end = date(start.year + (1 if start.month == 12 else 0), start.month % 12 + 1, 1)
    return start, end


def paid_toward_period_clause(period_start: date, period_end: date):
    """Canonical 'paid toward this billing period' filter (rules_financial §1).

    rent payments tagged to the period, PLUS deposit/booking payments
    (period_month is NULL on those) physically received inside the month —
    first-month rent_due bundles the deposit, so they must count or dues
    are inflated. Callers add their own tenancy/is_void constraints.
    """
    return or_(
        and_(Payment.for_type == PaymentFor.rent, Payment.period_month == period_start),
        and_(
            Payment.for_type.in_([PaymentFor.deposit, PaymentFor.booking]),
            Payment.period_month.is_(None),
            Payment.payment_date >= period_start,
            Payment.payment_date < period_end,
        ),
    )


def period_remaining(rent_due, adjustment, paid) -> Decimal:
    """Bundled per-RS-row remaining = max(0, rent_due + adjustment − paid)."""
    eff = Decimal(str(rent_due or 0)) + Decimal(str(adjustment or 0))
    return max(Decimal("0"), eff - Decimal(str(paid or 0)))


def first_month_due(agreed_rent, security_deposit, booking_amount, checkin: Optional[date]) -> float:
    """Bundled first-month due = prorated rent + deposit − booking advance.

    Pure mirror of first_month_rent_due() for callers holding scalars
    instead of a Tenancy object (e.g. KPI recent-checkins fallback).
    """
    prorated = float(prorated_first_month_rent(agreed_rent, checkin)) if checkin else float(agreed_rent or 0)
    return max(0.0, prorated + float(security_deposit or 0) - float(booking_amount or 0))


# ── Split view (current-month PWA surfaces) ──────────────────────────────────

@dataclass
class MonthlyDues:
    rent_dues: float
    deposit_due: float
    credit: float
    is_first_month: bool
    not_yet_checked_in: bool
    prorated_rent: Optional[float]  # set only for the check-in month
    effective_due: float            # rent_due + adjustment (RS view)
    booking_credit_amt: float       # advance credited (rows first, field fallback)

    @property
    def total(self) -> float:
        return self.rent_dues + self.deposit_due


def monthly_dues(
    *,
    period: date,
    as_of: date,
    checkin_date: Optional[date],
    agreed_rent,
    security_deposit,
    rent_due,
    adjustment,
    rent_paid,
    deposit_paid,
    booking_paid_rows,
    booking_amount_field,
) -> MonthlyDues:
    """Split rent/deposit dues for one tenancy for one period.

    Exact math previously inlined in get_tenant_dues (tenants.py) and the
    KPI tile/panel (kpi.py):
    - check-in month: recompute prorated rent from scratch (ignores RS
      bundling), apply adjustment as waiver, overflow rent overpay into
      the deposit bucket;
    - other months: RS effective_due vs rent-only payments; deposit
      tracked separately, credited with the booking advance
      (history rows first, legacy field fallback — booking_credit()).
    - future check-in ⇒ nothing due yet (rules_financial §13).
    """
    rent_paid_f = float(rent_paid or 0)
    dep_paid_f = float(deposit_paid or 0)
    dep_agreed = float(security_deposit or 0)
    adj = float(adjustment or 0)
    eff_due = float(rent_due or agreed_rent or 0) + adj
    booking_amt = booking_credit(booking_paid_rows, booking_amount_field)

    not_yet = bool(checkin_date and checkin_date > as_of)
    is_first = bool(checkin_date and checkin_date.replace(day=1) == period.replace(day=1))

    if not_yet:
        return MonthlyDues(0.0, 0.0, 0.0, is_first, True,
                           None, eff_due, booking_amt)

    if is_first:
        prorated = float(prorated_first_month_rent(agreed_rent, checkin_date))
        effective_prorated = max(0.0, prorated + adj)  # adjustment = waiver
        overflow = max(0.0, rent_paid_f - effective_prorated)
        rent_dues_v = max(0.0, effective_prorated - rent_paid_f)
        deposit_due_v = max(0.0, dep_agreed - (dep_paid_f + overflow) - booking_amt)
        credit = overflow if (overflow > 0 and dep_agreed == 0) else 0.0
        return MonthlyDues(rent_dues_v, deposit_due_v, credit, True, False,
                           prorated, eff_due, booking_amt)

    rent_dues_v = max(0.0, eff_due - rent_paid_f)
    credit = max(0.0, rent_paid_f - eff_due)
    deposit_due_v = max(0.0, dep_agreed - dep_paid_f - booking_amt)
    return MonthlyDues(rent_dues_v, deposit_due_v, credit, False, False,
                       None, eff_due, booking_amt)


# ── Bundled multi-month view (bot snapshot / checkout / rollover) ────────────

@dataclass
class MonthOutstanding:
    period: date
    effective_due: Decimal
    paid: Decimal
    remaining: Decimal
    maintenance_due: Decimal
    maintenance_paid: Decimal
    maintenance_remaining: Decimal
    status: str  # 'partial' if any payment, else 'unpaid'
    notes: Optional[str]


async def outstanding_months(session, tenancy_id: int) -> list[MonthOutstanding]:
    """Per-month outstanding for every pending/partial RentSchedule row.

    The bundled view: first-month rent_due already includes deposit −
    booking field, so paid uses the canonical clause above. Ordered
    oldest first (payment allocation depends on this).
    """
    rs_rows = (await session.execute(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy_id,
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
        ).order_by(RentSchedule.period_month.asc())
    )).scalars().all()

    out: list[MonthOutstanding] = []
    for rs in rs_rows:
        start, end = period_bounds(rs.period_month)
        paid = await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,  # noqa: E712
                paid_toward_period_clause(start, end),
            )
        ) or Decimal("0")
        paid = Decimal(str(paid))
        remaining = period_remaining(rs.rent_due, rs.adjustment, paid)

        maint_due = Decimal(str(rs.maintenance_due or 0))
        maint_paid = await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,  # noqa: E712
                Payment.for_type == PaymentFor.maintenance,
                Payment.period_month == rs.period_month,
            )
        ) or Decimal("0")
        maint_paid = Decimal(str(maint_paid))

        out.append(MonthOutstanding(
            period=rs.period_month,
            effective_due=Decimal(str(rs.rent_due or 0)) + Decimal(str(rs.adjustment or 0)),
            paid=paid,
            remaining=remaining,
            maintenance_due=maint_due,
            maintenance_paid=maint_paid,
            maintenance_remaining=max(Decimal("0"), maint_due - maint_paid),
            status="partial" if paid > 0 else "unpaid",
            notes=rs.notes,
        ))
    return out
