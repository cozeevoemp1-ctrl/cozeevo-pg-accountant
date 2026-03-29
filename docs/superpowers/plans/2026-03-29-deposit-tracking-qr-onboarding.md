# Deposit Tracking + QR Self-Check-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track partial deposit/advance payments with remaining balance visibility, and enable tenant self-check-in via QR code with photo ID uploads.

**Architecture:** Phase 1 adds an "advance paid" step to the add-tenant flow, stores in existing `booking_amount` field, shows remaining deposit in queries and sheet. Phase 2 extends the existing OnboardingSession system with photo upload steps, adds media intake to chat_api.py, and wires the QR-triggered flow with receptionist approval before DB commit.

**Tech Stack:** FastAPI, SQLAlchemy (asyncpg), gspread, WhatsApp Cloud API (media download), Supabase Storage (optional, or local disk).

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `src/whatsapp/handlers/owner_handler.py` | Modify | Add ask_advance step, show deposit gap in confirmation |
| `src/integrations/gsheets.py` | Modify | Pass booking_amount to sheet write |
| `src/whatsapp/handlers/tenant_handler.py` | Modify | Add photo upload steps to onboarding, save documents |
| `src/whatsapp/chat_api.py` | Modify | Add media message intake (image/document parsing) |
| `src/whatsapp/media_handler.py` | Create | Download + save WhatsApp media files |
| `src/database/models.py` | No change | All models already exist |
| `tests/test_deposit_tracking.py` | Create | Tests for deposit flow |
| `tests/test_qr_onboarding.py` | Create | Tests for QR + photo onboarding |

---

## Phase 1: Deposit/Advance Tracking

### Task 1: Add "advance paid" step to add-tenant flow

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py:543-600`

- [ ] **Step 1: Add ask_advance step after ask_deposit**

In the ADD_TENANT_STEP handler, after `ask_deposit` (which stores the total deposit amount), add a new step that asks how much was actually paid:

```python
        if step == "ask_deposit":
            action_data["deposit"] = _parse_amount_field(ans)
            deposit = action_data["deposit"]
            if deposit > 0:
                action_data["step"] = "ask_advance"
                await _save_pending(pending.phone, "ADD_TENANT_STEP", action_data, [], session)
                return f"Deposit is Rs.{int(deposit):,}.\n\n*How much paid now?* (amount, or *full* if fully paid)"
            else:
                action_data["advance"] = 0
                action_data["step"] = "ask_maintenance"
                await _save_pending(pending.phone, "ADD_TENANT_STEP", action_data, [], session)
                return "*Maintenance fee?* (number, or *skip*)"

        if step == "ask_advance":
            deposit = action_data.get("deposit", 0)
            if ans.lower() in ("full", "all", "complete", "done", "paid"):
                action_data["advance"] = deposit
            else:
                adv = _parse_amount_field(ans)
                if adv < 0:
                    return "__KEEP_PENDING__Amount can't be negative. *How much paid now?*"
                if adv > deposit:
                    return f"__KEEP_PENDING__Can't pay more than deposit (Rs.{int(deposit):,}). *How much paid now?*"
                action_data["advance"] = adv
            action_data["step"] = "ask_maintenance"
            await _save_pending(pending.phone, "ADD_TENANT_STEP", action_data, [], session)
            adv = action_data["advance"]
            remaining = deposit - adv
            if remaining > 0:
                return f"Paid: Rs.{int(adv):,} | Remaining: Rs.{int(remaining):,} due on check-in.\n\n*Maintenance fee?* (number, or *skip*)"
            return "*Maintenance fee?* (number, or *skip*)"
```

- [ ] **Step 2: Update confirmation message to show deposit breakdown**

In the `ask_notes` step where confirmation is built, update deposit line:

```python
            deposit = int(action_data.get("deposit", 0))
            advance = int(action_data.get("advance", 0))
            deposit_remaining = deposit - advance

            # In the confirmation string:
            + f"Deposit: Rs.{deposit:,}"
            + (f" (Paid: Rs.{advance:,} | Due: Rs.{deposit_remaining:,})" if 0 < advance < deposit else "")
            + "\n"
```

- [ ] **Step 3: Pass advance to form_data in confirm step**

The `form_data` dict in the confirm step already has `"advance": 0`. Change to:

```python
                    "advance": action_data.get("advance", 0),
```

- [ ] **Step 4: Verify _do_add_tenant already handles advance correctly**

Already creates Payment with `for_type=PaymentFor.booking` when advance > 0. Already writes to sheet Booking column. No changes needed.

- [ ] **Step 5: Run test and commit**

```bash
cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant"
# Test via direct Python call (same pattern as earlier tests)
# Then commit
git add src/whatsapp/handlers/owner_handler.py
git commit -m "feat: deposit tracking — ask how much paid, show remaining balance"
```

### Task 2: Show deposit gap in tenant queries

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py` (query_tenant section)
- Modify: `src/whatsapp/handlers/tenant_handler.py` (_my_balance)

- [ ] **Step 1: Find _query_tenant and add deposit info**

In `_query_tenant`, after showing rent dues, add:

```python
    # Deposit status
    if tenancy.security_deposit and tenancy.security_deposit > 0:
        dep = int(tenancy.security_deposit)
        paid = int(tenancy.booking_amount or 0)
        remaining = dep - paid
        if remaining > 0:
            lines.append(f"Deposit: Rs.{dep:,} (Paid: Rs.{paid:,} | *Due: Rs.{remaining:,}*)")
        else:
            lines.append(f"Deposit: Rs.{dep:,} (Fully paid)")
```

- [ ] **Step 2: Add to tenant self-service _my_balance**

Same logic in tenant_handler.py `_my_balance`.

- [ ] **Step 3: Test and commit**

---

## Phase 2: QR Self-Check-in with Photo Uploads

### Task 3: Add media message intake to chat_api

**Files:**
- Modify: `src/whatsapp/chat_api.py:44-48`
- Create: `src/whatsapp/media_handler.py`

- [ ] **Step 1: Extend InboundMessage to accept media**

```python
class InboundMessage(BaseModel):
    phone:      str
    message:    str
    message_id: Optional[str] = None
    media_type: Optional[str] = None    # "image", "document", "video"
    media_id:   Optional[str] = None    # WhatsApp media ID
    media_url:  Optional[str] = None    # direct URL if available
    media_mime: Optional[str] = None    # "image/jpeg", "application/pdf"
    media_filename: Optional[str] = None
```

- [ ] **Step 2: Create media_handler.py**

```python
"""
Download and save WhatsApp media files to local storage.
Uses WhatsApp Cloud API to retrieve media by ID.
"""
import os
import httpx
from pathlib import Path
from datetime import datetime
from loguru import logger

MEDIA_DIR = Path(os.getenv("DATA_DOCUMENTS_DIR", "./data/documents"))
WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")

async def download_whatsapp_media(
    media_id: str,
    mime_type: str,
    subfolder: str = "id_proofs",
    filename_prefix: str = "",
) -> str | None:
    """
    Download media from WhatsApp Cloud API, save to disk.
    Returns relative file path or None on failure.
    """
    try:
        # Step 1: Get media URL from WhatsApp
        headers = {"Authorization": f"Bearer {WA_TOKEN}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers=headers,
            )
            resp.raise_for_status()
            media_url = resp.json().get("url")

            if not media_url:
                logger.warning(f"No URL returned for media_id {media_id}")
                return None

            # Step 2: Download the actual file
            file_resp = await client.get(media_url, headers=headers)
            file_resp.raise_for_status()

        # Step 3: Save to disk
        ext = _mime_to_ext(mime_type)
        month_dir = datetime.now().strftime("%Y-%m")
        save_dir = MEDIA_DIR / subfolder / month_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{timestamp}{ext}" if filename_prefix else f"{timestamp}{ext}"
        file_path = save_dir / filename

        file_path.write_bytes(file_resp.content)
        logger.info(f"Media saved: {file_path} ({len(file_resp.content)} bytes)")

        # Return relative path from MEDIA_DIR
        return str(file_path.relative_to(MEDIA_DIR))

    except Exception as e:
        logger.error(f"Media download failed: {e}")
        return None


def _mime_to_ext(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(mime_type, ".bin")
```

- [ ] **Step 3: Wire media into onboarding flow in chat_api.py**

In the onboarding section of `_process_message_inner`, pass media info:

```python
        if ob:
            if ob.step == "ask_gender" and message.lower() in (...):
                reply = welcome + Q1
            else:
                reply = await handle_onboarding_step(
                    ob, message, ctx, session,
                    media_id=body.media_id,
                    media_type=body.media_type,
                    media_mime=body.media_mime,
                )
```

- [ ] **Step 4: Commit**

### Task 4: Add photo upload steps to onboarding

**Files:**
- Modify: `src/whatsapp/handlers/tenant_handler.py:699-855`

- [ ] **Step 1: Add photo steps to _ONBOARDING_STEPS**

After `ask_id_number`, add:

```python
_ONBOARDING_STEPS = [
    "ask_dob", "ask_father_name", "ask_father_phone",
    "ask_address", "ask_email", "ask_occupation",
    "ask_gender",
    "ask_emergency_name", "ask_emergency_relationship", "ask_emergency_phone",
    "ask_id_type", "ask_id_number",
    "ask_id_photo",       # NEW: upload photo of ID
    "ask_selfie",         # NEW: upload selfie for verification
    "done",
]

_ONBOARDING_QUESTIONS["ask_id_photo"] = "Please *send a photo* of your ID proof (Aadhar/PAN card). Or type *skip*."
_ONBOARDING_QUESTIONS["ask_selfie"] = "Please *send a selfie* for verification. Or type *skip*."
```

- [ ] **Step 2: Handle photo upload in handle_onboarding_step**

```python
    elif step in ("ask_id_photo", "ask_selfie"):
        if not skip:
            if media_id and media_type == "image":
                from src.whatsapp.media_handler import download_whatsapp_media
                from src.database.models import Document, DocumentType
                subfolder = "id_proofs" if step == "ask_id_photo" else "photos"
                prefix = f"tenant_{ob.tenant_id}_{step.replace('ask_', '')}"
                file_path = await download_whatsapp_media(
                    media_id, media_mime or "image/jpeg",
                    subfolder=subfolder, filename_prefix=prefix,
                )
                if file_path:
                    doc = Document(
                        doc_type=DocumentType.id_proof if step == "ask_id_photo" else DocumentType.photo,
                        file_path=file_path,
                        original_name=f"{step}_{ob.tenant_id}",
                        mime_type=media_mime or "image/jpeg",
                        tenant_id=ob.tenant_id,
                        uploaded_by=ctx.phone,
                        notes=step.replace("ask_", "").replace("_", " ").title(),
                    )
                    session.add(doc)
                    data[step] = file_path
                else:
                    data[step] = "upload_failed"
            else:
                return f"__KEEP_PENDING__Please *send a photo* (not text). Or type *skip*."
```

- [ ] **Step 3: Update handle_onboarding_step signature**

```python
async def handle_onboarding_step(
    ob: OnboardingSession,
    reply_text: str,
    ctx: CallerContext,
    session: AsyncSession,
    media_id: Optional[str] = None,
    media_type: Optional[str] = None,
    media_mime: Optional[str] = None,
) -> str:
```

- [ ] **Step 4: Commit**

### Task 5: Add receptionist approval flow

**Files:**
- Modify: `src/whatsapp/handlers/tenant_handler.py` (onboarding completion)
- Modify: `src/whatsapp/handlers/owner_handler.py` (approval handler)

- [ ] **Step 1: On onboarding completion, send summary to receptionist instead of auto-saving**

In `handle_onboarding_step` when step reaches "done", instead of saving directly to Tenant:

```python
    if next_step == "done":
        # Don't save yet — send summary to receptionist for approval
        ob.step = "awaiting_approval"
        ob.collected_data = json.dumps(data)

        summary = _format_onboarding_summary(data, ob.tenant_id, session)

        # Send to admin/power_user phones
        admin_phone = os.getenv("ADMIN_PHONE", "")
        from src.whatsapp.handlers._shared import _save_pending
        await _save_pending(
            admin_phone, "APPROVE_ONBOARDING",
            {"onboarding_id": ob.id, "tenant_id": ob.tenant_id, "data": data},
            [], session,
        )

        # Notify receptionist via WhatsApp
        # (fire-and-forget send to admin)

        return (
            "Thank you! Your details have been submitted.\n"
            "The receptionist will confirm your check-in shortly."
        )
```

- [ ] **Step 2: Add APPROVE_ONBOARDING handler in owner_handler.py**

```python
    if pending.intent == "APPROVE_ONBOARDING":
        if ans.lower() in ("yes", "y", "approve", "confirm", "1"):
            data = action_data.get("data", {})
            # Save to Tenant record
            tenant = await session.get(Tenant, action_data["tenant_id"])
            if tenant:
                tenant.gender = data.get("gender")
                tenant.date_of_birth = parse_dob(data.get("dob"))
                # ... save all fields
                # Mark onboarding complete
                ob = await session.get(OnboardingSession, action_data["onboarding_id"])
                if ob:
                    ob.completed = True
            return f"Onboarding approved for *{tenant.name}*. KYC data saved."
        else:
            return "Onboarding rejected."
```

- [ ] **Step 3: Add intent pattern for approval notification**

The receptionist sees a message like:
```
*New Check-in Request*
Name: Shalini Kumar
Phone: 9876543210
Gender: female
ID: Aadhar XXXX-XXXX-1234
Photo: uploaded
Selfie: uploaded

Reply *yes* to approve or *no* to reject.
```

- [ ] **Step 4: Test full QR flow end-to-end**

- [ ] **Step 5: Commit**

### Task 6: Update n8n webhook to pass media fields

**Files:**
- This is a configuration change in n8n, not code

- [ ] **Step 1: Document what n8n needs to send**

The n8n WhatsApp webhook currently sends `{phone, message, message_id}`. Update it to also extract and forward:

```json
{
  "phone": "+919876543210",
  "message": "",
  "message_id": "wamid.xxx",
  "media_type": "image",
  "media_id": "1234567890",
  "media_mime": "image/jpeg",
  "media_filename": null
}
```

WhatsApp webhook payload for images:
```json
{
  "messages": [{
    "type": "image",
    "image": {
      "id": "1234567890",
      "mime_type": "image/jpeg",
      "sha256": "xxx",
      "caption": "My Aadhar card"
    }
  }]
}
```

- [ ] **Step 2: If using direct webhook (not n8n), update chat_api.py webhook handler**

Check if the WhatsApp webhook handler in `chat_api.py` or `main.py` parses media fields from the raw Meta webhook payload. If not, add parsing.

---

## Testing Checklist

### Phase 1 Tests
- [ ] Add tenant with full deposit paid → booking_amount = deposit, no remaining shown
- [ ] Add tenant with partial deposit → booking_amount = 6500, remaining Rs.6500 shown
- [ ] Add tenant with zero deposit → skip advance step entirely
- [ ] Query tenant balance → shows deposit gap
- [ ] Sheet shows correct Booking column value
- [ ] "full" as advance answer → sets advance = deposit

### Phase 2 Tests
- [ ] Receptionist triggers "onboard 9876543210"
- [ ] Tenant receives KYC form on WhatsApp
- [ ] Tenant fills all steps including photo upload
- [ ] Tenant skips photo upload → proceeds without error
- [ ] Summary sent to receptionist for approval
- [ ] Receptionist approves → data saved to DB
- [ ] Receptionist rejects → data not saved
- [ ] Document record created with correct file_path and tenant_id
- [ ] Onboarding expires after 48 hours
