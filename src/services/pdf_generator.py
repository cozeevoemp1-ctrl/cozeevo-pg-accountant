"""
src/services/pdf_generator.py
Generate signed rental agreement PDF using reportlab.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
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
    "Maintenance Charges are fixed @ {maintenance}/-",
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
    maintenance = f"Rs.{int(obs.maintenance_fee or 0):,}"
    for i, rule in enumerate(HOUSE_RULES, 1):
        formatted = rule.format(rent=rent, deposit=deposit, lock_in=lock_in, food=food, maintenance=maintenance)
        elements.append(Paragraph(f"{i}. {formatted}", small))
        elements.append(Spacer(1, 1.5*mm))

    elements.append(Spacer(1, 8*mm))

    # ── Agreement Confirmation ──
    elements.append(Paragraph(
        f"I, {tenant_data.get('name', '')}, confirm that I have read and agree to all terms above.",
        small
    ))
    elements.append(Spacer(1, 3*mm))

    # Show agreement confirmation with date (no signature boxes).
    # IT Act 2000 §3A: tenant ticks "I agree" — timestamp stored as "I_AGREE:<name>:<iso_ts>".
    sig_data = obs.signature_image or ""
    if sig_data.startswith("I_AGREE:"):
        parts = sig_data.split(":", 2)
        ts_iso = parts[2] if len(parts) > 2 else ""
        agreed_on = ""
        try:
            from datetime import datetime as _dt
            dt_ = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
            agreed_on = dt_.strftime("%d %b %Y, %H:%M")
        except Exception:
            agreed_on = ts_iso[:16] if ts_iso else ""

        agreement_style = ParagraphStyle(
            'Agreement', parent=small, fontSize=10, textColor=colors.HexColor("#00AEED"),
        )
        elements.append(Paragraph(
            f"✓ Agreed on {agreed_on}" if agreed_on else "✓ Agreement accepted",
            agreement_style
        ))
    else:
        elements.append(Paragraph("✓ Agreement accepted", small))

    elements.append(Spacer(1, 5*mm))
    elements.append(Paragraph(
        f"Date: {datetime.now().strftime('%d %b %Y')} | Ref: {obs.token[:8]}",
        ParagraphStyle('Footer', parent=small, textColor=colors.grey)
    ))

    doc.build(elements)
    return str(filepath.relative_to(MEDIA_DIR))


async def generate_agreement_pdf(obs, tenant_data: dict, room, building: str, sharing: str) -> str:
    """Async wrapper for PDF generation."""
    return await asyncio.to_thread(_generate_pdf_sync, obs, tenant_data, room, building, sharing)
