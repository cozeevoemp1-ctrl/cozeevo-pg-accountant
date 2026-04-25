"""Onboarding-related pending-action resolvers.

Extracted from owner_handler.resolve_pending_action on 2026-04-23 (Phase 2A).
See plan: docs/superpowers/plans/2026-04-23-phase2-handler-refactor.md
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import PendingAction


async def resolve_approve_onboarding(
    pending: PendingAction,
    reply_text: str,
    session: AsyncSession,
    action_data: dict,
    choices: list,
    *,
    media_id: Optional[str] = None,
    media_type: Optional[str] = None,
    media_mime: Optional[str] = None,
) -> Optional[str]:
    """Admin Yes/No on an onboarding approval request.

    Behaviour mirrors the original branch at owner_handler.py:236-334 (pre-2A).
    On Yes: write KYC data to Tenant, mark OnboardingSession.completed, notify
    tenant, fire-and-forget sheet sync. On No: mark rejected, notify tenant.
    Anything else: keep pending with re-prompt.
    """
    import asyncio
    from src.database.models import Tenant, OnboardingSession

    ans = reply_text.strip().lower()

    if ans in ("yes", "y", "approve", "confirm", "1"):
        data = action_data.get("data", {})
        tenant_id = action_data.get("tenant_id")
        onboarding_id = action_data.get("onboarding_id")

        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            return "Tenant not found. Onboarding may have expired."

        # Save KYC data to Tenant record
        if data.get("gender"):
            tenant.gender = data["gender"]
        if data.get("dob"):
            try:
                from datetime import datetime as _dt
                for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
                    try:
                        tenant.date_of_birth = _dt.strptime(data["dob"], fmt).date()
                        break
                    except ValueError:
                        continue
            except Exception:
                pass
        if data.get("father_name"):
            tenant.father_name = data["father_name"]
        if data.get("father_phone"):
            tenant.father_phone = data["father_phone"]
        if data.get("address"):
            tenant.permanent_address = data["address"]
        if data.get("email"):
            tenant.email = data["email"]
        if data.get("occupation"):
            tenant.occupation = data["occupation"]
        if data.get("emergency_name"):
            tenant.emergency_contact_name = data["emergency_name"]
        if data.get("emergency_phone"):
            tenant.emergency_contact_phone = data["emergency_phone"]
        if data.get("emergency_relationship"):
            tenant.emergency_contact_relationship = data["emergency_relationship"]
        if data.get("id_type"):
            tenant.id_proof_type = data["id_type"]
        if data.get("id_number"):
            tenant.id_proof_number = data["id_number"]
        if data.get("food_pref"):
            tenant.food_preference = data["food_pref"]

        # Systemic rule: DB changed → sheet must follow. Fire-and-forget.
        try:
            from src.integrations.gsheets import sync_tenant_all_fields as _sta
            asyncio.create_task(_sta(tenant.id))
        except Exception:
            pass

        # Mark onboarding complete
        ob = await session.get(OnboardingSession, onboarding_id)
        if ob:
            ob.completed = True
            ob.step = "done"

        # Notify tenant
        try:
            from src.whatsapp.webhook_handler import _send_whatsapp
            await _send_whatsapp(
                tenant.phone,
                f"Your check-in has been approved! Welcome to Cozeevo, {tenant.name}.",
            )
        except Exception:
            pass

        # Update gender in Google Sheet (fire-and-forget, best-effort)
        if data.get("gender"):
            try:
                from src.integrations.gsheets import update_tenant_gender
                asyncio.ensure_future(update_tenant_gender(tenant.phone, data["gender"]))
            except Exception:
                pass

        return f"*Onboarding approved — {tenant.name}*\nKYC data saved."

    if ans in ("no", "n", "reject", "2"):
        ob = await session.get(OnboardingSession, action_data.get("onboarding_id"))
        if ob:
            ob.completed = True
            ob.step = "rejected"

        tenant = await session.get(Tenant, action_data.get("tenant_id"))
        if tenant:
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp
                await _send_whatsapp(
                    tenant.phone,
                    "Your check-in request was not approved. Please contact the reception.",
                )
            except Exception:
                pass

        return "Onboarding rejected."

    return "__KEEP_PENDING__Reply *yes* to approve or *no* to reject."


async def resolve_checkin_arrival_payment(
    pending: PendingAction,
    reply_text: str,
    session: AsyncSession,
    action_data: dict,
    choices: list,
    *,
    media_id: Optional[str] = None,
    media_type: Optional[str] = None,
    media_mime: Optional[str] = None,
) -> Optional[str]:
    """Parse 'amount mode' reply, then move to CONFIRM_CHECKIN_ARRIVAL."""
    import re
    import json
    from datetime import datetime, timedelta
    from src.whatsapp.handlers._shared import is_negative

    ans = reply_text.strip().lower()

    if is_negative(ans) or ans == "cancel":
        pending.completed = True
        return "Check-in cancelled."

    amount = 0
    mode = "cash"

    if re.search(r"\b(skip|nothing|none|later|no payment)\b", ans) or ans.strip() == "0":
        amount = 0
        mode = "none"
    else:
        amt_match = re.search(r"(\d[\d,]*)", ans)
        if amt_match:
            amount = int(amt_match.group(1).replace(",", ""))
        mode_match = re.search(r"\b(cash|upi|gpay|phonepe|paytm|online|bank|neft)\b", ans, re.I)
        if mode_match:
            raw = mode_match.group(1).lower()
            mode = "upi" if raw in ("gpay", "phonepe", "paytm", "online", "bank", "neft") else raw
        elif amount > 0:
            mode = "cash"

    if amount < 0:
        return "__KEEP_PENDING__Amount can't be negative. Try again (e.g. *15000 cash*)."

    net_due = action_data.get("net_due", 0)
    remaining = net_due - amount

    action_data["collected_amount"] = amount
    action_data["collected_mode"] = mode

    pending.intent = "CONFIRM_CHECKIN_ARRIVAL"
    pending.action_data = json.dumps(action_data)
    pending.expires_at = datetime.utcnow() + timedelta(minutes=10)

    tenant_name = action_data.get("tenant_name", "Tenant")
    room = action_data.get("room_number", "?")

    lines = [
        f"*Confirm check-in for {tenant_name}?*",
        f"Room {room}",
        f"Due at door: Rs.{net_due:,}",
    ]
    if amount > 0:
        lines.append(f"Collected: Rs.{amount:,} {mode.upper()}")
        if remaining > 0:
            lines.append(f"Balance remaining: Rs.{remaining:,}")
        elif remaining < 0:
            lines.append(f"Overpaid by: Rs.{abs(remaining):,}")
    else:
        lines.append("Collected: Nothing (to be collected later)")
    lines += ["", "Reply *Yes* to check in or *No* to cancel."]
    return "\n".join(lines)


async def resolve_confirm_checkin_arrival(
    pending: PendingAction,
    reply_text: str,
    session: AsyncSession,
    action_data: dict,
    choices: list,
    *,
    media_id: Optional[str] = None,
    media_type: Optional[str] = None,
    media_mime: Optional[str] = None,
) -> Optional[str]:
    """Flip a no-show tenancy to active when receptionist confirms arrival.

    Writes Tenancy.status = active + audit_log + triggers monthly sheet sync
    (so the NO-SHOW row becomes an active CHECKIN) + TENANTS master sync.
    Optionally updates checkin_date to today if the booking was for a future
    date (so sheet shows actual arrival, not booking).
    """
    from src.database.models import Tenancy, TenancyStatus, AuditLog
    from src.whatsapp.handlers._shared import is_affirmative, is_negative

    ans = reply_text.strip().lower()
    if is_negative(ans):
        return "Cancelled. Tenancy stays as no-show."
    if not is_affirmative(ans):
        return "__KEEP_PENDING__Reply *Yes* to mark as arrived or *No* to cancel."

    tenancy = await session.get(Tenancy, action_data["tenancy_id"])
    if not tenancy:
        return "Tenancy not found — may have been already checked in."
    if tenancy.status != TenancyStatus.no_show:
        return (
            f"*{action_data['tenant_name']}* is already "
            f"{tenancy.status.value if hasattr(tenancy.status, 'value') else tenancy.status}. "
            f"No change."
        )

    today = date.today()
    old_checkin = tenancy.checkin_date
    old_status = "no_show"

    # If the tenant arrived earlier than their booked date, keep booked_checkin
    # (it's the agreement). If booked_checkin is in the future, fast-forward to
    # today so sheet reflects the actual arrival.
    if tenancy.checkin_date and tenancy.checkin_date > today:
        tenancy.checkin_date = today

    tenancy.status = TenancyStatus.active

    # Log payment collected at door
    collected_amount = action_data.get("collected_amount", 0)
    collected_mode   = action_data.get("collected_mode", "cash")
    if collected_amount and collected_amount > 0:
        from decimal import Decimal
        from src.database.models import Payment, PaymentMode, PaymentFor
        mode_map = {"cash": PaymentMode.cash, "upi": PaymentMode.upi}
        session.add(Payment(
            tenancy_id   = tenancy.id,
            amount       = Decimal(str(collected_amount)),
            payment_date = today,
            payment_mode = mode_map.get(collected_mode, PaymentMode.cash),
            for_type     = PaymentFor.rent,
            period_month = (tenancy.checkin_date or today).replace(day=1),
            notes        = f"Collected at check-in ({collected_mode})",
        ))

    session.add(AuditLog(
        changed_by=action_data.get("confirmed_by", "system"),
        entity_type="tenancy",
        entity_id=tenancy.id,
        entity_name=action_data.get("tenant_name", ""),
        field="status",
        old_value=old_status,
        new_value="active",
        room_number=action_data.get("room_number", ""),
        source="whatsapp",
        notes=(
            f"arrival confirmed; booked_checkin={old_checkin.isoformat() if old_checkin else '-'}, "
            f"actual={tenancy.checkin_date.isoformat() if tenancy.checkin_date else '-'}"
        ),
    ))

    # DB → sheet: TENANTS master row (status, checkin) + current monthly tab
    # (NO-SHOW row → CHECKIN row). Fire-and-forget — scheduled retry queue
    # handles failures (see Phase 2D).
    try:
        import asyncio
        from src.integrations.gsheets import (
            sync_tenant_all_fields as _sta,
            trigger_monthly_sheet_sync as _tms,
        )
        asyncio.create_task(_sta(tenancy.tenant_id))
        _tms(today.month, today.year)
    except Exception:
        import logging
        logging.getLogger(__name__).error(
            "Sheet sync failed after CHECKIN_ARRIVAL for tenancy %s", tenancy.id
        )

    # Notify tenant
    try:
        from src.database.models import Tenant
        tenant = await session.get(Tenant, tenancy.tenant_id)
        if tenant and tenant.phone:
            from src.whatsapp.webhook_handler import _send_whatsapp
            await _send_whatsapp(
                tenant.phone,
                f"Welcome, {tenant.name}! Your check-in has been confirmed at Cozeevo.",
            )
    except Exception:
        pass

    new_ci = tenancy.checkin_date.strftime("%d %b %Y") if tenancy.checkin_date else "-"
    ff_note = ""
    if old_checkin and old_checkin != tenancy.checkin_date:
        ff_note = f" (booking was {old_checkin.strftime('%d %b %Y')}, arrived early)"

    collected_amount = action_data.get("collected_amount", 0)
    collected_mode   = action_data.get("collected_mode", "cash")
    net_due          = action_data.get("net_due", 0)
    pay_line = ""
    if collected_amount and collected_amount > 0:
        remaining = net_due - collected_amount
        pay_line = f"\nCollected: Rs.{collected_amount:,} {collected_mode.upper()}"
        if remaining > 0:
            pay_line += f" | Balance due: Rs.{remaining:,}"
    else:
        pay_line = f"\nPayment: Rs.{net_due:,} to be collected"

    return (
        f"*{action_data['tenant_name']}* checked in ✓\n"
        f"Room {action_data.get('room_number', '?')} — {new_ci}{ff_note}"
        f"{pay_line}\n"
        f"Status: ACTIVE. Sheets updating."
    )
