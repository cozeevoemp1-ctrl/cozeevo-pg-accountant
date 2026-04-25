import pytest
from unittest.mock import AsyncMock
from src.agent.state import make_initial_state
from src.agent.nodes.clarify import clarify_node
from src.agent.nodes.confirm import confirm_node
from src.agent.nodes.cancel import cancel_node


@pytest.mark.asyncio
async def test_clarify_node_echoes_question_as_reply():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["clarify_question"] = "Which Ravi did you mean?"
    result = await clarify_node(state, {"configurable": {}})
    assert result["reply"] == "Which Ravi did you mean?"


@pytest.mark.asyncio
async def test_confirm_node_checkout_includes_name_and_room():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["intent"] = "CHECKOUT"
    state["entities"] = {
        "tenant_id": 42, "tenant_name": "Ravi Sharma",
        "room": "305", "checkout_date": "2026-04-25",
    }
    result = await confirm_node(state, {"configurable": {}})
    assert "Ravi Sharma" in result["reply"]
    assert "305" in result["reply"]
    assert "yes" in result["reply"].lower() or "confirm" in result["reply"].lower()


@pytest.mark.asyncio
async def test_confirm_node_payment_includes_amount():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["intent"] = "PAYMENT_LOG"
    state["entities"] = {
        "tenant_id": 42, "tenant_name": "Ravi Sharma", "room": "305",
        "amount": 5000, "mode": "UPI", "month": "April 2026",
    }
    result = await confirm_node(state, {"configurable": {}})
    assert "5000" in result["reply"]
    assert "UPI" in result["reply"]


@pytest.mark.asyncio
async def test_cancel_node_clears_flow_state():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["intent"] = "CHECKOUT"
    state["pending_tool"] = "checkout"
    state["entities"] = {"tenant_id": 42}
    result = await cancel_node(state, {"configurable": {}})
    assert result["intent"] is None
    assert result["pending_tool"] is None
    assert result["entities"] == {}
    assert "cancel" in result["reply"].lower()
