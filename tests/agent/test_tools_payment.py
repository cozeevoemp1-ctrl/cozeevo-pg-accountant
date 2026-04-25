import pytest
from unittest.mock import AsyncMock, patch
from src.agent.tools.payment import run_payment, PaymentInput


@pytest.mark.asyncio
async def test_payment_returns_success_reply():
    with patch("src.agent.tools.payment._execute_payment",
               new=AsyncMock(return_value="Payment of Rs.5000 logged for Ravi.")):
        result = await run_payment(
            {"tenant_id": 42, "tenancy_id": 10, "amount": 5000.0, "mode": "UPI",
             "month": "April 2026", "tenant_name": "Ravi", "room": "305"},
            AsyncMock(),
        )
    assert result.success is True
    assert "5000" in result.reply or "Ravi" in result.reply


@pytest.mark.asyncio
async def test_payment_wraps_exception_as_failure():
    with patch("src.agent.tools.payment._execute_payment",
               side_effect=ValueError("Tenant not found")):
        result = await run_payment(
            {"tenant_id": 99, "tenancy_id": 0, "amount": 1000.0, "mode": "Cash",
             "month": "April 2026", "tenant_name": "X", "room": ""},
            AsyncMock(),
        )
    assert result.success is False
    assert "Tenant not found" in result.reply


def test_payment_input_validates():
    inp = PaymentInput(tenant_id=42, tenancy_id=10, amount=5000.0, mode="UPI",
                       month="April 2026", tenant_name="Ravi", room="305")
    assert inp.amount == 5000.0
    assert inp.mode == "UPI"
