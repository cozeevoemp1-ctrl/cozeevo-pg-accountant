# Kozzy — Product Roadmap

## Current State (v1.7.0 — LIVE)
- Bot live on VPS, WhatsApp connected
- 21 DB tables, 234 tenants imported
- Regex pipeline: 99.4% accuracy
- Golden suite: 93/100 (7 failing)

---

## Phase 1 — Stabilise (this week)
**Goal: production-quality bot, 100% golden tests, VPS fully up to date**

| Task | Owner | Status |
|---|---|---|
| Fix 7 failing golden tests | Claude | Pending |
| Push all local changes to VPS | Manual `/ship` | Pending |
| Verify live bot end-to-end | Kiran | Pending |

### 7 Failing Tests to Fix
| ID | Fix |
|---|---|
| G003 | Add "Arjun" tenant to DB or update test |
| G014, G032 | Room 203 has open complaint — use room 301 in test |
| G024 | Saurabh checked out — update test to different tenants |
| G034 | Add regex: "did Raj pay this month?" → QUERY_TENANT |
| G069 | ADD_REFUND handler: ask for name when missing |
| G072 | Include amount in disambiguation reply |

---

## Phase 2 — Tenant Experience (next 2 weeks)
**Goal: tenants can self-serve fully via WhatsApp**

| Feature | Intent | Notes |
|---|---|---|
| Rent receipt on request | MY_PAYMENTS | PDF/text receipt |
| Complaint status tracking | COMPLAINT_STATUS | "is my complaint fixed?" |
| Notice submission | GIVE_NOTICE | tenant sends formal notice |
| UPI payment link | REQUEST_PAYMENT_LINK | send QR/link to pay |
| Move-in checklist | ONBOARDING flow | already built, needs polish |

---

## Phase 3 — Owner Automation (month 2)
**Goal: owner spends <5 min/day on routine tasks**

| Feature | Intent | Notes |
|---|---|---|
| Auto-send dues reminders | REMINDER_SET (scheduled) | WhatsApp blast to defaulters |
| Monthly report auto-send | REPORT (scheduled) | 1st of every month |
| Expiring agreements alert | QUERY_EXPIRING (scheduled) | 7 days before |
| Expense photo → auto-log | ADD_EXPENSE | WhatsApp image → OCR → expense |
| Bank statement reconcile | (pipeline) | upload PDF → auto-match payments |

---

## Phase 4 — SaaS (month 3+)
**Goal: onboard second PG client**

| Task | Notes |
|---|---|
| Multi-tenant DB isolation | Supabase project per client OR schema-per-tenant |
| Client onboarding flow | New Supabase + .env + nginx block (15 min per client) |
| Billing/subscription | Razorpay or Stripe — per-seat or per-property |
| Admin dashboard (web) | Simple React dashboard for owner |
| WhatsApp number management | Each client gets own WA number |

---

## Agent Architecture (how Claude works on this project)

```
You (Kiran)
    ↓ instruction
Main Claude (orchestrator)
    ├── reads CLAUDE.md for instant project context
    ├── does simple edits directly (no subagent)
    ├── spawns Explore subagent for deep codebase search
    ├── spawns Plan subagent for architecture decisions
    └── spawns general-purpose subagent for:
            - running tests
            - multi-file refactors
            - parallel independent tasks

Rules:
- Start NEW conversation every 30-40 turns (avoids context overload)
- Use /compact when context gets heavy
- CLAUDE.md = always loaded, no need to re-explain the project
- /ship = commit + push (no confirmation needed, pre-authorized)
```

---

## Feature Priority Matrix

| Feature | Impact | Effort | Priority |
|---|---|---|---|
| Fix 7 golden tests | High (stability) | Low | NOW |
| VPS deploy | High (live) | Low | NOW |
| Auto dues reminders | High (saves time daily) | Medium | P1 |
| Monthly report auto-send | High | Low | P1 |
| Expense photo → log | High (UX) | Medium | P2 |
| Tenant UPI payment link | High (collections) | Medium | P2 |
| Bank reconciliation | Medium | High | P3 |
| Web dashboard | Medium | High | P3 |
| SaaS multi-tenant | High (revenue) | High | P4 |
