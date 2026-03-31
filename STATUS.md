# Cozeevo Help Desk — Project Status

> Updated: 2026-03-31
> Read this FIRST at the start of every session.

## What's Working (Live on VPS after deploy)

### WhatsApp Bot (all roles)
- **Greeting** — "Cozeevo Help Desk" branding (not Artha)
- **Chat history** — all messages saved to chat_messages table, last 5 loaded as context
- **Follow-up detection** — "how much did he pay?" after "room 209" → re-routes to tenant query
- **Activity log** — 7 categories (delivery, purchase, maintenance, utility, supply, staff, visitor, note)
- **Activity auto-resolves complaints** — "log plumber fixed room 204 leak" closes matching complaint
- **Complaint tickets** — PLU/ELE/WIF/FOD/FUR/OTH prefix format
- **Google Sheets connected** — read + write to "Copy of Cozeevo Monthly stay" sheet

### Admin Services
- Log payment, Query dues, Void payment, Monthly report, Bank report, Add expense
- Add tenant, Checkout, Rent change, Room query (with payment history + notes), Tenant search
- Occupancy (premium=2 beds), Vacant rooms, Complaints, Resolve, Activity log, Contacts

### Receptionist (blocked from: bank report, monthly report only)
### Tenant (my balance, my payments, wifi, complaints)
### Lead (prices, availability, room types, visit booking)

### Dashboard (web)
- static/mockup_c.html — Stitch/Material Design 3 dark theme
- Real API data, month picker, property filter (THOR/HULK)
- static/wireframe.html — stakeholder service map

### Data State (Supabase)
- 261 tenants, 261 tenancies, 498 rent_schedules, 471 payments
- 200 active (181 regular + 19 premium = 219 beds), 22 no-show
- Master: 166 rooms (THOR 84 + HULK 82), 291 revenue beds, 8 staff rooms
- Authorized users: Kiran (admin), Lakshmi Mam (admin), Prabhakaran 9444296681 (admin), 8548884455 (admin/business number), Sathyam 7993273966 (receptionist)

### Google Sheets
- Sheet ID: 1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA
- Credentials: credentials/gsheets_service_account.json (NOT in git)
- Payment write-back: auto-detect month, overpayment check, Dec/Jan/Feb/Mar columns

## Known Bugs
- ~~Monthly report Rs.0~~ — FIXED (is_void was NULL, now false; commit b17327b)
- ~~No-show count wrong (9 instead of 22)~~ — FIXED (commit 950a994)
- **Tenant/lead auto-reply disabled** (commit 6a3618f) — bot silent for non-authorized users, messages still logged
- **Prabhakaran (9444296681)** — messages reach bot, but replies blocked by Meta error 131030 (recipient not in allowed list). App still uses test number (+1 555 192 0467). Added to Meta test number list but needs real business number migration.
- **Golden suite: 86/100** — 14 failing (mostly test-env issues with tenant/lead phone numbers, not code bugs)
- **WhatsApp number migration on hold** — 8548884455 stays on WhatsApp Business app, bot stays on Meta test number (+1 555 192 0467). Must migrate to real business number for Prabhakaran and other external users to receive replies.
- **Payment confirmation crash fixed** — UnboundLocalError on _do_log_payment_by_ids resolved (lazy import)

## Master Data Rules (LOCKED)
- Room layout: THOR G01-G10 + floors 1-6 (x01-x12) + 701,702 = 84 rooms
- Room layout: HULK G11-G20 + floors 1-6 (x13-x24) = 82 rooms
- Staff rooms: THOR (G05,G06,107,108,701) + HULK (G12,114,618) = 8 rooms
- Revenue beds: THOR 145 + HULK 146 = 291 (corner rooms=single, middle=double, G07-G09/G13-G14=triple)
- Premium = tenancy attribute (1 person books full double room = 2 beds occupied)
- Occupancy: regular x1 + premium x2. No-show shown separately.
- Dues scoping: checkin_date < month_start, only current month's rent_schedule

## Pending Tasks
1. ~~Fix monthly report Rs.0 bug~~ — DONE
2. ~~Fix no-show count~~ — DONE (removed checkin_date filter from no-show queries)
3. **VPS deploy** — `cd /opt/pg-accountant && git pull && python3 -m src.database.migrate_all && systemctl restart pg-accountant`
4. **Daily Basis sheet integration** — day-stay customers sheet
5. **P&L reclassification** — Nov 2025 has 4 unanswered questions, Dec-Mar still to review
6. **Unclassified bank vendors** — arunphilip25, tpasha638, M036TPQEK, akhilreddy007420, volipi.l, ksshyamreddy

## File Map
- `src/whatsapp/chat_api.py` — webhook, chat history, follow-up detection
- `src/whatsapp/intent_detector.py` — regex intent patterns
- `src/whatsapp/gatekeeper.py` — role+intent routing
- `src/whatsapp/handlers/owner_handler.py` — admin/receptionist handlers
- `src/whatsapp/handlers/account_handler.py` — financial handlers (payments, dues, reports)
- `src/whatsapp/handlers/tenant_handler.py` — tenant self-service
- `src/whatsapp/handlers/lead_handler.py` — sales/lead handlers
- `src/integrations/gsheets.py` — Google Sheets read/write
- `src/database/models.py` — all ORM models
- `scripts/import_excel_full.py` — Excel → DB full import
- `static/mockup_c.html` — dashboard
- `static/wireframe.html` — service map
