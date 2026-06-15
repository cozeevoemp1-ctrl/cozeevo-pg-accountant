# PWA → Endpoint Map (2026-06-15)

Source of truth for "which page shows which number from which endpoint". Built from
`web/lib/api.ts` + `web/app/**/page.tsx` + `web/components/**`.

All endpoints are under base `/api/v2/app` unless noted. The API client wrappers live in
[web/lib/api.ts](../../../web/lib/api.ts).

---

## 1. API client inventory (web/lib/api.ts → backend)

| api.ts function | Method + path | Backend file |
|---|---|---|
| `getKpi` | GET `/reporting/kpi` | [kpi.py:30](../../../src/api/v2/kpi.py#L30) |
| `getKpiDetail` | GET `/reporting/kpi-detail?type=` | kpi.py (`type` branches) |
| `getCollectionSummary` | GET `/reporting/collection?period_month=` | [reporting.py:18](../../../src/api/v2/reporting.py#L18) → `collection_summary` |
| `getCollectionHistory` | GET `/reporting/collection-history?months=` | reporting.py:33 → `collection_summary` |
| `getDepositsHeld` | GET `/reporting/deposits` | `deposits_breakdown` |
| `getRecentCheckins` | GET `/activity/recent-checkins?limit=` | [kpi.py:1205](../../../src/api/v2/kpi.py#L1205) |
| `getRecentActivity` / `getActivityFeed` | GET `/activity/recent`, `/activity/feed` | kpi.py / activity |
| `getTenantsList` | GET `/tenants/list` | [tenants.py:~40](../../../src/api/v2/tenants.py#L40) `list_tenants` |
| `getTenantDues` | GET `/tenants/{id}/dues` | [tenants.py:232](../../../src/api/v2/tenants.py#L232) `get_tenant_dues` |
| `searchTenants` | GET `/tenants/search` | tenants.py |
| `patchTenant` | PATCH `/tenants/{id}` | tenants.py (+`recalc_checkin_month_rs`) |
| `patchAdjustment` | PATCH `/tenants/{id}/adjustment` | tenants.py |
| `getPreviousStays` | GET `/tenants/{id}/previous-stays` | tenants.py |
| `getCheckinPreview` / `recordCheckin` | GET `/tenants/{id}/checkin-preview`, POST `/checkin/...` | [checkin.py](../../../src/api/v2/checkin.py) |
| `getOverdueTenants` | GET `/reminders/overdue` | [reminders.py:91](../../../src/api/v2/reminders.py#L91) |
| `sendReminder` | POST `/reminders/send` | reminders.py |
| `getActiveNotices` | GET `/notices/active` | [notices.py](../../../src/api/v2/notices.py) |
| `getCheckouts` | GET `/checkouts?month=` | [checkouts.py](../../../src/api/v2/checkouts.py) |
| `getCheckoutPrefetch` | GET `/checkout/tenant/{id}` | [checkout.py:32](../../../src/api/v2/checkout.py#L32) → `_calc_outstanding_dues` |
| `createCheckout` / `getCheckoutStatus` | POST `/checkout/create`, GET `/checkout/status/{token}` | checkout.py |
| `createPayment` | POST `/payments` | [payments.py](../../../src/api/v2/payments.py) |
| `getPaymentHistory` / `editPayment` / `voidPayment` | GET/PATCH/DELETE `/payments` | payments.py |
| `uploadReceipt` / `ocrReceiptPreview` | POST `/payments/{id}/receipt`, `/payments/ocr` | payments.py |
| `getFinancePnl` | GET `/finance/pnl?month=` | [finance.py:454](../../../src/api/v2/finance.py#L454) |
| `downloadPnlExcel` | GET `/finance/pnl/excel` | finance.py → `pnl_builder.py` (verified) |
| `downloadPnlLive` | GET `/finance/pnl/live` | finance.py (live) |
| `getUnitEconomics` | GET `/finance/unit-economics?month=` | [finance.py:1180](../../../src/api/v2/finance.py#L1180) → `unit_economics.py` |
| `getCashPosition` | GET `/finance/cash?month=` | [finance.py:116](../../../src/api/v2/finance.py#L116) |
| `addCashExpense`/`patchCashExpense`/`voidCashExpense`/`logCashCount` | `/finance/cash/...` | finance.py |
| `getDepositReconciliation` | GET `/finance/reconcile?month=` | finance.py |
| `uploadUpiFile`/`getUnmatchedUpi`/`assignUpiEntry` | `/finance/upi-reconcile...` | finance.py |
| `uploadBankCsv` | POST `/finance/upload` | finance.py |
| `getInvestments` | GET `/finance/investments` | finance.py |
| `getOccupancyData` | GET `/analytics/occupancy?months=` | [analytics.py](../../../src/api/v2/analytics.py) |
| `checkRoom`/`checkRoomAvailability` | GET `/rooms/check` | [rooms.py](../../../src/api/v2/rooms.py) |
| `transferRoom` | POST `/tenants/{id}/transfer-room` | `services/room_transfer.py` |
| `quickBook` | POST onboarding | onboarding_router.py |
| `updateBookingSession`/`cancelBookingSession` | `/api/onboarding/admin/{token}` | onboarding_router.py |
| `cancelNoShow` | POST `/tenancies/{id}/cancel-no-show` | tenants.py |
| `getOperationalLogs` + CRUD | `/operations` | [operations.py](../../../src/api/v2/operations.py) |

---

## 2. Page → endpoints

| PWA page | Calls |
|---|---|
| `web/app/page.tsx` (Home) | `getKpi`, `getKpiDetail`(×many types), `getCollectionSummary`, `getRecentCheckins`, `getRecentActivity` |
| `web/components/home/kpi-grid.tsx` | renders `getKpiDetail` payloads |
| `web/components/home/recent-checkins.tsx` | `getRecentCheckins` |
| `web/app/tenants/page.tsx` (Manage) | `getTenantsList`, `searchTenants` |
| `web/app/tenants/[id]/edit/page.tsx` | `getTenantDues`, `patchTenant`, `patchAdjustment`, `deleteTenant`, `getPreviousStays` |
| `web/app/payment/new/page.tsx` | `getTenantDues`, `createPayment` |
| `web/app/checkin/new/page.tsx` | `getTenantDues`, `getCheckinPreview`, `recordCheckin` |
| `web/app/checkout/new/page.tsx` | `getTenantDues` **and** `getCheckoutPrefetch`, `createCheckout`, `getCheckoutStatus` |
| `web/app/checkouts/page.tsx` | `getCheckouts` |
| `web/app/notices/page.tsx` | `getActiveNotices`, `patchTenant` |
| `web/app/reminders/page.tsx` | `getOverdueTenants`, `sendReminder` |
| `web/app/payments/history/page.tsx` | `getPaymentHistory`, `searchTenants`, `editPayment`, `voidPayment` |
| `web/app/collection/history/page.tsx` | `getCollectionHistory` |
| `web/app/collection/breakdown/page.tsx` | `getCollectionSummary`, `getDepositsHeld` |
| `web/app/finance/page.tsx` | `getFinancePnl`, `getUnitEconomics`, `getOccupancyData`, `getCashPosition`, `getInvestments`, reconcile/upload |
| `web/components/finance/occupancy-tab.tsx` | `getOccupancyData` |
| `web/components/finance/cash-tab.tsx` | `getCashPosition`, cash CRUD |
| `web/components/finance/unit-economics-card.tsx` | `getUnitEconomics` |
| `web/components/finance/investment-section.tsx` | `getInvestments` |
| `web/app/operations/page.tsx` | operations CRUD |
| `web/app/activity/page.tsx` | `getActivityFeed` |

---

## 3. Shared-number sourcing (the connectivity risk)

The same business concept, displayed on multiple screens, pulled from **different endpoints**:

### "What does this tenant owe?" — 5 PWA entry points, 5 different backend formulas
| Screen | api.ts | Endpoint | Formula impl |
|---|---|---|---|
| Home dues/overdue tile + panel | `getKpi` / `getKpiDetail` | kpi.py | inline #3, #4 |
| Manage-Tenants list | `getTenantsList` | tenants.py `list_tenants` | inline #2 (bundled) |
| Tenant pages (pay / checkin / edit) | `getTenantDues` | tenants.py `get_tenant_dues` | #1 (canonical-ish, split) |
| Reminders page | `getOverdueTenants` | reminders.py `/overdue` | #7 (bundled) |
| Collection page | `getCollectionSummary` | reporting.py `collection_summary.pending` | #6 (bundled) |
| Checkout page | `getCheckoutPrefetch` | checkout.py → `_calc_outstanding_dues` | #8 (all-months bundled) |

→ See [02_LOGIC_DIVERGENCE.md](02_LOGIC_DIVERGENCE.md#dues). **These do not all agree.**

### Occupancy % — 3 endpoints
| Screen | Endpoint | Impl |
|---|---|---|
| Home vacant-beds tile | `getKpi` → `occupancy.py` | canonical (active + no_show) |
| Finance ▸ Occupancy tab | `getOccupancyData` → analytics.py | canonical occupied; inline `total_beds` (matches) |
| Finance ▸ Unit-Economics card | `getUnitEconomics` → unit_economics.py | **inline, active-only (no no_show)** ← O1 |

### Collected this month — 3 endpoints
| Screen | Endpoint | Impl |
|---|---|---|
| Home collected + Collection pages | `getCollectionSummary` → `collection_summary` | canonical |
| Finance ▸ Cash tab | `getCashPosition` → finance.py | cash-rent only ← C2 |
| Finance ▸ Unit-Economics | `getUnitEconomics` → unit_economics.py | own `total_collected` |

### Revenue / profit — 3 endpoints
| Screen | Endpoint | Impl |
|---|---|---|
| Finance ▸ P&L tab | `getFinancePnl` → finance.py live | live from bank_transactions ← P1/P2 |
| Finance ▸ P&L Excel download | `downloadPnlExcel` → `pnl_builder.py` | hardcoded verified |
| Finance ▸ Unit-Economics | `getUnitEconomics` → unit_economics.py | own `true_revenue` |

---

## 4. Client-side logic in React (.tsx)

| File | What it computes client-side | Note |
|---|---|---|
| `web/app/checkout/new/page.tsx` | `depositForfeited`, `autoRefund = max(deposit − maintenance − dues − deductions, 0)`, day-wise nights adjustment | Mirrors backend `checkout.py:147`; backend re-validates (±100). Acceptable but duplicated. |
| `web/app/notices/page.tsx` | eligible/forfeited split, late-notice rule, `NOTICE_BY_DAY=5` hardcoded | `NOTICE_BY_DAY` duplicated with checkout/new (LOW). |
| `web/components/finance/*` | chart aggregations, `?? 0` null fallbacks | display-only. |

No `.tsx` independently recomputes dues from raw payments — pages trust the dues endpoints
(the divergence is between the endpoints themselves, not page-vs-endpoint).

---

## 5. Notes
- All data flows through `web/lib/api.ts`; a few mutations call `fetch()` directly for
  multipart/DELETE (`uploadReceipt`, `voidPayment`, `deleteTenant`, cash expense edits, onboarding
  admin) — same base URL + auth header, just not via the `_get/_post` helpers.
- No dead endpoints found in the financial set; every endpoint above has ≥1 consumer.
