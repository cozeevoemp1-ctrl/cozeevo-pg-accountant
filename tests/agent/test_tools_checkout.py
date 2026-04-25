import pytest
from datetime import date
from unittest.mock import AsyncMock, patch
from src.agent.tools.checkout import run_checkout, CheckoutInput


@pytest.mark.asyncio
async def test_checkout_returns_success_reply():
    with patch("src.agent.tools.checkout._execute_checkout",
               new=AsyncMock(return_value="Ravi Sharma checked out. Balance: Rs.0.")):
        result = await run_checkout(
            {"tenant_id": 42, "tenancy_id": 10, "checkout_date": "2026-04-25", "tenant_name": "Ravi Sharma", "room": "305"},
            AsyncMock(),
        )
    assert result.success is True
    assert "Ravi Sharma" in result.reply or "checked out" in result.reply.lower()


@pytest.mark.asyncio
async def test_checkout_wraps_exception_as_failure():
    with patch("src.agent.tools.checkout._execute_checkout",
               side_effect=ValueError("Tenant not found")):
        result = await run_checkout(
            {"tenant_id": 99, "tenancy_id": 0, "checkout_date": "2026-04-25", "tenant_name": "Unknown", "room": ""},
            AsyncMock(),
        )
    assert result.success is False
    assert "Tenant not found" in result.reply


def test_checkout_input_validates():
    inp = CheckoutInput(tenancy_id=10, checkout_date="2026-04-25", tenant_name="Ravi", room="305")
    assert inp.tenancy_id == 10
    assert inp.checkout_date == "2026-04-25"
