# Cozeevo PG Accountant — Product Requirements Document
> Living document. Update after every major release.
> Last updated: 2026-03-14 (v1.4.0)

---

## 1. Product Vision

**What:** AI-powered bookkeeping + WhatsApp bot for PG (Paying Guest) businesses.

**Who:** PG owners in Bangalore/Hyderabad managing 50–200 rooms and 100–400 tenants.

**Why:** PG owners currently use paper registers or WhatsApp manually. No affordable software handles the PG business model (room-based rent, security deposits, prorated first month, daily stays, shared rooms, monthly cycles).

**SaaS Future:** Same codebase deployed per PG customer — each gets their own Supabase project + WhatsApp Business number + `.env` config. No shared state between customers.

---

## 2. Users and Roles

| Role | Identified by | Capabilities |
|------|--------------|-------------|
| `admin` | `authorized_users` table, role=admin | Full CRUD, add/remove authorized users, all intents |
| `power_user` | `authorized_users` table, role=power_user | Full business access — same as admin except user management |
| `key_user` | `authorized_users` table, role=key_user | Log payments + view assigned tenants only |
| `tenant` | Phone number in `tenants` table | Read-only: own balance, payment history, complaints, rules |
| `lead` | Unknown phone number | Room enquiry, pricing, availability, visit booking |
| `blocked` | Rate limit exceeded (10 msg/10min, 50/day) | Silently ignored — no reply |

Anti-spam applies to **all roles including admin** (prevents accidental flood).

---

## 3. Core Features (v1.4.0)

### 3.1 AccountWorker — Financial Intents

Accessed by admin/power_user/key_user when intent is financial.
All responses use `Rs.` prefix and show full due/paid/balance breakdowns.

| Intent | Trigger examples | Action |
|--------|-----------------|--------|
| `PAYMENT_LOG` | "Raj paid 15000 upi" | Record payment against tenant's rent_schedule |
| `QUERY_DUES` | "who hasn't paid", "dues this month" | List tenants with outstanding balances |
| `QUERY_TENANT` | "Raj balance", "show Arjun's account" | Full account: due, paid, balance, last payment |
| `ADD_EXPENSE` | "maintenance 5000 cash" | Log expense with category + payment mode |
| `QUERY_EXPENSES` | "expenses this month", "show expenses" | Expense breakdown by category |
| `REPORT` | "monthly report", "summary" | Revenue, occupancy, outstanding, expenses |
| `RENT_CHANGE` | "change rent for room 205 to 12000" | Update rate_card from next month |
| `RENT_DISCOUNT` | "give Raj 500 discount" | One-time rent reduction for specific tenant |
| `VOID_PAYMENT` | "void payment 42" | Mark payment as void (is_void=true, never deleted) |
| `ADD_REFUND` | "refund 5000 to Raj" | Log security deposit or other refund |
| `QUERY_REFUNDS` | "show refunds", "refund history" | List all refunds for a tenant |

### 3.2 OwnerWorker — Operational Intents

Accessed by admin/power_user/key_user for non-financial operations.

| Intent | Trigger examples | Action |
|--------|-----------------|--------|
| `ADD_TENANT` | "add tenant Arjun 9876543210 room 204" | Create Tenant + Tenancy record |
| `START_ONBOARDING` | "start onboarding for Arjun 9876543210" | Begin 12-step KYC flow (see §4) |
| `UPDATE_CHECKIN` | "checkin date for Raj is March 1" | Correct check-in date |
| `CHECKOUT` | "Raj is leaving", "checkout Raj" | Schedule checkout |
| `SCHEDULE_CHECKOUT` | "Raj checkout on 31st March" | Set future checkout date |
| `NOTICE_GIVEN` | "Raj gave notice" | Mark notice period started |
| `RECORD_CHECKOUT` | "record checkout Raj" | Begin 5-step offboarding checklist (see §4) |
| `LOG_VACATION` | "Raj on vacation 10 days" | Log vacation (affects food billing) |
| `COMPLAINT_REGISTER` | "AC not working in room 205" | Log maintenance complaint |
| `QUERY_VACANT_ROOMS` | "vacant rooms", "empty rooms" | List unoccupied rooms |
| `QUERY_OCCUPANCY` | "occupancy", "how full are we" | Occupancy % + room count |
| `QUERY_EXPIRING` | "who is leaving this month" | Tenants with upcoming checkouts |
| `REMINDER_SET` | "remind Raj about rent on 5th" | Set one-time reminder |
| `SEND_REMINDER_ALL` | "send rent reminders" | Bulk reminder to all tenants with dues |
| `ADD_PARTNER` | "add partner 9876543210" | Add power_user to authorized_users |
| `RULES` | "pg rules", "house rules" | Show 19 PG rules |
| `HELP` | "help", "commands" | Full command menu |

### 3.3 TenantWorker — Tenant Self-Service

Accessed by tenants (phones in `tenants` table). Read-only.

| Intent | Trigger | Response |
|--------|---------|---------|
| `MY_BALANCE` | "my balance", "how much do I owe" | Due amount + breakdown |
| `MY_PAYMENTS` | "my payments", "payment history" | Last 6 payments with dates |
| `MY_DETAILS` | "my details", "my room" | Room number, check-in date, rent amount |
| `COMPLAINT_REGISTER` | "AC not working", "water problem" | Log complaint (auto-categorized) |
| `RULES` | "rules", "regulations" | 19 PG house rules |

### 3.4 LeadWorker — Room Enquiry Bot

Accessed by unknown phone numbers. Conversational AI via Ollama.

| Intent | Trigger | Response |
|--------|---------|---------|
| `ROOM_PRICE` | "price", "rent", "how much" | Room pricing by type |
| `AVAILABILITY` | "available", "any rooms" | Current vacant rooms |
| `ROOM_TYPE` | "single room", "double room" | Room type details |
| `VISIT_REQUEST` | "visit", "tour", "see the room" | Collect name + preferred time, save as Lead |
| `GENERAL` | Anything else | Conversational AI response via Ollama |

---

## 4. Multi-Step Flows

### 4.1 Tenant KYC Onboarding (12 steps)

**Trigger:** Owner sends "start onboarding for [name] [phone]"

**Flow:**
1. Owner handler creates `Tenant` + `OnboardingSession` (48-hr TTL)
2. When tenant messages, `chat_api` detects active session BEFORE intent detection
3. Bot walks tenant through 12 questions:

```
ask_dob → ask_father_name → ask_father_phone → ask_address →
ask_email (skippable) → ask_occupation (skippable) → ask_gender →
ask_emergency_name → ask_emergency_relationship → ask_emergency_phone →
ask_id_type → ask_id_number → done
```

4. On completion: data saved to `Tenant` record, `OnboardingSession.completed = True`

Accepted ID types: Aadhar, Passport, Driving License, PAN Card, Voter ID, Ration Card

### 4.2 Checkout Checklist (5 steps)

**Trigger:** Owner sends "record checkout [name]"

**Flow:**
1. Owner handler finds tenant via fuzzy name search
2. Saves `PendingAction` with step=ask_cupboard_key
3. `resolve_pending_action` walks through:

```
cupboard key returned? → main key returned? → any damage? →
pending dues? → deposit refund amount + date
```

4. On completion: creates `CheckoutRecord`, marks `Tenancy.status = exited`, sets `checkout_date = today`

---

## 5. Architecture

### 5.1 Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| API | FastAPI + Uvicorn (Python 3.11) | Free |
| Database | Supabase PostgreSQL (cloud) | Free tier |
| WhatsApp | Meta Cloud API | Free (1,000 msgs/day free tier) |
| Automation | n8n (Docker, self-hosted) | Free |
| LLM | Ollama llama3.2 (local) | Free |
| Intent detection | Python regex rules (97%) | Free |
| LLM fallback | Ollama / Groq / Anthropic (3%) | Free/Low |

### 5.2 Gatekeeper Routing

Single `gatekeeper.py` is the only file that knows which worker handles what:

```
(role=admin/power_user/key_user) + FINANCIAL_INTENT → AccountWorker
(role=admin/power_user/key_user) + OPERATIONAL_INTENT → OwnerWorker
role=tenant → TenantWorker
role=lead/unknown → LeadWorker
```

### 5.3 Database (21 Tables, 7 Layers)

```
L0 Permanent:    investment_expenses, pg_contacts
L1 Master:       properties, rooms, rate_cards, tenants, staff, food_plans, expense_categories
L2 Tenancy:      tenancies
L3 Transactions: rent_schedule, payments, refunds, expenses
L4 Bot:          leads, rate_limit_log, whatsapp_log, conversation_memory
L5 Operational:  vacations, reminders, onboarding_sessions, checkout_records, pending_actions
L6 Access:       authorized_users
```

### 5.4 n8n Integration

Only **one** n8n workflow: `WA-01-whatsapp-router.json`

```
Meta Cloud API webhook
      ↓
n8n: WhatsApp Trigger → Extract Message → Is Text? → Call FastAPI → Should Reply? → Send Reply
      POST /api/whatsapp/process
      Body: { phone, message, message_id }
      Response: { reply, intent, role, confidence, skip }
```

n8n is a thin pipe only — all business logic lives in FastAPI.

---

## 6. AI Usage Policy

| Task | Method | Cost |
|------|--------|------|
| Intent detection (97%) | Regex rules (`intent_detector.py`) | Free |
| Intent detection (ambiguous ~3%) | Ollama llama3.2 (local) | Free |
| Lead conversation | Ollama llama3.2 (local) | Free |
| Merchant categorization (unknown) | Ollama / Groq | Free/Low |
| All financial math | Python only (`property_logic.py`) | Free |
| Reports, dedup, reconciliation | Python only | Free |

Switch provider: set `LLM_PROVIDER=groq` or `LLM_PROVIDER=anthropic` in `.env`.

---

## 7. Anti-Spam Policy

- 10 messages per 10 minutes per phone number
- 50 messages per day per phone number
- Applies to ALL roles including admin
- Blocked callers: no reply, no processing — silently dropped
- Tracked in `rate_limit_log` table

---

## 8. Roadmap

### Completed (v1.0.0 – v1.4.0)
- [x] 21-table database schema + Supabase setup
- [x] Excel import (234 tenants, 292 tenancies, 705 payments)
- [x] 6-tier role system + phone normalization
- [x] Rules-based intent detection (97% coverage)
- [x] AccountWorker — 11 financial intents
- [x] OwnerWorker — 18+ operational intents
- [x] TenantWorker — 5 self-service intents
- [x] LeadWorker — conversational AI sales bot
- [x] Gatekeeper routing (role + intent → worker)
- [x] 12-step KYC onboarding flow (digitized registration form)
- [x] 5-step checkout checklist (offboarding)
- [x] 19 PG house rules (RULES intent)
- [x] investment_expenses table (Rs 2.05 Cr tracked)
- [x] pg_contacts table (62 maintenance contacts)
- [x] Git version control + GitHub repository

### Next: Local Testing
- [ ] Install Docker Desktop + start n8n
- [ ] ngrok tunnel → Meta Cloud API webhook
- [ ] End-to-end WhatsApp test

### Next: Cloud Deployment
- [ ] Hostinger VPS KVM 1 (~$5/month)
- [ ] systemd service for FastAPI
- [ ] nginx + SSL (certbot)
- [ ] n8n on same server (Docker)

### Future: SaaS
- [ ] Per-customer onboarding script (new Supabase project + .env)
- [ ] Admin dashboard (web UI for non-WhatsApp management)
- [ ] Automated rent reminders (scheduled, not manual)
- [ ] PDF rent receipts
- [ ] Salary payment tracking for staff

### Future: Financial Reconciliation Engine (`finance/` package)

A second major selling point — multi-source UPI + bank statement reconciliation. See [FINANCIAL_VISION.md](FINANCIAL_VISION.md) for full design.

**What it solves:** A single payment appears in 3 places (bank statement + UPI app + merchant gateway). The engine merges duplicates, keeps one canonical record, and enriches it with metadata.

**Already built (Phase 0):**
- `scripts/bank_statement_extractor.py` — YES Bank PDF extraction (word-coordinate layout)
- `scripts/pnl_report.py` — EXPENSE_RULES keyword classifier (15 categories)

**Planned package structure:**
```
finance/                    ← completely self-contained, zero imports from src/
  extractors/               ← pdf_extractor.py, csv_extractor.py
  parsers/                  ← paytm_parser.py, phonepe_parser.py, bank_parser.py
  matching/                 ← fingerprint.py, transaction_matcher.py
  categorization/           ← categorizer.py (EXPENSE_RULES → YAML config)
  output/                   ← excel_exporter.py
  config/                   ← column_mappings.yaml, category_rules.yaml
  main.py                   ← standalone CLI entry point

src/whatsapp/handlers/
  financial_worker.py       ← thin adapter: WhatsApp intent → finance.main
```

**Sources supported:** YES Bank, HDFC, Paytm, PhonePe, Google Pay, Razorpay, BharatPe

**Integration:** FinancialWorker routes through the same Gatekeeper — same WhatsApp number, same role system, one combined AI assistant.
