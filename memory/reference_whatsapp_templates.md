---
name: WhatsApp Templates
description: All Meta WhatsApp message templates with approval status and parameter mapping
metadata:
  type: reference
---

# WhatsApp Message Templates

Status codes: ✅ APPROVED | ⏳ PENDING | ❌ REJECTED

## Transactional Templates (auto-reply, 24hr window)

| Template Name | Status | Parameters | Use Case |
|---|---|---|---|
| `rent_reminder` | ❌ BLOCKED | `name` | Rent due reminder — permanently disabled per rules |
| `payment_received` | ❌ BLOCKED | `name`, `amount`, `date` | Payment confirmation — permanently disabled |
| `general_notice` | ❌ BLOCKED | `month` | General notice — permanently disabled |

## Service Templates (staff + admin only)

| Template Name | Status | Parameters | Use Case |
|---|---|---|---|
| `checkout_confirmation` | ⏳ PENDING | `name`, `room`, `date`, `refund`, `link` | Checkout summary to departing tenant (within 24hr) |
| `cozeevo_notice_confirmation` | ✅ APPROVED | `name`, `room`, `checkout_date` | Notice given confirmation |
| `cozeevo_checkin_prep` | ✅ APPROVED | `name`, `date`, `time` | Pre-checkin reminder to staff (not tenants) |
| `cozeevo_checkout_prep` | ✅ APPROVED | `name`, `room`, `date` | Pre-checkout prep to staff (not tenants) |

## Operational Templates (maintenance, systems)

| Template Name | Status | Parameters | Use Case |
|---|---|---|---|
| `power_maintenance_notice` | ⏳ PENDING | `date` | Advance notice of power outage / maintenance |
| `water_supply_notice` | — | `date`, `time` | Water supply interruption notice |

---

## Template Specifications

### `power_maintenance_notice`

**Approval Status:** Pending (not yet created in Meta Business Manager)

**Template Body:**
```
We wanted to inform you that there may be a power outage for a few hours on {{date}} due to ongoing government maintenance work in the area. The authorities are working on this, but please don't be concerned.

We have backup power — Our DG (diesel generator) will be operational during the outage to ensure continuous electricity supply to all essential areas.

Thank you for your understanding.
```

**Header:** Power Maintenance Notice  
**Footer:** Cozeevo Help Desk  
**Parameters:** `date` (string, e.g., "2026-06-15")  
**Language:** English  
**Category:** SERVICE_UPDATE  

**Notes:**
- For building-wide or multi-tenant announcements
- Can be sent to all tenants (informational, not transactional)
- Replace `{{date}}` with actual date before sending
- Fallback: if template approval pending, send as free-form text via bot

---

## How to Create a New Template

1. **Meta Business Manager:** business.facebook.com → WhatsApp Manager → Message Templates
2. **Fill form:**
   - Template name (snake_case, e.g., `power_maintenance_notice`)
   - Category (TRANSACTIONAL / MARKETING / SERVICE_UPDATE)
   - Language (English)
   - Body text (with `{{param_name}}` placeholders)
   - Header, footer (if needed)
3. **Submit for approval** — usually 24-48 hours
4. **Once approved:**
   - Add to code: `src/whatsapp/reminder_sender.py` → `TEMPLATE_PARAM_NAMES`
   - Add to this reference file with ✅ status
   - Implement send function in handlers

---

## Code Mapping

Update `src/whatsapp/reminder_sender.py:TEMPLATE_PARAM_NAMES`:

```python
TEMPLATE_PARAM_NAMES = {
    "rent_reminder":              ["name"],
    "general_notice":             ["month"],
    "checkout_confirmation":      ["name", "room", "date", "refund", "link"],
    "cozeevo_notice_confirmation": ["name", "room", "checkout_date"],
    "power_maintenance_notice":   ["date"],  # ← NEW
}
```

---

## Restrictions (CRITICAL)

**HARD RULE:** No automated/scheduled messages to tenants.
- ✅ Allowed: Transactional (within 24hr window after tenant action)
- ✅ Allowed: Informational (one-off, triggered by operations team)
- ❌ Blocked: Scheduled reminders (rent due, notice date approaching, etc.)
- ❌ Blocked: Bulk blasts outside user-triggered actions

See `rules_no_tenant_comms.md` for full policy.
