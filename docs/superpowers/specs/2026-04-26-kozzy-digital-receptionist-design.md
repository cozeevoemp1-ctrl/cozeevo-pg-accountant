# Kozzy — Digital PG Receptionist: Product Design Spec

**Date:** 2026-04-26
**Status:** Approved — moving to implementation plan
**Author:** Kiran + Claude (brainstorm session)

---

## 1. The Problem

Indian PG operators run ₹5L–50L/month businesses on paper registers and WhatsApp because:
- No PMS understands multi-bed rooms, Indian payments, or shared accommodation billing
- All existing PMS software is desktop-first (hotel-grade) — receptionists only have phones
- WhatsApp bot (natural language) is unreliable for data entry — staff mistype, bot misparses
- Result: missed payments, wrong room assignments, no audit trail, Lokesh calls Kiran for everything

---

## 2. The Solution: Kozzy

**Tagline:** *Your digital PG receptionist*

A mobile-first PG management platform. Three interfaces, one backend, one source of truth.

| Interface | Who uses it | Device | Status |
|---|---|---|---|
| PWA Forms | Receptionist (Lokesh) | Shared reception phone | **BUILD NOW** |
| PWA Voice ("Hey Kozzy") | Receptionist (Lokesh) | Shared reception phone | Build in parallel |
| WhatsApp Bot | Owner (Kiran, Prabhakaran), Tenants | Personal phones | Exists — maintain |

All three hit the same FastAPI backend → same Supabase DB → same Google Sheet mirror.

---

## 2b. Existing Foundation (do not rebuild)

The PWA is already substantially built. All new work builds on this base.

| What exists | Where | Status |
|---|---|---|
| Next.js 15 + React 18 + TypeScript PWA | `web/` | Built |
| Design system (DM Sans, cream/pink/blue, pastel tiles) | `web/tailwind.config.ts` | Locked |
| Home dashboard (greeting, KPI grid, activity feed, tab bar) | `components/home/` | Built |
| Voice sheet + mic button components | `components/voice/` | Built (needs wake word) |
| Phone OTP auth | `components/auth/` | Built (Supabase config pending) |
| Payment form page | `app/payment/new/page.tsx` | Built |
| Button, Card, IconTile, Pill, ProgressBar UI library | `components/ui/` | Built |
| HTML mockups (30+ versions) | `.superpowers/brainstorm/` | Reference |
| Owner PWA design spec | `docs/superpowers/specs/2026-04-19-owner-pwa-design.md` | Approved |
| Checkout form spec | `docs/superpowers/specs/2026-04-25-checkout-form-design.md` | Approved |
| Onboarding form spec | `docs/superpowers/specs/2026-04-15-digital-onboarding-form-design.md` | Approved |
| FastAPI backend + 26-table Supabase schema | `src/` | 95% complete |
| 105 golden tests (93 passing) | `tests/` | Running |

**Design system locked values:**
- Font: DM Sans (400–800)
- Background: `#F6F5F0` (warm cream)
- Brand pink: `#EF1F9C` | Brand blue: `#00AEED`
- Cards: 18px radius | Tiles: 14px radius
- Status: paid `#2A7A2A` / due pink / warn orange

---

## 3. What Kozzy Is NOT

- Not an ERP (no inventory modules, HR payroll, procurement)
- Not a hotel PMS (not built for single-occupancy or international guests)
- Not a generic apartment manager
- Not WhatsApp-only (bot stays for owners/tenants, staff move to PWA)

---

## 4. Architecture

```
                    KIRAN (owner)
                        │
              ┌─────────┼──────────┐
              ▼         ▼          ▼
    ┌──────────────┬──────────────┬──────────────┐
    │  TRACK A     │  TRACK B     │  TRACK C     │
    │  PWA Forms   │  PWA Voice   │  WhatsApp    │
    │  (priority)  │  (parallel)  │  (existing)  │
    └──────┬───────┴──────┬───────┴──────┬───────┘
           │              │              │
           └──────────────┼──────────────┘
                          ▼
             ┌────────────────────────┐
             │   FastAPI Backend      │
             │   intent_detector.py   │
             │   account_handler.py   │
             │   owner_handler.py     │
             │   tenant_handler.py    │
             └──────────┬─────────────┘
                        ▼
             ┌────────────────────────┐
             │  Supabase (Postgres)   │
             │  + Google Sheet mirror │
             └────────────────────────┘
```

---

## 5. Track A — PWA Forms (Critical Path)

**Goal:** Lokesh can do 100% of his daily work without touching WhatsApp.

### Screens

| Screen | Frequency | Key fields |
|---|---|---|
| Home dashboard | Always open | Today's collections, who checked in, dues alerts |
| Collect Payment | Daily | Tenant search, amount, type (cash/UPI/bank), date |
| Check In | Regular | Room/bed selector, tenant details, KYC photo, rent |
| Check Out | Regular | Tenant selector, dues summary, deposit status, confirm |
| Dues Query | Regular | Search tenant → show balance, last payment |
| Day-wise Booking | Regular | Room, dates, daily rate, guest name |
| Rental Change | ~15/month | Tenant, old rent, new rent, effective date |
| Salary Payment | ~5/month | Staff name, amount, month |
| Master Data | Owner only | Rooms, beds, staff rooms, rent types |

### UX rules
- Every write action ends at a **confirmation card** — summary of what will happen → Confirm / Edit
- Confirmation card is the safety gate: no DB write without explicit confirm
- Search-first for tenant selection (fuzzy match by name/room/phone)
- All forms work offline-first (queue writes, sync when connected)
- Session stays open — shared phone should never require re-login mid-shift

### Auth
- Staff (Lokesh): phone OTP login, session persists for the shift
- Owner: phone OTP, full access including master data
- Tenants: WhatsApp only, no PWA access

---

## 6. Track B — PWA Voice ("Hey Kozzy")

**Goal:** Lokesh can record a transaction hands-free in under 5 seconds.

### Voice pipeline

```
Shared phone mic (always open at desk)
   → Porcupine wake word "Hey Kozzy" (on-device, free tier)
   OR tap big mic button on screen
      → Groq Whisper Turbo (transcription, <1s)
         → intent_detector.py (same as WhatsApp + Forms)
            → Confirmation card (same as Forms)
               → Lokesh taps Confirm
                  → Handler executes → DB → Sheet
```

### Noise handling
- Wake word + tap-to-talk hybrid — NOT pure ambient (noisy PG = false triggers)
- After wake word / tap: 15-second focused listening window
- VAD inside the window: stop when speech ends (no endless waiting)
- Confirmation card is mandatory — no auto-commit on voice

### Languages
- English, Tamil, Telugu, Hindi + code-switching
- Groq Whisper Large v3 Turbo handles all four natively
- Cost: ~₹250–400/month per customer at heavy usage (4hrs working time/day)

### Pricing tier
- Growth ₹799 — Forms only
- Pro ₹1999 — Forms + Voice

### Future
- Physical device (Alexa-like with screen + expressions) — v3 or beyond
- Always-listening ambient (requires quieter environment or directional mic)

---

## 7. Track C — WhatsApp Bot (Existing)

**No new features required for Track C parity with Track A.**

Maintain existing bot for:
- Kiran/Prabhakaran: owner queries on the go ("show dues", "P&L this month")
- Tenants: self-service ("my balance", "I paid rent", "raise complaint")

All WhatsApp commands continue to work exactly as today. Track A/B reuse the same backend.

---

## 8. Shared Test Suite (Critical)

**Rule:** A test scenario that passes in Track A MUST also pass in Track B and Track C.

One set of golden test scenarios, three input methods.

### Test categories

| Category | What it tests |
|---|---|
| Payment logging | Correct room + amount + type recorded |
| Check-in | Correct bed assigned, no double-booking |
| Checkout | Dues cleared, deposit status correct |
| Dues query | Correct balance shown, no hallucination |
| Ambiguation flow | System asks for clarification when input is ambiguous |
| Conversation memory | Multi-turn: "how much does Suresh owe?" → "pay him off" |
| Intent accuracy | No wrong intent classification |
| Hallucination check | System never invents tenant names or amounts |
| Edge cases | Partial payment, overpayment, vacant room, no-show |

### How tests run
- `tests/eval_golden.py` — existing golden suite, extended for new scenarios
- Forms: Playwright end-to-end against PWA
- Voice: synthetic audio → Whisper → same intent pipeline
- WhatsApp: existing HTTP test harness (`TEST_MODE=1`)
- All three suites run in CI before any merge to main

---

## 9. Three-Agent Development Model

```
KIRAN
  │
  ▼
ORCHESTRATOR (Claude, main session)
  │  owns: backend API contracts, DB schema, deployment
  │  reviews: subagent PRs before merge
  │
  ├── AGENT A: Forms track (own branch: feature/pwa-forms)
  │     goal: all Track A screens built + Playwright tests pass
  │
  ├── AGENT B: Voice track (own branch: feature/pwa-voice)
  │     goal: wake word + Whisper + confirmation card + shared tests pass
  │
  └── AGENT C: WhatsApp track (own branch: feature/whatsapp-parity)
        goal: existing bot passes all shared golden tests, zero regressions
```

**Rule:** Backend changes (new endpoints, schema migrations) go through orchestrator only. Agents consume the API — they don't modify it without orchestrator approval.

---

## 10. Confidence Levels

| Component | Confidence | Notes |
|---|---|---|
| FastAPI backend + data model | 95% | Already built, battle-tested |
| PWA scaffold (React + Tailwind) | 80% | Built, Supabase Auth pending |
| Forms: payment, checkout | 85% | Checkout designed, payment straightforward |
| Forms: check-in, day-wise, others | 80% | New, clear requirements |
| Supabase Auth (phone OTP) | 75% | Blocked on Task 6 (Kiran to enable) |
| Confirmation card UX | 90% | Simple, clear pattern |
| Voice: tap-to-talk + Whisper | 85% | Proven tech stack |
| Wake word "Hey Kozzy" (Porcupine) | 70% | Free tier exists, needs accent testing |
| Multi-language voice (EN/TA/TE/HI) | 75% | Whisper handles it, needs testing |
| Shared test suite (all 3 tracks) | 80% | Golden suite exists, needs expansion |
| 3-agent parallel dev | 80% | Needs solid plan (this spec → plan next) |
| Physical Alexa-like device | 20% | Future, v3+ |

---

## 11. The Pivot Story

```
NOV 2025 — STARTED
  WhatsApp bot with regex intent detection + Groq LLM
  Goal: owner manages PG entirely via chat

MAR–APR 2026 — WHAT WE BUILT
  FastAPI + Supabase backend (95% complete)
  26-table data model
  Intent detection: regex 76.5% → 99.4% with tuning
  PWA scaffold: React + Tailwind + Supabase Auth
  Checkout form designed
  105 golden tests (93 passing)

APR 26 2026 — WHAT WE LEARNED
  Lokesh (receptionist) can't use natural language chat reliably
  Staff have phones only, no laptops
  Natural language ≠ reliable financial data entry
  Bot is right for owners + tenants, wrong for staff data entry

APR 26 2026 — THE PIVOT
  From: WhatsApp-first bot (staff + owner + tenant)
  To:   PWA forms + voice for staff
        WhatsApp bot stays for owner + tenant
  One backend. Three frontends. One source of truth.

VISION
  Phase 1: Forms on shared reception phone (ship in 2 weeks)
  Phase 2: "Hey Kozzy" voice commands (4 weeks)
  Phase 3: Full two-way voice digital receptionist (month 2)
  Future:  Physical device at reception desk (v3+)
```

---

## 12. Pricing (updated)

| Tier | Price | Includes |
|---|---|---|
| Starter | Free (30-day trial) | WhatsApp bot: owner + tenant queries |
| Growth | ₹799/month | All bot features + PWA forms for staff |
| Pro | ₹1,999/month | Everything + "Hey Kozzy" voice assistant |

Voice cost per Pro customer: ~₹250–400/month (Groq Whisper Turbo). Margin: ~₹1,500+/month.

---

## 13. What Success Looks Like

**Week 2:** Lokesh uses Forms for 100% of daily operations. Zero WhatsApp commands from receptionist. Zero missed payments.

**Week 4:** "Hey Kozzy" voice works reliably. Lokesh records a payment in under 5 seconds hands-free.

**Month 2:** First paying external customer onboarded. Same PWA, different Supabase instance.

**Month 3:** 5 paying customers. Voice is the differentiator. No competitor has this.
