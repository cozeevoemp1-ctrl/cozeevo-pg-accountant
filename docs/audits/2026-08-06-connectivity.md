# Connectivity + Idempotency Audit — 2026-08-06

> Supersedes `docs/audits/2026-06-15-connectivity/`. Read-only audit; no code changed.
> Companion: `docs/CLEANUP_DRY_RUN.md` (data-layer findings, same date).

## Headline takeaways

1. **No hard breakage** — every PWA fetch target resolves to a registered route. The one user-visible failure: the Reminders page still calls `POST /reminders/send`, which is permanently 410 (`web/app/reminders/page.tsx:36,57`) → guaranteed error toast. Strip the button/page.
2. **Finance UI rebuild orphaned 5 components + ~10 `api.ts` wrappers**, leaving ~12 finance endpoints unreachable from any screen: `cash-tab.tsx`, `unit-economics-card.tsx`, `upi-reconcile-tab.tsx`, `pnl-cards.tsx`, `reconcile-card.tsx` are not imported anywhere. CLAUDE.md "Active files" table is stale about these.
3. **Legacy PIN stack duplicates v2 with weaker validation.** Biggest risk **D-1**: legacy `POST /api/checkout/create` (`checkout_router.py:116`, used by `static/checkout_admin.html`) does **no refund/forfeiture re-validation** — it persists whatever the client sends; the v2 path re-validates ±₹100. Also dead: `sync_router.py` (unmounted file), empty `/api/report` shell, `/api/ingest` + `/api/entities` (superseded by `/finance/upload`), `/api/onboarding/admin/stats`, `regen-pdf`, v2 `voice/*` (client-side now), v2 `blacklist` REST (bot/PWA use the service directly).
4. **Monthly dues still have 7 inline implementations + 3 bot helpers** (day-stay dues WERE unified in `services/daily_dues.py`). kpi tile/panel are hand-resynced copies of `get_tenant_dues` — the exact drift mechanism that caused past mismatches. June audit's Phase-2 item (shared `compute_tenant_dues()`) remains open.
5. **Write guards are strong overall** (payments unique_hash + DB index, bank/UPI dedup, booking overlap constraint + no_overlap DB constraint, onboarding phone dedup). Unguarded creators: `POST /finance/cash/expenses`, `POST /finance/cash/counts` (double-tap = 2 rows), and the quick-book advance Payment row (`bookings.py:265` raw insert, no unique_hash).

## Dues implementations (D-2 — the structural debt)

| # | Impl | Location |
|---|---|---|
| 1 | `get_tenant_dues` (canonical-ish, split rent/deposit) | `src/api/v2/tenants.py:240-436` |
| 2 | `list_tenants` bundled calc (deposit lumped in, no booking credit) | `tenants.py:40-122` |
| 3 | kpi dues tile (copy of #1 math) | `src/api/v2/kpi.py:237-310` |
| 4 | kpi dues panel (copy of #3) | `kpi.py:578-702` |
| 5 | recent-checkins balance | `kpi.py:1251+` |
| 6 | collection pending | `src/services/reporting.py:104+` |
| 7 | reminders overdue | `src/api/v2/reminders.py:37-135` |
| 8 | `_calc_outstanding_dues` (bot + v2 checkout share it — but it lives in a bot handler) | `src/whatsapp/handlers/account_handler.py:985` |
| + | bot: `build_dues_snapshot` (`_shared.py:406`), `_my_balance` (`tenant_handler.py:55`), `_prev_outstanding` (`monthly_rollover.py:38`) | |

## Other drift risks

| # | Concept | Detail | Risk |
|---|---|---|---|
| D-1 | Checkout create | legacy PIN path skips refund validation (above) | HIGH |
| D-3 | list_tenants ≠ dues page | visible number mismatch in Manage list | MED |
| D-4 | unit-economics occupancy counts active-only vs canonical `services/occupancy.py` | masked while card is orphaned | LOW→MED |
| D-5 | Notice day-5 rule hardcoded in PWA | `checkout/new/page.tsx:18`, `notices/page.tsx:9`, `edit/page.tsx:288,758,773` vs backend `services/property_logic.py` | MED |
| D-7 | Three P&L revenue derivations | `pnl_builder.py` vs `_compute_dynamic_pnl_months` vs `three-statement` | MED |
| — | auth_hooks docstring says configure `…/api/v2/auth/send-otp`; real mount is `/api/v2/app/auth/send-otp` | moot (email login) but fix docstring | LOW |

## Proposed unified structure (Phase 3 — pending Kiran approval, NOT implemented)

1. **`src/services/dues.py`** — one `compute_tenant_dues(tenancy, session, *, as_of)` returning a typed breakdown (rent, deposit, adjustments, booking_credit, first-month split). Wire all 8+3 call-sites to it, mirroring the daily_dues.py consolidation. This is the single highest-value refactor in the codebase.
2. **Retire the legacy PIN checkout stack**: point `static/checkout_admin.html` at v2 (or delete the static page if unused by staff), then tombstone `/api/checkout/*` with 410 like direct-checkin. Fixes D-1 without touching v2.
3. **Delete dead weight** (after Kiran OK): `src/api/sync_router.py`, empty report_router, `/api/ingest`, `/api/entities`, v2 `voice/*`, `admin/stats`, `regen-pdf`; either delete or deliberately re-mount the 5 orphaned finance components (unit-economics + cash tab were built to spec — decide if they return in the redesign).
4. **Guards**: add dedup window to cash expenses/counts; give quick-book advance the same unique_hash path as `log_payment`.
5. **PWA constants**: export NOTICE_BY_DAY via `/field-registry` (endpoint already exists) or a config response, kill the 3 hardcoded `5`s.
6. **Web app (desktop)** consumes the same `/api/v2/app` routes + `web/lib/api.ts` — no new API surface; the redesign (Phase 4) builds on this single layer.
