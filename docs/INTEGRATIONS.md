# INTEGRATIONS.md — External Systems & APIs

Complete reference for all external integrations: WhatsApp, Google Sheets, Supabase, Groq, bank statements.

---

## 1. WhatsApp Cloud API (Meta)

### Overview
Direct webhook integration with Meta's WhatsApp Cloud API v18.0. No Twilio.

**File:** `src/whatsapp/webhook_handler.py`

### Webhook Verification (GET)

**Endpoint:** `GET /webhook/whatsapp`

```
hub.mode=subscribe
hub.challenge=<verification_string>
hub.verify_token=<token_from_env>
```

Server checks token against `WHATSAPP_VERIFY_TOKEN` (default: `pg-accountant-verify`). Match → return `int(hub_challenge)`. Mismatch → 403.

### Message Reception (POST)

**Endpoint:** `POST /webhook/whatsapp`

1. Verify HMAC signature (`X-Hub-Signature-256` using `WHATSAPP_APP_SECRET`)
2. Parse nested Meta JSON: `entry[0].changes[0].value.messages[0]`
3. Detect type: `text`, `interactive`, `document`, `image`, `audio`
4. Route through `process_message()` pipeline
5. Send reply via Meta Graph API (background task)

### Sending Messages

**Endpoint:** `POST https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages`

**Text:**
```json
{"messaging_product": "whatsapp", "to": "919876543210", "type": "text", "text": {"body": "message"}}
```

**Interactive (buttons):**
```json
{"messaging_product": "whatsapp", "to": "...", "type": "interactive",
 "interactive": {"type": "button", "body": {"text": "Choose:"}, "action": {"buttons": [...]}}}
```

**Functions:** `_send_whatsapp(to, message)`, `_send_whatsapp_interactive(to, payload)`

### Media & Voice

- Download media from Meta CDN using media_id
- Documents (PDF/Excel/CSV) saved to `data/raw/`
- Voice transcription via Groq Whisper (`whisper-large-v3-turbo`, multilingual auto-detect)

---

## 2. Google Sheets

### Overview
Payment write-back to "History" sheet in Cozeevo's master spreadsheet.

**File:** `src/integrations/gsheets.py`

### Setup
- Credentials: `credentials/gsheets_service_account.json` (NOT in git)
- Sheet ID: `1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA`
- Share sheet with service account email

### Key Columns (History sheet)

| Col | Header | Purpose |
|-----|--------|---------|
| 0 | Room No | Room number |
| 1 | Name | Tenant name |
| 9 | Monthly Rent | Base rent |
| 10-11 | From 1st FEB/MAY | Rent revisions |
| 16 | IN/OUT | CHECKIN/EXIT/CANCELLED |
| 17 | BLOCK | THOR/HULK |
| 23-24 | Jan Cash/UPI | January payments |
| 28-29 | Feb Cash/UPI | February payments |
| 31-32 | Mar Cash/UPI | March payments |

### Read Operations

`get_tenant_dues(room, name)` → month-by-month dues breakdown

### Write Operations

`update_payment(room, name, amount, method, month)`:
1. Add amount to existing cell (never replace)
2. Update rent status (PAID/PARTIALLY PAID/NOT PAID)
3. Append timestamp to Comments column

**Fire-and-forget:** Sheet writes are async. Errors don't block payment logging.

**Cache:** 5-minute TTL on worksheet object.

---

## 3. Supabase (PostgreSQL)

### Connection

```
postgresql+asyncpg://postgres:[password]@db.[project-ref].supabase.co:5432/postgres
```

**Engine:** SQLAlchemy async with pool_size=10, max_overflow=20, pool_pre_ping=True

### 21 Tables (key ones)

| Table | Purpose |
|-------|---------|
| properties | THOR, HULK |
| rooms | 166 rooms, max_occupancy, is_staff_room |
| tenants | Person record (name, phone, gender) |
| tenancies | Tenant-room assignment, rent, status |
| rent_schedule | Monthly rent tracking (period_month, rent_due, status) |
| payments | Payment records (amount, mode, is_void) |
| expenses | PG operating expenses |
| complaints | Maintenance complaints |
| bank_uploads | Uploaded bank statements |
| bank_transactions | Parsed + classified transactions |
| authorized_users | Admin/staff accounts |
| wifi_networks | WiFi credentials per property |
| chat_messages | All WhatsApp messages logged |
| pending_actions | Multi-step conversation state |

### Migration System

**File:** `src/database/migrate_all.py` -- idempotent, append-only, safe to re-run.

```bash
python -m src.database.migrate_all
```

---

## 4. Groq LLM

### When Called (NOT for common intents)

1. **Ambiguous intent** -- regex confidence too low
2. **Lead chat** -- conversational sales response
3. **Unknown merchant** -- bank transaction classification fallback

### Config
- Model: `llama-3.3-70b`
- API: `https://api.groq.com/openai/v1/chat/completions`
- Voice: `whisper-large-v3-turbo` (multilingual)
- Fallback: generic response if API fails

---

## 5. Bank Statement Processing

### Upload Flow

Owner sends PDF/Excel/CSV via WhatsApp →

1. **Download** from Meta CDN
2. **Parse** (PDF: Yes Bank-specific extractor, Excel/CSV: pandas)
3. **Classify** each transaction via `pnl_classify.py` rules (first match wins)
4. **Dedup** by SHA-256 hash of `date|description[:80]|amount`
5. **Save** to `bank_transactions` table
6. **Reply** with summary

### Classification Rules

**File:** `src/rules/pnl_classify.py`

- 100+ keyword rules, first match wins
- **Non-Operating MUST be first** (prevents false matches)
- 18 expense categories + 5 income categories
- Empty keywords = catch-all

### Deposit Matching

Match bank income to tenant deposits: amount within 10%, date within 45 days of check-in, name in description.

---

## 6. n8n (Not Used)

n8n was evaluated but skipped -- webhooks go directly to FastAPI via nginx.

---

## 7. Data Import/Export

### Full Excel Import

**Script:** `scripts/import_excel_full.py`
**Input:** `Cozeevo Monthly stay (4).xlsx`
**Creates:** tenants, tenancies, rent_schedules, payments from History sheet

### Delta Import

**Script:** `src/database/delta_import.py`
**Behavior:** Only adds missing rows, applies rent revisions, never modifies existing

```bash
python -m src.database.delta_import          # dry run
python -m src.database.delta_import --write  # insert
```

### Classified Export

**Script:** `scripts/export_classified.py`
**Output:**
- `data/reports/unclassified_review.xlsx` -- per-month, yellow column for corrections
- `data/reports/expense_classified_full.xlsx` -- summary + subcategory + all txns

---

## 8. Environment Variables — Complete Reference

### Required

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:[pass]@db.[ref].supabase.co:5432/postgres` |
| `WHATSAPP_TOKEN` | Meta permanent access token |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone number ID from Meta |
| `GROQ_API_KEY` | Groq API key (if LLM_PROVIDER=groq) |
| `credentials/gsheets_service_account.json` | Google service account (file, not env var) |

### Optional

| Var | Default | Purpose |
|-----|---------|---------|
| `LLM_PROVIDER` | `ollama` | `groq` for cloud LLM |
| `WHATSAPP_APP_SECRET` | "" | HMAC signature verification |
| `WHATSAPP_VERIFY_TOKEN` | `pg-accountant-verify` | Webhook verify token |
| `GSHEETS_SHEET_ID` | (hardcoded) | Google Sheet ID |
| `TEST_MODE` | `0` | `1` enables debug endpoints |
| `ADMIN_PHONE` | `917845952289` | Receives lead visit notifications |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `ENVIRONMENT` | `development` | development/production |

---

## 9. Integration Map

| Use Case | Integration | File |
|----------|-------------|------|
| Receive WhatsApp messages | Meta Cloud API | `webhook_handler.py` |
| Send replies | Meta Graph API | `webhook_handler.py:_send_whatsapp()` |
| Interactive buttons/lists | Meta Graph API | `webhook_handler.py:_send_whatsapp_interactive()` |
| Voice transcription | Groq Whisper | `webhook_handler.py:_transcribe_audio_bytes()` |
| Payment write-back | Google Sheets | `gsheets.py:update_payment()` |
| Read tenant dues | Google Sheets | `gsheets.py:get_tenant_dues()` |
| All data storage | Supabase PostgreSQL | `models.py` |
| Ambiguous intents | Groq LLM | `chat_api.py` |
| Bank statement parsing | pandas/openpyxl | `finance_handler.py` |
| Transaction classification | Custom rules | `pnl_classify.py` |
| Excel → DB import | SQLAlchemy async | `import_excel_full.py` |
| P&L reports | Excel export | `export_classified.py` |
