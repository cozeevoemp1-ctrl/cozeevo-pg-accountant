# WhatsApp Message Templates

Meta requires templates for any business-initiated message to a phone
that hasn't messaged you in the last 24 hours. First-time tenants
*always* fall in this bucket — without an approved template the
booking confirmation is silently dropped at Meta's edge.

Register every template below in **Meta Business Manager →
WhatsApp Manager → Message Templates**, exactly as named.

---

## Template 1: `cozeevo_booking_confirmation`

**Used by:** `src/api/onboarding_router.py::approve_session` after a
new tenant is created via the onboarding form.

- **Name:** `cozeevo_booking_confirmation`
- **Category:** UTILITY
- **Language:** English (en)
- **Header:** None
- **Body** (5 variables):

```
Welcome to Cozeevo, {{1}}!

Your booking is confirmed.

Room: *{{2}}*
Check-in: *{{3}}*
Monthly rent: *{{4}}*
Deposit: *{{5}}*

If any amount shown differs from what was agreed in the form, please contact the receptionist or call 8548884455.
```

> **Note:** v1 of this template was submitted with a different body that
> mentioned the rental agreement. Meta does not allow editing PENDING
> templates. Once Meta approves v1 (~15-60 min after submission at
> 2026-04-19), edit via `POST /v21.0/1303194515065555` with the body
> above. Code already references `cozeevo_booking_confirmation` — no
> code change needed after the edit.

- **Footer:** `Cozeevo Co-living • getkozzy.com`
- **Sample values for Meta review submission:**
  - `{{1}}` = `Pooja K L`
  - `{{2}}` = `114`
  - `{{3}}` = `19 Apr 2026`
  - `{{4}}` = `Rs.13,000`
  - `{{5}}` = `Rs.6,500`

After Meta approves it, `approve_session` uses it automatically. Until
approval, the code falls back to free-text (only works inside a 24-hour
conversation window).

### Pending enhancement — diff notification

When the receptionist edits any form-submitted value during approval
(deposit, rent, check-in date), the current template shows only the
final numbers. We want an extra follow-up message listing ONLY the
fields that differ from what the tenant submitted, so they can flag
mistakes quickly. Tracked in `project_pending_tasks.md`.

---

## Template 2: `cozeevo_checkin_form`

**Used by:** `src/api/onboarding_router.py::create_session` to send the
KYC form link to a new tenant.

Already registered and approved.

---

## Template 3: `cozeevo_checkout_confirmation` (to create)

**Future use:** auto-send a checkout summary when the receptionist
marks a tenant exited via the bot. Covers refund status, deposit
returned, final dues.

- **Name:** `cozeevo_checkout_confirmation`
- **Category:** UTILITY
- **Language:** English (en)
- **Header:** None
- **Body** (5 variables):

```
Hi {{1}}, your check-out is recorded.

Room: *{{2}}*
Checkout date: *{{3}}*
Deposit refund: *{{4}}*
Final balance: *{{5}}*

Thank you for staying with Cozeevo — it was a pleasure having you. If you enjoyed your stay, we'd love a quick review and a recommendation to friends. And whenever you're in town again, our doors are open to welcome you back.
```

- **Footer:** `Cozeevo Co-living • getkozzy.com`
- **Sample values:**
  - `{{1}}` = `Krishnan`
  - `{{2}}` = `101`
  - `{{3}}` = `25 Apr 2026`
  - `{{4}}` = `Rs.14,000`
  - `{{5}}` = `Rs.0 (settled)`

**Wiring** (not yet in code): after
`src/whatsapp/handlers/owner_handler.py::_do_checkout` writes the
AuditLog, add a `_send_whatsapp_template("cozeevo_checkout_confirmation", [name, room, date, refund, balance])` with free-text fallback.

---

## Template 4: `cozeevo_payment_received`

**Future use:** auto-send a receipt summary to the tenant when the
receptionist logs a payment via the bot. Mode of payment (cash/UPI)
is intentionally omitted — tenants only care about what they've paid
for the month and what's still owed.

- **Name:** `cozeevo_payment_received`
- **Category:** UTILITY
- **Language:** English (en)
- **Header:** None
- **Body** (4 variables):

```
Hi {{1}}, payment received — thank you.

Towards: *{{2}}*
Paid this month so far: *{{3}}*
Balance remaining: *{{4}}*

— Cozeevo Help Desk
```

- **Footer:** `Cozeevo Co-living • getkozzy.com`
- **Sample values for Meta review submission:**
  - `{{1}}` = `Krishnan`
  - `{{2}}` = `April 2026 rent`
  - `{{3}}` = `Rs.14,000`
  - `{{4}}` = `Rs.0 (paid in full)`

**Wiring** (not yet in code): after `account_handler.py::_do_log_payment_by_ids` writes its AuditLog, compute:
- `paid_so_far` = sum of `Payment.amount` for this tenancy + period_month where `is_void=False` and `for_type='rent'`
- `balance` = `rent_schedule.rent_due + adjustment − paid_so_far` (≥0)
- Format balance as `"Rs.0 (paid in full)"` if balance ≤ 0, else `f"Rs.{balance:,}"`
- `_send_whatsapp_template("cozeevo_payment_received", [name, period_label, paid_so_far, balance_str])` with free-text fallback.

---

## Verifying a sent template after deploy

```sql
-- Most recent outbound template sends
SELECT created_at, to_number, intent, message_text
FROM whatsapp_log
WHERE direction = 'outbound'
  AND intent IN ('TEMPLATE', 'TEMPLATE_FAILED')
ORDER BY created_at DESC
LIMIT 20;
```

If you see `TEMPLATE_FAILED` rows, check VPS journal:
```bash
ssh root@... "journalctl -u pg-accountant --since '1 hour ago' | grep 'Template send failed'"
```

Common failure reasons:
- Template name typo (Meta is case-sensitive)
- Variable count mismatch
- Template still in `IN_REVIEW` or `REJECTED` status in Meta Business Manager
