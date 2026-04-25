# Checkout Form Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-step web checkout form (receptionist fills all details, tenant confirms via WhatsApp) and fix the existing WhatsApp conversational checkout to show full financial details before writing to DB.

**Architecture:** New `CheckoutSession` table holds form data pre-confirmation. A shared `_do_confirm_checkout()` helper writes `CheckoutRecord` + `Refund`, marks tenancy exited, and syncs Sheet — called from three places: the WhatsApp CHECKOUT_AGREE handler, the CHECKOUT_REJECT handler, and an APScheduler auto-confirm job. Phase 2 rewrites the `RECORD_CHECKOUT` WhatsApp step flow to add deduction steps and defer all DB writes to the final confirm step.

**Tech Stack:** FastAPI, SQLAlchemy async (PostgreSQL via Supabase), APScheduler, gspread, Meta WhatsApp Cloud API (`_send_whatsapp` / `_send_whatsapp_template` from `src/whatsapp/webhook_handler.py`)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/database/models.py` | Modify | Add `CheckoutSession` model + `CheckoutSessionStatus` enum; extend `CheckoutRecord` with 6 new columns |
| `src/database/migrate_all.py` | Modify | Append migration: create `checkout_sessions` table, `ALTER TABLE checkout_records` |
| `src/whatsapp/handlers/owner_handler.py` | Modify | Extract `_do_confirm_checkout()` shared helper; add `_handle_checkout_agree()` + `_handle_checkout_reject()`; fix `RECORD_CHECKOUT` step flow (Phase 2) |
| `src/api/checkout_router.py` | Create | Tenant autocomplete, pre-fetch, session create, status poll |
| `src/whatsapp/chat_api.py` | Modify | Intercept YES/NO from tenants with active `CheckoutSession` before intent detection |
| `src/scheduler.py` | Modify | Add `_auto_confirm_checkout_sessions` job (every 15 min) |
| `main.py` | Modify | Register `checkout_router`, add `/admin/checkout` route, allow path in middleware |
| `static/checkout_admin.html` | Create | 3-step receptionist form |
| `static/admin_onboarding.html` | Modify | Add shared nav bar |
| `tests/test_checkout_router.py` | Create | API endpoint tests |
| `tests/test_checkout_flow.py` | Create | WhatsApp YES/NO/auto-confirm flow tests |

---

## Task 1: DB Model — CheckoutSession + extend CheckoutRecord

**Files:**
- Modify: `src/database/models.py`

- [ ] **Step 1: Add `CheckoutSessionStatus` enum and `CheckoutSession` model**

  Open `src/database/models.py`. After the `OnboardingSession` class (around line 880), add:

  ```python
  class CheckoutSessionStatus:
      pending       = "pending"
      confirmed     = "confirmed"
      auto_confirmed = "auto_confirmed"
      rejected      = "rejected"
      cancelled     = "cancelled"


  class CheckoutSession(Base):
      """
      Checkout form session created by receptionist.
      Tenant confirms (or auto-confirms after 2hr) via WhatsApp YES/NO.
      """
      __tablename__ = "checkout_sessions"

      id                    = Column(Integer, primary_key=True)
      token                 = Column(String(36), unique=True, nullable=False, index=True)
      status                = Column(String(20), default=CheckoutSessionStatus.pending, nullable=False)
      created_by_phone      = Column(String(20), nullable=False)
      tenant_phone          = Column(String(20), nullable=False)
      tenancy_id            = Column(Integer, ForeignKey("tenancies.id"), nullable=False)
      checkout_date         = Column(Date, nullable=False)
      room_key_returned     = Column(Boolean, nullable=False, default=False)
      wardrobe_key_returned = Column(Boolean, nullable=False, default=False)
      biometric_removed     = Column(Boolean, nullable=False, default=False)
      room_condition_ok     = Column(Boolean, nullable=False, default=True)
      damage_notes          = Column(Text, nullable=True)
      security_deposit      = Column(Numeric(12, 2), nullable=False, default=0)
      pending_dues          = Column(Numeric(12, 2), nullable=False, default=0)
      deductions            = Column(Numeric(12, 2), nullable=False, default=0)
      deduction_reason      = Column(Text, nullable=True)
      refund_amount         = Column(Numeric(12, 2), nullable=False, default=0)
      refund_mode           = Column(String(10), nullable=False)
      rejection_reason      = Column(Text, nullable=True)
      expires_at            = Column(DateTime, nullable=False)
      confirmed_at          = Column(DateTime, nullable=True)
      created_at            = Column(DateTime, default=datetime.utcnow)

      __table_args__ = (
          Index("ix_checkout_sessions_token", "token"),
          Index("ix_checkout_sessions_status", "status"),
          Index("ix_checkout_sessions_tenant_phone", "tenant_phone"),
          Index("ix_checkout_sessions_expires", "expires_at"),
      )
  ```

- [ ] **Step 2: Add 6 new columns to `CheckoutRecord`**

  In the same file, find the `CheckoutRecord` class. After `recorded_by = Column(...)` add:

  ```python
      biometric_removed    = Column(Boolean, default=False)
      room_condition_ok    = Column(Boolean, default=True)
      deductions           = Column(Numeric(12, 2), default=0)
      deduction_reason     = Column(Text, nullable=True)
      refund_mode          = Column(String(10), nullable=True)
      checkout_session_id  = Column(Integer, ForeignKey("checkout_sessions.id"), nullable=True)
  ```

  Also add `CheckoutSession` to the import block at top of `models.py` (it's defined in the same file so no import needed — just ensure `CheckoutSession` appears BEFORE `CheckoutRecord` in the file, so the FK reference resolves).

- [ ] **Step 3: Export `CheckoutSession` and `CheckoutSessionStatus` everywhere `CheckoutRecord` is used**

  Search for every file that imports from `src.database.models` and imports `CheckoutRecord` — add `CheckoutSession, CheckoutSessionStatus` to those imports where needed later. For now just note the pattern; actual import additions happen in later tasks.

- [ ] **Step 4: Commit**

  ```bash
  git add src/database/models.py
  git commit -m "feat(db): add CheckoutSession model + extend CheckoutRecord with 6 new columns"
  ```

---

## Task 2: DB Migration

**Files:**
- Modify: `src/database/migrate_all.py`

- [ ] **Step 1: Find the last migration function in the file**

  Open `src/database/migrate_all.py`. Find the last `async def _migrate_*` function and the list where all migrations are registered (usually at the bottom). Note the pattern used.

- [ ] **Step 2: Append `_migrate_checkout_sessions`**

  Add this function before the migration runner list:

  ```python
  async def _migrate_checkout_sessions(conn) -> None:
      """Create checkout_sessions table and extend checkout_records."""
      await conn.execute(text("""
          CREATE TABLE IF NOT EXISTS checkout_sessions (
              id                    SERIAL PRIMARY KEY,
              token                 VARCHAR(36) NOT NULL UNIQUE,
              status                VARCHAR(20) NOT NULL DEFAULT 'pending',
              created_by_phone      VARCHAR(20) NOT NULL,
              tenant_phone          VARCHAR(20) NOT NULL,
              tenancy_id            INTEGER NOT NULL REFERENCES tenancies(id),
              checkout_date         DATE NOT NULL,
              room_key_returned     BOOLEAN NOT NULL DEFAULT FALSE,
              wardrobe_key_returned BOOLEAN NOT NULL DEFAULT FALSE,
              biometric_removed     BOOLEAN NOT NULL DEFAULT FALSE,
              room_condition_ok     BOOLEAN NOT NULL DEFAULT TRUE,
              damage_notes          TEXT,
              security_deposit      NUMERIC(12, 2) NOT NULL DEFAULT 0,
              pending_dues          NUMERIC(12, 2) NOT NULL DEFAULT 0,
              deductions            NUMERIC(12, 2) NOT NULL DEFAULT 0,
              deduction_reason      TEXT,
              refund_amount         NUMERIC(12, 2) NOT NULL DEFAULT 0,
              refund_mode           VARCHAR(10) NOT NULL DEFAULT '',
              rejection_reason      TEXT,
              expires_at            TIMESTAMPTZ NOT NULL,
              confirmed_at          TIMESTAMPTZ,
              created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
          );
          CREATE INDEX IF NOT EXISTS ix_checkout_sessions_token
              ON checkout_sessions(token);
          CREATE INDEX IF NOT EXISTS ix_checkout_sessions_status
              ON checkout_sessions(status);
          CREATE INDEX IF NOT EXISTS ix_checkout_sessions_tenant_phone
              ON checkout_sessions(tenant_phone);
          CREATE INDEX IF NOT EXISTS ix_checkout_sessions_expires
              ON checkout_sessions(expires_at);
      """))
      await conn.execute(text("""
          ALTER TABLE checkout_records
              ADD COLUMN IF NOT EXISTS biometric_removed   BOOLEAN DEFAULT FALSE,
              ADD COLUMN IF NOT EXISTS room_condition_ok   BOOLEAN DEFAULT TRUE,
              ADD COLUMN IF NOT EXISTS deductions          NUMERIC(12, 2) DEFAULT 0,
              ADD COLUMN IF NOT EXISTS deduction_reason    TEXT,
              ADD COLUMN IF NOT EXISTS refund_mode         VARCHAR(10),
              ADD COLUMN IF NOT EXISTS checkout_session_id INTEGER
                  REFERENCES checkout_sessions(id);
      """))
  ```

- [ ] **Step 3: Register the migration**

  Find the list/tuple of migrations (looks like `MIGRATIONS = [...]` or similar). Append `_migrate_checkout_sessions` to it.

- [ ] **Step 4: Run the migration locally**

  ```bash
  venv/Scripts/python -m src.database.migrate_all
  ```

  Expected output: migration runs without error. Run again — expected: idempotent (no error, no duplicate columns).

- [ ] **Step 5: Commit**

  ```bash
  git add src/database/migrate_all.py
  git commit -m "feat(db): migration — checkout_sessions table + extend checkout_records"
  ```

---

## Task 3: Extract `_do_confirm_checkout()` shared helper

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py`

This is the core shared function. It writes DB + Sheet. Called by: WhatsApp CHECKOUT_AGREE handler, APScheduler auto-confirm job.

- [ ] **Step 1: Write the failing test**

  Create `tests/test_checkout_flow.py`:

  ```python
  """Tests for checkout confirm helper and WhatsApp YES/NO flow."""
  import pytest
  from decimal import Decimal
  from datetime import date, datetime, timedelta
  from unittest.mock import AsyncMock, patch, MagicMock


  @pytest.mark.asyncio
  async def test_do_confirm_checkout_writes_checkout_record(db_session, sample_tenancy):
      """_do_confirm_checkout writes CheckoutRecord with all new fields."""
      from src.whatsapp.handlers.owner_handler import _do_confirm_checkout
      from src.database.models import CheckoutRecord, CheckoutSession, CheckoutSessionStatus

      cs = CheckoutSession(
          token="test-token-001",
          status=CheckoutSessionStatus.confirmed,
          created_by_phone="9444296681",
          tenant_phone="9876543210",
          tenancy_id=sample_tenancy.id,
          checkout_date=date.today(),
          room_key_returned=True,
          wardrobe_key_returned=True,
          biometric_removed=False,
          room_condition_ok=True,
          damage_notes=None,
          security_deposit=Decimal("15000"),
          pending_dues=Decimal("0"),
          deductions=Decimal("2000"),
          deduction_reason="paint damage",
          refund_amount=Decimal("13000"),
          refund_mode="upi",
          expires_at=datetime.utcnow() + timedelta(hours=2),
      )
      db_session.add(cs)
      await db_session.flush()

      with patch("src.integrations.gsheets.record_checkout", new_callable=AsyncMock) as mock_gs:
          mock_gs.return_value = {"success": True}
          msg = await _do_confirm_checkout(cs, db_session)

      from sqlalchemy import select
      from src.database.models import CheckoutRecord
      cr = await db_session.scalar(
          select(CheckoutRecord).where(CheckoutRecord.tenancy_id == sample_tenancy.id)
      )
      assert cr is not None
      assert cr.room_key_returned is True  # formerly main_key_returned
      assert cr.wardrobe_key_returned is True  # formerly cupboard_key_returned
      assert cr.biometric_removed is False
      assert cr.deductions == Decimal("2000")
      assert cr.deduction_reason == "paint damage"
      assert cr.refund_mode == "upi"
      assert cr.deposit_refunded_amount == Decimal("13000")
      assert "confirmed" in msg.lower() or "checkout" in msg.lower()
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_flow.py::test_do_confirm_checkout_writes_checkout_record -v
  ```

  Expected: `FAILED` — `ImportError: cannot import name '_do_confirm_checkout'`

- [ ] **Step 3: Implement `_do_confirm_checkout()` in owner_handler.py**

  Find the `confirm_checkout` step handler (around line 1565). Add this function BEFORE the `resolve_pending_action` function (i.e., as a standalone async function in the module):

  ```python
  async def _do_confirm_checkout(
      cs: "CheckoutSession",
      session: AsyncSession,
  ) -> str:
      """
      Final checkout execution: write CheckoutRecord + Refund, mark tenancy exited,
      sync Sheet. Returns a human-readable confirmation string.
      Does NOT send WhatsApp — the caller is responsible for that.
      """
      from src.database.models import CheckoutSession  # avoid circular at module level

      tenancy = await session.get(Tenancy, cs.tenancy_id)
      tenant_name = ""
      room_number = ""
      notice_str = None

      if tenancy:
          tenancy.status = TenancyStatus.exited
          tenancy.checkout_date = cs.checkout_date
          tenant = await session.get(Tenant, tenancy.tenant_id)
          tenant_name = tenant.name if tenant else ""
          room = await session.get(Room, tenancy.room_id)
          room_number = room.room_number if room else ""
          if tenancy.notice_date:
              notice_str = tenancy.notice_date.strftime("%d/%m/%Y")

      # Upsert CheckoutRecord (may already exist from old WhatsApp flow)
      from sqlalchemy import select as _select
      existing = await session.scalar(
          _select(CheckoutRecord).where(CheckoutRecord.tenancy_id == cs.tenancy_id)
      )
      cr = existing or CheckoutRecord(tenancy_id=cs.tenancy_id)
      cr.main_key_returned        = cs.room_key_returned
      cr.cupboard_key_returned    = cs.wardrobe_key_returned
      cr.biometric_removed        = cs.biometric_removed
      cr.room_condition_ok        = cs.room_condition_ok
      cr.damage_notes             = cs.damage_notes or None
      cr.pending_dues_amount      = cs.pending_dues
      cr.deposit_refunded_amount  = cs.refund_amount
      cr.deposit_refund_date      = cs.checkout_date if cs.refund_amount > 0 else None
      cr.actual_exit_date         = cs.checkout_date
      cr.recorded_by              = cs.created_by_phone
      cr.deductions               = cs.deductions
      cr.deduction_reason         = cs.deduction_reason
      cr.refund_mode              = cs.refund_mode
      cr.checkout_session_id      = cs.id
      if not existing:
          session.add(cr)

      # Refund record
      session.add(Refund(
          tenancy_id  = cs.tenancy_id,
          amount      = Decimal(str(cs.refund_amount)),
          refund_date = cs.checkout_date if cs.refund_amount > 0 else None,
          reason      = cs.deduction_reason or "checkout refund",
          status      = RefundStatus.pending if cs.refund_amount > 0 else RefundStatus.cancelled,
          notes       = f"Web checkout session {cs.token}",
      ))

      # Mark session as confirmed / auto_confirmed (caller sets before calling us)
      cs.confirmed_at = datetime.utcnow()
      await session.flush()

      # Google Sheet sync
      try:
          from src.integrations.gsheets import record_checkout as _gs_checkout
          await _gs_checkout(
              room_number,
              tenant_name,
              notice_str,
              cs.checkout_date.strftime("%d/%m/%Y"),
          )
      except Exception as _e:
          logger.warning("Sheet sync failed on checkout confirm: %s", _e)

      refund_line = (
          f"Refund: Rs.{int(cs.refund_amount):,} via {cs.refund_mode}"
          if cs.refund_amount > 0
          else "No refund."
      )
      return (
          f"Checkout confirmed — {tenant_name}, Room {room_number}\n"
          f"Exit: {cs.checkout_date.strftime('%d %b %Y')}\n"
          f"{refund_line}"
      )
  ```

  Also add `CheckoutSession` to the import from `src.database.models` at the top of owner_handler.py:

  ```python
  from src.database.models import (
      ActivityLog, ActivityLogType,
      AuthorizedUser, CheckoutRecord, CheckoutSession, Complaint, ...  # add CheckoutSession here
  )
  ```

- [ ] **Step 4: Run test to verify it passes**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_flow.py::test_do_confirm_checkout_writes_checkout_record -v
  ```

  Expected: `PASSED`

- [ ] **Step 5: Commit**

  ```bash
  git add src/whatsapp/handlers/owner_handler.py tests/test_checkout_flow.py
  git commit -m "feat(checkout): extract _do_confirm_checkout() shared helper"
  ```

---

## Task 4: checkout_router.py — tenant search + pre-fetch

**Files:**
- Create: `src/api/checkout_router.py`
- Create (partial): `tests/test_checkout_router.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/test_checkout_router.py`:

  ```python
  """Tests for checkout API endpoints."""
  import pytest
  from httpx import AsyncClient


  @pytest.mark.asyncio
  async def test_tenant_search_returns_active_tenants(async_client: AsyncClient):
      """GET /api/checkout/tenants?q=Ravi returns matching active tenants."""
      resp = await async_client.get(
          "/api/checkout/tenants",
          params={"q": "Ravi"},
          headers={"X-Admin-Pin": "cozeevo2026"},
      )
      assert resp.status_code == 200
      data = resp.json()
      assert isinstance(data, list)
      # Each result has required fields
      if data:
          assert "tenancy_id" in data[0]
          assert "label" in data[0]   # "Ravi Kumar (Room 305)"
          assert "phone" in data[0]


  @pytest.mark.asyncio
  async def test_tenant_prefetch_returns_financial_data(async_client: AsyncClient, sample_tenancy):
      """GET /api/checkout/tenant/{tenancy_id} returns deposit, dues, notice."""
      resp = await async_client.get(
          f"/api/checkout/tenant/{sample_tenancy.id}",
          headers={"X-Admin-Pin": "cozeevo2026"},
      )
      assert resp.status_code == 200
      data = resp.json()
      assert "security_deposit" in data
      assert "pending_dues" in data
      assert "notice_date" in data      # may be null
      assert "tenant_name" in data
      assert "room_number" in data
      assert "tenant_phone" in data
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_router.py -v
  ```

  Expected: `FAILED` — `404 Not Found` (router not registered yet)

- [ ] **Step 3: Create checkout_router.py with tenant search + pre-fetch**

  Create `src/api/checkout_router.py`:

  ```python
  """
  src/api/checkout_router.py
  Checkout form API — receptionist creates session, tenant confirms via WhatsApp.
  """
  from __future__ import annotations

  import os
  import uuid
  from collections import defaultdict
  from datetime import datetime, timedelta, date
  from decimal import Decimal
  from typing import Optional

  from fastapi import APIRouter, HTTPException, Request
  from pydantic import BaseModel
  from sqlalchemy import select, and_
  from sqlalchemy.ext.asyncio import AsyncSession

  from src.database.db_manager import get_session
  from src.database.models import (
      CheckoutSession, CheckoutSessionStatus,
      Tenancy, TenancyStatus, Tenant, Room, RentSchedule, RentStatus,
  )
  from src.api.onboarding_router import _check_admin_pin, _rate_check

  router = APIRouter(prefix="/api/checkout", tags=["checkout"])

  SESSION_TTL_HOURS = 2


  # ── Pydantic models ──────────────────────────────────────────────────────────

  class CreateCheckoutRequest(BaseModel):
      tenancy_id: int
      checkout_date: str          # ISO YYYY-MM-DD
      room_key_returned: bool
      wardrobe_key_returned: bool
      biometric_removed: bool
      room_condition_ok: bool
      damage_notes: str = ""
      security_deposit: float
      pending_dues: float
      deductions: float
      deduction_reason: str = ""
      refund_amount: float
      refund_mode: str            # cash / upi / bank
      created_by_phone: str = ""


  # ── Helpers ──────────────────────────────────────────────────────────────────

  async def _get_pending_dues(tenancy_id: int, session: AsyncSession) -> Decimal:
      """Sum of unpaid rent + maintenance for a tenancy."""
      from src.whatsapp.handlers.account_handler import _calc_outstanding_dues
      o_rent, o_maint = await _calc_outstanding_dues(tenancy_id, session)
      return o_rent + o_maint


  # ── Endpoints ────────────────────────────────────────────────────────────────

  @router.get("/tenants")
  async def search_tenants(q: str, request: Request):
      """Autocomplete: active tenants matching name or room number."""
      _check_admin_pin(request)
      _rate_check(f"co_search:{request.client.host}", 60, 60)
      async with get_session() as session:
          stmt = (
              select(Tenancy, Tenant, Room)
              .join(Tenant, Tenancy.tenant_id == Tenant.id)
              .join(Room, Tenancy.room_id == Room.id)
              .where(
                  Tenancy.status == TenancyStatus.active,
                  Tenant.name.ilike(f"%{q}%") | Room.room_number.ilike(f"%{q}%"),
              )
              .limit(10)
          )
          rows = (await session.execute(stmt)).all()
          return [
              {
                  "tenancy_id": t.id,
                  "label": f"{tn.name} (Room {r.room_number})",
                  "tenant_name": tn.name,
                  "phone": tn.phone,
                  "room_number": r.room_number,
              }
              for t, tn, r in rows
          ]


  @router.get("/tenant/{tenancy_id}")
  async def prefetch_tenancy(tenancy_id: int, request: Request):
      """Pre-fill: fetch deposit, pending dues, notice date for a tenancy."""
      _check_admin_pin(request)
      async with get_session() as session:
          tenancy = await session.get(Tenancy, tenancy_id)
          if not tenancy or tenancy.status != TenancyStatus.active:
              raise HTTPException(404, "Active tenancy not found")
          tenant = await session.get(Tenant, tenancy.tenant_id)
          room = await session.get(Room, tenancy.room_id)
          dues = await _get_pending_dues(tenancy_id, session)
          return {
              "tenancy_id": tenancy_id,
              "tenant_name": tenant.name if tenant else "",
              "phone": tenant.phone if tenant else "",
              "room_number": room.room_number if room else "",
              "security_deposit": float(tenancy.security_deposit or 0),
              "pending_dues": float(dues),
              "notice_date": tenancy.notice_date.isoformat() if tenancy.notice_date else None,
          }
  ```

- [ ] **Step 4: Register router in main.py (temporarily for tests)**

  Open `main.py`. After the line `from src.api.onboarding_router import router as onboarding_router`, add:

  ```python
  from src.api.checkout_router import router as checkout_router
  app.include_router(checkout_router)
  ```

  Also in `LocalOnlyMiddleware.dispatch`, add to the allowed-paths block:

  ```python
  or path.startswith("/admin/checkout")    # admin checkout panel
  or path.startswith("/api/checkout")      # all checkout API endpoints
  ```

- [ ] **Step 5: Run tests to verify they pass**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_router.py::test_tenant_search_returns_active_tenants tests/test_checkout_router.py::test_tenant_prefetch_returns_financial_data -v
  ```

  Expected: `PASSED`

- [ ] **Step 6: Commit**

  ```bash
  git add src/api/checkout_router.py tests/test_checkout_router.py main.py
  git commit -m "feat(checkout): tenant search + pre-fetch API endpoints"
  ```

---

## Task 5: checkout_router.py — session create + WhatsApp send

**Files:**
- Modify: `src/api/checkout_router.py`
- Modify: `tests/test_checkout_router.py`

- [ ] **Step 1: Write failing test**

  Add to `tests/test_checkout_router.py`:

  ```python
  @pytest.mark.asyncio
  async def test_create_checkout_session(async_client: AsyncClient, sample_tenancy, mock_send_whatsapp):
      """POST /api/checkout/create creates CheckoutSession and sends WhatsApp to tenant."""
      from datetime import date
      resp = await async_client.post(
          "/api/checkout/create",
          json={
              "tenancy_id": sample_tenancy.id,
              "checkout_date": date.today().isoformat(),
              "room_key_returned": True,
              "wardrobe_key_returned": True,
              "biometric_removed": False,
              "room_condition_ok": True,
              "damage_notes": "",
              "security_deposit": 15000.0,
              "pending_dues": 0.0,
              "deductions": 2000.0,
              "deduction_reason": "paint damage",
              "refund_amount": 13000.0,
              "refund_mode": "upi",
              "created_by_phone": "9444296681",
          },
          headers={"X-Admin-Pin": "cozeevo2026"},
      )
      assert resp.status_code == 200
      data = resp.json()
      assert data["status"] == "pending"
      assert "token" in data
      assert mock_send_whatsapp.called   # WhatsApp sent to tenant
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_router.py::test_create_checkout_session -v
  ```

  Expected: `FAILED` — endpoint doesn't exist yet

- [ ] **Step 3: Add `POST /api/checkout/create` to checkout_router.py**

  Add to `src/api/checkout_router.py`:

  ```python
  @router.post("/create")
  async def create_checkout_session(req: CreateCheckoutRequest, request: Request):
      """
      Receptionist submits checkout form. Creates CheckoutSession, sends WhatsApp to tenant.
      """
      _check_admin_pin(request)
      _rate_check(f"co_create:{request.client.host}", 10, 60)

      try:
          checkout_date = date.fromisoformat(req.checkout_date)
      except ValueError:
          raise HTTPException(400, "Invalid checkout_date format (use YYYY-MM-DD)")

      async with get_session() as session:
          tenancy = await session.get(Tenancy, req.tenancy_id)
          if not tenancy or tenancy.status != TenancyStatus.active:
              raise HTTPException(404, "Active tenancy not found")
          tenant = await session.get(Tenant, tenancy.tenant_id)
          if not tenant:
              raise HTTPException(404, "Tenant not found")
          room = await session.get(Room, tenancy.room_id)

          # Cancel any existing pending session for this tenancy
          existing = await session.scalar(
              select(CheckoutSession).where(
                  CheckoutSession.tenancy_id == req.tenancy_id,
                  CheckoutSession.status == CheckoutSessionStatus.pending,
              )
          )
          if existing:
              existing.status = CheckoutSessionStatus.cancelled

          cs = CheckoutSession(
              token                 = str(uuid.uuid4()),
              status                = CheckoutSessionStatus.pending,
              created_by_phone      = req.created_by_phone or "unknown",
              tenant_phone          = tenant.phone,
              tenancy_id            = req.tenancy_id,
              checkout_date         = checkout_date,
              room_key_returned     = req.room_key_returned,
              wardrobe_key_returned = req.wardrobe_key_returned,
              biometric_removed     = req.biometric_removed,
              room_condition_ok     = req.room_condition_ok,
              damage_notes          = req.damage_notes or None,
              security_deposit      = Decimal(str(req.security_deposit)),
              pending_dues          = Decimal(str(req.pending_dues)),
              deductions            = Decimal(str(req.deductions)),
              deduction_reason      = req.deduction_reason or None,
              refund_amount         = Decimal(str(req.refund_amount)),
              refund_mode           = req.refund_mode,
              expires_at            = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS),
          )
          session.add(cs)
          await session.flush()

          room_number = room.room_number if room else "?"
          key_line    = f"Room key: {'Returned' if cs.room_key_returned else 'Not returned'}"
          ward_line   = f"Wardrobe key: {'Returned' if cs.wardrobe_key_returned else 'Not returned'}"
          bio_line    = f"Biometric: {'Removed' if cs.biometric_removed else 'Not removed'}"
          room_line   = f"Room condition: {'OK' if cs.room_condition_ok else 'Damage noted'}"
          refund_line = f"Refund: Rs.{int(cs.refund_amount):,} via {cs.refund_mode}" if cs.refund_amount > 0 else "Refund: Rs.0"

          msg = (
              f"Hi {tenant.name}, your checkout from Room {room_number} "
              f"on {checkout_date.strftime('%d %b %Y')} has been recorded.\n\n"
              f"Summary:\n"
              f"- {key_line}\n"
              f"- {ward_line}\n"
              f"- {bio_line}\n"
              f"- {room_line}\n"
              f"- {refund_line}\n\n"
              f"Reply *YES* to confirm.\n"
              f"If you disagree, reply *NO* followed by your reason "
              f"(e.g. NO the damage charge is wrong).\n"
              f"If no response in 2 hours, this will be auto-confirmed."
          )

          # Send WhatsApp to tenant
          phone_wa = f"+91{tenant.phone}" if not tenant.phone.startswith("+") else tenant.phone
          try:
              from src.whatsapp.webhook_handler import _send_whatsapp
              await _send_whatsapp(phone_wa, msg, intent="CHECKOUT_REQUEST")
          except Exception as _e:
              logger.warning("WhatsApp send failed for checkout request: %s", _e)

          await session.commit()
          return {"status": "pending", "token": cs.token, "expires_at": cs.expires_at.isoformat()}
  ```

- [ ] **Step 4: Run test to verify it passes**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_router.py::test_create_checkout_session -v
  ```

  Expected: `PASSED`

- [ ] **Step 5: Commit**

  ```bash
  git add src/api/checkout_router.py tests/test_checkout_router.py
  git commit -m "feat(checkout): POST /api/checkout/create — create session + send WhatsApp to tenant"
  ```

---

## Task 6: checkout_router.py — status poll endpoint

**Files:**
- Modify: `src/api/checkout_router.py`

- [ ] **Step 1: Add `GET /api/checkout/status/{token}`**

  Add to `src/api/checkout_router.py`:

  ```python
  @router.get("/status/{token}")
  async def poll_session_status(token: str, request: Request):
      """Admin page polls this to know when tenant has responded."""
      _check_admin_pin(request)
      async with get_session() as session:
          cs = await session.scalar(
              select(CheckoutSession).where(CheckoutSession.token == token)
          )
          if not cs:
              raise HTTPException(404, "Session not found")
          return {
              "token": cs.token,
              "status": cs.status,
              "confirmed_at": cs.confirmed_at.isoformat() if cs.confirmed_at else None,
              "rejection_reason": cs.rejection_reason,
              "expires_at": cs.expires_at.isoformat(),
          }
  ```

- [ ] **Step 2: Run full router test suite**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_router.py -v
  ```

  Expected: all tests `PASSED`

- [ ] **Step 3: Commit**

  ```bash
  git add src/api/checkout_router.py
  git commit -m "feat(checkout): GET /api/checkout/status/{token} poll endpoint"
  ```

---

## Task 7: WhatsApp YES/NO intercept in chat_api.py

**Files:**
- Modify: `src/whatsapp/chat_api.py`

When a tenant with an active `CheckoutSession` replies YES or NO, intercept before intent detection and route to checkout handlers.

- [ ] **Step 1: Write failing test**

  Add to `tests/test_checkout_flow.py`:

  ```python
  @pytest.mark.asyncio
  async def test_tenant_yes_triggers_checkout_agree(
      async_client: AsyncClient, active_checkout_session, mock_send_whatsapp
  ):
      """Tenant replying YES with an active CheckoutSession triggers CHECKOUT_AGREE."""
      tenant_phone = active_checkout_session.tenant_phone
      resp = await async_client.post(
          "/api/whatsapp/process",
          json={"phone": tenant_phone, "message": "YES", "message_id": "test-msg-001"},
      )
      assert resp.status_code == 200
      data = resp.json()
      assert data["intent"] == "CHECKOUT_AGREE"


  @pytest.mark.asyncio
  async def test_tenant_no_without_reason_asks_for_reason(
      async_client: AsyncClient, active_checkout_session
  ):
      """Tenant replying NO without reason gets prompted to add a reason."""
      tenant_phone = active_checkout_session.tenant_phone
      resp = await async_client.post(
          "/api/whatsapp/process",
          json={"phone": tenant_phone, "message": "NO", "message_id": "test-msg-002"},
      )
      assert resp.status_code == 200
      data = resp.json()
      assert "reason" in data["reply"].lower()
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_flow.py::test_tenant_yes_triggers_checkout_agree tests/test_checkout_flow.py::test_tenant_no_without_reason_asks_for_reason -v
  ```

  Expected: `FAILED`

- [ ] **Step 3: Add checkout session intercept to chat_api.py**

  In `src/whatsapp/chat_api.py`, find the section labelled `# ── 3. Detect intent` (around line 517). Before that block, add:

  ```python
  # ── 2b. Checkout session intercept — tenant replying YES/NO ──────────────
  # Check BEFORE intent detection so YES/NO don't get mis-classified.
  _checkout_intercept_reply = None
  _co_msg = message.strip().upper()
  if ctx.role in ("tenant", "lead", "unknown"):   # tenants confirm checkouts
      _active_cs = await session.scalar(
          select(CheckoutSession).where(
              CheckoutSession.tenant_phone == phone,
              CheckoutSession.status == CheckoutSessionStatus.pending,
              CheckoutSession.expires_at > datetime.utcnow(),
          )
      )
      if _active_cs:
          if _co_msg == "YES":
              intent_result = IntentResult(intent="CHECKOUT_AGREE", confidence=1.0)
              intent = "CHECKOUT_AGREE"
          elif _co_msg.startswith("NO"):
              reason = message.strip()[2:].strip()
              if not reason:
                  reply = (
                      "Please provide a reason for rejection "
                      "(e.g. *NO the damage charge is wrong*)."
                  )
                  await _log(session, phone, message, ctx.role, "CHECKOUT_REJECT_NOOP", reply)
                  await session.commit()
                  return OutboundReply(reply=reply, intent="CHECKOUT_REJECT_NOOP", role=ctx.role)
              intent_result = IntentResult(
                  intent="CHECKOUT_REJECT", confidence=1.0, entities={"reason": reason}
              )
              intent = "CHECKOUT_REJECT"
  ```

  Also add to the imports at the top of `chat_api.py`:

  ```python
  from src.database.models import CheckoutSession, CheckoutSessionStatus
  from sqlalchemy import select
  ```

  (add `CheckoutSession, CheckoutSessionStatus` to the existing models import if already importing from there)

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_flow.py::test_tenant_yes_triggers_checkout_agree tests/test_checkout_flow.py::test_tenant_no_without_reason_asks_for_reason -v
  ```

  Expected: `PASSED`

- [ ] **Step 5: Commit**

  ```bash
  git add src/whatsapp/chat_api.py tests/test_checkout_flow.py
  git commit -m "feat(checkout): intercept YES/NO from tenants with active CheckoutSession"
  ```

---

## Task 8: CHECKOUT_AGREE + CHECKOUT_REJECT handlers

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py`
- Modify: `src/whatsapp/gatekeeper.py`

- [ ] **Step 1: Write failing tests**

  Add to `tests/test_checkout_flow.py`:

  ```python
  @pytest.mark.asyncio
  async def test_checkout_agree_confirms_and_sends_tenant_confirmation(
      db_session, active_checkout_session, mock_send_whatsapp
  ):
      """CHECKOUT_AGREE writes DB, syncs Sheet, sends confirmed message to tenant."""
      from src.whatsapp.handlers.owner_handler import _handle_checkout_agree
      from src.database.models import CheckoutRecord, TenancyStatus

      reply = await _handle_checkout_agree(
          active_checkout_session.tenant_phone, db_session
      )
      assert "confirmed" in reply.lower() or "checkout" in reply.lower()

      from sqlalchemy import select
      cr = await db_session.scalar(
          select(CheckoutRecord).where(
              CheckoutRecord.tenancy_id == active_checkout_session.tenancy_id
          )
      )
      assert cr is not None
      assert mock_send_whatsapp.called  # confirmed message sent to tenant


  @pytest.mark.asyncio
  async def test_checkout_reject_voids_session_notifies_receptionist(
      db_session, active_checkout_session, mock_send_whatsapp
  ):
      """CHECKOUT_REJECT marks session rejected, notifies receptionist."""
      from src.whatsapp.handlers.owner_handler import _handle_checkout_reject
      from src.database.models import CheckoutSessionStatus

      reply = await _handle_checkout_reject(
          active_checkout_session.tenant_phone, "damage charge is wrong", db_session
      )
      assert reply  # non-empty reply to tenant

      from sqlalchemy import select
      from src.database.models import CheckoutSession
      cs = await db_session.scalar(
          select(CheckoutSession).where(
              CheckoutSession.token == active_checkout_session.token
          )
      )
      assert cs.status == CheckoutSessionStatus.rejected
      assert cs.rejection_reason == "damage charge is wrong"
      assert mock_send_whatsapp.called  # receptionist notified
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_flow.py::test_checkout_agree_confirms_and_sends_tenant_confirmation tests/test_checkout_flow.py::test_checkout_reject_voids_session_notifies_receptionist -v
  ```

  Expected: `FAILED`

- [ ] **Step 3: Add handlers to owner_handler.py**

  Add after `_do_confirm_checkout`:

  ```python
  async def _handle_checkout_agree(tenant_phone: str, session: AsyncSession) -> str:
      """Tenant replied YES. Confirm checkout, write DB, send confirmed WA to tenant."""
      from sqlalchemy import select as _sel
      cs = await session.scalar(
          _sel(CheckoutSession).where(
              CheckoutSession.tenant_phone == tenant_phone,
              CheckoutSession.status == CheckoutSessionStatus.pending,
          )
      )
      if not cs:
          return "No pending checkout found. Please ask the receptionist to create a new one."

      cs.status = CheckoutSessionStatus.confirmed
      summary = await _do_confirm_checkout(cs, session)

      # Send checkout_confirmed to tenant
      phone_wa = f"+91{tenant_phone}" if not tenant_phone.startswith("+") else tenant_phone
      try:
          from src.whatsapp.webhook_handler import _send_whatsapp
          refund_line = (
              f"Refund of Rs.{int(cs.refund_amount):,} will be processed by receptionist now."
              if cs.refund_amount > 0
              else ""
          )
          confirmed_msg = (
              f"Your checkout from Room [Room] on "
              f"{cs.checkout_date.strftime('%d %b %Y')} is confirmed.\n"
              + (f"{refund_line}\n" if refund_line else "")
              + "Thank you for staying with Cozeevo."
          )
          # Fill actual room number from summary
          tenancy = await session.get(Tenancy, cs.tenancy_id)
          if tenancy:
              room = await session.get(Room, tenancy.room_id)
              if room:
                  confirmed_msg = confirmed_msg.replace("[Room]", room.room_number)
          await _send_whatsapp(phone_wa, confirmed_msg, intent="CHECKOUT_CONFIRMED")
      except Exception as _e:
          logger.warning("Failed to send checkout_confirmed to tenant: %s", _e)

      # Notify receptionist
      try:
          from src.whatsapp.webhook_handler import _send_whatsapp
          recep_phone = f"+91{cs.created_by_phone}" if not cs.created_by_phone.startswith("+") else cs.created_by_phone
          await _send_whatsapp(recep_phone, summary, intent="CHECKOUT_CONFIRMED")
      except Exception as _e:
          logger.warning("Failed to notify receptionist on checkout confirm: %s", _e)

      return summary


  async def _handle_checkout_reject(
      tenant_phone: str, reason: str, session: AsyncSession
  ) -> str:
      """Tenant replied NO + reason. Void session, notify receptionist."""
      from sqlalchemy import select as _sel
      cs = await session.scalar(
          _sel(CheckoutSession).where(
              CheckoutSession.tenant_phone == tenant_phone,
              CheckoutSession.status == CheckoutSessionStatus.pending,
          )
      )
      if not cs:
          return "No pending checkout found."

      cs.status = CheckoutSessionStatus.rejected
      cs.rejection_reason = reason

      # Notify receptionist
      try:
          from src.whatsapp.webhook_handler import _send_whatsapp
          tenancy = await session.get(Tenancy, cs.tenancy_id)
          tenant  = await session.get(Tenant, tenancy.tenant_id) if tenancy else None
          tenant_name = tenant.name if tenant else "Tenant"
          room    = await session.get(Room, tenancy.room_id) if tenancy else None
          room_no = room.room_number if room else "?"
          recep_phone = f"+91{cs.created_by_phone}" if not cs.created_by_phone.startswith("+") else cs.created_by_phone
          notif = (
              f"{tenant_name} (Room {room_no}) rejected the checkout.\n"
              f"Reason: {reason}\n"
              f"Please resolve and create a new checkout session."
          )
          await _send_whatsapp(recep_phone, notif, intent="CHECKOUT_REJECTED")
      except Exception as _e:
          logger.warning("Failed to notify receptionist on checkout rejection: %s", _e)

      return (
          "Understood. Your feedback has been sent to the receptionist. "
          "They will contact you to resolve this."
      )
  ```

  Also add `CheckoutSessionStatus` to the models import at top of owner_handler.py.

- [ ] **Step 4: Wire handlers in gatekeeper.py**

  Open `src/whatsapp/gatekeeper.py`. Find the owner/admin intent routing block. Add:

  ```python
  if intent == "CHECKOUT_AGREE":
      from src.whatsapp.handlers.owner_handler import _handle_checkout_agree
      return await _handle_checkout_agree(ctx.phone, session)

  if intent == "CHECKOUT_REJECT":
      reason = entities.get("reason", "")
      from src.whatsapp.handlers.owner_handler import _handle_checkout_reject
      return await _handle_checkout_reject(ctx.phone, reason, session)
  ```

  These intents come from ALL roles (tenant replies YES/NO), so add them at the top of `route()` before role checks.

- [ ] **Step 5: Run tests**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_flow.py -v
  ```

  Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

  ```bash
  git add src/whatsapp/handlers/owner_handler.py src/whatsapp/gatekeeper.py tests/test_checkout_flow.py
  git commit -m "feat(checkout): CHECKOUT_AGREE + CHECKOUT_REJECT handlers"
  ```

---

## Task 9: APScheduler auto-confirm job

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: Add `_auto_confirm_checkout_sessions` job function**

  In `src/scheduler.py`, add the async job function near the other job functions:

  ```python
  async def _auto_confirm_checkout_sessions() -> None:
      """
      Every 15 minutes: find pending CheckoutSessions whose 2-hr window has expired.
      Auto-confirm each one — write DB, sync Sheet, send WhatsApp to tenant and receptionist.
      """
      from sqlalchemy import select
      from src.database.db_manager import get_session
      from src.database.models import CheckoutSession, CheckoutSessionStatus
      from datetime import datetime

      async with get_session() as session:
          expired_sessions = (await session.execute(
              select(CheckoutSession).where(
                  CheckoutSession.status == CheckoutSessionStatus.pending,
                  CheckoutSession.expires_at <= datetime.utcnow(),
              )
          )).scalars().all()

          for cs in expired_sessions:
              try:
                  cs.status = CheckoutSessionStatus.auto_confirmed
                  from src.whatsapp.handlers.owner_handler import _do_confirm_checkout
                  summary = await _do_confirm_checkout(cs, session)

                  from src.database.models import Tenancy, Tenant, Room
                  tenancy = await session.get(Tenancy, cs.tenancy_id)
                  tenant  = await session.get(Tenant, tenancy.tenant_id) if tenancy else None
                  room    = await session.get(Room, tenancy.room_id) if tenancy else None
                  room_no = room.room_number if room else "?"

                  from src.whatsapp.webhook_handler import _send_whatsapp
                  tenant_phone = f"+91{cs.tenant_phone}" if not cs.tenant_phone.startswith("+") else cs.tenant_phone
                  refund_line = (
                      f"Refund of Rs.{int(cs.refund_amount):,} will be processed by receptionist now."
                      if cs.refund_amount > 0 else ""
                  )
                  confirmed_msg = (
                      f"Your checkout from Room {room_no} on "
                      f"{cs.checkout_date.strftime('%d %b %Y')} is confirmed.\n"
                      + (f"{refund_line}\n" if refund_line else "")
                      + "Thank you for staying with Cozeevo."
                  )
                  await _send_whatsapp(tenant_phone, confirmed_msg, intent="CHECKOUT_AUTO_CONFIRMED")

                  recep_phone = f"+91{cs.created_by_phone}" if not cs.created_by_phone.startswith("+") else cs.created_by_phone
                  await _send_whatsapp(recep_phone, f"[Auto-confirmed] {summary}", intent="CHECKOUT_AUTO_CONFIRMED")

                  await session.commit()
                  logger.info("Auto-confirmed checkout session %s", cs.token)
              except Exception as _e:
                  logger.error("Auto-confirm failed for session %s: %s", cs.token, _e)
                  await session.rollback()
  ```

- [ ] **Step 2: Register the job in `start_scheduler()`**

  In `start_scheduler()`, after the last `scheduler.add_job(...)` call, add:

  ```python
  from apscheduler.triggers.interval import IntervalTrigger

  scheduler.add_job(
      _auto_confirm_checkout_sessions,
      trigger=IntervalTrigger(minutes=15),
      id="checkout_auto_confirm",
      name="Checkout auto-confirm — expired 2hr sessions",
      replace_existing=True,
  )
  ```

- [ ] **Step 3: Smoke-test by starting the server**

  ```bash
  venv/Scripts/python main.py
  ```

  Expected: Server starts, scheduler starts, log shows `checkout_auto_confirm` job registered. No errors.

- [ ] **Step 4: Commit**

  ```bash
  git add src/scheduler.py
  git commit -m "feat(checkout): APScheduler auto-confirm job — 15min interval"
  ```

---

## Task 10: checkout_admin.html — 3-step receptionist form

**Files:**
- Create: `static/checkout_admin.html`

- [ ] **Step 1: Create `static/checkout_admin.html`**

  Create the file with the 3-step wizard. Full content:

  ```html
  <!DOCTYPE html>
  <html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Checkout — Cozeevo Admin</title>
    <style>
      :root { --pink: #EF1F9C; --blue: #00AEED; --bg: #0f0f1a; --card: #1a1a2e; --text: #e0e0e0; --muted: #888; }
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; min-height: 100vh; }

      /* Nav */
      nav { background: var(--card); padding: 14px 24px; display: flex; align-items: center; gap: 24px; border-bottom: 1px solid #2a2a40; }
      nav .brand { color: var(--pink); font-weight: 700; font-size: 16px; text-decoration: none; }
      nav a { color: var(--muted); text-decoration: none; font-size: 14px; padding: 6px 12px; border-radius: 6px; }
      nav a.active, nav a:hover { background: rgba(239,31,156,0.12); color: var(--pink); }

      /* Layout */
      .page { max-width: 680px; margin: 40px auto; padding: 0 20px; }
      h1 { font-size: 22px; margin-bottom: 8px; }
      .subtitle { color: var(--muted); font-size: 14px; margin-bottom: 28px; }

      /* Progress */
      .progress { display: flex; gap: 8px; margin-bottom: 32px; }
      .step-dot { flex: 1; height: 4px; border-radius: 2px; background: #2a2a40; transition: background .3s; }
      .step-dot.active { background: var(--pink); }
      .step-dot.done { background: var(--blue); }

      /* Card */
      .card { background: var(--card); border-radius: 12px; padding: 28px; margin-bottom: 20px; }
      .card h2 { font-size: 16px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 20px; }

      /* Form */
      .field { margin-bottom: 18px; }
      label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }
      input, select, textarea { width: 100%; background: #0d0d1a; border: 1px solid #2a2a40; border-radius: 8px; color: var(--text); padding: 10px 14px; font-size: 14px; outline: none; }
      input:focus, select:focus { border-color: var(--pink); }
      textarea { resize: vertical; min-height: 72px; }
      .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }

      /* Toggles */
      .toggle-group { display: flex; gap: 10px; }
      .toggle-btn { flex: 1; padding: 10px; border-radius: 8px; border: 1px solid #2a2a40; background: #0d0d1a; color: var(--muted); cursor: pointer; font-size: 14px; text-align: center; transition: all .2s; }
      .toggle-btn.yes.selected { background: rgba(74,222,128,.15); border-color: #4ade80; color: #4ade80; }
      .toggle-btn.no.selected  { background: rgba(239,68,68,.15);  border-color: #ef4444; color: #ef4444; }
      .toggle-btn.ok.selected  { background: rgba(74,222,128,.15); border-color: #4ade80; color: #4ade80; }

      /* Autocomplete */
      .autocomplete { position: relative; }
      .suggestions { position: absolute; top: 100%; left: 0; right: 0; background: var(--card); border: 1px solid #2a2a40; border-radius: 8px; z-index: 100; max-height: 200px; overflow-y: auto; }
      .suggestion-item { padding: 10px 14px; cursor: pointer; font-size: 14px; }
      .suggestion-item:hover { background: rgba(239,31,156,.1); }

      /* Settlement */
      .settlement { background: #0d0d1a; border-radius: 8px; padding: 16px; margin-bottom: 18px; }
      .settlement-row { display: flex; justify-content: space-between; padding: 5px 0; font-size: 14px; }
      .settlement-row.total { border-top: 1px solid #2a2a40; margin-top: 8px; padding-top: 10px; font-weight: 600; color: #4ade80; }

      /* Buttons */
      .btn-primary { width: 100%; background: var(--pink); border: none; color: white; padding: 14px; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; margin-top: 8px; }
      .btn-primary:hover { opacity: .9; }
      .btn-back { background: none; border: 1px solid #2a2a40; color: var(--muted); padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; margin-right: 10px; }

      /* Status */
      .status-box { background: var(--card); border-radius: 12px; padding: 28px; text-align: center; display: none; }
      .status-icon { font-size: 48px; margin-bottom: 16px; }
      .status-title { font-size: 20px; font-weight: 600; margin-bottom: 8px; }
      .status-sub { color: var(--muted); font-size: 14px; }
      .badge { display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-top: 12px; }
      .badge.pending  { background: rgba(251,191,36,.15); color: #fbbf24; }
      .badge.confirmed { background: rgba(74,222,128,.15); color: #4ade80; }
      .badge.auto_confirmed { background: rgba(0,174,237,.15); color: var(--blue); }
      .badge.rejected { background: rgba(239,68,68,.15); color: #ef4444; }
      .hidden { display: none !important; }

      select option { background: #1a1a2e; }
    </style>
  </head>
  <body>

  <nav>
    <a href="/admin/onboarding" class="brand">Cozeevo Admin</a>
    <a href="/admin/onboarding">Check-in</a>
    <a href="/admin/checkout" class="active">Checkout</a>
  </nav>

  <div class="page">
    <h1>Checkout Form</h1>
    <p class="subtitle">Fill all details. Tenant will receive a WhatsApp summary to confirm.</p>

    <div class="progress">
      <div class="step-dot active" id="dot1"></div>
      <div class="step-dot" id="dot2"></div>
      <div class="step-dot" id="dot3"></div>
    </div>

    <!-- Step 1: Tenant + Date -->
    <div id="step1">
      <div class="card">
        <h2>Step 1 — Tenant &amp; Date</h2>
        <div class="field autocomplete">
          <label>Tenant</label>
          <input type="text" id="tenantSearch" placeholder="Search by name or room…" autocomplete="off">
          <div class="suggestions" id="suggestions" style="display:none"></div>
          <input type="hidden" id="tenancyId">
          <input type="hidden" id="tenantPhone">
        </div>
        <div class="field">
          <label>Checkout Date</label>
          <input type="date" id="checkoutDate">
        </div>
      </div>
      <button class="btn-primary" onclick="goStep2()">Next: Physical Handover →</button>
    </div>

    <!-- Step 2: Physical Handover -->
    <div id="step2" class="hidden">
      <div class="card">
        <h2>Step 2 — Physical Handover</h2>
        <div class="field">
          <label>Room Key Returned</label>
          <div class="toggle-group">
            <button class="toggle-btn yes" data-field="roomKey" data-val="true" onclick="setToggle(this)">Yes</button>
            <button class="toggle-btn no"  data-field="roomKey" data-val="false" onclick="setToggle(this)">No</button>
          </div>
        </div>
        <div class="field">
          <label>Wardrobe Key Returned</label>
          <div class="toggle-group">
            <button class="toggle-btn yes" data-field="wardrobeKey" data-val="true" onclick="setToggle(this)">Yes</button>
            <button class="toggle-btn no"  data-field="wardrobeKey" data-val="false" onclick="setToggle(this)">No</button>
          </div>
        </div>
        <div class="field">
          <label>Biometric Removed</label>
          <div class="toggle-group">
            <button class="toggle-btn yes" data-field="biometric" data-val="true" onclick="setToggle(this)">Yes</button>
            <button class="toggle-btn no"  data-field="biometric" data-val="false" onclick="setToggle(this)">No</button>
          </div>
        </div>
        <div class="field">
          <label>Room Condition</label>
          <div class="toggle-group">
            <button class="toggle-btn ok yes" data-field="roomCondition" data-val="true" onclick="setToggle(this)">OK</button>
            <button class="toggle-btn no"     data-field="roomCondition" data-val="false" onclick="setToggle(this)">Not OK</button>
          </div>
        </div>
        <div class="field" id="damageField" style="display:none">
          <label>Damage Notes *</label>
          <textarea id="damageNotes" placeholder="Describe the damage…"></textarea>
        </div>
      </div>
      <button class="btn-back" onclick="goStep1()">← Back</button>
      <button class="btn-primary" style="width:auto;display:inline-block;padding:14px 32px" onclick="goStep3()">Next: Settlement →</button>
    </div>

    <!-- Step 3: Financial Settlement -->
    <div id="step3" class="hidden">
      <div class="card">
        <h2>Step 3 — Financial Settlement</h2>
        <div class="row2">
          <div class="field">
            <label>Security Deposit (₹)</label>
            <input type="number" id="deposit" oninput="calcRefund()">
          </div>
          <div class="field">
            <label>Pending Dues (₹)</label>
            <input type="number" id="pendingDues" oninput="calcRefund()">
          </div>
        </div>
        <div class="row2">
          <div class="field">
            <label>Deductions (₹)</label>
            <input type="number" id="deductions" value="0" oninput="calcRefund()">
          </div>
          <div class="field">
            <label>Refund Mode</label>
            <select id="refundMode">
              <option value="">Select…</option>
              <option value="cash">Cash</option>
              <option value="upi">UPI</option>
              <option value="bank">Bank Transfer</option>
            </select>
          </div>
        </div>
        <div class="field" id="deductionReasonField" style="display:none">
          <label>Deduction Reason *</label>
          <input type="text" id="deductionReason" placeholder="e.g. paint damage, no notice given">
        </div>
        <div class="field">
          <label>Refund Amount (₹) — editable</label>
          <input type="number" id="refundAmount" oninput="refundOverridden = true">
        </div>
        <div class="settlement">
          <div class="settlement-row"><span>Security Deposit</span><span id="s_deposit">₹0</span></div>
          <div class="settlement-row"><span>Pending Dues</span><span id="s_dues" style="color:#ef4444">- ₹0</span></div>
          <div class="settlement-row"><span>Deductions</span><span id="s_deductions" style="color:#ef4444">- ₹0</span></div>
          <div class="settlement-row total"><span>Refund</span><span id="s_refund">₹0</span></div>
        </div>
      </div>
      <button class="btn-back" onclick="goStep2()">← Back</button>
      <button class="btn-primary" style="width:auto;display:inline-block;padding:14px 32px" onclick="submitForm()">Send to Tenant →</button>
    </div>

    <!-- Status box (shown after submit) -->
    <div class="status-box" id="statusBox">
      <div class="status-icon">📋</div>
      <div class="status-title" id="statusTitle">Sent to Tenant</div>
      <div class="status-sub" id="statusSub">Waiting for confirmation…</div>
      <div class="badge pending" id="statusBadge">PENDING</div>
      <br><br>
      <button class="btn-primary" onclick="resetForm()">New Checkout</button>
    </div>
  </div>

  <script>
  const PIN = 'cozeevo2026';
  let state = { tenancyId: null, tenantPhone: '', toggles: {}, sessionToken: null };
  let refundOverridden = false;
  let pollInterval = null;

  // Set today as default date
  document.getElementById('checkoutDate').value = new Date().toISOString().split('T')[0];

  // ── Autocomplete ──────────────────────────────────────────────────────────
  let searchTimer = null;
  document.getElementById('tenantSearch').addEventListener('input', e => {
    clearTimeout(searchTimer);
    const q = e.target.value.trim();
    if (q.length < 2) { hideSuggestions(); return; }
    searchTimer = setTimeout(() => fetchSuggestions(q), 250);
  });

  async function fetchSuggestions(q) {
    const resp = await fetch(`/api/checkout/tenants?q=${encodeURIComponent(q)}&pin=${PIN}`,
      { headers: { 'X-Admin-Pin': PIN } });
    if (!resp.ok) return;
    const items = await resp.json();
    const box = document.getElementById('suggestions');
    box.innerHTML = '';
    if (!items.length) { hideSuggestions(); return; }
    items.forEach(item => {
      const d = document.createElement('div');
      d.className = 'suggestion-item';
      d.textContent = item.label;
      d.onclick = () => selectTenant(item);
      box.appendChild(d);
    });
    box.style.display = 'block';
  }

  async function selectTenant(item) {
    document.getElementById('tenantSearch').value = item.label;
    document.getElementById('tenancyId').value = item.tenancy_id;
    state.tenancyId = item.tenancy_id;
    hideSuggestions();

    // Pre-fetch financial data
    const resp = await fetch(`/api/checkout/tenant/${item.tenancy_id}`,
      { headers: { 'X-Admin-Pin': PIN } });
    if (!resp.ok) return;
    const d = await resp.json();
    document.getElementById('deposit').value = d.security_deposit;
    document.getElementById('pendingDues').value = d.pending_dues;
    state.tenantPhone = d.phone;
    document.getElementById('tenantPhone').value = d.phone;
    refundOverridden = false;
    calcRefund();
  }

  function hideSuggestions() {
    document.getElementById('suggestions').style.display = 'none';
  }
  document.addEventListener('click', e => {
    if (!e.target.closest('.autocomplete')) hideSuggestions();
  });

  // ── Toggles ───────────────────────────────────────────────────────────────
  function setToggle(btn) {
    const field = btn.dataset.field;
    btn.closest('.toggle-group').querySelectorAll('.toggle-btn').forEach(b => {
      b.classList.remove('selected');
    });
    btn.classList.add('selected');
    state.toggles[field] = btn.dataset.val === 'true';
    if (field === 'roomCondition') {
      document.getElementById('damageField').style.display =
        btn.dataset.val === 'false' ? 'block' : 'none';
      if (btn.dataset.val === 'true') document.getElementById('damageNotes').value = '';
    }
  }

  // ── Settlement calc ───────────────────────────────────────────────────────
  function calcRefund() {
    const dep  = parseFloat(document.getElementById('deposit').value) || 0;
    const dues = parseFloat(document.getElementById('pendingDues').value) || 0;
    const ded  = parseFloat(document.getElementById('deductions').value) || 0;
    document.getElementById('s_deposit').textContent = `₹${dep.toLocaleString()}`;
    document.getElementById('s_dues').textContent = `- ₹${dues.toLocaleString()}`;
    document.getElementById('s_deductions').textContent = `- ₹${ded.toLocaleString()}`;
    const refund = Math.max(0, dep - dues - ded);
    document.getElementById('s_refund').textContent = `₹${refund.toLocaleString()}`;
    if (!refundOverridden) document.getElementById('refundAmount').value = refund;
    document.getElementById('deductionReasonField').style.display = ded > 0 ? 'block' : 'none';
  }

  // ── Step navigation ───────────────────────────────────────────────────────
  function updateProgress(step) {
    [1,2,3].forEach(i => {
      const dot = document.getElementById(`dot${i}`);
      dot.className = 'step-dot' + (i < step ? ' done' : i === step ? ' active' : '');
    });
  }

  function goStep1() {
    document.getElementById('step1').classList.remove('hidden');
    document.getElementById('step2').classList.add('hidden');
    updateProgress(1);
  }

  function goStep2() {
    if (!state.tenancyId) { alert('Please select a tenant first.'); return; }
    if (!document.getElementById('checkoutDate').value) { alert('Please set a checkout date.'); return; }
    document.getElementById('step1').classList.add('hidden');
    document.getElementById('step2').classList.remove('hidden');
    updateProgress(2);
  }

  function goStep3() {
    const required = ['roomKey', 'wardrobeKey', 'biometric', 'roomCondition'];
    for (const f of required) {
      if (state.toggles[f] === undefined) {
        alert(`Please answer all physical handover questions.`); return;
      }
    }
    if (state.toggles.roomCondition === false && !document.getElementById('damageNotes').value.trim()) {
      alert('Please describe the damage.'); return;
    }
    document.getElementById('step2').classList.add('hidden');
    document.getElementById('step3').classList.remove('hidden');
    updateProgress(3);
    calcRefund();
  }

  // ── Submit ────────────────────────────────────────────────────────────────
  async function submitForm() {
    const deductions = parseFloat(document.getElementById('deductions').value) || 0;
    if (deductions > 0 && !document.getElementById('deductionReason').value.trim()) {
      alert('Please enter a deduction reason.'); return;
    }
    if (!document.getElementById('refundMode').value) {
      alert('Please select a refund mode.'); return;
    }

    const payload = {
      tenancy_id:            state.tenancyId,
      checkout_date:         document.getElementById('checkoutDate').value,
      room_key_returned:     state.toggles.roomKey,
      wardrobe_key_returned: state.toggles.wardrobeKey,
      biometric_removed:     state.toggles.biometric,
      room_condition_ok:     state.toggles.roomCondition,
      damage_notes:          document.getElementById('damageNotes').value.trim(),
      security_deposit:      parseFloat(document.getElementById('deposit').value) || 0,
      pending_dues:          parseFloat(document.getElementById('pendingDues').value) || 0,
      deductions:            deductions,
      deduction_reason:      document.getElementById('deductionReason').value.trim(),
      refund_amount:         parseFloat(document.getElementById('refundAmount').value) || 0,
      refund_mode:           document.getElementById('refundMode').value,
      created_by_phone:      '',
    };

    const resp = await fetch('/api/checkout/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Pin': PIN },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert('Error: ' + (err.detail || resp.status)); return;
    }
    const data = await resp.json();
    state.sessionToken = data.token;

    document.getElementById('step3').classList.add('hidden');
    document.getElementById('statusBox').style.display = 'block';
    startPolling(data.token);
  }

  // ── Status polling ────────────────────────────────────────────────────────
  function startPolling(token) {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => checkStatus(token), 8000);
  }

  async function checkStatus(token) {
    const resp = await fetch(`/api/checkout/status/${token}`,
      { headers: { 'X-Admin-Pin': PIN } });
    if (!resp.ok) return;
    const d = await resp.json();
    const badge = document.getElementById('statusBadge');
    const title = document.getElementById('statusTitle');
    const sub   = document.getElementById('statusSub');
    badge.className = `badge ${d.status}`;
    badge.textContent = d.status.replace('_', ' ').toUpperCase();

    if (d.status === 'confirmed') {
      clearInterval(pollInterval);
      title.textContent = 'Tenant Confirmed';
      sub.textContent = 'Checkout is confirmed. DB and Sheet have been updated.';
    } else if (d.status === 'auto_confirmed') {
      clearInterval(pollInterval);
      title.textContent = 'Auto-Confirmed';
      sub.textContent = 'No response in 2 hours — checkout auto-confirmed.';
    } else if (d.status === 'rejected') {
      clearInterval(pollInterval);
      title.textContent = 'Tenant Rejected';
      sub.textContent = `Reason: ${d.rejection_reason || 'Not provided'}. Please resolve and create a new session.`;
    }
  }

  function resetForm() {
    clearInterval(pollInterval);
    document.getElementById('statusBox').style.display = 'none';
    document.getElementById('step1').classList.remove('hidden');
    document.getElementById('tenantSearch').value = '';
    document.getElementById('tenancyId').value = '';
    document.getElementById('checkoutDate').value = new Date().toISOString().split('T')[0];
    state = { tenancyId: null, tenantPhone: '', toggles: {}, sessionToken: null };
    refundOverridden = false;
    updateProgress(1);
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('selected'));
    document.getElementById('damageNotes').value = '';
    document.getElementById('deposit').value = '';
    document.getElementById('pendingDues').value = '';
    document.getElementById('deductions').value = '0';
    document.getElementById('refundAmount').value = '';
    document.getElementById('refundMode').value = '';
    document.getElementById('deductionReason').value = '';
    calcRefund();
  }
  </script>
  </body>
  </html>
  ```

- [ ] **Step 2: Smoke-test manually**

  Start the server:
  ```bash
  venv/Scripts/python main.py
  ```

  Open http://localhost:8000/admin/checkout in a browser. Verify:
  - Nav bar shows "Check-in" and "Checkout" links
  - Step 1: typing a name in tenant search calls `/api/checkout/tenants`
  - Selecting a tenant pre-fills deposit + dues
  - Step 2: all 4 yes/no toggles work; damage notes appear on "Not OK"
  - Step 3: refund auto-calculates; deduction reason appears when deductions > 0
  - Submit posts to `/api/checkout/create`

- [ ] **Step 3: Commit**

  ```bash
  git add static/checkout_admin.html
  git commit -m "feat(checkout): 3-step admin checkout form"
  ```

---

## Task 11: Nav bar + main.py /admin/checkout route

**Files:**
- Modify: `static/admin_onboarding.html`
- Modify: `main.py`

- [ ] **Step 1: Add nav bar to admin_onboarding.html**

  Open `static/admin_onboarding.html`. Find the opening `<body>` tag. After it, insert:

  ```html
  <nav style="background:#1a1a2e;padding:14px 24px;display:flex;align-items:center;gap:24px;border-bottom:1px solid #2a2a40;margin-bottom:0">
    <a href="/admin/onboarding" style="color:#EF1F9C;font-weight:700;font-size:16px;text-decoration:none">Cozeevo Admin</a>
    <a href="/admin/onboarding" style="color:#EF1F9C;text-decoration:none;font-size:14px;padding:6px 12px;background:rgba(239,31,156,.12);border-radius:6px">Check-in</a>
    <a href="/admin/checkout"   style="color:#888;text-decoration:none;font-size:14px;padding:6px 12px;border-radius:6px">Checkout</a>
  </nav>
  ```

- [ ] **Step 2: Add `/admin/checkout` route to main.py**

  In `main.py`, after the existing `/admin/onboarding` route:

  ```python
  @app.get("/admin/checkout", response_class=HTMLResponse)
  async def serve_admin_checkout():
      """Serve the admin checkout panel."""
      form_path = Path("static/checkout_admin.html")
      if not form_path.exists():
          return HTMLResponse("<h1>Checkout form not available yet</h1>", status_code=404)
      return HTMLResponse(form_path.read_text(encoding="utf-8"))
  ```

- [ ] **Step 3: Verify nav bar works**

  Open http://localhost:8000/admin/onboarding and confirm "Checkout" nav link appears and navigates to /admin/checkout.

- [ ] **Step 4: Commit**

  ```bash
  git add static/admin_onboarding.html main.py
  git commit -m "feat(checkout): nav bar on admin pages + /admin/checkout route"
  ```

---

## Task 12 (Phase 2): Fix WhatsApp RECORD_CHECKOUT — add deductions + defer DB writes

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py`

The current RECORD_CHECKOUT flow writes to DB inside `confirm_checkout` step — that part is fine. The issue is: (1) no deduction step, (2) the summary doesn't show the full financial breakdown with editable confirmation, (3) in some cases checkout happens without all steps. This task adds the deduction steps and ensures the summary is complete before any DB write.

- [ ] **Step 1: Write failing tests**

  Add to `tests/test_checkout_flow.py`:

  ```python
  @pytest.mark.asyncio
  async def test_record_checkout_asks_deductions_after_fingerprint(
      db_session, pending_record_checkout_fingerprint_done
  ):
      """After ask_fingerprint step, next step is ask_deductions (not confirm_checkout)."""
      from src.whatsapp.handlers.owner_handler import resolve_pending_action
      from src.database.models import PendingAction

      pending = pending_record_checkout_fingerprint_done  # step="ask_fingerprint"
      # Simulate receptionist replying "yes"
      reply = await resolve_pending_action(pending, "yes", [], {}, db_session)
      assert reply is not None
      assert "deduction" in reply.lower() or "damage" in reply.lower() or "amount" in reply.lower()


  @pytest.mark.asyncio
  async def test_record_checkout_full_summary_shown_before_confirm(
      db_session, pending_record_checkout_deductions_done
  ):
      """After deduction steps, summary shows deposit, dues, deductions, refund."""
      from src.whatsapp.handlers.owner_handler import resolve_pending_action

      pending = pending_record_checkout_deductions_done  # step="ask_deduction_reason"
      reply = await resolve_pending_action(pending, "paint damage", [], {}, db_session)
      assert reply is not None
      # All financial lines present in summary
      assert "deposit" in reply.lower()
      assert "refund" in reply.lower()
      assert "confirm" in reply.lower()


  @pytest.mark.asyncio
  async def test_record_checkout_no_db_write_before_confirm(
      db_session, pending_record_checkout_at_confirm
  ):
      """DB not written until receptionist explicitly confirms."""
      from src.whatsapp.handlers.owner_handler import resolve_pending_action
      from src.database.models import CheckoutRecord
      from sqlalchemy import select

      # Before confirm
      pending = pending_record_checkout_at_confirm
      count_before = await db_session.scalar(
          select(func.count(CheckoutRecord.id))
      )
      # Reply cancel
      await resolve_pending_action(pending, "cancel", [], {}, db_session)
      count_after = await db_session.scalar(
          select(func.count(CheckoutRecord.id))
      )
      assert count_before == count_after  # nothing written on cancel
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_flow.py::test_record_checkout_asks_deductions_after_fingerprint tests/test_checkout_flow.py::test_record_checkout_full_summary_shown_before_confirm -v
  ```

  Expected: `FAILED`

- [ ] **Step 3: Modify `ask_fingerprint` step to transition to `ask_deductions`**

  In `src/whatsapp/handlers/owner_handler.py`, find the `if step == "ask_fingerprint":` block (around line 1520). Change the `action_data["step"]` assignment from `"confirm_checkout"` to `"ask_deductions"` and replace the summary/return with:

  ```python
  if step == "ask_fingerprint":
      action_data["fingerprint_deleted"] = yes
      action_data["step"] = "ask_deductions"
      await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
      return "Any *deductions* from the deposit? Enter amount in Rs. or reply *0* for none."
  ```

- [ ] **Step 4: Add `ask_deductions` step**

  After the `ask_fingerprint` block, add:

  ```python
  if step == "ask_deductions":
      try:
          ded_amount = float(ans.replace(",", "").replace("rs", "").replace("₹", "").strip())
      except ValueError:
          return "__KEEP_PENDING__Please enter a number (e.g. *2000* or *0*)."
      action_data["deductions"] = ded_amount
      if ded_amount > 0:
          action_data["step"] = "ask_deduction_reason"
          await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
          return "Reason for deduction? (e.g. *paint damage*, *no notice given*)"
      else:
          action_data["deductions"] = 0
          action_data["deduction_reason"] = ""
          action_data["step"] = "confirm_checkout"
          return await _build_checkout_summary(action_data, pending.phone, session)
  ```

- [ ] **Step 5: Add `ask_deduction_reason` step**

  ```python
  if step == "ask_deduction_reason":
      action_data["deduction_reason"] = reply_text.strip()
      action_data["step"] = "confirm_checkout"
      await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
      return await _build_checkout_summary(action_data, pending.phone, session)
  ```

- [ ] **Step 6: Extract `_build_checkout_summary()` helper**

  Add this function near `_do_confirm_checkout`:

  ```python
  async def _build_checkout_summary(action_data: dict, phone: str, session: AsyncSession) -> str:
      """
      Build the full settlement summary for RECORD_CHECKOUT confirm step.
      Saves updated action_data with calculated financials to pending action.
      Returns the summary string with confirm/cancel prompt.
      """
      tenancy_id = action_data.get("tenancy_id")
      tenancy = await session.get(Tenancy, tenancy_id) if tenancy_id else None
      deposit    = int(tenancy.security_deposit or 0) if tenancy else 0
      o_rent, o_maint = await _calc_outstanding_dues(tenancy_id, session) if tenancy_id else (Decimal("0"), Decimal("0"))
      pending_dues = int(o_rent) + int(o_maint)
      deductions   = int(action_data.get("deductions", 0))
      ded_reason   = action_data.get("deduction_reason", "")

      deposit_forfeited = False
      notice_line = ""
      if tenancy and not tenancy.notice_date:
          deposit_forfeited = True
          notice_line = "\nNo notice on record — *deposit forfeited*"
      elif tenancy and tenancy.notice_date:
          if tenancy.notice_date.day > _NOTICE_BY_DAY:
              deposit_forfeited = True
              notice_line = (f"\nNotice: {tenancy.notice_date.strftime('%d %b %Y')} "
                             f"(after {_NOTICE_BY_DAY}th) — *deposit forfeited*")
          else:
              notice_line = (f"\nNotice: {tenancy.notice_date.strftime('%d %b %Y')} "
                             f"(before {_NOTICE_BY_DAY}th) — eligible for refund")

      if deposit_forfeited:
          refund = 0
      else:
          refund = max(0, deposit - pending_dues - deductions)

      action_data.update({
          "auto_deposit": deposit,
          "auto_dues": pending_dues,
          "auto_refund": refund,
          "deposit_forfeited": deposit_forfeited,
      })
      await _save_pending(phone, "RECORD_CHECKOUT", action_data, [], session)

      exit_d = date.fromisoformat(action_data.get("exit_date", date.today().isoformat()))
      deduction_line = f"Deductions: -Rs.{deductions:,}" + (f" ({ded_reason})" if ded_reason else "")

      if deposit_forfeited:
          settlement = f"Deposit: Rs.{deposit:,}\n*FORFEITED — Refund: Rs.0*"
      else:
          settlement = (
              f"Deposit held: Rs.{deposit:,}\n"
              f"Pending dues: -Rs.{pending_dues:,}\n"
              f"{deduction_line}\n"
              f"{'─' * 25}\n"
              f"*Refund: Rs.{refund:,}*"
          )

      return (
          f"*Checkout Summary — {action_data.get('tenant_name', '')}*\n\n"
          f"Exit date: {exit_d.strftime('%d %b %Y')}\n"
          f"Cupboard key: {'Returned' if action_data.get('cupboard_key') else 'NOT returned'}\n"
          f"Main key: {'Returned' if action_data.get('main_key') else 'NOT returned'}\n"
          f"Damages: {action_data.get('damage') or 'None'}\n"
          f"Fingerprint: {'Deleted' if action_data.get('fingerprint_deleted') else 'NOT deleted'}\n"
          f"{notice_line}\n\n"
          f"{settlement}\n\n"
          "Reply *confirm* to save.\n"
          "Reply *cancel* or *no* to abort."
      )
  ```

- [ ] **Step 7: Update `confirm_checkout` step to use new financial fields**

  In the `confirm_checkout` step (around line 1565), update `CheckoutRecord` creation to include the new fields:

  ```python
  cr = CheckoutRecord(
      tenancy_id=tenancy_id,
      cupboard_key_returned=action_data.get("cupboard_key", False),
      main_key_returned=action_data.get("main_key", False),
      biometric_removed=action_data.get("fingerprint_deleted", False),
      damage_notes=action_data.get("damage") or None,
      pending_dues_amount=action_data.get("auto_dues", 0),
      deposit_refunded_amount=refund_amt,
      deposit_refund_date=exit_date if refund_amt > 0 else None,
      actual_exit_date=exit_date,
      recorded_by=pending.phone,
      deductions=Decimal(str(action_data.get("deductions", 0))),
      deduction_reason=action_data.get("deduction_reason") or None,
  )
  ```

  Also update the settlement display line in the return message to include deductions:

  ```python
  if deposit_forfeited:
      settlement_line = f"Deposit: Rs.{deposit:,} — *FORFEITED*\n*Refund: Rs.0*"
  else:
      settlement_line = (
          f"Deposit: Rs.{deposit:,}\n"
          f"Dues: -Rs.{action_data.get('auto_dues', 0):,}\n"
          f"Deductions: -Rs.{int(action_data.get('deductions', 0)):,}"
          + (f" ({action_data.get('deduction_reason', '')})" if action_data.get('deduction_reason') else "")
          + f"\n*Refund: Rs.{refund_amt:,}*"
      )
  ```

- [ ] **Step 8: Run all checkout flow tests**

  ```bash
  venv/Scripts/python -m pytest tests/test_checkout_flow.py -v
  ```

  Expected: all tests `PASSED`

- [ ] **Step 9: Run the full test suite to check for regressions**

  ```bash
  venv/Scripts/python -m pytest tests/ -v --tb=short
  ```

  Expected: no regressions in existing checkout or payment tests.

- [ ] **Step 10: Commit**

  ```bash
  git add src/whatsapp/handlers/owner_handler.py tests/test_checkout_flow.py
  git commit -m "feat(checkout): Phase 2 — add deduction steps + full financial summary to WhatsApp RECORD_CHECKOUT flow"
  ```

---

## Task 13: End-to-end smoke test + deploy

- [ ] **Step 1: Start server and run a full manual flow**

  ```bash
  TEST_MODE=1 venv/Scripts/python main.py
  ```

  1. Open http://localhost:8000/admin/checkout
  2. Search for an active tenant, select them
  3. Complete all 3 steps with test data
  4. Submit — verify response is `{"status": "pending", "token": "..."}`
  5. Check DB: `SELECT * FROM checkout_sessions ORDER BY id DESC LIMIT 1;`
  6. Simulate tenant YES reply via `/api/whatsapp/process` POST
  7. Check DB: `checkout_sessions.status = 'confirmed'`, `checkout_records` row created, `tenancies.status = 'exited'`

- [ ] **Step 2: Run golden test suite**

  ```bash
  venv/Scripts/python tests/eval_golden.py
  ```

  Expected: pass rate ≥ 95% (same or better than before)

- [ ] **Step 3: Update CHANGELOG**

  Open `docs/CHANGELOG.md` and prepend a new entry for this session.

- [ ] **Step 4: Push to GitHub**

  ```bash
  git push origin master
  ```

- [ ] **Step 5: Deploy to VPS**

  ```bash
  ssh vps "cd /opt/pg-accountant && git pull && systemctl restart pg-accountant"
  ```

  Verify: `systemctl status pg-accountant` shows `active (running)`.

- [ ] **Step 6: Run migration on VPS**

  ```bash
  ssh vps "cd /opt/pg-accountant && venv/bin/python -m src.database.migrate_all"
  ```

---

## Self-Review Checklist

| Spec requirement | Covered in |
|---|---|
| 3-step web form (Tenant+Date, Physical, Settlement) | Task 10 |
| All fields compulsory | Task 10 (JS validation per step) |
| All Step 3 fields editable even if pre-filled | Task 10 (all inputs are `<input type="number">`, pre-filled but editable) |
| Receptionist fills all details | Task 10 (no tenant-facing form) |
| WhatsApp checkout_request sent to tenant | Task 5 |
| 2-hour expiry | Task 5 (expires_at = now + 2hr), Task 9 (auto-confirm job) |
| YES = confirm → DB + Sheet | Task 8 (_handle_checkout_agree → _do_confirm_checkout) |
| NO + reason = reject → receptionist notified | Task 8 (_handle_checkout_reject) |
| NO without reason = ask for reason | Task 7 (chat_api intercept) |
| No response = auto-confirm | Task 9 (APScheduler every 15min) |
| `auto_confirmed` status distinct from `confirmed` | Task 1 (CheckoutSessionStatus), Task 9 |
| Nav bar /admin/onboarding + /admin/checkout | Task 11 |
| Status poll endpoint for admin page | Task 6 |
| Phase 2: deduction steps in WhatsApp flow | Task 12 |
| Phase 2: full financial summary before confirm | Task 12 (_build_checkout_summary) |
| Phase 2: no DB write until confirm | Task 12 (all writes in confirm_checkout step only) |
| checkout_confirmed message wording | Task 8 ("Refund ... will be processed by receptionist now.") |
