# BOT_FLOWS.md — WhatsApp Bot Intent Catalog & Message Flows

Complete reference for all intents, role-based routing, pending state machine, and interaction patterns.

---

## 1. Intent Catalog

| Intent | Example Messages | Handler | Role | What It Does |
|--------|------------------|---------|------|--------------|
| PAYMENT_LOG | "Raj paid 15000 upi", "Raj paied 15000" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Log rent payment |
| QUERY_DUES | "who owes", "pending dues", "dues" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: List tenants with outstanding dues |
| QUERY_TENANT | "Raj balance", "room 203 balance" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Tenant account: rent, paid, balance, history |
| ADD_EXPENSE | "electricity 5000 upi" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Log operational expense |
| QUERY_EXPENSES | "total expenses" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Expense breakdown by category/month |
| REPORT | "monthly report", "march report" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Monthly financial report |
| RENT_CHANGE | "change rent for Raj to 20000" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Update tenant rent |
| RENT_DISCOUNT | "concession 2000 for Raj" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Apply one-time discount |
| VOID_PAYMENT | "void 15000 payment" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Mark payment as void |
| VOID_EXPENSE | "void electricity expense" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Mark expense as void |
| DEPOSIT_CHANGE | "update deposit for Raj to 50000" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Update security deposit |
| ADD_REFUND | "return deposit 50000 to Raj" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Initiate deposit refund |
| QUERY_REFUNDS | "pending refunds" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: List refunds |
| BANK_REPORT | "bank report March" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Parse bank statement → P&L |
| BANK_DEPOSIT_MATCH | "match deposits" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Match bank deposits to payments |
| QUERY_UNIT_ECONOMICS | "unit economics", "revenue per bed", "cost per bed", "avg rent", "collection rate" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: Per-bed KPIs: True Revenue, OPEX, EBITDA per bed, avg rent, occupancy, collection rate |
| DASHBOARD_SUMMARY | "show dashboard", "dashboard summary", "all stats" | — (gatekeeper) | all staff | **APP ONLY — blocked on WhatsApp** (security decision 25 May 2026; reply: use the Kozzy app). Was: All 6 dashboard rows: occupancy, buildings, collection, status, notice, deposits |
| SHOW_MASTER_DATA | "show master data", "bed count summary" | owner_handler | owner | Live DB snapshot: staff rooms + revenue beds per property |
| ADD_TENANT | "add tenant Raj", "new check-in" | owner_handler | owner | New tenant onboarding |
| CHECKOUT | "checkout Raj" | owner_handler | owner | Initiate checkout + settlement |
| SCHEDULE_CHECKOUT | "Raj leaving 31st March" | owner_handler | owner | Record planned checkout |
| RECORD_CHECKOUT | "record checkout Raj" | owner_handler | owner | Mark checkout complete |
| UPDATE_CHECKIN | "Raj checkin was 15th March" | owner_handler | owner | Correct check-in date |
| NOTICE_GIVEN | "Raj gave notice" | owner_handler | owner | Record notice to vacate |
| ADD_PARTNER | "add partner +91...", "give access" | owner_handler | owner | Honest reply only: bot access is the hardcoded allowlist in `role_service.py` — not changeable from chat (non-admin: refused) |
| ROOM_TRANSFER | "move Raj to room 301" | owner_handler | owner | Transfer tenant to different room |
| ROOM_LAYOUT | "floor plan THOR" | owner_handler | owner | Show room diagram |
| ROOM_STATUS | "who is in room 203" | owner_handler | owner | Room occupancy details |
| QUERY_VACANT_ROOMS | "vacant rooms" | owner_handler | owner | List empty rooms by floor |
| QUERY_OCCUPANCY | "occupancy report" | owner_handler | owner | Total occupancy stats |
| QUERY_EXPIRING | "who is leaving this month" | owner_handler | owner | Upcoming checkouts |
| QUERY_CHECKINS | "new arrivals" | owner_handler | owner | Recent check-ins |
| QUERY_CHECKOUTS | "who left" | owner_handler | owner | Recent checkouts |
| LOG_VACATION | "Raj vacation from 15 Oct to 20 Oct", "Lokesh on leave from 15 oct to 18 oct" | owner_handler | owner | Tenant → `vacations` row (rent unchanged); Lokesh/Dilip (`operations.VACATION_EMPLOYEES`) → `operational_logs` vacation. Dates must be in the message; duplicates not re-logged; audit_log written |
| SEND_REMINDER_ALL | "send reminder all", "remind unpaid" | owner_handler | owner | **Disabled by rule (no automated tenant comms).** Replies that reminders are off; nothing queued or sent |
| START_ONBOARDING | "start onboarding Raj" | owner_handler | owner | Begin tenant form |
| GET_WIFI_PASSWORD | "wifi password", "wifi password hulk floor 2", "net ka password batao" | owner_handler | owner (tenants/leads get no reply) | WiFi credentials |
| SET_WIFI | "update wifi thor Cozeevo T2 password newpass1" | owner_handler | owner | Change one network's password in `properties.wifi_floor_map`; audit_log written |
| COMPLAINT_REGISTER | "no water room 512", "512 tap leaking" | owner_handler | owner | Register complaint against the room's active tenancy (dedup per category); audit_log written |
| COMPLAINT_UPDATE | "resolve complaint 512", "resolve PLU-20261011-001", "resolve complaint #5" | owner_handler | owner | Resolve by ticket / #id / room (room before bare id; asks if the room has 2+ open). No reference → lists open complaints, closes nothing. audit_log written |
| QUERY_COMPLAINTS | "show complaints" | owner_handler | owner | List open complaints |
| QUERY_CONTACTS | "plumber contact", "plumber kaun hai", "Ravi number" | owner_handler | owner | Vendor/supplier contacts |
| UPDATE_CONTACT | "update contact Ravi", "edit vendor Ravi" | owner_handler | owner | Change a vendor's phone/notes (confirm; audit_log) |
| ADD_STAFF | "add staff Raju \| Security \| 8000 \| 15-06-1990 \| ... \| room G05", "add staff Raju" | update_handler | owner | Register staff (no duplicate active name) → KYC photo or skip |
| ASSIGN_STAFF_ROOM | "staff Raju room G05", "move staff Raju to 702", "staff raju 702 mein" | update_handler | owner | Link staff to a room; room flips to staff room |
| EXIT_STAFF | "staff Raju exit", "staff Raju left" | update_handler | owner | Staff exited; last staff out flips room back to revenue |
| ACTIVITY_LOG | "log plumber visit" | owner_handler | owner | Record operational activity |
| QUERY_ACTIVITY | "activity today" | owner_handler | owner | Show activity timeline |
| ADD_CONTACT | "add plumber Raju 9876543210" | owner_handler | owner | Save vendor/service contact |
| GET_TENANT_NOTES | "notes for Raj" | owner_handler | owner | View tenant agreement notes |
| REMINDER_SET | "remind Raj tomorrow" | owner_handler | owner | **Disabled by rule (no scheduled messages).** Replies that reminders are off; nothing set |
| REQUEST_RECEIPT | "receipt for Raj" | tenant/lead handler | tenant/lead | Generate payment receipt (DISABLED — tenants/leads get no reply) |
| ROOM_TYPE | "what type is room 203" | tenant/lead handler | tenant/lead | Room sharing type info (DISABLED — tenants/leads get no reply) |
| VACATION_NOTICE | "Raj going home 5 days" | tenant/lead handler | tenant/lead | Record planned absence (DISABLED — tenants/leads get no reply) |
| MORE_MENU | "more", "more options", "full menu" | owner_handler | admin/owner/receptionist | Same role-aware WhatsApp menu as HELP (`owner_handler._ops_menu`) |
| RULES | "house rules" | all handlers | all | PG house rules |
| HELP | "help", "menu", "hi" | owner_handler | admin/owner/receptionist | Role-aware menu of commands that work on WhatsApp only; chit block only for CHIT_PHONES; ends with the Kozzy-app line |
| UPDATE_TENANT_NOTES | "update agreement for Raj" | owner_handler | owner | Edit permanent tenant notes |
| CHIT_LOG | "paid boobalan chit 5.5L on 11 sep", "chit belandur 5L" | chit_handler | **Kiran + Prabhakaran phones only** | Record a chit / hand-loan instalment (`chit_payments`). Name fuzzy-matched to known names; "loan" → category Loan; bank/upi → mode bank; date defaults today |
| CHIT_QUERY | "chit payments", "chit sep", "chit boobalan", "chit summary" | chit_handler | **Kiran + Prabhakaran phones only** | List instalments, filter by month / name, totals by name |
| CHIT_EDIT | "chit 6 amount 5L", "chit 6 date 10 sep", "chit 6 name boobalan", "chit 6 bank", "edit chit 6 date 10 sep amount 5L" | chit_handler | **Kiran + Prabhakaran phones only** | Edit date / amount / name / mode / category in place; every change appended to `notes` as an audit trail |
| CHIT_VOID | "void chit 6", "delete chit #6" | chit_handler | **Kiran + Prabhakaran phones only** | Void an instalment (is_void, never delete) |
| MY_BALANCE | "my balance" | tenant_handler | tenant | Own dues (DISABLED) |
| MY_PAYMENTS | "my payments" | tenant_handler | tenant | Own payment history (DISABLED) |
| MY_DETAILS | "my room" | tenant_handler | tenant | Own stay details (DISABLED) |
| CHECKOUT_NOTICE | "I want to leave" | tenant_handler | tenant | Initiate checkout (DISABLED) |
| ROOM_PRICE | "room price" | lead_handler | lead | Room pricing (DISABLED) |
| AVAILABILITY | "available rooms" | lead_handler | lead | Availability (DISABLED) |
| VISIT_REQUEST | "can I visit" | lead_handler | lead | Book visit (DISABLED) |

**Note:** Tenant and lead intents return `None` (no auto-reply) — rule: zero automated tenant comms. Messages are logged but the bot stays silent.

**All `FINANCIAL_INTENTS`** (`account_handler.FINANCIAL_INTENTS`) are blocked in `gatekeeper.py` for every role and answered with "use the Kozzy app" — payments, dues, expenses, reports, refunds, deposits all live in the app. Their rows above are kept to show where each moved.

**"owner" column** = any staff phone: admin, owner, receptionist (`role_service._HARDCODED_ROLES`). Receptionist reaches every non-finance intent except ADD_PARTNER (admin only) and CHIT_* (Kiran + Prabhakaran phones only).

---

## 2. Role Resolution

**File:** `src/whatsapp/role_service.py`

```
Normalize phone → 10-digit
    ↓
Hardcoded allowlist (_HARDCODED_ROLES; DEMO_ROLES when DEMO_MODE=1)
    → admin / owner / receptionist
    ↓ NOT FOUND
role = "blocked" → no reply (tenants, leads, unknown numbers)
```

Partners / staff cannot be added from chat — edit `_HARDCODED_ROLES` and deploy.

Returns `CallerContext` with: phone, role, name, tenant_id, auth_user_id, is_blocked

---

## 3. Per-Role Flows

### Admin / Owner

```
Message → Rate Limit → Role Detection → Intent Detection (regex 97%)
    ↓
[Gatekeeper]
    CHIT_* intent → phone in services/chit_payments.CHIT_PHONES? → chit_handler, else generic UNKNOWN reply (hard boundary, role is NOT enough)
    Financial intent → "use the Kozzy app" (blocked, every role)
    Operational intent → owner_handler
    ↓
[Handler]
    0 matches → suggest similar names + save pending
    1 match → confirm inline
    2+ matches → numbered list + save pending
    ↓
[Reply]
```

### Receptionist

Same as admin/owner (finance is blocked for everyone), except ADD_PARTNER is refused and CHIT_* gets the generic "didn't understand" reply.

### Tenant (DISABLED)

Bot returns `None` → no reply sent. Message logged to `chat_messages`.

### Lead (DISABLED)

Bot returns `None` → no reply sent. Message logged to `chat_messages`.

---

## 4. Pending Actions State Machine

**File:** `src/whatsapp/chat_api.py`, `src/database/models.py` (PendingAction table)

### States

| State | Trigger | User Response | Resolution |
|-------|---------|---------------|------------|
| INTENT_AMBIGUOUS | 2+ regex matches | Pick number (1, 2...) | Re-route to selected intent |
| AWAITING_CLARIFICATION | Handler needs month/name | "March", "Raj" | Add to entities, re-route |
| CONFIRM_PAYMENT_LOG | Payment details shown | Yes / No / correction | Log payment or cancel |
| CONFIRM_ADD_EXPENSE | Expense details shown | Yes / No | Log expense or cancel |
| CONFIRM_DEPOSIT_REFUND | Refund details shown | Yes / No | Process refund or cancel |
| DUPLICATE_CONFIRM | Same payment in 24hrs | 1=Log anyway, 2=Cancel | Skip check or abort |

### Special Behaviors

- **`__KEEP_PENDING__` prefix**: Handler wants to re-prompt (e.g., correction accepted, confirm again)
- **Auto-expiry**: All pending actions expire after 30 minutes
- **Learning**: When user picks from ambiguous list, pattern→intent saved to `learned_rules.json`

### Mid-Flow Corrections (v1.12) — historical (payment logging is app-only now)

During CONFIRM_PAYMENT_LOG, users can correct details instead of just yes/no:

| Correction | Examples |
|------------|----------|
| Amount only | "no 15000", "15000" |
| Mode only | "no it was upi", "actually cash", "no gpay" |
| Month only | "no for february", "no january" |
| Amount + month | "no 14000 for february" |
| Amount + mode | "no 14000 upi" |
| Cancel | "no", "cancel", "stop" |
| Confirm | "yes", "ok", "haan", "theek hai", "thik hai", "sahi hai", "confirm" |

---

## 5. Shared Helpers (`_shared.py`)

| Function | Purpose | Used By |
|----------|---------|---------|
| `_find_active_tenants_by_name(name)` | Fuzzy tenant search by name (ilike) | account, owner |
| `_find_active_tenants_by_room(room)` | Find tenants by room number | account, owner |
| `_find_similar_names(name)` | Typo-tolerant suggestions (difflib) | account, owner |
| `_make_choices(rows)` | Format numbered choice list | account, owner |
| `_save_pending(phone, intent, ...)` | Save pending action (30min expiry) | all handlers |
| `bot_intro(first_time, name, role)` | Greeting header (rotates daily) | all handlers |
| `is_affirmative(text)` | "yes", "haan", "confirm", "theek hai", "thik hai", "sahi hai" → True | owner (pending) |
| `is_negative(text)` | "no", "nahi", "cancel" → True | owner (pending) |
| `parse_target_month(entities)` | Extract month from entities | account, owner |

---

## 6. Chat History & Follow-up Detection

**File:** `src/whatsapp/chat_api.py`

### Storage

All messages saved to `chat_messages` table (phone, direction, message, intent, role, created_at). Last 5 loaded as context per request.

### Follow-up Detection

When intent = UNKNOWN and message contains pronoun patterns:

**English:** "how much", "what about", "his/her/their", "payment history"
**Hindi:** "uska", "uski", "kitna", "kab se"

Flow:
1. Extract room number or tenant name from last bot response
2. Re-route as QUERY_TENANT with extracted context
3. Example: "Raj balance" → bot replies with Raj info → "his payments" → detected as follow-up → re-routes to QUERY_TENANT for Raj

---

## 7. Google Sheets Integration

**File:** `src/integrations/gsheets.py`

### Read Operations

- Rate cards (room pricing by type)
- Tenant data (for cross-referencing)

### Write Operations

- **Payment write-back**: After PAYMENT_LOG, update cell in month column
- **Month auto-detection**: Maps period_month to correct column (Dec, Jan, Feb, Mar...)
- **Overpayment check**: If paid > due, flag in sheet

### Fire-and-forget

Sheet writes are async and non-blocking. Sheet errors don't prevent payment logging.

---

## 8. Intent Detection Internals

**File:** `src/whatsapp/intent_detector.py`

### Rule Structure

```python
(re.compile(r"pattern", re.I), "INTENT_NAME", confidence_score)
```

### Confidence Tiers

- **0.95+**: Exact phrase match, all entities present
- **0.90-0.94**: Clear intent with minor variations
- **0.85-0.89**: Good but might need disambiguation
- **<0.70**: SYSTEM_HARD_UNKNOWN → "Could you rephrase?"

### Entity Extraction

| Entity | Pattern | Examples |
|--------|---------|----------|
| Amount | `\d[\d,]*(?:\.\d+)?` + 'k' suffix | "15000", "15k", "1,50,000" |
| Name | Titlecase `[A-Z][a-z]{2,}` | "Raj", "Raj Kumar" |
| Room | "room 203", "G15", bare number | "203", "G15", "room 203-A" |
| Month | Keyword match | "jan", "february", "march" |
| Mode | Keyword | "cash", "upi", "gpay" → upi |

---

## 9. Example Flow: "Raj paid 15000 upi" — HISTORICAL

> Today this message gets "Finance queries are not available via WhatsApp — use the Kozzy app". Kept as a record of the old flow; the payment logic now runs from the app.

```
1. Rate limit → Pass
2. Role → admin (phone in authorized_users)
3. Intent → PAYMENT_LOG (confidence 0.92)
   Entities: {name: "Raj", amount: 15000, payment_mode: "upi"}
4. Gatekeeper → account_handler (financial intent)
5. _payment_log():
   - Search "Raj" → 1 match: Raj Kumar, Room 203
   - Save CONFIRM_PAYMENT_LOG pending
   - Reply: "Confirm? Raj Kumar (Room 203), Rs.15,000 UPI, March 2026. Reply Yes/No"
6. User replies "Yes"
   - Load pending → CONFIRM_PAYMENT_LOG
   - is_affirmative("Yes") → True
   - Create Payment record
   - Update RentSchedule → paid
   - Google Sheets write-back (async)
   - Reply: "Payment logged — Raj Kumar (Room 203): Rs.15,000 UPI"
```

### 9b. Updated Payment Flow (v2)

The payment flow now shows a dues snapshot before confirmation:

1. Resolve tenant (same fuzzy search as before)
2. Fetch dues snapshot: all pending/partial months + tenant notes + monthly notes
3. Compute oldest-first allocation
4. Show snapshot + allocation, ask for confirmation or override
5. If multi-month: allow override (e.g. "all to march" or "feb 3000 march 5000")
6. On confirm: log split payments, update rent_schedule, sync to Sheet

**Notes system:**
- `tenancy.notes` = permanent agreements (editable via UPDATE_TENANT_NOTES intent)
- `rent_schedule.notes` = monthly notes (editable during payment flow, auto-carried to next month)
- Both synced to Sheet with retry (3 attempts)
