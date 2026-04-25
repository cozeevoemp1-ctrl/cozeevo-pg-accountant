"""
Full graph runs using MemorySaver — no DB, no real LLM (all mocked).
Tests graph topology: correct node sequence, state persistence across turns,
correct reply for each flow.
"""
import pytest
from unittest.mock import AsyncMock, patch

from src.agent.checkpointer import make_memory_checkpointer
from src.agent.graph import build_graph
from src.agent.state import make_initial_state


def _graph():
    return build_graph(checkpointer=make_memory_checkpointer())


def _cfg(user_id: str) -> dict:
    return {"configurable": {"thread_id": user_id, "session": AsyncMock(), "pg_id": "test"}}


def _classify(intent: str, entities: dict):
    return type("R", (), {
        "action": "classify", "intent": intent, "confidence": 0.95,
        "entities": entities, "reply": None, "options": None,
    })()


def _clarify(question: str):
    return type("R", (), {
        "action": "clarify", "intent": None, "confidence": 0.35,
        "entities": {}, "reply": question, "options": None,
    })()


@pytest.mark.asyncio
async def test_checkout_happy_path_confirm_then_yes():
    """
    Turn 1: 'checkout ravi sharma'
        → intent: CHECKOUT, entities resolved → confirm node
        → reply contains name + yes/no prompt
    Turn 2: 'yes'
        → router: pending_tool=checkout, msg=yes → execute
        → reply: success message
    """
    g   = _graph()
    cfg = _cfg("wa:test_happy")

    # Include tenancy_id so _resolve_tenant_entities is skipped
    entities = {"tenant_id": 7, "tenancy_id": 42, "tenant_name": "Ravi Sharma",
                "room": "305", "checkout_date": "2026-04-25"}
    llm_out  = _classify("CHECKOUT", entities)
    tool_out = AsyncMock(return_value=type("R", (), {"success": True, "reply": "Ravi Sharma checked out."})())

    with patch("src.agent.nodes.intent.run_conversation_agent", new=AsyncMock(return_value=llm_out)):
        with patch("src.agent.nodes.execute._TOOL_REGISTRY", {"checkout": tool_out}):
            s1 = make_initial_state(user_id="wa:test_happy", channel="whatsapp",
                                    role="admin", name="Kiran", last_message="checkout ravi sharma")
            r1 = await g.ainvoke(s1, config=cfg)
            assert "Ravi Sharma" in r1["reply"]
            assert "yes" in r1["reply"].lower() or "confirm" in r1["reply"].lower()

            r2 = await g.ainvoke({"last_message": "yes"}, config=cfg)
            assert "checked out" in r2["reply"].lower()
            # State cleared after execution
            assert r2.get("intent") is None
            assert r2.get("pending_tool") is None


@pytest.mark.asyncio
async def test_checkout_with_clarification_three_turns():
    """
    Turn 1: 'check out ravi' → LLM asks clarifying question
    Turn 2: 'sharma'         → intent resolves with tenancy_id → confirm
    Turn 3: 'yes'            → execute → success
    """
    g   = _graph()
    cfg = _cfg("wa:test_clarify")

    side_effects = [
        _clarify("Found Ravi Kumar (201) and Ravi Sharma (305). Which one?"),
        _classify("CHECKOUT", {"tenant_id": 7, "tenancy_id": 42, "tenant_name": "Ravi Sharma",
                               "room": "305", "checkout_date": "2026-04-25"}),
    ]
    tool_out = AsyncMock(return_value=type("R", (), {"success": True, "reply": "Ravi Sharma checked out."})())

    with patch("src.agent.nodes.intent.run_conversation_agent",
               new=AsyncMock(side_effect=side_effects)):
        with patch("src.agent.nodes.execute._TOOL_REGISTRY", {"checkout": tool_out}):
            s1 = make_initial_state(user_id="wa:test_clarify", channel="whatsapp",
                                    role="admin", name="Kiran", last_message="check out ravi")
            r1 = await g.ainvoke(s1, config=cfg)
            assert "Ravi" in r1["reply"] or "Which" in r1["reply"]

            r2 = await g.ainvoke({"last_message": "sharma"}, config=cfg)
            assert "305" in r2["reply"] or "confirm" in r2["reply"].lower()

            r3 = await g.ainvoke({"last_message": "yes"}, config=cfg)
            assert "checked out" in r3["reply"].lower()


@pytest.mark.asyncio
async def test_cancel_clears_all_state():
    """
    Turn 1: checkout flow → confirm
    Turn 2: 'no' → cancel → state wiped
    """
    g   = _graph()
    cfg = _cfg("wa:test_cancel")

    entities = {"tenant_id": 7, "tenancy_id": 42, "tenant_name": "Ravi",
                "room": "201", "checkout_date": "2026-04-25"}
    llm_out  = _classify("CHECKOUT", entities)

    with patch("src.agent.nodes.intent.run_conversation_agent", new=AsyncMock(return_value=llm_out)):
        s1 = make_initial_state(user_id="wa:test_cancel", channel="whatsapp",
                                role="admin", name="Kiran", last_message="checkout ravi")
        await g.ainvoke(s1, config=cfg)

        r2 = await g.ainvoke({"last_message": "no"}, config=cfg)
        assert "cancel" in r2["reply"].lower()

        final = await g.aget_state(cfg)
        assert final.values.get("intent") is None
        assert final.values.get("pending_tool") is None
        assert final.values.get("entities") == {}


@pytest.mark.asyncio
async def test_payment_log_happy_path():
    """PAYMENT_LOG: confirm then yes → success."""
    g   = _graph()
    cfg = _cfg("wa:test_payment")

    entities = {"tenant_id": 7, "tenancy_id": 42, "tenant_name": "Ravi", "room": "305",
                "amount": 5000.0, "mode": "UPI", "month": "April 2026"}
    llm_out  = _classify("PAYMENT_LOG", entities)
    tool_out = AsyncMock(return_value=type("R", (), {"success": True, "reply": "₹5000 logged for Ravi."})())

    with patch("src.agent.nodes.intent.run_conversation_agent", new=AsyncMock(return_value=llm_out)):
        with patch("src.agent.nodes.execute._TOOL_REGISTRY", {"payment": tool_out}):
            s1 = make_initial_state(user_id="wa:test_payment", channel="whatsapp",
                                    role="admin", name="Kiran", last_message="ravi paid 5000 upi")
            r1 = await g.ainvoke(s1, config=cfg)
            assert "5000" in r1["reply"] or "confirm" in r1["reply"].lower()

            r2 = await g.ainvoke({"last_message": "yes"}, config=cfg)
            assert "5000" in r2["reply"] or "logged" in r2["reply"].lower()
