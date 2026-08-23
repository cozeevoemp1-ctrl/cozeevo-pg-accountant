# Havenly Stays — AI Receptionist Demo

Fictional PG accommodation ("Havenly Stays", Ariana) built for a YouTube
series on building an AI WhatsApp receptionist. **Fully isolated** from the
real Cozeevo/Kozzy production bot and database — separate Supabase project,
separate WhatsApp test number, separate code path. Nothing here can affect
production; see `src/whatsapp/webhook_handler.py`'s `HAVENLY_WHATSAPP_PHONE_NUMBER_ID`
branch for the one line that routes to it.

## What it does

- Answers **pricing** questions (asks which room type if not specified)
- Answers **availability** questions (asks which month if not specified)
- Books a **visit**: collects name → email → preferred date/time → confirms,
  then creates a real Cal.com booking (Cal.com emails the visitor a confirmation/invite)
- Falls back to Groq (via the existing `get_claude_client()`) to ask one
  clarifying question when the message doesn't match any of the above

## One-time setup

1. **Meta WhatsApp test number** — in the Meta Developer dashboard (same App
   as production is fine), add a test number, add your own number to its
   recipient allow-list, copy its Phone Number ID + access token.
2. **New Supabase project** — create a fresh project in the Supabase
   dashboard, copy its Postgres connection string (asyncpg form).
3. **Cal.com** — create an event type (e.g. "Havenly Stays Visit", 30 min),
   grab its numeric event type ID from the edit-page URL, and an API key from
   Settings → Developer → API Keys.
4. Fill in `.env`:
   ```
   HAVENLY_DATABASE_URL=...
   HAVENLY_WHATSAPP_PHONE_NUMBER_ID=...
   HAVENLY_WHATSAPP_TOKEN=...
   HAVENLY_CALCOM_API_KEY=...
   HAVENLY_CALCOM_EVENT_TYPE_ID=...
   ```
5. Seed sample room data:
   ```
   py -3 -m demo.havenly_stays.seed
   ```

## Testing without WhatsApp

```
py -3 -m demo.havenly_stays.test_conversation
```
Runs a scripted conversation (pricing → availability → book a visit) directly
against `handle_demo_message()`.

## Testing with real WhatsApp

Once the Meta test number is configured and pointed at the same webhook URL
as production (`/webhook/whatsapp` — Meta routes by `phone_number_id` inside
the payload, so one URL serves both numbers), message the demo number from
your allow-listed phone. A booked visit will show up as a real Cal.com
booking (visible in the Cal.com dashboard, and on your Google Calendar too if
you've connected one inside Cal.com), and the confirmation email will land in
whatever address you give the bot.

## Files

| File | Purpose |
|---|---|
| `models.py` | SQLAlchemy models — `Room`, `Lead`, `LeadSession`, `VisitBooking` |
| `db.py` | Async engine/session against `HAVENLY_DATABASE_URL` |
| `seed.py` | Sample room/pricing data |
| `intents.py` | Regex intent classification (pricing/availability/visit/confirm/cancel) |
| `handler.py` | Main conversation state machine — `handle_demo_message(phone, text)` |
| `calendar_booking.py` | Real Cal.com booking creation (visit confirmation/invite) |
| `whatsapp_send.py` | Standalone outbound WhatsApp sender (deliberately not reusing production's `_send_whatsapp`, which logs to the Cozeevo `whatsapp_log` table) |
| `test_conversation.py` | Scripted manual conversation test, no WhatsApp needed |

## Out of scope

No double-booking checks, no business-hours validation — this is a demo, not
the real booking engine. No automated pytest suite.
