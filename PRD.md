# PG Ledger AI — Product Requirements Document
> Living document. Update after every workflow is tested and deployed.
> Last updated: 2026-03-11

---

## 1. Product Vision

**WhatsApp-first operating system for PG and hostel owners** that automates rent tracking, payment reconciliation, and tenant management.

Owner sends a WhatsApp message → AI understands → database updates → owner gets confirmation.
No app. No login. No accounting knowledge needed.

---

## 2. Primary User

- PG owner managing **20–2000 rooms**
- Non-technical, uses WhatsApp daily
- Minimal accounting knowledge
- Wants instant answers

---

## 3. Core Problems Solved

| Problem | Solution |
|---|---|
| Don't know who paid rent | Payment logging + query via WhatsApp |
| UPI payments with unclear names | AI reconciliation matches bank txn to tenant |
| Deposit disputes | Deposits tracked separately in ledger |
| Manual rent reminders | Automated WhatsApp reminders |
| No financial visibility | On-demand reports via WhatsApp |

---

## 4. Database Schema (PostgreSQL / Supabase)

### Core Tables

```sql
-- authorized_users: Who can talk to the bot
authorized_users(id, phone, role[owner|tenant], property_id, is_active)

-- properties: PG buildings
properties(id, name, address, owner_phone, created_at)

-- rooms: Room inventory
rooms(id, property_id, room_number, capacity, rent_amount, status[vacant|occupied])

-- tenants: Tenant records
tenants(id, property_id, room_id, name, phone, rent_amount, deposit_paid,
        check_in_date, check_out_date, status[active|vacated])

-- transactions: All payments
transactions(id, tenant_id, property_id, amount, txn_type[rent|deposit|maintenance],
             payment_mode[upi|cash|bank], reference_id, txn_date,
             unique_hash, confirmed, notes, created_at)

-- bank_payments: Raw imported bank/UPI data
bank_payments(id, property_id, amount, sender_name, reference_id,
              payment_date, matched_tenant_id, match_status[pending|matched|unmatched])

-- conversation_state: Short-term memory (5 min TTL)
conversation_state(id, phone, state, data JSONB, expires_at)

-- audit_logs: Every action
audit_logs(id, action, user_phone, property_id, details JSONB, created_at)
```

---

## 5. Security Architecture

1. **Sender Verification** — Every message checks `authorized_users` table. Unknown numbers get rejected.
2. **Role Isolation** — Owners get full control. Tenants get read-only (balance check only).
3. **Webhook Signature** — Meta webhook verified via `hub.verify_token`.
4. **Idempotency** — `unique_hash` on transactions prevents double-counting.
5. **Transaction Confirmation** — Bot asks "YES to confirm?" before logging payments.
6. **Audit Logs** — Every action logged with phone + timestamp.
7. **Conversation TTL** — State expires in 5 minutes. No stale memory.

---

## 6. AI Strategy (Low Token Usage)

```
Incoming Message
      ↓
Regex Parser (handles ~85% — no AI cost)
      ↓
Rule Parser (structured commands)
      ↓
AI Fallback (only for ambiguous natural language)
```

**AI used ONLY for:** natural language parsing, fuzzy name matching
**AI NEVER used for:** calculations, DB writes, financial logic

**Model:** GPT-4o-mini (primary) / Claude Haiku (fallback)

---

## 7. The 10 Workflows (n8n)

| # | Workflow | Trigger | Status |
|---|---|---|---|
| WA-01 | WhatsApp Router | Webhook (every message) | 🔨 Building |
| WA-02 | Message Parser | Called by WA-01 | ⏳ Next |
| WA-03 | Payment Logger | Called by WA-01 | ⏳ Pending |
| WA-04 | Tenant Creator | Called by WA-01 | ⏳ Pending |
| WA-05 | Rent Reminder Scheduler | Daily cron 10am | ⏳ Pending |
| WA-06 | Bank Statement Importer | Every 5 min / manual | ⏳ Pending |
| WA-07 | Payment Reconciliation | Called by WA-01 | ⏳ Pending |
| WA-08 | Dashboard Metrics | Hourly cron | ⏳ Pending |
| WA-09 | Tenant Checkout | Called by WA-01 | ⏳ Pending |
| WA-10 | Weekly Financial Report | Sunday 9am cron | ⏳ Pending |

---

## 8. WhatsApp Commands (Owner UX)

```
💳 Payments
  "Rahul paid 8500"
  "Received 5000 from room 204"

👤 Tenant Management
  "Add tenant Rahul room 204 rent 8500"
  "Rahul is vacating"

🔍 Queries
  "Who hasn't paid?"
  "Pending rent this month?"
  "Balance for Rahul?"

📊 Reports
  "Show report"
  "Occupancy today?"
  "Revenue this month"

🔔 Reminders
  "Send rent reminders"
  "Remind room 204"

❓ Help
  "help" or "menu"
```

---

## 9. Non-Goals (v1)

- GST filing
- Full accounting (P&L, balance sheet)
- Inventory management
- Marketplace listings
- Tenant-facing app

---

## 10. Success Metrics

Owner can WhatsApp-query and get answer in < 5 seconds:
- "Who hasn't paid rent?" → list of names
- "Expected rent this month?" → ₹X from Y tenants
- "Current occupancy?" → X/Y rooms occupied

---

## 11. Tech Stack

| Layer | Tool |
|---|---|
| Automation | n8n (Docker self-hosted or n8n.cloud) |
| Database | Supabase (PostgreSQL) |
| WhatsApp | Meta WhatsApp Cloud API (free) |
| AI | GPT-4o-mini / Claude Haiku |
| File Parsing | Python FastAPI (bank statements only) |
| Hosting | Any VPS or Railway.app |
