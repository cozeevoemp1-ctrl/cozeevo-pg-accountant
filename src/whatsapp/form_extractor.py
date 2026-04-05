"""
Extract tenant registration form data from photos using Claude Haiku vision.
Saves image+JSON pairs for future Groq fine-tuning.
"""
import os
import json
import base64
from pathlib import Path
from datetime import datetime
from loguru import logger

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Training data directory for future Groq fine-tuning
TRAINING_DIR = Path("data/form_training")

EXTRACTION_PROMPT = """You are extracting data from a PG (paying guest) tenant registration form photo.
The form is from Cozeevo Co-living, Bangalore. It's a standard printed form with handwritten entries.
Extract ALL fields you can read. Return ONLY valid JSON, no markdown, no explanation.

Required JSON structure:
{
  "name": "",
  "phone": "",
  "room_number": "",
  "gender": "",
  "father_name": "",
  "father_phone": "",
  "date_of_birth": "",
  "age": "",
  "permanent_address": "",
  "date_of_admission": "",
  "emergency_contact": "",
  "emergency_relationship": "",
  "email": "",
  "educational_qualification": "",
  "occupation": "",
  "office_address": "",
  "office_phone": "",
  "monthly_rent": "",
  "deposit": "",
  "maintenance": "",
  "rent_remarks": "",
  "deposit_remarks": "",
  "maintenance_remarks": "",
  "id_proof_type": "",
  "id_proof_number": "",
  "food_preference": ""
}

Rules:
- Phone numbers: extract digits only, must be exactly 10 digits for Indian numbers. If you read more or fewer, re-examine carefully.
- Room numbers: typically short like G17, T-201, 102, 301 etc. Not 5+ digit numbers.
- Dates: use DD/MM/YYYY format. The PG opened in 2024, so admission dates should be 2024-2026 range.
- Rent/deposit/maintenance: numbers only, no Rs. or commas
- rent_remarks/deposit_remarks/maintenance_remarks: capture ANY handwritten notes, annotations, conditions, or special terms written near the rent/deposit/maintenance fields. Examples: "including maintenance", "21000 for April & May", "18000 refund on exit", "first 2 months 21k then 22k", "no damage refund". These are agreed terms — capture them exactly as written. If no remarks, use empty string.
- If a field is empty/blank/unreadable, use empty string ""
- For gender, normalize to "male" or "female"
- For food_preference, normalize to "veg", "non-veg", or "egg"
- For id_proof_type, normalize to "aadhar", "voter_id", "passport", "driving_license", or "ration_card"
- Read carefully — handwriting can be messy. Double-check phone numbers and room numbers.
"""


async def _extract_with_haiku(image_bytes: bytes, mime_type: str = "image/jpeg", prompt: str = None) -> dict | None:
    """Extract form data using Claude Haiku (~$0.001/call)."""
    api_key = ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("PASTE_"):
        logger.error("[FormExtract] ANTHROPIC_API_KEY not set. Required for form extraction.")
        return None

    b64 = base64.b64encode(image_bytes).decode()
    media_type = mime_type if mime_type in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg"

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64},
                        },
                        {"type": "text", "text": prompt or EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
        text = msg.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)
    except Exception as e:
        logger.error(f"[FormExtract] Haiku vision failed: {e}")
        return None


async def extract_form_from_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> dict:
    """
    Extract registration form data from image using Claude Haiku.
    Also saves the image+result pair for future Groq fine-tuning.

    Returns:
        {"result": {...}, "provider": "haiku"} on success
        {"result": None, "provider": None} on failure
    """
    result = await _extract_with_haiku(image_bytes, mime_type)
    if result:
        # Save training pair for future Groq fine-tuning
        try:
            _save_training_pair(image_bytes, mime_type, result)
        except Exception as e:
            logger.warning(f"[FormExtract] Failed to save training pair: {e}")
        return {"result": result, "provider": "haiku"}

    return {"result": None, "provider": None}


def _save_training_pair(image_bytes: bytes, mime_type: str, extracted: dict):
    """Save image + extracted JSON for future Groq fine-tuning."""
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    }.get(mime_type, ".jpg")

    # Save image
    img_path = TRAINING_DIR / f"{timestamp}{ext}"
    img_path.write_bytes(image_bytes)

    # Save extracted JSON
    json_path = TRAINING_DIR / f"{timestamp}.json"
    json_path.write_text(json.dumps(extracted, indent=2, ensure_ascii=False), encoding="utf-8")

    count = len(list(TRAINING_DIR.glob("*.json")))
    logger.info(f"[FormExtract] Training pair saved: {timestamp} (total: {count})")
    if count >= 30 and count % 10 == 0:
        logger.info(f"[FormExtract] {count} training pairs collected — consider fine-tuning Groq!")


def format_extracted_data(data: dict, provider: str = "") -> str:
    """Format extracted data as a WhatsApp confirmation message."""
    if not data:
        return "Could not extract any data from the image."

    provider_tag = f" _({provider})_" if provider else ""
    lines = [f"*Extracted from form{provider_tag}:*\n"]

    field_map = [
        ("name", "Name"),
        ("phone", "Phone"),
        ("gender", "Gender"),
        ("room_number", "Room"),
        ("monthly_rent", "Rent"),
        ("rent_remarks", "  Rent terms"),
        ("deposit", "Deposit"),
        ("deposit_remarks", "  Deposit terms"),
        ("maintenance", "Maintenance"),
        ("maintenance_remarks", "  Maint. terms"),
        ("date_of_admission", "Check-in"),
        ("date_of_birth", "DOB"),
        ("father_name", "Father"),
        ("father_phone", "Father Phone"),
        ("permanent_address", "Address"),
        ("emergency_contact", "Emergency"),
        ("emergency_relationship", "Relationship"),
        ("email", "Email"),
        ("educational_qualification", "Education"),
        ("occupation", "Occupation"),
        ("office_address", "Office Address"),
        ("office_phone", "Office Phone"),
        ("id_proof_type", "ID Type"),
        ("id_proof_number", "ID Number"),
        ("food_preference", "Food"),
    ]

    for key, label in field_map:
        val = data.get(key, "")
        if val:
            if key in ("monthly_rent", "deposit", "maintenance"):
                try:
                    lines.append(f"{label}: Rs.{int(float(val)):,}")
                except (ValueError, TypeError):
                    lines.append(f"{label}: {val}")
            else:
                lines.append(f"{label}: {val}")

    return "\n".join(lines)


# ── Checkout form extraction ─────────────────────────────────────────────────

CHECKOUT_EXTRACTION_PROMPT = """You are extracting data from a PG (paying guest) checkout form photo.
The form is from Cozeevo Co-living, Bangalore. It's a printed form with handwritten entries.
Extract ALL fields you can read. Return ONLY valid JSON, no markdown, no explanation.

Required JSON structure:
{
  "name": "",
  "room_number": "",
  "phone": "",
  "checkout_date": "",
  "security_deposit": "",
  "deductions": "",
  "deductions_reason": "",
  "refund_amount": "",
  "refund_mode": "",
  "room_investigation": "",
  "room_key_returned": "",
  "wardrobe_key_returned": "",
  "biometric_removed": "",
  "signature_date": ""
}

Rules:
- Phone numbers: extract digits only, must be exactly 10 digits for Indian numbers
- Room numbers: typically short like G17, T-201, 102, 301 etc
- Dates: use DD/MM/YYYY format. Admission dates should be 2024-2026 range
- Money amounts: numbers only, no Rs. or commas
- refund_mode: normalize to "cash", "upi", or "bank"
- room_investigation: "ok" or "not_ok"
- room_key_returned / wardrobe_key_returned / biometric_removed: "yes" or "no"
- If checkbox is ticked/checked, use "yes". If empty/unchecked, use "no"
- If a field is empty/blank/unreadable, use empty string ""
- Read carefully — handwriting can be messy
"""


async def extract_checkout_form(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> dict:
    """Extract checkout form data from image using Claude Haiku."""
    result = await _extract_with_haiku(image_bytes, mime_type, prompt=CHECKOUT_EXTRACTION_PROMPT)
    if result:
        try:
            _save_training_pair(image_bytes, mime_type, result)
        except Exception:
            pass
        return {"result": result, "provider": "haiku"}
    return {"result": None, "provider": None}


def format_checkout_data(data: dict, provider: str = "") -> str:
    """Format checkout extraction as WhatsApp confirmation message."""
    if not data:
        return "Could not extract any data from the image."

    provider_tag = f" _({provider})_" if provider else ""
    lines = [f"*Checkout form{provider_tag}:*\n"]

    field_map = [
        ("name", "Name"),
        ("room_number", "Room"),
        ("phone", "Phone"),
        ("checkout_date", "Checkout Date"),
        ("security_deposit", "Security Deposit"),
        ("deductions", "Deductions"),
        ("deductions_reason", "  Reason"),
        ("refund_amount", "Refund Amount"),
        ("refund_mode", "Refund Mode"),
        ("room_investigation", "Room Check"),
        ("room_key_returned", "Room Key"),
        ("wardrobe_key_returned", "Wardrobe Key"),
        ("biometric_removed", "Biometric"),
        ("signature_date", "Signed Date"),
    ]

    for key, label in field_map:
        val = data.get(key, "")
        if val:
            if key in ("security_deposit", "deductions", "refund_amount"):
                try:
                    lines.append(f"{label}: Rs.{int(float(val)):,}")
                except (ValueError, TypeError):
                    lines.append(f"{label}: {val}")
            elif key in ("room_key_returned", "wardrobe_key_returned", "biometric_removed"):
                lines.append(f"{label}: {'Returned' if val.lower() == 'yes' else 'NOT returned'}" if 'key' in key
                             else f"{label}: {'Removed' if val.lower() == 'yes' else 'NOT removed'}")
            elif key == "room_investigation":
                lines.append(f"{label}: {'OK' if val.lower() == 'ok' else 'Issues found'}")
            else:
                lines.append(f"{label}: {val}")

    return "\n".join(lines)
