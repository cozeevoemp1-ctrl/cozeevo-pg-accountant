# Owner PWA — Design Spec

**Date:** 2026-04-19
**Status:** Brainstorm complete · pending user review
**Author:** Kiran + Claude (brainstorm session)

## 1. Purpose

Build a mobile-first web app for PG owners (primary user: Kiran) that **complements** the existing WhatsApp bot. The app's reason to exist: fast, fool-proof, voice-first data entry for the five core operations that happen daily — **with state that never resets mid-task** (the bot's biggest weakness).

The WhatsApp bot continues to serve tenants, staff, and quick-fire owner actions. The app is the power-user surface for the owner when WhatsApp's ephemeral conversational state isn't enough.

Long-term: becomes **Kozzy SaaS** — sold to other PG owners once stable at Cozeevo.

## 2. Users

**Primary (v1):** Owner role — Kiran, partner (Prabhakaran, Lakshmi Mam). Currently 4 users.

**Deferred to v2:** Tenants (self-service — balance, receipts, complaints), staff (check-in desk).

**Out of scope (no plan):** Leads on the app. They continue via WhatsApp.

## 3. Scope

### In scope — v1 (6 weeks)

**Five end-to-end workflows:**
1. **Rent collection** — log payment via voice / form; auto-receipt to tenant via WhatsApp
2. **Field modifications** — change rent / room / deposit / maintenance for any tenant (rent changes create rent_revisions entry per existing rules)
3. **Check-in wizard** — onboard new tenant (details → room → rent/deposit/maintenance → ID/agreement upload → confirm)
4. **Check-out wizard** — settle dues → deposit refund calc (per REPORTING.md) → forwarding details → exit
5. **Communication** — send reminders to tenants (bot is the channel; app triggers)

**Supporting surfaces:**
- Home dashboard with tabbed overview card (Collection / Bookings / Expenses / P&L)
- Tenants list with search, filters, quick actions
- Tenant detail view with full audit trail
- Collection breakdown screen (per REPORTING.md §4.2)
- Voice entry with transcribe + confirm pattern
- Login + biometric unlock + session management

### Out of scope (deferred)

- Tenant PWA (self-service)
- Receptionist / staff PWA
- Lead portal
- Document hub (IDs, agreements library)
- Calendar view
- Approval queue (multi-step workflow states)
- Offline mode (service worker + IndexedDB sync)
- Multi-org switching UI (data model is multi-tenant; UI stays single-PG for v1)

## 4. Design principles (7)

1. **Numbers are the hero** — Money is the subject. Rent, dues, totals deserve typographic weight. Never shrink numbers for decoration.
2. **Speed over beauty** — Daily tool, not showcase. Kill decoration that costs a tap.
3. **Fool-proof by structure, not warnings** — Pre-fill from context. Destructive actions show exactly what changes, then confirm. Design errors out of the flow.
4. **Voice first, tap second, type last** — Mic is always reachable. Typing is fallback.
5. **One screen, one answer** — Home = "what's happening with my money today?". Tenant detail = "who is this?". No cramming.
6. **Thumb-reachable, one-handed** — Primary actions in the bottom 40%.
7. **Trust signals on money actions** — Every write shows who/when/from where/previous state. Audit trail is in the UI, not hidden in logs.

## 5. Architecture

```
┌──────────────────────────────────────────────────────────┐
│           PWA · Next.js 15 + TypeScript + Tailwind       │
│   Mobile-first · install to home screen · push notifs    │
│   Voice → Groq Whisper · Intent → Groq Llama 3.3 70B     │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTPS + JWT (Supabase Auth)
                        ▼
┌──────────────────────────────────────────────────────────┐
│        FastAPI (existing VPS at api.getkozzy.com)        │
│  /webhook          ← WhatsApp bot (UNTOUCHED)            │
│  /api/v2/app/*     ← NEW: JSON router for PWA            │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│  Shared services layer: src/services/                    │
│  (lift existing handlers here — single source of truth)  │
└───────────────────────┬──────────────────────────────────┘
                        ▼
                   Supabase DB
              (existing · add org_id)
```

**Key rule:** business logic lives in the services layer (single source of truth). Bot and app are thin wrappers that call the same services. A bug fix in `log_payment()` → both WhatsApp and app get it automatically.

### Multi-tenant data model (hybrid)

Add `org_id` column to all primary tables (tenancies, payments, expenses, rooms, rent_revisions, etc.). Cozeevo = `org_id = 1`. UI stays single-PG (no org switcher, no onboarding wizard) for v1. When customer #2 arrives, flip a flag to show the switcher — no data migration needed.

### Hosting

- **PWA:** Vercel
- **API:** existing Hostinger VPS (api.getkozzy.com) — no change
- **DB:** existing Supabase — no change
- **STT + LLM:** existing Groq account — no change

## 6. Platform decision

**Start: PWA. Migrate to native (iOS + Android) later when Kozzy has paying customers who want App Store presence.**

PWA details:
- One codebase (Next.js)
- Install to home screen (no app stores)
- Push notifications (iOS 16.4+ supports)
- Push-to-talk voice (browsers require tap to start mic — no always-listening wake word)
- Instant updates (no store review)

## 7. Voice pipeline

```
[Tap mic FAB (center of tab bar)]
   → Browser records audio (MediaRecorder API)
   → POST /api/v2/app/voice/transcribe (audio blob)
   → Groq Whisper Large v3 Turbo (multilingual, $0.04/hr)
   → Transcript returned, shown to user (editable)
   → POST /api/v2/app/intent/extract (transcript + context)
   → Groq Llama 3.3 70B (structured output via PydanticAI)
   → Form fields pre-filled; user visually confirms
   → POST to action endpoint (e.g. /api/v2/app/payments)
   → Writes DB via shared service + audit_log entry
   → WhatsApp receipt sent to tenant (existing flow)
```

**Cost estimate:** ~₹40/month per active user (Whisper + Llama combined).

**Language support:** English / Tamil / Tanglish all work out of the box (Whisper auto-detects). Adding more is a 1-line config change.

## 8. Security

- **Login:** Phone + OTP (reuses existing identity system; no passwords)
- **Biometric unlock:** WebAuthn (Face ID / fingerprint) after first login
- **Session timeout:** 15 min idle → auto-lock (biometric to reopen)
- **Roles:** admin (full) / staff (limited — v2) / tenant (self-only — v2)
- **Audit log:** every financial write → `audit_log` (existing table)
- **2FA on money-out:** biometric re-prompt for refunds, waivers, rent decreases
- **Transport:** HTTPS only
- **Storage:** encrypted session storage; NO financial data in unencrypted localStorage

## 9. Home screen design (locked)

Structure (top to bottom):
1. **Status bar** (OS-provided)
2. **Greeting** — "Welcome 👋 · Kiran" + notification bell + report icon
3. **Pending strip** — warm cream bar: "12 payments overdue · ₹78,000 ›"
4. **Tabbed overview card** — switches between:
   - **Collection** — Collected ₹2,40,000 of ₹3,18,000 · 75% progress bar · "Tap for breakdown"
   - **Bookings** — Upcoming check-ins + advances held + no-show risk + list of next 3
   - **Expenses** — Spent this month + delta vs last + category breakdown
   - **P&L** — Net profit + margin % + Income/Expenses/Profit bars
5. **KPI grid (2×2)** — Beds occupied / Vacant / Tenants / In-Out today
6. **Quick Actions (4 tiles)** — Payment · Check-in · Check-out · Edit + "All ›" for more
7. **Recent activity** — today's payments & alerts
8. **Tab bar** — Home · Tenants · [VOICE mic — center, elevated] · Ledger · More

## 10. Design system

**Fonts:**
- Body / numbers: DM Sans (400, 500, 600, 700, 800)
- No serif display font in current version (stripped for clarity)

**Colors:**
- Background: `#F6F5F0` (warm cream)
- Cards: `#FFFFFF`
- Text primary: `#0F0E0D`
- Text secondary: `#6F655D`
- Brand pink: `#EF1F9C`
- Brand blue: `#00AEED`
- Pastel icon backgrounds: green `#E1F3DF` · pink `#FCE2EE` · blue `#DFF0FB` · orange `#FFE8D0`
- Status: paid green `#2A7A2A` · due pink `#EF1F9C` · warning orange `#C25000`

**Numbers:** Indian format (₹2,40,000 with commas, NOT ₹2.4L).

**Icons:** Lucide-style outline SVG, 1.8px stroke, stroke-linecap round.

**Voice mic:** center of tab bar, elevated circle, pink gradient, always visible.

## 11. Build sequence (6 weeks)

| Week | Scope |
|---|---|
| 1 | Skeleton: Next.js PWA + Serwist + Supabase Auth phone+OTP + `/api/v2/app/` router + lift-and-shift handlers to `src/services/` + `org_id` migration |
| 2 | **Rent collection** end-to-end (list → voice entry → payment detail → receipt) + home dashboard (Collection tab) |
| 3 | **Field modifications** (rent/room/deposit/maintenance) + tenant detail + audit drill-down |
| 4 | **Check-in wizard** (5 steps) + home Bookings tab + biometric unlock |
| 5 | **Check-out wizard** (dues → refund → exit) + home Expenses + P&L tabs |
| 6 | **Communication/reminders** + bulk ops + push notifications + polish + beta rollout to Kiran |

## 12. Dependencies

- Existing FastAPI handlers must be lifted to `src/services/` — this is the biggest internal refactor in Week 1
- Existing DB migrations (migrate_all.py) remain append-only; new migration adds `org_id`
- Groq account (existing) — no changes needed
- Supabase Auth (new setup for phone+OTP)
- Vercel account (new) for PWA hosting

## 13. Existing rules the app must follow

- **REPORTING.md §4.2** — Collection = rent + maintenance only; deposits & booking advances separate
- **No hard-delete of financial records** — use `is_void = True`
- **Rent changes → rent_revisions entry** with effective date
- **DB writes first, Sheet mirror after** — see `docs/BRAIN.md` section 15b
- **No-show tenants visible every month until checkin** — don't filter them out of dues
- **Deposit includes maintenance** — first-month Rent Due = rent + deposit
- **97% regex + AI for ambiguous** — existing intent detector stays as bot's classifier

## 14. Risks & open questions

| # | Risk | Mitigation |
|---|---|---|
| 1 | Whisper transcription accuracy on Tanglish | Prompt-tune Llama for mixed-language intent extraction during week 2 |
| 2 | FastAPI handler refactor (lift to services) is bigger than 1 week | Start lift in week 1 alongside skeleton; accept some handlers stay in-place for v1 if needed |
| 3 | Multi-tenant `org_id` migration on live DB | Test on local first; can be applied with default `org_id=1` before app goes live |
| 4 | Biometric unlock on older Android browsers | WebAuthn fallback to PIN |
| 5 | Push notifications on iOS require user to install PWA first | Add "install first" step in onboarding |

## 15. Success criteria (v1)

- Kiran uses the app daily for all 5 workflows within 4 weeks of beta
- Zero WhatsApp-bot regressions (bot keeps working identically)
- Voice entry success rate > 85% (correctly extracts intent + entities)
- Time to log a payment via app ≤ time via WhatsApp bot (should actually be faster with voice)
- No financial data divergence between bot and app (same DB, same services)

## 16. Build cadence — mockup before every screen

**User requirement:** each screen gets a mockup (in the Visual Companion browser) BEFORE its code is written.

Flow per screen in each build week:
1. Produce mockup applying the locked design language (pastel icon cards, pink+blue brand, DM Sans, center mic nav, progress bars, tabbed overview where relevant)
2. User reviews mockup in browser, gives feedback
3. Iterate mockup if needed (typically ≤2 iterations based on v1–v6 home-screen cadence)
4. Once approved, code the screen
5. User tests in staging before moving to next screen

**Screens that still need mockups (pre-build):**
- Login + OTP + biometric unlock
- Tenants list + filters + bulk selection
- Tenant detail + audit trail
- Payment entry (voice + form)
- Check-in wizard (5 steps)
- Check-out wizard
- Field modifications (rent/room/deposit/maintenance)
- Reminders / communication
- Reports / full breakdown screens

## 17. Next step

Hand off to `writing-plans` skill to produce the implementation plan (week-by-week task breakdown, with explicit "mock → review → code" cycle per screen).
