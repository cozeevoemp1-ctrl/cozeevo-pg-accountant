import pytest
from src.agent.state import make_initial_state
from src.agent.nodes.router import route_decision


def _s(msg: str, *, pending_tool: str = None, clarify_q: str = None) -> dict:
    s = make_initial_state(user_id="wa:x", channel="whatsapp", role="admin", name="K")
    s["last_message"] = msg
    if pending_tool:
        s["pending_tool"] = pending_tool
    if clarify_q:
        s["clarify_question"] = clarify_q
    return s


def test_yes_in_confirm_goes_to_execute():
    assert route_decision(_s("yes", pending_tool="checkout")) == "execute"


def test_ok_in_confirm_goes_to_execute():
    assert route_decision(_s("ok", pending_tool="checkout")) == "execute"


def test_no_in_confirm_goes_to_cancel():
    assert route_decision(_s("no", pending_tool="checkout")) == "cancel"


def test_cancel_in_confirm_goes_to_cancel():
    assert route_decision(_s("cancel", pending_tool="checkout")) == "cancel"


def test_with_clarify_question_goes_to_intent():
    assert route_decision(_s("sharma", clarify_q="Which Ravi?")) == "intent"


def test_new_message_no_state_goes_to_intent():
    assert route_decision(_s("check out ravi")) == "intent"


def test_numeric_with_clarify_goes_to_intent_not_execute():
    # "1" mid-clarify should go to intent for resolution, not execute
    assert route_decision(_s("1", clarify_q="Which Ravi?")) == "intent"


def test_yes_without_pending_tool_goes_to_intent():
    # "yes" with no flow in progress should be classified by LLM
    assert route_decision(_s("yes")) == "intent"
