"""
src/whatsapp/conversation/
===========================
Conversation state framework for the WhatsApp bot.

Problem it solves
-----------------
Before this module, multi-turn state lived inside a single 2000-line
`resolve_pending_action` in owner_handler.py. Intents were distinguished
by string match on `pending.intent`, and any block could accidentally
swallow an input meant for another (e.g. an APPROVE_ONBOARDING handler
matching "1" intended for a PAYMENT_LOG disambiguation).

Design
------
- `ConversationState` enum — what the bot is waiting for
  (AWAITING_CHOICE, AWAITING_CONFIRMATION, AWAITING_FIELD, ...)
- `UserInput` — one parsed user message (is it a number? yes/no? cancel?)
- `ConversationMemory` — bundle of {phone, role, pending, recent_turns,
  user_context} passed to every handler
- `router.route()` — looks at (intent, state) and dispatches to the
  matching handler. ONE function per (intent, state) tuple, no cascading
  if-elif.

Migration strategy
------------------
Pending actions with `state` field set are routed through this module.
Legacy pending rows with `state == NULL` fall back to the old
`resolve_pending_action` cascade. Intents are ported one at a time;
tests gate each migration.
"""
