# Voice Onboarding — Design Spec
**Date:** 2026-04-29
**Status:** Approved

## What it does

Adds a mic button to the `/onboarding/new` form. Lokesh (receptionist) taps it, speaks tenant details naturally, the bot extracts all fields, speaks back a confirmation, and pre-fills the form. Multi-turn — Lokesh can speak multiple times and the bot accumulates fields across rounds.

## Entry point

Mic button in the header of `web/app/onboarding/new/page.tsx`. Tapping opens `OnboardingVoiceSheet` as a bottom sheet overlay. The existing form remains unchanged underneath.

## Conversation style

Open (style B): Lokesh says whatever he knows in one shot or multiple rounds. Bot confirms what it captured and asks only for what's still missing. No guided question-by-question prompting.

Example:
1. Lokesh: *"Room 201, phone 9876543210, rent 12k"*
2. Bot: *"Got it — room 201, phone 9876543210, rent 12,000. Still need deposit and maintenance."*
3. Lokesh: *"Deposit 15k, maintenance 500, lock in 6 months"*
4. Bot: *"Perfect. Room 201, rent 12,000, deposit 15,000, maintenance 500, lock-in 6 months. Ready to fill the form."*
5. Lokesh taps "Fill Form" → all fields pre-populate.

## Data flow

```
[Mic button tapped]
  → OnboardingVoiceSheet opens, partialFields = {}

[Each recording round]
  → SpeechRecognition captures transcript
  → Groq LLM (llama-3.3-70b) called client-side
      input: {transcript, existing: partialFields}
      output: {fields (merged), confirmation_text, missing[]}
  → partialFields updated with merged fields
  → OpenAI TTS (tts-1, voice: nova) speaks confirmation_text
  → Sheet shows captured fields + missing list

[Required fields present OR Lokesh taps "Fill Form"]
  → onOnboardingIntent(fields) callback fires
  → page state setters pre-fill all captured fields
  → sheet closes, missing fields stay blank for manual entry
```

## Required vs optional fields

**Required** (Fill Form button disabled until all three are captured):
- `room_number`
- `tenant_phone`
- `monthly_rent`

**Optional** (pre-fill if mentioned, skip if not):
- `sharing_type`, `checkin_date`, `security_deposit`, `maintenance_fee`
- `booking_amount`, `advance_mode`, `lock_in_months`
- `future_rent`, `future_rent_after_months`

## Component states

```
OnboardingVoiceSheet:
  recording   → mic active, SpeechRecognition listening
  extracting  → Groq LLM call in flight
  speaking    → OpenAI TTS audio playing
  confirm     → shows captured fields + missing list
                "Record again" button (always shown)
                "Fill Form" button (disabled until required fields present)
  error       → mic denied / API failed with message + retry
```

## Groq LLM prompt

```
You are a helpful PG receptionist assistant for Kozzy co-living.

Already captured: {JSON.stringify(existing)}

Receptionist just said: "{transcript}"

Extract or update any of these fields:
- room_number (e.g. "101", "G20")
- sharing_type ("single", "double", "triple", "premium")
- tenant_phone (10-digit Indian mobile, no country code)
- checkin_date (ISO date YYYY-MM-DD, use today's date if "today" or not mentioned)
- monthly_rent (rupees, convert "k" = 1000)
- security_deposit (rupees)
- maintenance_fee (rupees/month)
- booking_amount (rupees advance paid now)
- advance_mode ("cash", "upi", "bank")
- lock_in_months (number)
- future_rent (rupees, if rent increase mentioned)
- future_rent_after_months (number of months before increase)

Rules:
- Keep existing field values unless new speech explicitly changes them
- null = not mentioned yet
- Write a short natural confirmation (2 sentences max) of what was captured and what's still missing. Sound like a helpful assistant, not a robot.
- All monetary values in rupees (convert "k" → ×1000, "lakh" → ×100000)

Return only JSON: {"fields": {...}, "confirmation": "...", "missing": ["field1", ...]}
```

## OpenAI TTS

- Model: `tts-1`
- Voice: `nova` (clear, natural, neutral)
- Called client-side via `NEXT_PUBLIC_OPENAI_API_KEY`
- Response: MP3 blob → `new Audio(URL.createObjectURL(blob)).play()`
- Fallback: browser `window.speechSynthesis` if OpenAI call fails
- Cost: ~$0.30/month at Kozzy's volume (~15 onboardings/month)

## Files

| File | Change |
|------|--------|
| `web/components/voice/onboarding-voice-sheet.tsx` | New — bottom sheet component |
| `web/lib/parse-onboarding.ts` | New — Groq LLM extraction function |
| `web/lib/tts.ts` | New — OpenAI TTS + browser fallback |
| `web/app/onboarding/new/page.tsx` | Edit — mic button + sheet wiring |
| `web/.env.local` | Edit — add `NEXT_PUBLIC_GROQ_API_KEY`, `NEXT_PUBLIC_OPENAI_API_KEY` |
| `web/.env.example` | Edit — same keys (no values) |

No backend changes.

## Environment variables

```
NEXT_PUBLIC_GROQ_API_KEY=...       # for LLM parsing (same key as server GROQ_API_KEY)
NEXT_PUBLIC_OPENAI_API_KEY=...     # for TTS voice output
```

## Cost

| Service | Purpose | Monthly cost |
|---------|---------|-------------|
| Groq llama-3.3-70b | Field extraction + confirmation text | Free |
| OpenAI TTS tts-1 | Voice output | ~$0.30/month |

## Out of scope

- WhatsApp voice note input (separate feature)
- STT via Groq Whisper (browser SpeechRecognition is sufficient)
- Day-wise stay voice onboarding (monthly only for now)
- "Hey Kozzy" wake word (PWA Plan 4 backlog)
