"""
src/services/payments.py
========================
Payment business logic — shared between WhatsApp bot and owner PWA.

Public API:
    log_payment(...)  → PaymentResult

Responsibilities of this module:
    1. Insert a Payment row into the DB.
    2. Upsert the RentSchedule row (auto-create if missing, update status).
    3. Write an AuditLog entry via src.services.audit.write_audit_entry().
    4. Compute and return the new outstanding balance.

Out of scope (handled by callers):
    - Duplicate detection / wrong-month warnings (conversation concerns).
    - Google Sheets write-back (WhatsApp handler concern).
    - Overpayment / underpayment prompts (conversation concerns).
    - Message formatting (WhatsApp handler concern).

NOTE: Do NOT write org_id — that column does not exist yet (Task 2 adds it).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    AuditLog,
    Payment,
    PaymentFor,
    PaymentMode,
    RentSchedule,
    RentStatus,
    Tenancy,
)
from src.services.audit import write_audit_entry


# ── Public result type ─────────────────────────────────────────────────────────

@dataclass
class PaymentResult:
    """Returned by log_payment().

    Attributes:
        payment_id:   PK of the newly created Payment row.
        new_balance:  Remaining amount owed for the period month after this
                      payment. Zero or negative means fully paid / overpaid.
        status:       RentSchedule status after this payment (None for
                      non-rent payments where no RentSchedule is touched).
        effective_due: Effective rent due for the period (0 for non-rent).
        total_paid:   Total paid for the period including this payment
                      (0 for non-rent).
    """
    payment_id: int
    new_balance: Decimal
    status: Optional[RentStatus]
    effective_due: Decimal
    total_paid: Decimal


# ── Helpers ────────────────────────────────────────────────────────────────────

_METHOD_TO_MODE: dict[str, PaymentMode] = {
    # UPI apps
    "upi":         PaymentMode.upi,
    "gpay":        PaymentMode.upi,
    "googlepay":   PaymentMode.upi,
    "phonepe":     PaymentMode.upi,
    "paytm":       PaymentMode.upi,
    "online":      PaymentMode.upi,
    # Bank transfer (was incorrectly grouped with UPI before)
    "bank":            PaymentMode.bank_transfer,
    "bank_transfer":   PaymentMode.bank_transfer,
    "banktransfer":    PaymentMode.bank_transfer,
    "transfer":        PaymentMode.bank_transfer,
    "netbanking":      PaymentMode.bank_transfer,
    "net banking":     PaymentMode.bank_transfer,
    "neft":            PaymentMode.bank_transfer,
    "imps":            PaymentMode.bank_transfer,
    "rtgs":            PaymentMode.bank_transfer,
    # Cheque
    "cheque": PaymentMode.cheque,
    "check":  PaymentMode.cheque,
    # Cash
    "cash":  PaymentMode.cash,
    "card":  PaymentMode.cash,   # no card enum — fall back to cash
    "other": PaymentMode.cash,
}


def _resolve_payment_mode(method: str) -> PaymentMode:
    """Map a free-text or PWA method string to a PaymentMode enum value."""
    return _METHOD_TO_MODE.get((method or "").lower().strip(), PaymentMode.cash)


def _resolve_for_type(for_type: str) -> PaymentFor:
    """Map a for_type string to PaymentFor enum value."""
    try:
        return PaymentFor(for_type.lower())
    except (ValueError, AttributeError):
        return PaymentFor.rent


def _parse_period_month(period_month: Optional[str]) -> date:
    """Parse 'YYYY-MM' or 'YYYY-MM-DD' to first-of-month date."""
    if not period_month:
        return date.today().replace(day=1)
    try:
        # Accept YYYY-MM or YYYY-MM-DD
        raw = period_month.strip()
        if len(raw) == 7:  # YYYY-MM
            raw = raw + "-01"
        d = date.fromisoformat(raw)
        return d.replace(day=1)
    except ValueError:
        return date.today().replace(day=1)


# ── Core service function ──────────────────────────────────────────────────────

async def log_payment(
    *,
    tenancy_id: int,
    amount,
    method: str,
    for_type: str,
    period_month: Optional[str],
    recorded_by: str,
    session: AsyncSession,
    notes: Optional[str] = None,
    source: str = "service",
    room_number: Optional[str] = None,
    entity_name: Optional[str] = None,
) -> PaymentResult:
    """Insert a payment and update rent schedule status.

    Args:
        tenancy_id:    PK of the Tenancy this payment is for.
        amount:        Payment amount (int, float, or Decimal).
        method:        Payment method string ("UPI", "cash", "GPay", …).
        for_type:      Payment type ("rent", "deposit", "maintenance", …).
        period_month:  Month string "YYYY-MM" (or "YYYY-MM-DD"). Defaults to
                       current month.
        recorded_by:   Phone number or identifier of whoever is logging this.
        session:       SQLAlchemy async session. Caller owns the transaction.
        notes:         Optional free-text notes to store on the payment row.
        source:        audit_log source field ("whatsapp", "pwa", "system", …).

    Returns:
        PaymentResult with payment_id and new_balance.

    Raises:
        ValueError: If tenancy_id is not found.
    """
    amount_dec = Decimal(str(amount))
    pay_mode = _resolve_payment_mode(method)
    pay_for = _resolve_for_type(for_type)
    period = _parse_period_month(period_month)

    # Freeze guard: past calendar months are locked — no new payments allowed.
    # Future months are fine (advance payments). Current month is always fine.
    current_period = date.today().replace(day=1)
    if period < current_period:
        raise ValueError(
            f"period_frozen: {period.strftime('%B %Y')} is closed — "
            "payments cannot be added to past months. "
            "Use the adjustment line on the current month row to correct discrepancies."
        )

    tenancy: Optional[Tenancy] = await session.get(Tenancy, tenancy_id)
    if tenancy is None:
        raise ValueError(f"Tenancy {tenancy_id} not found")

    is_daily = getattr(tenancy, "stay_type", None) and tenancy.stay_type.value == "daily"

    # ── Upsert RentSchedule (only for monthly rent payments — skip daily stays) ──
    rs: Optional[RentSchedule] = None
    if pay_for == PaymentFor.rent and not is_daily:
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy.id,
                RentSchedule.period_month == period,
            )
        )

        if not rs:
            # Auto-create, carrying over notes from the previous month
            prev_month = _prev_month(period)
            prev_rs = await session.scalar(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == tenancy.id,
                    RentSchedule.period_month == prev_month,
                )
            )
            carry_notes = prev_rs.notes if prev_rs else None

            from src.services.rent_schedule import first_month_rent_due
            rs = RentSchedule(
                tenancy_id=tenancy.id,
                period_month=period,
                rent_due=first_month_rent_due(tenancy, period),
                maintenance_due=tenancy.maintenance_fee or Decimal("0"),
                status=RentStatus.pending,
                due_date=period,
                notes=carry_notes,
            )
            session.add(rs)
            await session.flush()

    # ── Sum already-paid this period (before this payment) ────────────────
    prev_paid: Decimal = (
        await session.scalar(
            select(func.sum(Payment.amount)).where(
                Payment.tenancy_id == tenancy.id,
                Payment.period_month == period,
                Payment.is_void == False,
            )
        )
        or Decimal("0")
    )

    # ── Resolve the receptionist who recorded this ─────────────────────────
    # recorded_by is typically the caller's phone (or name). Normalise to last
    # 10 digits and look up Staff by phone so received_by_staff_id is set on
    # the Payment row. Sheet's "entered by" column + audit trails depend on
    # this being populated.
    received_by_staff_id: Optional[int] = None
    if recorded_by:
        import re as _re
        from src.database.models import Staff as _Staff
        _digits = _re.sub(r"[^0-9]", "", recorded_by)
        if len(_digits) >= 10:
            _phone10 = _digits[-10:]
            _staff = await session.scalar(
                select(_Staff).where(_Staff.phone.like(f"%{_phone10}"))
            )
            if _staff:
                received_by_staff_id = _staff.id

    # ── Create Payment row ─────────────────────────────────────────────────
    _period_for_hash = (period if pay_for == PaymentFor.rent else None) or ""
    _hash_raw = f"{tenancy.id}:{date.today()}:{amount_dec}:{pay_mode.value}:{_period_for_hash}:{pay_for.value}"
    _unique_hash = hashlib.md5(_hash_raw.encode()).hexdigest()

    payment = Payment(
        tenancy_id=tenancy.id,
        amount=amount_dec,
        payment_date=date.today(),
        payment_mode=pay_mode,
        for_type=pay_for,
        period_month=period if (pay_for == PaymentFor.rent and not is_daily) else None,
        notes=notes or f"Logged by {recorded_by}",
        is_void=False,
        receipt_url=None,
        received_by_staff_id=received_by_staff_id,
        unique_hash=_unique_hash,
    )
    session.add(payment)
    try:
        await session.flush()  # get payment.id — raises IntegrityError on duplicate hash
    except Exception as _exc:
        if "uq_payment_unique_hash" in str(_exc) or "unique_hash" in str(_exc):
            await session.rollback()
            raise ValueError("duplicate_payment") from _exc
        raise

    # ── Update RentSchedule status + compute result fields ────────────────
    rs_status: Optional[RentStatus] = None
    effective_due_val: Decimal = Decimal("0")
    total_paid_val: Decimal = Decimal("0")

    if rs is not None:
        total_paid_val = prev_paid + amount_dec
        rent_due = rs.rent_due or Decimal("0")
        adjustment = rs.adjustment or Decimal("0")
        effective_due_val = rent_due + adjustment  # negative adj = discount

        rs.status = RentStatus.paid if total_paid_val >= effective_due_val else RentStatus.partial
        rs_status = rs.status

    # ── Compute new_balance ────────────────────────────────────────────────
    if rs is not None:
        new_balance = effective_due_val - total_paid_val
    else:
        new_balance = Decimal("0")

    # ── Audit entry ────────────────────────────────────────────────────────
    await write_audit_entry(
        session=session,
        changed_by=recorded_by,
        entity_type="payment",
        entity_id=payment.id,
        field="payment.log",
        old_value=None,
        new_value=str(float(amount_dec)),
        source=source,
        room_number=room_number,
        entity_name=entity_name,
        note=(
            f"Payment Rs.{int(amount_dec):,} {method} "
            f"for {period.strftime('%b %Y') if pay_for == PaymentFor.rent else for_type}"
        ),
    )

    return PaymentResult(
        payment_id=payment.id,
        new_balance=new_balance,
        status=rs_status,
        effective_due=effective_due_val,
        total_paid=total_paid_val,
    )


# ── Internal helpers ───────────────────────────────────────────────────────────

def _prev_month(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)
