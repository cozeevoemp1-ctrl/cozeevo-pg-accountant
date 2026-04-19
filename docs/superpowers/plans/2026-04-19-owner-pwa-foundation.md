# Owner PWA — Foundation + Rent Collection · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a usable PWA where Kiran can log in, see today's collection progress, and log a rent payment via voice. This is Plan 1 of 3 (weeks 1-2 of the 6-week Owner PWA project). Plans 2-3 follow after Plan 1 ships to production.

**Architecture:** Next.js 15 PWA (Vercel) → existing FastAPI on VPS via new `/api/v2/app/*` router → shared services layer (lift-and-shift from existing `src/whatsapp/handlers/`) → existing Supabase DB (new `org_id` column) + Groq (Whisper + Llama 3.3 70B). WhatsApp bot is untouched and keeps working in parallel.

**Tech Stack:** Next.js 15 · TypeScript · Tailwind CSS · shadcn/ui primitives · Serwist (PWA service worker) · Supabase Auth (phone+OTP) · FastAPI (existing) · Pydantic · Groq Whisper Large v3 Turbo · Groq Llama 3.3 70B · pytest · Vitest · Playwright (E2E).

**Spec reference:** `docs/superpowers/specs/2026-04-19-owner-pwa-design.md`

**Session reminders (from CLAUDE.md):**
- DB is source of truth — never edit Sheet manually, never hard-delete
- No placeholders — every value derived or asked
- Update ALL dependencies when touching a field (parser, Sheet writer, schema, dashboard, etc.)
- Test locally before any VPS deploy
- `/ship` = commit + push (standing authorization)

---

## File Structure Overview

### New files (PWA — under `/web`)

```
web/
├── package.json                     # Next.js 15, TS, Tailwind, Serwist deps
├── next.config.mjs                  # PWA, headers, env
├── tailwind.config.ts               # Design tokens (brand colors, fonts)
├── tsconfig.json                    # TS strict mode
├── .env.example                     # Document required env vars
├── app/
│   ├── layout.tsx                   # Root layout, font loading, PWA meta
│   ├── page.tsx                     # Home (Collection tab + KPI + Actions + Activity)
│   ├── login/
│   │   └── page.tsx                 # Phone + OTP login
│   ├── payment/
│   │   └── new/
│   │       └── page.tsx             # Voice-first payment entry
│   ├── collection/
│   │   └── breakdown/
│   │       └── page.tsx             # Tap-expanded collection breakdown
│   └── api/                         # Next.js proxy to FastAPI (optional, for CORS simplification)
├── components/
│   ├── ui/
│   │   ├── card.tsx
│   │   ├── button.tsx
│   │   ├── progress-bar.tsx
│   │   ├── icon-tile.tsx
│   │   ├── tab-bar.tsx              # Bottom nav with center mic
│   │   └── pill.tsx
│   ├── home/
│   │   ├── greeting.tsx
│   │   ├── pending-strip.tsx
│   │   ├── overview-card.tsx        # Tabbed (Collection only for v1)
│   │   ├── kpi-grid.tsx
│   │   ├── quick-actions.tsx
│   │   └── activity-feed.tsx
│   ├── voice/
│   │   ├── mic-button.tsx           # Centre tab bar, push-to-talk
│   │   └── voice-sheet.tsx          # Full-screen voice capture + transcript
│   └── auth/
│       ├── phone-input.tsx
│       └── otp-input.tsx
├── lib/
│   ├── api.ts                       # Typed client for /api/v2/app/*
│   ├── auth.ts                      # Supabase client + session
│   ├── format.ts                    # Indian number formatting (₹2,40,000)
│   └── types.ts                     # Shared TS types mirroring Pydantic models
└── tests/
    ├── setup.ts
    ├── components/                   # Vitest component tests
    └── e2e/                          # Playwright E2E
```

### New files (backend — existing FastAPI repo)

```
src/
├── services/                        # NEW — shared business logic, lifted from handlers
│   ├── __init__.py
│   ├── payments.py                  # log_payment(), void_payment()
│   ├── tenants.py                   # list_tenants(), get_tenant()
│   ├── reporting.py                 # collection_summary() per REPORTING.md §4.2
│   └── audit.py                     # write_audit_entry()
├── api/
│   └── v2/
│       ├── __init__.py
│       ├── app_router.py            # Top-level /api/v2/app/* router
│       ├── auth.py                  # JWT verify middleware
│       ├── payments.py              # POST /payments
│       ├── tenants.py               # GET /tenants, GET /tenants/{id}
│       ├── reporting.py             # GET /reporting/collection
│       └── voice.py                 # POST /voice/transcribe, POST /voice/intent
├── database/
│   └── migrations/
│       └── 2026_04_19_add_org_id.py # Append-only migration
└── schemas/                         # NEW — Pydantic models for app API
    ├── __init__.py
    ├── payments.py
    ├── tenants.py
    ├── reporting.py
    └── voice.py

tests/
├── services/
│   ├── test_payments_service.py
│   ├── test_reporting_service.py
│   └── test_tenants_service.py
└── api/v2/
    ├── test_payments_api.py
    ├── test_reporting_api.py
    └── test_voice_api.py
```

### Modified files

- `src/whatsapp/handlers/account_handler.py` — update imports to use `src/services/payments.py` (lift-and-shift target)
- `src/database/models.py` — add `org_id` column to relevant tables
- `src/database/migrate_all.py` — register new migration
- `main.py` — mount `/api/v2/app` router
- `requirements.txt` — add `supabase`, `PyJWT[crypto]`, `pydantic-ai`
- `.env.example` — add `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `JWT_SECRET`

---

## Phase A · Backend Foundation (5 tasks)

### Task 1: Lift `log_payment` from handler to service

**Files:**
- Create: `src/services/__init__.py`
- Create: `src/services/payments.py`
- Create: `src/services/audit.py`
- Create: `tests/services/test_payments_service.py`
- Modify: `src/whatsapp/handlers/account_handler.py` (update import only after service works)

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_payments_service.py
import pytest
from src.services.payments import log_payment
from src.database.models import Payment, Tenancy

def test_log_payment_creates_payment_and_audit(db_session, active_tenancy):
    result = log_payment(
        tenant_id=active_tenancy.tenant_id,
        amount=8000,
        method="UPI",
        for_type="rent",
        period_month="2026-04",
        recorded_by="kiran@cozeevo",
    )
    assert result.payment_id is not None
    assert result.new_balance == active_tenancy.total_due - 8000
    db_payment = db_session.query(Payment).filter_by(id=result.payment_id).one()
    assert db_payment.amount == 8000
    assert db_payment.for_type == "rent"
    assert db_payment.is_void is False
    audit = db_session.query(AuditLog).filter_by(entity_id=result.payment_id).one()
    assert audit.action == "payment.log"
    assert audit.actor == "kiran@cozeevo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_payments_service.py::test_log_payment_creates_payment_and_audit -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services'`

- [ ] **Step 3: Extract `log_payment` from handler into service**

Read `src/whatsapp/handlers/account_handler.py`, find the current payment-logging code (grep for `payment` create/insert), copy the DB write + rent_schedule update + audit logic into:

```python
# src/services/payments.py
from dataclasses import dataclass
from datetime import datetime
from src.database.supabase_client import get_client
from src.services.audit import write_audit_entry

@dataclass
class PaymentResult:
    payment_id: int
    new_balance: int

def log_payment(
    *,
    tenant_id: int,
    amount: int,
    method: str,
    for_type: str,
    period_month: str,
    recorded_by: str,
    notes: str = "",
    org_id: int = 1,
) -> PaymentResult:
    """Log a payment. Writes payments row + audit_log atomically. Returns new balance."""
    sb = get_client()
    # Insert payment
    payment = sb.table("payments").insert({
        "tenant_id": tenant_id,
        "org_id": org_id,
        "amount": amount,
        "method": method,
        "for_type": for_type,
        "period_month": period_month,
        "is_void": False,
        "recorded_by": recorded_by,
        "notes": notes,
        "created_at": datetime.utcnow().isoformat(),
    }).execute()
    payment_id = payment.data[0]["id"]
    # Update rent_schedule status if for_type == 'rent'
    if for_type == "rent":
        _update_rent_schedule(sb, tenant_id, period_month, amount)
    # Audit
    write_audit_entry(
        action="payment.log",
        entity_type="payment",
        entity_id=payment_id,
        actor=recorded_by,
        payload={"amount": amount, "method": method, "for_type": for_type},
    )
    # Compute new balance
    new_balance = _compute_balance(sb, tenant_id)
    return PaymentResult(payment_id=payment_id, new_balance=new_balance)

def _update_rent_schedule(sb, tenant_id, period_month, amount):
    # existing logic — copy from handler
    ...

def _compute_balance(sb, tenant_id):
    # existing logic — copy from handler
    ...
```

```python
# src/services/audit.py
from datetime import datetime
from typing import Any
from src.database.supabase_client import get_client

def write_audit_entry(*, action: str, entity_type: str, entity_id: int, actor: str, payload: dict[str, Any]) -> None:
    sb = get_client()
    sb.table("audit_log").insert({
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor": actor,
        "payload": payload,
        "created_at": datetime.utcnow().isoformat(),
    }).execute()
```

```python
# src/services/__init__.py
from src.services.payments import log_payment, PaymentResult
__all__ = ["log_payment", "PaymentResult"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_payments_service.py -v`
Expected: PASS

- [ ] **Step 5: Update handler to call service (zero behaviour change)**

In `src/whatsapp/handlers/account_handler.py`, replace the inline payment-insert code with:

```python
from src.services.payments import log_payment
# ... inside the handler where it currently inserts a payment:
result = log_payment(
    tenant_id=tenant_id,
    amount=amount,
    method=method,
    for_type="rent",
    period_month=period_month,
    recorded_by=sender_phone,
    notes=notes or "",
)
payment_id = result.payment_id
new_balance = result.new_balance
```

- [ ] **Step 6: Run existing golden tests to verify bot still works**

Run: `TEST_MODE=1 python main.py &` then `pytest tests/eval_golden.py -k payment -v`
Expected: All payment-related golden tests PASS (bot behaviour unchanged)

- [ ] **Step 7: Commit**

```bash
git add src/services/ src/whatsapp/handlers/account_handler.py tests/services/
git commit -m "feat(services): lift log_payment from handler to shared service layer"
```

---

### Task 2: Add `org_id` migration

**Files:**
- Create: `src/database/migrations/2026_04_19_add_org_id.py`
- Modify: `src/database/models.py`
- Modify: `src/database/migrate_all.py`
- Create: `tests/database/test_org_id_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/database/test_org_id_migration.py
from src.database.supabase_client import get_client

def test_org_id_column_exists_on_all_tables():
    sb = get_client()
    for table in ["tenancies", "payments", "rooms", "rent_revisions", "expenses", "leads"]:
        res = sb.rpc("pg_get_column_names", {"table_name": table}).execute()
        names = [r["column_name"] for r in res.data]
        assert "org_id" in names, f"{table} missing org_id"

def test_all_existing_rows_default_to_org_id_1():
    sb = get_client()
    for table in ["tenancies", "payments", "rooms"]:
        rows = sb.table(table).select("org_id").execute()
        assert all(r["org_id"] == 1 for r in rows.data), f"{table} has non-1 org_id rows"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/database/test_org_id_migration.py -v`
Expected: FAIL (org_id column not present)

- [ ] **Step 3: Write migration**

```python
# src/database/migrations/2026_04_19_add_org_id.py
"""Add org_id (INTEGER NOT NULL DEFAULT 1) to multi-tenant tables.

Backfills existing rows with org_id=1 (Cozeevo). Future Kozzy customers get org_id=2, 3, etc.
"""
from src.database.supabase_client import get_client

TABLES = ["tenancies", "payments", "rooms", "rent_revisions", "expenses", "leads", "audit_log"]

def run():
    sb = get_client()
    for table in TABLES:
        sb.rpc("exec_sql", {
            "sql": f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS org_id INTEGER NOT NULL DEFAULT 1;"
        }).execute()
        sb.rpc("exec_sql", {
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{table}_org_id ON {table}(org_id);"
        }).execute()

if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Register in master migration**

In `src/database/migrate_all.py`, append:

```python
from src.database.migrations.add_org_id_2026_04_19 import run as migrate_org_id

MIGRATIONS = [
    # ...existing...
    ("2026_04_19_add_org_id", migrate_org_id),
]
```

- [ ] **Step 5: Run migration + test**

Run: `python -m src.database.migrate_all && pytest tests/database/test_org_id_migration.py -v`
Expected: Migration runs, PASS

- [ ] **Step 6: Update ORM models**

In `src/database/models.py`, add `org_id: int = 1` field to each affected model class.

- [ ] **Step 7: Commit**

```bash
git add src/database/ tests/database/
git commit -m "feat(db): add org_id column to multi-tenant tables (default=1 Cozeevo)"
```

---

### Task 3: FastAPI `/api/v2/app/*` router scaffold with JWT auth

**Files:**
- Create: `src/api/v2/__init__.py`
- Create: `src/api/v2/app_router.py`
- Create: `src/api/v2/auth.py`
- Create: `tests/api/v2/test_auth_middleware.py`
- Modify: `main.py`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/v2/test_auth_middleware.py
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_app_endpoint_requires_jwt():
    r = client.get("/api/v2/app/health")
    assert r.status_code == 401

def test_app_endpoint_accepts_valid_jwt(valid_jwt):
    r = client.get("/api/v2/app/health", headers={"Authorization": f"Bearer {valid_jwt}"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_app_endpoint_rejects_invalid_jwt():
    r = client.get("/api/v2/app/health", headers={"Authorization": "Bearer invalid.token.here"})
    assert r.status_code == 401
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/api/v2/test_auth_middleware.py -v`
Expected: FAIL (router not mounted)

- [ ] **Step 3: Write JWT middleware**

```python
# src/api/v2/auth.py
import os
import jwt
from fastapi import Depends, HTTPException, Header
from dataclasses import dataclass

SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]

@dataclass
class AppUser:
    user_id: str
    phone: str
    role: str  # "admin" | "staff" | "tenant"
    org_id: int

def get_current_user(authorization: str = Header(None)) -> AppUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}")
    return AppUser(
        user_id=payload["sub"],
        phone=payload.get("phone", ""),
        role=payload.get("user_metadata", {}).get("role", "tenant"),
        org_id=payload.get("user_metadata", {}).get("org_id", 1),
    )
```

- [ ] **Step 4: Write router scaffold**

```python
# src/api/v2/app_router.py
from fastapi import APIRouter, Depends
from src.api.v2.auth import AppUser, get_current_user

router = APIRouter(prefix="/api/v2/app", tags=["app"])

@router.get("/health")
def health(user: AppUser = Depends(get_current_user)):
    return {"status": "ok", "user_id": user.user_id, "role": user.role}
```

```python
# src/api/v2/__init__.py
from src.api.v2.app_router import router as app_router
__all__ = ["app_router"]
```

- [ ] **Step 5: Mount in main**

In `main.py`, after existing route registrations:

```python
from src.api.v2 import app_router
app.include_router(app_router)
```

- [ ] **Step 6: Add env var**

In `.env.example`:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=ey...
SUPABASE_JWT_SECRET=your-jwt-secret-from-supabase-dashboard
```

- [ ] **Step 7: Install PyJWT**

Add to `requirements.txt`:
```
PyJWT[crypto]>=2.8.0
```

Run: `pip install -r requirements.txt`

- [ ] **Step 8: Run tests**

Run: `pytest tests/api/v2/test_auth_middleware.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 9: Commit**

```bash
git add src/api/v2/ main.py requirements.txt .env.example tests/api/v2/
git commit -m "feat(api): /api/v2/app/* router with Supabase JWT auth middleware"
```

---

### Task 4: `POST /api/v2/app/payments` endpoint

**Files:**
- Create: `src/api/v2/payments.py`
- Create: `src/schemas/payments.py`
- Modify: `src/api/v2/app_router.py`
- Create: `tests/api/v2/test_payments_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/v2/test_payments_api.py
def test_post_payment_happy_path(client, admin_jwt, active_tenant):
    r = client.post(
        "/api/v2/app/payments",
        headers={"Authorization": f"Bearer {admin_jwt}"},
        json={
            "tenant_id": active_tenant.id,
            "amount": 8000,
            "method": "UPI",
            "for_type": "rent",
            "period_month": "2026-04",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["payment_id"] > 0
    assert body["new_balance"] is not None
    assert body["receipt_sent"] is True

def test_post_payment_rejects_non_admin(client, tenant_jwt):
    r = client.post(
        "/api/v2/app/payments",
        headers={"Authorization": f"Bearer {tenant_jwt}"},
        json={"tenant_id": 1, "amount": 1000, "method": "UPI", "for_type": "rent", "period_month": "2026-04"},
    )
    assert r.status_code == 403

def test_post_payment_validates_amount():
    r = client.post(
        "/api/v2/app/payments",
        headers={"Authorization": f"Bearer {admin_jwt}"},
        json={"tenant_id": 1, "amount": -100, "method": "UPI", "for_type": "rent", "period_month": "2026-04"},
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/api/v2/test_payments_api.py -v`
Expected: FAIL (endpoint doesn't exist)

- [ ] **Step 3: Write Pydantic schemas**

```python
# src/schemas/payments.py
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class PaymentCreate(BaseModel):
    tenant_id: int = Field(gt=0)
    amount: int = Field(gt=0, description="Amount in rupees (integer, no paise)")
    method: Literal["UPI", "CASH", "BANK", "CARD", "OTHER"]
    for_type: Literal["rent", "deposit", "maintenance", "booking", "adjustment"]
    period_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    notes: str = ""

class PaymentResponse(BaseModel):
    payment_id: int
    new_balance: int
    receipt_sent: bool
```

- [ ] **Step 4: Write endpoint**

```python
# src/api/v2/payments.py
from fastapi import APIRouter, Depends, HTTPException
from src.api.v2.auth import AppUser, get_current_user
from src.schemas.payments import PaymentCreate, PaymentResponse
from src.services.payments import log_payment
from src.integrations.whatsapp import send_receipt_to_tenant

router = APIRouter()

@router.post("/payments", response_model=PaymentResponse, status_code=201)
def create_payment(body: PaymentCreate, user: AppUser = Depends(get_current_user)):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin/staff only")
    result = log_payment(
        tenant_id=body.tenant_id,
        amount=body.amount,
        method=body.method,
        for_type=body.for_type,
        period_month=body.period_month,
        recorded_by=user.phone or user.user_id,
        notes=body.notes,
        org_id=user.org_id,
    )
    receipt_sent = send_receipt_to_tenant(tenant_id=body.tenant_id, payment_id=result.payment_id)
    return PaymentResponse(
        payment_id=result.payment_id,
        new_balance=result.new_balance,
        receipt_sent=receipt_sent,
    )
```

- [ ] **Step 5: Mount sub-router**

In `src/api/v2/app_router.py`:

```python
from src.api.v2.payments import router as payments_router
router.include_router(payments_router)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/api/v2/test_payments_api.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/api/v2/payments.py src/schemas/payments.py src/api/v2/app_router.py tests/api/v2/
git commit -m "feat(api): POST /api/v2/app/payments + WhatsApp receipt dispatch"
```

---

### Task 5: `GET /api/v2/app/reporting/collection` (per REPORTING.md §4.2)

**Files:**
- Create: `src/services/reporting.py`
- Create: `src/api/v2/reporting.py`
- Create: `src/schemas/reporting.py`
- Modify: `src/api/v2/app_router.py`
- Create: `tests/services/test_reporting_service.py`
- Create: `tests/api/v2/test_reporting_api.py`

- [ ] **Step 1: Write the failing service test**

```python
# tests/services/test_reporting_service.py
from src.services.reporting import collection_summary

def test_collection_summary_structure(db_session, seeded_april):
    s = collection_summary(period_month="2026-04", org_id=1)
    assert s.collected == s.rent_collected + s.maintenance_collected
    assert s.expected > 0
    assert s.pending == s.expected - s.collected
    assert 0 <= s.collection_pct <= 100
    # Per REPORTING.md §4.2 — deposits + booking advances NOT in collected
    assert s.deposits_received >= 0
    assert s.booking_advances >= 0
    assert s.collected == s.rent_collected + s.maintenance_collected  # NOT including deposits/advances
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/services/test_reporting_service.py -v`
Expected: FAIL

- [ ] **Step 3: Write the service**

```python
# src/services/reporting.py
"""Per REPORTING.md §4.2 — Total Collection = rent + maintenance only.
Deposits and booking advances are tracked but EXCLUDED from Total Collection."""

from dataclasses import dataclass
from src.database.supabase_client import get_client

@dataclass
class CollectionSummary:
    period_month: str
    expected: int
    collected: int
    pending: int
    collection_pct: int
    rent_collected: int
    maintenance_collected: int
    deposits_received: int
    booking_advances: int
    overdue_count: int

def collection_summary(*, period_month: str, org_id: int = 1) -> CollectionSummary:
    sb = get_client()
    # Rent collected — per REPORTING.md §4.2
    rent_res = sb.rpc("sum_payments_for_type", {
        "p_for_type": "rent",
        "p_period_month": period_month,
        "p_org_id": org_id,
    }).execute()
    rent_collected = rent_res.data or 0
    maint_collected = (sb.rpc("sum_payments_for_type", {
        "p_for_type": "maintenance", "p_period_month": period_month, "p_org_id": org_id,
    }).execute()).data or 0
    deposits = (sb.rpc("sum_payments_for_type", {
        "p_for_type": "deposit", "p_period_month": period_month, "p_org_id": org_id,
    }).execute()).data or 0
    advances = (sb.rpc("sum_payments_for_type", {
        "p_for_type": "booking", "p_period_month": period_month, "p_org_id": org_id,
    }).execute()).data or 0

    # Expected — per REPORTING.md §4.1
    expected = (sb.rpc("expected_collection_for_month", {
        "p_period_month": period_month, "p_org_id": org_id,
    }).execute()).data or 0

    # Overdue count — tenants with RentSchedule in [pending, partial] for this or earlier months
    overdue = (sb.rpc("overdue_tenant_count", {
        "p_period_month": period_month, "p_org_id": org_id,
    }).execute()).data or 0

    collected = rent_collected + maint_collected
    pending = max(expected - collected, 0)
    pct = round(collected / expected * 100) if expected > 0 else 0

    return CollectionSummary(
        period_month=period_month,
        expected=expected,
        collected=collected,
        pending=pending,
        collection_pct=pct,
        rent_collected=rent_collected,
        maintenance_collected=maint_collected,
        deposits_received=deposits,
        booking_advances=advances,
        overdue_count=overdue,
    )
```

- [ ] **Step 4: Write the SQL functions (Supabase SQL editor)**

```sql
-- Run once in Supabase SQL editor
CREATE OR REPLACE FUNCTION sum_payments_for_type(p_for_type text, p_period_month text, p_org_id int)
RETURNS int LANGUAGE sql AS $$
  SELECT COALESCE(SUM(amount), 0)::int FROM payments
  WHERE for_type = p_for_type AND period_month = p_period_month AND org_id = p_org_id AND is_void = false;
$$;

-- similar for expected_collection_for_month, overdue_tenant_count — see REPORTING.md
```

- [ ] **Step 5: Run service test**

Run: `pytest tests/services/test_reporting_service.py -v`
Expected: PASS

- [ ] **Step 6: Write Pydantic schema**

```python
# src/schemas/reporting.py
from pydantic import BaseModel

class CollectionSummaryResponse(BaseModel):
    period_month: str
    expected: int
    collected: int
    pending: int
    collection_pct: int
    rent_collected: int
    maintenance_collected: int
    deposits_received: int
    booking_advances: int
    overdue_count: int
```

- [ ] **Step 7: Write the endpoint**

```python
# src/api/v2/reporting.py
from fastapi import APIRouter, Depends
from src.api.v2.auth import AppUser, get_current_user
from src.services.reporting import collection_summary
from src.schemas.reporting import CollectionSummaryResponse

router = APIRouter(prefix="/reporting")

@router.get("/collection", response_model=CollectionSummaryResponse)
def get_collection_summary(period_month: str, user: AppUser = Depends(get_current_user)):
    s = collection_summary(period_month=period_month, org_id=user.org_id)
    return CollectionSummaryResponse(**s.__dict__)
```

- [ ] **Step 8: Mount + API test**

In `src/api/v2/app_router.py`, add `router.include_router(reporting_router)`.

Write API test:

```python
# tests/api/v2/test_reporting_api.py
def test_get_collection_summary(client, admin_jwt):
    r = client.get(
        "/api/v2/app/reporting/collection?period_month=2026-04",
        headers={"Authorization": f"Bearer {admin_jwt}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["period_month"] == "2026-04"
    assert body["collected"] == body["rent_collected"] + body["maintenance_collected"]
    assert body["deposits_received"] >= 0  # separate, not in collected
```

Run: `pytest tests/api/v2/test_reporting_api.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/services/reporting.py src/api/v2/reporting.py src/schemas/reporting.py src/api/v2/app_router.py tests/
git commit -m "feat(api): GET /api/v2/app/reporting/collection per REPORTING.md §4.2"
```

---

## Phase B · Auth + PWA Skeleton (6 tasks)

### Task 6: Configure Supabase Auth (phone+OTP)

**Files:** (Supabase dashboard, plus env var updates)

- [ ] **Step 1:** Open Supabase project → Authentication → Providers → enable **Phone** provider
- [ ] **Step 2:** Configure SMS provider (Twilio recommended; use existing account or sign up)
- [ ] **Step 3:** Add 4 test phone numbers for dev: Kiran (+917845952289), partner (+917358341775), Prabhakaran, Lakshmi Mam
- [ ] **Step 4:** In Supabase dashboard → user_metadata, set `{"role": "admin", "org_id": 1}` for Kiran and partner; `"staff"` for Prabhakaran/Lakshmi
- [ ] **Step 5:** Copy JWT secret from Project Settings → API → JWT Settings → add to `.env` as `SUPABASE_JWT_SECRET`
- [ ] **Step 6:** Commit `.env.example` if any new keys added. No code commit required for this task.

---

### Task 7: Init Next.js 15 PWA skeleton

**Files:**
- Create: entire `/web` directory via `create-next-app`

- [ ] **Step 1: Create Next.js app**

From the repo root:

```bash
npx create-next-app@latest web --typescript --tailwind --app --src-dir=false --import-alias="@/*" --no-eslint
```

- [ ] **Step 2: Add dependencies**

```bash
cd web
npm i @supabase/ssr @supabase/supabase-js serwist clsx lucide-react
npm i -D @serwist/next @types/node vitest @vitejs/plugin-react @testing-library/react @testing-library/jest-dom playwright
```

- [ ] **Step 3: Configure Serwist PWA**

```js
// web/next.config.mjs
import withSerwistInit from "@serwist/next";

const withSerwist = withSerwistInit({
  swSrc: "app/sw.ts",
  swDest: "public/sw.js",
});

export default withSerwist({
  reactStrictMode: true,
});
```

```ts
// web/app/sw.ts
import { defaultCache } from "@serwist/next/worker";
import { installSerwist } from "serwist";
installSerwist({
  precacheEntries: self.__SW_MANIFEST,
  runtimeCaching: defaultCache,
  skipWaiting: true,
  clientsClaim: true,
});
```

- [ ] **Step 4: Configure manifest**

```json
// web/public/manifest.json
{
  "name": "Kozzy · Cozeevo Help Desk",
  "short_name": "Kozzy",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#F6F5F0",
  "theme_color": "#EF1F9C",
  "icons": [
    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

Add icons to `/web/public/` (use brand pink K on cream — take from design mockups).

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "feat(web): scaffold Next.js 15 PWA with Serwist + manifest"
```

---

### Task 8: Tailwind theme + DM Sans + design tokens

**Files:**
- Modify: `web/tailwind.config.ts`
- Modify: `web/app/layout.tsx`
- Create: `web/app/globals.css`

- [ ] **Step 1: Write tailwind config**

```ts
// web/tailwind.config.ts
import type { Config } from "tailwindcss";
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F6F5F0",
        surface: "#FFFFFF",
        ink: {
          DEFAULT: "#0F0E0D",
          muted: "#6F655D",
        },
        brand: {
          pink: "#EF1F9C",
          blue: "#00AEED",
        },
        status: {
          paid: "#2A7A2A",
          due: "#EF1F9C",
          warn: "#C25000",
        },
        tile: {
          green: "#E1F3DF",
          pink: "#FCE2EE",
          blue: "#DFF0FB",
          orange: "#FFE8D0",
        },
      },
      fontFamily: {
        sans: ["var(--font-dm-sans)", "system-ui", "sans-serif"],
      },
      borderRadius: {
        card: "18px",
        tile: "14px",
        pill: "12px",
      },
    },
  },
  plugins: [],
} satisfies Config;
```

- [ ] **Step 2: Load DM Sans + set theme color**

```tsx
// web/app/layout.tsx
import { DM_Sans } from "next/font/google";
import "./globals.css";

const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans", weight: ["400","500","600","700","800"] });

export const metadata = {
  title: "Kozzy",
  manifest: "/manifest.json",
  themeColor: "#EF1F9C",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={dmSans.variable}>
      <body className="bg-bg text-ink font-sans">{children}</body>
    </html>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add web/tailwind.config.ts web/app/
git commit -m "feat(web): tailwind theme + DM Sans + design tokens"
```

---

### Task 9: Shared UI primitives + format helpers

**Files:**
- Create: `web/components/ui/card.tsx`, `button.tsx`, `progress-bar.tsx`, `icon-tile.tsx`, `pill.tsx`, `tab-bar.tsx`
- Create: `web/lib/format.ts`
- Create: `web/tests/components/*.test.tsx`

- [ ] **Step 1: Write `lib/format.ts` test first**

```ts
// web/tests/format.test.ts
import { rupee, indianNumber } from "@/lib/format";

test("rupee formats Indian number system", () => {
  expect(rupee(240000)).toBe("₹2,40,000");
  expect(rupee(78000)).toBe("₹78,000");
  expect(rupee(192000)).toBe("₹1,92,000");
  expect(rupee(0)).toBe("₹0");
});
```

- [ ] **Step 2: Verify fail then implement**

```ts
// web/lib/format.ts
export function indianNumber(n: number): string {
  const s = Math.abs(n).toString();
  const last3 = s.slice(-3);
  const rest = s.slice(0, -3);
  const withCommas = rest.length ? rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3 : last3;
  return n < 0 ? `-${withCommas}` : withCommas;
}
export function rupee(n: number): string {
  return `₹${indianNumber(n)}`;
}
```

- [ ] **Step 3: Write primitives** (Card, Button, ProgressBar, IconTile, Pill, TabBar)

Use component code from mockup `home-v5-complete.html` as reference — port each styled section to a React component. Each primitive takes props for variant/size/children.

- [ ] **Step 4: Commit**

```bash
git add web/components/ web/lib/ web/tests/
git commit -m "feat(web): UI primitives + Indian number formatting helpers"
```

---

### Task 10: Supabase client + auth context

**Files:**
- Create: `web/lib/supabase.ts`
- Create: `web/lib/auth.ts`
- Create: `web/components/auth/auth-provider.tsx`

- [ ] **Step 1:** Create Supabase client

```ts
// web/lib/supabase.ts
import { createBrowserClient } from "@supabase/ssr";

export function supabase() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
```

- [ ] **Step 2:** Auth context provider that wraps app, exposes `user`, `signIn(phone)`, `verifyOtp(phone, otp)`, `signOut()`
- [ ] **Step 3:** Wire in `app/layout.tsx`
- [ ] **Step 4:** Add to `.env.local.example`: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- [ ] **Step 5:** Commit

```bash
git add web/lib/ web/components/auth/ web/app/layout.tsx web/.env.local.example
git commit -m "feat(web): Supabase client + auth context provider"
```

---

### Task 11: Mockup → Login screen → user approval

- [ ] **Step 1: Produce login mockup in Visual Companion**

Push an HTML mockup to brainstorm session for the login flow (phone input → OTP → biometric gate). Follow the locked design language: cream bg, pink accents, DM Sans, generous radius.

- [ ] **Step 2: Wait for user review; iterate if needed (≤2 iterations typical)**

- [ ] **Step 3: On approval, code the screen:**

```
web/app/login/page.tsx      — phone input step
web/app/login/verify/page.tsx — OTP input step
web/components/auth/phone-input.tsx
web/components/auth/otp-input.tsx
```

- [ ] **Step 4: Wire to Supabase: signInWithOtp({ phone }) → verifyOtp({ phone, token, type: "sms" })**

- [ ] **Step 5: E2E test with Playwright**

```ts
// web/tests/e2e/login.spec.ts
import { test, expect } from "@playwright/test";
test("login with phone+OTP", async ({ page }) => {
  await page.goto("/login");
  await page.fill("[name=phone]", "+917845952289");
  await page.click("text=Send OTP");
  await expect(page).toHaveURL(/\/verify/);
  // Use Supabase test-mode OTP (123456)
  await page.fill("[name=otp]", "123456");
  await page.click("text=Verify");
  await expect(page).toHaveURL("/");
});
```

- [ ] **Step 6: Commit**

```bash
git add web/app/login/ web/components/auth/ web/tests/e2e/login.spec.ts
git commit -m "feat(web): phone+OTP login flow"
```

---

## Phase C · Home Screen (4 tasks)

### Task 12: Mockup → Home (Collection tab) → user approval

- [ ] **Step 1:** Push home screen mockup (already exists at `home-v5-complete.html`/`home-v6-multioverview.html` — reference). For v1, lock the Collection tab only (Bookings/Expenses/P&L tabs come in Plan 2).
- [ ] **Step 2:** User re-confirms. (Already approved in brainstorm; this step is for completeness / any late tweaks.)

---

### Task 13: Home page scaffold + greeting + pending strip

**Files:**
- Create: `web/app/page.tsx`
- Create: `web/components/home/greeting.tsx`, `pending-strip.tsx`

- [ ] **Step 1:** Fetch user session on server; if unauth, redirect to `/login`
- [ ] **Step 2:** Render `<Greeting />` (name from session) + `<PendingStrip />` (fetches `/api/v2/app/reporting/collection` for overdue_count + pending amount)
- [ ] **Step 3:** Component test for `<Greeting />` rendering passed prop
- [ ] **Step 4:** Commit

---

### Task 14: Overview card + collection data + progress bar

**Files:**
- Create: `web/components/home/overview-card.tsx`
- Create: `web/lib/api.ts` (typed client)

- [ ] **Step 1:** Write typed API client for `getCollectionSummary(periodMonth)` that calls `/api/v2/app/reporting/collection`
- [ ] **Step 2:** Write `<OverviewCard>` with props `{collected, expected, pending, collectionPct}`. Renders title "April 2026 · Collection", label "Collected this month", big rupee value with "of ₹X" suffix, progress bar with 75% width, meta line, tap CTA
- [ ] **Step 3:** Vitest for component: snapshot + assert progress width matches pct
- [ ] **Step 4:** Use in `app/page.tsx` with data from server-side fetch
- [ ] **Step 5:** Commit

---

### Task 15: KPI grid + Quick Actions + Recent Activity

**Files:**
- Create: `web/components/home/kpi-grid.tsx`, `quick-actions.tsx`, `activity-feed.tsx`
- Create: backend endpoints `GET /api/v2/app/reporting/kpi`, `GET /api/v2/app/activity/recent`
- Services: `src/services/kpi.py`, `src/services/activity.py`
- Tests: service + API tests for both

- [ ] **Step 1:** Write service tests (kpi returns beds_occupied, vacant, active_tenants, in_out_today; activity returns last N transactions with tenant + amount + method)
- [ ] **Step 2:** Implement services (lift from existing dashboard endpoints if they already compute these)
- [ ] **Step 3:** Expose as API endpoints under `/api/v2/app/`
- [ ] **Step 4:** Build React components using same design language as mockup (pastel icon cards, uniform treatment)
- [ ] **Step 5:** Wire to `app/page.tsx`
- [ ] **Step 6:** Commit per layer (backend, then frontend)

---

## Phase D · Voice + Rent Collection (5 tasks)

### Task 16: Voice recording component + microphone permission

**Files:**
- Create: `web/components/voice/mic-button.tsx` (center tab bar button)
- Create: `web/components/voice/voice-sheet.tsx` (full-screen capture UI)
- Create: `web/lib/voice.ts` (MediaRecorder helpers)

- [ ] **Step 1:** Write hook `useVoiceRecorder()` that returns `{start, stop, audioBlob, state}`. Use MediaRecorder API with `audio/webm;codecs=opus` fallback to `audio/mp4`.
- [ ] **Step 2:** Vitest: mock `navigator.mediaDevices.getUserMedia`, verify lifecycle.
- [ ] **Step 3:** Build `<MicButton>` — appears in tab bar center, tap opens `<VoiceSheet>`.
- [ ] **Step 4:** Build `<VoiceSheet>` full-screen modal — shows big pulsing mic, "Listening..." text, transcript as it comes in, editable after stop, Confirm/Cancel buttons.
- [ ] **Step 5:** Commit

---

### Task 17: `POST /api/v2/app/voice/transcribe` with Groq Whisper

**Files:**
- Create: `src/api/v2/voice.py`
- Create: `src/services/voice.py`
- Create: `src/schemas/voice.py`
- Create: `tests/services/test_voice_service.py`

- [ ] **Step 1: Write service test**

```python
def test_transcribe_returns_text_and_lang(sample_audio_bytes):
    result = transcribe(audio_bytes=sample_audio_bytes, mime="audio/webm")
    assert len(result.text) > 0
    assert result.language in ("en", "ta", "hi", "auto")
    assert result.duration_seconds > 0
```

- [ ] **Step 2: Verify fail then implement using Groq SDK**

```python
# src/services/voice.py
import os
from dataclasses import dataclass
from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])

@dataclass
class TranscribeResult:
    text: str
    language: str
    duration_seconds: float

def transcribe(*, audio_bytes: bytes, mime: str) -> TranscribeResult:
    res = client.audio.transcriptions.create(
        file=("audio", audio_bytes, mime),
        model="whisper-large-v3-turbo",
        response_format="verbose_json",
    )
    return TranscribeResult(
        text=res.text,
        language=res.language,
        duration_seconds=res.duration,
    )
```

- [ ] **Step 3: API endpoint**

```python
# src/api/v2/voice.py
@router.post("/voice/transcribe")
async def transcribe_endpoint(
    audio: UploadFile,
    user: AppUser = Depends(get_current_user),
):
    bytes_ = await audio.read()
    result = transcribe(audio_bytes=bytes_, mime=audio.content_type)
    return {"text": result.text, "language": result.language, "duration_seconds": result.duration_seconds}
```

- [ ] **Step 4: Frontend integration** — on voice-sheet stop, POST blob as multipart form-data, show returned text
- [ ] **Step 5: Commit**

---

### Task 18: `POST /api/v2/app/voice/intent` with Llama 3.3 70B structured extraction

**Files:**
- Create: `src/services/intent_voice.py`
- Modify: `src/api/v2/voice.py`
- Create: `tests/services/test_intent_voice.py`

- [ ] **Step 1: Write test for payment intent extraction**

```python
def test_extract_payment_intent():
    r = extract_intent(transcript="Got 8k from Ravi H201 UPI today", context_tenants=[...])
    assert r.intent == "log_payment"
    assert r.entities["amount"] == 8000
    assert r.entities["tenant"]["name"].lower() == "ravi"
    assert r.entities["tenant"]["room"] == "H201"
    assert r.entities["method"] == "UPI"
```

- [ ] **Step 2: Verify fail then implement using PydanticAI**

```python
# src/services/intent_voice.py
from pydantic import BaseModel
from pydantic_ai import Agent

class PaymentIntent(BaseModel):
    intent: str  # "log_payment" | "check_balance" | "unknown"
    amount: int | None = None
    tenant_name: str | None = None
    tenant_room: str | None = None
    method: str | None = None
    for_type: str | None = None

agent = Agent("groq:llama-3.3-70b-versatile", result_type=PaymentIntent)

def extract_intent(*, transcript: str, context_tenants: list[dict]) -> PaymentIntent:
    prompt = f"""Extract structured data from this owner's voice note.
Transcript: "{transcript}"
Known tenants (name, room): {context_tenants}
If amount uses "k" suffix, multiply by 1000 (e.g. "8k" = 8000).
Method: UPI / CASH / BANK / CARD / OTHER."""
    return agent.run_sync(prompt).data
```

- [ ] **Step 3:** API endpoint + frontend hook that calls this after transcribe
- [ ] **Step 4:** On confirm button in voice-sheet, call `POST /api/v2/app/payments` with extracted fields
- [ ] **Step 5:** Commit

---

### Task 19: Mockup → Payment entry screen → user approval

- [ ] **Step 1:** Produce mockup with 2 states: voice capture (big mic + transcript) + confirmation (pre-filled form with Tenant / Amount / Method / For / Date + Confirm button)
- [ ] **Step 2:** User review, iterate
- [ ] **Step 3:** On approval, build `web/app/payment/new/page.tsx` with the two states
- [ ] **Step 4:** Add manual-entry fallback (typing form if voice fails)
- [ ] **Step 5:** Commit

---

### Task 20: End-to-end test: voice → transcribe → intent → payment → receipt → DB

**Files:**
- Create: `web/tests/e2e/payment-voice.spec.ts`
- Create: `tests/integration/test_payment_flow.py`

- [ ] **Step 1: Backend integration test**

```python
# tests/integration/test_payment_flow.py
def test_full_payment_flow(client, admin_jwt, active_tenant, sample_voice_blob):
    # Transcribe
    r = client.post("/api/v2/app/voice/transcribe",
                    headers=auth(admin_jwt),
                    files={"audio": ("voice.webm", sample_voice_blob, "audio/webm")})
    transcript = r.json()["text"]

    # Intent
    r = client.post("/api/v2/app/voice/intent",
                    headers=auth(admin_jwt),
                    json={"transcript": transcript})
    entities = r.json()

    # Log payment
    r = client.post("/api/v2/app/payments",
                    headers=auth(admin_jwt),
                    json={
                        "tenant_id": active_tenant.id,
                        "amount": entities["amount"],
                        "method": entities["method"],
                        "for_type": "rent",
                        "period_month": "2026-04",
                    })
    assert r.status_code == 201
    assert r.json()["receipt_sent"] is True

    # Verify DB + audit
    payment = db_get_payment(r.json()["payment_id"])
    assert payment.tenant_id == active_tenant.id
    audit = db_get_audit(payment.id)
    assert audit.action == "payment.log"
```

- [ ] **Step 2: Playwright E2E**

```ts
test("voice payment from home screen", async ({ page, context }) => {
  await context.grantPermissions(["microphone"]);
  await login(page);
  await page.click("[aria-label=Voice]");
  await page.waitForSelector("[data-testid=mic-active]");
  // Simulate audio input via evaluate with test blob
  ...
  await page.click("text=Confirm");
  await expect(page.locator(".toast")).toContainText("Payment logged");
});
```

- [ ] **Step 3:** Run both tests; fix regressions
- [ ] **Step 4:** Commit

---

## Phase E · Collection Breakdown Screen (2 tasks)

### Task 21: Mockup → Collection breakdown page → approval

- [ ] **Step 1:** Reference mockup `home-v4-collection.html` right-side phone for layout
- [ ] **Step 2:** Iterate if needed
- [ ] **Step 3:** On approval, build `web/app/collection/breakdown/page.tsx`
- [ ] **Step 4:** Commit

---

### Task 22: Wire breakdown to API

- [ ] **Step 1:** Use existing `/api/v2/app/reporting/collection` endpoint — it already returns all fields (rent_collected, maintenance_collected, deposits_received, booking_advances, pending, overdue_count)
- [ ] **Step 2:** Render three sections exactly as mockup: "Counted in Total Collection" (rent THOR + rent HULK + maintenance), "Pending (not yet collected)", "Separate (NOT in Total Collection)" (deposits + booking advances)
- [ ] **Step 3:** Add "back" nav to home
- [ ] **Step 4:** Tap on home overview card navigates here
- [ ] **Step 5:** Commit

---

## Phase F · Ship (3 tasks)

### Task 23: Vercel staging deploy + environment setup

- [ ] **Step 1:** Connect `web/` directory to Vercel via GitHub integration
- [ ] **Step 2:** Add env vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL=https://api.getkozzy.com`
- [ ] **Step 3:** Configure custom domain (e.g. `app.getkozzy.com`) via Vercel DNS
- [ ] **Step 4:** Verify staging build passes + PWA audit score ≥ 90 (Lighthouse)
- [ ] **Step 5:** Commit any config changes

---

### Task 24: Deploy backend to VPS

- [ ] **Step 1:** SSH to VPS, `git pull`, `pip install -r requirements.txt`
- [ ] **Step 2:** Run migration: `python -m src.database.migrate_all`
- [ ] **Step 3:** Restart service: `systemctl restart pg-accountant`
- [ ] **Step 4:** Verify `/api/v2/app/health` returns 401 (requires auth — confirms it's live)
- [ ] **Step 5:** Tail logs for 10 min during first Kiran login
- [ ] **Step 6:** No git commit — VPS-side only

---

### Task 25: Beta rollout to Kiran (one user)

- [ ] **Step 1:** Send app install link to Kiran's phone
- [ ] **Step 2:** Observe first 5 real payments logged via voice
- [ ] **Step 3:** Track success rate (voice intent correct on first try?)
- [ ] **Step 4:** Log any issues in `memory/project_pending_tasks.md`
- [ ] **Step 5:** End-of-session CLAUDE.md checklist: update CHANGELOG with Plan 1 ship, memory with lessons, deploy note in pending tasks

---

## Definition of Done (Plan 1)

- [ ] Kiran can log in with phone + OTP
- [ ] Home screen loads in < 2s, shows accurate Collection % + pending
- [ ] Voice → transcript → intent → payment round-trip works for at least 80% of real voice notes Kiran makes in first week
- [ ] Receipt goes to tenant via existing WhatsApp flow (no changes to bot code)
- [ ] Zero regressions in existing WhatsApp bot (golden tests still pass)
- [ ] `org_id` migrated on live DB, defaults to 1
- [ ] Audit log populated for every payment logged via app
- [ ] All new code has tests; `pytest` + `vitest` + `playwright` all green

---

## Dependencies Required Before Starting

- Supabase Auth phone provider enabled + Twilio SMS configured (Task 6)
- Vercel account connected to repo (can do in Task 23)
- Brand icon PNGs (192px, 512px) — create from logo in `data/cozeevo_logo.png` or ask Kiran
- `.env` updated with `SUPABASE_JWT_SECRET` before Task 3 can run
