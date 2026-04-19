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

Your signed rental agreement is on the way.

If any amount shown differs from what you submitted in the form, please reply to this message and the receptionist will reconcile it.
```

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

Thank you for staying with Cozeevo. If any amount here looks wrong, please reply — the receptionist will reconcile.
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

## Template 4 (recommended): `cozeevo_payment_received`

**Future use:** auto-send a receipt summary to the tenant when the
receptionist logs a payment via the bot.

- **Name:** `cozeevo_payment_received`
- **Category:** UTILITY
- **Body** (4 variables):

```
Payment received — thank you, {{1}}.

Amount: *{{2}}*
For: *{{3}}*
Balance: *{{4}}*

— Cozeevo Help Desk
```

- **Sample values:**
  - `{{1}}` = `Krishnan`
  - `{{2}}` = `Rs.14,000`
  - `{{3}}` = `April 2026 rent`
  - `{{4}}` = `Rs.0 (paid in full)`

Not yet wired. Plan: add inside
`src/whatsapp/handlers/account_handler.py::_do_log_payment_by_ids`
after the AuditLog write.

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
