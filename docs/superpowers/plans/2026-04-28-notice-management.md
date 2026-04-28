# Notice Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add notice management to the PWA — dashboard KPI tile, tenant edit notice section, checkout auto-fill, and bot NOTICE_WITHDRAWN intent.

**Architecture:** Backend extends three existing API endpoints (KPI, tenant dues/patch, checkout prefetch) and adds one bot intent. Frontend adds one tile, one edit section, and one checkout banner — all reusing existing component patterns.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js 14 + Tailwind (frontend), gspread (sheet sync), regex intent detection.

---

## File Map

| File | Change |
|---|---|
| `src/schemas/kpi.py` | Add `notices_count: int` |
| `src/api/v2/kpi.py` | Add notices query to `get_kpi()` + `type=notices` branch to `get_kpi_detail()` |
| `src/api/v2/tenants.py` | Add `notice_date` + `expected_checkout` to dues GET; add `notice_date` handling to PATCH |
| `src/api/v2/checkout.py` | Add `expected_checkout` to prefetch response |
| `src/integrations/gsheets.py` | Handle `notice_date=None` in `record_notice()` to clear sheet cells |
| `src/whatsapp/intent_detector.py` | Add `NOTICE_WITHDRAWN` pattern to `_OWNER_RULES` |
| `src/whatsapp/handlers/owner_handler.py` | Add `_withdraw_notice()` handler + register in handler map |
| `web/lib/api.ts` | Add `notices_count`, `deposit_eligible`, `notice_date`, `expected_checkout` to interfaces |
| `web/components/home/kpi-grid.tsx` | Add `"notices"` tile + deposit badge rendering |
| `web/app/tenants/[tenancy_id]/edit/page.tsx` | Add Notice card (notice_date, expected_checkout, deposit badge, withdraw button) |
| `web/app/checkout/new/page.tsx` | Add notice banner + auto-fill `checkoutDate` from `expected_checkout` |

---

## Task 1: Backend — KPI notices_count + kpi-detail

**Files:**
- Modify: `src/schemas/kpi.py`
- Modify: `src/api/v2/kpi.py`

- [ ] **Step 1: Add `notices_count` to KPI schema**

In `src/schemas/kpi.py`, add the field after `no_show_count`:

```python
class KpiResponse(BaseModel):
    occupied_beds: int
    total_beds: int
    vacant_beds: int
    occupancy_pct: float
    active_tenants: int
    no_show_count: int
    notices_count: int          # ← add this
    checkins_today: int
    checkouts_today: int
    overdue_tenants: int
    overdue_amount: float
```

- [ ] **Step 2: Add notices query to `get_kpi()`**

In `src/api/v2/kpi.py`, add this block immediately after the `no_show_count` block (before `# Check-ins today`):

```python
        # Tenants on notice (active, notice_date set)
        notices_count = int(
            await session.scalar(
                select(func.count(Tenancy.id))
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "UNASSIGNED",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.notice_date != None,
                )
            ) or 0
        )
```

- [ ] **Step 3: Add `notices_count` to the KpiResponse return**

Update the `return KpiResponse(...)` call to include:

```python
    return KpiResponse(
        occupied_beds=occupied_beds,
        total_beds=total_beds,
        vacant_beds=vacant_beds,
        occupancy_pct=occ_pct,
        active_tenants=active_tenants,
        no_show_count=no_show_count,
        notices_count=notices_count,        # ← add this
        checkins_today=checkins_today,
        checkouts_today=checkouts_today,
        overdue_tenants=overdue_tenants,
        overdue_amount=overdue_amount,
    )
```

- [ ] **Step 4: Add `type=notices` branch to `get_kpi_detail()`**

In `src/api/v2/kpi.py`, add this `elif` block inside `get_kpi_detail()` immediately before the final `return {"type": type, "items": []}` line:

```python
        elif type == "notices":
            rows = (await session.execute(
                select(
                    Tenancy.id, Tenant.name, Room.room_number,
                    Tenancy.notice_date, Tenancy.expected_checkout,
                )
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .join(Room, Room.id == Tenancy.room_id)
                .where(
                    Room.is_staff_room == False,
                    Room.room_number != "UNASSIGNED",
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.notice_date != None,
                )
                .order_by(Tenancy.expected_checkout.asc().nulls_last())
            )).all()
            return {"type": type, "items": [
                {
                    "tenancy_id": r.id,
                    "name": r.name,
                    "room": r.room_number,
                    "detail": r.expected_checkout.strftime("%-d %b") if r.expected_checkout else "—",
                    "deposit_eligible": (r.notice_date.day <= 5) if r.notice_date else None,
                }
                for r in rows
            ]}
```

- [ ] **Step 5: Verify locally**

Start the API: `venv/Scripts/python main.py`
Hit the endpoint: `curl -s http://localhost:8000/api/v2/app/reporting/kpi` (needs auth — just confirm it starts without error)
Check logs for any import errors.

- [ ] **Step 6: Commit**

```bash
git add src/schemas/kpi.py src/api/v2/kpi.py
git commit -m "feat(api): notices_count in KPI + kpi-detail?type=notices endpoint"
```

---

## Task 2: Backend — TenantDues + PATCH for notice_date

**Files:**
- Modify: `src/api/v2/tenants.py`

- [ ] **Step 1: Add `notice_date` and `expected_checkout` to dues GET response**

In `src/api/v2/tenants.py`, in the `get_tenant_dues()` function, add these two fields to the return dict (after `"period_month"`):

```python
        "notice_date":      tenancy.notice_date.isoformat() if tenancy.notice_date else None,
        "expected_checkout": tenancy.expected_checkout.isoformat() if tenancy.expected_checkout else None,
```

- [ ] **Step 2: Add `notice_date` handling to PATCH**

In `src/api/v2/tenants.py`, in the `update_tenant()` PATCH handler, add this block after the existing `if "expected_checkout" in body:` block:

```python
        if "notice_date" in body:
            val = body["notice_date"]
            tenancy.notice_date = date.fromisoformat(val) if val else None
```

- [ ] **Step 3: Call `gsheets.record_notice()` on notice_date change in PATCH**

In `update_tenant()`, replace the existing `trigger_monthly_sheet_sync` call at the end with:

```python
    today = date.today()
    from src.integrations.gsheets import trigger_monthly_sheet_sync, record_notice

    # Sync notice to sheet if notice_date was in the patch body
    if "notice_date" in body:
        import asyncio
        notice_val = body["notice_date"] or ""
        checkout_val = body.get("expected_checkout") or ""
        if isinstance(checkout_val, date):
            checkout_val = checkout_val.isoformat()
        # Run sheet sync in background — don't block the response
        asyncio.create_task(
            record_notice(tenancy.room_number_cached or "", tenant.name, notice_val, checkout_val)
        )

    trigger_monthly_sheet_sync(today.month, today.year)
```

Wait — `room_number` isn't on the tenancy directly. Fetch it:

```python
    today = date.today()
    from src.integrations.gsheets import trigger_monthly_sheet_sync, record_notice

    if "notice_date" in body:
        import asyncio
        async with get_session() as _s:
            _room = await _s.get(Room, tenancy.room_id)
            _room_number = _room.room_number if _room else ""
        notice_val = body["notice_date"] or ""
        checkout_val = body.get("expected_checkout") or ""
        asyncio.create_task(
            record_notice(_room_number, tenant.name, notice_val, checkout_val)
        )

    trigger_monthly_sheet_sync(today.month, today.year)
```

- [ ] **Step 4: Add `Room` to imports if not already present**

Ensure `Room` is imported at the top of `src/api/v2/tenants.py`. Check existing imports — if `Room` is already there, skip. If not:

```python
from src.database.models import (
    ...
    Room,       # ← add if missing
    ...
)
```

- [ ] **Step 5: Verify locally**

Start API and confirm startup is clean. No test needed here — covered by integration.

- [ ] **Step 6: Commit**

```bash
git add src/api/v2/tenants.py
git commit -m "feat(api): notice_date in tenant dues GET + PATCH support with sheet sync"
```

---

## Task 3: Backend — Checkout prefetch adds expected_checkout

**Files:**
- Modify: `src/api/v2/checkout.py`

- [ ] **Step 1: Add `expected_checkout` to prefetch response**

In `src/api/v2/checkout.py`, in `checkout_prefetch()`, add to the return dict after `"notice_date"`:

```python
            "expected_checkout": tenancy.expected_checkout.isoformat() if tenancy.expected_checkout else None,
```

- [ ] **Step 2: Commit**

```bash
git add src/api/v2/checkout.py
git commit -m "feat(api): add expected_checkout to checkout prefetch response"
```

---

## Task 4: Backend — gsheets record_notice handles None (clear)

**Files:**
- Modify: `src/integrations/gsheets.py`

- [ ] **Step 1: Understand current behaviour**

`record_notice(room, name, notice_date: str, expected_exit: str = "")` currently writes `notice_date` string directly. If `notice_date = ""` it writes an empty string, which clears the cell — this already works for clearing.

The async wrapper passes straight through to `_record_notice_sync`. No code change needed for clearing — passing `""` already clears. **Verify** this is correct by reading lines ~1237-1307 of `src/integrations/gsheets.py` and confirming `batch_update` with `[[""]]` is what happens.

- [ ] **Step 2: Add type hint + None guard to async wrapper**

Update the async `record_notice` signature to accept `None`:

```python
async def record_notice(
    room_number: str,
    tenant_name: str,
    notice_date: str | None,
    expected_exit: str | None = "",
) -> dict:
    return await asyncio.to_thread(
        _record_notice_sync,
        room_number,
        tenant_name,
        notice_date or "",
        expected_exit or "",
    )
```

This ensures callers can pass `None` safely and it converts to `""` before the sync function sees it.

- [ ] **Step 3: Commit**

```bash
git add src/integrations/gsheets.py
git commit -m "fix(gsheets): record_notice accepts None for notice_date/expected_exit (clears cells)"
```

---

## Task 5: Bot — NOTICE_WITHDRAWN intent + handler

**Files:**
- Modify: `src/whatsapp/intent_detector.py`
- Modify: `src/whatsapp/handlers/owner_handler.py`

- [ ] **Step 1: Add NOTICE_WITHDRAWN pattern to intent_detector**

In `src/whatsapp/intent_detector.py`, find the `_OWNER_RULES` list. Add this tuple near the existing `NOTICE_GIVEN` pattern (after it, so NOTICE_GIVEN's more specific patterns match first):

```python
(re.compile(
    r"cancel\s+notice|withdraw\s+notice|remove\s+notice|revoke\s+notice|"
    r"not\s+leaving|changed\s+mind\s+(?:about\s+)?leaving|won['’]?t\s+(?:be\s+)?leaving|"
    r"will\s+not\s+leave|take\s+back\s+notice|notice\s+cancel(?:led)?|cancel(?:led)?\s+notice",
    re.I,
), "NOTICE_WITHDRAWN", 0.93),
```

- [ ] **Step 2: Verify pattern doesn't conflict**

Run the existing intent test suite to make sure no regressions:

```bash
venv/Scripts/python tests/benchmark_intent.py 2>/dev/null | tail -5
```

Expected: existing accuracy unchanged.

- [ ] **Step 3: Add `_withdraw_notice()` handler to owner_handler**

In `src/whatsapp/handlers/owner_handler.py`, add this function. Find a logical place near `_notice_given` (search for `async def _notice_given`):

```python
async def _withdraw_notice(ctx: MessageContext, session) -> str:
    """Cancel/withdraw a notice — clears notice_date + expected_checkout from DB + Sheet."""
    from src.whatsapp.handlers._shared import fuzzy_search_tenants

    # Parse tenant name/room from message
    search_term = ctx.text.strip()
    # Strip the command words to isolate the tenant identifier
    import re as _re
    search_term = _re.sub(
        r"cancel\s+notice|withdraw\s+notice|remove\s+notice|revoke\s+notice|"
        r"not\s+leaving|changed\s+mind.*?leaving|won['’]?t\s+(?:be\s+)?leaving|"
        r"will\s+not\s+leave|take\s+back\s+notice|notice\s+cancel(?:led)?",
        "", search_term, flags=_re.I,
    ).strip(" \t\n:–-")

    if not search_term:
        return "Who should I withdraw the notice for? E.g. *withdraw notice Raj Kumar*"

    rows = await fuzzy_search_tenants(search_term, session, status_filter="active")
    # Filter to only tenants who actually have a notice on record
    rows = [r for r in rows if r.get("notice_date")]

    if not rows:
        return f"No active tenant on notice matching *{search_term}*."

    if len(rows) == 1:
        r = rows[0]
        notice_str = r["notice_date"].strftime("%d %b %Y") if hasattr(r["notice_date"], "strftime") else str(r["notice_date"])
        exit_str = r["expected_checkout"].strftime("%d %b %Y") if r.get("expected_checkout") and hasattr(r["expected_checkout"], "strftime") else "—"
        action_data = {
            "tenancy_id": r["tenancy_id"],
            "tenant_name": r["name"],
            "room_number": r["room_number"],
        }
        choices = [{"index": 1, "label": "Yes"}, {"index": 2, "label": "No"}]
        await _save_pending(ctx.phone, "NOTICE_WITHDRAWN", action_data, choices, session, state="awaiting_choice")
        return (
            f"Withdraw notice for *{r['name']}* (Room {r['room_number']})?\n"
            f"Notice given: {notice_str} · Expected out: {exit_str}\n\n"
            f"1. Yes, withdraw  2. No, keep"
        )

    # Multiple matches — ask which one
    choices = _make_choices(rows)
    action_data = {"search_term": search_term}
    await _save_pending(ctx.phone, "NOTICE_WITHDRAWN", action_data, choices, session, state="awaiting_choice")
    return _format_choices_message(search_term, choices, "withdraw notice")
```

- [ ] **Step 4: Add NOTICE_WITHDRAWN confirmation resolver**

In `owner_handler.py`, find the section where pending action confirmations are resolved (search for `@register("NOTICE_GIVEN"` or look in `notice_void_overpay.py` — wherever NOTICE_GIVEN confirmation is handled). Add alongside it:

```python
@register("NOTICE_WITHDRAWN", ConversationState.AWAITING_CHOICE)
async def _resolve_notice_withdrawn(ctx: MessageContext, pending, session) -> str:
    action_data = pending.action_data if isinstance(pending.action_data, dict) else json.loads(pending.action_data)
    choice = int(ctx.text.strip())

    # If this was a multi-match disambiguation step, re-enter with specific tenant
    if "search_term" in action_data and "tenancy_id" not in action_data:
        rows = await fuzzy_search_tenants(action_data["search_term"], session, status_filter="active")
        rows = [r for r in rows if r.get("notice_date")]
        if not rows or choice < 1 or choice > len(rows):
            return "Invalid choice. Try again."
        r = rows[choice - 1]
        notice_str = r["notice_date"].strftime("%d %b %Y") if hasattr(r["notice_date"], "strftime") else str(r["notice_date"])
        exit_str = r["expected_checkout"].strftime("%d %b %Y") if r.get("expected_checkout") and hasattr(r["expected_checkout"], "strftime") else "—"
        new_data = {"tenancy_id": r["tenancy_id"], "tenant_name": r["name"], "room_number": r["room_number"]}
        new_choices = [{"index": 1, "label": "Yes"}, {"index": 2, "label": "No"}]
        await _save_pending(ctx.phone, "NOTICE_WITHDRAWN", new_data, new_choices, session, state="awaiting_choice")
        return (
            f"Withdraw notice for *{r['name']}* (Room {r['room_number']})?\n"
            f"Notice given: {notice_str} · Expected out: {exit_str}\n\n"
            f"1. Yes, withdraw  2. No, keep"
        )

    if choice == 2:
        return "OK, notice kept."

    if choice != 1:
        return "Reply 1 to confirm or 2 to cancel."

    tenancy_id = action_data["tenancy_id"]
    tenant_name = action_data["tenant_name"]
    room_number = action_data["room_number"]

    # Clear notice from DB
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenancy:
        return "Tenancy not found."
    tenancy.notice_date = None
    tenancy.expected_checkout = None
    session.add(tenancy)
    await session.commit()

    # Clear from Sheet
    from src.integrations.gsheets import record_notice
    await record_notice(room_number, tenant_name, "", "")

    return f"Notice withdrawn for *{tenant_name}* (Room {room_number}). They remain active."
```

- [ ] **Step 5: Register NOTICE_WITHDRAWN in the handler map**

In `owner_handler.py`, find the handler dispatch map (search for `"NOTICE_GIVEN": _notice_given` or similar). Add:

```python
"NOTICE_WITHDRAWN": _withdraw_notice,
```

- [ ] **Step 6: Test intent detection manually**

```bash
venv/Scripts/python -c "
from src.whatsapp.intent_detector import detect_intent
tests = [
    'withdraw notice for Raj Kumar',
    'cancel notice Priya',
    'changed mind about leaving room 205',
    'not leaving anymore',
]
for t in tests:
    r = detect_intent(t, role='admin')
    print(f'{t!r} -> {r.intent} ({r.confidence})')
"
```

Expected: all four → `NOTICE_WITHDRAWN` with confidence >= 0.93

- [ ] **Step 7: Commit**

```bash
git add src/whatsapp/intent_detector.py src/whatsapp/handlers/owner_handler.py
git commit -m "feat(bot): NOTICE_WITHDRAWN intent — withdraw notice via WhatsApp"
```

---

## Task 6: Frontend — API types

**Files:**
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add `notices_count` to KpiResponse**

```typescript
export interface KpiResponse {
  occupied_beds: number;
  total_beds: number;
  vacant_beds: number;
  occupancy_pct: number;
  active_tenants: number;
  no_show_count: number;
  notices_count: number;          // ← add
  checkins_today: number;
  checkouts_today: number;
  overdue_tenants: number;
  overdue_amount: number;
}
```

- [ ] **Step 2: Add `deposit_eligible` to KpiDetailItem**

```typescript
export interface KpiDetailItem {
  tenancy_id?: number;
  name: string;
  room: string;
  detail: string;
  rent?: number;
  free_beds?: number;
  gender?: string;
  stay_type?: string;
  dues?: number;
  building?: string;
  deposit_eligible?: boolean;     // ← add (notices tile only)
}
```

- [ ] **Step 3: Add `notice_date` + `expected_checkout` to TenantDues**

```typescript
export interface TenantDues {
  tenancy_id: number;
  tenant_id: number;
  name: string;
  phone: string;
  room_number: string;
  building_code: string;
  rent: number;
  dues: number;
  checkin_date: string | null;
  security_deposit: number;
  maintenance_fee: number;
  last_payment_date: string | null;
  last_payment_amount: number | null;
  period_month: string;
  notice_date: string | null;          // ← add
  expected_checkout: string | null;    // ← add
}
```

- [ ] **Step 4: Add `notice_date` + `expected_checkout` to PatchTenantBody**

```typescript
export interface PatchTenantBody {
  name?: string;
  phone?: string;
  email?: string;
  tenant_notes?: string;
  agreed_rent?: number;
  security_deposit?: number;
  expected_checkout?: string | null;
  tenancy_notes?: string;
  rent_change_reason?: string;
  notice_date?: string | null;         // ← add
}
```

- [ ] **Step 5: Add `expected_checkout` to CheckoutPrefetch**

```typescript
export interface CheckoutPrefetch {
  tenancy_id: number;
  tenant_id: number;
  name: string;
  phone: string;
  room_number: string;
  building_code: string;
  actual_date: string;
  agreed_checkin_date: string | null;
  stay_type: "monthly" | "daily";
  agreed_rent: number;
  security_deposit: number;
  booking_amount: number;
  prorated_rent: number;
  first_month_total: number;
  balance_due: number;
  overpayment: number;
  date_changed: boolean;
  daily_rate: number | null;
  num_days: number | null;
  checkout_date: string | null;
  total_stay_amount: number | null;
  notice_date: string | null;           // already exists
  expected_checkout: string | null;     // ← add
}
```

- [ ] **Step 6: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(types): notices_count, deposit_eligible, notice_date, expected_checkout in API types"
```

---

## Task 7: Frontend — KPI notices tile

**Files:**
- Modify: `web/components/home/kpi-grid.tsx`

- [ ] **Step 1: Add `"notices"` to TileKey**

```typescript
type TileKey = "occupied" | "vacant" | "checkins_today" | "checkouts_today" | "dues" | "no_show" | "notices" | null;
```

- [ ] **Step 2: Add notices to `filtered` logic**

In the `filtered` const, add after the `no_show` block:

```typescript
    if (open === "notices") {
      return (
        !nameSearch.trim() ||
        it.name.toLowerCase().includes(nameSearch.toLowerCase()) ||
        it.room.toLowerCase().includes(nameSearch.toLowerCase())
      );
    }
```

- [ ] **Step 3: Add notices tile to the grid**

After the `{data.no_show_count > 0 && (...)}` block, add:

```tsx
{data.notices_count > 0 && (
  <div className="col-span-2">
    <IconTile
      icon="📋" label={`On notice · ${data.notices_count}`}
      value={`${data.notices_count} leaving`}
      color="orange" active={open === "notices"}
      onClick={() => toggle("notices")}
    />
  </div>
)}
```

- [ ] **Step 4: Add filter bar for notices panel**

In the filter bars section, add before the vacant filter bar:

```tsx
{/* Filter bar — notices: name search */}
{open === "notices" && (
  <div className="px-3 pt-3 pb-2">
    <input
      type="text"
      placeholder="Name or room…"
      value={nameSearch}
      onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
      className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
    />
  </div>
)}
```

- [ ] **Step 5: Add deposit badge to row rendering**

In the `filtered.map(...)` section, the row currently shows `item.detail` on the right. Update it so notices rows show a deposit badge:

Replace the `<p className={...}>{item.detail}</p>` inside the map with:

```tsx
<div className="flex items-center gap-1.5">
  {open === "notices" && item.deposit_eligible !== undefined ? (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-pill ${
      item.deposit_eligible
        ? "bg-[#D1FAE5] text-[#065F46]"
        : "bg-[#FEE2E2] text-[#991B1B]"
    }`}>
      {item.deposit_eligible ? "Refundable" : "Forfeited"}
    </span>
  ) : null}
  <p className={`text-xs font-medium ${open === "dues" ? "text-status-due font-semibold" : "text-ink-muted"}`}>
    {item.detail}
  </p>
  {item.tenancy_id && (
    <span className="text-xs text-brand-pink font-bold">
      {selected?.tenancy_id === item.tenancy_id ? "▾" : "›"}
    </span>
  )}
</div>
```

- [ ] **Step 6: Add `"notices"` to `resetFilters`**

`resetFilters()` already resets `nameSearch` — no extra state to reset for notices. Confirm `"notices"` is covered by the existing reset (it uses `nameSearch` which is already reset). No change needed.

- [ ] **Step 7: Commit**

```bash
git add web/components/home/kpi-grid.tsx
git commit -m "feat(pwa): On Notice KPI tile with deposit eligibility badges"
```

---

## Task 8: Frontend — Tenant edit notice section

**Files:**
- Modify: `web/app/tenants/[tenancy_id]/edit/page.tsx`

- [ ] **Step 1: Add `noticeDate` state and load from TenantDues**

Add state variables after the existing `expectedCheckout` state:

```typescript
const [noticeDate, setNoticeDate] = useState("")
```

In `useEffect`, update the `.then((d) => {...})` block to set both fields:

```typescript
setExpectedCheckout(formatDate(d.expected_checkout))   // was formatDate(null) — fix this
setNoticeDate(formatDate(d.notice_date))
```

- [ ] **Step 2: Add deposit eligibility computed value**

After the state declarations, add:

```typescript
const depositEligible = noticeDate
  ? new Date(noticeDate).getDate() <= 5
  : null
```

- [ ] **Step 3: Add notice_date + expected_checkout to `buildChanges()`**

```typescript
function buildChanges(): PatchTenantBody {
  if (!original) return {}
  const changes: PatchTenantBody = {}
  if (name.trim() && name.trim() !== original.name) changes.name = name.trim()
  if (phone.trim() && phone.trim() !== original.phone) changes.phone = phone.trim()
  if (email.trim()) changes.email = email.trim()
  if (agreedRent && Number(agreedRent) !== original.rent) changes.agreed_rent = Number(agreedRent)
  if (securityDeposit && Number(securityDeposit) !== original.security_deposit)
    changes.security_deposit = Number(securityDeposit)
  // Notice fields — include if changed or being cleared
  const origNotice = formatDate(original.notice_date)
  const origCheckout = formatDate(original.expected_checkout)
  if (noticeDate !== origNotice) changes.notice_date = noticeDate || null
  if (expectedCheckout !== origCheckout) changes.expected_checkout = expectedCheckout || null
  if (notes.trim()) changes.tenancy_notes = notes.trim()
  return changes
}
```

- [ ] **Step 4: Add notice fields to `buildConfirmFields()`**

```typescript
if (changes.notice_date !== undefined)
  fields.push({ label: "Notice date", value: changes.notice_date ?? "Cleared" })
if (changes.expected_checkout !== undefined)
  fields.push({ label: "Expected checkout", value: changes.expected_checkout ?? "Cleared" })
```

- [ ] **Step 5: Add the Notice card to the form**

In the JSX, add this card after the "Stay Details" card (after the `</div>` that closes the stay details section):

```tsx
{/* Notice */}
<div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-4">
  <div className="flex justify-between items-center">
    <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Notice</p>
    {noticeDate && (
      <span className={`text-[10px] font-bold px-2.5 py-1 rounded-pill ${
        depositEligible
          ? "bg-[#D1FAE5] text-[#065F46]"
          : "bg-[#FEE2E2] text-[#991B1B]"
      }`}>
        {depositEligible ? "Deposit Refundable" : "Deposit Forfeited"}
      </span>
    )}
  </div>

  <div>
    <label className="block text-xs font-medium text-ink-muted mb-1">Notice date</label>
    <input
      type="date"
      value={noticeDate}
      onChange={(e) => setNoticeDate(e.target.value)}
      className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
    />
    {noticeDate && (
      <p className="text-[10px] text-ink-muted mt-1 px-1">
        {depositEligible
          ? "Given on day ≤ 5 — deposit refundable, exits end of this month"
          : "Given after day 5 — deposit forfeited, exits end of next month"}
      </p>
    )}
  </div>

  <div>
    <label className="block text-xs font-medium text-ink-muted mb-1">Expected checkout</label>
    <input
      type="date"
      value={expectedCheckout}
      onChange={(e) => setExpectedCheckout(e.target.value)}
      className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
    />
  </div>

  {noticeDate && (
    <button
      type="button"
      onClick={() => { setNoticeDate(""); setExpectedCheckout("") }}
      className="rounded-pill border border-[#E2DEDD] py-2.5 text-sm font-semibold text-status-warn w-full"
    >
      Withdraw notice
    </button>
  )}
</div>
```

- [ ] **Step 6: Remove duplicate `expectedCheckout` from Stay Details card**

In the "Stay Details" card, remove the existing `Expected Checkout` field (it's now in the Notice card). Find and delete:

```tsx
<div>
  <label className="block text-xs font-medium text-ink-muted mb-1">Expected Checkout</label>
  <input
    type="date"
    value={expectedCheckout}
    onChange={(e) => setExpectedCheckout(e.target.value)}
    className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
  />
</div>
```

- [ ] **Step 7: Commit**

```bash
git add web/app/tenants/[tenancy_id]/edit/page.tsx
git commit -m "feat(pwa): notice section in tenant edit — notice date, deposit flag, withdraw"
```

---

## Task 9: Frontend — Checkout notice banner + auto-fill

**Files:**
- Modify: `web/app/checkout/new/page.tsx`

- [ ] **Step 1: Auto-fill checkoutDate from expected_checkout**

In the `useCallback` or `useEffect` that loads the prefetch (find where `setPrefetch(data)` is called), add after it:

```typescript
if (data.expected_checkout) {
  setCheckoutDate(data.expected_checkout)
}
```

- [ ] **Step 2: Compute notice banner data**

After the prefetch state declarations, add:

```typescript
const noticeDay = prefetch?.notice_date
  ? new Date(prefetch.notice_date).getDate()
  : null
const depositRefundable = noticeDay !== null ? noticeDay <= 5 : null
const netRefund = prefetch
  ? Math.max(0, prefetch.security_deposit - prefetch.pending_dues)
  : 0
```

- [ ] **Step 3: Add notice banner JSX**

In the form JSX, add the notice banner immediately after the tenant search result is confirmed and before the checklist section. Find where the checklist starts (look for `{/* Checklist */}` or the `CheckBox` components). Insert before it:

```tsx
{/* Notice banner — only shown if tenant is on notice */}
{prefetch?.notice_date && (
  <div className={`rounded-card p-4 border-2 flex flex-col gap-1.5 ${
    depositRefundable
      ? "border-[#6EE7B7] bg-[#F0FDF4]"
      : "border-[#FCA5A5] bg-[#FFF5F5]"
  }`}>
    <p className="text-xs font-bold text-ink">
      📋 Notice on file — {fmtDate(prefetch.notice_date)}
    </p>
    {depositRefundable ? (
      <p className="text-xs text-[#065F46] font-semibold">
        Deposit refundable — {fmtINR(netRefund)} to return
      </p>
    ) : (
      <p className="text-xs text-[#991B1B] font-semibold">
        Deposit forfeited (notice given after day 5)
      </p>
    )}
  </div>
)}
```

- [ ] **Step 4: Commit**

```bash
git add web/app/checkout/new/page.tsx
git commit -m "feat(pwa): checkout notice banner + auto-fill checkout date from expected_checkout"
```

---

## Task 10: Build + Deploy

- [ ] **Step 1: Run unit tests locally**

```bash
venv/Scripts/python -m pytest tests/ -x -q 2>/dev/null | tail -5
```

Expected: all pass.

- [ ] **Step 2: Copy backend files to VPS**

```bash
scp src/schemas/kpi.py src/api/v2/kpi.py src/api/v2/tenants.py src/api/v2/checkout.py src/integrations/gsheets.py src/whatsapp/intent_detector.py src/whatsapp/handlers/owner_handler.py root@187.127.130.194:/opt/pg-accountant/src/schemas/
scp src/api/v2/kpi.py src/api/v2/tenants.py src/api/v2/checkout.py root@187.127.130.194:/opt/pg-accountant/src/api/v2/
scp src/integrations/gsheets.py root@187.127.130.194:/opt/pg-accountant/src/integrations/
scp src/whatsapp/intent_detector.py src/whatsapp/handlers/owner_handler.py root@187.127.130.194:/opt/pg-accountant/src/whatsapp/handlers/
```

Use exact paths — run from project root:

```bash
scp "src/schemas/kpi.py" root@187.127.130.194:/opt/pg-accountant/src/schemas/kpi.py
scp "src/api/v2/kpi.py" root@187.127.130.194:/opt/pg-accountant/src/api/v2/kpi.py
scp "src/api/v2/tenants.py" root@187.127.130.194:/opt/pg-accountant/src/api/v2/tenants.py
scp "src/api/v2/checkout.py" root@187.127.130.194:/opt/pg-accountant/src/api/v2/checkout.py
scp "src/integrations/gsheets.py" root@187.127.130.194:/opt/pg-accountant/src/integrations/gsheets.py
scp "src/whatsapp/intent_detector.py" root@187.127.130.194:/opt/pg-accountant/src/whatsapp/intent_detector.py
scp "src/whatsapp/handlers/owner_handler.py" root@187.127.130.194:/opt/pg-accountant/src/whatsapp/handlers/owner_handler.py
```

- [ ] **Step 3: Restart backend**

```bash
ssh root@187.127.130.194 "systemctl restart pg-accountant && sleep 2 && systemctl is-active pg-accountant"
```

Expected: `active`

- [ ] **Step 4: Copy frontend files + rebuild PWA**

```bash
scp "web/lib/api.ts" root@187.127.130.194:/opt/pg-accountant/web/lib/api.ts
scp "web/components/home/kpi-grid.tsx" root@187.127.130.194:/opt/pg-accountant/web/components/home/kpi-grid.tsx
scp "web/app/tenants/[tenancy_id]/edit/page.tsx" "root@187.127.130.194:/opt/pg-accountant/web/app/tenants/[tenancy_id]/edit/page.tsx"
scp "web/app/checkout/new/page.tsx" root@187.127.130.194:/opt/pg-accountant/web/app/checkout/new/page.tsx
ssh root@187.127.130.194 "cd /opt/pg-accountant/web && npm run build && systemctl restart kozzy-pwa"
```

- [ ] **Step 5: Smoke test**

1. Open `app.getkozzy.com` — confirm "On notice · X" tile appears on dashboard
2. Click tile — confirm list with Refundable/Forfeited badges
3. Open a tenant edit for a tenant on notice — confirm notice section shows pre-filled with badge
4. Open checkout → search for a noticed tenant — confirm banner appears and date auto-fills
5. Send "withdraw notice [name]" on WhatsApp — confirm bot asks for confirmation
6. Reply "1" — confirm notice cleared, check tenant edit shows blank notice section

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: notice management — dashboard tile, tenant edit, checkout banner, bot withdrawal"
```
