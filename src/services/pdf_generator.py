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
    "If anybody wants to vacate the PG, they should inform 30 days before and vacating notice before 5th of EVERY MONTH. Otherwise 30 days rent must be paid. (Note: should vacate only on 30th or 31st of any month)",
    "Rent should be paid on or before 5th of every calendar month.",
    "Once paid the Advance & Rent cannot be refunded.",
    "Outsiders are strictly not allowed.",
    "Guest Accommodation with / without food will be charged Rs.1200/- per day.",
    "Iron box, Kettle, Induction Stove etc., usage not allowed.",
    "Maintenance Charges are fixed @ Rs. 5000/-",
    "Management is not responsible for your belongings.",
    "Please make sure that all the lights, fans and geysers are SWITCHED OFF before you leave the premises.",
    "Smoking & Liquor not allowed inside the premises of the PG.",
    "Please do not throw garbage out of your window and must keep all premises clean.",
    "In the event of failure to abide by the rules, the paying guest shall vacate the room within 30 days.",
    "Management reserves the right to immediately evict, without exception, any person whose behavior is deemed abnormal, inappropriate, disruptive, or poses risk to others.",
    "In case of late arrival to PG (after 10.30 pm) please inform the in-charge in advance in writing.",
    "Two wheeler wheel lock should be ensured.",
    "Parking space will be provided, but management is not responsible for the vehicles parked for stolen etc.",
    "If you lose the Key, you have to pay Rs.1000/- for duplicate key.",
    "Do not take PG FOOD for outsiders.",
    "If any belongings of owner are damaged, the amount for the item will be deducted from the advance amount.",
]


def _generate_pdf_sync(obs, tenant_data: dict, room, building: str, sharing: str, staff_signature: str = "") -> str:
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

    # Details table
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
    elements.append(Paragraph("Terms &amp; Conditions", heading_style))
    lock_in = str(obs.lock_in_months or 3)
    food = tenant_data.get("food_preference", "Veg")
    for i, rule in enumerate(HOUSE_RULES, 1):
        formatted = rule.format(rent=rent, deposit=deposit, lock_in=lock_in, food=food)
        elements.append(Paragraph(f"{i}. {formatted}", small))
        elements.append(Spacer(1, 1.5*mm))

    elements.append(Spacer(1, 8*mm))

    # ── Signatures (side by side: tenant left, staff right) ──
    elements.append(Paragraph("Signatures", heading_style))
    elements.append(Paragraph(
        f"I, {tenant_data.get('name', '')}, confirm that I have read and agree to all terms above.",
        small
    ))
    elements.append(Spacer(1, 3*mm))

    # Build tenant signature block.
    # New flow (IT Act 2000 §3A): tenant ticks "I agree" — their typed name
    # + timestamp is stored as text token "I_AGREE:<name>:<iso_ts>".
    # Legacy drawn-PNG signatures also still render (pre-migration forms).
    tenant_sig_el = Paragraph("[Signature on file]", small)
    sig_data = obs.signature_image or ""
    if sig_data.startswith("I_AGREE:"):
        parts = sig_data.split(":", 2)
        typed_name = parts[1] if len(parts) > 1 else tenant_data.get("name", "")
        ts_iso = parts[2] if len(parts) > 2 else ""
        signed_on = ""
        try:
            from datetime import datetime as _dt
            dt_ = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
            signed_on = dt_.strftime("%d %b %Y, %H:%M")
        except Exception:
            signed_on = ts_iso[:16] if ts_iso else ""
        cursive_style = ParagraphStyle(
            'CursiveSig', parent=small, fontName='Helvetica-Oblique',
            fontSize=16, textColor=colors.HexColor("#EF1F9C"), leading=18,
        )
        sig_meta_style = ParagraphStyle(
            'SigMeta', parent=small, fontSize=7, textColor=colors.grey,
        )
        tenant_sig_el = Table([
            [Paragraph(typed_name or "—", cursive_style)],
            [Paragraph("✓ Agreed digitally" + (f" — {signed_on}" if signed_on else ""),
                       sig_meta_style)],
        ], colWidths=[70*mm])
        tenant_sig_el.setStyle(TableStyle([
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
    elif sig_data and "base64," in sig_data:
        try:
            b64 = sig_data.split("base64,")[1]
            img_bytes = base64.b64decode(b64)
            tenant_sig_el = Image(io.BytesIO(img_bytes), width=55*mm, height=18*mm)
        except Exception:
            pass

    staff_sig_el = Paragraph("[Awaiting staff signature]", small)
    if staff_signature and "base64," in staff_signature:
        try:
            b64 = staff_signature.split("base64,")[1]
            img_bytes = base64.b64decode(b64)
            staff_sig_el = Image(io.BytesIO(img_bytes), width=55*mm, height=18*mm)
        except Exception:
            pass

    # Two-column signature table
    sig_table_data = [
        [Paragraph("<b>Tenant</b>", small), Paragraph("<b>Authorized Staff</b>", small)],
        [tenant_sig_el, staff_sig_el],
        [Paragraph(tenant_data.get('name', ''), small), Paragraph("Cozeevo Co-living", small)],
    ]
    sig_table = Table(sig_table_data, colWidths=[80*mm, 80*mm])
    sig_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, 1), (0, 1), 0.5, colors.HexColor("#EF1F9C")),
        ('LINEBELOW', (1, 1), (1, 1), 0.5, colors.HexColor("#00AEED")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(sig_table)

    elements.append(Spacer(1, 5*mm))
    elements.append(Paragraph(
        f"Date: {datetime.now().strftime('%d %b %Y')} | Ref: {obs.token[:8]}",
        ParagraphStyle('Footer', parent=small, textColor=colors.grey)
    ))

    doc.build(elements)
    return str(filepath.relative_to(MEDIA_DIR))


async def generate_agreement_pdf(obs, tenant_data: dict, room, building: str, sharing: str, staff_signature: str = "") -> str:
    """Async wrapper for PDF generation."""
    return await asyncio.to_thread(_generate_pdf_sync, obs, tenant_data, room, building, sharing, staff_signature)
