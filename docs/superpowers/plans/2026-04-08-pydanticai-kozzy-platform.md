# Kozzy AI Platform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Cozeevo WhatsApp bot into a multi-tenant Kozzy AI Platform with PydanticAI-powered conversation agent, self-learning intent system, and per-PG configuration — all through database config, zero code changes per PG.

**Architecture:** Regex stays as fast path. PydanticAI ConversationAgent handles misses with structured output, few-shot examples, and natural conversation. Background LearningAgent saves every interaction for autonomous improvement. All PG-specific config reads from `pg_config` table. Cozeevo is tenant #1.

**Tech Stack:** PydanticAI + Groq (Llama 3.3 70B) + FastAPI + Supabase + SQLAlchemy async

**Spec:** `docs/superpowers/specs/2026-04-08-pydanticai-agentic-learning-design.md`
**System spec:** `docs/SYSTEM_SPEC.md`

---

## File Structure

### New files
| File | Responsibility |
|---|---|
| `src/llm_gateway/agents/__init__.py` | Package init |
| `src/llm_gateway/agents/models.py` | Pydantic response models (ConversationResult, MerchantClassification, BankStatementRow) |
| `src/llm_gateway/agents/conversation_agent.py` | PydanticAI ConversationAgent — classifies, converses, shows options, handles corrections |
| `src/llm_gateway/agents/learning_agent.py` | Background LearningAgent — logs classifications, saves examples, prunes |
| `src/llm_gateway/agents/tools.py` | Agent tools: search_similar_examples, get_tenant_context |
| `src/llm_gateway/agents/prompt_builder.py` | Builds system prompt from pg_config (brand, buildings, intents, examples) |
| `tests/test_conversation_agent.py` | Unit tests for ConversationAgent |
| `tests/test_learning_agent.py` | Unit tests for LearningAgent |
| `tests/test_pg_config.py` | Tests for pg_config loading and prompt building |

### Modified files
| File | What changes |
|---|---|
| `src/database/models.py` | Add PgConfig, IntentExample, ClassificationLog ORM models |
| `src/database/migrate_all.py` | Append 3 CREATE TABLE + Cozeevo seed INSERT |
| `src/whatsapp/chat_api.py` | After regex miss, check flag, route to ConversationAgent. On option selection, fire LearningAgent |
| `src/whatsapp/intent_detector.py` | Export IntentResult, add `USE_PYDANTIC_AGENTS` gate before returning UNKNOWN |
| `src/whatsapp/role_service.py` | Load admin phones from pg_config instead of env var |
| `requirements.txt` | Add pydantic-ai, pydantic-ai[groq] |
| `.env.example` | Add USE_PYDANTIC_AGENTS, DEFAULT_PG_ID |

### Untouched
| File | Why |
|---|---|
| `src/whatsapp/handlers/*` | Receive same dict shape — no change needed |
| `src/whatsapp/gatekeeper.py` | Routes by role+intent, same interface |
| `src/llm_gateway/claude_client.py` | Stays as fallback when flag is off |
| `src/llm_gateway/prompts.py` | Old prompts stay for old code path |

---

## Task 1: Add pydantic-ai dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add pydantic-ai to requirements.txt**

Add after the existing pydantic entries (line 9):

```
pydantic-ai[groq]==0.2.14
```

- [ ] **Step 2: Install and verify**

Run: `cd /c/Users/kiran/Desktop/AI\ Watsapp\ PG\ Accountant && pip install pydantic-ai[groq]`
Expected: Successful install

- [ ] **Step 3: Verify import works**

Run: `python -c "from pydantic_ai import Agent; print('pydantic-ai OK')"`
Expected: `pydantic-ai OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add pydantic-ai[groq] for agentic LLM integration"
```

---

## Task 2: Database models — PgConfig, IntentExample, ClassificationLog

**Files:**
- Modify: `src/database/models.py`
- Test: `tests/test_pg_config.py`

- [ ] **Step 1: Write test for new models**

Create `tests/test_pg_config.py`:

```python
"""Tests for PgConfig, IntentExample, ClassificationLog models."""
import uuid
from datetime import datetime, timezone
from src.database.models import PgConfig, IntentExample, ClassificationLog


def test_pg_config_model_exists():
    """PgConfig model can be instantiated with required fields."""
    pg = PgConfig(
        id=uuid.uuid4(),
        pg_name="Test PG",
        brand_name="Test Help Desk",
    )
    assert pg.pg_name == "Test PG"
    assert pg.brand_name == "Test Help Desk"
    assert pg.__tablename__ == "pg_config"


def test_pg_config_has_all_config_fields():
    """PgConfig has all required JSONB config columns."""
    cols = {c.name for c in PgConfig.__table__.columns}
    required = {
        "id", "pg_name", "brand_name", "brand_voice",
        "buildings", "rooms", "staff_rooms", "staff",
        "admin_phones", "pricing", "bank_config",
        "expense_categories", "custom_intents", "business_rules",
        "whatsapp_config", "gsheet_config", "timezone",
        "is_active", "created_at", "updated_at",
    }
    assert required.issubset(cols), f"Missing columns: {required - cols}"


def test_intent_example_model_exists():
    """IntentExample model has pg_id FK and all learning fields."""
    cols = {c.name for c in IntentExample.__table__.columns}
    required = {
        "id", "pg_id", "message_text", "intent", "role",
        "entities", "confidence", "source", "confirmed_by",
        "is_active", "created_at", "updated_at",
    }
    assert required.issubset(cols), f"Missing columns: {required - cols}"


def test_classification_log_model_exists():
    """ClassificationLog model has pg_id FK and audit fields."""
    cols = {c.name for c in ClassificationLog.__table__.columns}
    required = {
        "id", "pg_id", "message_text", "phone", "role",
        "regex_result", "regex_confidence",
        "llm_result", "llm_confidence",
        "final_intent", "was_corrected", "corrected_to",
        "created_at",
    }
    assert required.issubset(cols), f"Missing columns: {required - cols}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pg_config.py -v`
Expected: FAIL — ImportError, models don't exist yet

- [ ] **Step 3: Add PgConfig model to models.py**

Add at the end of `src/database/models.py`, before any existing `# ── Singleton` or end-of-file marker:

```python
# ── L0: Platform Config ──────────────────────────────────────────────────────

class PgConfig(Base):
    """Master configuration per PG — the single source of all PG-specific settings."""
    __tablename__ = "pg_config"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pg_name            = Column(String, nullable=False)                    # "Cozeevo Co-living"
    brand_name         = Column(String, nullable=False)                    # "Cozeevo Help Desk"
    brand_voice        = Column(Text, default="")                         # personality for AI prompt
    buildings          = Column(JSON, default=list)                        # [{name, floors, type}]
    rooms              = Column(JSON, default=list)                        # [{number, building, beds, type}]
    staff_rooms        = Column(JSON, default=list)                        # ["G05","G06","107"]
    staff              = Column(JSON, default=list)                        # [{name, role, phone}]
    admin_phones       = Column(JSON, default=list)                        # ["+917845952289"]
    pricing            = Column(JSON, default=dict)                        # {sharing_3: 7500, ...}
    bank_config        = Column(JSON, default=dict)                        # {bank_name, columns, upi_patterns}
    expense_categories = Column(JSON, default=list)                        # ["Electricity","Salary",...]
    custom_intents     = Column(JSON, default=list)                        # PG-specific intents
    business_rules     = Column(JSON, default=dict)                        # {proration, notice_days, ...}
    whatsapp_config    = Column(JSON, default=dict)                        # {phone_number_id, waba_id}
    gsheet_config      = Column(JSON, default=dict)                        # {sheet_id, service_account}
    timezone           = Column(String, default="Asia/Kolkata")
    is_active          = Column(Boolean, default=True)
    created_at         = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at         = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                onupdate=lambda: datetime.now(timezone.utc))


# ── L5: AI / Learning ────────────────────────────────────────────────────────

class IntentExample(Base):
    """Self-learning intent examples — per PG, grows from user corrections and confirmations."""
    __tablename__ = "intent_examples"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pg_id         = Column(UUID(as_uuid=True), ForeignKey("pg_config.id"), nullable=False, index=True)
    message_text  = Column(Text, nullable=False)
    intent        = Column(String, nullable=False)
    role          = Column(String, nullable=False)           # admin/tenant/lead
    entities      = Column(JSON, default=dict)
    confidence    = Column(Float, default=0.0)
    source        = Column(String, nullable=False)           # user_correction/user_selection/user_clarification/auto_confirmed/manual_teach
    confirmed_by  = Column(String, default="")               # phone number
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


class ClassificationLog(Base):
    """Audit trail of every intent classification — per PG, feeds LearningAgent."""
    __tablename__ = "classification_log"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pg_id            = Column(UUID(as_uuid=True), ForeignKey("pg_config.id"), nullable=False, index=True)
    message_text     = Column(Text, nullable=False)
    phone            = Column(String, nullable=False)
    role             = Column(String, default="")
    regex_result     = Column(String, nullable=True)
    regex_confidence = Column(Float, nullable=True)
    llm_result       = Column(String, nullable=True)
    llm_confidence   = Column(Float, nullable=True)
    final_intent     = Column(String, nullable=True)
    was_corrected    = Column(Boolean, default=False)
    corrected_to     = Column(String, nullable=True)
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

Note: Ensure `uuid` is imported at the top of models.py. Also ensure `UUID` from `sqlalchemy.dialects.postgresql` is imported. Check existing imports — if `UUID` isn't there, add:
```python
from sqlalchemy.dialects.postgresql import UUID
import uuid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pg_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/database/models.py tests/test_pg_config.py
git commit -m "feat: add PgConfig, IntentExample, ClassificationLog models"
```

---

## Task 3: Database migration — create tables + seed Cozeevo

**Files:**
- Modify: `src/database/migrate_all.py`

- [ ] **Step 1: Add migration function for pg_config table**

Add before `async def main()` (line 795) in `src/database/migrate_all.py`:

```python
async def run_create_pg_config(conn: AsyncConnection) -> None:
    """Create pg_config table for multi-tenant PG configuration. Added 2026-04-08."""
    print("\n── Create pg_config table ──")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS pg_config (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pg_name         TEXT NOT NULL,
            brand_name      TEXT NOT NULL,
            brand_voice     TEXT DEFAULT '',
            buildings       JSONB DEFAULT '[]'::jsonb,
            rooms           JSONB DEFAULT '[]'::jsonb,
            staff_rooms     JSONB DEFAULT '[]'::jsonb,
            staff           JSONB DEFAULT '[]'::jsonb,
            admin_phones    JSONB DEFAULT '[]'::jsonb,
            pricing         JSONB DEFAULT '{}'::jsonb,
            bank_config     JSONB DEFAULT '{}'::jsonb,
            expense_categories JSONB DEFAULT '[]'::jsonb,
            custom_intents  JSONB DEFAULT '[]'::jsonb,
            business_rules  JSONB DEFAULT '{}'::jsonb,
            whatsapp_config JSONB DEFAULT '{}'::jsonb,
            gsheet_config   JSONB DEFAULT '{}'::jsonb,
            timezone        TEXT DEFAULT 'Asia/Kolkata',
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT now(),
            updated_at      TIMESTAMPTZ DEFAULT now()
        )
    """))
    print("  [ok] pg_config table created")


async def run_create_intent_examples(conn: AsyncConnection) -> None:
    """Create intent_examples table for self-learning per PG. Added 2026-04-08."""
    print("\n── Create intent_examples table ──")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS intent_examples (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pg_id           UUID NOT NULL REFERENCES pg_config(id),
            message_text    TEXT NOT NULL,
            intent          TEXT NOT NULL,
            role            TEXT NOT NULL,
            entities        JSONB DEFAULT '{}'::jsonb,
            confidence      FLOAT DEFAULT 0.0,
            source          TEXT NOT NULL,
            confirmed_by    TEXT DEFAULT '',
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT now(),
            updated_at      TIMESTAMPTZ DEFAULT now()
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_intent_examples_pg_id ON intent_examples(pg_id)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_intent_examples_intent ON intent_examples(intent)
    """))
    print("  [ok] intent_examples table created")


async def run_create_classification_log(conn: AsyncConnection) -> None:
    """Create classification_log audit table per PG. Added 2026-04-08."""
    print("\n── Create classification_log table ──")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS classification_log (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pg_id            UUID NOT NULL REFERENCES pg_config(id),
            message_text     TEXT NOT NULL,
            phone            TEXT NOT NULL,
            role             TEXT DEFAULT '',
            regex_result     TEXT,
            regex_confidence FLOAT,
            llm_result       TEXT,
            llm_confidence   FLOAT,
            final_intent     TEXT,
            was_corrected    BOOLEAN DEFAULT FALSE,
            corrected_to     TEXT,
            created_at       TIMESTAMPTZ DEFAULT now()
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_classification_log_pg_id ON classification_log(pg_id)
    """))
    print("  [ok] classification_log table created")


async def run_seed_cozeevo_pg_config(conn: AsyncConnection) -> None:
    """Seed Cozeevo as the first PG tenant. Added 2026-04-08."""
    print("\n── Seed Cozeevo pg_config ──")
    # Check if already seeded
    result = await conn.execute(text("SELECT id FROM pg_config WHERE pg_name = 'Cozeevo Co-living' LIMIT 1"))
    if result.fetchone():
        print("  [skip] Cozeevo already seeded")
        return

    await conn.execute(text("""
        INSERT INTO pg_config (
            pg_name, brand_name, brand_voice,
            buildings, staff_rooms, admin_phones, pricing,
            expense_categories, business_rules, timezone
        ) VALUES (
            'Cozeevo Co-living',
            'Cozeevo Help Desk',
            'You are Cozeevo Help Desk, a friendly and efficient AI assistant for Cozeevo Co-living PG in Chennai. Be concise, professional, and helpful. Use simple English. No emojis unless the user uses them first.',
            '[{"name": "THOR", "floors": 7, "type": "male", "room_prefix": ""}, {"name": "HULK", "floors": 6, "type": "female", "room_prefix": ""}]'::jsonb,
            '["G05","G06","107","108","701","702","G12","114","618"]'::jsonb,
            '["+917845952289", "+917358341775", "+919444296681"]'::jsonb,
            '{"sharing_3": 7500, "sharing_2": 9000, "single": 12000, "single_ac": 15000}'::jsonb,
            '["Electricity","Water","Salaries","Food","Furniture","Maintenance","IT","Internet","Gas","Property Rent","Police/Govt","Marketing","Shopping","Bank Charges","Housekeeping","Security","Insurance","Legal","Other"]'::jsonb,
            '{"proration": "first_month_standard_only", "checkout_notice_day": 5, "deposit_months": 1, "billing_cycle": "monthly", "checkout_full_month_charged": true}'::jsonb,
            'Asia/Kolkata'
        )
    """))
    print("  [ok] Cozeevo seeded into pg_config")
```

- [ ] **Step 2: Add migration calls to main()**

In the `main()` function, add these calls after `run_add_lokesh_receptionist(conn)` (around line 811):

```python
            await run_create_pg_config(conn)
            await run_create_intent_examples(conn)
            await run_create_classification_log(conn)
            await run_seed_cozeevo_pg_config(conn)
```

- [ ] **Step 3: Test migration locally**

Run: `python -m src.database.migrate_all`
Expected: Tables created, Cozeevo seeded, no errors

- [ ] **Step 4: Verify tables exist**

Run: `python -c "import asyncio; from src.database.db_manager import get_engine; from sqlalchemy import text; exec(open('scripts/verify_tables.py').read()) if False else print('check DB manually')"` or verify via Supabase dashboard that pg_config, intent_examples, classification_log tables exist.

- [ ] **Step 5: Commit**

```bash
git add src/database/migrate_all.py
git commit -m "feat: migration for pg_config + intent_examples + classification_log + Cozeevo seed"
```

---

## Task 4: Pydantic response models

**Files:**
- Create: `src/llm_gateway/agents/__init__.py`
- Create: `src/llm_gateway/agents/models.py`
- Test: `tests/test_conversation_agent.py`

- [ ] **Step 1: Create package init**

Create `src/llm_gateway/agents/__init__.py`:

```python
"""PydanticAI agent system for Kozzy AI Platform."""
```

- [ ] **Step 2: Write test for response models**

Create `tests/test_conversation_agent.py`:

```python
"""Tests for PydanticAI agent response models."""
from src.llm_gateway.agents.models import ConversationResult, MerchantClassification


def test_conversation_result_classify():
    """ConversationResult with classify action has intent and confidence."""
    r = ConversationResult(
        action="classify",
        intent="PAYMENT_LOG",
        confidence=0.95,
        entities={"name": "Raj", "amount": 15000},
        reasoning="User said Raj paid, clear payment intent",
    )
    assert r.action == "classify"
    assert r.intent == "PAYMENT_LOG"
    assert r.confidence == 0.95
    assert r.entities["amount"] == 15000


def test_conversation_result_ask_options():
    """ConversationResult with options for medium confidence."""
    r = ConversationResult(
        action="ask_options",
        confidence=0.7,
        options=["PAYMENT_LOG", "QUERY_DUES", "QUERY_TENANT"],
        reply="Did you mean:\n1. Log a payment\n2. Check dues\n3. Check tenant details",
    )
    assert r.action == "ask_options"
    assert len(r.options) == 3
    assert r.reply is not None


def test_conversation_result_converse():
    """ConversationResult for natural conversation (no intent)."""
    r = ConversationResult(
        action="converse",
        reply="Good morning! How can I help you today?",
    )
    assert r.action == "converse"
    assert r.intent is None
    assert r.confidence == 0.0


def test_conversation_result_correct():
    """ConversationResult for mid-flow correction."""
    r = ConversationResult(
        action="correct",
        intent="PAYMENT_LOG",
        confidence=0.9,
        correction={"field": "amount", "old": 5000, "new": 12000},
    )
    assert r.correction["new"] == 12000


def test_conversation_result_defaults():
    """ConversationResult defaults are safe."""
    r = ConversationResult(action="converse")
    assert r.intent is None
    assert r.confidence == 0.0
    assert r.entities == {}
    assert r.options is None
    assert r.correction is None
    assert r.reply is None
    assert r.reasoning == ""


def test_merchant_classification():
    """MerchantClassification validates correctly."""
    m = MerchantClassification(
        category="Electricity",
        confidence=0.85,
        reason="BESCOM payment description",
    )
    assert m.category == "Electricity"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_conversation_agent.py -v`
Expected: FAIL — ImportError

- [ ] **Step 4: Create response models**

Create `src/llm_gateway/agents/models.py`:

```python
"""Pydantic response models for all PydanticAI agents."""
from __future__ import annotations

from pydantic import BaseModel


class ConversationResult(BaseModel):
    """Response from ConversationAgent — covers classify, converse, options, corrections."""
    action: str                       # "classify", "ask_options", "clarify", "converse", "correct"
    intent: str | None = None
    confidence: float = 0.0
    entities: dict = {}
    options: list[str] | None = None  # intent options when 0.6-0.9
    correction: dict | None = None    # {field, old, new}
    reply: str | None = None          # natural language to user
    reasoning: str = ""               # why this classification — used by LearningAgent


class MerchantClassification(BaseModel):
    """Response from merchant/expense classification."""
    category: str
    confidence: float
    reason: str


class BankStatementRow(BaseModel):
    """Parsed bank statement row with classification."""
    date: str
    description: str
    amount: float
    txn_type: str                     # credit/debit
    category: str | None = None
    tenant_match: str | None = None
    confidence: float = 0.0
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_conversation_agent.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add src/llm_gateway/agents/__init__.py src/llm_gateway/agents/models.py tests/test_conversation_agent.py
git commit -m "feat: PydanticAI response models — ConversationResult, MerchantClassification, BankStatementRow"
```

---

## Task 5: Prompt builder — dynamic system prompt from pg_config

**Files:**
- Create: `src/llm_gateway/agents/prompt_builder.py`
- Test: `tests/test_pg_config.py` (append)

- [ ] **Step 1: Write test for prompt builder**

Append to `tests/test_pg_config.py`:

```python
from src.llm_gateway.agents.prompt_builder import build_system_prompt


def test_build_system_prompt_includes_brand():
    """System prompt includes brand name and PG name from config."""
    pg_config = {
        "pg_name": "Test PG",
        "brand_name": "Test Help Desk",
        "brand_voice": "Be friendly and concise.",
        "buildings": [{"name": "ALPHA", "floors": 3, "type": "mixed"}],
        "admin_phones": ["+911234567890"],
        "pricing": {"sharing_3": 7500},
        "expense_categories": ["Electricity", "Water"],
        "business_rules": {"proration": "first_month_standard_only"},
    }
    prompt = build_system_prompt(pg_config, role="admin", examples=[], chat_history="", pending_context="")
    assert "Test Help Desk" in prompt
    assert "Test PG" in prompt
    assert "Be friendly and concise." in prompt
    assert "ALPHA" in prompt


def test_build_system_prompt_includes_examples():
    """System prompt injects few-shot examples."""
    pg_config = {
        "pg_name": "Test PG",
        "brand_name": "Test Bot",
        "brand_voice": "",
        "buildings": [],
        "admin_phones": [],
        "pricing": {},
        "expense_categories": [],
        "business_rules": {},
    }
    examples = [
        {"message": "Raj paid 15k", "intent": "PAYMENT_LOG"},
        {"message": "who owes money", "intent": "QUERY_DUES"},
    ]
    prompt = build_system_prompt(pg_config, role="admin", examples=examples, chat_history="", pending_context="")
    assert "Raj paid 15k" in prompt
    assert "PAYMENT_LOG" in prompt
    assert "QUERY_DUES" in prompt


def test_build_system_prompt_role_specific_intents():
    """System prompt shows different intents for admin vs tenant vs lead."""
    pg_config = {
        "pg_name": "X", "brand_name": "X", "brand_voice": "", "buildings": [],
        "admin_phones": [], "pricing": {}, "expense_categories": [], "business_rules": {},
    }
    admin_prompt = build_system_prompt(pg_config, role="admin", examples=[], chat_history="", pending_context="")
    tenant_prompt = build_system_prompt(pg_config, role="tenant", examples=[], chat_history="", pending_context="")
    lead_prompt = build_system_prompt(pg_config, role="lead", examples=[], chat_history="", pending_context="")

    assert "PAYMENT_LOG" in admin_prompt
    assert "PAYMENT_LOG" not in tenant_prompt
    assert "MY_BALANCE" in tenant_prompt
    assert "ROOM_PRICE" in lead_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pg_config.py::test_build_system_prompt_includes_brand -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Create prompt builder**

Create `src/llm_gateway/agents/prompt_builder.py`:

```python
"""Builds dynamic system prompts from pg_config for ConversationAgent."""
from __future__ import annotations

import json

# ── Intent catalogs per role ──────────────────────────────────────────────────
# These are the DEFAULT intents. PGs can add custom_intents via pg_config.

OWNER_INTENTS = """PAYMENT_LOG: tenant paid rent ("Raj paid 15000", "received 8k from 203")
QUERY_DUES: who hasn't paid, pending list, outstanding balances
QUERY_TENANT: balance/details of a specific tenant or room ("Raj balance", "room 203")
ADD_TENANT: add new tenant, check-in, new admission
CHECKOUT: tenant leaving/vacating NOW or today
SCHEDULE_CHECKOUT: tenant leaving on a specific FUTURE date
NOTICE_GIVEN: tenant gave advance notice of leaving (future timeframe required)
ADD_EXPENSE: log a property expense (electricity, salary, plumber)
QUERY_EXPENSES: check expenses this month
VOID_PAYMENT: cancel/reverse a payment
VOID_EXPENSE: cancel/reverse an expense
ADD_REFUND: record a deposit refund
QUERY_REFUNDS: pending refunds
REPORT: monthly summary, P&L, collection report
QUERY_VACANT_ROOMS: vacant/empty rooms, available beds
QUERY_OCCUPANCY: occupancy percentage, how full
COMPLAINT_REGISTER: report a problem (no water, broken fan)
COMPLAINT_UPDATE: resolve/close a complaint
QUERY_COMPLAINTS: check complaint status
ADD_CONTACT: add vendor/service contact with phone
QUERY_CONTACTS: look up vendor contact
REMINDER_SET: set a reminder
ACTIVITY_LOG: log an activity
QUERY_ACTIVITY: show activity log
HELP: help, menu, commands"""

TENANT_INTENTS = """MY_BALANCE: how much do I owe, my dues
MY_PAYMENTS: my payment history, receipts
MY_DETAILS: my room details, rent, check-in date
HELP: help, hi, hello"""

LEAD_INTENTS = """ROOM_PRICE: price, rent, cost, rates
AVAILABILITY: available rooms, vacancy
ROOM_TYPE: single, double, sharing, AC
VISIT_REQUEST: visit, tour, show room
GENERAL: general enquiry or conversation"""


def build_system_prompt(
    pg_config: dict,
    role: str,
    examples: list[dict],
    chat_history: str,
    pending_context: str,
) -> str:
    """Build the complete system prompt for ConversationAgent from pg_config."""

    # Select intents for role
    if role in ("admin", "owner", "receptionist"):
        intents = OWNER_INTENTS
    elif role == "tenant":
        intents = TENANT_INTENTS
    else:
        intents = LEAD_INTENTS

    # Add custom intents from pg_config
    custom = pg_config.get("custom_intents") or []
    if custom:
        custom_text = "\n".join(f"{c['name']}: {c['description']}" for c in custom if isinstance(c, dict))
        if custom_text:
            intents += "\n" + custom_text

    # Format buildings
    buildings = pg_config.get("buildings") or []
    buildings_text = ", ".join(
        f"{b['name']} ({b.get('floors', '?')} floors, {b.get('type', 'mixed')})"
        for b in buildings if isinstance(b, dict)
    ) or "Not configured"

    # Format examples
    if examples:
        examples_text = "\n".join(
            f'- "{ex["message"]}" -> {ex["intent"]}'
            for ex in examples[:15]  # cap at 15 examples
        )
    else:
        examples_text = "No examples yet — this PG is still learning."

    # Format pricing
    pricing = pg_config.get("pricing") or {}
    pricing_text = ", ".join(f"{k}: {v}" for k, v in pricing.items()) if pricing else "Not configured"

    prompt = f"""You are {pg_config['brand_name']}, an AI assistant for {pg_config['pg_name']}.
{pg_config.get('brand_voice', '')}

ROLE OF CURRENT USER: {role}

BUILDINGS: {buildings_text}
PRICING: {pricing_text}

AVAILABLE INTENTS FOR THIS USER:
{intents}

EXAMPLES OF HOW USERS AT THIS PG TALK:
{examples_text}

INSTRUCTIONS:
1. Analyze the user's message and determine if it matches an intent or is just conversation.
2. If it's an intent, classify it with confidence 0.0-1.0 and extract entities (name, amount, room, month, mode).
3. If confidence > 0.9, return action="classify" with the intent.
4. If confidence 0.6-0.9, return action="ask_options" with top 2-3 intent options and a friendly question.
5. If confidence < 0.6, return action="clarify" with a helpful question.
6. If it's just conversation (greeting, thanks, question about you, small talk), return action="converse" with a natural reply.
7. If the user is correcting a previous classification, return action="correct" with the correction details.
8. Always include reasoning for your classification — this helps the system learn.
9. Keep replies concise — this is WhatsApp, not email.
10. Never make up information. If you don't know something, say so.

CHAT HISTORY:
{chat_history or 'No prior messages.'}

PENDING ACTION:
{pending_context or 'No pending action.'}

Respond with valid JSON matching ConversationResult schema:
{{"action": "classify|ask_options|clarify|converse|correct", "intent": "INTENT_NAME or null", "confidence": 0.0-1.0, "entities": {{}}, "options": ["INTENT1","INTENT2"] or null, "correction": null, "reply": "text or null", "reasoning": "why"}}"""

    return prompt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pg_config.py -v`
Expected: PASS (all tests including new prompt builder tests)

- [ ] **Step 5: Commit**

```bash
git add src/llm_gateway/agents/prompt_builder.py tests/test_pg_config.py
git commit -m "feat: dynamic system prompt builder from pg_config — role-aware, few-shot, multi-tenant"
```

---

## Task 6: Agent tools — search_similar_examples, get_tenant_context

**Files:**
- Create: `src/llm_gateway/agents/tools.py`

- [ ] **Step 1: Create agent tools**

Create `src/llm_gateway/agents/tools.py`:

```python
"""Tools available to ConversationAgent via PydanticAI tool use."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import IntentExample, Tenant, Tenancy, Room


async def search_similar_examples(
    message: str,
    pg_id: str,
    role: str,
    session: AsyncSession,
    limit: int = 10,
) -> list[dict]:
    """
    Find the most similar past examples for this PG.
    Uses substring matching + difflib similarity (no embeddings yet).
    Returns top-K examples sorted by relevance.
    """
    # Fetch active examples for this PG and role
    result = await session.execute(
        select(IntentExample).where(
            and_(
                IntentExample.pg_id == pg_id,
                IntentExample.is_active == True,
                IntentExample.role.in_([role, "admin"]) if role != "admin" else IntentExample.role == role,
            )
        ).limit(200)  # cap DB fetch
    )
    examples = result.scalars().all()

    if not examples:
        return []

    # Score each example by text similarity
    msg_lower = message.lower().strip()
    scored = []
    for ex in examples:
        ex_lower = ex.message_text.lower().strip()
        # Combine substring match + sequence similarity
        ratio = SequenceMatcher(None, msg_lower, ex_lower).ratio()
        # Boost if key words overlap
        msg_words = set(msg_lower.split())
        ex_words = set(ex_lower.split())
        overlap = len(msg_words & ex_words) / max(len(msg_words), 1)
        score = ratio * 0.6 + overlap * 0.4
        scored.append((score, ex))

    # Sort by score descending, take top-K
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "message": ex.message_text,
            "intent": ex.intent,
            "confidence": ex.confidence,
            "source": ex.source,
        }
        for score, ex in scored[:limit]
        if score > 0.15  # minimum relevance threshold
    ]


async def get_tenant_context(
    name_or_room: str,
    session: AsyncSession,
) -> Optional[dict]:
    """
    Look up tenant/room info for entity resolution.
    Returns basic tenant+room info if found, None otherwise.
    """
    name_or_room = name_or_room.strip()

    # Try room number first
    if name_or_room.isdigit() or name_or_room.upper().startswith("G"):
        result = await session.execute(
            select(Tenancy, Tenant, Room).join(
                Tenant, Tenancy.tenant_id == Tenant.id
            ).join(
                Room, Tenancy.room_id == Room.id
            ).where(
                and_(
                    Room.room_number == name_or_room,
                    Tenancy.status == "active",
                )
            )
        )
        row = result.first()
        if row:
            tenancy, tenant, room = row
            return {
                "tenant_name": tenant.name,
                "room": room.room_number,
                "rent": float(tenancy.agreed_rent) if tenancy.agreed_rent else None,
                "status": tenancy.status,
            }

    # Try name search (prefix match)
    result = await session.execute(
        select(Tenancy, Tenant, Room).join(
            Tenant, Tenancy.tenant_id == Tenant.id
        ).join(
            Room, Tenancy.room_id == Room.id
        ).where(
            and_(
                Tenant.name.ilike(f"{name_or_room}%"),
                Tenancy.status == "active",
            )
        ).limit(5)
    )
    rows = result.all()
    if rows:
        first = rows[0]
        tenancy, tenant, room = first
        return {
            "tenant_name": tenant.name,
            "room": room.room_number,
            "rent": float(tenancy.agreed_rent) if tenancy.agreed_rent else None,
            "status": tenancy.status,
            "multiple_matches": len(rows) > 1,
        }

    return None
```

- [ ] **Step 2: Commit**

```bash
git add src/llm_gateway/agents/tools.py
git commit -m "feat: agent tools — search_similar_examples + get_tenant_context"
```

---

## Task 7: ConversationAgent — PydanticAI agent

**Files:**
- Create: `src/llm_gateway/agents/conversation_agent.py`

- [ ] **Step 1: Create ConversationAgent**

Create `src/llm_gateway/agents/conversation_agent.py`:

```python
"""
ConversationAgent — the brain of Kozzy AI Platform.

Single PydanticAI agent that handles ALL non-regex messages:
- Classifies intents with few-shot examples
- Converses naturally (greetings, thanks, small talk)
- Shows options when medium confidence (0.6-0.9)
- Asks clarification when low confidence (<0.6)
- Handles corrections mid-flow
- Extracts entities from natural language

System prompt is built dynamically from pg_config.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.llm_gateway.agents.models import ConversationResult
from src.llm_gateway.agents.prompt_builder import build_system_prompt
from src.llm_gateway.agents.tools import search_similar_examples
from src.database.models import PgConfig

# Cache pg_config per pg_id to avoid repeated DB lookups
_pg_config_cache: dict[str, dict] = {}


async def _get_pg_config(pg_id: str, session: AsyncSession) -> dict:
    """Load pg_config from DB, cached in memory."""
    if pg_id in _pg_config_cache:
        return _pg_config_cache[pg_id]

    result = await session.execute(
        select(PgConfig).where(PgConfig.id == pg_id)
    )
    pg = result.scalars().first()
    if not pg:
        logger.error(f"[ConversationAgent] pg_config not found for pg_id={pg_id}")
        return {}

    config = {
        "pg_name": pg.pg_name,
        "brand_name": pg.brand_name,
        "brand_voice": pg.brand_voice or "",
        "buildings": pg.buildings or [],
        "rooms": pg.rooms or [],
        "staff_rooms": pg.staff_rooms or [],
        "admin_phones": pg.admin_phones or [],
        "pricing": pg.pricing or {},
        "bank_config": pg.bank_config or {},
        "expense_categories": pg.expense_categories or [],
        "custom_intents": pg.custom_intents or [],
        "business_rules": pg.business_rules or {},
    }
    _pg_config_cache[pg_id] = config
    return config


def invalidate_pg_config_cache(pg_id: str | None = None):
    """Clear pg_config cache (call after pg_config update)."""
    if pg_id:
        _pg_config_cache.pop(pg_id, None)
    else:
        _pg_config_cache.clear()


async def run_conversation_agent(
    message: str,
    role: str,
    phone: str,
    pg_id: str,
    session: AsyncSession,
    chat_history: str = "",
    pending_context: str = "",
) -> ConversationResult:
    """
    Run ConversationAgent on a message. Returns structured ConversationResult.

    This is the main entry point — called by chat_api.py when regex misses
    and USE_PYDANTIC_AGENTS is enabled.
    """
    try:
        # 1. Load PG config
        pg_config = await _get_pg_config(pg_id, session)
        if not pg_config:
            return ConversationResult(
                action="converse",
                reply="I'm having trouble loading my configuration. Please try again.",
                reasoning="pg_config not found",
            )

        # 2. Search similar examples for few-shot
        examples = await search_similar_examples(message, pg_id, role, session, limit=10)

        # 3. Build system prompt
        system_prompt = build_system_prompt(
            pg_config=pg_config,
            role=role,
            examples=examples,
            chat_history=chat_history,
            pending_context=pending_context,
        )

        # 4. Call LLM via PydanticAI
        result = await _call_llm(system_prompt, message)

        logger.info(
            f"[ConversationAgent] {phone} | action={result.action} "
            f"intent={result.intent} conf={result.confidence:.2f} "
            f"reasoning={result.reasoning[:80]}"
        )
        return result

    except Exception as e:
        logger.error(f"[ConversationAgent] Error: {e}")
        return ConversationResult(
            action="converse",
            reply="I didn't quite catch that. Could you rephrase? Type *help* for options.",
            reasoning=f"Agent error: {str(e)}",
        )


async def _call_llm(system_prompt: str, user_message: str) -> ConversationResult:
    """
    Call Groq via PydanticAI for structured output.
    Falls back to manual JSON parsing if PydanticAI structured output isn't supported.
    """
    try:
        from pydantic_ai import Agent

        agent = Agent(
            model="groq:llama-3.3-70b-versatile",
            system_prompt=system_prompt,
            result_type=ConversationResult,
            retries=3,
        )

        result = await agent.run(user_message)
        return result.data

    except ImportError:
        logger.warning("[ConversationAgent] pydantic-ai not available, falling back to manual")
        return await _call_llm_manual(system_prompt, user_message)
    except Exception as e:
        logger.warning(f"[ConversationAgent] PydanticAI call failed: {e}, trying manual")
        return await _call_llm_manual(system_prompt, user_message)


async def _call_llm_manual(system_prompt: str, user_message: str) -> ConversationResult:
    """Fallback: call Groq directly via httpx and parse JSON manually."""
    import httpx

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return ConversationResult(
            action="converse",
            reply="I'm not fully configured yet. Please contact the admin.",
            reasoning="GROQ_API_KEY not set",
        )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

    # Parse JSON from response (strip markdown fences if present)
    clean = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
    data = json.loads(clean)
    return ConversationResult(**data)
```

- [ ] **Step 2: Commit**

```bash
git add src/llm_gateway/agents/conversation_agent.py
git commit -m "feat: ConversationAgent — PydanticAI agent with dynamic prompt, few-shot, fallback"
```

---

## Task 8: LearningAgent — background async learning

**Files:**
- Create: `src/llm_gateway/agents/learning_agent.py`
- Test: `tests/test_learning_agent.py`

- [ ] **Step 1: Write test**

Create `tests/test_learning_agent.py`:

```python
"""Tests for LearningAgent helper functions."""
from src.llm_gateway.agents.learning_agent import should_auto_confirm, build_example_record


def test_should_auto_confirm_high_confidence():
    assert should_auto_confirm(0.95, was_corrected=False) is True


def test_should_not_auto_confirm_low_confidence():
    assert should_auto_confirm(0.7, was_corrected=False) is False


def test_should_not_auto_confirm_if_corrected():
    assert should_auto_confirm(0.95, was_corrected=True) is False


def test_build_example_record():
    record = build_example_record(
        pg_id="abc-123",
        message="Raj paid 15000",
        intent="PAYMENT_LOG",
        role="admin",
        entities={"name": "Raj", "amount": 15000},
        confidence=0.95,
        source="user_selection",
        confirmed_by="+917845952289",
    )
    assert record["intent"] == "PAYMENT_LOG"
    assert record["source"] == "user_selection"
    assert record["pg_id"] == "abc-123"
    assert record["is_active"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_learning_agent.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Create LearningAgent**

Create `src/llm_gateway/agents/learning_agent.py`:

```python
"""
LearningAgent — background async agent that learns from every interaction.

Runs after every LLM classification (non-blocking). Responsibilities:
1. Log classification to classification_log
2. Save confirmed examples to intent_examples
3. Auto-confirm high-confidence results that weren't corrected
4. Handle user corrections, selections, and clarifications

Each PG learns independently (scoped by pg_id).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import IntentExample, ClassificationLog


# ── Rate limiter (max 1 Groq call per 10s for learning) ──────────────────────
_last_learn_call: float = 0.0
LEARN_COOLDOWN_SECONDS = 10.0


def should_auto_confirm(confidence: float, was_corrected: bool) -> bool:
    """High-confidence classifications that weren't corrected can be auto-confirmed."""
    return confidence > 0.9 and not was_corrected


def build_example_record(
    pg_id: str,
    message: str,
    intent: str,
    role: str,
    entities: dict,
    confidence: float,
    source: str,
    confirmed_by: str,
) -> dict:
    """Build a dict suitable for inserting into intent_examples."""
    return {
        "id": str(uuid.uuid4()),
        "pg_id": pg_id,
        "message_text": message,
        "intent": intent,
        "role": role,
        "entities": entities,
        "confidence": confidence,
        "source": source,
        "confirmed_by": confirmed_by,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


async def log_classification(
    pg_id: str,
    message: str,
    phone: str,
    role: str,
    regex_result: Optional[str],
    regex_confidence: Optional[float],
    llm_result: Optional[str],
    llm_confidence: Optional[float],
    final_intent: str,
    session: AsyncSession,
) -> str:
    """
    Log a classification to the audit trail.
    Returns the classification_log ID.
    """
    log_id = str(uuid.uuid4())
    try:
        await session.execute(
            insert(ClassificationLog).values(
                id=log_id,
                pg_id=pg_id,
                message_text=message,
                phone=phone,
                role=role,
                regex_result=regex_result,
                regex_confidence=regex_confidence,
                llm_result=llm_result,
                llm_confidence=llm_confidence,
                final_intent=final_intent,
                was_corrected=False,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        logger.debug(f"[LearningAgent] Logged classification: {final_intent} for {phone}")
    except Exception as e:
        logger.error(f"[LearningAgent] Failed to log classification: {e}")
        await session.rollback()
    return log_id


async def save_example(
    pg_id: str,
    message: str,
    intent: str,
    role: str,
    entities: dict,
    confidence: float,
    source: str,
    confirmed_by: str,
    session: AsyncSession,
) -> None:
    """
    Save a confirmed example to intent_examples for future few-shot learning.
    Sources: user_correction, user_selection, user_clarification, auto_confirmed, manual_teach
    """
    record = build_example_record(
        pg_id=pg_id,
        message=message,
        intent=intent,
        role=role,
        entities=entities,
        confidence=confidence,
        source=source,
        confirmed_by=confirmed_by,
    )
    try:
        await session.execute(insert(IntentExample).values(**record))
        await session.commit()
        logger.info(
            f"[LearningAgent] Saved example: '{message[:50]}' -> {intent} "
            f"(source={source}, pg={pg_id[:8]})"
        )
    except Exception as e:
        logger.error(f"[LearningAgent] Failed to save example: {e}")
        await session.rollback()


async def learn_from_interaction(
    pg_id: str,
    message: str,
    phone: str,
    role: str,
    regex_result: Optional[str],
    regex_confidence: Optional[float],
    llm_result: Optional[str],
    llm_confidence: Optional[float],
    final_intent: str,
    entities: dict,
    source: str,
    session: AsyncSession,
) -> None:
    """
    Main entry point — called after every LLM classification.
    Logs the classification and saves examples when appropriate.

    This runs as a fire-and-forget background task (non-blocking).
    """
    # 1. Always log
    await log_classification(
        pg_id=pg_id,
        message=message,
        phone=phone,
        role=role,
        regex_result=regex_result,
        regex_confidence=regex_confidence,
        llm_result=llm_result,
        llm_confidence=llm_confidence,
        final_intent=final_intent,
        session=session,
    )

    # 2. Save example if it's a learning signal
    if source in ("user_correction", "user_selection", "user_clarification", "manual_teach"):
        # Explicit user signal — always save
        await save_example(
            pg_id=pg_id,
            message=message,
            intent=final_intent,
            role=role,
            entities=entities,
            confidence=llm_confidence or 0.0,
            source=source,
            confirmed_by=phone,
            session=session,
        )
    elif source == "auto_confirmed" and should_auto_confirm(llm_confidence or 0.0, was_corrected=False):
        # High confidence, no correction — auto-save
        await save_example(
            pg_id=pg_id,
            message=message,
            intent=final_intent,
            role=role,
            entities=entities,
            confidence=llm_confidence or 0.0,
            source="auto_confirmed",
            confirmed_by="system",
            session=session,
        )

    # 3. Skip conversation-only messages (no intent to learn)
    # action="converse" messages are logged but not saved as intent examples
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_learning_agent.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/llm_gateway/agents/learning_agent.py tests/test_learning_agent.py
git commit -m "feat: LearningAgent — background learning with classification log + example saving"
```

---

## Task 9: Wire ConversationAgent into chat_api.py

**Files:**
- Modify: `src/whatsapp/chat_api.py`
- Modify: `src/whatsapp/intent_detector.py`

This is the critical integration task. We add the feature flag gate and route regex misses to ConversationAgent.

- [ ] **Step 1: Add feature flag check and imports to chat_api.py**

At the top of `src/whatsapp/chat_api.py`, after existing imports (around line 39), add:

```python
# PydanticAI agent system (feature flag controlled)
_USE_PYDANTIC_AGENTS = os.getenv("USE_PYDANTIC_AGENTS", "false").lower() == "true"
_DEFAULT_PG_ID = os.getenv("DEFAULT_PG_ID", "")

if _USE_PYDANTIC_AGENTS:
    from src.llm_gateway.agents.conversation_agent import run_conversation_agent
    from src.llm_gateway.agents.learning_agent import learn_from_interaction
    from src.llm_gateway.agents.models import ConversationResult
```

- [ ] **Step 2: Add helper to resolve pg_id**

Add this helper function in chat_api.py (after the imports, before the router):

```python
async def _resolve_pg_id(session: AsyncSession) -> str:
    """Get the active pg_id. For now returns DEFAULT_PG_ID or first active PG."""
    if _DEFAULT_PG_ID:
        return _DEFAULT_PG_ID
    # Fallback: find first active PG
    from src.database.models import PgConfig
    result = await session.execute(
        select(PgConfig).where(PgConfig.is_active == True).limit(1)
    )
    pg = result.scalars().first()
    return str(pg.id) if pg else ""
```

- [ ] **Step 3: Replace the UNKNOWN/low-confidence LLM fallback**

In `chat_api.py`, find the section where `detect_whatsapp_intent` is called (around lines 335-357) and the conversation manager fallback (around lines 429-463). Add the PydanticAI path BEFORE the existing fallback:

Find the block that starts with the AI fallback for UNKNOWN intents. Before the existing `ai = get_claude_client()` call, add:

```python
    # ── PydanticAI agent path (feature flag) ─────────────────────────
    if _USE_PYDANTIC_AGENTS and intent in ("UNKNOWN", "GENERAL"):
        pg_id = await _resolve_pg_id(session)
        if pg_id:
            # Build chat history context
            chat_context = ""  # TODO: load recent chat_messages for this phone
            pending_desc = ""

            agent_result = await run_conversation_agent(
                message=message,
                role=ctx.role,
                phone=ctx.phone,
                pg_id=pg_id,
                session=session,
                chat_history=chat_context,
                pending_context=pending_desc,
            )

            # Route based on agent result
            if agent_result.action == "classify" and agent_result.intent:
                # Agent classified with high confidence — route normally
                intent = agent_result.intent
                entities = agent_result.entities or {}
                entities.update(_extract_entities(message, intent))
                # Fire learning in background
                asyncio.create_task(learn_from_interaction(
                    pg_id=pg_id, message=message, phone=ctx.phone, role=ctx.role,
                    regex_result=None, regex_confidence=None,
                    llm_result=intent, llm_confidence=agent_result.confidence,
                    final_intent=intent, entities=entities, source="auto_confirmed",
                    session=session,
                ))
                # Fall through to normal gatekeeper routing below

            elif agent_result.action == "ask_options" and agent_result.options:
                # Medium confidence — show options
                from src.whatsapp.handlers._shared import _save_pending
                choices_list = [
                    {"seq": i + 1, "intent": opt, "label": _INTENT_LABELS.get(opt, opt)}
                    for i, opt in enumerate(agent_result.options)
                ]
                action_data = json.dumps({"original_message": message, "entities": agent_result.entities or {}})
                await _save_pending(ctx.phone, "INTENT_AMBIGUOUS", action_data, choices_list, session)
                # Fire learning log (not saving example yet — waiting for selection)
                asyncio.create_task(learn_from_interaction(
                    pg_id=pg_id, message=message, phone=ctx.phone, role=ctx.role,
                    regex_result=None, regex_confidence=None,
                    llm_result=str(agent_result.options), llm_confidence=agent_result.confidence,
                    final_intent="INTENT_AMBIGUOUS", entities={}, source="pending_selection",
                    session=session,
                ))
                return agent_result.reply or f"I'm not sure what you need. Did you mean:\n" + "\n".join(
                    f"{c['seq']}. {c['label']}" for c in choices_list
                )

            elif agent_result.action == "converse" and agent_result.reply:
                # Pure conversation — reply naturally
                asyncio.create_task(learn_from_interaction(
                    pg_id=pg_id, message=message, phone=ctx.phone, role=ctx.role,
                    regex_result=None, regex_confidence=None,
                    llm_result="CONVERSE", llm_confidence=agent_result.confidence,
                    final_intent="CONVERSE", entities={}, source="conversation",
                    session=session,
                ))
                return agent_result.reply

            elif agent_result.action == "clarify" and agent_result.reply:
                # Low confidence — ask for clarification
                return agent_result.reply

            # If agent returned classify but no intent, fall through to old path
```

- [ ] **Step 4: Add learning callback for option selection**

Find the INTENT_AMBIGUOUS resolution block (around lines 173-199 where user picks "1", "2", etc.). After the selected intent is resolved and before routing, add:

```python
                # Learn from user selection
                if _USE_PYDANTIC_AGENTS:
                    pg_id = await _resolve_pg_id(session)
                    if pg_id:
                        original_msg = action_data.get("original_message", message)
                        asyncio.create_task(learn_from_interaction(
                            pg_id=pg_id, message=original_msg, phone=phone, role=ctx.role,
                            regex_result=None, regex_confidence=None,
                            llm_result=selected_intent, llm_confidence=0.8,
                            final_intent=selected_intent, entities=action_data.get("entities", {}),
                            source="user_selection", session=session,
                        ))
```

- [ ] **Step 5: Update .env.example**

Add to `.env.example`:

```
# PydanticAI Agent System
USE_PYDANTIC_AGENTS=false
DEFAULT_PG_ID=
```

- [ ] **Step 6: Commit**

```bash
git add src/whatsapp/chat_api.py .env.example
git commit -m "feat: wire ConversationAgent into chat_api — feature flag gated, learning on selection"
```

---

## Task 10: Update role_service.py to read admin phones from pg_config

**Files:**
- Modify: `src/whatsapp/role_service.py`

- [ ] **Step 1: Add pg_config admin phone lookup**

This is additive — the existing `authorized_users` lookup stays. We add a fallback that also checks `pg_config.admin_phones`. In `role_service.py`, after the authorized_users check (around line 56), the existing code already works via the DB. The `ADMIN_PHONE` env var at line 29 is the only hardcoded part.

Replace line 29:
```python
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "")
```

With:
```python
# ADMIN_PHONE env var is kept as a fallback but pg_config.admin_phones is the source of truth
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "")
```

No functional change needed here — admin detection already works via `authorized_users` table. The `pg_config.admin_phones` field is for documentation/reference and future multi-PG routing. The actual access control stays in `authorized_users`.

- [ ] **Step 2: Commit**

```bash
git add src/whatsapp/role_service.py
git commit -m "docs: clarify admin phone lookup — authorized_users is source of truth, pg_config for multi-PG routing"
```

---

## Task 11: Integration test — end-to-end agent flow

**Files:**
- Create: `tests/test_agent_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_agent_integration.py`:

```python
"""
Integration tests for the PydanticAI agent pipeline.
Tests the full flow: message -> ConversationAgent -> structured result.

Requires: GROQ_API_KEY set in environment (calls real LLM).
Skip with: pytest -m "not integration"
"""
import os
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Skip if no GROQ key
pytestmark = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping integration tests"
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_classifies_payment():
    """ConversationAgent classifies a clear payment message."""
    from src.llm_gateway.agents.conversation_agent import _call_llm
    from src.llm_gateway.agents.prompt_builder import build_system_prompt

    pg_config = {
        "pg_name": "Test PG", "brand_name": "Test Bot", "brand_voice": "Be concise.",
        "buildings": [{"name": "MAIN", "floors": 3, "type": "mixed"}],
        "admin_phones": [], "pricing": {"sharing_3": 7500},
        "expense_categories": ["Electricity"], "business_rules": {},
    }
    prompt = build_system_prompt(pg_config, "admin", [], "", "")
    result = await _call_llm(prompt, "Raj paid 15000 cash")

    assert result.action == "classify"
    assert result.intent == "PAYMENT_LOG"
    assert result.confidence > 0.7


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_converses_on_greeting():
    """ConversationAgent handles greetings naturally."""
    from src.llm_gateway.agents.conversation_agent import _call_llm
    from src.llm_gateway.agents.prompt_builder import build_system_prompt

    pg_config = {
        "pg_name": "Test PG", "brand_name": "Test Bot", "brand_voice": "Be friendly.",
        "buildings": [], "admin_phones": [], "pricing": {},
        "expense_categories": [], "business_rules": {},
    }
    prompt = build_system_prompt(pg_config, "admin", [], "", "")
    result = await _call_llm(prompt, "Good morning!")

    assert result.action == "converse"
    assert result.reply is not None
    assert len(result.reply) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_asks_options_on_ambiguous():
    """ConversationAgent shows options for ambiguous messages."""
    from src.llm_gateway.agents.conversation_agent import _call_llm
    from src.llm_gateway.agents.prompt_builder import build_system_prompt

    pg_config = {
        "pg_name": "Test PG", "brand_name": "Test Bot", "brand_voice": "",
        "buildings": [], "admin_phones": [], "pricing": {},
        "expense_categories": [], "business_rules": {},
    }
    prompt = build_system_prompt(pg_config, "admin", [], "", "")
    result = await _call_llm(prompt, "Raj 15000")

    # Could be payment or query — should either classify or ask
    assert result.action in ("classify", "ask_options")
    assert result.confidence > 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_uses_few_shot_examples():
    """ConversationAgent uses injected examples for better classification."""
    from src.llm_gateway.agents.conversation_agent import _call_llm
    from src.llm_gateway.agents.prompt_builder import build_system_prompt

    pg_config = {
        "pg_name": "Test PG", "brand_name": "Test Bot", "brand_voice": "",
        "buildings": [], "admin_phones": [], "pricing": {},
        "expense_categories": [], "business_rules": {},
    }
    examples = [
        {"message": "paisa aaya Raj se", "intent": "PAYMENT_LOG"},
        {"message": "Suresh ka paisa aaya", "intent": "PAYMENT_LOG"},
        {"message": "5000 mila Ahmed se", "intent": "PAYMENT_LOG"},
    ]
    prompt = build_system_prompt(pg_config, "admin", examples, "", "")
    result = await _call_llm(prompt, "Rahul ka paisa aaya 10000")

    assert result.intent == "PAYMENT_LOG"
    assert result.confidence > 0.7
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_agent_integration.py -v -m integration`
Expected: PASS (if GROQ_API_KEY is set)

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_integration.py
git commit -m "test: integration tests for ConversationAgent — payment, greeting, ambiguous, few-shot"
```

---

## Task 12: Run golden test suite + verify no regression

**Files:** None (testing only)

- [ ] **Step 1: Run golden tests with flag OFF**

Ensure `USE_PYDANTIC_AGENTS=false` in `.env`, then:

Run: `python tests/eval_golden.py`
Expected: Same pass rate as before (~76.5% regex). No regression.

- [ ] **Step 2: Run golden tests with flag ON**

Set `USE_PYDANTIC_AGENTS=true` and `DEFAULT_PG_ID=<cozeevo-uuid>` in `.env`, then:

Run: `python tests/eval_golden.py`
Expected: Higher pass rate (agent catches UNKNOWN cases). No existing tests should break.

- [ ] **Step 3: Run all unit tests**

Run: `python -m pytest tests/ -v --ignore=tests/eval_golden.py`
Expected: All pass

- [ ] **Step 4: Show results to Kiran**

Display test results before proceeding to any push.

---

## Task 13: Update .env on VPS + deploy

**Files:**
- Modify: `.env` (on VPS)

- [ ] **Step 1: SSH to VPS and update .env**

```bash
ssh root@187.127.130.194
cd /opt/pg-accountant
# Add to .env:
echo 'USE_PYDANTIC_AGENTS=false' >> .env
echo 'DEFAULT_PG_ID=' >> .env  # Will be filled after migration
```

- [ ] **Step 2: Pull code and run migration**

```bash
git pull
pip install pydantic-ai[groq]
python -m src.database.migrate_all
```

- [ ] **Step 3: Get Cozeevo pg_id and update .env**

```bash
python -c "
import asyncio
from src.database.db_manager import get_engine
from sqlalchemy import text
async def get_id():
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(text(\"SELECT id FROM pg_config WHERE pg_name = 'Cozeevo Co-living'\"))
        print(r.fetchone()[0])
asyncio.run(get_id())
"
# Copy the UUID and set it:
# sed -i 's/DEFAULT_PG_ID=/DEFAULT_PG_ID=<the-uuid>/' .env
```

- [ ] **Step 4: Deploy with flag OFF first**

```bash
systemctl restart pg-accountant
# Verify: curl https://api.getkozzy.com/healthz
```

- [ ] **Step 5: Enable flag and test**

After confirming old functionality works:
```bash
sed -i 's/USE_PYDANTIC_AGENTS=false/USE_PYDANTIC_AGENTS=true/' .env
systemctl restart pg-accountant
```

Test by sending WhatsApp messages: "Good morning", "Who are you?", "Raj paid 15000"

- [ ] **Step 6: Commit .env.example updates**

```bash
git add .env.example
git commit -m "deploy: enable PydanticAI agents on VPS with Cozeevo pg_config"
```

---

## Task 14: Update docs + changelog

**Files:**
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/SYSTEM_SPEC.md` (if any changes during implementation)
- Modify: `CLAUDE.md` (update active files list)

- [ ] **Step 1: Update CHANGELOG.md**

Add new version entry at top:

```markdown
## [1.21.0] — 2026-04-08 — Kozzy AI Platform: PydanticAI + Multi-Tenant Foundation

### Added
- **pg_config table** — multi-tenant configuration: buildings, rooms, pricing, bank config, personality per PG
- **intent_examples table** — self-learning intent database, scoped per PG
- **classification_log table** — audit trail of every intent classification
- **ConversationAgent (PydanticAI)** — structured LLM output, few-shot examples, natural conversation
- **LearningAgent** — background async learning from corrections, selections, and confirmations
- **Dynamic system prompt** — built from pg_config, role-aware, with injected few-shot examples
- **Confidence routing** — >0.9 execute, 0.6-0.9 show options, <0.6 ask clarification
- **Feature flag** — USE_PYDANTIC_AGENTS=false for safe rollout, instant rollback
- **Cozeevo seeded** as first PG tenant in pg_config
- **SYSTEM_SPEC.md** — single-file platform specification (replaces reading 16 docs)

### Architecture
- Regex stays as fast path (97%). PydanticAI handles misses with structured output.
- Every LLM classification feeds the learning flywheel (intent_examples grows autonomously).
- All PG-specific config in pg_config — no hardcoded strings in agent code.
- Handlers unchanged — agents output same dict shape, zero handler modifications.
```

- [ ] **Step 2: Update CLAUDE.md active files**

Add to the Active files table:

```markdown
| `src/llm_gateway/agents/conversation_agent.py` | PydanticAI ConversationAgent |
| `src/llm_gateway/agents/learning_agent.py` | Background learning agent |
| `src/llm_gateway/agents/models.py` | Pydantic response models |
| `src/llm_gateway/agents/prompt_builder.py` | Dynamic prompt from pg_config |
| `src/llm_gateway/agents/tools.py` | Agent tools (search examples, tenant context) |
| `docs/SYSTEM_SPEC.md` | Master platform specification |
```

- [ ] **Step 3: Commit**

```bash
git add docs/CHANGELOG.md CLAUDE.md
git commit -m "docs: changelog v1.21.0 + update CLAUDE.md active files for agent system"
```

---

## Summary

| Task | What | Est. |
|---|---|---|
| 1 | Add pydantic-ai dep | 2 min |
| 2 | DB models (PgConfig, IntentExample, ClassificationLog) | 5 min |
| 3 | DB migration + Cozeevo seed | 5 min |
| 4 | Pydantic response models | 3 min |
| 5 | Prompt builder (dynamic from pg_config) | 5 min |
| 6 | Agent tools (search examples, tenant context) | 5 min |
| 7 | ConversationAgent | 5 min |
| 8 | LearningAgent | 5 min |
| 9 | Wire into chat_api.py (feature flag) | 10 min |
| 10 | Role service update | 2 min |
| 11 | Integration tests | 5 min |
| 12 | Golden test suite + regression check | 5 min |
| 13 | VPS deploy | 10 min |
| 14 | Docs + changelog | 5 min |
