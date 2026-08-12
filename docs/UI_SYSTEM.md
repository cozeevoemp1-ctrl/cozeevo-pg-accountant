# PWA UI System — single source of truth

**The rule: before writing ANY new UI, check this file. If a primitive exists, import it.
Never re-implement a formatter, overlay, header, or color. If a primitive is missing,
add it HERE (lib/ or components/ui/) first, document it below, then use it.**
(Adopted 2026-08-12 after an audit found 15 INR formatters, 10 date formatters and
11 hand-rolled modals. Consolidation lesson: duplicated copies diverge and grow bugs.)

## Formatters — `web/lib/format.ts`
| Function | Output | Use for |
|---|---|---|
| `rupee(n)` | `₹1,23,456` (lakh grouping, negative-safe) | default money display |
| `rupeeExact(n)` | `₹1,235` (rounds) | computed amounts (dues math) |
| `rupeeShort(n)` | `₹1.2Cr` / `₹4.5L` / `₹12.3K` | dense cards, charts, KPIs |
| `indianNumber(n)` | `1,23,456` (no symbol) | tables where ₹ is in the header |

Never: local `inr()`/`fmtINR()`, inline `` `₹${x.toLocaleString("en-IN")}` ``, `"Rs."`.

## Dates & months — `web/lib/date.ts`
| Function | Output |
|---|---|
| `fmtDate(iso)` | `5 Jan 2026` |
| `fmtDateShort(iso)` | `5 Jan` |
| `fmtDateTime(iso)` | `5 Jan 2026, 3:42 PM` |
| `todayISO()` / `nowTime()` | `2026-01-05` / `15:42` |
| `monthLabel("2026-01")` | `Jan 2026` (`{long:true}` → `January 2026`) |
| `addMonths("2026-01", -1)` | `2025-12` |
| `periodMonth(date?)` | `2026-01` |

These parse by string-splitting — no `new Date("YYYY-MM-DD")` TZ off-by-one.
Never: local `fmtDate`, month-name arrays, `prevMonth`/`nextMonth` copies.

## Overlays — `web/components/ui/modal.tsx`
`<Modal open onClose title>` (centered card) and `<Sheet open onClose title>` (bottom sheet).
Both encode the hard rules: inline `zIndex: 9999` (Tailwind arbitrary z- gets purged;
tab bar is z-50) and Sheet's safe-area bottom padding. Backdrop-tap closes by default
(`closeOnBackdrop={false}` for must-decide dialogs). Never hand-roll `fixed inset-0`.

## Page furniture — `web/components/ui/`
| Component | Use |
|---|---|
| `<PageHeader title backHref? right?>` | every page top: ← back + title |
| `<MonthNav value onChange maxMonth? dark?>` | ← Jan 2026 → month pickers |
| `<Spinner />` | loading spinner (brand-pink ring) |
| `<Skeleton className="h-4 w-32" />` | skeleton bars |
| `<EmptyState>No payments found</EmptyState>` | empty lists |
| `<Card>`, `<Button>`, `<ProgressBar>`, `<TabBar>` | existing primitives — use them |
| `<DatePickerInput>` / `<DateTimePickerInput>` | date inputs (calendar popup) |

## Forms — `web/components/forms/`
`<ConfirmationCard>` for every review-and-save step. `<TenantSearch>` for every tenant
lookup. `<Numpad>`, `<ReceiptScanner>` as-is.

## Data fetching — `web/lib/api.ts`
Every backend call goes through a typed function in `lib/api.ts` (which owns auth
headers, `res.ok` checking, error extraction, `BASE_URL`). Raw `fetch()` in a
page/component is a bug. New endpoint → add the typed wrapper first.

## Color tokens — `web/tailwind.config.ts`
| Token | Hex | Use |
|---|---|---|
| `bg` / `surface` | `#F6F5F0` / `#FFFFFF` | page bg / cards |
| `border` / `border-strong` | `#F0EDE9` / `#E0DDD8` | hairlines / input+card edges |
| `ink` / `ink-muted` | `#0F0E0D` / `#6F655D` | text |
| `brand-pink` / `brand-blue` | `#EF1F9C` / `#00AEED` | brand |
| `status-paid/due/warn` | greens/pink/orange | statuses |
| `tile-green/pink/blue/orange` | pastels | KPI tiles |

Never type a hex that has a token (`#E2DEDD` was an accidental fork of `#E0DDD8` — use
`border-strong`). Missing a color? Add the token first.

## Known debt (accepted, don't copy the pattern)
- `bg-tile-yellow` is used in app/tenants/page.tsx (Overdue tile) but has NO token in
  tailwind.config.ts — the class silently resolves to nothing (pre-existing bug;
  needs a design decision on the yellow).
- Full-bleed sticky page headers (checkin/checkout/notices/operations, tenant edit)
  keep their custom bars — PageHeader has no subtitle/kicker slot yet; add one before
  migrating them.
- Voice sheets keep their custom bottom-sheet roots (recording-lock backdrop,
  drag handle) — migrate to `<Sheet>` only after it grows those affordances.
- Finance dark-theme palette (`#080d14` family) is untokenised — tokenise when the
  finance tree is next reworked.
- `date-picker-input` and `datetime-picker-input` share ~120 duplicated lines — merge
  into one `withTime` component when next touched.
- Orphaned finance components (cash-tab, upi-reconcile-tab, reconcile-card,
  unit-economics-card, pnl-cards) awaiting Kiran's restore-vs-delete decision.
