# Digital Onboarding Form — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace printed registration form with a digital 2-form system — receptionist creates session, tenant fills details + signs on phone, receptionist approves.

**Architecture:** FastAPI backend + two static HTML pages (tenant mobile form + admin panel). Linked by UUID token. Signature via HTML5 canvas. PDF via reportlab. WhatsApp delivery via existing Meta Graph API.

**Tech Stack:** FastAPI, SQLAlchemy (Supabase/PostgreSQL), reportlab (PDF), signature_pad.js (canvas), existing WhatsApp Cloud API

**Spec:** `docs/superpowers/specs/2026-04-15-digital-onboarding-form-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/database/models.py` | Modify | Add/extend OnboardingSession model |
| `src/database/migrate_all.py` | Modify | Append onboarding_sessions table migration |
| `src/api/onboarding_router.py` | Create | All onboarding API endpoints |
| `src/services/pdf_generator.py` | Create | HTML→PDF agreement generation |
| `static/onboarding.html` | Create | Tenant mobile form (5-step wizard) |
| `static/admin_onboarding.html` | Create | Admin create/review panel |
| `templates/agreement.html` | Create | PDF agreement HTML template |
| `main.py` | Modify | Mount onboarding router, serve /onboard route |
| `src/whatsapp/handlers/owner_handler.py` | Modify | Remove step-by-step flow, update add_tenant_prompt |
| `src/whatsapp/webhook_handler.py` | Modify | Add send_document helper |
| `requirements.txt` | Modify | Add reportlab |
| `tests/test_onboarding_api.py` | Create | API endpoint tests |

---

### Task 1: Database — Extend OnboardingSession Model

**Files:**
- Modify: `src/database/models.py:796-818`
- Modify: `src/database/migrate_all.py` (append after line 1051)

- [ ] **Step 1: Update OnboardingSession model in models.py**

Replace the existing `OnboardingSession` class (lines 796-818) with the extended version:

```python
class OnboardingSession(Base):
    """
    Digital onboarding form session.
    Receptionist creates (fills room/rent) → sends link to tenant →
    tenant fills personal details + signs → receptionist approves → Tenant created.
    """
    __tablename__ = "onboarding_sessions"

    id                = Column(Integer, primary_key=True)
    token             = Column(String(36), unique=True, nullable=False, index=True)
    status            = Column(String(20), default="draft")  # draft, pending_tenant, pending_review, approved, expired, cancelled
    created_by_phone  = Column(String(20))  # receptionist phone
    tenant_phone      = Column(String(20))  # tenant phone for WhatsApp
    # Room & financial (filled by receptionist)
    room_id           = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    agreed_rent       = Column(Numeric(12, 2), default=0)
    security_deposit  = Column(Numeric(12, 2), default=0)
    maintenance_fee   = Column(Numeric(10, 2), default=0)
    booking_amount    = Column(Numeric(12, 2), default=0)
    advance_mode      = Column(String(10))  # cash/upi
    checkin_date      = Column(Date)
    stay_type         = Column(String(10), default="monthly")
    lock_in_months    = Column(Integer, default=0)
    special_terms     = Column(Text)
    # Tenant-filled data
    tenant_data       = Column(Text)  # JSON: personal details
    signature_image   = Column(Text)  # base64 PNG
    agreement_pdf_path = Column(String(255))
    # Legacy fields (keep for backward compat)
    tenant_id         = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    tenancy_id        = Column(Integer, ForeignKey("tenancies.id"), nullable=True)
    step              = Column(String(40))
    collected_data    = Column(Text)
    completed         = Column(Boolean, default=False)
    # Timestamps
    expires_at        = Column(DateTime)
    completed_at      = Column(DateTime)
    approved_at       = Column(DateTime)
    created_at        = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_onboarding_token", "token"),
        Index("ix_onboarding_status", "status"),
        Index("ix_onboarding_tenant", "tenant_id"),
        Index("ix_onboarding_expires", "expires_at"),
    )
```

- [ ] **Step 2: Add migration function in migrate_all.py**

Add this function before the `main()` function, and call it inside `main()` after `run_unhandled_requests_table`:

```python
async def run_extend_onboarding_sessions(conn: AsyncConnection) -> None:
    """Extend onboarding_sessions table for digital form flow."""
    print("\n-- Extend onboarding_sessions for digital form --")
    # Add new columns (IF NOT EXISTS for idempotency)
    new_cols = [
        ("token", "VARCHAR(36)"),
        ("status", "VARCHAR(20) DEFAULT 'draft'"),
        ("created_by_phone", "VARCHAR(20)"),
        ("tenant_phone", "VARCHAR(20)"),
        ("room_id", "INTEGER REFERENCES rooms(id)"),
        ("agreed_rent", "NUMERIC(12,2) DEFAULT 0"),
        ("security_deposit", "NUMERIC(12,2) DEFAULT 0"),
        ("maintenance_fee", "NUMERIC(10,2) DEFAULT 0"),
        ("booking_amount", "NUMERIC(12,2) DEFAULT 0"),
        ("advance_mode", "VARCHAR(10)"),
        ("checkin_date", "DATE"),
        ("stay_type", "VARCHAR(10) DEFAULT 'monthly'"),
        ("lock_in_months", "INTEGER DEFAULT 0"),
        ("special_terms", "TEXT"),
        ("tenant_data", "TEXT"),
        ("signature_image", "TEXT"),
        ("agreement_pdf_path", "VARCHAR(255)"),
        ("completed_at", "TIMESTAMP"),
        ("approved_at", "TIMESTAMP"),
    ]
    for col_name, col_type in new_cols:
        try:
            await conn.execute(text(
                f"ALTER TABLE onboarding_sessions ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            ))
        except Exception:
            pass  # column already exists
    # Add unique index on token
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_onboarding_token ON onboarding_sessions(token)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_onboarding_status ON onboarding_sessions(status)"
    ))
    # Make tenant_id nullable (was NOT NULL for old WhatsApp flow)
    try:
        await conn.execute(text(
            "ALTER TABLE onboarding_sessions ALTER COLUMN tenant_id DROP NOT NULL"
        ))
    except Exception:
        pass
    print("  [ok] onboarding_sessions extended")
```

In `main()`, add after line 1051:
```python
            await run_extend_onboarding_sessions(conn)
```

- [ ] **Step 3: Run migration locally**

```bash
cd "c:\Users\kiran\Desktop\AI Watsapp PG Accountant"
venv/Scripts/python -m src.database.migrate_all
```

Expected: `[ok] onboarding_sessions extended`

- [ ] **Step 4: Commit**

```bash
git add src/database/models.py src/database/migrate_all.py
git commit -m "feat: extend onboarding_sessions for digital form flow"
```

---

### Task 2: Onboarding API Router

**Files:**
- Create: `src/api/onboarding_router.py`

- [ ] **Step 1: Create the router with all endpoints**

```python
"""
src/api/onboarding_router.py
Onboarding form API — receptionist creates session, tenant fills, receptionist approves.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from typing import Optional

from src.database.db_manager import get_session
from src.database.models import (
    OnboardingSession, Room, Property, Tenant, Tenancy, TenancyStatus,
    RentSchedule, RentStatus, Payment, PaymentMode, PaymentFor,
)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# ── Pydantic models ──────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    room_number: str
    agreed_rent: float
    security_deposit: float = 0
    maintenance_fee: float = 0
    booking_amount: float = 0
    advance_mode: str = ""  # cash/upi — required if booking_amount > 0
    checkin_date: str  # ISO format YYYY-MM-DD
    stay_type: str = "monthly"
    lock_in_months: int = 0
    special_terms: str = ""
    tenant_phone: str  # 10 digits
    created_by_phone: str = ""


class TenantSubmitRequest(BaseModel):
    name: str
    phone: str
    gender: str
    date_of_birth: str = ""
    age: str = ""
    email: str = ""
    food_preference: str
    father_name: str = ""
    father_phone: str = ""
    emergency_contact_name: str
    emergency_contact_phone: str
    emergency_contact_relationship: str
    permanent_address: str = ""
    occupation: str = ""
    educational_qualification: str = ""
    office_address: str = ""
    office_phone: str = ""
    id_proof_type: str = ""
    id_proof_number: str = ""
    signature_image: str  # base64 PNG data URL


# ── Create session (receptionist) ────────────────────────────────────────────

@router.post("/create")
async def create_session(req: CreateSessionRequest):
    """Receptionist creates onboarding session with room/rent details."""
    if req.booking_amount > 0 and not req.advance_mode:
        raise HTTPException(400, "Payment method (cash/upi) required when booking amount > 0")

    async with get_session() as session:
        # Validate room
        room = await session.scalar(select(Room).where(Room.room_number.ilike(req.room_number)))
        if not room:
            raise HTTPException(404, f"Room {req.room_number} not found")

        # Derive building from room
        building = ""
        if room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""

        token = str(uuid.uuid4())
        obs = OnboardingSession(
            token=token,
            status="pending_tenant",
            created_by_phone=req.created_by_phone,
            tenant_phone=req.tenant_phone,
            room_id=room.id,
            agreed_rent=Decimal(str(req.agreed_rent)),
            security_deposit=Decimal(str(req.security_deposit)),
            maintenance_fee=Decimal(str(req.maintenance_fee)),
            booking_amount=Decimal(str(req.booking_amount)),
            advance_mode=req.advance_mode if req.booking_amount > 0 else "",
            checkin_date=date.fromisoformat(req.checkin_date),
            stay_type=req.stay_type,
            lock_in_months=req.lock_in_months,
            special_terms=req.special_terms,
            expires_at=datetime.utcnow() + timedelta(hours=48),
        )
        session.add(obs)
        await session.flush()

        rt = room.room_type
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")

        return {
            "token": token,
            "link": f"/onboard/{token}",
            "session_id": obs.id,
            "room": {
                "number": room.room_number,
                "building": building,
                "floor": str(room.floor or ""),
                "sharing": sharing,
            },
        }


# ── Get session data (tenant form loads this) ────────────────────────────────

@router.get("/{token}")
async def get_session_data(token: str):
    """Tenant form loads session data — room/rent summary."""
    async with get_session() as session:
        obs = await session.scalar(
            select(OnboardingSession).where(OnboardingSession.token == token)
        )
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status == "expired" or (obs.expires_at and obs.expires_at < datetime.utcnow()):
            raise HTTPException(410, "This onboarding link has expired")
        if obs.status not in ("pending_tenant", "pending_review"):
            raise HTTPException(400, f"Session status: {obs.status}")

        room = await session.get(Room, obs.room_id) if obs.room_id else None
        building = ""
        if room and room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""

        rt = room.room_type if room else ""
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")

        return {
            "status": obs.status,
            "room": {
                "number": room.room_number if room else "",
                "building": building,
                "floor": str(room.floor or "") if room else "",
                "sharing": sharing,
            },
            "agreed_rent": float(obs.agreed_rent or 0),
            "security_deposit": float(obs.security_deposit or 0),
            "maintenance_fee": float(obs.maintenance_fee or 0),
            "booking_amount": float(obs.booking_amount or 0),
            "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
            "lock_in_months": obs.lock_in_months or 0,
            "special_terms": obs.special_terms or "",
            "tenant_data": json.loads(obs.tenant_data) if obs.tenant_data else None,
        }


# ── Tenant submits form ──────────────────────────────────────────────────────

@router.post("/{token}/submit")
async def tenant_submit(token: str, req: TenantSubmitRequest):
    """Tenant submits personal details + signature."""
    async with get_session() as session:
        obs = await session.scalar(
            select(OnboardingSession).where(OnboardingSession.token == token)
        )
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status != "pending_tenant":
            raise HTTPException(400, f"Cannot submit — status is {obs.status}")
        if obs.expires_at and obs.expires_at < datetime.utcnow():
            obs.status = "expired"
            raise HTTPException(410, "This onboarding link has expired")

        # Store tenant data as JSON
        tenant_data = req.model_dump(exclude={"signature_image"})
        obs.tenant_data = json.dumps(tenant_data)
        obs.signature_image = req.signature_image
        obs.status = "pending_review"
        obs.completed_at = datetime.utcnow()

        return {"status": "pending_review", "message": "Submitted. Receptionist will review."}


# ── List pending sessions (admin) ────────────────────────────────────────────

@router.get("/admin/pending")
async def list_pending():
    """List sessions pending review."""
    async with get_session() as session:
        result = await session.execute(
            select(OnboardingSession).where(
                OnboardingSession.status.in_(["pending_tenant", "pending_review"])
            ).order_by(OnboardingSession.created_at.desc())
        )
        sessions = result.scalars().all()
        items = []
        for obs in sessions:
            room = await session.get(Room, obs.room_id) if obs.room_id else None
            items.append({
                "token": obs.token,
                "status": obs.status,
                "room": room.room_number if room else "",
                "tenant_phone": obs.tenant_phone,
                "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
                "created_at": obs.created_at.isoformat() if obs.created_at else "",
                "tenant_name": json.loads(obs.tenant_data).get("name", "") if obs.tenant_data else "",
            })
        return {"sessions": items}


# ── Approve session (admin) → create Tenant + Tenancy ────────────────────────

@router.post("/{token}/approve")
async def approve_session(token: str):
    """Receptionist approves → creates Tenant, Tenancy, RentSchedule, updates Sheet."""
    async with get_session() as session:
        obs = await session.scalar(
            select(OnboardingSession).where(OnboardingSession.token == token)
        )
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status != "pending_review":
            raise HTTPException(400, f"Cannot approve — status is {obs.status}")

        td = json.loads(obs.tenant_data) if obs.tenant_data else {}
        if not td.get("name") or not td.get("phone"):
            raise HTTPException(400, "Tenant data incomplete")

        room = await session.get(Room, obs.room_id)
        if not room:
            raise HTTPException(400, "Room not found")

        # Derive building
        building = ""
        if room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""

        phone = td["phone"].strip()
        if len(phone) > 10:
            phone = phone[-10:]

        # Create or find tenant
        tenant = await session.scalar(select(Tenant).where(Tenant.phone == phone))
        if not tenant:
            tenant = Tenant(
                name=td["name"],
                phone=phone,
                gender=td.get("gender"),
                food_preference=td.get("food_preference"),
                date_of_birth=None,  # parse below
                email=td.get("email"),
                father_name=td.get("father_name"),
                father_phone=td.get("father_phone"),
                emergency_contact_name=td.get("emergency_contact_name"),
                emergency_contact_phone=td.get("emergency_contact_phone"),
                emergency_contact_relationship=td.get("emergency_contact_relationship"),
                permanent_address=td.get("permanent_address"),
                occupation=td.get("occupation"),
                educational_qualification=td.get("educational_qualification"),
                office_address=td.get("office_address"),
                office_phone=td.get("office_phone"),
                id_proof_type=td.get("id_proof_type"),
                id_proof_number=td.get("id_proof_number"),
            )
            # Parse DOB
            dob_str = td.get("date_of_birth", "")
            if dob_str:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        tenant.date_of_birth = datetime.strptime(dob_str, fmt).date()
                        break
                    except ValueError:
                        continue
            session.add(tenant)
            await session.flush()

        # Create tenancy
        rt = room.room_type
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")
        checkin = obs.checkin_date or date.today()

        tenancy = Tenancy(
            tenant_id=tenant.id,
            room_id=room.id,
            checkin_date=checkin,
            agreed_rent=obs.agreed_rent or 0,
            security_deposit=obs.security_deposit or 0,
            booking_amount=obs.booking_amount or 0,
            maintenance_fee=obs.maintenance_fee or 0,
            lock_in_months=obs.lock_in_months or 0,
            status=TenancyStatus.active if checkin <= date.today() else TenancyStatus.no_show,
        )
        session.add(tenancy)
        await session.flush()

        # Create RentSchedule
        period = checkin.replace(day=1)
        current_month = date.today().replace(day=1)
        while period <= current_month:
            session.add(RentSchedule(
                tenancy_id=tenancy.id,
                period_month=period,
                rent_due=obs.agreed_rent or 0,
                maintenance_due=obs.maintenance_fee or 0,
                status=RentStatus.pending,
                due_date=period,
            ))
            if period.month == 12:
                period = date(period.year + 1, 1, 1)
            else:
                period = date(period.year, period.month + 1, 1)

        # Log advance payment
        if obs.booking_amount and obs.booking_amount > 0:
            adv_mode = PaymentMode.upi if obs.advance_mode == "upi" else PaymentMode.cash
            session.add(Payment(
                tenancy_id=tenancy.id,
                amount=obs.booking_amount,
                payment_date=checkin,
                payment_mode=adv_mode,
                for_type=PaymentFor.booking,
                period_month=checkin.replace(day=1),
                notes=f"Booking advance ({obs.advance_mode})",
            ))

        # Update session
        obs.status = "approved"
        obs.approved_at = datetime.utcnow()
        obs.tenant_id = tenant.id
        obs.tenancy_id = tenancy.id

        # Google Sheet write-back (fire and forget)
        gsheets_note = ""
        try:
            from src.integrations.gsheets import add_tenant as gsheets_add
            gs_r = await gsheets_add(
                room_number=room.room_number, name=td["name"], phone=phone,
                gender=td.get("gender", ""), building=building,
                floor=str(room.floor or ""), sharing=sharing,
                checkin=checkin.strftime("%d/%m/%Y"),
                agreed_rent=float(obs.agreed_rent or 0),
                deposit=float(obs.security_deposit or 0),
                booking=float(obs.booking_amount or 0),
                maintenance=float(obs.maintenance_fee or 0),
                notes=obs.special_terms or "",
                dob=td.get("date_of_birth", ""),
                father_name=td.get("father_name", ""),
                father_phone=td.get("father_phone", ""),
                address=td.get("permanent_address", ""),
                emergency_contact=td.get("emergency_contact_phone", ""),
                emergency_relationship=td.get("emergency_contact_relationship", ""),
                email=td.get("email", ""),
                occupation=td.get("occupation", ""),
                education=td.get("educational_qualification", ""),
                office_address=td.get("office_address", ""),
                office_phone=td.get("office_phone", ""),
                id_type=td.get("id_proof_type", ""),
                id_number=td.get("id_proof_number", ""),
                food_pref=td.get("food_preference", ""),
                entered_by="onboarding_form",
                advance_amount=float(obs.booking_amount or 0),
                advance_mode=obs.advance_mode or "",
            )
            if gs_r.get("success"):
                gsheets_note = " | Sheet updated"
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("GSheets onboarding: %s", e)

        # Generate PDF (async, non-blocking)
        try:
            from src.services.pdf_generator import generate_agreement_pdf
            pdf_path = await generate_agreement_pdf(obs, td, room, building, sharing)
            obs.agreement_pdf_path = pdf_path
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("PDF generation failed: %s", e)

        return {
            "status": "approved",
            "tenant_id": tenant.id,
            "tenancy_id": tenancy.id,
            "message": f"Tenant {td['name']} created{gsheets_note}",
        }
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import py_compile; py_compile.compile('src/api/onboarding_router.py', doraise=True); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/api/onboarding_router.py
git commit -m "feat: onboarding API router with create/submit/approve endpoints"
```

---

### Task 3: PDF Generator Service

**Files:**
- Create: `src/services/pdf_generator.py`
- Modify: `requirements.txt` — add `reportlab`

- [ ] **Step 1: Add reportlab to requirements.txt**

Add line: `reportlab>=4.0`

- [ ] **Step 2: Install**

```bash
pip install reportlab
```

- [ ] **Step 3: Create pdf_generator.py**

```python
"""
src/services/pdf_generator.py
Generate signed rental agreement PDF using reportlab.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib import colors


MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "media"))
AGREEMENT_DIR = MEDIA_DIR / "agreements"


HOUSE_RULES = [
    "Rent of {rent} is due on the 1st of every month. Late payment after 5th incurs Rs.100/day penalty.",
    "Security deposit of {deposit} is refundable on checkout after deducting damages and outstanding dues.",
    "Minimum stay period is {lock_in} months. Early exit forfeits the security deposit.",
    "30-day written notice is required before checkout.",
    "No smoking, alcohol, or illegal substances on premises.",
    "Guests allowed only in common areas. No overnight guests.",
    "Quiet hours: 10 PM - 7 AM.",
    "Tenant is responsible for personal belongings. Management is not liable for theft or loss.",
    "Room damage beyond normal wear will be deducted from deposit.",
    "Management may reassign rooms with 7-day notice.",
    "Food plan: {food} as per selected plan.",
    "Violation of rules may lead to termination with 7-day notice.",
]


def _generate_pdf_sync(obs, tenant_data: dict, room, building: str, sharing: str) -> str:
    """Generate agreement PDF. Returns relative path from MEDIA_DIR."""
    save_dir = AGREEMENT_DIR / datetime.now().strftime("%Y-%m")
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"agreement_{obs.token[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = save_dir / filename

    doc = SimpleDocTemplate(str(filepath), pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=15*mm, bottomMargin=15*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title2', parent=styles['Title'], fontSize=16,
                                  textColor=colors.HexColor("#EF1F9C"))
    subtitle_style = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=10,
                                     alignment=TA_CENTER, textColor=colors.grey)
    heading_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=12,
                                    textColor=colors.HexColor("#0095D9"))
    normal = styles['Normal']
    small = ParagraphStyle('Small', parent=normal, fontSize=9)

    elements = []

    # Header
    elements.append(Paragraph("COZEEVO CO-LIVING", title_style))
    elements.append(Paragraph("Rental Agreement", subtitle_style))
    elements.append(Spacer(1, 8*mm))

    # Tenant & Room details table
    rent = f"Rs.{int(obs.agreed_rent or 0):,}"
    deposit = f"Rs.{int(obs.security_deposit or 0):,}"
    maint = f"Rs.{int(obs.maintenance_fee or 0):,}"
    checkin = obs.checkin_date.strftime("%d %b %Y") if obs.checkin_date else ""

    details = [
        ["Tenant Name", tenant_data.get("name", ""), "Room", f"{room.room_number} ({building})"],
        ["Phone", tenant_data.get("phone", ""), "Sharing", sharing],
        ["Gender", tenant_data.get("gender", ""), "Floor", str(room.floor or "")],
        ["Monthly Rent", rent, "Deposit", deposit],
        ["Maintenance", maint, "Check-in", checkin],
        ["Lock-in", f"{obs.lock_in_months or 0} months", "Food", tenant_data.get("food_preference", "")],
    ]

    t = Table(details, colWidths=[35*mm, 50*mm, 30*mm, 50*mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor("#718096")),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor("#718096")),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E8ECF0")),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 6*mm))

    # Special terms
    if obs.special_terms:
        elements.append(Paragraph("Special Terms", heading_style))
        elements.append(Paragraph(obs.special_terms, normal))
        elements.append(Spacer(1, 4*mm))

    # House Rules
    elements.append(Paragraph("Terms & Conditions", heading_style))
    lock_in = str(obs.lock_in_months or 3)
    food = tenant_data.get("food_preference", "Veg")
    for i, rule in enumerate(HOUSE_RULES, 1):
        formatted = rule.format(rent=rent, deposit=deposit, lock_in=lock_in, food=food)
        elements.append(Paragraph(f"{i}. {formatted}", small))
        elements.append(Spacer(1, 1.5*mm))

    elements.append(Spacer(1, 8*mm))

    # Signature
    elements.append(Paragraph("Tenant Signature", heading_style))
    elements.append(Paragraph(
        f"I, {tenant_data.get('name', '')}, confirm that I have read and agree to all terms above.",
        small
    ))
    elements.append(Spacer(1, 3*mm))

    # Embed signature image
    sig_data = obs.signature_image or ""
    if sig_data and "base64," in sig_data:
        try:
            b64 = sig_data.split("base64,")[1]
            img_bytes = base64.b64decode(b64)
            img_buf = io.BytesIO(img_bytes)
            sig_img = Image(img_buf, width=60*mm, height=20*mm)
            elements.append(sig_img)
        except Exception:
            elements.append(Paragraph("[Signature on file]", small))
    else:
        elements.append(Paragraph("[Signature on file]", small))

    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph(
        f"Date: {datetime.now().strftime('%d %b %Y')} | Ref: {obs.token[:8]}",
        ParagraphStyle('Footer', parent=small, textColor=colors.grey)
    ))

    doc.build(elements)
    return str(filepath.relative_to(MEDIA_DIR))


async def generate_agreement_pdf(obs, tenant_data: dict, room, building: str, sharing: str) -> str:
    """Async wrapper for PDF generation."""
    return await asyncio.to_thread(_generate_pdf_sync, obs, tenant_data, room, building, sharing)
```

- [ ] **Step 4: Commit**

```bash
git add src/services/pdf_generator.py requirements.txt
git commit -m "feat: PDF agreement generator using reportlab"
```

---

### Task 4: Mount Router + Serve Form Pages

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add router import and mount in main.py**

After the existing router imports (around line 121-131), add:

```python
from src.api.onboarding_router import router as onboarding_router
app.include_router(onboarding_router)
```

Add route to serve tenant form:

```python
@app.get("/onboard/{token}", response_class=HTMLResponse)
async def serve_onboarding_form(token: str):
    """Serve the tenant onboarding form."""
    import aiofiles
    try:
        async with aiofiles.open("static/onboarding.html", "r") as f:
            html = await f.read()
        return HTMLResponse(html)
    except FileNotFoundError:
        return HTMLResponse("<h1>Form not found</h1>", status_code=404)
```

Add route to serve admin panel:

```python
@app.get("/admin/onboarding", response_class=HTMLResponse)
async def serve_admin_onboarding():
    """Serve the admin onboarding panel."""
    import aiofiles
    try:
        async with aiofiles.open("static/admin_onboarding.html", "r") as f:
            html = await f.read()
        return HTMLResponse(html)
    except FileNotFoundError:
        return HTMLResponse("<h1>Admin panel not found</h1>", status_code=404)
```

- [ ] **Step 2: Commit**

```bash
git add main.py
git commit -m "feat: mount onboarding router, serve form pages"
```

---

### Task 5: Tenant Mobile Form (HTML)

**Files:**
- Create: `static/onboarding.html`

- [ ] **Step 1: Create the tenant form**

This is the full 5-step wizard form. Uses the v6 mockup design — white header with SVG logo, pink primary, blue secondary, signature pad canvas.

The HTML is large (~800 lines). Key sections:
- Header: loads `/static/logo.svg`
- 5-step progress bar
- Step 1: Personal (name, phone, gender, DOB, email, food)
- Step 2: Family (father, emergency contact)
- Step 3: Address & Work (address, occupation, education, office)
- Step 4: ID Proof (type, number)
- Step 5: Agreement summary + terms + signature canvas + submit
- Confirmation screen
- JavaScript: step navigation, validation, signature_pad canvas, API calls to `/api/onboarding/{token}` and `/api/onboarding/{token}/submit`

Write the full file to `static/onboarding.html`. The CSS uses the approved color scheme from the spec (pink `#EF1F9C`, blue `#00AEED`, etc).

- [ ] **Step 2: Test locally**

Start the server and open `/onboard/test-token` in browser to verify layout renders.

- [ ] **Step 3: Commit**

```bash
git add static/onboarding.html
git commit -m "feat: tenant mobile onboarding form (5-step wizard)"
```

---

### Task 6: Admin Onboarding Panel (HTML)

**Files:**
- Create: `static/admin_onboarding.html`

- [ ] **Step 1: Create the admin panel**

Two-section page:
1. **Create Session** — form with room number (auto-fills building/floor/sharing via API), rent, deposit, maintenance, booking amount (if >0: cash/upi prompt), checkin date, stay type, lock-in, special terms, tenant phone. "Generate Link" button.
2. **Review Queue** — table of pending sessions. Click to expand → shows tenant data + signature preview + "Approve" button.

Uses same brand colors. Desktop-optimized layout.

- [ ] **Step 2: Test locally**

Open `/admin/onboarding` in browser, verify create form works.

- [ ] **Step 3: Commit**

```bash
git add static/admin_onboarding.html
git commit -m "feat: admin onboarding panel (create session + review queue)"
```

---

### Task 7: WhatsApp Document Sending

**Files:**
- Modify: `src/whatsapp/webhook_handler.py`

- [ ] **Step 1: Add send_whatsapp_document function**

Add after `_send_whatsapp_interactive`:

```python
async def _send_whatsapp_document(to_number: str, document_url: str, filename: str, caption: str = ""):
    """Send a document via WhatsApp Cloud API."""
    token    = os.getenv("WHATSAPP_TOKEN", "")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    if not (token and phone_id):
        logger.warning("[Meta] WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID not set")
        return

    to = to_number.lstrip("+").replace(" ", "")
    url     = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "link": document_url,
            "filename": filename,
            **({"caption": caption} if caption else {}),
        },
    }
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 200:
            logger.info(f"[Meta] Document sent to {to}: {filename}")
        else:
            logger.error(f"[Meta] Document send failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[Meta] Document send exception: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add src/whatsapp/webhook_handler.py
git commit -m "feat: WhatsApp document sending helper"
```

---

### Task 8: Remove Step-by-Step Checkin Flow

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py`

- [ ] **Step 1: Remove ADD_TENANT_STEP intent handler**

Remove the entire `if pending.intent == "ADD_TENANT_STEP":` block (the step-by-step flow with ask_name, ask_phone, ask_gender, ask_food, ask_room, ask_rent, ask_deposit, ask_advance, ask_advance_mode, ask_maintenance, ask_checkin, ask_personal, ask_dob, ask_age, ask_father_name, etc through confirm).

- [ ] **Step 2: Update _add_tenant_prompt**

Replace the step-by-step flow start in `_add_tenant_prompt` with onboarding link option:

```python
    # ── Start: offer image upload or onboarding link ──────────────────────
    return (
        "*New tenant check-in*\n\n"
        "You can:\n"
        "1. Send a *photo of the registration form* to auto-extract details\n"
        "2. Use the *digital onboarding form* — go to /admin/onboarding to create a link"
    )
```

- [ ] **Step 3: Verify syntax**

```bash
python -c "import py_compile; py_compile.compile('src/whatsapp/handlers/owner_handler.py', doraise=True); print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "refactor: remove step-by-step WhatsApp checkin flow, point to digital form"
```

---

### Task 9: Integration Test

**Files:**
- Create: `tests/test_onboarding_api.py`

- [ ] **Step 1: Write API tests**

```python
"""Tests for onboarding API endpoints."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_create_session(client):
    resp = await client.post("/api/onboarding/create", json={
        "room_number": "609",
        "agreed_rent": 9500,
        "security_deposit": 9500,
        "checkin_date": "2026-04-20",
        "tenant_phone": "9876543210",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "link" in data
    assert data["link"].startswith("/onboard/")


@pytest.mark.asyncio
async def test_get_session(client):
    # Create first
    resp = await client.post("/api/onboarding/create", json={
        "room_number": "609",
        "agreed_rent": 9500,
        "security_deposit": 9500,
        "checkin_date": "2026-04-20",
        "tenant_phone": "9876543210",
    })
    token = resp.json()["token"]

    # Get session data
    resp = await client.get(f"/api/onboarding/{token}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agreed_rent"] == 9500
    assert data["status"] == "pending_tenant"


@pytest.mark.asyncio
async def test_booking_amount_requires_mode(client):
    resp = await client.post("/api/onboarding/create", json={
        "room_number": "609",
        "agreed_rent": 9500,
        "security_deposit": 9500,
        "booking_amount": 5000,
        "advance_mode": "",  # missing!
        "checkin_date": "2026-04-20",
        "tenant_phone": "9876543210",
    })
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_onboarding_api.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_onboarding_api.py
git commit -m "test: onboarding API endpoint tests"
```

---

### Task 10: End-to-End Test in Browser

- [ ] **Step 1: Start local server**

```bash
venv/Scripts/python main.py
```

- [ ] **Step 2: Run migration**

```bash
venv/Scripts/python -m src.database.migrate_all
```

- [ ] **Step 3: Test admin panel**

Open `http://localhost:8000/admin/onboarding` → create a session for room 609 → copy the link.

- [ ] **Step 4: Test tenant form**

Open the generated link → fill all 5 steps → draw signature → submit.

- [ ] **Step 5: Test approve**

Back in admin panel → see pending session → approve → verify tenant created in DB.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: digital onboarding form v1 — complete flow"
```
