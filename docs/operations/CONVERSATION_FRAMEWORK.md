# Conversation State Framework

## Why this exists

Before, multi-turn state lived inside a 2000-line `resolve_pending_action`
in `owner_handler.py`. Intents were distinguished by string match on
`pending.intent`, and any block could accidentally swallow an input meant
for another intent (e.g. APPROVE_ONBOARDING's `"yes" in ("yes", "y", "1")`
matching a "1" intended for a PAYMENT_LOG disambiguation).

The framework replaces that cascade with a typed state dispatcher.
Each `(intent, state)` pair has exactly one handler. No fallthrough,
no accidental matches.

## Module layout

```
src/whatsapp/conversation/
├── __init__.py           — module docstring
├── state.py              — ConversationState enum + UserInput parser
├── memory.py             — ConversationMemory dataclass + load()
├── router.py             — @register decorator + route() dispatcher
└── handlers/
    ├── __init__.py
    └── payment_log.py    — PAYMENT_LOG handlers (choice + confirm)
```

## Core concepts

### ConversationState

What the bot is waiting for:
- `IDLE` — no pending
- `AWAITING_CHOICE` — user must pick a number
- `AWAITING_CONFIRMATION` — yes/no
- `AWAITING_FIELD` — next field in a multi-step form
- `AWAITING_DATE`, `AWAITING_AMOUNT`, `AWAITING_TEXT`, `AWAITING_IMAGE`

Stored in `pending_actions.state`. NULL means legacy pending (routed
through the old cascade).

### UserInput

Every message is pre-parsed into all possible interpretations:
```python
inp = parse("1.")
inp.parsed_number  # 1
inp.parsed_yes     # False
inp.parsed_cancel  # False
inp.parsed_amount  # 1.0
```

Handlers pick the field relevant to their state. No re-parsing.

### ConversationMemory

Single struct passed to every handler:
```python
mem.phone          # normalized 10-digit
mem.role           # admin/owner/tenant/lead
mem.name
mem.pending        # PendingAction | None
mem.recent_turns   # last 10 messages (inbound + outbound)
mem.user_context   # free-form kv
```

Loaded once in `chat_api` via `memory.load(...)`.

### RouteResult

What a handler returns:
```python
return RouteResult(
    reply="Payment logged.",
    keep_pending=False,          # True = stay in pending (re-prompt/correction)
    next_state=ConversationState.AWAITING_CONFIRMATION,  # optional transition
    next_intent="CONFIRM_PAYMENT_LOG",                    # optional intent swap
)
```

## How to port an intent

### 1. Save pending with a state

```python
await _save_pending(
    ctx.phone, "MY_INTENT",
    {"amount": 100}, choices, session,
    state="awaiting_choice",     # ← new arg
)
```

### 2. Write the handler

```python
# src/whatsapp/conversation/handlers/my_intent.py
from ..memory import ConversationMemory
from ..state import ConversationState, UserInput
from ..router import RouteResult, register

@register("MY_INTENT", ConversationState.AWAITING_CHOICE)
async def on_my_intent_choice(mem, inp, session) -> RouteResult:
    choices = json.loads(mem.pending.choices or "[]")
    if inp.parsed_number and 1 <= inp.parsed_number <= len(choices):
        chosen = choices[inp.parsed_number - 1]
        # Call existing business function — don't duplicate logic
        reply = await do_the_thing(chosen, session)
        return RouteResult(reply=reply, keep_pending=False)
    # Re-prompt on invalid input
    options = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices)
    return RouteResult(
        reply=f"Please pick:\n{options}\n\nOr *cancel*.",
        keep_pending=True,
    )
```

### 3. Register the handler module in router.py

```python
from .handlers import my_intent  # noqa: F401
```

### 4. Add a test

```python
# tests/intent_suite.py
Case("my_intent flow", [
    ("start my intent", None),
    ("1", None),
], ["my_intent"]),
```

### 5. Run `python tests/intent_suite.py` — must stay green.

## Testing

- `tests/chat_harness.py` — simulate a WhatsApp conversation locally
  (no webhook, no real phone). Chainable multi-turn. REPL mode:
  `python tests/chat_harness.py`
- `tests/intent_suite.py` — pass/fail matrix across cheat-sheet +
  edge cases. Currently 50/50 (100%).

## What's ported so far

- ✅ PAYMENT_LOG (AWAITING_CHOICE + correction re-prompt)
- ✅ CONFIRM_PAYMENT_LOG (AWAITING_CONFIRMATION, delegates to legacy
  for the heavy yes-path)

## Remaining to port (38 intents)

See `memory/MEMORY.md` audit for the full list. Priority order based
on real-world frequency:

1. CHECKOUT / SCHEDULE_CHECKOUT — high volume
2. CONFIRM_ADD_TENANT — high volume
3. CONFIRM_ADD_EXPENSE — high volume
4. OVERPAYMENT_RESOLVE / UNDERPAYMENT_NOTE — edge-heavy
5. NOTICE_GIVEN / VOID_PAYMENT / QUERY_TENANT — medium volume
6. RENT_CHANGE / DEPOSIT_CHANGE / ROOM_TRANSFER — lower volume
7. Everything else

Each port is a small PR: one handler file + one `_save_pending(...,
state=...)` line + new test cases. No code shared between handlers
means no refactoring risk.

## Golden rule

If the test suite stays green after your change, the port is safe.
If it breaks, revert and re-diagnose.
