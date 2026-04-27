# Kozzy — Product Roadmap

> **Pivot recorded:** 2026-04-26. Staff moved from WhatsApp bot → PWA (forms + voice). WhatsApp stays for owners + tenants. See pivot story in `docs/superpowers/specs/2026-04-26-kozzy-digital-receptionist-design.md`.

---

## Current State (v1.67.0 — LIVE)

- WhatsApp bot live on VPS, regex pipeline 99.4% accuracy
- 105 golden tests (93 passing, 7 known failures)
- Next.js 15 PWA scaffolded: home dashboard, payment form, voice sheet, auth components
- Design system locked: DM Sans, warm cream, pink/blue, pastel tiles
- FastAPI + Supabase backend: 95% complete, 26 tables

---

## Three Parallel Tracks

```
TRACK A — Forms (CRITICAL PATH)     TRACK B — Voice (parallel)     TRACK C — WhatsApp (maintain)
Lokesh uses PWA for all ops         "Hey Kozzy" + tap-to-talk       Owner + tenant bot stays
Ship in 2 weeks                     Ship in 4 weeks                 No new features needed
```

---

## Track A — PWA Forms (Critical Path)

**Goal:** Lokesh uses the app for 100% of daily operations. Zero WhatsApp commands from receptionist.

### Screens to build (priority order)

| Screen | Status | Confidence |
|---|---|---|
| Home dashboard (today's view) | Built | 80% |
| Collect Payment form | Partially built | 85% |
| Dues Query (tenant balance) | Not started | 85% |
| Check In wizard | Not started | 80% |
| Check Out wizard | Spec approved | 85% |
| Day-wise Booking form | Not started | 80% |
| Rental Change form | Not started | 75% |
| Salary Payment form | Not started | 75% |
| Master Data (owner-only) | Not started | 70% |

### Blockers
- Supabase Auth (phone OTP) — Kiran must enable Phone provider + set SMS webhook (Task 6)
- VPS deploy — kozzy-pwa.service (Next.js on Hostinger VPS)

---

## Track B — Voice ("Hey Kozzy")

**Goal:** Record a transaction hands-free in under 5 seconds.

### Components needed

| Component | Status | Confidence |
|---|---|---|
| Mic button + voice sheet | Built (basic) | 80% |
| Groq Whisper integration | Exists (owner PWA spec) | 85% |
| Porcupine wake word "Hey Kozzy" | Not started | 70% |
| VAD (stop when speech ends) | Not started | 75% |
| Confirmation card from voice input | Not started | 80% |
| Multi-language testing (EN/TA/TE/HI) | Not started | 75% |

### Pricing gate
- Growth ₹799 — Forms only
- Pro ₹1999 — Forms + Voice

---

## Track C — WhatsApp Bot (Maintain)

**Goal:** Zero regressions. Existing owners + tenants unaffected by PWA launch.

| Task | Status |
|---|---|
| Fix 7 failing golden tests | Pending |
| Add new screens to shared test suite | Pending (after Track A ships) |
| Parity: all form actions also testable via WhatsApp | Ongoing |

---

## Shared Test Suite (all 3 tracks)

One scenario set. All three input methods must pass the same tests.

| Category | Tests |
|---|---|
| Payment logging | correct room + amount + type |
| Check-in | no double-booking, correct bed |
| Checkout | dues cleared, deposit status |
| Dues query | correct balance, no hallucination |
| Ambiguation flow | system asks clarification |
| Conversation memory | multi-turn ("pay him off") |
| Intent accuracy | no misclassification |
| Edge cases | partial payment, overpayment, no-show |

---

## Phase Plan

### Phase 1 — Forms on reception phone (weeks 1–2)
- All Track A screens built + Playwright tests pass
- Lokesh onboarded — stops using WhatsApp for data entry
- Auth working (Supabase phone OTP)
- Deployed to VPS (kozzy-pwa.service, app.getkozzy.com)

### Phase 2 — Voice layer (weeks 3–4)
- Wake word "Hey Kozzy" + tap-to-talk
- Whisper transcription → confirmation card
- Multi-language tested
- Pro tier unlocked

### Phase 3 — First external customer (month 2)
- Multi-tenant DB isolation (schema-per-tenant or separate Supabase project)
- Client onboarding flow (15 min per new PG)
- ₹799/month Growth tier first sale

### Phase 4 — Scale (month 3+)
- 5 paying customers
- Voice = differentiator, no competitor has this
- Razorpay subscriptions
- Referral + CA partnership GTM

### Future (v3+)
- Physical device at reception desk (Alexa-like with screen)
- Full two-way voice digital receptionist
- Multi-property dashboard

---

## Confidence Tracker

| Component | Confidence | Last updated |
|---|---|---|
| FastAPI backend + data model | 95% | 2026-04-26 |
| PWA scaffold | 80% | 2026-04-26 |
| Forms (payment, checkout) | 85% | 2026-04-26 |
| Forms (check-in, day-wise, others) | 80% | 2026-04-26 |
| Supabase Auth | 75% | 2026-04-26 |
| Voice tap-to-talk + Whisper | 85% | 2026-04-26 |
| Wake word (Porcupine) | 70% | 2026-04-26 |
| Multi-language voice | 75% | 2026-04-26 |
| 3-agent parallel dev | 80% | 2026-04-26 |
| Physical device | 20% | 2026-04-26 |

---

## Agent Architecture (updated)

```
KIRAN
  │
  ▼
ORCHESTRATOR (Claude)
  │  owns: backend API, DB schema, deployments, reviews
  │
  ├── AGENT A: feature/pwa-forms
  │     → all Track A screens + Playwright tests
  │
  ├── AGENT B: feature/pwa-voice
  │     → wake word + Whisper + confirmation card
  │
  └── AGENT C: feature/whatsapp-parity
        → golden test fixes + shared test suite
```

Backend changes go through orchestrator only. Agents consume the API.
