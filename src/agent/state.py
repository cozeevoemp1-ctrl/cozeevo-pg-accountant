from typing import Any, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict):
    user_id: str
    channel: str        # "whatsapp" | "app" | "voice"
    role: str           # "admin" | "owner" | "receptionist" | "tenant" | "lead"
    name: str
    last_message: str
    intent: Optional[str]
    entities: dict[str, Any]
    clarify_question: Optional[str]
    pending_tool: Optional[str]    # tool name queued for execute node
    reply: Optional[str]           # outbound text to send to user
    turn_count: int
    error: Optional[str]


def make_initial_state(
    *,
    user_id: str,
    channel: str,
    role: str,
    name: str,
    last_message: str = "",
) -> AgentState:
    return AgentState(
        user_id=user_id,
        channel=channel,
        role=role,
        name=name,
        last_message=last_message,
        intent=None,
        entities={},
        clarify_question=None,
        pending_tool=None,
        reply=None,
        turn_count=0,
        error=None,
    )
