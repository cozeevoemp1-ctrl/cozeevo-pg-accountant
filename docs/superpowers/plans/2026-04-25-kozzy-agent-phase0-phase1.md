# Kozzy Agent — Phase 0 + Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LangGraph-based agent core that handles CHECKOUT and PAYMENT_LOG intents end-to-end (disambiguation → confirmation → execution) with full state persistence in Supabase, running alongside the existing bot via the USE_PYDANTIC_AGENTS feature flag.

**Architecture:** LangGraph graph (router → intent → clarify → confirm → execute) replaces the ad-hoc PendingAction pattern for agent-handled intents. Phase 0 audits existing code before touching it. Existing regex + gatekeeper system remains untouched for all other intents.

**Tech Stack:** Python 3.11, LangGraph 0.2+, PydanticAI (existing), Groq Llama 3.3 70B (existing), FastAPI (existing), Supabase PostgreSQL (existing), psycopg 3.x (new — LangGraph checkpointer)

---

## Scope note

This plan covers **Phase 0** (codebase audit) and **Phase 1** (LangGraph core + CHECKOUT + PAYMENT_LOG). Phases 2–6 from the design spec get separate plans when Phase 1 is stable.

---

## File Structure

### Phase 0 output
```
docs/superpowers/specs/2026-04-25-phase0-audit.md   categorized file map + design flaws
```

### Phase 1: New files
```
src/agent/
├── __init__.py                  exposes run_agent() + init_agent()
├── channel.py                   ChannelMessage + ChannelResponse dataclasses
├── state.py                     AgentState TypedDict (LangGraph requires TypedDict not dataclass)
├── config.py                    AGENT_INTENTS env var
├── checkpointer.py              MemorySaver (tests) + AsyncPostgresSaver (prod) factory
├── graph.py                     build_graph() + init_agent() + run_agent()
└── tools/
    ├── __init__.py
    ├── _base.py                 BaseToolResult
    ├── checkout.py              CHECKOUT tool — wraps _do_checkout from owner_handler.py
    └── payment.py               PAYMENT_LOG tool — wraps _do_log_payment_by_ids from account_handler.py

src/agent/nodes/
├── __init__.py
├── router.py                    fast path: yes/no → execute/cancel without LLM
├── intent.py                    wraps run_conversation_agent() → updates AgentState
├── clarify.py                   sends clarify_question as reply, ends turn
├── confirm.py                   formats action summary, asks yes/no
├── execute.py                   calls domain tool from registry
└── cancel.py                    clears state, sends cancelled message

tests/agent/
├── __init__.py
├── test_channel.py
├── test_state.py
├── test_graph_router.py         router node fast-path unit tests
├── test_graph_intent.py         intent node — mocks run_conversation_agent
├── test_graph_nodes.py          clarify, confirm, execute, cancel nodes
├── test_tools_checkout.py       CHECKOUT tool — mocks DB
├── test_tools_payment.py        PAYMENT_LOG tool — mocks DB
└── test_graph_e2e.py            full graph runs with MemorySaver (no DB)
```

### Phase 1: Modified files
```
requirements.txt                 + langgraph, langgraph-checkpoint-postgres, psycopg[binary,pool]
.env.template                    + AGENT_INTENTS, DATABASE_URL_PSYCOPG, LANGCHAIN_TRACING_V2
src/whatsapp/chat_api.py         insert agent routing block before line 845 (gatekeeper.route call)
main.py                          add init_agent() to lifespan startup block (after init_db)
```

---

## Phase 0

### Task 1: Produce the codebase audit doc

Output: `docs/superpowers/specs/2026-04-25-phase0-audit.md`. No code changes.

**Files:** Read all files in `src/`. Write audit doc.

- [ ] **Step 1: Run file inventory**

```bash
find src/ -name "*.py" | sort
```

- [ ] **Step 2: For each file, measure size and categorize**

Run these two commands per file to get line count and function count:
```bash
wc -l src/path/file.py
grep -c "^async def \|^def " src/path/file.py
```

Use these categories:
- `TOOL` — wraps a single confirmed business action; will get a tool wrapper in Phase 1
- `HANDLER` — current intent handler; logic extracted to TOOL after migration
- `SERVICE` — pure business logic (no HTTP, no bot formatting); called by HANDLERs and TOOLs
- `MODEL` — SQLAlchemy ORM or Pydantic schema; unchanged
- `UTILITY` — shared helpers (fuzzy match, date parse, room floor); unchanged
- `DEAD` — unused or superseded code; confirm no references with `grep -r "import.*filename\|from.*filename"`, then mark for deletion
- `CONFIG` — env/settings/migrations; unchanged
- `SCRIPT` — one-off admin scripts; should live in `scripts/` not `src/`
- `ROUTER` — routes requests to handlers/agents; modified in Phase 1

Flag for the design flaws section:
- Files > 300 lines: `wc -l src/path/file.py`
- HANDLERs that re-parse text: `grep -n "re\.search\|re\.fullmatch\|re\.match" src/whatsapp/handlers/*.py`
- HANDLERs that query DB directly (bypassing service layer): `grep -n "session\.execute\|session\.scalar" src/whatsapp/handlers/*.py`
- Functions > 80 lines: read each handler and count manually for the largest ones

- [ ] **Step 3: Write the audit doc**

Write `docs/superpowers/specs/2026-04-25-phase0-audit.md` with three sections:

**Section 1 — File catalog** (table: File | Category | Lines | Function count | Notes)

**Section 2 — Design flaws** (per-file findings with file:line references):
- Re-parsing in handlers (should use `src/whatsapp/conversation/state.py:parse()`)
- Direct DB queries in handlers (should go through service layer)
- Functions > 80 lines (candidates for splitting)
- Duplicate logic across files

**Section 3 — Deletion candidates** (DEAD files confirmed safe to remove after migration)

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-25-phase0-audit.md
git commit -m "docs: Phase 0 codebase audit — file map + design flaws"
```

---

## Phase 1

### Task 2: Add dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.template`

- [ ] **Step 1: Add packages to requirements.txt**

Open `requirements.txt`. After the `pydantic-ai[groq]>=0.2.14` line, add:

```
langgraph>=0.2.28
langgraph-checkpoint-postgres>=2.0.0
psycopg[binary,pool]>=3.1.0
```

- [ ] **Step 2: Install**

```bash
pip install "langgraph>=0.2.28" "langgraph-checkpoint-postgres>=2.0.0" "psycopg[binary,pool]>=3.1.0"
```

Verify:
```bash
python -c "import langgraph; import psycopg; print('ok')"
```

Expected output: `ok`

- [ ] **Step 3: Add env vars to .env.template**

Append to `.env.template`:

```
# Agent (LangGraph)
AGENT_INTENTS=CHECKOUT,PAYMENT_LOG
DATABASE_URL_PSYCOPG=postgresql://user:pass@host:5432/dbname

# LangSmith observability (optional — leave blank to disable tracing)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
```

- [ ] **Step 4: Add DATABASE_URL_PSYCOPG to your local .env**

Copy from `.env`'s `DATABASE_URL`. If it starts with `postgresql+asyncpg://`, strip `+asyncpg`:

```
# Example:
# DATABASE_URL=postgresql+asyncpg://postgres.xxx:pass@host:6543/postgres
# DATABASE_URL_PSYCOPG=postgresql://postgres.xxx:pass@host:6543/postgres
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.template
git commit -m "chore: add langgraph + psycopg3 deps for agent core"
```

---

### Task 3: AgentState + ChannelMessage

**Files:**
- Create: `src/agent/__init__.py`
- Create: `src/agent/channel.py`
- Create: `src/agent/state.py`
- Create: `tests/agent/__init__.py`
- Create: `tests/agent/test_channel.py`
- Create: `tests/agent/test_state.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agent/__init__.py` (empty file).

Create `tests/agent/test_channel.py`:

```python
from src.agent.channel import ChannelMessage, ChannelResponse


def test_channel_message_stores_fields():
    msg = ChannelMessage(user_id="wa:917845952289", channel="whatsapp", text="check out ravi")
    assert msg.user_id == "wa:917845952289"
    assert msg.channel == "whatsapp"
    assert msg.text == "check out ravi"
    assert msg.media_id is None


def test_channel_response_defaults():
    resp = ChannelResponse(text="Done.", intent="CHECKOUT", role="admin")
    assert resp.interactive_payload is None
```

Create `tests/agent/test_state.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/agent/test_channel.py tests/agent/test_state.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — modules don't exist yet.

- [ ] **Step 3: Create src/agent/__init__.py**

```python
# Populated in Task 7 when run_agent() is ready.
```

- [ ] **Step 4: Create src/agent/channel.py**

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChannelMessage:
    user_id: str        # "wa:917845952289" | "app:uuid-here"
    channel: str        # "whatsapp" | "app" | "voice"
    text: str
    media_id: Optional[str] = None
    media_type: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class ChannelResponse:
    text: str
    intent: str
    role: str
    interactive_payload: Optional[dict] = None
```

- [ ] **Step 5: Create src/agent/state.py**

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/agent/test_channel.py tests/agent/test_state.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agent/__init__.py src/agent/channel.py src/agent/state.py tests/agent/
git commit -m "feat(agent): add AgentState TypedDict + ChannelMessage dataclasses"
```

---

### Task 4: Router node (fast path — no LLM call)

**Files:**
- Create: `src/agent/config.py`
- Create: `src/agent/nodes/__init__.py`
- Create: `src/agent/nodes/router.py`
- Create: `tests/agent/test_graph_router.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agent/test_graph_router.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/agent/test_graph_router.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create src/agent/config.py**

```python
import os

AGENT_INTENTS: frozenset[str] = frozenset(
    i.strip()
    for i in os.getenv("AGENT_INTENTS", "CHECKOUT,PAYMENT_LOG").split(",")
    if i.strip()
)
```

- [ ] **Step 4: Create src/agent/nodes/__init__.py**

```python
from .router import router_node, route_decision

__all__ = ["router_node", "route_decision"]
```

- [ ] **Step 5: Create src/agent/nodes/router.py**

```python
"""
Router node — fast path for trivial mid-flow inputs.

If we're in confirm state (pending_tool set, no open clarify_question)
and the message is a plain yes/no, skip the LLM entirely.
Everything else goes to the intent node.
"""
from __future__ import annotations

from ..state import AgentState

_YES = frozenset({"yes", "y", "yeah", "yep", "ok", "okay", "confirm", "sure", "done"})
_NO  = frozenset({"no", "n", "nope", "cancel", "stop", "abort", "nevermind", "never mind"})


def route_decision(state: AgentState) -> str:
    msg = (state.get("last_message") or "").strip().lower().rstrip(".!?,;:")

    # Fast path only when: flow in progress AND no open clarify question
    if state.get("pending_tool") and not state.get("clarify_question"):
        if msg in _YES:
            return "execute"
        if msg in _NO:
            return "cancel"

    return "intent"


async def router_node(state: AgentState) -> dict:
    return {"turn_count": state.get("turn_count", 0) + 1}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/agent/test_graph_router.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agent/config.py src/agent/nodes/ tests/agent/test_graph_router.py
git commit -m "feat(agent): add router node — yes/no fast path, AGENT_INTENTS config"
```

---

### Task 5: Intent node

**Files:**
- Create: `src/agent/nodes/intent.py`
- Modify: `src/agent/nodes/__init__.py`
- Create: `tests/agent/test_graph_intent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agent/test_graph_intent.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/agent/test_graph_intent.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create src/agent/nodes/intent.py**

```python
"""
Intent node — calls run_conversation_agent() and maps its output into AgentState.

Does NOT replace conversation_agent.py — calls it and normalises the result.
"""
from __future__ import annotations

from langgraph.types import RunnableConfig

from ..state import AgentState

# Required entities per intent. All must be present before routing to confirm.
_REQUIRED: dict[str, set[str]] = {
    "CHECKOUT":    {"tenant_id"},
    "PAYMENT_LOG": {"tenant_id", "amount"},
}

# Maps intent name → tool name in execute registry
_TOOL_MAP = {
    "CHECKOUT":    "checkout",
    "PAYMENT_LOG": "payment",
}


def route_from_intent(state: AgentState) -> str:
    if state.get("clarify_question"):
        return "clarify"

    intent = state.get("intent")
    if not intent:
        return "__end__"

    required = _REQUIRED.get(intent, set())
    entities = state.get("entities") or {}
    missing  = required - set(entities.keys())

    if missing:
        return "clarify"

    if state.get("pending_tool"):
        return "confirm"

    return "__end__"


async def intent_node(state: AgentState, config: RunnableConfig) -> dict:
    from src.llm_gateway.agents.conversation_agent import run_conversation_agent

    session = config["configurable"]["session"]
    pg_id   = config["configurable"].get("pg_id", "")

    # Pass previous clarify question + user reply as context to the LLM
    pending_ctx = ""
    if state.get("clarify_question"):
        pending_ctx = (
            f"Bot asked: {state['clarify_question']}\n"
            f"User replied: {state['last_message']}"
        )

    result = await run_conversation_agent(
        message=state["last_message"],
        role=state["role"],
        phone=state["user_id"].replace("wa:", ""),
        pg_id=pg_id,
        session=session,
        chat_history="",
        pending_context=pending_ctx,
    )

    update: dict = {}

    if result.action == "classify" and result.intent:
        merged = dict(state.get("entities") or {})
        merged.update(result.entities or {})
        update["intent"]           = result.intent
        update["entities"]         = merged
        update["clarify_question"] = None
        if result.intent in _TOOL_MAP:
            update["pending_tool"] = _TOOL_MAP[result.intent]

    elif result.action in ("clarify", "ask_options") and result.reply:
        update["clarify_question"] = result.reply
        update["reply"]            = result.reply

    elif result.action == "converse" and result.reply:
        update["reply"]  = result.reply
        update["intent"] = "CONVERSE"

    return update
```

- [ ] **Step 4: Update src/agent/nodes/__init__.py**

```python
from .router import router_node, route_decision
from .intent import intent_node, route_from_intent

__all__ = ["router_node", "route_decision", "intent_node", "route_from_intent"]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/agent/test_graph_intent.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent/nodes/intent.py src/agent/nodes/__init__.py tests/agent/test_graph_intent.py
git commit -m "feat(agent): add intent node — wraps run_conversation_agent into LangGraph"
```

---

### Task 6: Clarify, Confirm, Execute, Cancel nodes

**Files:**
- Create: `src/agent/nodes/clarify.py`
- Create: `src/agent/nodes/confirm.py`
- Create: `src/agent/nodes/execute.py`
- Create: `src/agent/nodes/cancel.py`
- Create: `tests/agent/test_graph_nodes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agent/test_graph_nodes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/agent/test_graph_nodes.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create src/agent/nodes/clarify.py**

```python
"""
Clarify node — sends the clarifying question (already set by intent node) as the reply.
Ends the turn. Next turn: router sees clarify_question is set → routes to intent.
"""
from __future__ import annotations

from langgraph.types import RunnableConfig
from ..state import AgentState


async def clarify_node(state: AgentState, config: RunnableConfig) -> dict:
    question = state.get("clarify_question") or "Could you clarify?"
    return {"reply": question}
```

- [ ] **Step 4: Create src/agent/nodes/confirm.py**

```python
"""
Confirm node — formats a human-readable summary of the proposed action.
Asks the user to reply yes/no. Ends the turn.
Next turn: router sees pending_tool + no clarify_question → yes→execute, no→cancel.
"""
from __future__ import annotations

from langgraph.types import RunnableConfig
from ..state import AgentState

_TEMPLATES: dict[str, str] = {
    "CHECKOUT": (
        "Checking out *{tenant_name}* from room *{room}* on *{checkout_date}*.\n\n"
        "Reply *yes* to confirm or *no* to cancel."
    ),
    "PAYMENT_LOG": (
        "Logging payment of *₹{amount}* for *{tenant_name}* (room {room}) "
        "via *{mode}* for *{month}*.\n\n"
        "Reply *yes* to confirm or *no* to cancel."
    ),
}

_FALLBACK = (
    "Proceeding with: {intent}\n\n"
    "Reply *yes* to confirm or *no* to cancel."
)


async def confirm_node(state: AgentState, config: RunnableConfig) -> dict:
    intent   = state.get("intent") or ""
    entities = state.get("entities") or {}
    template = _TEMPLATES.get(intent, _FALLBACK)
    try:
        reply = template.format(intent=intent, **entities)
    except KeyError:
        reply = _FALLBACK.format(intent=intent)
    return {"reply": reply, "clarify_question": None}
```

- [ ] **Step 5: Create src/agent/nodes/cancel.py**

```python
"""Cancel node — clears pending flow state and tells the user."""
from __future__ import annotations

from langgraph.types import RunnableConfig
from ..state import AgentState


async def cancel_node(state: AgentState, config: RunnableConfig) -> dict:
    return {
        "intent": None,
        "entities": {},
        "pending_tool": None,
        "clarify_question": None,
        "reply": "Action cancelled. What else can I help with?",
    }
```

- [ ] **Step 6: Create src/agent/nodes/execute.py**

```python
"""
Execute node — looks up the confirmed tool in the registry and calls it.
Tools are registered by importing their module (see end of this file).
"""
from __future__ import annotations

from langgraph.types import RunnableConfig
from ..state import AgentState

_TOOL_REGISTRY: dict[str, any] = {}


def register_tool(name: str, fn) -> None:
    _TOOL_REGISTRY[name] = fn


async def execute_node(state: AgentState, config: RunnableConfig) -> dict:
    tool_name = state.get("pending_tool")
    if not tool_name or tool_name not in _TOOL_REGISTRY:
        return {
            "reply": f"Internal error: tool '{tool_name}' not registered. Please try again.",
            "pending_tool": None,
            "error": f"tool_not_found:{tool_name}",
        }

    session  = config["configurable"]["session"]
    tool_fn  = _TOOL_REGISTRY[tool_name]
    entities = state.get("entities") or {}

    try:
        result = await tool_fn(entities, session)
        return {
            "reply": result.reply,
            "pending_tool": None,
            "intent": None,
            "entities": {},
            "clarify_question": None,
            "error": None,
        }
    except Exception as exc:
        return {
            "reply": f"Something went wrong: {exc}. Please try again.",
            "pending_tool": None,
            "error": str(exc),
        }


def _register_all() -> None:
    from src.agent.tools import checkout as _ct
    from src.agent.tools import payment as _pt
    register_tool("checkout", _ct.run_checkout)
    register_tool("payment",  _pt.run_payment)


_register_all()
```

- [ ] **Step 7: Update src/agent/nodes/__init__.py**

```python
from .router  import router_node, route_decision
from .intent  import intent_node, route_from_intent
from .clarify import clarify_node
from .confirm import confirm_node
from .execute import execute_node, register_tool
from .cancel  import cancel_node

__all__ = [
    "router_node", "route_decision",
    "intent_node", "route_from_intent",
    "clarify_node",
    "confirm_node",
    "execute_node", "register_tool",
    "cancel_node",
]
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
pytest tests/agent/test_graph_nodes.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add src/agent/nodes/ tests/agent/test_graph_nodes.py
git commit -m "feat(agent): add clarify, confirm, execute, cancel nodes"
```

---

### Task 7: Assemble the graph + checkpointer

**Files:**
- Create: `src/agent/checkpointer.py`
- Create: `src/agent/graph.py`
- Modify: `src/agent/__init__.py`

- [ ] **Step 1: Create src/agent/checkpointer.py**

```python
"""
Checkpointer factory.
Production: AsyncPostgresSaver with psycopg3 pool (Supabase PostgreSQL).
Tests: MemorySaver (in-memory, no DB required).
"""
from __future__ import annotations

import os

from langgraph.checkpoint.memory import MemorySaver


def make_memory_checkpointer() -> MemorySaver:
    """For tests — no DB required."""
    return MemorySaver()


async def make_postgres_checkpointer():
    """
    For production (FastAPI lifespan startup).
    Requires DATABASE_URL_PSYCOPG in environment.
    Returns (checkpointer, pool) — caller must hold pool to close on shutdown.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    db_url = os.environ["DATABASE_URL_PSYCOPG"]
    pool = AsyncConnectionPool(db_url, open=False, max_size=5)
    await pool.open()
    cp = AsyncPostgresSaver(pool)
    await cp.setup()    # creates langgraph_checkpoints table if not exists
    return cp, pool
```

- [ ] **Step 2: Create src/agent/graph.py**

```python
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
```

- [ ] **Step 3: Update src/agent/__init__.py**

```python
from .channel import ChannelMessage, ChannelResponse
from .graph   import init_agent, run_agent

__all__ = ["ChannelMessage", "ChannelResponse", "init_agent", "run_agent"]
```

- [ ] **Step 4: Run all agent tests so far**

```bash
pytest tests/agent/ -v
```

Expected: all previously passing tests still PASS (no regressions from graph assembly).

- [ ] **Step 5: Commit**

```bash
git add src/agent/checkpointer.py src/agent/graph.py src/agent/__init__.py
git commit -m "feat(agent): assemble LangGraph graph with checkpointer factory + run_agent()"
```

---

### Task 8: Tool base types

**Files:**
- Create: `src/agent/tools/__init__.py`
- Create: `src/agent/tools/_base.py`

- [ ] **Step 1: Create src/agent/tools/__init__.py**

```python
# Tool modules register themselves when imported via execute.py:_register_all()
```

- [ ] **Step 2: Create src/agent/tools/_base.py**

```python
from pydantic import BaseModel


class BaseToolResult(BaseModel):
    success: bool
    reply: str    # human-readable summary sent back to user
```

- [ ] **Step 3: Commit**

```bash
git add src/agent/tools/
git commit -m "feat(agent): add tool base types"
```

---

### Task 9: CHECKOUT tool

**Files:**
- Create: `src/agent/tools/checkout.py`
- Create: `tests/agent/test_tools_checkout.py`

- [ ] **Step 1: Read the existing checkout execution logic**

Read these two files before writing the wrapper:

```bash
cat src/whatsapp/handlers/owner_handler.py | grep -n "def _do_checkout\|async def _do_checkout" | head -5
```

Then read the `_do_checkout` function body (or equivalent). You need to find:
- Exact function name
- Exact parameters (tenant_id? tenancy_id? checkout_date format?)
- What it returns (a string reply, or a dict, or None?)

Also read `src/whatsapp/conversation/handlers/checkout.py` lines 57–end to see what it does after disambiguation resolves.

- [ ] **Step 2: Write failing tests**

Create `tests/agent/test_tools_checkout.py`:

```python
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch
from src.agent.tools.checkout import run_checkout, CheckoutInput


@pytest.mark.asyncio
async def test_checkout_returns_success_reply():
    with patch("src.agent.tools.checkout._execute_checkout",
               new=AsyncMock(return_value="Ravi Sharma checked out. Balance: ₹0.")):
        result = await run_checkout(
            {"tenant_id": 42, "checkout_date": "2026-04-25", "tenant_name": "Ravi Sharma", "room": "305"},
            AsyncMock(),
        )
    assert result.success is True
    assert "Ravi Sharma" in result.reply or "checked out" in result.reply.lower()


@pytest.mark.asyncio
async def test_checkout_wraps_exception_as_failure():
    with patch("src.agent.tools.checkout._execute_checkout",
               side_effect=ValueError("Tenant not found")):
        result = await run_checkout(
            {"tenant_id": 99, "checkout_date": "2026-04-25", "tenant_name": "Unknown", "room": ""},
            AsyncMock(),
        )
    assert result.success is False
    assert "Tenant not found" in result.reply


def test_checkout_input_validates():
    inp = CheckoutInput(tenant_id=42, checkout_date="2026-04-25", tenant_name="Ravi", room="305")
    assert inp.tenant_id == 42
    assert inp.checkout_date == "2026-04-25"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/agent/test_tools_checkout.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Create src/agent/tools/checkout.py**

```python
"""
CHECKOUT tool — wraps the checkout execution logic from owner_handler.py.

The graph has already handled disambiguation (clarify node) and confirmation
(confirm node). By the time this tool is called, tenant_id and checkout_date
are resolved and the user has confirmed.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ._base import BaseToolResult


class CheckoutInput(BaseModel):
    tenant_id: int
    checkout_date: str    # ISO date "YYYY-MM-DD"
    tenant_name: str = ""
    room: str = ""


class CheckoutResult(BaseToolResult):
    pass


async def _execute_checkout(
    tenant_id: int,
    checkout_date: str,
    session: AsyncSession,
) -> str:
    """
    Calls the existing checkout execution function from owner_handler.py.

    BEFORE shipping: read src/whatsapp/handlers/owner_handler.py, find
    _do_checkout (or the function that writes checkout_date to Tenancy and
    marks the bed vacant), and update this call to match the exact signature.
    """
    from src.whatsapp.handlers.owner_handler import _do_checkout
    reply = await _do_checkout(
        tenant_id=tenant_id,
        checkout_date=checkout_date,
        session=session,
    )
    return reply or "Checkout recorded."


async def run_checkout(entities: dict[str, Any], session: AsyncSession) -> CheckoutResult:
    fields = {k: v for k, v in entities.items() if k in CheckoutInput.model_fields}
    inp = CheckoutInput(**fields)
    try:
        reply = await _execute_checkout(inp.tenant_id, inp.checkout_date, session)
        return CheckoutResult(success=True, reply=reply)
    except Exception as exc:
        return CheckoutResult(success=False, reply=f"Checkout failed: {exc}")
```

**After creating this file:** Open `src/whatsapp/handlers/owner_handler.py`, search for the checkout execution function (`_do_checkout` or equivalent). Update `_execute_checkout` above to match its exact name and parameter list.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/agent/test_tools_checkout.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent/tools/checkout.py src/agent/tools/_base.py tests/agent/test_tools_checkout.py
git commit -m "feat(agent): add CHECKOUT tool wrapper"
```

---

### Task 10: PAYMENT_LOG tool

**Files:**
- Create: `src/agent/tools/payment.py`
- Create: `tests/agent/test_tools_payment.py`

- [ ] **Step 1: Read the existing payment execution logic**

```bash
grep -n "def _do_log_payment_by_ids\|async def _do_log_payment_by_ids" src/whatsapp/handlers/account_handler.py
```

Read that function. Note the exact signature (parameters: tenant_id, amount, mode, month, session? or different names?).

Also read `src/whatsapp/conversation/handlers/payment_log.py` lines 60–end to see what happens after disambiguation resolves the tenant choice.

- [ ] **Step 2: Write failing tests**

Create `tests/agent/test_tools_payment.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from src.agent.tools.payment import run_payment, PaymentInput


@pytest.mark.asyncio
async def test_payment_returns_success_reply():
    with patch("src.agent.tools.payment._execute_payment",
               new=AsyncMock(return_value="Payment of ₹5000 logged for Ravi.")):
        result = await run_payment(
            {"tenant_id": 42, "amount": 5000.0, "mode": "UPI",
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
            {"tenant_id": 99, "amount": 1000.0, "mode": "Cash",
             "month": "April 2026", "tenant_name": "X", "room": ""},
            AsyncMock(),
        )
    assert result.success is False
    assert "Tenant not found" in result.reply


def test_payment_input_validates():
    inp = PaymentInput(tenant_id=42, amount=5000.0, mode="UPI",
                       month="April 2026", tenant_name="Ravi", room="305")
    assert inp.amount == 5000.0
    assert inp.mode == "UPI"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/agent/test_tools_payment.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Create src/agent/tools/payment.py**

```python
"""
PAYMENT_LOG tool — wraps _do_log_payment_by_ids from account_handler.py.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ._base import BaseToolResult


class PaymentInput(BaseModel):
    tenant_id: int
    amount: float
    mode: str = "Cash"
    month: str = ""
    tenant_name: str = ""
    room: str = ""


class PaymentResult(BaseToolResult):
    pass


async def _execute_payment(
    tenant_id: int,
    amount: float,
    mode: str,
    month: str,
    session: AsyncSession,
) -> str:
    """
    Calls the existing payment logging function from account_handler.py.

    BEFORE shipping: read src/whatsapp/handlers/account_handler.py,
    find _do_log_payment_by_ids, and update this call to match its
    exact parameter names and types.
    """
    from src.whatsapp.handlers.account_handler import _do_log_payment_by_ids
    reply = await _do_log_payment_by_ids(
        tenant_id=tenant_id,
        amount=amount,
        mode=mode,
        month=month,
        session=session,
    )
    return reply or f"₹{amount:.0f} logged."


async def run_payment(entities: dict[str, Any], session: AsyncSession) -> PaymentResult:
    fields = {k: v for k, v in entities.items() if k in PaymentInput.model_fields}
    inp = PaymentInput(**fields)
    try:
        reply = await _execute_payment(inp.tenant_id, inp.amount, inp.mode, inp.month, session)
        return PaymentResult(success=True, reply=reply)
    except Exception as exc:
        return PaymentResult(success=False, reply=f"Payment log failed: {exc}")
```

**After creating this file:** Open `src/whatsapp/handlers/account_handler.py`, find `_do_log_payment_by_ids`, and update `_execute_payment` above to match its exact signature.

- [ ] **Step 5: Update PAYMENT_LOG in intent.py tool_map** (it's already there — verify)

```bash
grep "PAYMENT_LOG" src/agent/nodes/intent.py
```

Expected output: `"PAYMENT_LOG": "payment"` in `_TOOL_MAP`.

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/agent/test_tools_payment.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agent/tools/payment.py tests/agent/test_tools_payment.py
git commit -m "feat(agent): add PAYMENT_LOG tool wrapper"
```

---

### Task 11: E2E graph tests with MemorySaver

**Files:**
- Create: `tests/agent/test_graph_e2e.py`

- [ ] **Step 1: Create tests/agent/test_graph_e2e.py**

```python
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

    entities = {"tenant_id": 42, "tenant_name": "Ravi Sharma", "room": "305", "checkout_date": "2026-04-25"}
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
    Turn 1: 'check out ravi' → clarify (ambiguous name)
    Turn 2: 'sharma'         → intent resolves → confirm
    Turn 3: 'yes'            → execute → success
    """
    g   = _graph()
    cfg = _cfg("wa:test_clarify")

    side_effects = [
        _clarify("Found Ravi Kumar (201) and Ravi Sharma (305). Which one?"),
        _classify("CHECKOUT", {"tenant_id": 42, "tenant_name": "Ravi Sharma",
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

    entities = {"tenant_id": 42, "tenant_name": "Ravi", "room": "201", "checkout_date": "2026-04-25"}
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

    entities = {"tenant_id": 42, "tenant_name": "Ravi", "room": "305",
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
```

- [ ] **Step 2: Run the e2e tests**

```bash
pytest tests/agent/test_graph_e2e.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 3: Run the full agent suite**

```bash
pytest tests/agent/ -v
```

Expected: all tests PASS. Count should be ≥ 23.

- [ ] **Step 4: Commit**

```bash
git add tests/agent/test_graph_e2e.py
git commit -m "test(agent): add e2e graph tests — happy path, clarification, cancel, payment"
```

---

### Task 12: Wire agent into chat_api.py + main.py

**Files:**
- Modify: `src/whatsapp/chat_api.py`
- Modify: `main.py`

- [ ] **Step 1: Add imports to chat_api.py**

Read `src/whatsapp/chat_api.py` lines 40–45 to find line 42 where `_USE_PYDANTIC_AGENTS` is set.

After that line, add:

```python
from src.agent.config import AGENT_INTENTS
from src.agent.channel import ChannelMessage as _AgentChannelMessage
```

- [ ] **Step 2: Insert agent routing block before gatekeeper.route() call**

Read lines 840–848 of `src/whatsapp/chat_api.py`. Line 845 is:
```python
reply = await route(intent, intent_result.entities, ctx, message, session)
```

Immediately **before** that line (after the media_id block that ends on line ~843), insert:

```python
    # ── LangGraph agent path ───────────────────────────────────────────────
    if _USE_PYDANTIC_AGENTS and intent in AGENT_INTENTS and ctx.role in ("admin", "owner", "receptionist"):
        try:
            from src.agent.graph import run_agent
            pg_id = await _resolve_pg_id(session)
            ch_msg = _AgentChannelMessage(
                user_id=f"wa:{phone}",
                channel="whatsapp",
                text=message,
                media_id=body.media_id,
                media_type=body.media_type,
            )
            agent_reply = await run_agent(
                channel_msg=ch_msg,
                session=session,
                pg_id=pg_id or "",
                role=ctx.role,
                name=ctx.name or "",
            )
            await _log(session, phone, message, ctx.role, intent, agent_reply)
            await session.commit()
            return OutboundReply(reply=agent_reply, intent=intent, role=ctx.role)
        except Exception as _agent_exc:
            import logging as _ag_log
            _ag_log.getLogger(__name__).error(
                f"[agent] {intent} failed: {_agent_exc}", exc_info=True
            )
            # Fall through to gatekeeper — user always gets a reply
```

- [ ] **Step 3: Add agent initialization to main.py lifespan**

Read `main.py` lines 57–80 (the lifespan startup block). After the `init_db` call and before the `yield`, add:

```python
    # Initialize LangGraph agent
    import os as _os
    _test_mode = _os.getenv("TEST_MODE", "0") == "1"
    from src.agent.graph import init_agent
    await init_agent(test_mode=_test_mode)
    logger.info("✓ Agent graph initialized")
```

- [ ] **Step 4: Start the server and do a smoke test**

```bash
TEST_MODE=1 USE_PYDANTIC_AGENTS=true AGENT_INTENTS=CHECKOUT,PAYMENT_LOG venv/Scripts/python main.py
```

In another terminal:

```bash
curl -s -X POST http://localhost:8000/api/whatsapp/process \
  -H "Content-Type: application/json" \
  -d '{"phone":"917845952289","message":"checkout ravi","message_id":"smoke-001"}' | python -m json.tool
```

Expected: JSON response with a `reply` field containing a question or confirm prompt (not an error, not empty).

- [ ] **Step 5: Verify fallback — non-agent intent still works**

```bash
curl -s -X POST http://localhost:8000/api/whatsapp/process \
  -H "Content-Type: application/json" \
  -d '{"phone":"917845952289","message":"show me rent report","message_id":"smoke-002"}' | python -m json.tool
```

Expected: normal report reply from gatekeeper (agent did not intercept — `intent` will be `REPORT`, not in `AGENT_INTENTS`).

- [ ] **Step 6: Commit**

```bash
git add src/whatsapp/chat_api.py main.py
git commit -m "feat(agent): wire LangGraph agent into WhatsApp webhook — AGENT_INTENTS routing"
```

---

### Task 13: Golden suite validation + push

- [ ] **Step 1: Run golden suite with agent DISABLED (establish baseline)**

```bash
USE_PYDANTIC_AGENTS=false python tests/eval_golden.py 2>&1 | tail -10
```

Note the pass rate. Target: ≥ 95%.

- [ ] **Step 2: Run golden suite with agent ENABLED for CHECKOUT + PAYMENT_LOG**

```bash
TEST_MODE=1 USE_PYDANTIC_AGENTS=true AGENT_INTENTS=CHECKOUT,PAYMENT_LOG python tests/eval_golden.py 2>&1 | tail -10
```

Expected: pass rate ≥ 95%. If CHECKOUT or PAYMENT_LOG cases regress, check:
- Is the agent fallback (try/except in Task 12 Step 2) working?
- Does the tool `_execute_checkout` or `_execute_payment` have the right function signature?

- [ ] **Step 3: Run full agent unit suite one final time**

```bash
pytest tests/agent/ -v --tb=short 2>&1 | tail -20
```

Expected: all PASS.

- [ ] **Step 4: Push to GitHub**

```bash
git push origin master
```

- [ ] **Step 5: Update VPS .env (DO NOT deploy yet)**

SSH to VPS and add to `/opt/pg-accountant/.env`:

```
AGENT_INTENTS=CHECKOUT,PAYMENT_LOG
DATABASE_URL_PSYCOPG=<same as DATABASE_URL but without +asyncpg if present>
```

Leave `USE_PYDANTIC_AGENTS=false` on VPS. Local validation first, 48h soak, then flip to true.

- [ ] **Step 6: Update pending tasks**

Update `memory/project_pending_tasks.md`:
- Mark Phase 0 audit complete
- Mark Phase 1 LangGraph core complete
- Add: "Enable USE_PYDANTIC_AGENTS=true on VPS after 48h local soak (CHECKOUT + PAYMENT_LOG)"
- Add: "Write Phase 2 plan (self-learning system — 3-tier)"
- Add: "Write Phase 3 plan (PWA channel adapter)"

```bash
git add memory/project_pending_tasks.md
git commit -m "docs: update pending tasks — Phase 0+1 complete, Phase 2+3 queued"
git push origin master
```

---

## Self-Review

### Spec coverage

| Spec section | Tasks that implement it |
|---|---|
| 3-layer architecture (§1) | Tasks 3, 7, 12 |
| LangGraph + PydanticAI stack (§2) | Tasks 3, 5, 7 |
| Conversation state machine (§3) | Tasks 4, 5, 6, 7 |
| Self-learning system (§4) | Phase 2 — separate plan |
| Phase 0 audit (§5) | Task 1 |
| Strangler fig migration (§6) | Task 12 |
| Channel adapters / ChannelMessage (§7) | Tasks 3, 12 |
| Cost = ₹0 (§8) | MemorySaver in dev, existing Supabase in prod |
| Phase roadmap (§9) | This plan = Phase 0 + 1 only |

**Gaps (intentional deferrals):** Self-learning (§4), PWA adapter (Phase 3), Voice (Phase 4) — separate plans.

### Type consistency

- `AgentState["pending_tool"]` — set in Task 5 (`intent_node`), read in Task 4 (`route_decision`), cleared in Task 6 (`execute_node`, `cancel_node`) — consistent.
- `route_from_intent` returns `"__end__"` — mapped to `END` in `build_graph()` conditional edges — consistent.
- `run_checkout` and `run_payment` both accept `dict[str, Any]` — consistent with `execute_node` passing `state.get("entities")`.
- `ChannelMessage.user_id` uses `"wa:"` prefix — set in Task 3, stripped in Task 5 (`phone = state["user_id"].replace("wa:", "")`) — consistent.
- `_TOOL_REGISTRY["checkout"]` set by `_register_all()` in `execute.py` — matches `pending_tool = "checkout"` set by `_TOOL_MAP` in `intent.py` — consistent.
- `_TOOL_REGISTRY` referenced in e2e tests (Task 11) with `patch("src.agent.nodes.execute._TOOL_REGISTRY", ...)` — matches the dict name in `execute.py` (Task 6) — consistent.

### No-placeholder check

- Tasks 9 and 10 both contain "BEFORE shipping: read X and update" instructions — these are genuine read-first steps, not placeholders. The function bodies are complete skeletons that will work once the engineer updates the import to match the real signature.
