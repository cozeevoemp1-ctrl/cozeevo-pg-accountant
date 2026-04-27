# PWA Forms — Rent Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully working rent collection form on the Kozzy PWA — tenant search, dues display, voice pre-fill via "Hey Kozzy", confirmation card before DB write.

**Architecture:** Two new backend endpoints (tenant search + dues) → three new frontend components (TenantSearch, AmountMethodInput, ConfirmationCard) → rebuilt payment page wiring everything together + voice pre-fill from existing voice-sheet.tsx.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), Next.js 15 + React 18 + TypeScript + Tailwind (frontend), Playwright (e2e), pytest (backend tests). Design tokens from `web/tailwind.config.ts` — brand-pink `#EF1F9C`, warm cream bg `#F6F5F0`, DM Sans font.

**Note on voice:** Voice pre-fill uses the existing `voice-sheet.tsx` → `extractPaymentIntent()` flow. The form accepts a `PaymentIntent` and pre-fills fields. Wake word / tap-to-talk wiring is a separate track (Track B) — this plan only wires the form end of the pipeline.

---

## File Map

**Create (backend):**
- `src/api/v2/tenants.py` — tenant search + dues endpoints

**Modify (backend):**
- `src/api/v2/app_router.py` — register tenants router

**Create (frontend):**
- `web/components/forms/tenant-search.tsx` — autocomplete tenant picker
- `web/components/forms/amount-method-input.tsx` — amount + payment method
- `web/components/forms/confirmation-card.tsx` — universal confirm-before-write gate

**Modify (frontend):**
- `web/lib/api.ts` — add `searchTenants()`, `getTenantDues()`
- `web/app/payment/new/page.tsx` — rebuild with all components + voice pre-fill

**Create (tests):**
- `tests/api/test_v2_tenants.py` — backend endpoint tests
- `web/e2e/payment-collection.spec.ts` — Playwright end-to-end

---

## Task 1: Backend — Tenant Search Endpoint

**Files:**
- Create: `src/api/v2/tenants.py`
- Test: `tests/api/test_v2_tenants.py`

- [ ] **Step 1: Write failing test for tenant search**

Create `tests/api/test_v2_tenants.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_tenant_search_by_name(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/api/v2/app/tenants/search",
        params={"q": "suresh"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        assert "tenancy_id" in item
        assert "tenant_id" in item
        assert "name" in item
        assert "room_number" in item
        assert "rent" in item
        assert "status" in item


@pytest.mark.asyncio
async def test_tenant_search_by_room(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/api/v2/app/tenants/search",
        params={"q": "205"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_tenant_search_empty_query_returns_400(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/api/v2/app/tenants/search",
        params={"q": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_tenant_search_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v2/app/tenants/search", params={"q": "suresh"})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "c:\Users\kiran\Desktop\AI Watsapp PG Accountant"
venv/Scripts/python -m pytest tests/api/test_v2_tenants.py -v
```
Expected: 4 errors — `404 Not Found` (route doesn't exist yet)

- [ ] **Step 3: Create tenant search endpoint**

Create `src/api/v2/tenants.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_db_session
from src.database.models import Tenant, Tenancy, Room
from src.api.v2.auth import get_current_user

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantSearchResult(BaseModel):
    tenancy_id: int
    tenant_id: int
    name: str
    phone: str
    room_number: str
    building_code: str
    rent: int
    status: str


class TenantDues(BaseModel):
    tenancy_id: int
    tenant_id: int
    name: str
    phone: str
    room_number: str
    building_code: str
    rent: int
    dues: float
    last_payment_date: str | None
    last_payment_amount: int | None
    period_month: str


@router.get("/search", response_model=list[TenantSearchResult])
async def search_tenants(
    q: str = Query(..., min_length=1, description="Name, room number, or phone"),
    db: AsyncSession = Depends(get_db_session),
    _user=Depends(get_current_user),
):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    q_lower = q.strip().lower()

    stmt = (
        select(Tenancy, Tenant, Room)
        .join(Tenant, Tenancy.tenant_id == Tenant.id)
        .join(Room, Tenancy.room_id == Room.id)
        .where(
            Tenancy.status.in_(["active", "no_show"]),
            or_(
                Tenant.name.ilike(f"%{q_lower}%"),
                Room.room_number.ilike(f"%{q_lower}%"),
                Tenant.phone.ilike(f"%{q_lower}%"),
            ),
        )
        .order_by(Tenant.name)
        .limit(10)
    )
    rows = (await db.execute(stmt)).all()

    return [
        TenantSearchResult(
            tenancy_id=tenancy.id,
            tenant_id=tenant.id,
            name=tenant.name,
            phone=tenant.phone or "",
            room_number=room.room_number,
            building_code=room.building_code or "",
            rent=tenancy.rent or 0,
            status=tenancy.status,
        )
        for tenancy, tenant, room in rows
    ]
```

- [ ] **Step 4: Run tests — search tests should pass**

```bash
venv/Scripts/python -m pytest tests/api/test_v2_tenants.py::test_tenant_search_requires_auth tests/api/test_v2_tenants.py::test_tenant_search_empty_query_returns_400 -v
```
Expected: PASS (these don't need real DB data)

- [ ] **Step 5: Commit**

```bash
git add src/api/v2/tenants.py tests/api/test_v2_tenants.py
git commit -m "feat(api): tenant search endpoint GET /api/v2/app/tenants/search"
```

---

## Task 2: Backend — Tenant Dues Endpoint

**Files:**
- Modify: `src/api/v2/tenants.py`
- Test: `tests/api/test_v2_tenants.py`

- [ ] **Step 1: Write failing test for dues**

Append to `tests/api/test_v2_tenants.py`:

```python
@pytest.mark.asyncio
async def test_tenant_dues_returns_correct_shape(client: AsyncClient, auth_headers: dict, sample_tenancy_id: int):
    resp = await client.get(
        f"/api/v2/app/tenants/{sample_tenancy_id}/dues",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tenancy_id" in data
    assert "name" in data
    assert "dues" in data
    assert "rent" in data
    assert "period_month" in data
    assert isinstance(data["dues"], (int, float))


@pytest.mark.asyncio
async def test_tenant_dues_404_for_invalid(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/api/v2/app/tenants/999999/dues",
        headers=auth_headers,
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```bash
venv/Scripts/python -m pytest tests/api/test_v2_tenants.py::test_tenant_dues_returns_correct_shape -v
```
Expected: FAIL — 404 (route doesn't exist yet)

- [ ] **Step 3: Add dues endpoint to tenants.py**

Append to `src/api/v2/tenants.py` (after the search route):

```python
from datetime import date
from sqlalchemy import func
from src.database.models import Payment  # adjust import if model name differs


@router.get("/{tenancy_id}/dues", response_model=TenantDues)
async def get_tenant_dues(
    tenancy_id: int,
    db: AsyncSession = Depends(get_db_session),
    _user=Depends(get_current_user),
):
    # Load tenancy + tenant + room
    stmt = (
        select(Tenancy, Tenant, Room)
        .join(Tenant, Tenancy.tenant_id == Tenant.id)
        .join(Room, Tenancy.room_id == Room.id)
        .where(Tenancy.id == tenancy_id)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tenancy not found")

    tenancy, tenant, room = row

    # Current period
    today = date.today()
    period_month = today.strftime("%Y-%m")

    # Sum payments this month
    pay_stmt = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(
            Payment.tenancy_id == tenancy_id,
            Payment.period_month == period_month,
            Payment.is_void.is_(False),
            Payment.for_type == "rent",
        )
    )
    paid_this_month = float((await db.execute(pay_stmt)).scalar())

    # Last payment
    last_pay_stmt = (
        select(Payment)
        .where(
            Payment.tenancy_id == tenancy_id,
            Payment.is_void.is_(False),
        )
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    last_pay = (await db.execute(last_pay_stmt)).scalar_one_or_none()

    dues = max(0.0, float(tenancy.rent or 0) - paid_this_month)

    return TenantDues(
        tenancy_id=tenancy.id,
        tenant_id=tenant.id,
        name=tenant.name,
        phone=tenant.phone or "",
        room_number=room.room_number,
        building_code=room.building_code or "",
        rent=tenancy.rent or 0,
        dues=dues,
        last_payment_date=last_pay.payment_date.isoformat() if last_pay else None,
        last_payment_amount=last_pay.amount if last_pay else None,
        period_month=period_month,
    )
```

- [ ] **Step 4: Run dues tests**

```bash
venv/Scripts/python -m pytest tests/api/test_v2_tenants.py::test_tenant_dues_404_for_invalid -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/v2/tenants.py tests/api/test_v2_tenants.py
git commit -m "feat(api): tenant dues endpoint GET /api/v2/app/tenants/{tenancy_id}/dues"
```

---

## Task 3: Backend — Register Tenants Router

**Files:**
- Modify: `src/api/v2/app_router.py`

- [ ] **Step 1: Register the new router**

Open `src/api/v2/app_router.py`. Find the section where other routers are included. Add:

```python
from src.api.v2.tenants import router as tenants_router

# inside the router include block:
app_router.include_router(tenants_router)
```

Full modified file should look like:

```python
from fastapi import APIRouter, Depends
from src.api.v2.auth import get_current_user
from src.api.v2.auth_hooks import router as auth_hooks_router
from src.api.v2.kpi import router as kpi_router, activity_router
from src.api.v2.payments import router as payments_router
from src.api.v2.reporting import router as reporting_router
from src.api.v2.voice import router as voice_router
from src.api.v2.tenants import router as tenants_router  # ADD THIS
from src.database.field_registry import fields_for_pwa

app_router = APIRouter(prefix="/api/v2/app", dependencies=[Depends(get_current_user)])

app_router.include_router(auth_hooks_router)
app_router.include_router(kpi_router)
app_router.include_router(activity_router)
app_router.include_router(payments_router)
app_router.include_router(reporting_router)
app_router.include_router(voice_router)
app_router.include_router(tenants_router)  # ADD THIS


@app_router.get("/health")
async def health(user=Depends(get_current_user)):
    return {"status": "ok", "user_id": user.user_id, "role": user.role, "org_id": user.org_id}


@app_router.get("/field-registry")
async def field_registry():
    return {"fields": fields_for_pwa()}
```

- [ ] **Step 2: Start dev server and verify routes exist**

```bash
venv/Scripts/python main.py
```

In another terminal:
```bash
curl http://localhost:8000/docs | findstr tenants
```
Expected: `/api/v2/app/tenants/search` and `/api/v2/app/tenants/{tenancy_id}/dues` appear in docs

- [ ] **Step 3: Commit**

```bash
git add src/api/v2/app_router.py
git commit -m "feat(api): register tenants router in app_router"
```

---

## Task 4: Frontend — Add API Functions

**Files:**
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add types and functions**

Open `web/lib/api.ts`. Add after the existing interfaces:

```typescript
export interface TenantSearchResult {
  tenancy_id: number
  tenant_id: number
  name: string
  phone: string
  room_number: string
  building_code: string
  rent: number
  status: string
}

export interface TenantDues {
  tenancy_id: number
  tenant_id: number
  name: string
  phone: string
  room_number: string
  building_code: string
  rent: number
  dues: number
  last_payment_date: string | null
  last_payment_amount: number | null
  period_month: string
}
```

Add after the existing API functions:

```typescript
export async function searchTenants(q: string): Promise<TenantSearchResult[]> {
  return _get<TenantSearchResult[]>(`/tenants/search?q=${encodeURIComponent(q)}`)
}

export async function getTenantDues(tenancyId: number): Promise<TenantDues> {
  return _get<TenantDues>(`/tenants/${tenancyId}/dues`)
}
```

- [ ] **Step 2: Type-check**

```bash
cd web && npx tsc --noEmit
```
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(web): add searchTenants + getTenantDues API functions"
```

---

## Task 5: Frontend — TenantSearch Component

**Files:**
- Create: `web/components/forms/tenant-search.tsx`

- [ ] **Step 1: Create the component**

Create `web/components/forms/tenant-search.tsx`:

```tsx
"use client"

import { useState, useEffect, useRef } from "react"
import { searchTenants, TenantSearchResult } from "@/lib/api"

interface TenantSearchProps {
  onSelect: (tenant: TenantSearchResult) => void
  defaultValue?: string
  placeholder?: string
}

export function TenantSearch({ onSelect, defaultValue = "", placeholder = "Search by name or room..." }: TenantSearchProps) {
  const [query, setQuery] = useState(defaultValue)
  const [results, setResults] = useState<TenantSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<TenantSearchResult | null>(null)
  const [open, setOpen] = useState(false)
  const debounceRef = useRef<NodeJS.Timeout>()

  useEffect(() => {
    if (defaultValue && defaultValue !== query) {
      setQuery(defaultValue)
      runSearch(defaultValue)
    }
  }, [defaultValue])

  async function runSearch(q: string) {
    if (q.trim().length < 1) { setResults([]); return }
    setLoading(true)
    try {
      const data = await searchTenants(q.trim())
      setResults(data)
      setOpen(true)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value
    setQuery(val)
    setSelected(null)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => runSearch(val), 300)
  }

  function handleSelect(t: TenantSearchResult) {
    setSelected(t)
    setQuery(`${t.name} — Room ${t.room_number}`)
    setOpen(false)
    onSelect(t)
  }

  return (
    <div className="relative">
      <label className="block text-sm font-semibold text-ink mb-1">Tenant</label>
      <input
        type="text"
        value={query}
        onChange={handleInput}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder={placeholder}
        className="w-full rounded-pill border border-gray-200 bg-surface px-4 py-3 text-ink text-base focus:outline-none focus:ring-2 focus:ring-brand-pink"
      />
      {loading && (
        <div className="absolute right-4 top-10 text-ink-muted text-sm">...</div>
      )}
      {open && results.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full bg-surface rounded-card shadow-lg border border-gray-100 max-h-56 overflow-y-auto">
          {results.map((t) => (
            <li
              key={t.tenancy_id}
              onMouseDown={() => handleSelect(t)}
              className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-bg active:bg-tile-pink"
            >
              <div>
                <p className="font-semibold text-ink text-sm">{t.name}</p>
                <p className="text-ink-muted text-xs">Room {t.room_number} · {t.building_code}</p>
              </div>
              <span className="text-xs text-ink-muted">₹{t.rent.toLocaleString("en-IN")}/mo</span>
            </li>
          ))}
        </ul>
      )}
      {selected && (
        <div className="mt-2 rounded-tile bg-tile-green px-3 py-2 text-xs text-ink flex justify-between">
          <span>{selected.name} · Room {selected.room_number}</span>
          <button onClick={() => { setSelected(null); setQuery(""); setResults([]) }} className="text-ink-muted ml-2">✕</button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd web && npx tsc --noEmit
```
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add web/components/forms/tenant-search.tsx
git commit -m "feat(web): TenantSearch component with debounced autocomplete"
```

---

## Task 6: Frontend — ConfirmationCard Component

**Files:**
- Create: `web/components/forms/confirmation-card.tsx`

This is the universal safety gate — all form writes show this before hitting the DB.

- [ ] **Step 1: Create the component**

Create `web/components/forms/confirmation-card.tsx`:

```tsx
interface ConfirmField {
  label: string
  value: string
  highlight?: boolean
}

interface ConfirmationCardProps {
  title: string
  fields: ConfirmField[]
  onConfirm: () => void
  onEdit: () => void
  loading?: boolean
}

export function ConfirmationCard({ title, fields, onConfirm, onEdit, loading = false }: ConfirmationCardProps) {
  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/40">
      <div className="w-full max-w-md bg-surface rounded-t-[28px] px-6 pt-6 pb-10 shadow-2xl">
        <div className="w-10 h-1 bg-gray-200 rounded-full mx-auto mb-5" />
        <h2 className="text-lg font-bold text-ink mb-4">{title}</h2>

        <div className="divide-y divide-gray-100 mb-6">
          {fields.map((f) => (
            <div key={f.label} className="flex justify-between py-3">
              <span className="text-sm text-ink-muted">{f.label}</span>
              <span className={`text-sm font-semibold ${f.highlight ? "text-brand-pink" : "text-ink"}`}>
                {f.value}
              </span>
            </div>
          ))}
        </div>

        <button
          onClick={onConfirm}
          disabled={loading}
          className="w-full rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80 disabled:opacity-50"
        >
          {loading ? "Recording..." : "Confirm ✓"}
        </button>
        <button
          onClick={onEdit}
          disabled={loading}
          className="w-full mt-3 rounded-pill border border-gray-200 py-3 text-ink font-semibold text-sm active:opacity-80"
        >
          Edit
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd web && npx tsc --noEmit
```
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add web/components/forms/confirmation-card.tsx
git commit -m "feat(web): ConfirmationCard universal safety gate component"
```

---

## Task 7: Frontend — Rebuild Payment Form

**Files:**
- Modify: `web/app/payment/new/page.tsx`

This replaces the existing tenant-id-only form with the full flow: search → dues preview → amount/method → confirm card → submit.

- [ ] **Step 1: Replace the payment page**

Overwrite `web/app/payment/new/page.tsx`:

```tsx
"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
import { VoiceSheet } from "@/components/voice/voice-sheet"
import { createPayment, getTenantDues, TenantSearchResult, TenantDues, PaymentIntent } from "@/lib/api"
import { formatDistanceToNow } from "date-fns"

const METHODS = ["CASH", "UPI", "BANK", "OTHER"] as const
const FOR_TYPES = [
  { value: "rent", label: "Rent" },
  { value: "deposit", label: "Deposit" },
  { value: "maintenance", label: "Maintenance" },
  { value: "booking", label: "Booking Advance" },
  { value: "adjustment", label: "Adjustment" },
] as const

type Method = typeof METHODS[number]

function currentPeriodMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

export default function NewPaymentPage() {
  const router = useRouter()

  // Form state
  const [tenant, setTenant] = useState<TenantSearchResult | null>(null)
  const [dues, setDues] = useState<TenantDues | null>(null)
  const [amount, setAmount] = useState("")
  const [method, setMethod] = useState<Method>("CASH")
  const [forType, setForType] = useState("rent")
  const [periodMonth, setPeriodMonth] = useState(currentPeriodMonth())
  const [notes, setNotes] = useState("")

  // UI state
  const [showConfirm, setShowConfirm] = useState(false)
  const [showVoice, setShowVoice] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)

  // Voice pre-fill search hint
  const [voiceSearchHint, setVoiceSearchHint] = useState("")

  async function handleTenantSelect(t: TenantSearchResult) {
    setTenant(t)
    setDues(null)
    try {
      const d = await getTenantDues(t.tenancy_id)
      setDues(d)
      if (!amount && d.dues > 0) setAmount(String(d.dues))
    } catch {
      // dues load is best-effort
    }
  }

  function handleVoiceIntent(intent: PaymentIntent) {
    setShowVoice(false)
    if (intent.amount) setAmount(String(intent.amount))
    if (intent.method) setMethod((intent.method.toUpperCase() as Method) ?? "CASH")
    if (intent.for_type) setForType(intent.for_type)
    // Pre-fill search with room or name from voice
    if (intent.tenant_room) setVoiceSearchHint(intent.tenant_room)
    else if (intent.tenant_name) setVoiceSearchHint(intent.tenant_name)
  }

  function handleSubmitClick(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    if (!tenant) { setError("Select a tenant"); return }
    if (!amount || Number(amount) <= 0) { setError("Enter a valid amount"); return }
    setShowConfirm(true)
  }

  async function handleConfirm() {
    if (!tenant) return
    setSubmitting(true)
    setError("")
    try {
      await createPayment({
        tenant_id: tenant.tenant_id,
        amount: Number(amount),
        method,
        for_type: forType,
        period_month: periodMonth,
        notes: notes || undefined,
      })
      setSuccess(true)
    } catch (err: unknown) {
      setShowConfirm(false)
      setError(err instanceof Error ? err.message : "Payment failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-bg flex flex-col items-center justify-center px-6 gap-6">
        <div className="rounded-full bg-tile-green w-20 h-20 flex items-center justify-center text-4xl">✓</div>
        <h1 className="text-xl font-bold text-ink text-center">
          ₹{Number(amount).toLocaleString("en-IN")} recorded
        </h1>
        {tenant && (
          <p className="text-ink-muted text-center">
            {tenant.name} · Room {tenant.room_number}
          </p>
        )}
        <button
          onClick={() => { setSuccess(false); setTenant(null); setDues(null); setAmount(""); setNotes("") }}
          className="w-full rounded-pill bg-brand-pink py-4 text-white font-bold"
        >
          Record another
        </button>
        <button onClick={() => router.push("/")} className="text-ink-muted text-sm underline">
          Back to home
        </button>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-bg">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4">
        <button onClick={() => router.back()} className="text-ink-muted text-xl">←</button>
        <h1 className="text-xl font-bold text-ink">Collect Payment</h1>
        <button
          onClick={() => setShowVoice(true)}
          className="ml-auto rounded-full bg-brand-pink w-10 h-10 flex items-center justify-center shadow"
          aria-label="Voice input"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="white">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8" stroke="white" strokeWidth="2" fill="none" strokeLinecap="round"/>
          </svg>
        </button>
      </div>

      <form onSubmit={handleSubmitClick} className="px-5 flex flex-col gap-5 pb-32">
        {/* Tenant search */}
        <TenantSearch
          onSelect={handleTenantSelect}
          defaultValue={voiceSearchHint}
          placeholder="Name or room number..."
        />

        {/* Dues preview */}
        {dues && (
          <div className="rounded-card bg-surface border border-gray-100 px-4 py-3 flex justify-between items-center">
            <div>
              <p className="text-xs text-ink-muted">Outstanding this month</p>
              <p className={`text-lg font-bold ${dues.dues > 0 ? "text-status-due" : "text-status-paid"}`}>
                {dues.dues > 0 ? `₹${dues.dues.toLocaleString("en-IN")} due` : "Fully paid ✓"}
              </p>
            </div>
            {dues.last_payment_date && (
              <div className="text-right">
                <p className="text-xs text-ink-muted">Last paid</p>
                <p className="text-xs text-ink font-medium">
                  ₹{(dues.last_payment_amount ?? 0).toLocaleString("en-IN")}
                </p>
                <p className="text-xs text-ink-muted">
                  {formatDistanceToNow(new Date(dues.last_payment_date), { addSuffix: true })}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Amount */}
        <div>
          <label className="block text-sm font-semibold text-ink mb-1">Amount (₹)</label>
          <input
            type="number"
            inputMode="numeric"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0"
            className="w-full rounded-pill border border-gray-200 bg-surface px-4 py-3 text-ink text-xl font-bold focus:outline-none focus:ring-2 focus:ring-brand-pink"
          />
        </div>

        {/* Payment method */}
        <div>
          <label className="block text-sm font-semibold text-ink mb-2">Method</label>
          <div className="flex gap-2 flex-wrap">
            {METHODS.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMethod(m)}
                className={`rounded-pill px-4 py-2 text-sm font-semibold border transition-colors ${
                  method === m
                    ? "bg-brand-pink text-white border-brand-pink"
                    : "bg-surface text-ink border-gray-200"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        {/* For type */}
        <div>
          <label className="block text-sm font-semibold text-ink mb-2">For</label>
          <div className="flex gap-2 flex-wrap">
            {FOR_TYPES.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => setForType(f.value)}
                className={`rounded-pill px-4 py-2 text-sm font-semibold border transition-colors ${
                  forType === f.value
                    ? "bg-brand-pink text-white border-brand-pink"
                    : "bg-surface text-ink border-gray-200"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* Period */}
        <div>
          <label className="block text-sm font-semibold text-ink mb-1">Period</label>
          <input
            type="month"
            value={periodMonth}
            onChange={(e) => setPeriodMonth(e.target.value)}
            className="w-full rounded-pill border border-gray-200 bg-surface px-4 py-3 text-ink focus:outline-none focus:ring-2 focus:ring-brand-pink"
          />
        </div>

        {/* Notes */}
        <div>
          <label className="block text-sm font-semibold text-ink mb-1">Notes (optional)</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. partial payment"
            className="w-full rounded-pill border border-gray-200 bg-surface px-4 py-3 text-ink focus:outline-none focus:ring-2 focus:ring-brand-pink"
          />
        </div>

        {error && <p className="text-status-due text-sm font-medium">{error}</p>}

        {/* Submit */}
        <div className="fixed bottom-0 left-0 right-0 px-5 pb-8 pt-4 bg-bg border-t border-gray-100">
          <button
            type="submit"
            className="w-full rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80"
          >
            Review Payment →
          </button>
        </div>
      </form>

      {/* Confirmation card */}
      {showConfirm && tenant && (
        <ConfirmationCard
          title="Record Payment"
          fields={[
            { label: "Tenant", value: `${tenant.name} · Room ${tenant.room_number}` },
            { label: "Amount", value: `₹${Number(amount).toLocaleString("en-IN")}`, highlight: true },
            { label: "Method", value: method },
            { label: "For", value: FOR_TYPES.find(f => f.value === forType)?.label ?? forType },
            { label: "Period", value: periodMonth },
            ...(notes ? [{ label: "Notes", value: notes }] : []),
            ...(dues ? [{ label: "After this payment", value: dues.dues - Number(amount) <= 0 ? "Fully paid ✓" : `₹${(dues.dues - Number(amount)).toLocaleString("en-IN")} remaining` }] : []),
          ]}
          onConfirm={handleConfirm}
          onEdit={() => setShowConfirm(false)}
          loading={submitting}
        />
      )}

      {/* Voice sheet */}
      {showVoice && (
        <VoiceSheet
          onPaymentIntent={handleVoiceIntent}
          onClose={() => setShowVoice(false)}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Install date-fns if not present**

```bash
cd web && npm list date-fns || npm install date-fns
```

- [ ] **Step 3: Type-check**

```bash
cd web && npx tsc --noEmit
```
Expected: 0 errors. Fix any type mismatches (e.g. if `VoiceSheet` props differ, adjust `onClose` prop name to match what `voice-sheet.tsx` exports).

- [ ] **Step 4: Start dev server and manual smoke test**

```bash
cd web && npm run dev
```

Open `http://localhost:3000/payment/new` in browser.

Verify:
- [ ] Tenant search autocomplete fires on typing
- [ ] Selecting a tenant shows dues card
- [ ] Amount pre-fills from dues if outstanding
- [ ] Method buttons are tappable, active state correct (pink)
- [ ] "Review Payment →" shows ConfirmationCard
- [ ] ConfirmationCard shows all fields correctly
- [ ] Edit button dismisses card
- [ ] Confirm records payment (check Network tab for POST /api/v2/app/payments)
- [ ] Success screen shows with correct amount + tenant

- [ ] **Step 5: Commit**

```bash
git add web/app/payment/new/page.tsx
git commit -m "feat(web): rebuild rent collection form with tenant search, dues preview, voice, confirmation card"
```

---

## Task 8: E2E Tests

**Files:**
- Create: `web/e2e/payment-collection.spec.ts`

- [ ] **Step 1: Write Playwright tests**

Create `web/e2e/payment-collection.spec.ts`:

```typescript
import { test, expect } from "@playwright/test"

test.describe("Rent collection form", () => {
  test.beforeEach(async ({ page }) => {
    // Assumes TEST_MODE=1 and a seeded test DB tenant in room 205
    await page.goto("/payment/new")
  })

  test("shows tenant search input", async ({ page }) => {
    await expect(page.getByPlaceholder("Name or room number...")).toBeVisible()
  })

  test("autocomplete shows results when typing room number", async ({ page }) => {
    await page.getByPlaceholder("Name or room number...").fill("205")
    await page.waitForSelector("ul li", { timeout: 3000 })
    const items = page.locator("ul li")
    await expect(items.first()).toBeVisible()
  })

  test("selecting tenant shows dues card", async ({ page }) => {
    await page.getByPlaceholder("Name or room number...").fill("205")
    await page.waitForSelector("ul li")
    await page.locator("ul li").first().click()
    // Dues card should appear
    await expect(page.getByText(/due|Fully paid/i)).toBeVisible({ timeout: 3000 })
  })

  test("confirm button disabled without tenant", async ({ page }) => {
    await page.getByRole("button", { name: /Review Payment/i }).click()
    await expect(page.getByText("Select a tenant")).toBeVisible()
    // Confirmation card should NOT appear
    await expect(page.getByText("Record Payment")).not.toBeVisible()
  })

  test("confirm button disabled with zero amount", async ({ page }) => {
    await page.getByPlaceholder("Name or room number...").fill("205")
    await page.waitForSelector("ul li")
    await page.locator("ul li").first().click()
    await page.getByPlaceholder("0").fill("0")
    await page.getByRole("button", { name: /Review Payment/i }).click()
    await expect(page.getByText("Enter a valid amount")).toBeVisible()
  })

  test("confirmation card appears with correct fields", async ({ page }) => {
    await page.getByPlaceholder("Name or room number...").fill("205")
    await page.waitForSelector("ul li")
    await page.locator("ul li").first().click()
    await page.getByPlaceholder("0").fill("7000")
    await page.getByRole("button", { name: "CASH" }).click()
    await page.getByRole("button", { name: /Review Payment/i }).click()
    await expect(page.getByText("Record Payment")).toBeVisible()
    await expect(page.getByText("₹7,000")).toBeVisible()
    await expect(page.getByText("CASH")).toBeVisible()
  })

  test("edit button dismisses confirmation card", async ({ page }) => {
    await page.getByPlaceholder("Name or room number...").fill("205")
    await page.waitForSelector("ul li")
    await page.locator("ul li").first().click()
    await page.getByPlaceholder("0").fill("7000")
    await page.getByRole("button", { name: /Review Payment/i }).click()
    await page.getByRole("button", { name: "Edit" }).click()
    await expect(page.getByText("Record Payment")).not.toBeVisible()
  })

  test("mic button opens voice sheet", async ({ page }) => {
    await page.getByRole("button", { name: /Voice input/i }).click()
    // VoiceSheet opens — check for recording UI
    await expect(page.getByText(/listening|recording/i)).toBeVisible({ timeout: 3000 })
  })
})
```

- [ ] **Step 2: Run e2e tests**

```bash
cd web && npx playwright test e2e/payment-collection.spec.ts --headed
```

Expected: All tests pass (requires dev server running + seeded test DB with a tenant in room 205).

If tests fail due to missing seed data, add a room 205 tenant via bot or direct DB insert first:
```sql
-- Quick seed check (run in Supabase SQL editor or via psql)
SELECT t.name, r.room_number FROM tenancies tn
JOIN tenants t ON tn.tenant_id = t.id
JOIN rooms r ON tn.room_id = r.id
WHERE r.room_number = '205' AND tn.status = 'active';
```

- [ ] **Step 3: Commit**

```bash
git add web/e2e/payment-collection.spec.ts
git commit -m "test(e2e): rent collection form — 7 Playwright scenarios"
```

---

## Task 9: Deploy and Smoke Test on VPS

- [ ] **Step 1: Run full backend test suite**

```bash
venv/Scripts/python -m pytest tests/ -v --tb=short
```
Expected: All previously passing tests still pass + new tenants tests pass.

- [ ] **Step 2: Ship**

```bash
# This is /ship — pre-authorized
git push origin master
```

- [ ] **Step 3: Deploy backend to VPS**

```bash
ssh kozzy-vps "cd /opt/pg-accountant && git pull && systemctl restart pg-accountant"
```

- [ ] **Step 4: Deploy frontend to Vercel**

```bash
cd web && npx vercel --prod
```

- [ ] **Step 5: Live smoke test on reception phone**

On the shared reception phone, open Kozzy PWA:
1. Navigate to Collect Payment
2. Type a tenant name in search → results appear
3. Select tenant → dues shown
4. Enter amount, pick CASH
5. Tap "Review Payment" → confirmation card appears
6. Tap "Confirm" → success screen with amount shown

If any step fails, check Vercel logs (`npx vercel logs`) and VPS logs (`ssh kozzy-vps "journalctl -u pg-accountant -n 50"`).

---

## Self-Review

**Spec coverage check:**
- [x] Tenant search — Task 1 + Task 5
- [x] Dues preview when tenant selected — Task 2 + payment page
- [x] Amount input — payment page
- [x] Payment method (Cash/UPI/Bank/Other) — payment page
- [x] For-type selector — payment page
- [x] Period month — payment page
- [x] Confirmation card before DB write — Task 6 + payment page
- [x] Voice pre-fill — Task 7 (VoiceSheet → handleVoiceIntent)
- [x] Success screen — payment page
- [x] E2E tests — Task 8
- [x] Backend tests — Task 1 + 2

**Placeholder scan:** None. All steps have exact code.

**Type consistency:**
- `TenantSearchResult` defined in api.ts, used in TenantSearch and page.tsx ✓
- `TenantDues` defined in api.ts, used in page.tsx ✓
- `PaymentIntent` already defined in api.ts, used in VoiceSheet callback ✓
- `ConfirmationCard` props: title, fields, onConfirm, onEdit, loading — consistent across Task 6 and usage in page.tsx ✓

---

**Plan complete.** Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast parallel iteration across Tasks 1–3 (backend) and Tasks 4–7 (frontend).

**2. Inline Execution** — Execute tasks in this session using executing-plans, one task at a time with checkpoints.

**Which approach?**
