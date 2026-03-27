# ARCHITECTURE.md — System Overview & Component Map

---

## 1. System Overview

PG Accountant is a WhatsApp bot for managing paying guest hostels. Built on FastAPI + Supabase (PostgreSQL) + Groq LLM + Meta WhatsApp Cloud API. The bot handles 97% of requests with regex-based intent detection, using AI only for ambiguous or conversational intents. Live on Hostinger VPS (api.getkozzy.com).

---

## 2. Component Diagram

```
  WhatsApp User
       │
       │ Meta Cloud API
       ▼
  ┌──────────────────────┐
  │ nginx (SSL)          │  api.getkozzy.com:443
  │ Let's Encrypt        │
  └──────────┬───────────┘
             │ proxy_pass :8000
             ▼
  ┌────────────────────────────────────────────────────────┐
  │  FastAPI (port 8000, systemd)                          │
  │                                                        │
  │  webhook_handler.py                                    │
  │  ├─ GET /webhook/whatsapp  (Meta verification)         │
  │  ├─ POST /webhook/whatsapp (receive messages)          │
  │  ├─ Voice → Groq Whisper transcription                 │
  │  └─ Bank PDF → parse + classify                        │
  │       │                                                │
  │       ▼                                                │
  │  chat_api.py (main brain)                              │
  │  ├─ 1. Rate limit + role_service.py                    │
  │  ├─ 2. Load chat history (last 5 msgs)                 │
  │  ├─ 3. Check pending actions                           │
  │  ├─ 4. intent_detector.py (regex, 97% accuracy)        │
  │  ├─ 5. Follow-up detection (pronouns)                  │
  │  ├─ 6. AI fallback (Groq) if UNKNOWN                   │
  │  └─ 7. gatekeeper.py → route to handler                │
  │       │                                                │
  │       ├── account_handler.py  (financial)               │
  │       ├── owner_handler.py    (operational)             │
  │       ├── tenant_handler.py   (disabled → None)         │
  │       ├── lead_handler.py     (disabled → None)         │
  │       └── _shared.py          (fuzzy search, pending)   │
  │                                                        │
  │  Also:                                                 │
  │  ├─ dashboard_router.py  → REST API for web dashboard  │
  │  ├─ gsheets.py           → Google Sheets read/write    │
  │  └─ finance_handler.py   → bank statement processing   │
  │                                                        │
  └───────────────┬────────────────────────────────────────┘
                  │
                  ▼
  ┌────────────────────────────────────────┐
  │ Supabase PostgreSQL (26 tables)        │
  │ tenants, tenancies, payments,          │
  │ rent_schedule, rooms, complaints,      │
  │ chat_messages, activity_log, ...       │
  └────────────────────────────────────────┘
```

---

## 3. Request Lifecycle

### Phase 1: Reception
1. Meta sends POST to `/webhook/whatsapp`
2. `webhook_handler.py` verifies HMAC signature
3. Extract message from nested Meta JSON
4. Voice? → Groq Whisper transcription
5. Bank PDF? → save + parse in background

### Phase 2: Processing (chat_api.py)
6. **Rate limit** — 10/10min, 50/day per phone
7. **Role detection** — authorized_users → tenants → lead
8. **Load chat history** — last 5 messages for context
9. **Check pending actions** — disambiguation, clarification, confirmation
10. **Intent detection** — learned rules → 50+ regex patterns → AI fallback
11. **Follow-up detection** — pronoun patterns re-route to QUERY_TENANT
12. **Route** via gatekeeper → correct handler

### Phase 3: Handling
13. Handler executes (DB read/write, calculations)
14. If ambiguous → save pending action, ask user to clarify
15. If clear → execute and return reply

### Phase 4: Response
16. Log to whatsapp_log + chat_messages
17. Send reply via Meta Graph API (background task)
18. Return 200 OK

---

## 4. Component Details

### webhook_handler.py
**File:** `src/whatsapp/webhook_handler.py`
- Meta webhook entry point
- Signature verification, message extraction
- Media download (voice, PDFs, images)
- Voice transcription via Groq Whisper
- Calls `chat_api.process_message()`

### chat_api.py
**File:** `src/whatsapp/chat_api.py`
- Main processing pipeline (9 phases)
- Rate limiting, role detection, pending action resolution
- Intent detection orchestration
- Follow-up detection from chat context
- Message logging (whatsapp_log + chat_messages)
- Key class: `OutboundReply(reply, intent, role, confidence, skip, interactive_payload)`

### role_service.py
**File:** `src/whatsapp/role_service.py`
- `get_caller_context(phone, session)` → CallerContext
- Lookup: authorized_users → tenants → lead
- Rate limit enforcement (10/10min, 50/day)
- Phone normalization (any format → 10-digit)

### intent_detector.py
**File:** `src/whatsapp/intent_detector.py`
- `detect_intent(message, role)` → IntentResult
- 50+ regex patterns per role
- Learned rules from `data/learned_rules.json`
- Entity extraction: amount, name, room, date, month, payment mode
- Confidence: 0.95+ (high), 0.70-0.88 (medium), <0.70 (reject)

### gatekeeper.py
**File:** `src/whatsapp/gatekeeper.py`
- `route(intent, entities, ctx, message, session)` → str | None
- Owner + financial → account_handler
- Owner + operational → owner_handler
- Tenant → None (disabled)
- Lead → None (disabled)
- Receptionist: blocked from REPORT, BANK_REPORT, BANK_DEPOSIT_MATCH

### account_handler.py
**File:** `src/whatsapp/handlers/account_handler.py`
- 13 financial intents: PAYMENT_LOG, QUERY_DUES, REPORT, RENT_CHANGE, VOID_PAYMENT, etc.
- Payment processing with duplicate detection (24hr window)
- RentSchedule status updates (pending → paid/partial)
- Google Sheets write-back (fire-and-forget)

### owner_handler.py
**File:** `src/whatsapp/handlers/owner_handler.py`
- 28 operational intents: ADD_TENANT, CHECKOUT, OCCUPANCY, COMPLAINTS, ACTIVITY_LOG, etc.
- Multi-step forms (onboarding: 12 steps, checkout: 5 steps)
- Complaint auto-resolve from activity log
- Pending action resolver for all confirmation flows

### _shared.py
**File:** `src/whatsapp/handlers/_shared.py`
- Fuzzy tenant search (name, room)
- Disambiguation (numbered choice lists)
- Pending action creation (30min expiry)
- Greeting helpers, affirmative/negative detection

### dashboard_router.py
**File:** `src/api/dashboard_router.py`
- REST API for web dashboard (static/mockup_c.html)
- KPIs: occupancy, collection rate, dues outstanding
- Month picker, property filter (THOR/HULK)
- Dynamic bed count from rooms table

### gsheets.py
**File:** `src/integrations/gsheets.py`
- Google Sheets read/write via service account
- Payment write-back: auto-detect month column
- 5-minute worksheet cache
- Fire-and-forget (errors don't block payments)

---

## 5. Role System

| Role | Source | Auto-Reply | Access |
|------|--------|------------|--------|
| admin | authorized_users | Yes | Everything |
| power_user | authorized_users | Yes | Full business |
| key_user | authorized_users | Yes | Scoped operations |
| receptionist | authorized_users | Yes | Ops + finance (no reports) |
| tenant | tenants table | **No** | Disabled |
| lead | default | **No** | Disabled |
| blocked | rate limit exceeded | No | Ignored |

---

## 6. Intent Detection Pipeline

```
Message → Learned Rules (JSON) → Regex Patterns (50+) → AI Fallback (Groq)
                                                              │
                                         ┌────────────────────┤
                                         │                    │
                                    confidence            UNKNOWN
                                    ≥ 0.70?                   │
                                    │   │                Save to
                                   Yes  No              pending_learning
                                    │   │
                                Route  SYSTEM_HARD_UNKNOWN
                                    │  "Could you rephrase?"
                                    ▼
                               gatekeeper.route()
```

**Accuracy:** 97% on 177-test evaluation suite. AI costs near zero.

---

## 7. Pending Actions State Machine

| State | Trigger | User Reply | Resolution |
|-------|---------|------------|------------|
| INTENT_AMBIGUOUS | 2+ regex matches | Pick number | Re-route chosen intent |
| AWAITING_CLARIFICATION | Missing month/name | Provide data | Merge + re-route |
| CONFIRM_PAYMENT_LOG | Payment details shown | Yes/No | Log or cancel |
| CONFIRM_ADD_EXPENSE | Expense shown | Yes/No | Log or cancel |
| Multi-step form | Onboarding/checkout | Answer each step | Progress through form |

- **Expiry:** 30 minutes
- **`__KEEP_PENDING__`:** Handler reply prefix = keep pending alive for next turn

---

## 8. Chat History & Follow-up Detection

**Storage:** `chat_messages` table — all inbound/outbound messages, never deleted.

**Context:** Last 5 messages loaded per request for AI context.

**Follow-up:** When intent=UNKNOWN and message contains pronouns ("how much", "his payments", "uska"):
1. Extract room/name from last bot response
2. Re-route as QUERY_TENANT with injected context
3. Example: "Raj balance" → bot responds → "his payments" → auto-routes to Raj's payment history

---

## 9. Error Handling

| Scenario | Response |
|----------|----------|
| Rate limit exceeded | Silent (skip=True, no reply) |
| Low confidence (<0.70) | "Could you rephrase? Type *help* for options." |
| Handler exception | "Sorry, something went wrong. Please try again." |
| Voice transcription fails | "Couldn't understand voice note. Please type instead." |
| DB unreachable | App won't start (fails at lifespan init) |
| Groq API fails | Fall back to UNKNOWN, log error |
| Pending expired (>30min) | Treat as fresh message |

---

## 10. Key Files

| File | Lines | Purpose |
|------|-------|---------|
| main.py | ~300 | App entry, routers, middleware |
| webhook_handler.py | ~450 | Meta webhook, media, transcription |
| chat_api.py | ~600 | Main pipeline (all phases) |
| intent_detector.py | ~600 | Regex rules, entity extraction |
| role_service.py | ~180 | Role detection, rate limiting |
| gatekeeper.py | ~70 | (role, intent) → handler routing |
| account_handler.py | ~1250 | 13 financial intents |
| owner_handler.py | ~1850 | 28 operational intents |
| tenant_handler.py | ~550 | Tenant self-service (disabled) |
| lead_handler.py | ~350 | Sales conversation (disabled) |
| _shared.py | ~210 | Fuzzy search, disambiguation |
| dashboard_router.py | ~500 | REST API for web dashboard |
| models.py | ~1000 | 26 ORM table definitions |
| gsheets.py | ~450 | Google Sheets integration |
| pnl_classify.py | ~250 | Bank transaction classification |
