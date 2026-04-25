from src.agent.state import AgentState, make_initial_state


def test_initial_state_defaults():
    s = make_initial_state(user_id="wa:917845952289", channel="whatsapp", role="admin", name="Kiran")
    assert s["intent"] is None
    assert s["entities"] == {}
    assert s["turn_count"] == 0
    assert s["clarify_question"] is None
    assert s["pending_tool"] is None
    assert s["reply"] is None


def test_state_is_dict_compatible():
    s = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    assert isinstance(s, dict)
