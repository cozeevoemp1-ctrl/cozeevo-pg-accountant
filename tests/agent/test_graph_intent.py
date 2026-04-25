import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.agent.state import make_initial_state
from src.agent.nodes.intent import intent_node, route_from_intent, _resolve_tenant_entities


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


def _make_tenant_row(tenant_id: int, tenancy_id: int, name: str, room: str):
    """Build a fake (Tenant, Tenancy, Room) tuple."""
    tenant  = MagicMock(); tenant.id = tenant_id; tenant.name = name
    tenancy = MagicMock(); tenancy.id = tenancy_id
    room_   = MagicMock(); room_.room_number = room
    return (tenant, tenancy, room_)


# ── intent_node tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intent_node_sets_intent_and_entities():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["last_message"] = "checkout ravi sharma"

    with patch("src.agent.nodes.intent.run_conversation_agent",
               new=AsyncMock(return_value=_mock_classify("CHECKOUT", {"tenant_name": "ravi sharma"}))):
        with patch("src.agent.nodes.intent._resolve_tenant_entities",
                   new=AsyncMock(return_value={
                       "entities": {"tenant_name": "ravi sharma", "tenant_id": 42, "tenancy_id": 7},
                       "clarify_question": None,
                   })):
            config = {"configurable": {"session": AsyncMock(), "pg_id": "test-pg"}}
            result = await intent_node(state, config)

    assert result["intent"] == "CHECKOUT"
    assert result["entities"]["tenant_name"] == "ravi sharma"
    assert result["entities"]["tenancy_id"] == 7
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
               new=AsyncMock(return_value=_mock_classify("CHECKOUT", {"tenant_name": "sharma"}))):
        with patch("src.agent.nodes.intent._resolve_tenant_entities",
                   new=AsyncMock(return_value={
                       "entities": {"intent_hint": "CHECKOUT", "tenant_name": "sharma",
                                    "tenant_id": 42, "tenancy_id": 7},
                       "clarify_question": None,
                   })):
            config = {"configurable": {"session": AsyncMock(), "pg_id": "test-pg"}}
            result = await intent_node(state, config)

    # Previous entities preserved AND new entities merged
    assert result["entities"].get("intent_hint") == "CHECKOUT"
    assert result["entities"].get("tenancy_id") == 7


@pytest.mark.asyncio
async def test_intent_node_clarifies_when_tenant_not_found():
    """When _resolve_tenant_entities returns 0 matches, clarify_question is set."""
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["last_message"] = "checkout nobody"

    with patch("src.agent.nodes.intent.run_conversation_agent",
               new=AsyncMock(return_value=_mock_classify("CHECKOUT", {"tenant_name": "nobody"}))):
        with patch("src.agent.nodes.intent._resolve_tenant_entities",
                   new=AsyncMock(return_value={
                       "clarify_question": "No active tenant named 'nobody' found. Please check the name.",
                   })):
            config = {"configurable": {"session": AsyncMock(), "pg_id": "test-pg"}}
            result = await intent_node(state, config)

    assert "nobody" in result["clarify_question"]
    assert "tenancy_id" not in (result.get("entities") or {})


@pytest.mark.asyncio
async def test_intent_node_disambiguation_fast_path():
    """When choices are stored and user sends a number, resolve without LLM."""
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["last_message"] = "2"
    state["intent"] = "CHECKOUT"
    state["entities"] = {
        "tenant_name": "Ravi",
        "choices": [
            {"seq": 1, "tenant_id": 10, "tenancy_id": 100, "label": "Ravi Kumar (Room 201)"},
            {"seq": 2, "tenant_id": 20, "tenancy_id": 200, "label": "Ravi Sharma (Room 305)"},
        ],
    }
    state["pending_tool"] = "checkout"

    # run_conversation_agent should NOT be called in the fast path
    with patch("src.agent.nodes.intent.run_conversation_agent",
               new=AsyncMock(side_effect=AssertionError("LLM should not be called"))):
        config = {"configurable": {"session": AsyncMock(), "pg_id": "test-pg"}}
        result = await intent_node(state, config)

    assert result["entities"]["tenant_id"] == 20
    assert result["entities"]["tenancy_id"] == 200
    assert "choices" not in result["entities"]
    assert result["clarify_question"] is None
    assert result["pending_tool"] == "checkout"


# ── route_from_intent tests ───────────────────────────────────────────────────

def test_route_from_intent_to_clarify_when_question_set():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["clarify_question"] = "Which tenant?"
    assert route_from_intent(state) == "clarify"


def test_route_from_intent_to_confirm_when_required_entities_present():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["intent"] = "CHECKOUT"
    state["entities"] = {"tenancy_id": 7, "checkout_date": "2026-04-25"}
    state["pending_tool"] = "checkout"
    assert route_from_intent(state) == "confirm"


def test_route_from_intent_to_clarify_when_tenancy_id_missing():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["intent"] = "CHECKOUT"
    state["entities"] = {"tenant_name": "ravi"}   # name present but tenancy_id not resolved yet
    state["pending_tool"] = "checkout"
    assert route_from_intent(state) == "clarify"


def test_route_from_intent_payment_log_needs_tenancy_id_and_amount():
    state = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    state["intent"] = "PAYMENT_LOG"
    state["entities"] = {"tenancy_id": 7}   # amount missing
    state["pending_tool"] = "payment"
    assert route_from_intent(state) == "clarify"

    state["entities"] = {"tenancy_id": 7, "amount": 15000}
    assert route_from_intent(state) == "confirm"


# ── _resolve_tenant_entities unit tests ──────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_tenant_entities_single_match():
    session = AsyncMock()
    row = _make_tenant_row(tenant_id=5, tenancy_id=99, name="Ravi Kumar", room="201")

    with patch("src.whatsapp.handlers._shared._find_active_tenants_by_name",
               new=AsyncMock(return_value=[row])):
        result = await _resolve_tenant_entities("Ravi", session, {"tenant_name": "Ravi"})

    assert result["entities"]["tenant_id"] == 5
    assert result["entities"]["tenancy_id"] == 99
    assert result["clarify_question"] is None


@pytest.mark.asyncio
async def test_resolve_tenant_entities_no_match():
    session = AsyncMock()

    with patch("src.whatsapp.handlers._shared._find_active_tenants_by_name",
               new=AsyncMock(return_value=[])):
        result = await _resolve_tenant_entities("Ghost", session, {})

    assert "tenancy_id" not in result.get("entities", {})
    assert "Ghost" in result["clarify_question"]


@pytest.mark.asyncio
async def test_resolve_tenant_entities_multiple_matches():
    session = AsyncMock()
    rows = [
        _make_tenant_row(1, 10, "Ravi Kumar", "201"),
        _make_tenant_row(2, 20, "Ravi Sharma", "305"),
    ]

    with patch("src.whatsapp.handlers._shared._find_active_tenants_by_name",
               new=AsyncMock(return_value=rows)):
        result = await _resolve_tenant_entities("Ravi", session, {"tenant_name": "Ravi"})

    assert "choices" in result["entities"]
    assert len(result["entities"]["choices"]) == 2
    assert "Reply with the number" in result["clarify_question"]
    assert "tenancy_id" not in result["entities"]
