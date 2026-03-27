# BOT_FLOWS.md — WhatsApp Bot Intent Catalog & Message Flows

Complete reference for all intents, role-based routing, pending state machine, and interaction patterns.

---

## 1. Intent Catalog

| Intent | Example Messages | Handler | Role | What It Does |
|--------|------------------|---------|------|--------------|
| PAYMENT_LOG | "Raj paid 15000 upi" | account_handler | owner | Log rent payment |
| QUERY_DUES | "who owes", "pending dues" | account_handler | owner | List tenants with outstanding dues |
| QUERY_TENANT | "Raj balance", "room 203 balance" | account_handler | owner | Tenant account: rent, paid, balance, history |
| ADD_EXPENSE | "electricity 5000 upi" | account_handler | owner | Log operational expense |
| QUERY_EXPENSES | "total expenses" | account_handler | owner | Expense breakdown by category/month |
| REPORT | "monthly report", "march report" | account_handler | owner | Monthly financial report |
| RENT_CHANGE | "change rent for Raj to 20000" | account_handler | owner | Update tenant rent |
| RENT_DISCOUNT | "concession 2000 for Raj" | account_handler | owner | Apply one-time discount |
| VOID_PAYMENT | "void 15000 payment" | account_handler | owner | Mark payment as void |
| VOID_EXPENSE | "void electricity expense" | account_handler | owner | Mark expense as void |
| DEPOSIT_CHANGE | "update deposit for Raj to 50000" | account_handler | owner | Update security deposit |
| ADD_REFUND | "return deposit 50000 to Raj" | account_handler | owner | Initiate deposit refund |
| QUERY_REFUNDS | "pending refunds" | account_handler | owner | List refunds |
| BANK_REPORT | "bank report March" | finance_handler | owner | Parse bank statement → P&L |
| BANK_DEPOSIT_MATCH | "match deposits" | finance_handler | owner | Match bank deposits to payments |
| ADD_TENANT | "add tenant Raj", "new check-in" | owner_handler | owner | New tenant onboarding |
| CHECKOUT | "checkout Raj" | owner_handler | owner | Initiate checkout + settlement |
| SCHEDULE_CHECKOUT | "Raj leaving 31st March" | owner_handler | owner | Record planned checkout |
| RECORD_CHECKOUT | "record checkout Raj" | owner_handler | owner | Mark checkout complete |
| UPDATE_CHECKIN | "Raj checkin was 15th March" | owner_handler | owner | Correct check-in date |
| NOTICE_GIVEN | "Raj gave notice" | owner_handler | owner | Record notice to vacate |
| ADD_PARTNER | "add admin +919876543210" | owner_handler | owner | Add authorized user |
| ROOM_TRANSFER | "move Raj to room 301" | owner_handler | owner | Transfer tenant to different room |
| ROOM_LAYOUT | "floor plan THOR" | owner_handler | owner | Show room diagram |
| ROOM_STATUS | "who is in room 203" | owner_handler | owner | Room occupancy details |
| QUERY_VACANT_ROOMS | "vacant rooms" | owner_handler | owner | List empty rooms by floor |
| QUERY_OCCUPANCY | "occupancy report" | owner_handler | owner | Total occupancy stats |
| QUERY_EXPIRING | "who is leaving this month" | owner_handler | owner | Upcoming checkouts |
| QUERY_CHECKINS | "new arrivals" | owner_handler | owner | Recent check-ins |
| QUERY_CHECKOUTS | "who left" | owner_handler | owner | Recent checkouts |
| LOG_VACATION | "Raj vacation 5 days" | owner_handler | owner | Log temporary absence |
| SEND_REMINDER_ALL | "send reminder all" | owner_handler | owner | Mass due reminder to all tenants |
| START_ONBOARDING | "start onboarding Raj" | owner_handler | owner | Begin tenant form |
| GET_WIFI_PASSWORD | "wifi password" | owner/tenant/lead | all | WiFi credentials |
| SET_WIFI | "set wifi ssid PASSWORD123" | owner_handler | owner | Update WiFi |
| COMPLAINT_REGISTER | "AC not working room 203" | owner/tenant | owner+tenant | Register complaint |
| COMPLAINT_UPDATE | "resolve CMP-001" | owner_handler | owner | Update complaint status |
| QUERY_COMPLAINTS | "show complaints" | owner_handler | owner | List open complaints |
| QUERY_CONTACTS | "plumber contact" | owner_handler | owner | Vendor/supplier contacts |
| ACTIVITY_LOG | "log plumber visit" | owner_handler | owner | Record operational activity |
| QUERY_ACTIVITY | "activity today" | owner_handler | owner | Show activity timeline |
| RULES | "house rules" | all handlers | all | PG house rules |
| HELP | "help", "menu" | all handlers | all | Role-specific menu |
| MY_BALANCE | "my balance" | tenant_handler | tenant | Own dues (DISABLED) |
| MY_PAYMENTS | "my payments" | tenant_handler | tenant | Own payment history (DISABLED) |
| MY_DETAILS | "my room" | tenant_handler | tenant | Own stay details (DISABLED) |
| CHECKOUT_NOTICE | "I want to leave" | tenant_handler | tenant | Initiate checkout (DISABLED) |
| ROOM_PRICE | "room price" | lead_handler | lead | Room pricing (DISABLED) |
| AVAILABILITY | "available rooms" | lead_handler | lead | Availability (DISABLED) |
| VISIT_REQUEST | "can I visit" | lead_handler | lead | Book visit (DISABLED) |

**Note:** Tenant and lead intents currently return `None` (no auto-reply). Messages are logged but bot stays silent.

**"owner" role** = admin, power_user, key_user, receptionist (receptionist blocked from REPORT, BANK_REPORT, BANK_DEPOSIT_MATCH)

---

## 2. Role Resolution

**File:** `src/whatsapp/role_service.py`

```
Normalize phone → 10-digit
    ↓
Rate limit check (10/10min, 50/day)
    ↓ FAIL → role = "blocked"
Check authorized_users table → admin / power_user / key_user / receptionist
    ↓ NOT FOUND
Check tenants table → tenant
    ↓ NOT FOUND
Default → lead
```

Returns `CallerContext` with: phone, role, name, tenant_id, auth_user_id, is_blocked

---

## 3. Per-Role Flows

### Admin / Power User / Key User

```
Message → Rate Limit → Role Detection → Intent Detection (regex 97%)
    ↓
[Gatekeeper]
    Financial intent → account_handler
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

Same as admin BUT blocked from: REPORT, BANK_REPORT, BANK_DEPOSIT_MATCH

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
| `is_affirmative(text)` | "yes", "haan", "confirm" → True | owner (pending) |
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

## 9. Example Flow: "Raj paid 15000 upi"

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
