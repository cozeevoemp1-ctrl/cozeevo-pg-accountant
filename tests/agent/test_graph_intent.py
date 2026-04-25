import pytest
from unittest.mock import AsyncMock, patch
from src.agent.state import make_initial_state
from src.agent.nodes.intent import intent_node, route_from_intent


def _mock_classify(intent: str, entities: dict, confidence: float = 0.95):
    return type("R", (), {
        "action": "classify", "intent": intent, "confidence": confidence,
        "entities": entities, "reply": None, "options": None,
    })()


def _mock_clarify(question: str):
    return type("R", (), {
        "action": "clarify", "intent": None, "confidence": 0.4,
        "entities": {}, "reply": question, "options": None,
    })()


@pytest.mark.asyncio
async def test_intent_node_sets_intent_and_entities():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["last_message"] = "checkout ravi sharma"

    with patch("src.agent.nodes.intent.run_conversation_agent",
               new=AsyncMock(return_value=_mock_classify("CHECKOUT", {"tenant_id": 42, "name": "ravi sharma"}))):
        config = {"configurable": {"session": AsyncMock(), "pg_id": "test-pg"}}
        result = await intent_node(state, config)

    assert result["intent"] == "CHECKOUT"
    assert result["entities"]["name"] == "ravi sharma"
    assert result["pending_tool"] == "checkout"
    assert result.get("clarify_question") is None


@pytest.mark.asyncio
async def test_intent_node_sets_clarify_on_low_confidence():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["last_message"] = "check him out"

    with patch("src.agent.nodes.intent.run_conversation_agent",
               new=AsyncMock(return_value=_mock_clarify("Who should I check out?"))):
        config = {"configurable": {"session": AsyncMock(), "pg_id": "test-pg"}}
        result = await intent_node(state, config)

    assert result["clarify_question"] == "Who should I check out?"
    assert result["reply"] == "Who should I check out?"


@pytest.mark.asyncio
async def test_intent_node_merges_entities_from_previous_turn():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["last_message"] = "sharma"
    state["entities"] = {"intent_hint": "CHECKOUT"}  # from prior turn
    state["clarify_question"] = "Which Ravi?"

    with patch("src.agent.nodes.intent.run_conversation_agent",
               new=AsyncMock(return_value=_mock_classify("CHECKOUT", {"tenant_id": 42}))):
        config = {"configurable": {"session": AsyncMock(), "pg_id": "test-pg"}}
        result = await intent_node(state, config)

    # Previous entities preserved AND new entities merged
    assert result["entities"].get("intent_hint") == "CHECKOUT"
    assert result["entities"].get("tenant_id") == 42


def test_route_from_intent_to_clarify_when_question_set():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["clarify_question"] = "Which tenant?"
    assert route_from_intent(state) == "clarify"


def test_route_from_intent_to_confirm_when_required_entities_present():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["intent"] = "CHECKOUT"
    state["entities"] = {"tenant_id": 42, "checkout_date": "2026-04-25"}
    state["pending_tool"] = "checkout"
    assert route_from_intent(state) == "confirm"


def test_route_from_intent_to_clarify_when_tenant_id_missing():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["intent"] = "CHECKOUT"
    state["entities"] = {"name": "ravi"}   # name present but tenant_id not resolved yet
    state["pending_tool"] = "checkout"
    assert route_from_intent(state) == "clarify"
