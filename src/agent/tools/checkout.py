"""
CHECKOUT tool — wraps the checkout execution logic from owner_handler.py.

The graph has already handled disambiguation (clarify node) and confirmation
(confirm node). By the time this tool is called, tenancy_id and checkout_date
are resolved and the user has confirmed.

Actual signature of _do_checkout (owner_handler.py:3830):
    async def _do_checkout(
        tenancy_id: int,
        tenant_name: str,
        checkout_date_val: date,   # date object, NOT a string
        session: AsyncSession,
    ) -> str
"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ._base import BaseToolResult


class CheckoutInput(BaseModel):
    tenancy_id: int
    checkout_date: str = ""  # ISO date "YYYY-MM-DD"; empty → defaults to today
    tenant_name: str = ""
    room: str = ""


class CheckoutResult(BaseToolResult):
    pass


async def _execute_checkout(
    tenancy_id: int,
    tenant_name: str,
    checkout_date: str,
    session: AsyncSession,
) -> str:
    """Calls _do_checkout from owner_handler.py."""
    from src.whatsapp.handlers.owner_handler import _do_checkout

    try:
        checkout_date_val = date.fromisoformat(checkout_date)
    except ValueError:
        checkout_date_val = date.today()

    reply = await _do_checkout(
        tenancy_id=tenancy_id,
        tenant_name=tenant_name,
        checkout_date_val=checkout_date_val,
        session=session,
    )
    return reply or "Checkout recorded."


async def run_checkout(entities: dict[str, Any], session: AsyncSession) -> CheckoutResult:
    fields = {k: v for k, v in entities.items() if k in CheckoutInput.model_fields}
    inp = CheckoutInput(**fields)
    try:
        reply = await _execute_checkout(
            inp.tenancy_id, inp.tenant_name, inp.checkout_date, session
        )
        return CheckoutResult(success=True, reply=reply)
    except Exception as exc:
        return CheckoutResult(success=False, reply=f"Checkout failed: {exc}")
