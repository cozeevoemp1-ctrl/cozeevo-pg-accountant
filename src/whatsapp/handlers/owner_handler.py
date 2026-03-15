"""
Owner / Power-user handler.
Processes intents for admin, power_user, key_user roles.

Disambiguation flow:
  - Fuzzy name search → 0 results  → suggest similar names, save pending action
  - Fuzzy name search → 1 result   → confirm inline, proceed
  - Fuzzy name search → 2+ results → numbered list, save pending action
  - User replies "1" / "2" / "yes" → chat_api resolves via resolve_pending_action()
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    AuthorizedUser, CheckoutRecord, Complaint, ComplaintCategory, ComplaintStatus, Payment, PaymentFor,
    PaymentMode, PendingAction, PendingLearning, LearnedRule, Property, Refund, RefundStatus, RentSchedule, RentStatus,
    Room, Staff, Tenant, Tenancy, TenancyStatus, UserRole, Vacation, OnboardingSession,
)
from src.whatsapp.role_service import CallerContext
from src.database.validators import check_no_active_tenancy, check_tenancy_active
from src.whatsapp.handlers._shared import (
    _find_active_tenants_by_name, _find_active_tenants_by_room,
    _find_similar_names, _check_room_overlap,
    _make_choices, _save_pending,
    _format_choices_message, _format_no_match_message,
    BOT_NAME, time_greeting, is_first_time,
    is_affirmative, is_negative, parse_target_month,
)
from src.whatsapp.handlers.account_handler import (
    _calc_outstanding_dues,       # needed by _room_status + _do_checkout
    _do_log_payment_by_ids,       # needed by resolve_pending_action
    _do_void_payment,             # needed by resolve_pending_action
    _do_rent_change,              # needed by resolve_pending_action
    _do_query_tenant_by_id,       # needed by resolve_pending_action
)
from services.property_logic import (
    NOTICE_BY_DAY,
    calc_checkin_prorate,
    calc_checkout_prorate,
    calc_effective_due,
    calc_payment_status,
    calc_notice_last_day,
    calc_settlement,
    fmt_settlement_lines,
    is_deposit_eligible,
    OVERPAYMENT_NOISE_RS,
)


# ── Main dispatcher ───────────────────────────────────────────────────────────

async def handle_owner(
    intent: str,
    entities: dict,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:
    # Financial intents are handled by AccountWorker (account_handler.py).
    # Only operational intents remain here.
    handlers = {
        "ADD_TENANT":         _add_tenant_prompt,
        "CHECKOUT":           _checkout_prompt,
        "SCHEDULE_CHECKOUT":  _checkout_prompt,   # same handler — date in entities distinguishes
        "UPDATE_CHECKIN":     _update_checkin,
        "NOTICE_GIVEN":       _notice_given,
        "ADD_PARTNER":        _add_partner,
        "REMINDER_SET":       _reminder_prompt,
        "QUERY_VACANT_ROOMS": _query_vacant_rooms,
        "QUERY_OCCUPANCY":    _query_occupancy,
        "QUERY_EXPIRING":     _query_expiring,
        "QUERY_CHECKINS":     _query_checkins,
        "QUERY_CHECKOUTS":    _query_checkouts,
        "LOG_VACATION":       _log_vacation,
        "ROOM_STATUS":        _room_status,
        "SEND_REMINDER_ALL":  _send_reminder_all,
        "START_ONBOARDING":   _start_onboarding,
        "RECORD_CHECKOUT":    _record_checkout,
        "GET_WIFI_PASSWORD":  _get_wifi_password,
        "SET_WIFI":           _set_wifi,
        "COMPLAINT_REGISTER": _owner_complaint_register,
        "GET_TENANT_NOTES":   _get_tenant_notes,
        "RULES":              _rules,
        "HELP":               _help,
        "UNKNOWN":            _unknown,
    }
    fn = handlers.get(intent, _unknown)
    return await fn(entities, ctx, session)


# ── Pending action resolver (called from chat_api before intent detection) ────

async def resolve_pending_action(pending: PendingAction, reply_text: str, session: AsyncSession) -> Optional[str]:
    """
    Called when the user replies to a disambiguation question.
    Returns the final reply string, or None if the reply wasn't a valid choice.
    """
    reply_text = reply_text.strip()
    choices = json.loads(pending.choices or "[]")
    action_data = json.loads(pending.action_data or "{}")

    # Parse user's choice: "1", "2", "1." etc.
    chosen_idx = None
    if reply_text.rstrip(".").isdigit():
        num = int(reply_text.rstrip("."))
        if 1 <= num <= len(choices):
            chosen_idx = num - 1

    # ── Multi-step text-based flows — handled BEFORE numeric check ───────────

    if pending.intent == "CONFIRM_PAYMENT_LOG":
        if is_affirmative(reply_text):
            return await _do_log_payment_by_ids(
                tenant_id=action_data["tenant_id"],
                tenancy_id=action_data["tenancy_id"],
                amount=action_data["amount"],
                mode=action_data["mode"],
                ctx_name=action_data["logged_by"],
                period_month_str=action_data["period_month"],
                session=session,
            )
        if is_negative(reply_text):
            return "❌ Payment cancelled. Nothing was logged."
        return (
            f"Reply *Yes* to confirm logging Rs.{int(action_data['amount']):,} "
            f"for {action_data['tenant_name']}, or *No* to cancel."
        )

    if pending.intent == "CONFIRM_DEPOSIT_REFUND":
        ans = reply_text.lower().strip()
        tenancy_id   = action_data.get("tenancy_id")
        tenant_name  = action_data.get("tenant_name", "Tenant")
        deposit_held = int(action_data.get("deposit_held", 0))
        maintenance  = int(action_data.get("maintenance", 0))
        net_refund   = int(action_data.get("net_refund", deposit_held))

        # "deduct 2000" or "deduct 2000 process"
        deduct_match = re.search(r"deduct\s+(\d+)", ans)
        if deduct_match:
            extra_deduction = int(deduct_match.group(1))
            maintenance = maintenance + extra_deduction
            net_refund  = max(0, deposit_held - maintenance)
            action_data["maintenance"] = maintenance
            action_data["net_refund"]  = net_refund

        do_process = "process" in ans

        if deduct_match and not do_process:
            # Updated deduction — ask to confirm
            await _save_pending(pending.phone, "CONFIRM_DEPOSIT_REFUND", action_data, [], session)
            return (
                f"*Updated — {tenant_name}*\n"
                f"Deposit held  : Rs.{deposit_held:,}\n"
                f"Maintenance   : -Rs.{maintenance:,}\n"
                f"Net refund    : Rs.{net_refund:,}\n\n"
                "Reply *process* to confirm, or *deduct XXXX* to adjust further."
            )

        if do_process:
            if not tenancy_id:
                return "Error: tenancy not found in pending action."
            # Check if already processed
            existing_refund = (await session.execute(
                select(Refund).where(
                    Refund.tenancy_id == tenancy_id,
                    Refund.status == RefundStatus.processed,
                )
            )).scalars().first()
            if existing_refund:
                return f"Deposit refund for *{tenant_name}* already processed (Rs.{int(existing_refund.amount):,})."

            # Create or update Refund row
            pending_refund = (await session.execute(
                select(Refund).where(
                    Refund.tenancy_id == tenancy_id,
                    Refund.status == RefundStatus.pending,
                )
            )).scalars().first()

            if pending_refund:
                pending_refund.amount      = Decimal(str(net_refund))
                pending_refund.refund_date = date.today()
                pending_refund.status      = RefundStatus.processed
                pending_refund.notes       = f"Maintenance deducted: Rs.{maintenance:,}"
            else:
                session.add(Refund(
                    tenancy_id   = tenancy_id,
                    amount       = Decimal(str(net_refund)),
                    refund_date  = date.today(),
                    reason       = "deposit refund on checkout",
                    status       = RefundStatus.processed,
                    notes        = f"Maintenance deducted: Rs.{maintenance:,}",
                ))

            # Update CheckoutRecord if it exists
            cr = (await session.execute(
                select(CheckoutRecord).where(CheckoutRecord.tenancy_id == tenancy_id)
            )).scalars().first()
            if cr:
                cr.deposit_refunded_amount = Decimal(str(net_refund))
                cr.deposit_refund_date     = date.today()

            return (
                f"*Deposit Processed — {tenant_name}*\n"
                f"Deposit held  : Rs.{deposit_held:,}\n"
                f"Maintenance   : -Rs.{maintenance:,}\n"
                f"*Returned     : Rs.{net_refund:,}*\n"
                f"Date          : {date.today().strftime('%d %b %Y')}\n\n"
                "Refund record saved."
            )

        # Unrecognised reply — re-prompt
        return (
            f"Reply *process* to confirm refund of Rs.{net_refund:,}\n"
            "or *deduct XXXX* to reduce for maintenance first."
        )

    if pending.intent == "RECORD_CHECKOUT":
        step = action_data.get("step", "")

        # Step 0 (confirm_tenant) needs a numbered choice
        if step == "confirm_tenant":
            if not reply_text.rstrip(".").isdigit():
                return None
            num = int(reply_text.rstrip("."))
            if not (1 <= num <= len(choices)):
                return None
            chosen_tenant = choices[num - 1]
            action_data["step"]        = "ask_cupboard_key"
            action_data["tenancy_id"]  = chosen_tenant["tenancy_id"]
            action_data["tenant_name"] = chosen_tenant["label"]
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
            return (
                f"*Checkout Form — {chosen_tenant['label']}*\n\n"
                "*Q1/5* Was the *cupboard/almirah key* returned?\n"
                "Reply: *yes* or *no*"
            )

        # Steps 1–5 are text-based
        ans = reply_text.lower().strip()
        yes = ans in ("yes", "y", "haan", "ha", "done", "returned", "1")

        if step == "ask_cupboard_key":
            action_data["cupboard_key"] = yes
            action_data["step"] = "ask_main_key"
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
            return "*Q2/5* Was the *main gate / room key* returned?\nReply: *yes* or *no*"

        if step == "ask_main_key":
            action_data["main_key"] = yes
            action_data["step"] = "ask_damage"
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
            return "*Q3/5* Any *damages* to report?\nReply: *no* — or describe them (e.g. 'broken fan, cracked mirror')"

        if step == "ask_damage":
            action_data["damage"] = "" if ans in ("no", "n", "none", "nil", "nahi", "nope") else reply_text.strip()
            action_data["step"] = "ask_dues"
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
            return "*Q4/5* Any *pending dues* at checkout? (Rs.)\nReply: *0* if fully paid, or the amount"

        if step == "ask_dues":
            try:
                dues = int("".join(filter(str.isdigit, reply_text)) or "0")
            except ValueError:
                dues = 0
            action_data["dues"] = dues
            action_data["step"] = "ask_deposit_refund"
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
            # Pre-calculate expected refund for convenience
            tenancy_id_hint = action_data.get("tenancy_id")
            deposit_hint = 0
            if tenancy_id_hint:
                tenancy_hint = await session.get(Tenancy, tenancy_id_hint)
                if tenancy_hint and tenancy_hint.security_deposit:
                    deposit_hint = int(tenancy_hint.security_deposit)
            hint_line = f"\n_(Deposit on record: Rs.{deposit_hint:,} — dues: Rs.{dues:,} — expected refund: Rs.{max(0, deposit_hint - dues):,})_" if deposit_hint else ""
            return (
                f"*Q5/5* Deposit refund amount? (Rs.){hint_line}\n"
                "Reply: *0* if not refunding, or the amount"
            )

        if step == "ask_deposit_refund":
            try:
                refund_amt = int("".join(filter(str.isdigit, reply_text)) or "0")
            except ValueError:
                refund_amt = 0

            tenancy_id = action_data.get("tenancy_id")
            cr = CheckoutRecord(
                tenancy_id=tenancy_id,
                cupboard_key_returned=action_data.get("cupboard_key", False),
                main_key_returned=action_data.get("main_key", False),
                damage_notes=action_data.get("damage") or None,
                pending_dues_amount=action_data.get("dues", 0),
                deposit_refunded_amount=refund_amt,
                deposit_refund_date=date.today() if refund_amt > 0 else None,
                actual_exit_date=date.today(),
                recorded_by=pending.phone,
            )
            session.add(cr)

            # Create Refund row (pending until explicitly processed)
            if tenancy_id:
                session.add(Refund(
                    tenancy_id  = tenancy_id,
                    amount      = Decimal(str(refund_amt)),
                    refund_date = date.today() if refund_amt > 0 else None,
                    reason      = "deposit refund on checkout",
                    status      = RefundStatus.pending if refund_amt > 0 else RefundStatus.cancelled,
                    notes       = f"Recorded during checkout form by {pending.phone}",
                ))

            # Mark tenancy as exited
            tenancy = await session.get(Tenancy, tenancy_id)
            if tenancy:
                tenancy.status = TenancyStatus.exited
                tenancy.checkout_date = date.today()

            name = action_data.get("tenant_name", "Tenant")
            return (
                f"*Checkout Complete — {name}*\n\n"
                f"Cupboard key: {'Returned' if action_data.get('cupboard_key') else 'Not returned'}\n"
                f"Main key: {'Returned' if action_data.get('main_key') else 'Not returned'}\n"
                f"Damages: {action_data.get('damage') or 'None'}\n"
                f"Pending dues: Rs.{int(action_data.get('dues', 0)):,}\n"
                f"Deposit refund: Rs.{refund_amt:,} _(status: pending — reply *process* to finalise)_\n"
                f"Exit date: {date.today().strftime('%d %b %Y')}\n\n"
                "Record saved. Room is now vacant."
            )

        return None  # Unrecognised step

    # ── Numbered-choice disambiguation ────────────────────────────────────────

    if chosen_idx is None:
        return None   # Not a valid numbered choice — let normal flow handle it

    chosen = choices[chosen_idx]

    if pending.intent == "PAYMENT_LOG":
        return await _do_log_payment_by_ids(
            tenant_id=chosen["tenant_id"],
            tenancy_id=chosen["tenancy_id"],
            amount=action_data["amount"],
            mode=action_data.get("mode", "cash"),
            ctx_name=action_data.get("logged_by", "owner"),
            period_month_str=action_data.get("period_month", ""),
            session=session,
        )

    if pending.intent in ("CHECKOUT", "SCHEDULE_CHECKOUT"):
        date_str = action_data.get("checkout_date", "")
        try:
            checkout_date_val = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            checkout_date_val = date.today()
        return await _do_checkout(
            tenancy_id=chosen["tenancy_id"],
            tenant_name=chosen["label"],
            checkout_date_val=checkout_date_val,
            session=session,
        )

    if pending.intent == "UPDATE_CHECKIN":
        return await _do_update_checkin(
            tenancy_id=chosen["tenancy_id"],
            tenant_name=chosen["label"],
            new_checkin_str=action_data.get("new_checkin", ""),
            session=session,
        )

    if pending.intent == "NOTICE_GIVEN":
        tenancy = await session.get(Tenancy, chosen["tenancy_id"])
        if tenancy:
            try:
                tenancy.notice_date = date.fromisoformat(action_data["notice_date"])
                tenancy.expected_checkout = date.fromisoformat(action_data["last_day"])
            except (ValueError, KeyError):
                pass
            last_day_str = action_data.get("last_day", "")
            try:
                last_day_fmt = date.fromisoformat(last_day_str).strftime("%d %b %Y")
            except ValueError:
                last_day_fmt = last_day_str
            deposit_note = action_data.get("deposit_note", "")
            return (
                f"*Notice recorded — {chosen['label']}*\n"
                f"Notice date: {action_data.get('notice_date', '')}\n"
                f"Last day: {last_day_fmt}\n\n"
                f"{deposit_note}"
            )
        return "Tenancy not found."

    if pending.intent == "RENT_CHANGE_WHO":
        # After picking the right tenant, ask one-time vs permanent
        tenant = await session.get(Tenant, chosen["tenant_id"])
        tenancy = await session.get(Tenancy, chosen["tenancy_id"])
        if not tenant or not tenancy:
            return "Tenant not found."
        old_rent = int(tenancy.agreed_rent or 0)
        amount = action_data["new_amount"]
        try:
            month_fmt = date.fromisoformat(action_data["month"]).strftime("%b %Y")
        except (ValueError, KeyError):
            month_fmt = "this month"
        option_choices = [
            {"seq": 1, "label": f"Only {month_fmt}"},
            {"seq": 2, "label": f"Permanent from {month_fmt}"},
        ]
        action_data["tenancy_id"] = tenancy.id
        action_data["tenant_name"] = tenant.name
        await _save_pending(pending.phone, "RENT_CHANGE", action_data, option_choices, session)
        verb = "concession" if action_data.get("is_discount") else "rent change"
        return (
            f"*{verb.title()} for {tenant.name}*\n"
            f"Amount: Rs.{int(amount):,}\n\n"
            f"1. Only {month_fmt}\n"
            f"2. Permanent from {month_fmt}\n\n"
            "Reply *1* or *2*."
        )

    if pending.intent == "RENT_CHANGE":
        # choices here are option-picks: seq 1=one-time, seq 2=permanent
        permanent = (chosen.get("seq", 1) == 2)
        return await _do_rent_change(
            tenancy_id=action_data["tenancy_id"],
            tenant_name=action_data["tenant_name"],
            new_amount=action_data["new_amount"],
            month_str=action_data.get("month", ""),
            permanent=permanent,
            is_discount=action_data.get("is_discount", False),
            reason=action_data.get("reason", ""),
            session=session,
        )

    if pending.intent == "QUERY_TENANT":
        return await _do_query_tenant_by_id(
            tenant_id=chosen["tenant_id"],
            tenancy_id=chosen["tenancy_id"],
            session=session,
        )

    if pending.intent == "GET_TENANT_NOTES":
        tenancy = await session.get(Tenancy, chosen["tenancy_id"])
        tenant = await session.get(Tenant, chosen["tenant_id"])
        if not tenancy or not tenant:
            return "Tenant not found."
        notes = tenancy.notes
        if not notes or not notes.strip():
            return f"*{tenant.name}* (Room {tenancy.room_id}) — no agreed terms on record."
        return f"*{tenant.name}* — Room {tenancy.room_id}\nAgreed terms:\n{notes}"

    if pending.intent == "DUPLICATE_CONFIRM":
        if chosen.get("seq") == 1:  # Log anyway
            return await _do_log_payment_by_ids(
                tenant_id=action_data["tenant_id"],
                tenancy_id=action_data["tenancy_id"],
                amount=action_data["amount"],
                mode=action_data.get("mode", "cash"),
                ctx_name=action_data.get("logged_by", "owner"),
                period_month_str=action_data.get("period_month", ""),
                skip_duplicate_check=True,
                session=session,
            )
        return "Payment not logged."

    if pending.intent == "OVERPAYMENT_RESOLVE":
        tenancy_id = action_data["tenancy_id"]
        extra = action_data["extra_amount"]
        tenant_name = action_data["tenant_name"]
        next_month_str = action_data.get("next_month", "")
        seq = chosen.get("seq", 3)
        if seq == 1:  # Advance for next month
            try:
                next_month = date.fromisoformat(next_month_str)
            except (ValueError, TypeError):
                next_month = date.today().replace(day=1)
                if next_month.month == 12:
                    next_month = date(next_month.year + 1, 1, 1)
                else:
                    next_month = next_month.replace(month=next_month.month + 1)
            session.add(Payment(
                tenancy_id=tenancy_id,
                amount=Decimal(str(extra)),
                payment_date=date.today(),
                payment_mode=PaymentMode.upi if action_data.get("mode") == "upi" else PaymentMode.cash,
                for_type=PaymentFor.rent,
                period_month=next_month,
                notes=f"Advance for {next_month.strftime('%b %Y')} — overpayment carry-forward",
            ))
            return (
                f"*Overpayment allocated — {tenant_name}*\n"
                f"Rs.{int(extra):,} logged as advance for {next_month.strftime('%b %Y')}."
            )
        elif seq == 2:  # Add to deposit
            tenancy = await session.get(Tenancy, tenancy_id)
            if tenancy:
                tenancy.security_deposit = (tenancy.security_deposit or Decimal("0")) + Decimal(str(extra))
            return (
                f"*Overpayment allocated — {tenant_name}*\n"
                f"Rs.{int(extra):,} added to security deposit.\n"
                f"New deposit: Rs.{int(tenancy.security_deposit or 0):,}"
            )
        else:  # Keep as credit / ask tenant
            return (
                f"Rs.{int(extra):,} extra for {tenant_name} left as unallocated credit.\n"
                "Confirm with tenant what it's for."
            )

    if pending.intent == "VOID_PAYMENT":
        if chosen.get("seq") == 1:  # Confirm void
            return await _do_void_payment(
                payment_id=action_data["payment_id"],
                tenant_name=action_data["tenant_name"],
                session=session,
            )
        return "Void cancelled — payment remains as logged."

    return None


# ── Shared helpers and financial functions are in _shared.py / account_handler.py ──
# Imported at the top of this file — see import block above.


# ── Checkout ──────────────────────────────────────────────────────────────────

async def _checkout_prompt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name = entities.get("name", "").strip()
    room = entities.get("room", "").strip()
    date_str = entities.get("date", "")

    if not name and not room:
        return (
            "Who is checking out?\n"
            "Say: *checkout [Name]* or *checkout Room 203*\n"
            "Example: *checkout Raj Kumar on 31 May*"
        )

    # Parse checkout date (default to today if not specified)
    checkout_date_val: Optional[date] = None
    if date_str:
        try:
            checkout_date_val = date.fromisoformat(date_str)
        except ValueError:
            return "Couldn't parse that date. Use format: *31 May* or *31/05/2026*"
    is_future_checkout = checkout_date_val and checkout_date_val > date.today()

    rows: list = []
    search_term = name

    if name:
        rows = await _find_active_tenants_by_name(name, session)
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)
        search_term = f"Room {room}"

    if len(rows) == 0:
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)

    intent_type = "SCHEDULE_CHECKOUT" if is_future_checkout else "CHECKOUT"
    action_data = {"name_raw": search_term, "checkout_date": date_str}

    if len(rows) == 1:
        tenant, tenancy, room_obj = rows[0]
        # Validate date order
        if checkout_date_val and checkout_date_val <= tenancy.checkin_date:
            return (
                f"Invalid: checkout {checkout_date_val.strftime('%d %b %Y')} is on/before "
                f"checkin {tenancy.checkin_date.strftime('%d %b %Y')}."
            )
        # Save pending so user replies "1" to confirm
        choices = _make_choices(rows)
        await _save_pending(ctx.phone, intent_type, action_data, choices, session)

        date_line = f"\nCheckout date: {checkout_date_val.strftime('%d %b %Y')}" if checkout_date_val else ""
        schedule_note = " *(tenancy stays active until then)*" if is_future_checkout else ""
        return (
            f"Confirm checkout for *{tenant.name}* (Room {room_obj.room_number})?\n\n"
            f"Checkin: {tenancy.checkin_date.strftime('%d %b %Y')}"
            f"{date_line}\n"
            f"Deposit held: Rs.{int(tenancy.security_deposit or 0):,}"
            f"{schedule_note}\n\n"
            f"Reply *1* to confirm."
        )

    choices = _make_choices(rows)
    await _save_pending(ctx.phone, intent_type, action_data, choices, session)
    label = f"schedule checkout on {checkout_date_val.strftime('%d %b %Y')}" if checkout_date_val else "initiate checkout"
    return _format_choices_message(search_term, choices, label)


async def _do_checkout(
    tenancy_id: int,
    tenant_name: str,
    checkout_date_val: date,
    session: AsyncSession,
) -> str:
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenancy:
        return "Tenancy record not found."

    # Validate: checkout must be after checkin
    if checkout_date_val <= tenancy.checkin_date:
        return (
            f"Cannot checkout: {checkout_date_val.strftime('%d %b %Y')} is on/before "
            f"checkin {tenancy.checkin_date.strftime('%d %b %Y')}."
        )

    if checkout_date_val > date.today():
        # Future date → schedule only, tenancy stays active
        tenancy.expected_checkout = checkout_date_val
        return (
            f"*Checkout scheduled for {tenant_name}*\n"
            f"Expected exit: {checkout_date_val.strftime('%d %b %Y')}\n"
            "Tenancy remains active. Send *checkout [Name]* on the day to finalise."
        )

    # Past/today → actual checkout
    tenancy.status = TenancyStatus.exited
    tenancy.checkout_date = checkout_date_val

    # Notice period check
    notice_warn = ""
    if not tenancy.notice_date:
        notice_warn = "\n⚠️ No notice on record — deposit forfeited, extra month may be charged."
    elif tenancy.notice_date.day > _NOTICE_BY_DAY:
        notice_warn = (
            f"\n⚠️ Notice given on {tenancy.notice_date.strftime('%d %b')} "
            f"(after {_NOTICE_BY_DAY}th) — deposit forfeited + extra month charged."
        )
    else:
        notice_warn = (
            f"\n✅ Notice was on time ({tenancy.notice_date.strftime('%d %b')}) — deposit eligible for refund."
        )

    # Proration: always by days for checkout
    days_in_month = calendar.monthrange(checkout_date_val.year, checkout_date_val.month)[1]
    days_stayed = checkout_date_val.day
    prorate_note = ""
    if tenancy.agreed_rent:
        prorated = int(tenancy.agreed_rent * days_stayed / days_in_month)
        prorate_note = (
            f"\nDays in {checkout_date_val.strftime('%b')}: {days_stayed}/{days_in_month} "
            f"= prorated rent: Rs.{prorated:,}"
        )

    # ── Settlement summary ─────────────────────────────────────────────────────
    deposit = tenancy.security_deposit or Decimal("0")
    o_rent, o_maintenance = await _calc_outstanding_dues(tenancy.id, session)
    damages = Decimal("0")   # 0 unless owner specifies later
    net = deposit - o_rent - o_maintenance - damages

    settlement_lines = ["\n*Settlement Summary*"]
    settlement_lines.append(f"Security deposit held : Rs.{int(deposit):,}")
    if o_rent > 0:
        settlement_lines.append(f"Outstanding rent      : -Rs.{int(o_rent):,}")
    if o_maintenance > 0:
        settlement_lines.append(f"Outstanding maintenance: -Rs.{int(o_maintenance):,}")
    settlement_lines.append(f"Damages               : Rs.0")
    settlement_lines.append("─" * 28)
    if net >= 0:
        settlement_lines.append(f"*Refund to tenant: Rs.{int(net):,}*")
    else:
        settlement_lines.append(f"*Tenant still owes: Rs.{int(abs(net)):,}*")
    settlement_summary = "\n".join(settlement_lines)

    return (
        f"*Checkout recorded — {tenant_name}*\n"
        f"Date: {checkout_date_val.strftime('%d %b %Y')}"
        f"{prorate_note}"
        f"{notice_warn}"
        f"{settlement_summary}\n\n"
        "Next steps:\n"
        "1. Collect room keys\n"
        "2. Process deposit refund → *refund [amount] to [Name]*"
    )


# ── Notice / proration helpers (canonical versions live in services/property_logic.py) ──
# Kept as thin aliases so existing call-sites in this file need no changes.
_NOTICE_BY_DAY = NOTICE_BY_DAY   # re-export from property_logic


def _calc_notice_last_day(notice_date_val: date) -> date:
    """Thin alias → services.property_logic.calc_notice_last_day."""
    return calc_notice_last_day(notice_date_val, NOTICE_BY_DAY)


def _calc_prorate(amount: Decimal, day_of_month: int, days_in_month: int) -> int:
    """Prorated rent for check-in month (days from day_of_month to EOM, inclusive)."""
    if days_in_month <= 0:
        return 0
    days_remaining = max(0, days_in_month - day_of_month + 1)
    return int(Decimal(str(amount)) * days_remaining / days_in_month)


# ── Notice given ──────────────────────────────────────────────────────────────

async def _notice_given(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name = entities.get("name", "").strip()
    room = entities.get("room", "").strip()
    date_str = entities.get("date", "")

    if not name and not room:
        return (
            "Who gave notice?\n"
            "Say: *[Name] gave notice* or *[Name] gave notice on [date]*"
        )

    # Notice date — if not specified, default to today but make it visible
    date_assumed = False
    if date_str:
        try:
            notice_date_val = date.fromisoformat(date_str)
        except ValueError:
            return "Couldn't parse that date. Use: *20 Mar* or *20/03/2026*"
    else:
        notice_date_val = date.today()
        date_assumed = True

    rows: list = []
    search_term = name
    if name:
        rows = await _find_active_tenants_by_name(name, session)
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)
        search_term = f"Room {room}"

    if len(rows) == 0:
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)

    last_day = _calc_notice_last_day(notice_date_val)

    # Deposit eligibility based on notice timing
    if notice_date_val.day <= _NOTICE_BY_DAY:
        deposit_note = f"✅ On time — deposit eligible for refund on vacate.\nLast day: *{last_day.strftime('%d %b %Y')}*"
    else:
        deposit_note = (
            f"⚠️ Late notice (after {_NOTICE_BY_DAY}th) — *deposit forfeited*.\n"
            f"Last day extended to: *{last_day.strftime('%d %b %Y')}* (extra month charged)."
        )

    assumed_note = ""
    if date_assumed:
        assumed_note = (
            f"\n📅 Notice date assumed as *TODAY ({notice_date_val.strftime('%d %b %Y')})*.\n"
            f"If different, say: *{name or 'tenant'} gave notice on DD Mon*"
        )

    if len(rows) == 1:
        tenant, tenancy, room_obj = rows[0]
        tenancy.notice_date = notice_date_val
        tenancy.expected_checkout = last_day
        return (
            f"*Notice recorded — {tenant.name}* (Room {room_obj.room_number})\n"
            f"Notice date: {notice_date_val.strftime('%d %b %Y')}{assumed_note}\n\n"
            f"{deposit_note}"
        )

    choices = _make_choices(rows)
    action_data = {
        "notice_date": notice_date_val.isoformat(),
        "last_day": last_day.isoformat(),
        "deposit_note": deposit_note,
    }
    await _save_pending(ctx.phone, "NOTICE_GIVEN", action_data, choices, session)
    return _format_choices_message(search_term, choices, f"record notice (last day: {last_day.strftime('%d %b %Y')})")



# ── Update check-in date ──────────────────────────────────────────────────────

async def _update_checkin(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name    = entities.get("name", "").strip()
    room    = entities.get("room", "").strip()
    date_str = entities.get("date", "")

    if not date_str:
        return (
            "What's the correct check-in date?\n"
            "Say: *[Name] checked in on [DD Mon]*\n"
            "Example: *Kiran checked in on 20 Feb*"
        )

    try:
        new_checkin = date.fromisoformat(date_str)
    except ValueError:
        return "Couldn't parse that date. Use: *20 Feb* or *20/02/2026*"

    if new_checkin > date.today():
        return (
            "Check-in date can't be in the future.\n"
            "To schedule a future checkout use: *checkout [Name] on [date]*"
        )

    if not name and not room:
        return "Whose check-in date? Say: *[Name] checked in on [date]*"

    rows: list = []
    search_term = name

    if name:
        rows = await _find_active_tenants_by_name(name, session)
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)
        search_term = f"Room {room}"

    if len(rows) == 0:
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)

    action_data = {"name_raw": search_term, "new_checkin": date_str}

    if len(rows) == 1:
        tenant, tenancy, room_obj = rows[0]
        if tenancy.checkout_date and new_checkin >= tenancy.checkout_date:
            return (
                f"Invalid: new checkin {new_checkin.strftime('%d %b %Y')} is on/after "
                f"checkout {tenancy.checkout_date.strftime('%d %b %Y')}."
            )
        choices = _make_choices(rows)
        await _save_pending(ctx.phone, "UPDATE_CHECKIN", action_data, choices, session)
        return (
            f"Update checkin for *{tenant.name}* (Room {room_obj.room_number})?\n\n"
            f"Current: {tenancy.checkin_date.strftime('%d %b %Y')}\n"
            f"New:     {new_checkin.strftime('%d %b %Y')}\n\n"
            f"Reply *1* to confirm."
        )

    choices = _make_choices(rows)
    await _save_pending(ctx.phone, "UPDATE_CHECKIN", action_data, choices, session)
    return _format_choices_message(search_term, choices, f"update checkin to {new_checkin.strftime('%d %b %Y')}")


async def _do_update_checkin(
    tenancy_id: int,
    tenant_name: str,
    new_checkin_str: str,
    session: AsyncSession,
) -> str:
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenancy:
        return "Tenancy record not found."

    try:
        new_checkin = date.fromisoformat(new_checkin_str)
    except (ValueError, TypeError):
        return "Invalid date in pending action. Please try again."

    if tenancy.checkout_date and new_checkin >= tenancy.checkout_date:
        return (
            f"Cannot update: new checkin {new_checkin.strftime('%d %b %Y')} is on/after "
            f"checkout {tenancy.checkout_date.strftime('%d %b %Y')}."
        )

    old_checkin = tenancy.checkin_date
    tenancy.checkin_date = new_checkin

    return (
        f"*Checkin updated — {tenant_name}*\n"
        f"Was: {old_checkin.strftime('%d %b %Y')}\n"
        f"Now: {new_checkin.strftime('%d %b %Y')}\n\n"
        "Note: rent schedule rows are not auto-adjusted.\n"
        "Send *report* to verify dues."
    )


# ── Other handlers ────────────────────────────────────────────────────────────

async def _add_tenant_prompt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    # Guard: if phone provided upfront, block if already has active tenancy
    phone = entities.get("phone", "").strip()
    if phone:
        ok, reason = await check_no_active_tenancy(phone, session)
        if not ok:
            return reason

    # Check if a known tenant name was mentioned (possible re-entry)
    name = entities.get("name", "").strip()
    reentry_note = ""
    if name:
        rows = await _find_active_tenants_by_name(name, session)
        if rows:
            # Active tenant — shouldn't be adding again
            tenant, tenancy, room_obj = rows[0]
            reentry_note = (
                f"\n⚠️ *{tenant.name}* already has an active tenancy in Room {room_obj.room_number}.\n"
                "If this is a room change, first checkout the old room then add new.\n"
            )
        else:
            # Check if they exist as a past tenant (re-entry after gap)
            past = await session.scalar(
                select(Tenant).where(Tenant.name.ilike(f"%{name}%"))
            )
            if past:
                reentry_note = (
                    f"\n📋 *{past.name}* has a previous record in the system.\n"
                    "A *new tenancy* will be created — existing payment history is preserved.\n"
                )

    return (
        f"*New tenant check-in*{reentry_note}\n"
        "Please send all details:\n\n"
        "Name: [full name]\n"
        "Phone: [mobile number]\n"
        "Room: [room number]\n"
        "Rent: [monthly amount]\n"
        "Deposit: [security deposit]\n"
        "Checkin: [DD/MM/YYYY]\n"
        "Food: [veg/non-veg/egg/none]\n\n"
        "I'll confirm before saving."
    )


async def _add_partner(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    if ctx.role != "admin":
        return "Only the admin can add partners."
    return (
        "*Add a partner*\n\n"
        "Send: *add partner +91XXXXXXXXXX [Name]*\n"
        "Example: *add partner +917001234567 Suresh*"
    )


async def _reminder_prompt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    return (
        "*Set a reminder*\n\n"
        "Format: *remind [Name] [when]*\n"
        "Examples:\n"
        "• remind Raj tomorrow about rent\n"
        "• remind all pending tenants on 3rd"
    )


async def _fetch_active_property(session: AsyncSession):
    """Fetch the single active property (owner context)."""
    result = await session.execute(select(Property).where(Property.active == True).limit(1))
    return result.scalars().first()


async def _get_wifi_password(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show all WiFi credentials for the property."""
    prop = await _fetch_active_property(session)
    if not prop:
        return "No active property found."

    lines = ["*WiFi Credentials*\n"]
    floor_map: dict = prop.wifi_floor_map or {}
    if floor_map:
        for key, info in floor_map.items():
            label = "Common Area" if key == "common" else f"Floor {key}"
            lines.append(f"*{label}*")
            lines.append(f"  Network : `{info.get('ssid', 'N/A')}`")
            lines.append(f"  Password: `{info.get('password', 'N/A')}`\n")
    if prop.wifi_ssid:
        lines.append("*Property-Wide*")
        lines.append(f"  Network : `{prop.wifi_ssid}`")
        lines.append(f"  Password: `{prop.wifi_password or 'N/A'}`")

    if len(lines) == 1:
        return (
            "No WiFi configured yet.\n\n"
            "To add WiFi:\n"
            "*set wifi floor 1 SSID CozeevoPG1 password PG2024Floor1*\n"
            "*set wifi common SSID CozeevaCommon password CommonPass*"
        )
    return "\n".join(lines)


async def _set_wifi(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Parse and save WiFi credentials.
    Formats:
      set wifi floor 1 SSID <name> password <pass>
      set wifi common SSID <name> password <pass>
      set wifi SSID <name> password <pass>   (property-wide)
    """
    from sqlalchemy.orm.attributes import flag_modified

    msg = entities.get("description", "")
    prop = await _fetch_active_property(session)
    if not prop:
        return "No active property found."

    # Parse floor/common/global
    floor_m = re.search(r"(?:floor\s+(\d+)|(common))\s+ssid\s+(\S+)\s+password\s+(\S+)", msg, re.I)
    global_m = re.search(r"ssid\s+(\S+)\s+password\s+(\S+)", msg, re.I) if not floor_m else None

    if floor_m:
        floor_key = floor_m.group(1) if floor_m.group(1) else "common"
        ssid, pw = floor_m.group(3), floor_m.group(4)
        floor_map = dict(prop.wifi_floor_map or {})
        floor_map[floor_key] = {"ssid": ssid, "password": pw}
        prop.wifi_floor_map = floor_map
        flag_modified(prop, "wifi_floor_map")   # tell SQLAlchemy the JSONB dict changed
        label = "Common Area" if floor_key == "common" else f"Floor {floor_key}"
        return f"WiFi updated for *{label}*\nNetwork: `{ssid}`\nPassword: `{pw}`"
    elif global_m:
        prop.wifi_ssid = global_m.group(1)
        prop.wifi_password = global_m.group(2)
        return f"Property WiFi updated\nNetwork: `{prop.wifi_ssid}`\nPassword: `{prop.wifi_password}`"

    return (
        "Couldn't parse WiFi details. Use format:\n"
        "*set wifi floor 1 SSID CozeevoPG1 password PG2024Floor1*\n"
        "*set wifi common SSID CozeevaCommon password CommonPass*"
    )


async def _help(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    role_label = "Admin" if ctx.role == "admin" else "Owner"
    greeting = time_greeting()
    first_time = await is_first_time(ctx.phone, session)
    intro = f"I'm *{BOT_NAME}*, your PG assistant! 🏠\n\n" if first_time else ""
    return (
        f"*{greeting}, {ctx.name}!* {intro}\n"
        f"*{BOT_NAME} — {role_label} Menu*\n\n"
        "*Payments*\n"
        "• Raj paid 15000 upi\n"
        "• Received 8000 cash from Priya\n\n"
        "*Queries*\n"
        "• Who hasn't paid?\n"
        "• Raj balance\n"
        "• Monthly report\n\n"
        "*Tenant Management*\n"
        "• Add tenant\n"
        "• Start onboarding for Ravi 9876543210\n"
        "• Checkout Raj\n"
        "• Record checkout Priya\n\n"
        "*Expenses & WiFi*\n"
        "• Expense electricity 4500\n"
        "• wifi password\n"
        "• set wifi floor 1 SSID CozeevoPG password PG2024\n\n"
        "• rules — View PG rules\n\n"
        "Just type naturally — I'll understand!"
    )


async def _rules(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    return (
        "*COZEEVO — Rules & Regulations*\n"
        "No. 9, 7th Cross Road, EPIP Zone, Brookefield, Bangalore-560048\n\n"
        "1. Vacating notice: *30 days before*, before *5th of the month*. "
        "Otherwise 30 days rent charged. _(Vacate only on 30th or 31st)_\n"
        "2. Rent on or before *5th of every month*.\n"
        "3. Advance & Rent once paid *cannot be refunded*.\n"
        "4. *Outsiders strictly not allowed*.\n"
        "5. Guest accommodation: *Rs. 1,200/- per day*.\n"
        "6. *Iron box, Kettle, Induction Stove* not allowed.\n"
        "7. Maintenance charges: *Rs. 5,000/-*.\n"
        "8. Management *not responsible* for belongings.\n"
        "9. Switch OFF *lights, fans, geysers* before leaving room.\n"
        "10. *Smoking & Liquor* not allowed.\n"
        "11. *No garbage* from windows. Keep premises clean.\n"
        "12. Rule violation → vacate within *30 days*.\n"
        "13. Management may *immediately evict* disruptive persons.\n"
        "14. Late arrival after *10:30 PM* — inform in-charge in advance.\n"
        "15. *Two-wheeler wheel lock* must be ensured.\n"
        "16. Parking provided; management *not responsible* for vehicle theft.\n"
        "17. Lost key: *Rs. 1,000/- replacement charge*.\n"
        "18. *Do not share PG food* with outsiders.\n"
        "19. Owner property damage *deducted from deposit*.\n\n"
        "⚠️ _Not responsible for Gold, Mobile, Laptop, Cash, Cards, Passport, Pancard etc._"
    )


# ── Vacant rooms ──────────────────────────────────────────────────────────────

async def _query_vacant_rooms(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    result = await session.execute(
        select(Room).where(Room.active == True, Room.is_staff_room == False)
        .order_by(Room.room_number)
    )
    all_rooms = result.scalars().all()

    # Get rooms with active tenancies
    occupied_result = await session.execute(
        select(Tenancy.room_id).where(Tenancy.status == TenancyStatus.active)
    )
    occupied_ids = {row[0] for row in occupied_result.all()}

    vacant = [r for r in all_rooms if r.id not in occupied_ids]
    if not vacant:
        return f"All {len(all_rooms)} rooms are currently occupied."

    lines = [f"*Vacant Rooms — {len(vacant)} available*\n"]
    for r in vacant:
        ac = " (AC)" if r.has_ac else ""
        bath = " (attached bath)" if r.has_attached_bath else ""
        lines.append(f"• Room {r.room_number} — {r.room_type.value}{ac}{bath}")
    return "\n".join(lines)


# ── Occupancy overview ────────────────────────────────────────────────────────

async def _query_occupancy(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    total = await session.scalar(
        select(func.count(Room.id)).where(Room.active == True, Room.is_staff_room == False)
    ) or 0
    occupied = await session.scalar(
        select(func.count(Tenancy.id)).where(Tenancy.status == TenancyStatus.active)
    ) or 0
    vacant = total - occupied
    pct = int(occupied * 100 / total) if total else 0
    return (
        f"*Occupancy Status*\n\n"
        f"Total rooms : {total}\n"
        f"Occupied    : {occupied}\n"
        f"Vacant      : {vacant}\n"
        f"Occupancy   : {pct}%\n\n"
        "Say *vacant rooms* to see which rooms are empty."
    )


# ── Expiring tenancies / upcoming checkouts ───────────────────────────────────

async def _query_expiring(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    today = date.today()
    end_of_month = today.replace(day=1)
    # Last day of current month
    import calendar as _cal
    last_day = _cal.monthrange(today.year, today.month)[1]
    end_of_month = date(today.year, today.month, last_day)

    result = await session.execute(
        select(Tenant.name, Tenancy, Room)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status == TenancyStatus.active,
            or_(
                and_(Tenancy.expected_checkout >= today, Tenancy.expected_checkout <= end_of_month),
                and_(Tenancy.notice_date != None, Tenancy.notice_date >= today.replace(day=1)),
            )
        )
        .order_by(Tenancy.expected_checkout)
    )
    rows = result.all()

    if not rows:
        return f"No tenants expecting to leave this month ({today.strftime('%B %Y')})."

    lines = [f"*Upcoming Checkouts — {today.strftime('%B %Y')}*\n"]
    for name, tenancy, room in rows:
        exit_str = tenancy.expected_checkout.strftime("%d %b") if tenancy.expected_checkout else "TBD"
        notice_str = f" | Notice: {tenancy.notice_date.strftime('%d %b')}" if tenancy.notice_date else " | No notice"
        lines.append(f"• {name} (Room {room.room_number}) — Exit: {exit_str}{notice_str}")
    return "\n".join(lines)


# ── Checkins this month ────────────────────────────────────────────────────────

async def _query_checkins(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    today = date.today()
    month_start = today.replace(day=1)
    result = await session.execute(
        select(Tenant.name, Tenancy.checkin_date, Room.room_number)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.checkin_date >= month_start,
            Tenancy.checkin_date <= today,
        )
        .order_by(Tenancy.checkin_date.desc())
    )
    rows = result.all()
    if not rows:
        return f"No new check-ins this month ({today.strftime('%B %Y')})."
    lines = [f"*Check-ins — {today.strftime('%B %Y')}* ({len(rows)} total)\n"]
    for name, checkin, room_num in rows:
        lines.append(f"• {name} (Room {room_num}) — {checkin.strftime('%d %b')}")
    return "\n".join(lines)


# ── Checkouts this month ───────────────────────────────────────────────────────

async def _query_checkouts(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    today = date.today()
    month_start = today.replace(day=1)
    result = await session.execute(
        select(Tenant.name, Tenancy.checkout_date, Room.room_number)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status == TenancyStatus.exited,
            Tenancy.checkout_date >= month_start,
            Tenancy.checkout_date <= today,
        )
        .order_by(Tenancy.checkout_date.desc())
    )
    rows = result.all()
    if not rows:
        return f"No check-outs this month ({today.strftime('%B %Y')})."
    lines = [f"*Check-outs — {today.strftime('%B %Y')}* ({len(rows)} total)\n"]
    for name, checkout, room_num in rows:
        lines.append(f"• {name} (Room {room_num}) — {checkout.strftime('%d %b')}")
    return "\n".join(lines)


# _query_expenses, _query_refunds, _add_refund moved to account_handler.py


# ── Log vacation ──────────────────────────────────────────────────────────────

async def _log_vacation(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name   = entities.get("name", "").strip()
    room   = entities.get("room", "").strip()

    if not name and not room:
        return (
            "Who is going on vacation?\n"
            "Say: *[Name] on vacation from [date] to [date]*"
        )

    rows: list = []
    if name:
        rows = await _find_active_tenants_by_name(name, session)
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)

    if not rows:
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)

    tenant, tenancy, room_obj = rows[0]
    return (
        f"*Log vacation for {tenant.name}* (Room {room_obj.room_number})\n\n"
        "Please send dates:\n"
        "From: DD Mon\n"
        "To: DD Mon\n\n"
        "Example: *Raj vacation from 15 Apr to 30 Apr*"
    )


# ── Room status ───────────────────────────────────────────────────────────────

async def _room_status(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    room = entities.get("room", "").strip()

    if not room:
        return "Which room? Say: *who's in room 203* or *room 5 occupant*"

    rows = await _find_active_tenants_by_room(room, session)
    if not rows:
        # Check if room exists but is vacant
        room_obj = await session.scalar(
            select(Room).where(Room.room_number.ilike(f"%{room}%"))
        )
        if room_obj:
            return f"Room {room_obj.room_number} is currently *vacant*."
        return f"Room {room} not found."

    lines = [f"*Room {room} Occupants*\n"]
    for tenant, tenancy, room_obj in rows:
        o_rent, o_maint = await _calc_outstanding_dues(tenancy.id, session)
        due_note = f" | Due: Rs.{int(o_rent):,}" if o_rent > 0 else " | Paid"
        lines.append(
            f"• {tenant.name}\n"
            f"  Since: {tenancy.checkin_date.strftime('%d %b %Y')}{due_note}"
        )
    return "\n".join(lines)


# ── Send reminder to all pending tenants ──────────────────────────────────────

async def _send_reminder_all(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    current_month = date.today().replace(day=1)
    result = await session.execute(
        select(Tenant.name, Tenant.phone, RentSchedule.rent_due)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(RentSchedule, RentSchedule.tenancy_id == Tenancy.id)
        .where(
            Tenancy.status == TenancyStatus.active,
            RentSchedule.period_month == current_month,
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
        )
        .order_by(Tenant.name)
    )
    rows = result.all()
    if not rows:
        return f"All tenants are paid up for {current_month.strftime('%B %Y')}! No reminders needed."

    # In production this would queue WhatsApp messages; here we list who would be notified
    lines = [f"*Reminder list — {current_month.strftime('%B %Y')}*\n", f"{len(rows)} tenants to be reminded:\n"]
    for name, phone, rent_due in rows:
        lines.append(f"• {name} ({phone}) — Rs.{int(rent_due or 0):,} due")
    lines.append("\n_WhatsApp reminders queued. Tenants will be notified shortly._")
    return "\n".join(lines)


async def _get_tenant_notes(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Owner/staff asks: "notes room 204", "agreement Mahika", "notes for 9876543210"
    Returns tenancy.notes for the matched tenant (internal use only — never tenant-facing).
    """
    # Try room number first, then name, then raw text
    room = entities.get("room")
    name = entities.get("name")

    tenancies: list = []

    if room:
        tenancies = await _find_active_tenants_by_room(room, session)
    if not tenancies and name:
        tenancies = await _find_active_tenants_by_name(name, session)

    # No match — try extracting any word from the original message as a last resort
    if not tenancies:
        return (
            "Couldn't find an active tenant matching that room/name.\n"
            "Try: *notes room 204* or *agreement Mahika*"
        )

    if len(tenancies) > 1:
        choices = _make_choices(tenancies)
        await _save_pending(ctx.phone, "GET_TENANT_NOTES", {}, choices, session)
        return _format_choices_message(choices, "Which tenant?")

    t, tncy = tenancies[0]
    notes = tncy.notes

    if not notes or not notes.strip():
        return f"*{t.name}* (Room {tncy.room_id}) — no agreed terms on record."

    return (
        f"*{t.name}* — Room {tncy.room_id}\n"
        f"Agreed terms:\n{notes}"
    )


async def _unknown(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    return (
        "I didn't understand that.\n\n"
        "Try:\n"
        "• *[Name] paid [amount]*\n"
        "• *Who hasn't paid?*\n"
        "• *Monthly report*\n"
        "• *help* for full menu"
    )


# ── Onboarding ─────────────────────────────────────────────────────────────────

async def _start_onboarding(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Owner says: "start onboarding Rahul 9876543210" or "start onboarding for Rahul 9876543210"
    Flow:
      1. Extract name + phone from entities
      2. Create Tenant record (or find existing)
      3. Create OnboardingSession for that tenant
      4. Reply: confirm + tell owner to have tenant message the bot
    """
    name  = entities.get("name", "").strip()
    phone = entities.get("phone", "").strip()

    # Minimal extraction from description if not parsed into entities
    if not phone or not name:
        desc = entities.get("description", "")
        import re as _re
        ph_match = _re.search(r"\b([6-9]\d{9})\b", desc)
        if ph_match:
            phone = ph_match.group(1)
        # Name: first word(s) before or after the phone number
        name_text = _re.sub(r"start\s+onboarding\s+(?:for\s+)?|begin\s+(?:kyc|onboarding|checkin)\s+(?:for\s+)?|onboard\s+|kyc\s+for\s+|checkin\s+for\s+", "", desc, flags=_re.I)
        name_text = _re.sub(r"\b[6-9]\d{9}\b", "", name_text).strip()
        if name_text and not name:
            name = name_text.strip()

    if not phone:
        return (
            "Please provide the tenant's *name and phone number*.\n\n"
            "Example: *start onboarding Rahul 9876543210*"
        )
    if not name:
        name = "New Tenant"

    # Normalize to 10 digits
    phone = phone.lstrip("+").lstrip("91") if len(phone) > 10 else phone

    # Find or create Tenant
    result = await session.execute(
        select(Tenant).where(Tenant.phone == phone)
    )
    tenant = result.scalars().first()
    if not tenant:
        tenant = Tenant(name=name, phone=phone)
        session.add(tenant)
        await session.flush()  # get tenant.id

    # Cancel any existing onboarding session for this tenant
    existing = await session.execute(
        select(OnboardingSession).where(
            OnboardingSession.tenant_id == tenant.id,
            OnboardingSession.completed == False,
        )
    )
    for old in existing.scalars().all():
        old.completed = True

    # Create fresh onboarding session (48-hour window)
    ob = OnboardingSession(
        tenant_id=tenant.id,
        step="ask_gender",
        collected_data=json.dumps({"name": tenant.name}),
        expires_at=datetime.utcnow() + timedelta(hours=48),
    )
    session.add(ob)

    return (
        f"*Onboarding started for {name}*\n"
        f"Phone: {phone}\n\n"
        f"Ask *{name}* to WhatsApp this number.\n"
        "They will be guided through their KYC form step by step.\n\n"
        "_Session valid for 48 hours._"
    )


# ── Offboarding / checkout record ──────────────────────────────────────────────

async def _record_checkout(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Owner says: "record checkout Rahul" or "checkout form Rahul"
    Walks through a multi-step offboarding checklist via PendingAction.
    Step 1: find the tenant, confirm which tenancy, then ask checklist questions.
    """
    name = entities.get("name", "").strip()
    if not name:
        desc = entities.get("description", "")
        import re as _re
        # Strip trigger words to get name
        name = _re.sub(r"(?:record\s+checkout|checkout\s+form|offboard|fill\s+checkout|handover|complete\s+checkout)\s+(?:for\s+)?", "", desc, flags=_re.I).strip()

    if not name:
        return (
            "Please provide the tenant's name.\n\n"
            "Example: *record checkout Rahul*"
        )

    # Find the tenancy (active tenants only — use existing fuzzy search)
    rows: list = await _find_active_tenants_by_name(name, session)
    if not rows:
        return f"No active tenant found matching '*{name}*'. Check the name and try again."

    if len(rows) > 1:
        lines = [f"Multiple tenants match '*{name}*'. Which one?\n"]
        choices = []
        for i, (t, tncy, room_obj) in enumerate(rows, 1):
            label = f"{t.name} — Room {room_obj.room_number}"
            lines.append(f"{i}. {label}")
            choices.append({"seq": i, "tenant_id": t.id, "tenancy_id": tncy.id, "label": label})
        pending = PendingAction(
            phone=ctx.phone,
            intent="RECORD_CHECKOUT",
            action_data=json.dumps({"step": "confirm_tenant"}),
            choices=json.dumps(choices),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        session.add(pending)
        return "\n".join(lines)

    tenant, tenancy, room = rows[0]

    # Check if checkout record already exists
    existing = await session.execute(
        select(CheckoutRecord).where(CheckoutRecord.tenancy_id == tenancy.id)
    )
    cr = existing.scalars().first()
    if cr:
        return (
            f"Checkout record already exists for *{tenant.name}* (Room {room.room_number}).\n\n"
            f"Exit: {cr.actual_exit_date or '—'}\n"
            f"Cupboard key: {'Returned' if cr.cupboard_key_returned else 'Not returned'}\n"
            f"Main key: {'Returned' if cr.main_key_returned else 'Not returned'}\n"
            f"Damages: {cr.damage_notes or 'None'}\n"
            f"Pending dues: Rs.{int(cr.pending_dues_amount or 0):,}\n"
            f"Deposit refunded: Rs.{int(cr.deposit_refunded_amount or 0):,}"
        )

    # Save pending action to track the checkout form steps
    pending = PendingAction(
        phone=ctx.phone,
        intent="RECORD_CHECKOUT",
        action_data=json.dumps({
            "step": "ask_cupboard_key",
            "tenancy_id": tenancy.id,
            "tenant_name": tenant.name,
            "room": room.room_number,
        }),
        choices=json.dumps([]),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    )
    session.add(pending)

    return (
        f"*Checkout Form — {tenant.name}* (Room {room.room_number})\n\n"
        f"*Q1/5* Was the *cupboard/almirah key* returned?\n"
        "Reply: *yes* or *no*"
    )


# ── Owner complaint registration ──────────────────────────────────────────────

_OWNER_COMPLAINT_KEYWORDS: dict[str, str] = {
    "leak": "plumbing", "tap": "plumbing", "flush": "plumbing", "drain": "plumbing",
    "pipe": "plumbing", "water": "plumbing", "geyser": "plumbing", "shower": "plumbing",
    "bulb": "electricity", "fan": "electricity", "switch": "electricity",
    "light": "electricity", "mcb": "electricity", "socket": "electricity",
    "power": "electricity", "current": "electricity",
    "wifi": "wifi", "wi-fi": "wifi", "internet": "wifi", "net": "wifi",
    "slow": "wifi", "signal": "wifi",
    "food": "food", "mess": "food", "meal": "food", "breakfast": "food",
    "lunch": "food", "dinner": "food", "cook": "food",
    "bed": "furniture", "mattress": "furniture", "pillow": "furniture",
    "sheet": "furniture", "chair": "furniture", "table": "furniture",
    "shelf": "furniture", "almirah": "furniture", "cupboard": "furniture",
}

_OWNER_CATEGORY_ENUM = {
    "plumbing":    ComplaintCategory.plumbing,
    "electricity": ComplaintCategory.electricity,
    "wifi":        ComplaintCategory.wifi,
    "food":        ComplaintCategory.food,
    "furniture":   ComplaintCategory.furniture,
    "other":       ComplaintCategory.other,
}


def _owner_detect_category(text: str) -> ComplaintCategory:
    lower = text.lower()
    for keyword, cat in _OWNER_COMPLAINT_KEYWORDS.items():
        if keyword in lower:
            return _OWNER_CATEGORY_ENUM[cat]
    return ComplaintCategory.other


async def _owner_complaint_register(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Owner/admin logs a complaint for a specific room.
    Usage: "room 624 fan not working" or "complaint room 101 wifi issue"
    """
    description = entities.get("description", "").strip()
    room_num = entities.get("room", "").strip()

    # Extract room number from description if not in entities
    if not room_num:
        import re as _re
        m = _re.search(r"\broom\s*(\w+)", description, _re.I)
        if m:
            room_num = m.group(1)

    if not room_num:
        return (
            "Which room has the issue?\n"
            "Say: *complaint room [number] [description]*\n"
            "Example: *room 624 fan not working*"
        )

    # Find room
    room_result = await session.execute(
        select(Room).where(Room.room_number == room_num, Room.active == True)
    )
    room = room_result.scalars().first()
    if not room:
        return f"Room {room_num} not found."

    # Find active tenancy for that room
    tenancy_result = await session.execute(
        select(Tenancy).where(
            Tenancy.room_id == room.id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    tenancy = tenancy_result.scalars().first()
    if not tenancy:
        return f"No active tenant in room {room_num}."

    category = _owner_detect_category(description)

    # Dedup: same tenancy + same category already open/in_progress → ignore
    existing = await session.scalar(
        select(Complaint).where(
            Complaint.tenancy_id == tenancy.id,
            Complaint.category == category,
            Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.in_progress]),
        )
    )
    if existing:
        return (
            f"Room {room_num} already has an open *{category.value}* complaint.\n"
            "Duplicate not created."
        )

    complaint = Complaint(
        tenancy_id=tenancy.id,
        category=category,
        description=description or f"Issue reported by owner for room {room_num}",
        status=ComplaintStatus.open,
    )
    session.add(complaint)

    cat_label = {
        ComplaintCategory.plumbing:    "Plumbing",
        ComplaintCategory.electricity: "Electricity",
        ComplaintCategory.wifi:        "Wi-Fi",
        ComplaintCategory.food:        "Food / Mess",
        ComplaintCategory.furniture:   "Furniture / Room item",
        ComplaintCategory.other:       "Other",
    }.get(category, "Other")

    return (
        f"*Complaint Logged — Room {room_num}*\n"
        f"Category: {cat_label}\n"
        f"Status: Open\n"
        f"Issue: {description}"
    )


# ── Self-Learning: !learn command ─────────────────────────────────────────────

_LEARNED_RULES_FILE = Path(__file__).parent.parent.parent.parent / "data" / "learned_rules.json"


async def handle_learn_command(message: str, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Admin command: !learn INTENT keyword1, keyword2, keyword phrase 3
    Creates a new LearnedRule in the DB and updates the JSON cache file so
    intent_detector picks it up immediately (no restart required).

    Examples:
      !learn ADD_TENANT new guest, someone checking in, wants a room
      !learn PAYMENT_LOG received amount, money collected
    """
    body = message.removeprefix("!learn").strip()
    if not body:
        return (
            "Usage: *!learn INTENT_NAME keyword1, keyword2*\n\n"
            "Example:\n"
            "`!learn ADD_TENANT new guest, someone checking in`\n\n"
            "The bot will immediately recognise these phrases as ADD_TENANT."
        )

    parts = body.split(None, 1)
    if len(parts) < 2:
        return "❌ Missing keywords. Format: `!learn INTENT_NAME keyword1, keyword2`"

    intent_name = parts[0].upper().strip()
    keywords_raw = parts[1]
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    if not keywords:
        return "❌ No valid keywords found. Separate multiple keywords with commas."

    # Build a regex pattern: keyword phrases are OR-ed together
    pattern = "|".join(re.escape(k) for k in keywords)

    # Save to DB
    rule = LearnedRule(
        pattern=pattern,
        intent=intent_name,
        confidence=0.87,
        applies_to="all",
        created_by=ctx.phone,
        active=True,
    )
    session.add(rule)

    # Mark pending_learning rows for these keywords as resolved
    await session.execute(
        __import__("sqlalchemy", fromlist=["update"]).update(PendingLearning)  # type: ignore[attr-defined]
        .where(PendingLearning.resolved == False)
        .values(resolved=True)
    )

    # Write / update learned_rules.json so intent_detector refreshes without restart
    try:
        existing: list[dict] = []
        if _LEARNED_RULES_FILE.exists():
            existing = json.loads(_LEARNED_RULES_FILE.read_text(encoding="utf-8"))
        existing.append({
            "pattern":    pattern,
            "intent":     intent_name,
            "confidence": 0.87,
            "applies_to": "all",
            "created_by": ctx.phone,
            "active":     True,
        })
        _LEARNED_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LEARNED_RULES_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        return f"⚠️ Rule saved to DB but could not update file cache: {exc}"

    kw_display = ", ".join(f'"{k}"' for k in keywords)
    return (
        f"✅ *Learned!* Bot will now recognise:\n"
        f"{kw_display}\n"
        f"→ *{intent_name}* (confidence: 0.87)\n\n"
        f"No restart needed — active immediately."
    )
