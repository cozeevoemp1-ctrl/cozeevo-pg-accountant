# Kozzy AI Platform — Design Spec

**Date:** 2026-04-08
**Status:** Approved
**Goal:** Multi-tenant PG management platform with agentic AI. Each PG gets a fully autonomous, self-learning WhatsApp bot configured through DB — zero code changes per PG. Cozeevo is tenant #1.

---

## Problem

1. Everything is hardcoded for Cozeevo — buildings, rooms, admins, personality, bank parser
2. Regex handles ~97% but misses natural language; Groq fallback is fragile (raw json.loads)
3. Bot is "dead" for conversation — canned templates instead of actual chat
4. No learning — same mistakes repeated, no memory of corrections
5. Can't onboard a new PG without code changes
6. Business logic scattered across 16+ markdown files instead of DB config

## Solution

Multi-tenant platform where each PG is fully configured through `pg_config` table. PydanticAI-powered ConversationAgent handles understanding + conversation + learning. Everything is plug-and-play per PG: buildings, rooms, staff, pricing, bank statements, personality.

---

## Architecture

```
WhatsApp message
  -> webhook receives msg + phone number
  -> look up phone -> which pg_id does this user belong to?
  -> load pg_config for that PG (cached)
  -> intent_detector.py (regex — fast, free, instant)
      -> HIGH confidence regex match -> execute
      -> LOW/NO match -> ConversationAgent
          - System prompt built from pg_config (personality, buildings, context)
          - Pulls top-K examples from intent_examples WHERE pg_id = this PG
          - Classifies OR converses naturally
          - Returns structured ConversationResult
          - Confidence routing:
               >0.9  -> execute silently
               0.6-0.9 -> show options
               <0.6  -> ask explicitly
          - Fires background LearningAgent (async)

  -> LearningAgent (background, per PG)
      - Logs to classification_log (pg_id scoped)
      - Saves confirmed examples to intent_examples (pg_id scoped)
      - Each PG learns independently from its own users
```

---

## Data Model

### New table: pg_config (the master config per PG)

| Column | Type | Description |
|---|---|---|
| id | UUID PK | |
| pg_name | TEXT | "Cozeevo Co-living", "Sunshine PG" |
| brand_name | TEXT | Bot display name ("Cozeevo Help Desk") |
| brand_voice | TEXT | System prompt personality: tone, style, greeting style |
| buildings | JSONB | [{name: "THOR", floors: 5, type: "male"}, {name: "HULK", floors: 4, type: "female"}] |
| rooms | JSONB | [{number: "101", building: "THOR", floor: 1, beds: 3, type: "sharing"}, ...] |
| staff | JSONB | [{name: "Lokesh", role: "receptionist", phone: "7680814628"}, ...] |
| admin_phones | JSONB | ["+917845952289", "+917358341775"] |
| pricing | JSONB | {sharing_3: 7500, sharing_2: 9000, single: 12000, single_ac: 15000, ...} |
| bank_config | JSONB | {bank_name: "HDFC", account_format: "...", statement_columns: {...}, upi_id_patterns: [...]} |
| expense_categories | JSONB | ["Electricity", "Salary", "Plumbing", "Maintenance", ...] |
| custom_intents | JSONB | Additional intents beyond defaults (optional) |
| business_rules | JSONB | {proration: "first_month_only", checkout_notice_days: 30, deposit_months: 1, billing_cycle: "monthly"} |
| whatsapp_config | JSONB | {phone_number_id: "...", waba_id: "...", token_env_key: "WHATSAPP_TOKEN"} |
| timezone | TEXT | "Asia/Kolkata" |
| is_active | BOOLEAN | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### New table: intent_examples (self-learning, per PG)

| Column | Type | Description |
|---|---|---|
| id | UUID PK | |
| pg_id | UUID FK | References pg_config.id |
| message_text | TEXT | Original user message |
| intent | TEXT | Confirmed intent |
| role | TEXT | admin/tenant/lead |
| entities | JSONB | {name, amount, room, etc.} |
| confidence | FLOAT | Confidence at time of classification |
| source | TEXT | 'user_correction', 'user_selection', 'user_clarification', 'auto_confirmed', 'manual_teach' |
| confirmed_by | TEXT | Phone number |
| is_active | BOOLEAN | Soft delete |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### New table: classification_log (audit trail, per PG)

| Column | Type | Description |
|---|---|---|
| id | UUID PK | |
| pg_id | UUID FK | References pg_config.id |
| message_text | TEXT | What user sent |
| phone | TEXT | Who sent it |
| role | TEXT | |
| regex_result | TEXT | NULL if miss |
| regex_confidence | FLOAT | |
| llm_result | TEXT | NULL if regex handled |
| llm_confidence | FLOAT | |
| final_intent | TEXT | What executed |
| was_corrected | BOOLEAN | |
| corrected_to | TEXT | |
| created_at | TIMESTAMPTZ | |

### Existing tables: add pg_id

Tables that need `pg_id` added: `authorized_users`, plus all new tables above. Existing tenant/payment/expense tables already have building context which maps to a PG. For phase 1, we add a `pg_id` default that maps to Cozeevo's UUID — zero disruption to existing data.

---

## pg_config: What Each Field Powers

| Field | What it drives |
|---|---|
| `brand_name` | Bot greeting, "I'm {brand_name}", WhatsApp profile |
| `brand_voice` | System prompt tone — injected into ConversationAgent prompt |
| `buildings` | Room queries, occupancy, floor plans, tenant assignment |
| `rooms` | Vacancy check, room status, bed availability |
| `staff` | Role assignment, who can do what |
| `admin_phones` | Admin detection in role_service.py (replaces hardcoded list) |
| `pricing` | Rent calculation, lead enquiry responses, billing |
| `bank_config` | Bank statement parser — column mapping, UPI patterns, account format |
| `expense_categories` | Expense classification, P&L categories |
| `custom_intents` | PG-specific commands beyond defaults |
| `business_rules` | Proration logic, notice period, deposit rules, billing cycle |
| `whatsapp_config` | Which WhatsApp number/account to use per PG |

---

## Pydantic Response Models

```python
class ConversationResult(BaseModel):
    action: str                       # "classify", "ask_options", "clarify", "converse", "correct"
    intent: str | None = None
    confidence: float = 0.0
    entities: dict = {}
    options: list[str] | None = None  # when 0.6-0.9
    correction: dict | None = None    # {field, old, new}
    reply: str | None = None          # natural language to user
    reasoning: str = ""               # for LearningAgent evaluation

class MerchantClassification(BaseModel):
    category: str
    confidence: float
    reason: str

class BankStatementRow(BaseModel):
    date: str
    description: str
    amount: float
    txn_type: str                     # credit/debit
    category: str | None = None
    tenant_match: str | None = None   # matched tenant name
    confidence: float = 0.0
```

---

## Agent Design

### ConversationAgent (the brain)

Single agent per conversation. Handles ALL non-regex messages:
- **Classifies** intents with few-shot examples from this PG's intent_examples
- **Converses** naturally — greetings, thanks, "who are you?", small talk
- **Shows options** when medium confidence (0.6-0.9)
- **Asks clarification** when low (<0.6)
- **Handles corrections** mid-flow
- **Extracts entities** from natural language

**System prompt built dynamically from pg_config:**
```
You are {pg_config.brand_name}, an AI assistant for {pg_config.pg_name}.
{pg_config.brand_voice}

Buildings: {pg_config.buildings}
Available intents for {role}: {intents}

Recent examples of how users at this PG talk:
{top_k_examples from intent_examples WHERE pg_id = this_pg}

Chat history: {recent_messages}
Pending action: {pending_context}
```

**Tools available to agent:**
- `search_similar_examples(message)` — find similar past messages from this PG
- `get_tenant_context(name_or_room)` — look up tenant/room info
- `get_room_info(room_number)` — vacancy, current tenant, pricing

**Provider:** Groq (Llama 3.3 70B)

### LearningAgent (the memory)

Background, async, per PG. Never talks to users:
- Logs every classification to classification_log
- Saves confirmed examples to intent_examples
- Finds patterns in misclassifications
- Prunes contradictory examples (soft delete)
- Rate limited: max 1 Groq call per 10 seconds

**Fires when:**
- LLM classification completes (any confidence)
- User selects from options
- User corrects a classification
- User clarifies after low-confidence ask
- Session ends without correction (auto-confirm >0.9)

### BankParserAgent (per-PG bank statement processing)

Uses `pg_config.bank_config` to parse any PG's bank statements:
- Column mapping from config (not hardcoded)
- UPI pattern matching from config
- Expense categories from config
- Tenant matching against this PG's tenant list

---

## Confidence Routing

| Confidence | Action | Learning |
|---|---|---|
| >0.9 | Execute silently | Auto-confirmed if no correction |
| 0.6-0.9 | Show options | Saved as 'user_selection' |
| <0.6 | Ask explicitly | Saved as 'user_clarification' |
| Any + correction | Re-route | Saved as 'user_correction' |
| Conversation | Reply naturally | Logged, no intent_example |

---

## Learning Flywheel

Each PG learns independently. PG A's users teaching the bot doesn't affect PG B.

```
Day 1:   Bot works with default intents. No PG-specific knowledge.
Week 1:  50-100 examples. Starts understanding this PG's vocabulary.
Month 1: 500+ examples. Most phrasings covered. Fewer options shown.
Over time: Bot becomes expert at THIS PG's communication style.
```

Every confidence band feeds learning. Corrections are highest value.

---

## Onboarding a New PG

1. INSERT one row into `pg_config` (buildings, rooms, pricing, admins, brand voice, bank config)
2. Register admin phones in `authorized_users` with the `pg_id`
3. Set up WhatsApp number (Meta Business API) — config goes in `pg_config.whatsapp_config`
4. Done — bot works immediately with default intents, learns from day 1

**Zero code changes. Zero new files. Zero deployment.**

---

## Integration Points

### Files that change

| File | Change |
|---|---|
| `src/llm_gateway/agents/` | NEW: conversation_agent.py, learning_agent.py, bank_parser_agent.py, models.py |
| `src/llm_gateway/agents/tools/` | NEW: search_examples.py, get_context.py |
| `src/whatsapp/intent_detector.py` | After regex miss: load pg_config, route to ConversationAgent |
| `src/whatsapp/chat_api.py` | Resolve pg_id from phone, pass to agents. Option selection fires LearningAgent |
| `src/whatsapp/role_service.py` | Load admin phones from pg_config instead of hardcoded list |
| `src/database/models.py` | Add PgConfig, IntentExample, ClassificationLog ORM models |
| `src/database/migrate_all.py` | Append CREATE TABLE statements + Cozeevo seed data |
| `.env` / `.env.example` | Add USE_PYDANTIC_AGENTS=false, DEFAULT_PG_ID |
| `requirements.txt` | Add pydantic-ai |

### Files that do NOT change (phase 1)

| File | Why |
|---|---|
| `handlers/*` | Receive same dict shape — don't know PydanticAI exists |
| `gatekeeper.py` | Routes by role+intent, same interface |
| `claude_client.py` | Stays as fallback when flag is off |

---

## Safety / Rollout

- **Feature flag:** `USE_PYDANTIC_AGENTS=false`. Old path stays. Instant rollback.
- **Cozeevo = first tenant:** pg_config seeded with current hardcoded values. Everything works same as before.
- **Golden tests first:** Run 115 tests against new agents before wiring in.
- **Classification log:** Every decision auditable per PG.
- **No handler changes in phase 1:** Agent outputs same dict shape.

---

## Dependencies

- `pydantic-ai` (new)
- Groq free tier — 30 req/min, 14,400 req/day (shared across all PGs initially, per-PG API keys later)
- Supabase (existing) — three new tables + pg_id on authorized_users

---

## Out of Scope (Phase 1)

- Auto-generating regex rules from learned patterns (logged/proposed only)
- Multi-language support beyond English
- Per-PG LLM provider selection (all PGs use Groq for now)
- Admin dashboard for pg_config management (manual DB inserts for now)
- Per-PG WhatsApp number routing (single number for now, multi-number phase 2)
- Cross-PG learning (each PG is isolated — sharing patterns across PGs is future)
- Docs consolidation (happens naturally as config moves to DB)
