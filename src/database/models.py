"""
SQLAlchemy ORM models for PG Accountant — Cozeevo.
Database: Supabase (PostgreSQL via asyncpg).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA LAYER FRAMEWORK  (wipe rules)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
L0 — PERMANENT / NEVER WIPE
  • authorized_users      — who can use the bot (admin, partner, staff)
  • properties            — building info, licenses, bank accounts
  • rooms                 — physical room layout (number, floor, type, staff flag)
  • rate_cards            — pricing history per room
  • staff                 — employee records
  • food_plans            — meal subscription options
  • expense_categories    — expense taxonomy
  • whatsapp_log          — full audit trail of every message, in + out
  • conversation_memory   — bot training data / semantic memory (pgvector)
  • documents             — file registry: receipts, licenses, agreements, IDs
  • investment_expenses   — Whitefield PG setup/construction investment tracker (owner-only)
  • pg_contacts           — vendor/service contacts for Whitefield PG (owner+staff only)

L1 — TENANT MASTER  (re-importable from Excel)
  • tenants               — person records (phone is identity key)
  • tenancies             — one stay = one tenancy row

L2 — FINANCIAL TRANSACTIONS  (re-importable from Excel / receipts)
  • payments              — money received (never delete, use is_void)
  • rent_schedule         — monthly dues ledger
  • refunds               — deposit / overpayment returns
  • expenses              — operating costs (electricity, salary, etc.)

L3 — OPERATIONAL  (can wipe without data loss)
  • leads                 — room enquiries (re-captured naturally)
  • vacations             — tenant absence records
  • reminders             — scheduled alerts
  • rate_limit_log        — spam counters
  • pending_actions       — bot disambiguation state (30-min TTL)
  • onboarding_sessions   — tenant KYC WhatsApp form state (48-hr TTL)
  • checkout_records      — offboarding checklist (keys, damages, dues, deposit)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Role Hierarchy:
  ADMIN       → Kiran — controls everything, adds/removes power users
  POWER_USER  → Partner owners — full business access via WhatsApp
  KEY_USER    → Staff — scoped access (view, log payments for assigned tenants)
  END_USER    → Tenants (read-only own data) + Leads (room enquiry only)

Security:
  - Supabase RLS policies enforced at DB layer (see rls_policies.sql)
  - Python layer enforces role checks before any DB write
  - pgvector (conversation_memory) enables semantic search on chat history

File Storage:
  data/documents/
    receipts/   → payment receipts (PDFs, photos)  [by YYYY-MM]
    licenses/   → property licenses, trade certs, FSSAI
    agreements/ → rental agreements, MoUs
    id_proofs/  → tenant Aadhaar / passport scans
    photos/     → property + room photos
    invoices/   → vendor invoices, utility bills
    imports/    → archived Excel / CSV imports
    exports/    → generated reports
    staff/      → staff contracts, ID proofs
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Numeric, Date, DateTime, Enum,
    ForeignKey, Text, Boolean, Index, UniqueConstraint
)
import os as _os
if _os.getenv("DATABASE_URL", "sqlite").startswith("sqlite"):
    from sqlalchemy import JSON as JSONB  # SQLite fallback
else:
    from sqlalchemy.dialects.postgresql import JSONB  # type: ignore[assignment]
try:
    from pgvector.sqlalchemy import Vector
    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ── Enums ──────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    admin        = "admin"        # Kiran — full access including L0 master data
    owner        = "owner"        # Partners (Lakshmi, Prabhakaran) — all except L0 master data
    receptionist = "receptionist" # Sathyam — payments, individual queries, no financial reports
    end_user     = "end_user"     # Tenants (read-only) + Leads (enquiry only)

class RoomType(str, enum.Enum):
    """Physical room type — based on number of beds in the room."""
    single  = "single"
    double  = "double"
    triple  = "triple"
    premium = "premium"    # single occupancy in a multi-bed room (higher rate)

class SharingType(str, enum.Enum):
    """Tenancy sharing type — how the tenant uses the room. Premium = 1 person in a multi-bed room."""
    single  = "single"
    double  = "double"
    triple  = "triple"
    premium = "premium"

class StayType(str, enum.Enum):
    monthly = "monthly"
    daily   = "daily"

class TenancyStatus(str, enum.Enum):
    active    = "active"
    exited    = "exited"
    cancelled = "cancelled"
    no_show   = "no_show"

class RentStatus(str, enum.Enum):
    pending  = "pending"
    paid     = "paid"
    partial  = "partial"
    waived   = "waived"
    na       = "na"       # tenant not present that month
    exit     = "exit"     # tenant exited mid-month

class PaymentMode(str, enum.Enum):
    cash          = "cash"
    upi           = "upi"
    bank_transfer = "bank_transfer"
    cheque        = "cheque"

class PaymentFor(str, enum.Enum):
    rent        = "rent"
    deposit     = "deposit"
    booking     = "booking"
    maintenance = "maintenance"
    food        = "food"
    penalty     = "penalty"
    other       = "other"

class RefundStatus(str, enum.Enum):
    pending   = "pending"
    processed = "processed"
    cancelled = "cancelled"

class DocumentType(str, enum.Enum):
    receipt    = "receipt"      # payment receipt (PDF / photo)
    license    = "license"      # property / trade / FSSAI license
    agreement  = "agreement"    # rental agreement, MoU
    id_proof   = "id_proof"     # tenant Aadhaar / passport / DL
    photo      = "photo"        # property or room photo
    invoice    = "invoice"      # vendor invoice, utility bill
    import_file = "import_file" # archived Excel / CSV import
    report     = "report"       # generated monthly report
    staff_doc  = "staff_doc"    # staff contract / staff ID proof
    reg_form       = "reg_form"       # tenant registration form (filled, signed)
    checkout_form  = "checkout_form"  # tenant checkout form (filled, signed)
    rules_page     = "rules_page"    # signed rules & regulations page
    other          = "other"

class ReminderType(str, enum.Enum):
    rent_due  = "rent_due"
    follow_up = "follow_up"
    checkout  = "checkout"
    custom    = "custom"

class ComplaintCategory(str, enum.Enum):
    plumbing    = "plumbing"    # leaks, tap, flush, drain
    electricity = "electricity" # bulb, fan, switch, MCB trip
    wifi        = "wifi"        # connectivity, slow, no signal
    food        = "food"        # mess quality, timing, hygiene
    furniture   = "furniture"   # table, chair, bed, mattress, shelf
    other       = "other"       # any other request

class ComplaintStatus(str, enum.Enum):
    open        = "open"
    in_progress = "in_progress"
    resolved    = "resolved"
    closed      = "closed"

class ReminderStatus(str, enum.Enum):
    pending   = "pending"
    sent      = "sent"
    cancelled = "cancelled"

class MessageDirection(str, enum.Enum):
    inbound  = "inbound"
    outbound = "outbound"

class CallerRole(str, enum.Enum):
    owner   = "owner"
    tenant  = "tenant"
    lead    = "lead"
    unknown = "unknown"
    blocked = "blocked"


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — MASTER DATA
# ══════════════════════════════════════════════════════════════════════════════

class Property(Base):
    """A PG building — e.g. Cozeevo THOR, Cozeevo HULK."""
    __tablename__ = "properties"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(120), nullable=False)   # "Cozeevo THOR"
    address     = Column(Text)
    owner_name  = Column(String(120))
    phone       = Column(String(20))
    gstin       = Column(String(20))
    total_rooms = Column(Integer, default=0)
    active          = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    # WiFi credentials — floor-scoped via wifi_floor_map
    wifi_ssid       = Column(String(120))   # property-wide fallback SSID
    wifi_password   = Column(String(120))   # property-wide fallback password
    # e.g. {"1": {"ssid": "PG_Floor1", "password": "abc123"}, "common": {"ssid": "PG_Common", "password": "xyz"}}
    wifi_floor_map  = Column(JSONB, default=dict)

    rooms     = relationship("Room", back_populates="property")
    staff     = relationship("Staff", back_populates="property")
    expenses  = relationship("Expense", back_populates="property")


class Room(Base):
    """A physical room within a property."""
    __tablename__ = "rooms"

    id              = Column(Integer, primary_key=True)
    property_id     = Column(Integer, ForeignKey("properties.id"), nullable=False)
    room_number     = Column(String(20), nullable=False)   # TEXT — "G15", "508/509"
    floor           = Column(Integer)
    room_type       = Column(Enum(RoomType), nullable=False)
    max_occupancy   = Column(Integer, default=1)
    has_ac            = Column(Boolean, default=False)
    has_attached_bath = Column(Boolean, default=False)
    is_staff_room     = Column(Boolean, default=False)   # True = reserved for staff, not tenant
    is_charged        = Column(Boolean, default=True)    # False = owner gives this room free (excluded from rent cost)
    active            = Column(Boolean, default=True)
    notes             = Column(Text)

    property    = relationship("Property", back_populates="rooms")
    rate_cards  = relationship("RateCard", back_populates="room")
    tenancies   = relationship("Tenancy", back_populates="room")

    __table_args__ = (
        UniqueConstraint("property_id", "room_number", name="uq_room_per_property"),
        Index("ix_rooms_property", "property_id"),
    )


class RateCard(Base):
    """
    Room price history. One active row per room (effective_to IS NULL).
    New row added whenever rent changes — old row gets effective_to set.
    """
    __tablename__ = "rate_cards"

    id             = Column(Integer, primary_key=True)
    room_id        = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to   = Column(Date, nullable=True)    # NULL = currently active
    monthly_rent   = Column(Numeric(12, 2))
    daily_rate     = Column(Numeric(10, 2))
    notes          = Column(Text)                   # e.g. "after lock-in period"

    room = relationship("Room", back_populates="rate_cards")

    __table_args__ = (
        Index("ix_rate_cards_room", "room_id"),
        Index("ix_rate_cards_effective", "effective_from"),
    )


class Tenant(Base):
    """
    A person who has stayed or is staying at the PG.
    phone is the WhatsApp identity key — must be unique.
    """
    __tablename__ = "tenants"

    id                              = Column(Integer, primary_key=True)
    name                            = Column(String(120), nullable=False)
    gender                          = Column(String(10))        # male / female / other
    phone                           = Column(String(20), unique=True, nullable=False)
    date_of_birth                   = Column(Date)
    permanent_address               = Column(Text)
    email                           = Column(String(120))
    occupation                      = Column(String(120))       # Present job / student
    father_name                     = Column(String(120))
    father_phone                    = Column(String(20))
    emergency_contact_name          = Column(String(120))
    emergency_contact_phone         = Column(String(20))
    emergency_contact_relationship  = Column(String(60))        # Father / Mother / Sibling etc.
    id_proof_type                   = Column(String(40))        # Aadhar / Passport / DL
    id_proof_number                 = Column(String(60))
    food_preference                 = Column(String(20))        # veg / non-veg / egg
    educational_qualification       = Column(String(120))       # B.Tech / MBA / etc.
    office_address                  = Column(Text)
    office_phone                    = Column(String(20))
    notes                           = Column(Text)
    created_at                      = Column(DateTime, default=datetime.utcnow)

    tenancies = relationship("Tenancy", back_populates="tenant")

    __table_args__ = (
        Index("ix_tenants_phone", "phone"),
    )


class Staff(Base):
    """PG staff — managers, housekeeping, security."""
    __tablename__ = "staff"

    id          = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id"))
    name        = Column(String(120), nullable=False)
    phone       = Column(String(20))
    role        = Column(String(60))     # Manager / Housekeeping / Security
    join_date   = Column(Date)
    exit_date   = Column(Date)           # NULL = still active
    active      = Column(Boolean, default=True)

    property  = relationship("Property", back_populates="staff")
    tenancies = relationship("Tenancy", back_populates="assigned_staff")
    payments  = relationship("Payment", back_populates="received_by_staff")
    refunds   = relationship("Refund", back_populates="processed_by_staff")
    expenses  = relationship("Expense", back_populates="paid_by_staff")


class FoodPlan(Base):
    """Food subscription options offered to tenants."""
    __tablename__ = "food_plans"

    id                 = Column(Integer, primary_key=True)
    name               = Column(String(40), nullable=False)   # veg / non-veg / egg / none
    includes_lunch_box = Column(Boolean, default=False)
    monthly_cost       = Column(Numeric(10, 2), default=0)    # 0 if bundled in rent
    active             = Column(Boolean, default=True)

    tenancies = relationship("Tenancy", back_populates="food_plan")


class ExpenseCategory(Base):
    """Expense categories — supports one level of sub-categories via parent_id."""
    __tablename__ = "expense_categories"

    id        = Column(Integer, primary_key=True)
    name      = Column(String(80), nullable=False, unique=True)
    parent_id = Column(Integer, ForeignKey("expense_categories.id"), nullable=True)
    active    = Column(Boolean, default=True)

    children = relationship("ExpenseCategory")
    expenses = relationship("Expense", back_populates="category")


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — TENANCY (the contract)
# ══════════════════════════════════════════════════════════════════════════════

class Tenancy(Base):
    """
    One row per tenant-room-stay.
    Links tenant + room + all agreed financial terms.
    For daily stays: stay_type='daily', checkout_date = checkin_date + days.
    """
    __tablename__ = "tenancies"

    id                  = Column(Integer, primary_key=True)
    tenant_id           = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    room_id             = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    stay_type           = Column(Enum(StayType), nullable=False, default=StayType.monthly)
    sharing_type        = Column(Enum(SharingType), nullable=True)   # how tenant uses room; premium = occupies all beds
    status              = Column(Enum(TenancyStatus), nullable=False, default=TenancyStatus.active)
    checkin_date        = Column(Date, nullable=False)
    checkout_date       = Column(Date)              # NULL if still active
    expected_checkout   = Column(Date)              # planned exit date
    notice_date         = Column(Date)              # date tenant formally gave notice
    booking_amount      = Column(Numeric(12, 2), default=0)   # advance to reserve
    security_deposit    = Column(Numeric(12, 2), default=0)
    maintenance_fee     = Column(Numeric(10, 2), default=0)   # monthly maintenance
    agreed_rent         = Column(Numeric(12, 2), default=0)   # rent at checkin time
    food_plan_id        = Column(Integer, ForeignKey("food_plans.id"), nullable=True)
    assigned_staff_id   = Column(Integer, ForeignKey("staff.id"), nullable=True)
    lock_in_months      = Column(Integer, default=0)
    lock_in_penalty     = Column(Numeric(12, 2), default=0)
    referral_source     = Column(String(120))
    notes               = Column(Text)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant          = relationship("Tenant", back_populates="tenancies")
    room            = relationship("Room", back_populates="tenancies")
    food_plan       = relationship("FoodPlan", back_populates="tenancies")
    assigned_staff  = relationship("Staff", back_populates="tenancies")
    rent_schedule   = relationship("RentSchedule", back_populates="tenancy")
    payments        = relationship("Payment", back_populates="tenancy")
    refunds         = relationship("Refund", back_populates="tenancy")
    vacations       = relationship("Vacation", back_populates="tenancy")
    reminders       = relationship("Reminder", back_populates="tenancy")
    complaints      = relationship("Complaint", back_populates="tenancy")

    __table_args__ = (
        Index("ix_tenancies_tenant", "tenant_id"),
        Index("ix_tenancies_room", "room_id"),
        Index("ix_tenancies_status", "status"),
        Index("ix_tenancies_checkin", "checkin_date"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — TRANSACTION DATA (money trail)
# ══════════════════════════════════════════════════════════════════════════════

class RentSchedule(Base):
    """
    What a tenant OWES each month.
    One row per tenancy per calendar month.
    Compare against payments to get outstanding balance.
    """
    __tablename__ = "rent_schedule"

    id               = Column(Integer, primary_key=True)
    tenancy_id       = Column(Integer, ForeignKey("tenancies.id"), nullable=False)
    period_month     = Column(Date, nullable=False)      # always 1st of month: 2026-03-01
    rent_due         = Column(Numeric(12, 2), default=0)
    maintenance_due  = Column(Numeric(10, 2), default=0)
    adjustment       = Column(Numeric(12, 2), default=0) # +ve = surcharge, -ve = discount
    adjustment_note  = Column(String(200))               # reason: "water issue concession"
    status           = Column(Enum(RentStatus), default=RentStatus.pending)
    due_date         = Column(Date)                      # usually 1st of month
    notes            = Column(Text)

    tenancy = relationship("Tenancy", back_populates="rent_schedule")

    __table_args__ = (
        UniqueConstraint("tenancy_id", "period_month", name="uq_rent_schedule_month"),
        Index("ix_rent_schedule_tenancy", "tenancy_id"),
        Index("ix_rent_schedule_month", "period_month"),
        Index("ix_rent_schedule_status", "status"),
    )


class Payment(Base):
    """
    Actual money RECEIVED — one row per payment event.
    A tenant may make multiple partial payments for the same month.
    Never delete — use is_void=True to cancel.
    """
    __tablename__ = "payments"

    id                  = Column(Integer, primary_key=True)
    tenancy_id          = Column(Integer, ForeignKey("tenancies.id"), nullable=False)
    amount              = Column(Numeric(12, 2), nullable=False)
    payment_date        = Column(Date, nullable=False)
    payment_mode        = Column(Enum(PaymentMode), nullable=False)
    upi_reference       = Column(String(100))
    for_type            = Column(Enum(PaymentFor), nullable=False, default=PaymentFor.rent)
    period_month        = Column(Date)      # which month rent this is for (NULL for deposit/booking)
    received_by_staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    notes               = Column(Text)
    is_void             = Column(Boolean, default=False)
    created_at          = Column(DateTime, default=datetime.utcnow)

    tenancy           = relationship("Tenancy", back_populates="payments")
    received_by_staff = relationship("Staff", back_populates="payments")

    __table_args__ = (
        Index("ix_payments_tenancy", "tenancy_id"),
        Index("ix_payments_date", "payment_date"),
        Index("ix_payments_period", "period_month"),
        Index("ix_payments_mode", "payment_mode"),
    )


class Refund(Base):
    """Security deposit refunds and overpayment returns."""
    __tablename__ = "refunds"

    id                    = Column(Integer, primary_key=True)
    tenancy_id            = Column(Integer, ForeignKey("tenancies.id"), nullable=False)
    amount                = Column(Numeric(12, 2), nullable=False)
    refund_date           = Column(Date)
    payment_mode          = Column(Enum(PaymentMode))
    upi_reference         = Column(String(100))
    reason                = Column(Text)        # "deposit refund", "overpayment"
    status                = Column(Enum(RefundStatus), default=RefundStatus.pending)
    processed_by_staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    notes                 = Column(Text)
    created_at            = Column(DateTime, default=datetime.utcnow)

    tenancy              = relationship("Tenancy", back_populates="refunds")
    processed_by_staff   = relationship("Staff", back_populates="refunds")

    __table_args__ = (
        Index("ix_refunds_tenancy", "tenancy_id"),
        Index("ix_refunds_status", "status"),
    )


class Expense(Base):
    """
    Operational expenses — electricity, water, staff salary, maintenance, etc.
    Never delete — use is_void=True.
    """
    __tablename__ = "expenses"

    id                = Column(Integer, primary_key=True)
    property_id       = Column(Integer, ForeignKey("properties.id"), nullable=False)
    category_id       = Column(Integer, ForeignKey("expense_categories.id"))
    amount            = Column(Numeric(12, 2), nullable=False)
    expense_date      = Column(Date, nullable=False)
    payment_mode      = Column(Enum(PaymentMode))
    vendor_name       = Column(String(120))
    invoice_reference = Column(String(100))
    description       = Column(Text)
    paid_by_staff_id  = Column(Integer, ForeignKey("staff.id"), nullable=True)
    is_void           = Column(Boolean, default=False)
    notes             = Column(Text)
    created_at        = Column(DateTime, default=datetime.utcnow)

    property       = relationship("Property", back_populates="expenses")
    category       = relationship("ExpenseCategory", back_populates="expenses")
    paid_by_staff  = relationship("Staff", back_populates="expenses")

    __table_args__ = (
        Index("ix_expenses_property", "property_id"),
        Index("ix_expenses_date", "expense_date"),
        Index("ix_expenses_category", "category_id"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — LEADS & BOT
# ══════════════════════════════════════════════════════════════════════════════

class Lead(Base):
    """
    Unknown WhatsApp numbers enquiring about rooms.
    Saved during lead conversation. converted=True when they become a Tenant.
    """
    __tablename__ = "leads"

    id              = Column(Integer, primary_key=True)
    phone           = Column(String(20), unique=True, nullable=False)
    name            = Column(String(120))           # captured during chat
    interested_in   = Column(String(80))            # room type / sharing they asked about
    budget_range    = Column(String(60))            # price range they mentioned
    last_message_at = Column(DateTime)
    converted       = Column(Boolean, default=False)  # True when they become a tenant
    notes           = Column(Text)
    created_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_leads_phone", "phone"),
        Index("ix_leads_converted", "converted"),
    )


class RateLimitLog(Base):
    """
    Anti-spam: tracks message count per phone per time window.
    10 messages per 10-minute window, 50 per day — enforced for ALL callers.
    """
    __tablename__ = "rate_limit_log"

    id            = Column(Integer, primary_key=True)
    phone         = Column(String(20), nullable=False)
    window_start  = Column(DateTime, nullable=False)  # start of 10-min window
    message_count = Column(Integer, default=1)
    day_count     = Column(Integer, default=1)        # messages today
    last_seen_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("phone", "window_start", name="uq_rate_limit_window"),
        Index("ix_rate_limit_phone", "phone"),
        Index("ix_rate_limit_window", "window_start"),
    )


class WhatsappLog(Base):
    """
    Audit trail of all WhatsApp messages in and out.
    Never deleted.
    """
    __tablename__ = "whatsapp_log"

    id                  = Column(Integer, primary_key=True)
    direction           = Column(Enum(MessageDirection), nullable=False)
    caller_role         = Column(Enum(CallerRole))              # owner/tenant/lead/blocked
    from_number         = Column(String(20))
    to_number           = Column(String(20))
    message_text        = Column(Text)
    intent              = Column(String(40))                    # PAYMENT, QUERY_PENDING, HELP...
    linked_entity_type  = Column(String(40))                    # tenancy / payment / lead
    linked_entity_id    = Column(Integer)
    n8n_execution_id    = Column(String(80))                    # for tracing in n8n
    created_at          = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_whatsapp_log_from", "from_number"),
        Index("ix_whatsapp_log_created", "created_at"),
        Index("ix_whatsapp_log_intent", "intent"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 5 — OPERATIONAL
# ══════════════════════════════════════════════════════════════════════════════

class Vacation(Base):
    """Tracks when a tenant is away. May affect billing if affects_billing=True."""
    __tablename__ = "vacations"

    id              = Column(Integer, primary_key=True)
    tenancy_id      = Column(Integer, ForeignKey("tenancies.id"), nullable=False)
    from_date       = Column(Date, nullable=False)
    to_date         = Column(Date, nullable=False)
    affects_billing = Column(Boolean, default=False)
    notes           = Column(Text)

    tenancy = relationship("Tenancy", back_populates="vacations")

    __table_args__ = (
        Index("ix_vacations_tenancy", "tenancy_id"),
    )


class Complaint(Base):
    """
    L3 — Tenant complaints / maintenance requests.
    Raised by tenant via WhatsApp; visible to admin/power_user for follow-up.

    Categories: plumbing, electricity, wifi, food, furniture, other.
    For furniture/other, sub_item captures "table", "chair", "bed sheet", etc.
    """
    __tablename__ = "complaints"

    id          = Column(Integer, primary_key=True)
    tenancy_id  = Column(Integer, ForeignKey("tenancies.id"), nullable=False)
    category    = Column(Enum(ComplaintCategory), nullable=False)
    sub_item    = Column(String(100))              # "bed sheet", "chair", etc.
    description = Column(Text, nullable=False)
    status      = Column(Enum(ComplaintStatus), default=ComplaintStatus.open)
    created_at  = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(20))               # phone of admin/staff who resolved
    notes       = Column(Text)

    tenancy = relationship("Tenancy", back_populates="complaints")

    __table_args__ = (
        Index("ix_complaints_tenancy", "tenancy_id"),
        Index("ix_complaints_status",  "status"),
        Index("ix_complaints_created", "created_at"),
    )


class Reminder(Base):
    """Scheduled follow-ups — rent reminders, checkout alerts, custom notes."""
    __tablename__ = "reminders"

    id            = Column(Integer, primary_key=True)
    tenancy_id    = Column(Integer, ForeignKey("tenancies.id"), nullable=True)
    reminder_type = Column(Enum(ReminderType), nullable=False)
    message       = Column(Text)
    remind_at     = Column(DateTime, nullable=False)
    sent_at       = Column(DateTime)
    status        = Column(Enum(ReminderStatus), default=ReminderStatus.pending)
    created_by    = Column(String(40))  # "bot" or staff phone number

    tenancy = relationship("Tenancy", back_populates="reminders")

    __table_args__ = (
        Index("ix_reminders_status", "status"),
        Index("ix_reminders_remind_at", "remind_at"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 6 — ACCESS CONTROL
# ══════════════════════════════════════════════════════════════════════════════

class AuthorizedUser(Base):
    """
    Dynamic role registry — who can access the bot and at what level.

    Role hierarchy:
      ADMIN      → Kiran — can add/remove users from this table, deploy code
      POWER_USER → Partner owners — full WhatsApp bot access (all tenants, payments, reports)
      KEY_USER   → Staff — scoped access (log payments, view assigned tenants only)
      END_USER   → Auto-assigned to tenants; leads are not in this table

    Seeded at startup: admin (+917845952289) + power_user (+917358341775).
    New partners added by admin via WhatsApp: "add partner +91XXXXXXXXXX"
    """
    __tablename__ = "authorized_users"

    id           = Column(Integer, primary_key=True)
    phone        = Column(String(20), unique=True, nullable=False)
    name         = Column(String(120))
    role         = Column(Enum(UserRole), nullable=False)
    property_id  = Column(Integer, ForeignKey("properties.id"), nullable=True)  # KEY_USER scoped to a property
    added_by     = Column(String(20))    # phone of who added them
    active       = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    deactivated_at = Column(DateTime)

    __table_args__ = (
        Index("ix_authorized_users_phone", "phone"),
        Index("ix_authorized_users_role", "role"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 7 — AI MEMORY (pgvector)
# ══════════════════════════════════════════════════════════════════════════════

class PendingAction(Base):
    """
    Disambiguation state — stores a pending bot action waiting for user confirmation.

    Examples:
      - "Raj paid 15000" → 2 tenants named Raj → ask which one → store choices here
      - "Checkout Kumar" → multiple Kumars → ask which one
      - "Add tenant" → partial form submitted → waiting for missing fields

    Flow:
      1. Bot asks clarifying question → saves PendingAction row
      2. User replies "1" or "2" or full answer
      3. chat_api checks pending actions FIRST → resolves → deletes row → completes action

    Expires after 30 minutes (caller can start fresh).
    """
    __tablename__ = "pending_actions"

    id          = Column(Integer, primary_key=True)
    phone       = Column(String(40), nullable=False)
    intent      = Column(String(40), nullable=False)   # PAYMENT_LOG, CHECKOUT, etc.
    action_data = Column(Text)                          # JSON: {amount, mode, ...}
    choices     = Column(Text)                          # JSON: [{seq, tenant_id, tenancy_id, label}, ...]
    expires_at  = Column(DateTime, nullable=False)
    resolved    = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pending_actions_phone", "phone"),
        Index("ix_pending_actions_expires", "expires_at"),
    )


class OnboardingSession(Base):
    """
    L3 — Tracks multi-step WhatsApp onboarding form for a new tenant.
    Owner triggers START_ONBOARDING → bot walks tenant through KYC questions.
    Expires after 48 hours if not completed.
    step values: ask_gender → ask_emergency_name → ask_emergency_phone →
                 ask_id_type → ask_id_number → done
    """
    __tablename__ = "onboarding_sessions"

    id              = Column(Integer, primary_key=True)
    tenant_id       = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    tenancy_id      = Column(Integer, ForeignKey("tenancies.id"), nullable=True)
    step            = Column(String(40), default="ask_gender")
    collected_data  = Column(Text)       # JSON: filled answers so far
    expires_at      = Column(DateTime, nullable=False)
    completed       = Column(Boolean, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_onboarding_tenant", "tenant_id"),
        Index("ix_onboarding_expires", "expires_at"),
    )


class CheckoutRecord(Base):
    """
    L3 — Offboarding checklist filled by owner/staff when a tenant checks out.
    Captures key returns, damage notes, pending dues, deposit refund date.
    """
    __tablename__ = "checkout_records"

    id                       = Column(Integer, primary_key=True)
    tenancy_id               = Column(Integer, ForeignKey("tenancies.id"), nullable=False, unique=True)
    cupboard_key_returned    = Column(Boolean, default=False)
    main_key_returned        = Column(Boolean, default=False)
    damage_notes             = Column(Text)           # description of any damages
    other_comments           = Column(Text)           # any additional notes
    pending_dues_amount      = Column(Numeric(12, 2), default=0)
    deposit_refunded_amount  = Column(Numeric(12, 2), default=0)
    deposit_refund_date      = Column(Date)           # NULL = not yet refunded
    actual_exit_date         = Column(Date)
    recorded_by              = Column(String(20))     # phone of staff who recorded it
    created_at               = Column(DateTime, default=datetime.utcnow)
    updated_at               = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_checkout_tenancy", "tenancy_id"),
    )


class ConversationMemory(Base):
    """
    Semantic memory for the WhatsApp bot powered by pgvector.
    Each message turn is stored with its embedding (1536-dim for text-embedding-3-small,
    or 768-dim for local models).

    Use cases:
      - "What did Raj say last week about his payment?" → vector similarity search
      - Lead context: remember what a prospect asked across multiple sessions
      - Intent learning: cluster similar messages to improve classification over time

    Requires: CREATE EXTENSION vector; in Supabase (done in rls_policies.sql)
    """
    __tablename__ = "conversation_memory"

    id           = Column(Integer, primary_key=True)
    phone        = Column(String(20), nullable=False)       # who said it
    caller_role  = Column(Enum(CallerRole))
    message_text = Column(Text, nullable=False)
    intent       = Column(String(40))
    # Vector column: 768 dims (Ollama nomic-embed-text) or 1536 (OpenAI)
    # Stored as Text if pgvector not installed — swap to Vector(768) in production
    embedding    = Column(Text)                             # JSON array of floats
    created_at   = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_conv_memory_phone", "phone"),
        Index("ix_conv_memory_created", "created_at"),
    )


class ConversationHistory(Base):
    """
    Simple per-user conversation window for the v2 Supervisor Agent.

    Stores the last N turns (user + bot) so the LangGraph supervisor can
    include chat history in every Groq call — enabling context-aware intent
    classification (e.g. "also wifi is slow" after a payment conversation).

    Auto-pruned to 50 rows per phone by memory.save_turn().
    Different from ConversationMemory (which is pgvector semantic search).
    """
    __tablename__ = "conversation_history"

    id         = Column(Integer, primary_key=True)
    phone      = Column(String(30), nullable=False)
    sent_by    = Column(String(10), nullable=False)  # "user" or "bot"
    message    = Column(Text, nullable=False)
    intent     = Column(String(60))
    role       = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_conv_hist_phone_created", "phone", "created_at"),
    )


class InvestmentExpense(Base):
    """
    L0 — Investment / setup expenses for Whitefield PG (construction phase).
    Source: 'White Field PG Expenses' consolidated sheet (import once, never double).
    Visible to: admin + power_user (owners) only.
    Never delete — use is_void=True.
    """
    __tablename__ = "investment_expenses"

    id               = Column(Integer, primary_key=True)
    sno              = Column(Integer)                      # original S No from Excel
    purpose          = Column(String(500), nullable=False)
    amount           = Column(Numeric(15, 2), nullable=False)
    paid_by          = Column(String(120))                  # investor: Ashokan, Jitendra, Narendra, Chandrasekhar, Kiran Kumar, Prabhakaran
    transaction_date = Column(Date)
    transaction_id   = Column(String(300))                  # UPI ref / bank transfer ID / "Cash"
    paid_to          = Column(String(300))                  # vendor or person paid
    property         = Column(String(60), default="Whitefield")
    unique_hash      = Column(String(64), unique=True, nullable=False)  # SHA-256 dedup key
    is_void          = Column(Boolean, default=False)
    notes            = Column(Text)
    created_at       = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_investment_expenses_paid_by", "paid_by"),
        Index("ix_investment_expenses_date", "transaction_date"),
        Index("ix_investment_expenses_property", "property"),
    )


class PgContact(Base):
    """
    L0 — Vendor and service contacts for Whitefield PG.
    Source: Contacts.xlsx. Visible to owner (admin/power_user) and staff (key_user) only.
    NOT accessible to tenants or leads via WhatsApp bot.
    """
    __tablename__ = "pg_contacts"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(200))
    contact_for = Column(Text)                              # what service/product they provide
    referred_by = Column(String(120))
    phone       = Column(String(30))
    comments    = Column(Text)
    amount_paid = Column(Numeric(12, 2))                    # amount paid to this vendor so far
    remaining   = Column(Text)                              # remaining balance or note
    category    = Column(String(80))                        # plumber / electrician / vendor / supplier etc.
    visible_to  = Column(String(50), default="owner,staff") # access control tag
    property    = Column(String(60), default="Whitefield")
    unique_hash = Column(String(64), unique=True, nullable=False)  # SHA-256 dedup key
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pg_contacts_phone", "phone"),
        Index("ix_pg_contacts_category", "category"),
        Index("ix_pg_contacts_property", "property"),
    )


class Document(Base):
    """
    L0 — File registry. Tracks every uploaded document, receipt, license, image.
    NEVER deleted. Physical files stored under data/documents/<type>/YYYY-MM/

    Folder map:
      receipts/    → payment receipts (PDFs, photos of cash/UPI)
      licenses/    → property licenses, trade certs, FSSAI
      agreements/  → rental agreements, MoUs
      id_proofs/   → tenant Aadhaar / passport / DL scans
      photos/      → property + room photos
      invoices/    → vendor invoices, electricity bills
      imports/     → archived Excel / CSV source files
      exports/     → generated monthly reports
      staff/       → staff contracts, staff ID proofs
    """
    __tablename__ = "documents"

    id            = Column(Integer, primary_key=True)
    doc_type      = Column(Enum(DocumentType), nullable=False)
    file_path     = Column(String(500), nullable=False)    # relative: receipts/2026-03/abc.pdf
    original_name = Column(String(255))                    # original filename as uploaded
    file_size_kb  = Column(Integer)                        # optional, for storage tracking
    mime_type     = Column(String(80))                     # image/jpeg, application/pdf, etc.

    # Optional links — a document can belong to a property, a tenancy, or a specific tenant
    property_id   = Column(Integer, ForeignKey("properties.id"), nullable=True)
    tenancy_id    = Column(Integer, ForeignKey("tenancies.id"), nullable=True)
    tenant_id     = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    staff_id      = Column(Integer, ForeignKey("staff.id"), nullable=True)

    uploaded_by   = Column(String(20))                     # phone of uploader, or "system"
    notes         = Column(Text)
    created_at    = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_documents_type",     "doc_type"),
        Index("ix_documents_property", "property_id"),
        Index("ix_documents_tenancy",  "tenancy_id"),
        Index("ix_documents_tenant",   "tenant_id"),
        Index("ix_documents_created",  "created_at"),
    )


class PendingLearning(Base):
    """
    L3 — Operational (wipe-safe).
    Logged every time the bot receives a message it cannot classify (UNKNOWN after AI fallback).
    Admin reviews these to teach the bot new patterns via the !learn command.
    """
    __tablename__ = "pending_learning"

    id               = Column(Integer, primary_key=True)
    phone            = Column(String(30), nullable=False)       # who sent it
    role             = Column(String(20), default="lead")       # their role at time of message
    message          = Column(Text, nullable=False)             # original unrecognised message
    detected_intent  = Column(String(60), default="UNKNOWN")   # what rules+AI returned
    resolved         = Column(Boolean, default=False)           # True after admin runs !learn
    created_at       = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pending_learning_resolved", "resolved"),
        Index("ix_pending_learning_created",  "created_at"),
    )


class LearnedRule(Base):
    """
    L0 — Permanent. Never wipe.
    Admin-taught intent patterns created via the !learn command.
    Loaded by intent_detector on startup (file-cache, refreshed on change).

    Example: !learn ADD_TENANT new guest, want to join, someone wants room
    → pattern = "new guest|want to join|someone wants room"
    → intent  = "ADD_TENANT"
    """
    __tablename__ = "learned_rules"

    id           = Column(Integer, primary_key=True)
    pattern      = Column(Text, nullable=False)              # pipe-separated regex alternates
    intent       = Column(String(60), nullable=False)        # e.g. ADD_TENANT
    confidence   = Column(Numeric(4, 2), default=0.87)      # assigned confidence score
    applies_to   = Column(String(20), default="all")        # "all", "owner", "tenant", "lead"
    created_by   = Column(String(30))                       # phone of admin who taught this
    active       = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_learned_rules_intent",  "intent"),
        Index("ix_learned_rules_active",  "active"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 8 — BANK STATEMENT ANALYTICS  (L2 financial, re-importable)
# ══════════════════════════════════════════════════════════════════════════════

class BankUpload(Base):
    """
    L2 — One row per bank statement PDF uploaded via WhatsApp.
    Tracks who uploaded it, when, and the date range it covers.
    """
    __tablename__ = "bank_uploads"

    id          = Column(Integer, primary_key=True)
    phone       = Column(String(20), nullable=False)       # uploader's phone
    file_path   = Column(String(500))                      # saved path on server
    row_count   = Column(Integer, default=0)               # transactions parsed
    new_count   = Column(Integer, default=0)               # new (non-duplicate) rows saved
    from_date   = Column(Date, nullable=True)              # earliest txn date in file
    to_date     = Column(Date, nullable=True)              # latest txn date in file
    status      = Column(String(20), default="processed")  # processed | error
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    transactions = relationship("BankTransaction", back_populates="upload")

    __table_args__ = (
        Index("ix_bank_uploads_phone",   "phone"),
        Index("ix_bank_uploads_dates",   "from_date", "to_date"),
    )


class ActivityLogType(str, enum.Enum):
    delivery    = "delivery"      # supplies received
    purchase    = "purchase"      # something bought + paid
    maintenance = "maintenance"   # repair/fix work
    utility     = "utility"       # water tanker, electricity, gas, internet
    supply      = "supply"        # groceries, cleaning items, kitchen supplies
    staff       = "staff"         # staff joined, left, vacation, salary, advance
    visitor     = "visitor"       # owner visit, guest, inspection
    payment     = "payment"       # auto-linked from payment handler
    complaint   = "complaint"     # auto-linked from complaint handler
    checkout    = "checkout"      # auto-linked from checkout handler
    note        = "note"          # general observation


class ActivityLog(Base):
    """
    L3 — Activity log for PG operations.
    Tracks deliveries, purchases, maintenance, notes, and auto-linked events.
    Deduplicated by dedup_hash (date + phone + normalized description).
    """
    __tablename__ = "activity_log"

    id           = Column(Integer, primary_key=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    logged_by    = Column(String(30), nullable=False)     # phone number
    log_type     = Column(Enum(ActivityLogType), default=ActivityLogType.note)
    room         = Column(String(20), nullable=True)
    tenant_name  = Column(String(120), nullable=True)
    description  = Column(Text, nullable=False)
    amount       = Column(Numeric(12, 2), nullable=True)  # only if payment involved
    media_url    = Column(String(500), nullable=True)      # photo/receipt URL
    source       = Column(String(20), default="whatsapp")  # whatsapp | dashboard | system
    linked_id    = Column(Integer, nullable=True)          # FK to payment/complaint/etc
    linked_type  = Column(String(30), nullable=True)       # "payment", "complaint", "expense"
    property_name = Column(String(120), nullable=True)     # THOR or HULK
    dedup_hash   = Column(String(64), nullable=True)       # SHA-256 prevent duplicates

    __table_args__ = (
        Index("ix_activity_log_created", "created_at"),
        Index("ix_activity_log_logged_by", "logged_by"),
        Index("ix_activity_log_type", "log_type"),
        Index("ix_activity_log_room", "room"),
        UniqueConstraint("dedup_hash", name="uq_activity_log_dedup"),
    )


class ChatMessage(Base):
    """
    L0 — Full chat history for every WhatsApp conversation.
    Stores both inbound (user) and outbound (bot) messages with metadata.
    Used for: loading recent context, follow-up detection, analytics.
    Never deleted.
    """
    __tablename__ = "chat_messages"

    id         = Column(Integer, primary_key=True)
    phone      = Column(String(30), nullable=False, index=True)
    direction  = Column(String(10), nullable=False)   # "inbound" or "outbound"
    message    = Column(Text, nullable=False)
    intent     = Column(String(60), nullable=True)     # detected intent for inbound
    role       = Column(String(20), nullable=True)     # admin/power_user/tenant/lead
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_chat_messages_phone_created", "phone", "created_at"),
    )


class BankTransaction(Base):
    """
    L2 — Individual transaction rows extracted from bank statement PDFs.
    Deduplicated by unique_hash (date + amount + description fingerprint).
    Used for P&L reporting, expense analysis, and deposit matching.
    """
    __tablename__ = "bank_transactions"

    id            = Column(Integer, primary_key=True)
    upload_id     = Column(Integer, ForeignKey("bank_uploads.id"), nullable=True)
    txn_date      = Column(Date, nullable=False)
    description   = Column(Text, default="")
    amount        = Column(Numeric(12, 2), nullable=False)
    txn_type      = Column(String(10), default="expense")  # "income" | "expense"
    category      = Column(String(80), default="Other Expenses")
    sub_category  = Column(String(120), default="")
    upi_reference = Column(String(120), nullable=True)
    source        = Column(String(40), default="bank_statement")
    unique_hash   = Column(String(64), nullable=True)       # SHA-256 dedup fingerprint
    created_at    = Column(DateTime, default=datetime.utcnow)

    upload = relationship("BankUpload", back_populates="transactions")

    __table_args__ = (
        Index("ix_btxn_date",       "txn_date"),
        Index("ix_btxn_type",       "txn_type"),
        Index("ix_btxn_category",   "category"),
        Index("ix_btxn_upload",     "upload_id"),
        UniqueConstraint("unique_hash", name="uq_btxn_hash"),
    )
