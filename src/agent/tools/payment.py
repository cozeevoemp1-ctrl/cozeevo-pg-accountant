"""
PAYMENT_LOG tool — wraps _do_log_payment_by_ids from account_handler.py.

Actual signature of _do_log_payment_by_ids (account_handler.py:315):
    async def _do_log_payment_by_ids(
        tenant_id: int,
        tenancy_id: int,       # REQUIRED — not optional
        amount,
        mode: str,
        ctx_name: str,         # who is logging (e.g. "owner")
        session: AsyncSession,
        period_month_str: str = "",
        skip_duplicate_check: bool = False,
        user_note: str = "",
    ) -> str
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ._base import BaseToolResult


class PaymentInput(BaseModel):
    tenant_id: int
    tenancy_id: int
    amount: float
    mode: str = "Cash"
    month: str = ""         # passed as period_month_str to _do_log_payment_by_ids
    tenant_name: str = ""
    room: str = ""


class PaymentResult(BaseToolResult):
    pass


async def _execute_payment(
    tenant_id: int,
    tenancy_id: int,
    amount: float,
    mode: str,
    month: str,
    session: AsyncSession,
) -> str:
    """Calls _do_log_payment_by_ids from account_handler.py."""
    from src.whatsapp.handlers.account_handler import _do_log_payment_by_ids

    reply = await _do_log_payment_by_ids(
        tenant_id=tenant_id,
        tenancy_id=tenancy_id,
        amount=amount,
        mode=mode,
        ctx_name="owner",
        session=session,
        period_month_str=month,
    )
    return reply or f"Rs.{amount:.0f} logged."


async def run_payment(entities: dict[str, Any], session: AsyncSession) -> PaymentResult:
    fields = {k: v for k, v in entities.items() if k in PaymentInput.model_fields}
    inp = PaymentInput(**fields)
    try:
        reply = await _execute_payment(
            inp.tenant_id, inp.tenancy_id, inp.amount, inp.mode, inp.month, session
        )
        return PaymentResult(success=True, reply=reply)
    except Exception as exc:
        return PaymentResult(success=False, reply=f"Payment log failed: {exc}")
