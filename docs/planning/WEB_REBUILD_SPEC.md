# Web + Mobile Rebuild — Functionality Inventory & Principles (2026-08-06)

> Source of truth for the new Web app (and later the mobile app, same look/feel).
> **Existing PWA stays unchanged and live until the new Web reaches parity.**
> Companion docs: `docs/audits/2026-08-06-connectivity.md` (endpoint map), `docs/CLEANUP_DRY_RUN.md`.
> Design demo: claude.ai artifact `6e816cd3` (Cupertino framework, kit TBD).

## 0. Non-negotiable architecture principles (from Kiran, 2026-08-06)

1. **One data point = one endpoint.** History, activity, dues, occupancy each have exactly ONE backend source consumed by PWA, Web, bot and exports. No screen-local reimplementations (the June/Aug audits found 7 monthly-dues copies and history/activity duplication — the rebuild consumes shared services only).
2. **Universal inspector pattern.** Clicking any row/tile anywhere opens the right-side detail panel with live data + actions (never navigate away for a preview).
3. **Every list ships with minimal filters + sorting** (segmented filter pills + sortable column headers). No filter crowding.
4. **Exports come from the same endpoints as screens** — a report can never disagree with the app.
5. Additive rollout: new Web at `web-v2` route/app consuming the SAME `/api/v2/app` layer; zero backend forks.

## 1. Carry-over inventory — everything the PWA does today

### Home / overview
- KPI tiles (occupied, dues, check-ins, checkouts, day-stays) with tap-to-expand detail lists → becomes KPI strip + Bed Board
- Recent check-ins (45-day, paid/partial/unpaid, deep-link to collect) → inspector queue
- Recent activity feed (payments-derived) → single activity endpoint (see §3)
- Quick actions: quick-book, collect payment, cancel no-show

### Tenants
- List + debounced search (active-only default) · dues per tenant (shared dues service) 
- Edit tenant: personal fields, financials (rent/deposit/maintenance/lock-in), Full/Prorated toggle, notice set/clear (auto-clears expected_checkout), notes; audit-logged; first-month RS recalc on money-field change
- Previous stays panel · payment history across tenancies · transfer room (shared `execute_room_transfer`) · delete (FK-safe) · cancel no-show · pre-register (room 000)
- NEW: sortable columns, status filters, inspector with dues breakdown + mini ledger + actions (collect / remind / notice / history)

### Payments
- Record payment: numpad, tenant search auto-loads dues, suggested amounts, mode, for_type, period; ConfirmationCard before write; unique-hash dedup; frozen-period guard
- History: all tenancies incl. exited; void with reason (never delete) + audit; receipt image (Claude vision classify)
- NEW: Daily collections register (day picker, cash/UPI × rent/deposit/advance matrix, recorded-by, cash-count line)

### Bookings / onboarding
- Quick-book (blacklist check, phone dedup, overlap + capacity guards, advance payment) · pending sessions list ("Save & Check In" approve) · edit session (capacity re-check) · resend link · cancel (releases tenancy + voids RS) · extract-ID (vision) · admin notes (special_terms) · agreement PDF on approve · day-stay bookings (daily_rate, num_days)

### Check-in / Check-out / Notices / Checkouts history
- Check-in preview + guarded activate (pending-form block, capacity, same-day payment dedup)
- Checkout: dues/refund calc (deposit − dues − maintenance − deductions), notice/forfeiture rules (day ≤ 5), day-stay exclusion, keys/biometric checklist, refund record, tenant confirm link
- Notices page: eligible vs late-notice vs forfeited, replacement chips, multi-select filters
- Checkouts page: month picker, All/Regular/Day-wise

### Finance (admin-gated) — FULL parity required
- Bank CSV upload THOR/HULK (unique-hash dedup, auto-classifier + Kiran's rules, tenant-refund auto-detect)
- P&L: verified frozen months + dynamic months, SOP Excel download, manual adjustments (cash holding / rent in cash / cash expense), frozen-month write-reject
- Cash tab: cash position, expenses CRUD, count log + variance (REVIVE — orphaned in current PWA)
- Occupancy analytics: monthly KPIs, type breakdown, check-ins vs outs, avg rent/bed
- Unit economics (REVIVE — orphaned): per-bed KPIs, investment return (₹2.31Cr basis), revenue quality
- Deposit reconciliation · UPI reconcile w/ RRN matching (REVIVE) · investments section (per-investor) · three-statement view
- Audit-log generators (deposit refund + salary) after every import

### Operations / Auth / Roles
- Operational logs (power/gas/water/garbage) w/ monthly summaries · inline edit
- Supabase auth: login, forgot-password (PKCE), role gates (staff blocked from /finance), logout
- Roles: admin / staff parity as today; same middleware model

### WhatsApp bot (unchanged, same endpoints)
- All financial/ops intents keep working against the same services — the rebuild MUST NOT fork logic the bot shares (dues, transfer, checkout, collection summary).

## 2. NEW in Web v2 (approved direction)
- **Bed Board** — 297-bed mosaic by payment state, filters (dues/vacant/today), room inspector (occupants, dues, ledger, flags, actions)
- **Daily collections register** (Finance tab)
- **Reports & export center**: payment history, room movement history, monthly collections (cash/UPI × rent/deposit tabular), activity log, dues snapshot — date-range + Excel/CSV, all from shared endpoints; recent-exports list
- Universal inspector + sorting/filters everywhere · Ctrl-K tenant/room/action search · sticky KPI strip
- Later: smart query bar (needs `/api/v2/app/query`)

## 2b. Month-close pipeline in-app (Kiran 2026-08-06: "scripts run from VS Code must be buttons")
Map each manual SOP step (memory `sop_pnl.md`) to a server-side job with UI, admin-only, every run audit-logged:
| VS Code / script today | In-app job |
|---|---|
| CSV upload via endpoint | exists — `POST /finance/upload` (unique_hash dedup) |
| `pnl_classify.py` rules + `reference_pnl_classifications.md` | rules table in DB + Rules Editor UI; auto-apply on import |
| Manual "who is this payee" sessions with Claude | **Review-unknowns queue**: name a payee once → saved rule; blocks month close until empty (or explicit skip) |
| `scripts/_generate_audit_logs.py` | `POST /finance/audit/generate` → deposit-refund + salary registers as in-app views |
| `pnl_monthly_adjustments` (cash holding / rent in cash / cash expense) | exists — surface in Uploads tab, editable pre-recalc |
| `_compute_dynamic_pnl_months` on demand | `POST /finance/recalculate?month=` — refreshes P&L/collections/dues caches |
| `pnl_builder` Excel | exists — `GET /finance/pnl/excel` |
| Known catch-all bug (Bank Charges swallows NEFT principal) | fix classifier BEFORE porting rules (open item from Session R) |
Guardrails: frozen months reject, job history (who/when/rows touched), dry-run preview diff before commit — same discipline as CLEANUP_DRY_RUN.

## 3. Endpoint consolidation prerequisites (approved Phase 3 — build BEFORE Web v2 screens)
1. `services/dues.py` — single `compute_tenant_dues()`; wire all 8 API + 3 bot call-sites
2. Single **activity** endpoint (payments + audit_log derived); Home feed, Reports activity export, history views all consume it
3. Retire legacy PIN checkout stack (D-1 refund-validation hole); tombstone 410
4. Delete dead routers (sync_router, ingest, entities, voice, blacklist REST unless Web needs it → it does: blacklist admin UI → keep + wire)
5. Dedup guards: cash expenses/counts, quick-book advance unique_hash
6. `NOTICE_BY_DAY` and TOTAL_BEDS served from config/field-registry endpoint (kill PWA hardcodes)

## 4. Mobile app (phase after Web v2)
- Same design system + components (Next.js PWA shell or Capacitor wrap — decide later); bottom pill nav (Board / Collect / + / Tenants / More); inspector = bottom sheet; 48px targets; numpad + ConfirmationCard patterns carried over. Existing PWA retired only after mobile parity sign-off.

## 5. Multi-tenant SaaS readiness (Kozzy as product — design decisions to bake in NOW)
- **Token-driven theming = white-label for free.** The 7-kit switcher proves rebranding is ~20 CSS variables. Ship a neutral platform default kit; each customer org gets accent + logo + name as DB config. No per-customer redesign ever.
- **Bed Board renders from data, not layout constants**: buildings/floors/rooms/beds come from the `rooms` table per org — any property shape (1 building or 5, 40 beds or 400) lays out automatically (side-by-side buildings when width allows). This is the flagship differentiator feature for sales demos.
- **Kill every hardcoded constant** (TOTAL_BEDS in 8 files, NOTICE_BY_DAY, building names, admin phones) → per-org settings served by the config endpoint. This is the single biggest SaaS blocker today, not the design.
- **Terminology + locale config**: tenant/guest/resident label, currency, date format, month-cycle rules per org.
- **`org_id` already exists across the schema** — enforce it everywhere + Postgres RLS for isolation; per-org auth roles; per-org WhatsApp number (Meta WABA per customer or shared with sender profiles).
- **Onboarding wizard as a product feature**: the Excel→Sheet→DB import pipeline (clean_and_load) becomes "bring your data" — that ugly migration work is a moat, competitors make customers start empty.
- Pricing/tiers already sketched in `docs/business/PRICING.md`; demo mode (DEMO_MODE + sanitized sync) already built for sales demos.

## 6. Rollout order
1. Phase 3 backend consolidation (§3) + tests → deploy
2. Web v2 scaffold (`web/` new route group or separate app) with locked brand kit + Cupertino type framework
3. Screens in order: Bed Board → Tenants → Payments/Register → Bookings → Checkout/Notices → Finance tabs → Reports → Ops
4. Playwright E2E per screen (Phase 5) · PWA untouched throughout
