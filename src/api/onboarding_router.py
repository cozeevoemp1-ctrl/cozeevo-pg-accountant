"""
src/api/onboarding_router.py
Onboarding form API — receptionist creates session, tenant fills, receptionist approves.
"""
from __future__ import annotations

import json
import os
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
    sharing_type: str = ""  # single/double/triple — override room default
    agreed_rent: float
    security_deposit: float = 0
    maintenance_fee: float = 0
    booking_amount: float = 0
    advance_mode: str = ""
    checkin_date: str  # ISO YYYY-MM-DD
    stay_type: str = "monthly"
    lock_in_months: int = 0
    special_terms: str = ""
    tenant_phone: str
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
    id_photo: str = ""       # base64 image or PDF data URL
    selfie_photo: str = ""   # base64 image data URL
    signature_image: str     # base64 PNG


# ── Create session (receptionist) ────────────────────────────────────────────

@router.get("/room-lookup/{room_number}")
async def room_lookup(room_number: str):
    """Look up room info for the create form."""
    async with get_session() as session:
        room = await session.scalar(select(Room).where(Room.room_number.ilike(room_number)))
        if not room:
            raise HTTPException(404, "Room not found")
        building = ""
        if room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""
        rt = room.room_type
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")
        return {"room_number": room.room_number, "building": building, "floor": str(room.floor or ""), "sharing": sharing}


@router.post("/create")
async def create_session(req: CreateSessionRequest):
    if req.booking_amount > 0 and not req.advance_mode:
        raise HTTPException(400, "Payment method (cash/upi) required when booking amount > 0")

    async with get_session() as session:
        room = await session.scalar(select(Room).where(Room.room_number.ilike(req.room_number)))
        if not room:
            raise HTTPException(404, f"Room {req.room_number} not found")

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
            expires_at=datetime.utcnow() + timedelta(hours=2),
        )
        session.add(obs)
        await session.flush()

        rt = room.room_type
        sharing = req.sharing_type if req.sharing_type else (rt.value if hasattr(rt, 'value') else str(rt or ""))

        # Calculate dues
        # Deposit already includes maintenance — don't double count
        total_due = float(req.agreed_rent + req.security_deposit - req.booking_amount)
        dues_due = max(0, total_due)

        # Auto-send onboarding link to tenant via WhatsApp
        base_url = os.getenv("BASE_URL", "https://api.getkozzy.com")
        onboard_link = f"{base_url}/onboard/{token}"
        whatsapp_sent = False
        if req.tenant_phone:
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp
                phone_wa = req.tenant_phone.strip()
                if not phone_wa.startswith("91"):
                    phone_wa = "91" + phone_wa
                rent_str = f"Rs.{int(req.agreed_rent):,}" if req.agreed_rent else ""
                deposit_str = f"Rs.{int(req.security_deposit):,}" if req.security_deposit else ""
                booking_str = f"Rs.{int(req.booking_amount):,}" if req.booking_amount else ""
                dues_str = f"Rs.{int(dues_due):,}"

                summary_lines = [f"Hello! Welcome to *Cozeevo Co-living*\n"]
                summary_lines.append(f"Room *{room.room_number}* ({building}) — {sharing}")
                if rent_str: summary_lines.append(f"Rent: {rent_str}/month")
                if deposit_str: summary_lines.append(f"Security Deposit (incl. maintenance): {deposit_str}")
                if booking_str: summary_lines.append(f"Advance Paid: {booking_str}")
                summary_lines.append(f"\n*Amount due at check-in: {dues_str}*")
                summary_lines.append(f"\nPlease complete your registration:\n{onboard_link}")
                summary_lines.append(f"\nThis link is valid for 2 hours.\nFor any questions, contact us on this number.")

                await _send_whatsapp(phone_wa, "\n".join(summary_lines))
                whatsapp_sent = True
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("WhatsApp onboarding link send failed: %s", e)

        return {
            "token": token,
            "link": f"/onboard/{token}",
            "full_link": onboard_link,
            "session_id": obs.id,
            "whatsapp_sent": whatsapp_sent,
            "dues_due": dues_due,
            "room": {"number": room.room_number, "building": building, "floor": str(room.floor or ""), "sharing": sharing},
        }


# ── List pending sessions (admin) ────────────────────────────────────────────

@router.get("/admin/stats")
async def onboarding_stats(date_from: str = "", date_to: str = ""):
    """Onboarding stats with optional date filter."""
    from sqlalchemy import func
    async with get_session() as session:
        q = select(OnboardingSession.status, func.count()).group_by(OnboardingSession.status)
        if date_from:
            q = q.where(OnboardingSession.created_at >= date.fromisoformat(date_from))
        if date_to:
            q = q.where(OnboardingSession.created_at < date.fromisoformat(date_to) + timedelta(days=1))
        result = await session.execute(q)
        counts = {row[0]: row[1] for row in result.all()}

        # Today's approved count
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_q = select(func.count()).where(
            OnboardingSession.status == "approved",
            OnboardingSession.approved_at >= today_start
        )
        today_approved = await session.scalar(today_q) or 0

        return {
            "total": sum(counts.values()),
            "approved": counts.get("approved", 0),
            "pending_tenant": counts.get("pending_tenant", 0),
            "pending_review": counts.get("pending_review", 0),
            "cancelled": counts.get("cancelled", 0),
            "expired": counts.get("expired", 0),
            "today_approved": today_approved,
        }


@router.get("/admin/pending")
async def list_pending():
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


# ── Cancel session (admin) ─────────────────────────────────────────────────────

@router.post("/admin/{token}/cancel")
async def cancel_session(token: str):
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status in ("approved", "cancelled"):
            raise HTTPException(400, f"Cannot cancel — status is {obs.status}")
        obs.status = "cancelled"
        await session.commit()
        return {"status": "cancelled", "token": token}


# ── Resend WhatsApp link (admin) ───────────────────────────────────────────────

@router.post("/admin/{token}/resend")
async def resend_link(token: str):
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status not in ("pending_tenant", "pending_review"):
            raise HTTPException(400, f"Cannot resend — status is {obs.status}")

        base_url = os.getenv("BASE_URL", "https://api.getkozzy.com")
        onboard_link = f"{base_url}/onboard/{token}"

        if not obs.tenant_phone:
            raise HTTPException(400, "No tenant phone on this session")

        from src.whatsapp.webhook_handler import _send_whatsapp
        phone_wa = obs.tenant_phone.strip()
        if not phone_wa.startswith("91"):
            phone_wa = "91" + phone_wa
        await _send_whatsapp(
            phone_wa,
            f"Reminder from *Cozeevo Co-living*\n\n"
            f"Please complete your registration:\n{onboard_link}\n\n"
            f"This link is valid for 2 hours."
        )
        return {"status": "sent", "token": token}


# ── Get session data (tenant form) ───────────────────────────────────────────

@router.get("/{token}")
async def get_session_data(token: str):
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
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
            "room": {"number": room.room_number if room else "", "building": building, "floor": str(room.floor or "") if room else "", "sharing": sharing},
            "agreed_rent": float(obs.agreed_rent or 0),
            "security_deposit": float(obs.security_deposit or 0),
            "maintenance_fee": float(obs.maintenance_fee or 0),
            "booking_amount": float(obs.booking_amount or 0),
            "advance_mode": obs.advance_mode or "",
            "stay_type": obs.stay_type or "",
            "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
            "lock_in_months": obs.lock_in_months or 0,
            "special_terms": obs.special_terms or "",
            "tenant_data": json.loads(obs.tenant_data) if obs.tenant_data else None,
            "signature_image": obs.signature_image or "",
        }


# ── Tenant submits form ──────────────────────────────────────────────────────

@router.post("/{token}/submit")
async def tenant_submit(token: str, req: TenantSubmitRequest):
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status != "pending_tenant":
            raise HTTPException(400, f"Cannot submit — status is {obs.status}")
        if obs.expires_at and obs.expires_at < datetime.utcnow():
            obs.status = "expired"
            raise HTTPException(410, "This onboarding link has expired")

        # Save uploaded files to disk
        from pathlib import Path
        import base64 as b64mod
        media_dir = Path(os.getenv("MEDIA_DIR", "media"))
        token_short = obs.token[:8]
        saved_files = {}

        for field_name, data_url in [("selfie", req.selfie_photo), ("id_proof", req.id_photo)]:
            if not data_url or "base64," not in data_url:
                continue
            try:
                header, b64_data = data_url.split("base64,", 1)
                # Detect file type
                if "pdf" in header:
                    ext = ".pdf"
                elif "png" in header:
                    ext = ".png"
                elif "webp" in header:
                    ext = ".webp"
                else:
                    ext = ".jpg"
                save_dir = media_dir / "onboarding" / token_short
                save_dir.mkdir(parents=True, exist_ok=True)
                file_path = save_dir / f"{field_name}{ext}"
                file_path.write_bytes(b64mod.b64decode(b64_data))
                saved_files[field_name] = str(file_path.relative_to(media_dir))
            except Exception:
                pass  # non-fatal — form still submits

        # Save signature to disk too
        if req.signature_image and "base64," in req.signature_image:
            try:
                _, sig_b64 = req.signature_image.split("base64,", 1)
                save_dir = media_dir / "onboarding" / token_short
                save_dir.mkdir(parents=True, exist_ok=True)
                sig_path = save_dir / "signature.png"
                sig_path.write_bytes(b64mod.b64decode(sig_b64))
                saved_files["signature"] = str(sig_path.relative_to(media_dir))
            except Exception:
                pass

        tenant_data = req.model_dump(exclude={"signature_image", "id_photo", "selfie_photo"})
        tenant_data["_saved_files"] = saved_files  # paths for approve step
        obs.tenant_data = json.dumps(tenant_data)
        obs.signature_image = req.signature_image
        obs.status = "pending_review"
        obs.completed_at = datetime.utcnow()

        # Notify receptionist via WhatsApp
        if obs.created_by_phone:
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp
                notify_phone = obs.created_by_phone.strip()
                if not notify_phone.startswith("91"):
                    notify_phone = "91" + notify_phone
                room = await session.get(Room, obs.room_id) if obs.room_id else None
                room_str = room.room_number if room else "—"
                await _send_whatsapp(
                    notify_phone,
                    f"*Onboarding form submitted*\n\n"
                    f"Tenant: *{req.name}*\n"
                    f"Phone: {req.phone}\n"
                    f"Room: {room_str}\n\n"
                    f"Please review and approve:\n"
                    f"{os.getenv('BASE_URL', 'https://api.getkozzy.com')}/admin/onboarding"
                )
            except Exception:
                pass  # non-fatal

        return {"status": "pending_review", "message": "Submitted. Receptionist will review."}


# ── Approve session (admin) ──────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    staff_signature: str = ""  # base64 PNG data URL


@router.post("/{token}/approve")
async def approve_session(token: str, req: ApproveRequest = None):
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
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
                name=td["name"], phone=phone, gender=td.get("gender"),
                food_preference=td.get("food_preference"), email=td.get("email"),
                father_name=td.get("father_name"), father_phone=td.get("father_phone"),
                emergency_contact_name=td.get("emergency_contact_name"),
                emergency_contact_phone=td.get("emergency_contact_phone"),
                emergency_contact_relationship=td.get("emergency_contact_relationship"),
                permanent_address=td.get("permanent_address"), occupation=td.get("occupation"),
                educational_qualification=td.get("educational_qualification"),
                office_address=td.get("office_address"), office_phone=td.get("office_phone"),
                id_proof_type=td.get("id_proof_type"), id_proof_number=td.get("id_proof_number"),
            )
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

        rt = room.room_type
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")
        checkin = obs.checkin_date or date.today()

        tenancy = Tenancy(
            tenant_id=tenant.id, room_id=room.id, checkin_date=checkin,
            agreed_rent=obs.agreed_rent or 0, security_deposit=obs.security_deposit or 0,
            booking_amount=obs.booking_amount or 0, maintenance_fee=obs.maintenance_fee or 0,
            lock_in_months=obs.lock_in_months or 0,
            status=TenancyStatus.active if checkin <= date.today() else TenancyStatus.no_show,
        )
        session.add(tenancy)
        await session.flush()

        # RentSchedule
        period = checkin.replace(day=1)
        current_month = date.today().replace(day=1)
        while period <= current_month:
            session.add(RentSchedule(
                tenancy_id=tenancy.id, period_month=period,
                rent_due=obs.agreed_rent or 0, maintenance_due=obs.maintenance_fee or 0,
                status=RentStatus.pending, due_date=period,
            ))
            if period.month == 12:
                period = date(period.year + 1, 1, 1)
            else:
                period = date(period.year, period.month + 1, 1)

        # Advance payment
        if obs.booking_amount and obs.booking_amount > 0:
            adv_mode = PaymentMode.upi if obs.advance_mode == "upi" else PaymentMode.cash
            session.add(Payment(
                tenancy_id=tenancy.id, amount=obs.booking_amount,
                payment_date=checkin, payment_mode=adv_mode,
                for_type=PaymentFor.booking, period_month=checkin.replace(day=1),
                notes=f"Booking advance ({obs.advance_mode})",
            ))

        obs.status = "approved"
        obs.approved_at = datetime.utcnow()
        obs.tenant_id = tenant.id
        obs.tenancy_id = tenancy.id

        # GSheets (fire and forget)
        gsheets_note = ""
        try:
            from src.integrations.gsheets import add_tenant as gsheets_add
            gs_r = await gsheets_add(
                room_number=room.room_number, name=td["name"], phone=phone,
                gender=td.get("gender", ""), building=building,
                floor=str(room.floor or ""), sharing=sharing,
                checkin=checkin.strftime("%d/%m/%Y"),
                agreed_rent=float(obs.agreed_rent or 0), deposit=float(obs.security_deposit or 0),
                booking=float(obs.booking_amount or 0), maintenance=float(obs.maintenance_fee or 0),
                notes=obs.special_terms or "",
                dob=td.get("date_of_birth", ""), father_name=td.get("father_name", ""),
                father_phone=td.get("father_phone", ""), address=td.get("permanent_address", ""),
                emergency_contact=td.get("emergency_contact_phone", ""),
                emergency_relationship=td.get("emergency_contact_relationship", ""),
                email=td.get("email", ""), occupation=td.get("occupation", ""),
                education=td.get("educational_qualification", ""),
                office_address=td.get("office_address", ""), office_phone=td.get("office_phone", ""),
                id_type=td.get("id_proof_type", ""), id_number=td.get("id_proof_number", ""),
                food_pref=td.get("food_preference", ""), entered_by="onboarding_form",
                advance_amount=float(obs.booking_amount or 0), advance_mode=obs.advance_mode or "",
            )
            if gs_r.get("success"):
                gsheets_note = " | Sheet updated"
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("GSheets onboarding: %s", e)

        # Save staff signature to disk
        staff_sig_path = ""
        if req and req.staff_signature and "base64," in req.staff_signature:
            try:
                import base64 as b64mod
                from pathlib import Path
                media_dir = Path(os.getenv("MEDIA_DIR", "media"))
                _, sig_b64 = req.staff_signature.split("base64,", 1)
                save_dir = media_dir / "onboarding" / obs.token[:8]
                save_dir.mkdir(parents=True, exist_ok=True)
                sig_file = save_dir / "staff_signature.png"
                sig_file.write_bytes(b64mod.b64decode(sig_b64))
                staff_sig_path = str(sig_file.relative_to(media_dir))
            except Exception:
                pass

        # PDF generation (includes both tenant + staff signatures)
        try:
            from src.services.pdf_generator import generate_agreement_pdf
            pdf_path = await generate_agreement_pdf(
                obs, td, room, building, sharing,
                staff_signature=req.staff_signature if req else "",
            )
            obs.agreement_pdf_path = pdf_path
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("PDF generation failed: %s", e)

        # Save documents (selfie, ID proof, signature, agreement PDF) linked to tenant
        from src.database.models import Document, DocumentType
        saved_files = td.get("_saved_files", {})
        doc_map = {
            "selfie": DocumentType.photo,
            "id_proof": DocumentType.id_proof,
            "signature": DocumentType.photo,
        }
        for file_key, doc_type in doc_map.items():
            file_path = saved_files.get(file_key)
            if file_path:
                session.add(Document(
                    doc_type=doc_type,
                    file_path=file_path,
                    original_name=f"{file_key}_{td.get('name', 'tenant')}",
                    mime_type="image/png" if file_key == "signature" else "image/jpeg",
                    tenant_id=tenant.id,
                    tenancy_id=tenancy.id,
                ))
        # Agreement PDF as document
        if obs.agreement_pdf_path:
            session.add(Document(
                doc_type=DocumentType.agreement,
                file_path=obs.agreement_pdf_path,
                original_name=f"agreement_{td.get('name', 'tenant')}",
                mime_type="application/pdf",
                tenant_id=tenant.id,
                tenancy_id=tenancy.id,
            ))

        # Send signed PDF to tenant via WhatsApp
        whatsapp_note = ""
        if obs.agreement_pdf_path and obs.tenant_phone:
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp_document, _send_whatsapp
                from pathlib import Path
                # Build public URL for the PDF
                base_url = os.getenv("BASE_URL", "https://api.getkozzy.com")
                pdf_url = f"{base_url}/static/agreements/{obs.agreement_pdf_path}"
                # Also copy PDF to static dir so it's accessible
                media_dir = Path(os.getenv("MEDIA_DIR", "media"))
                src_pdf = media_dir / obs.agreement_pdf_path
                static_pdf_dir = Path("static/agreements") / Path(obs.agreement_pdf_path).parent.name
                static_pdf_dir.mkdir(parents=True, exist_ok=True)
                static_pdf = static_pdf_dir / Path(obs.agreement_pdf_path).name
                if src_pdf.exists():
                    import shutil
                    shutil.copy2(str(src_pdf), str(static_pdf))

                phone_wa = obs.tenant_phone.strip()
                if not phone_wa.startswith("91"):
                    phone_wa = "91" + phone_wa
                await _send_whatsapp(
                    phone_wa,
                    f"Welcome to Cozeevo, {td.get('name', '')}! 🏠\n\n"
                    f"Your registration for Room {room.room_number} is confirmed.\n"
                    f"Check-in: {checkin.strftime('%d %b %Y')}\n\n"
                    f"Your signed rental agreement is attached below."
                )
                await _send_whatsapp_document(
                    phone_wa,
                    pdf_url,
                    f"Cozeevo_Agreement_{td.get('name', '').replace(' ', '_')}.pdf",
                    "Your signed rental agreement"
                )
                whatsapp_note = " | WhatsApp sent"
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("WhatsApp PDF delivery failed: %s", e)

        return {
            "status": "approved", "tenant_id": tenant.id, "tenancy_id": tenancy.id,
            "message": f"Tenant {td['name']} created{gsheets_note}{whatsapp_note}",
        }
