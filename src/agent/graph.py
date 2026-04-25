"""
LangGraph graph — the Kozzy agent core.

Graph topology per turn:
  router  ──intent──▶  intent  ──clarify──▶  clarify ──▶ END  (sends question)
          ──execute─▶  execute ──────────────────────────▶ END  (runs tool)
          ──cancel──▶  cancel  ──────────────────────────▶ END  (clears state)
                        intent ──confirm──▶  confirm ──▶ END  (sends plan)

State persists between turns via checkpointer. Thread ID = user_id.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import (
    cancel_node,
    clarify_node,
    confirm_node,
    execute_node,
    intent_node,
    route_decision,
    route_from_intent,
    router_node,
)
from .state import AgentState


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("router",  router_node)
    g.add_node("intent",  intent_node)
    g.add_node("clarify", clarify_node)
    g.add_node("confirm", confirm_node)
    g.add_node("execute", execute_node)
    g.add_node("cancel",  cancel_node)

    g.set_entry_point("router")

    g.add_conditional_edges(
        "router",
        route_decision,
        {"intent": "intent", "execute": "execute", "cancel": "cancel"},
    )
    g.add_conditional_edges(
        "intent",
        route_from_intent,
        {"clarify": "clarify", "confirm": "confirm", "__end__": END},
    )
    g.add_edge("clarify", END)
    g.add_edge("confirm", END)
    g.add_edge("execute", END)
    g.add_edge("cancel",  END)

    return g.compile(checkpointer=checkpointer)


# Module-level compiled graph — set once at FastAPI startup via init_agent().
_graph = None
_pool  = None    # psycopg3 pool (keep reference to close on shutdown)


def get_graph():
    if _graph is None:
        raise RuntimeError(
            "Agent graph not initialized. Call init_agent() in app lifespan startup."
        )
    return _graph


async def init_agent(*, test_mode: bool = False):
    """
    Initialize the agent graph at startup.
    test_mode=True uses MemorySaver (no DB — for local dev and tests).
    """
    global _graph, _pool
    from .checkpointer import make_memory_checkpointer, make_postgres_checkpointer

    if test_mode:
        cp = make_memory_checkpointer()
        _graph = build_graph(checkpointer=cp)
        return

    cp, pool = await make_postgres_checkpointer()
    _pool  = pool
    _graph = build_graph(checkpointer=cp)


async def run_agent(
    channel_msg,      # ChannelMessage
    session,          # AsyncSession
    pg_id: str,
    role: str,
    name: str,
) -> str:
    """
    Run one turn of the agent for this user. Returns reply text.
    Resumes an existing conversation thread or starts a new one.
    Thread ID = channel_msg.user_id (e.g. "wa:917845952289").
    """
    graph = get_graph()

    config = {
        "configurable": {
            "thread_id": channel_msg.user_id,
            "session":   session,
            "pg_id":     pg_id,
        }
    }

    existing = await graph.aget_state(config)

    if existing.values:
        # Resume existing thread — only inject the new message
        input_state = {"last_message": channel_msg.text}
    else:
        # New thread — initialize full state
        from .state import make_initial_state
        input_state = make_initial_state(
            user_id=channel_msg.user_id,
            channel=channel_msg.channel,
            role=role,
            name=name,
            last_message=channel_msg.text,
        )

    result = await graph.ainvoke(input_state, config=config)
    return result.get("reply") or "I'm not sure how to help with that. Could you rephrase?"
