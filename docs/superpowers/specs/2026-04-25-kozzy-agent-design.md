# Kozzy Agent — Full Design Spec

**Date:** 2026-04-25  
**Status:** Approved — ready for implementation planning  
**Author:** Kiran + Claude (brainstorming session)

---

## Problem Statement

The current bot has three compounding failures:

1. **State loss mid-conversation** — PendingAction is reloaded fresh per request; if the LLM doesn't save extracted entities back to `PendingAction.context`, the next turn starts blind.
2. **Entity detection failures** — regex handles 97% of classification but can't resolve ambiguous names ("Ravi" → which Ravi?) or recover from mismatches.
3. **No conversational recovery** — when something goes wrong ("no that's the wrong tenant"), the bot dead-ends instead of asking a follow-up question.

Root cause: the system is a classifier, not a conversational agent. It classifies intents and delegates to handlers, but there is no shared state machine maintaining context across turns.

---

## Design Overview

Three-layer architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                    DELIVERY LAYER                           │
│   WhatsApp (Meta API) │ PWA (Next.js) │ Voice (future)      │
│   channel adapters — normalize to ChannelMessage            │
└─────────────────────────────────┬──────────────────────────┘
                                  │ ChannelMessage
┌─────────────────────────────────▼──────────────────────────┐
│                    AGENT CORE                               │
│   LangGraph graph (state machine)                           │
│   ├── Router node: trivial inputs handled locally           │
│   ├── Intent node: PydanticAI + Groq LLM classifies         │
│   ├── Clarify node: LLM asks follow-up, saves to checkpoint │
│   ├── Confirm node: shows plan to user, waits for yes/no    │
│   └── Execute node: calls domain tools, saves to DB         │
│   Checkpoint store: Supabase PostgreSQL (existing)          │
│   State keyed by: user_id (not phone — channel-agnostic)    │
└─────────────────────────────────┬──────────────────────────┘
                                  │ tool calls (typed)
┌─────────────────────────────────▼──────────────────────────┐
│                    DOMAIN PLUGINS                           │
│   owner_tools.py  │ account_tools.py │ tenant_tools.py      │
│   Existing handler logic, wrapped as PydanticAI tools       │
│   Returns structured results — LLM reads, formats reply     │
└─────────────────────────────────────────────────────────────┘
```

---

## Section 1 — Three-Layer Architecture

### Delivery Layer

Each channel has a thin adapter that normalizes inbound messages into a `ChannelMessage` struct and sends `ChannelResponse` back. No business logic lives here.

```python
@dataclass
class ChannelMessage:
    user_id: str        # "wa:917845952289" | "app:uuid" | "voice:uuid"
    channel: str        # "whatsapp" | "app" | "voice"
    text: str
    media_id: str | None
    media_type: str | None
    raw: dict           # original payload, for debugging
```

The WhatsApp adapter is the existing `chat_api.py` webhook, refactored to output `ChannelMessage` instead of calling handlers directly. The PWA adapter is a REST endpoint on the existing FastAPI server. The Voice adapter is a future WebSocket endpoint.

**Key constraint:** state is keyed by `user_id`, not channel or phone number. A conversation started on WhatsApp can continue on the PWA without losing context.

### Agent Core (LangGraph)

LangGraph is a Python library. It runs inside the existing FastAPI process — no new server, no new hosting, no additional cost.

The graph is instantiated once at startup and shared across requests. Per-conversation state is persisted in the existing Supabase PostgreSQL database using LangGraph's built-in `AsyncPostgresSaver` checkpointer. Thread ID = `user_id`.

Graph nodes (details in Section 3):
- `router` — fast path for trivial inputs (yes/no/numbers in mid-flow)
- `intent` — LLM classifies intent, extracts entities
- `clarify` — LLM asks follow-up question when entity is ambiguous or missing
- `confirm` — shows proposed action to user, waits for confirmation
- `execute` — calls domain tool, writes to DB, returns result
- `learn` — records successful interaction to learning store (Section 4)

**LangGraph serializes graph execution per user_id.** Two concurrent WhatsApp messages from the same user queue — they never run simultaneously. This eliminates the race condition on Tenancy mutations (existing bug in `project_pending_tasks.md`).

### Domain Plugins

Existing handler logic becomes typed tools. The logic inside `checkout_tenant()`, `log_payment()`, `get_tenant_dues()` is untouched — it's just wrapped with a `@tool` decorator and a Pydantic input/output model.

```python
class CheckoutInput(BaseModel):
    tenant_id: int
    checkout_date: date
    final_balance: float

class CheckoutResult(BaseModel):
    success: bool
    receipt_text: str
    sheet_updated: bool

@tool
async def checkout_tenant(inp: CheckoutInput, db: AsyncSession) -> CheckoutResult:
    # existing owner_handler.py checkout logic, unchanged
    ...
```

The LLM never calls tools directly. The Execute node calls the tool function; the LLM only picks which tool and what parameters.

**Multi-industry extensibility:** tools live in plugin directories (`plugins/pg/`, `plugins/nail_salon/` in the future). The graph loads tools from the active plugin at startup via a Python registry — no MCP needed, no external protocol, just Python imports.

---

## Section 2 — LangGraph + PydanticAI Stack

### Component roles (no overlap)

| Component | Role |
|---|---|
| **LangGraph** | Graph container. Manages state machine, node routing, checkpointing, serialization per user. |
| **PydanticAI** | Type safety on LLM I/O. Wraps the LLM call in each node, enforces structured output. |
| **Groq LLM** | Inference. Lives inside graph nodes. Swappable via one config line. |
| **Supabase PostgreSQL** | Checkpoint store (LangGraph) + business data (existing). |

### LLM placement

The LLM is called inside graph nodes, not at the entry point. Flow:

```
ChannelMessage → LangGraph loads checkpoint (knows current state)
    │
    ├─ if mid-flow + trivial input (yes/no/1/2/3):
    │      → Router node handles locally, no LLM call (~10% savings)
    │
    └─ if new message or ambiguous:
           → Intent node: LLM(message + checkpoint context) → IntentResult
           → Clarify node (if needed): LLM(context + question) → ClarifyResult
           → Confirm node: format plan as text, send to user
           → Execute node: call domain tool, write DB
           → Learn node: record to examples store
```

### Model configuration

```python
# src/llm_gateway/config.py
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "groq" | "google" | "cerebras"
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
```

Swapping from Groq to Gemma 4 is one `.env` change, no code change.

### Fallback chain

Groq (315 tokens/sec, 6K tokens/min free) → Cerebras (60K tokens/min free) on rate-limit.

```python
async def call_llm(prompt: str) -> str:
    try:
        return await groq_client.complete(prompt)
    except RateLimitError:
        return await cerebras_client.complete(prompt)
```

### Observability

LangSmith (LangChain's trace tool): 5K free traces/month, enabled with one env var:
```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
```
Every graph execution is a trace: inputs, outputs, node timings, LLM calls. Disabled in production until Kiran enables it — zero cost by default.

---

## Section 3 — Conversation State Machine

### States

```
IDLE
  │ user sends any message
  ▼
INTENT_RESOLVED          ← LLM has identified intent + partial entities
  │ if entities missing or ambiguous
  ▼
CLARIFYING               ← bot asked a follow-up question, waiting for answer
  │ user answers
  ▼
ENTITIES_COLLECTED       ← all required entities confirmed
  │ automatic transition
  ▼
CONFIRMED                ← bot showed plan ("Will check out Ravi on May 1. Confirm?")
  │ user says yes
  ▼
EXECUTED                 ← tool ran, DB written, reply sent
  │ automatic transition
  ▼
IDLE
```

At any state, user can say "cancel" → back to IDLE, pending cleared.

### Checkpoint structure

```python
@dataclass
class AgentState:
    user_id: str
    channel: str
    role: str                    # admin | owner | tenant | lead
    name: str
    intent: str | None           # resolved intent name
    entities: dict               # collected so far {"tenant_id": 42, ...}
    pending_tool: str | None     # tool waiting to execute
    clarify_question: str | None # last question asked
    state: ConversationState     # current node
    turn_count: int              # guard against infinite clarification loops
    last_updated: datetime
```

This replaces `PendingAction` for agent-routed flows. Legacy `PendingAction` remains for regex-handled flows during the migration window.

### Clarification loop

The LLM asks at most 3 clarifying questions per flow. After 3, it says "I'm having trouble understanding — can you start over?" and resets to IDLE. This prevents infinite loops on broken inputs.

When a user sends a message that contradicts a previously collected entity ("no, it's Ravi Sharma not Ravi Kumar"), the Clarify node detects the correction and re-runs entity resolution with the updated context — it does not dead-end.

### Example flows

**Happy path — checkout:**
```
User: "check out Ravi"
  → Intent: CHECKOUT, entity: name="Ravi"
  → Clarify: "Found Ravi Kumar (room 201) and Ravi Sharma (305). Which one?"
User: "sharma"
  → Entities: tenant_id=42 (Ravi Sharma, 305)
  → Confirm: "Checking out Ravi Sharma from room 305 today (Apr 25). Confirm?"
User: "yes"
  → Execute: checkout_tenant(42, date.today())
  → Reply: "Done. Ravi Sharma checked out. Balance: ₹0."
```

**Correction mid-flow:**
```
User: "check out ravi"
  → Clarify: "Found Ravi Kumar (201). Checkout today?"
User: "no the one in 305"
  → [CORRECTION DETECTED — re-run entity resolution]
  → Entities: tenant_id=42 (Ravi Sharma, 305)
  → Confirm: "Checking out Ravi Sharma from room 305 today. Confirm?"
```

---

## Section 4 — Self-Learning System (3-Tier)

The agent learns from its own successful interactions. No external annotation pipeline needed.

### Tier 1 — Silent auto-save

**Trigger:** User confirms and flow executes successfully.  
**Action:** Save (message, intent, entities, outcome) to `agent_examples` table.  
**No user interaction.** ~80% of interactions, fully automated.

```sql
CREATE TABLE agent_examples (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    message TEXT NOT NULL,
    intent VARCHAR NOT NULL,
    entities JSONB NOT NULL,
    outcome JSONB NOT NULL,
    approved BOOLEAN DEFAULT TRUE,  -- auto-approved for Tier 1
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

These become few-shot examples in the system prompt on the next similar query.

### Tier 2 — Explicit ask

**Trigger:** Agent encounters a message pattern it hasn't seen before (similarity score < threshold against existing examples).  
**Action:** After successful execution, agent asks: *"That was a new kind of request for me. Should I remember how to handle this for next time?"*  
**User replies yes/no.** Saved with `approved = user_response`.

Example: Kiran asks for a custom report format never seen before. Bot handles it, then asks permission to remember.

### Tier 3 — Weekly digest

**Trigger:** Sunday 9 AM (cron, existing APScheduler).  
**Action:** WhatsApp message to Kiran: summary of the week's new/flagged examples with approve/reject buttons.  

```
"This week I learned 3 new patterns:
1. 'give me the PnL for last month' → REPORT intent ✓
2. 'which rooms are free tomorrow' → AVAILABILITY intent ✓
3. 'add maintenance charge for floor 2' → ??? (I'm unsure)

Reply 1/2/3 to reject any, or 'all ok' to approve."
```

Rejected examples are soft-deleted (`approved = false`). The learning store is the ground truth for few-shot prompting; bad examples contaminate the model, so rejection matters.

---

## Section 5 — Phase 0 Audit (Prerequisite)

Before building Phase 1, do a full audit of existing Python code. This is not optional — building the agent layer on top of unclear code creates technical debt that compounds.

**Audit output:** `docs/superpowers/specs/2026-04-25-phase0-audit.md` (separate doc, produced during Phase 0 execution)

**Categorize every file as:**
- `TOOL` — wraps business logic, called by agent; keep as-is, add PydanticAI decorator
- `HANDLER` — current intent handler; extract logic to tool, shell can be deleted after migration
- `SERVICE` — pure business logic with no I/O side effects; keep, becomes tool dependency
- `MODEL` — SQLAlchemy ORM or Pydantic schema; keep unchanged
- `UTILITY` — shared helpers (fuzzy match, date parse, etc.); keep, may move to shared lib
- `DEAD` — unused or superseded code; delete after confirming no references
- `CONFIG` — env/settings; keep unchanged
- `SCRIPT` — one-off admin scripts; move to `scripts/` if not already there

**Design flaws to flag and fix:**
- Any handler that re-parses text (should use `state.py:parse()`)
- Any handler that queries DB directly (should go through service layer)
- Duplicate logic across handlers (extract to shared service/tool)
- Any function > 100 lines (split into named steps)
- Any function that both reads AND writes DB in same call without explicit transaction boundary

---

## Section 6 — Migration Strategy (Strangler Fig)

The bot never goes dark. Old and new systems run side by side. Feature flag `USE_PYDANTIC_AGENTS` (already in codebase) gates which path handles each request.

```
Request arrives at chat_api.py
    │
    ├─ if USE_PYDANTIC_AGENTS=true AND intent in AGENT_INTENTS:
    │      → LangGraph agent
    │
    └─ else:
           → existing regex → handler cascade (unchanged)
```

`AGENT_INTENTS` is a list in config. Start with 2-3 low-risk intents (CHECKOUT, ADD_PAYMENT). Expand one by one as each is validated in production.

Migration order (safest first):
1. CHECKOUT — well-defined, confirms before writing, easy to test
2. ADD_PAYMENT — same
3. REPORT — read-only, no DB writes, zero risk
4. QUERY_DUES — read-only
5. ADD_TENANT — complex, do last

Each migration step:
1. Write tool wrapper for handler
2. Write LangGraph node for intent
3. Enable in staging (TEST_MODE=1)
4. Run golden test suite, check pass rate ≥ 95%
5. Enable in production for 48h, monitor for errors
6. If clean: move to next intent

---

## Section 7 — Channel Adapters

### WhatsApp (existing, refactored)

Current: `chat_api.py` directly calls `gatekeeper.py`.  
After refactor: `chat_api.py` normalizes to `ChannelMessage`, passes to `agent_core.process()`.

No change to Meta webhook URL or token. Transparent to Meta.

### PWA (Phase 3)

REST endpoint: `POST /api/agent/message`  
Auth: Supabase JWT (same auth as PWA dashboard).  
Response: `ChannelResponse` serialized as JSON.

Same `agent_core.process()` — same conversation state, same tools, same learning.

### Voice (Phase 4)

Pipeline:
```
Mic input → Whisper (STT, ~300ms) → ChannelMessage
ChannelResponse → Kokoro TTS (self-hosted, ~200ms) → Audio output
Total round-trip: ~900ms
```

Kokoro is open source (82M params), runs on CPU, free. Hosted on the existing VPS alongside FastAPI. No GPU needed for TTS.

Whisper: `whisper-1` via Groq's free API (same key as LLM), not self-hosted.

### Future: Kozzy Sound Box (Phase 5)

A Raspberry Pi 4 on the reception desk:
- Microphone array (always-on wake word "Hey Kozzy")
- Speaker
- Connects to VPS over HTTPS WebSocket (same voice endpoint)
- No local AI — all processing on VPS
- Cost: ~₹4,000 hardware, ₹0/month compute

---

## Section 8 — Cost Analysis

| Component | Cost |
|---|---|
| LangGraph Python library | ₹0 (open source) |
| LangGraph checkpoint (Supabase) | ₹0 (existing DB) |
| Groq LLM inference | ₹0 (free tier, 6K tokens/min) |
| Cerebras fallback | ₹0 (free tier) |
| LangSmith observability | ₹0 (5K traces/month free) |
| Kokoro TTS (self-hosted) | ₹0 (runs on VPS CPU) |
| Whisper STT (Groq) | ₹0 (free tier) |
| Raspberry Pi (future) | ₹4,000 one-time |

**Total ongoing cost: ₹0/month** (same as today).

---

## Section 9 — Phase Roadmap

| Phase | What | Prerequisite |
|---|---|---|
| **0** | Audit + reorganize Python files | None — do first |
| **1** | LangGraph core + tool wrappers for CHECKOUT, ADD_PAYMENT | Phase 0 complete |
| **2** | Self-learning system (3-tier) | Phase 1 stable |
| **3** | PWA channel adapter | Phase 1 stable |
| **4** | Voice channel (Whisper + Kokoro) | Phase 3 complete |
| **5** | Kozzy sound box (Raspberry Pi) | Phase 4 complete |
| **6** | SaaS multi-tenant (plugin registry) | Phase 5 stable |

Phase 0 + 1 are highest priority. Phases 2–6 are sequential but can be delayed.

---

## Non-Goals (explicitly out of scope)

- Tenant-facing flows in Phase 1 (too risky — separate phase after Phase 1 proven)
- Self-hosting LLMs (GPU cost too high at current scale — revisit at 500K+ commands/month)
- MCP protocol (all tools are internal Python; MCP adds overhead for no benefit)
- Replacing regex for simple commands (regex is faster, cheaper, more reliable for yes/no/number inputs)
- New infrastructure (everything runs on existing VPS and Supabase)

---

## Open Questions (resolved)

| Question | Decision |
|---|---|
| Gemma 4 vs Groq Llama? | Use model-agnostic config. Start with Groq (free, proven). Swap to Gemma with one env var change when available on Groq. |
| LangGraph vs custom state machine? | LangGraph — serialization, checkpointing, and graph visualization are free. Building equivalent from scratch = 2 weeks. |
| MCP for tools? | No. All tools are internal Python. MCP is for external services (GitHub, databases outside the project). |
| Self-host LLM? | No. GPU cost too high. Groq free tier sufficient. |
| When does LLM get called? | Only in Intent and Clarify nodes. Router, Confirm, and Execute nodes are deterministic — no LLM call. |
