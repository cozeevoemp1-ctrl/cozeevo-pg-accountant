"""
services/property_logic.py
===========================
Single source of truth for all PG business mathematics.

Every function here is PURE:  no DB access, no HTTP, no side effects.
Import and call from any handler — never duplicate these formulas elsewhere.

Business rule constants live at the top of this file.
Change ONE constant here to update behaviour across the entire system.

Usage:
    from services.property_logic import calc_checkout_prorate, calc_notice_last_day, NOTICE_BY_DAY
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

# ── Business rule constants ────────────────────────────────────────────────────
# Edit these values to change PG policy — affects ALL handlers automatically.

NOTICE_BY_DAY: int = 5
"""
Tenant must give notice on or before this day-of-month for deposit to be eligible.

  notice_date.day <= NOTICE_BY_DAY  → deposit refundable, last day = end of THIS month
  notice_date.day >  NOTICE_BY_DAY  → deposit forfeited,  last day = end of NEXT month
"""

OVERPAYMENT_NOISE_RS: int = 10
"""Overpayments up to this amount (Rs.) are treated as rounding — no credit action taken."""

DUPLICATE_PAYMENT_HOURS: int = 24
"""Window (hours) in which a payment of the same amount to the same tenancy is flagged as duplicate."""


# ── Proration ─────────────────────────────────────────────────────────────────

def calc_checkin_prorate(amount: Decimal, checkin_date: date) -> int:
    """
    Prorated rent for the first (partial) month of tenancy.

    Bills from check-in day to end of month (inclusive).
    E.g. check-in on 15 March in a 31-day month:
         days_remaining = 31 - 15 + 1 = 17
         prorated = rent * 17 / 31
    """
    days_in_month = calendar.monthrange(checkin_date.year, checkin_date.month)[1]
    days_remaining = days_in_month - checkin_date.day + 1
    return _prorate(amount, days_remaining, days_in_month)


def calc_checkout_prorate(amount: Decimal, checkout_date: date) -> int:
    """
    Prorated rent for the final (partial) month of tenancy.

    Bills from day 1 to checkout day (inclusive).
    E.g. checkout on 20 April in a 30-day month:
         days_stayed = 20
         prorated = rent * 20 / 30
    """
    days_in_month = calendar.monthrange(checkout_date.year, checkout_date.month)[1]
    return _prorate(amount, checkout_date.day, days_in_month)


def _prorate(amount: Decimal, days: int, days_in_month: int) -> int:
    """Internal: integer prorated rent (always rounds down)."""
    if days_in_month <= 0:
        return 0
    days = max(0, min(days, days_in_month))
    return int(Decimal(str(amount)) * days / days_in_month)


# ── Payment status ────────────────────────────────────────────────────────────

def calc_effective_due(rent_due: Decimal, adjustment: Decimal = Decimal("0")) -> Decimal:
    """
    Effective rent due = base rent + adjustment.
    Adjustment is negative for discounts/waivers, positive for surcharges.
    """
    return (rent_due or Decimal("0")) + (adjustment or Decimal("0"))


def calc_payment_status(
    total_paid: Decimal,
    rent_due: Decimal,
    adjustment: Decimal = Decimal("0"),
) -> tuple[str, Decimal, Decimal, Decimal]:
    """
    Determine payment status after receiving a payment.

    Returns:
        (status, effective_due, remaining, overpay)

        status       — "paid" | "partial" | "pending"
        effective_due — base rent adjusted for discounts/surcharges
        remaining    — amount still owed (0 if paid/overpaid)
        overpay      — excess paid beyond effective_due (0 if not overpaid)
    """
    effective = calc_effective_due(rent_due, adjustment)
    remaining = effective - total_paid
    overpay = total_paid - effective

    if total_paid >= effective:
        status = "paid"
    elif total_paid > Decimal("0"):
        status = "partial"
    else:
        status = "pending"

    return status, effective, max(Decimal("0"), remaining), max(Decimal("0"), overpay)


# ── Notice / checkout ─────────────────────────────────────────────────────────

def is_deposit_eligible(notice_date: date, notice_by_day: int = NOTICE_BY_DAY) -> bool:
    """
    True if notice was given early enough for the deposit to be refundable.
    Uses NOTICE_BY_DAY rule: given on/before that day → eligible.
    """
    return notice_date.day <= notice_by_day


def calc_notice_last_day(notice_date: date, notice_by_day: int = NOTICE_BY_DAY) -> date:
    """
    Calculate the tenant's last day based on when notice was given.

    On time  (day <= notice_by_day): last day = last day of THIS month.
    Late     (day >  notice_by_day): last day = last day of NEXT month (extra month charged).
    """
    if notice_date.day <= notice_by_day:
        last = calendar.monthrange(notice_date.year, notice_date.month)[1]
        return date(notice_date.year, notice_date.month, last)
    else:
        m = notice_date.month + 1
        y = notice_date.year
        if m > 12:
            m, y = 1, y + 1
        last = calendar.monthrange(y, m)[1]
        return date(y, m, last)


# ── Settlement ────────────────────────────────────────────────────────────────

def calc_settlement(
    deposit: Decimal,
    outstanding_rent: Decimal = Decimal("0"),
    outstanding_maintenance: Decimal = Decimal("0"),
    damages: Decimal = Decimal("0"),
) -> Decimal:
    """
    Net deposit refund = deposit − all outstanding charges.
    A negative result means the tenant owes money even after forfeiting the deposit.
    """
    return deposit - outstanding_rent - outstanding_maintenance - damages


def fmt_settlement_lines(
    deposit: Decimal,
    outstanding_rent: Decimal = Decimal("0"),
    outstanding_maintenance: Decimal = Decimal("0"),
    damages: Decimal = Decimal("0"),
) -> list[str]:
    """
    Human-readable settlement breakdown for WhatsApp replies.
    Returns a list of lines ready to join with \\n.
    """
    net = calc_settlement(deposit, outstanding_rent, outstanding_maintenance, damages)
    lines = [
        f"Security deposit:        Rs.{int(deposit):,}",
    ]
    if outstanding_rent > 0:
        lines.append(f"— Outstanding rent:      Rs.{int(outstanding_rent):,}")
    if outstanding_maintenance > 0:
        lines.append(f"— Maintenance dues:      Rs.{int(outstanding_maintenance):,}")
    if damages > 0:
        lines.append(f"— Damage charges:        Rs.{int(damages):,}")
    lines.append("─" * 36)
    if net >= 0:
        lines.append(f"*Refund due: Rs.{int(net):,}*")
    else:
        lines.append(f"*Tenant owes: Rs.{int(abs(net)):,}* (deposit exhausted)")
    return lines
