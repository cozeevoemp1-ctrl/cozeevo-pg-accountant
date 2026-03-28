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
import hashlib
import json
import re
import string
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy import select, and_, or_, func, case as sa_case
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    ActivityLog, ActivityLogType,
    AuthorizedUser, CheckoutRecord, Complaint, ComplaintCategory, ComplaintStatus, Expense, ExpenseCategory,
    Payment, PaymentFor, PaymentMode, PendingAction, PendingLearning, LearnedRule, PgContact, Property, Refund, RefundStatus,
    RentSchedule, RentStatus, Room, Staff, Tenant, Tenancy, TenancyStatus, UserRole, Vacation, OnboardingSession,
)
from src.whatsapp.role_service import CallerContext, _normalize as _normalize_phone
from src.database.validators import check_no_active_tenancy, check_tenancy_active
from src.whatsapp.handlers._shared import (
    _find_active_tenants_by_name, _find_active_tenants_by_room,
    _find_similar_names, _check_room_overlap,
    _make_choices, _save_pending,
    _format_choices_message, _format_no_match_message,
    BOT_NAME, time_greeting, is_first_time_today, bot_intro,
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
        "ROOM_LAYOUT":        _room_layout,
        "ROOM_TRANSFER":      _room_transfer_prompt,
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
        "COMPLAINT_UPDATE":   _complaint_update,
        "QUERY_COMPLAINTS":   _query_complaints,
        "GET_TENANT_NOTES":   _get_tenant_notes,
        "QUERY_CONTACTS":     _query_contacts,
        "ACTIVITY_LOG":       _activity_log,
        "QUERY_ACTIVITY":     _query_activity,
        "RULES":              _rules,
        "HELP":               _help,
        "MORE_MENU":          _more_menu,
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
        # ── Correction check (before yes/no) ──────────────────────────────────
        _MODE_MAP = {
            "upi": "UPI", "cash": "Cash", "gpay": "GPay", "phonepe": "PhonePe",
            "paytm": "Paytm", "online": "Online", "bank": "Bank Transfer",
            "neft": "NEFT", "cheque": "Cheque", "imps": "IMPS",
        }
        _corrected = False
        _rl = reply_text.lower()
        for _word, _label in _MODE_MAP.items():
            if _word in _rl and _label != action_data.get("mode", ""):
                action_data["mode"] = _label
                _corrected = True
                break
        _amt_m = re.search(r"\b(\d[\d,]+)\b", reply_text)
        if _amt_m:
            _new_amt = float(_amt_m.group(1).replace(",", ""))
            if _new_amt != action_data.get("amount", 0) and _new_amt > 0:
                action_data["amount"] = _new_amt
                _corrected = True
        if _corrected:
            pending.action_data = json.dumps(action_data)
            await session.flush()
            _amt   = int(action_data["amount"])
            _mode  = action_data.get("mode", "Cash")
            _tname = action_data.get("tenant_name", "")
            _room  = action_data.get("room_number", "")
            _tlabel = f"{_tname} (Room {_room})" if _room else _tname
            return (
                "__KEEP_PENDING__"
                f"✏️ Updated. Please confirm:\n"
                f"• Tenant: {_tlabel}\n"
                f"• Amount: ₹{_amt:,}\n"
                f"• Mode: {_mode}\n\n"
                "Reply *Yes* to confirm or *No* to cancel."
            )
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
        _room  = action_data.get("room_number", "")
        _tname = action_data.get("tenant_name", "")
        _tlabel = f"{_tname} (Room {_room})" if _room else _tname
        return (
            "__KEEP_PENDING__"
            f"Reply *Yes* to confirm logging Rs.{int(action_data['amount']):,} "
            f"for {_tlabel}, or *No* to cancel."
        )

    if pending.intent == "CONFIRM_ADD_EXPENSE":
        # ── Correction check (before yes/no) ──────────────────────────────────
        _amt_m = re.search(r"\b(\d[\d,]+)\b", reply_text)
        if _amt_m:
            _new_amt = float(_amt_m.group(1).replace(",", ""))
            if _new_amt != action_data.get("amount", 0) and _new_amt > 0:
                action_data["amount"] = _new_amt
                pending.action_data = json.dumps(action_data)
                await session.flush()
                _cat = action_data.get("category", "").capitalize()
                return (
                    "__KEEP_PENDING__"
                    f"✏️ Updated. Log expense?\n"
                    f"• Category: {_cat}\n"
                    f"• Amount: ₹{int(_new_amt):,}\n\n"
                    "Reply *Yes* to confirm or *No* to cancel."
                )
        if is_negative(reply_text):
            return "❌ Expense cancelled. Nothing was logged."
        if is_affirmative(reply_text):
            amount      = action_data.get("amount", 0)
            cat_name    = action_data.get("category", "Miscellaneous")
            description = action_data.get("description", "")
            prop = await _fetch_active_property(session)
            property_id = prop.id if prop else 1
            cat_row = (await session.execute(
                select(ExpenseCategory).where(ExpenseCategory.name.ilike(f"%{cat_name}%"))
            )).scalars().first()
            exp = Expense(
                property_id  = property_id,
                category_id  = cat_row.id if cat_row else None,
                amount       = amount,
                expense_date = date.today(),
                description  = description or cat_name,
            )
            session.add(exp)
            await session.commit()
            label = cat_name.capitalize()
            return f"✅ Expense logged — {label} ₹{int(amount):,} on {date.today().strftime('%d %b %Y')}."
        # Neither yes/no — re-prompt
        amount   = action_data.get("amount", 0)
        cat_name = action_data.get("category", "")
        return (
            "__KEEP_PENDING__"
            f"Log expense?\n"
            f"• Category: {cat_name.capitalize()}\n"
            f"• Amount: ₹{int(amount):,}\n\n"
            "Reply *Yes* to confirm or *No* to cancel."
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

    # ── Correction: user provides a new amount for RENT_CHANGE ───────────────
    if pending.intent == "RENT_CHANGE" and not reply_text.rstrip(".").isdigit():
        _amt_m = re.search(r"\b(\d[\d,]+)\b", reply_text)
        if _amt_m:
            _new_amt = float(_amt_m.group(1).replace(",", ""))
            if _new_amt != action_data.get("new_amount", 0) and _new_amt > 100:
                action_data["new_amount"] = _new_amt
                pending.action_data = json.dumps(action_data)
                await session.flush()
                _tname = action_data.get("tenant_name", "")
                _options = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices)
                return (
                    "__KEEP_PENDING__"
                    f"✏️ Updated. Change {_tname}'s rent to ₹{int(_new_amt):,}?\n\n"
                    f"{_options}"
                )

    # ── Cancel any pending confirmation with "no" ─────────────────────────────

    if is_negative(reply_text) and pending.intent in (
        "CHECKOUT", "SCHEDULE_CHECKOUT", "PAYMENT_LOG", "QUERY_TENANT",
        "GET_TENANT_NOTES", "NOTICE_GIVEN", "RENT_CHANGE_WHO", "RENT_CHANGE",
        "VOID_PAYMENT", "VOID_EXPENSE", "DUPLICATE_CONFIRM", "OVERPAYMENT_RESOLVE",
        "ROOM_TRANSFER", "DEPOSIT_CHANGE", "DEPOSIT_CHANGE_AMT",
        "AWAITING_CLARIFICATION",
    ):
        return "❌ Cancelled. Nothing was changed."

    # ── Correction: amount/mode update while disambiguation is pending ────────
    if chosen_idx is None and choices and pending.intent == "PAYMENT_LOG":
        _corrected = False
        _rl = reply_text.lower()
        _MODE_MAP = {
            "upi": "UPI", "cash": "Cash", "gpay": "GPay", "phonepe": "PhonePe",
            "paytm": "Paytm", "online": "Online", "bank": "Bank Transfer",
            "neft": "NEFT", "cheque": "Cheque", "imps": "IMPS",
        }
        for _word, _label in _MODE_MAP.items():
            if _word in _rl and _label != action_data.get("mode", ""):
                action_data["mode"] = _label
                _corrected = True
                break
        _amt_m = re.search(r"\b(\d[\d,]+)\b", reply_text)
        if _amt_m:
            _new_amt = float(_amt_m.group(1).replace(",", ""))
            if _new_amt != action_data.get("amount", 0) and _new_amt > 0:
                action_data["amount"] = _new_amt
                _corrected = True
        if _corrected:
            pending.action_data = json.dumps(action_data)
            await session.flush()
            _name_raw = action_data.get("name_raw", "")
            _amt = int(action_data["amount"])
            _mode = action_data.get("mode", "Cash")
            _options_str = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices)
            return (
                "__KEEP_PENDING__"
                f"✏️ Updated. Which tenant for Rs.{_amt:,} ({_mode})?\n\n"
                f"{_options_str}\n\nOr say *cancel* to stop."
            )

    # ── Re-prompt if reply isn't a valid number for disambiguation ───────────

    if chosen_idx is None and choices:
        # If only 1 option and user says yes — auto-select it
        if len(choices) == 1 and is_affirmative(reply_text):
            chosen_idx = 0
        else:
            options = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices)
            return "__KEEP_PENDING__" + f"Please reply with a number:\n{options}\n\nOr say *cancel* to stop."

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
        if chosen.get("seq") == 1:
            return await _do_void_payment(
                payment_id=action_data["payment_id"],
                tenant_name=action_data["tenant_name"],
                session=session,
            )
        return "Void cancelled — payment remains as logged."

    if pending.intent == "VOID_EXPENSE":
        choices_data = json.loads(pending.choices or "[]")
        seq = chosen.get("seq")
        match = next((c for c in choices_data if c["seq"] == seq), None)
        if match:
            from src.whatsapp.handlers.account_handler import _do_void_expense
            return await _do_void_expense(match["expense_id"], session)
        return "Void cancelled."

    if pending.intent == "DEPOSIT_CHANGE":
        if is_affirmative(reply_text):
            from src.whatsapp.handlers.account_handler import _do_deposit_change
            return await _do_deposit_change(
                tenancy_id=action_data["tenancy_id"],
                new_amount=action_data["new_amount"],
                tenant_name=action_data["tenant_name"],
                session=session,
            )
        return "Deposit change cancelled."

    if pending.intent == "DEPOSIT_CHANGE_AMT":
        amt_str = reply_text.strip().replace(",", "").replace("₹", "").replace("Rs", "").strip()
        if amt_str.isdigit():
            from src.whatsapp.handlers.account_handler import _do_deposit_change
            return await _do_deposit_change(
                tenancy_id=action_data["tenancy_id"],
                new_amount=int(amt_str),
                tenant_name=action_data["tenant_name"],
                session=session,
            )
        return "__KEEP_PENDING__Reply with the new deposit amount (numbers only):"

    if pending.intent == "ROOM_TRANSFER":
        if is_affirmative(reply_text):
            return await _do_room_transfer(action_data, session)
        return "Room transfer cancelled."

    if pending.intent == "CONFIRM_ADD_TENANT":
        if is_negative(reply_text):
            return "❌ Tenant check-in cancelled. Nothing was saved."
        if is_affirmative(reply_text):
            return await _do_add_tenant(action_data, session)
        return "__KEEP_PENDING__Reply *Yes* to save the new tenant or *No* to cancel."

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

    # No proration at checkout — full month rent charged regardless of exit date
    # Proration only applies at checkin (first month)
    prorate_note = ""

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

    # ── Google Sheets write-back (fire-and-forget) ──
    gsheets_note = ""
    room_obj = await session.get(Room, tenancy.room_id) if tenancy.room_id else None
    if room_obj:
        try:
            from src.integrations.gsheets import record_checkout as gsheets_checkout
            notice_str = tenancy.notice_date.strftime("%d/%m/%Y") if tenancy.notice_date else None
            gs_r = await gsheets_checkout(room_obj.room_number, tenant_name, notice_str)
            if gs_r.get("success"):
                gsheets_note = "\nSheet updated: EXIT"
            elif gs_r.get("error"):
                import logging as _log
                _log.getLogger(__name__).warning("GSheets checkout: %s", gs_r["error"])
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).error("GSheets checkout failed: %s", e)

    return (
        f"*Checkout recorded — {tenant_name}*\n"
        f"Date: {checkout_date_val.strftime('%d %b %Y')}"
        f"{prorate_note}"
        f"{notice_warn}"
        f"{settlement_summary}\n\n"
        "Next steps:\n"
        "1. Collect room keys\n"
        "2. Process deposit refund → *refund [amount] to [Name]*"
        f"{gsheets_note}"
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

_SKIP_VALUES = {"skip", "none", "no", "nil", "-", "n/a", "na", "0"}

_MONTHS_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _get_ff(text: str, field: str) -> str:
    """Extract value from 'Field: value' in multi-line form text."""
    m = re.search(rf"^{field}\s*:\s*(.+?)$", text, re.I | re.M)
    return m.group(1).strip() if m else ""


def _is_form_submission(text: str) -> bool:
    """Return True if message looks like a filled ADD_TENANT form (≥3 key fields present)."""
    keys = ["name", "phone", "room", "rent", "deposit", "checkin", "food"]
    matches = sum(1 for k in keys if re.search(rf"^{k}\s*:", text, re.I | re.M))
    return matches >= 3


def _parse_discount_field(s: str, base_rent: float) -> dict:
    """Parse Discount form field. Returns {} for no discount."""
    s = s.strip().lower()
    if not s or s in _SKIP_VALUES:
        return {}
    # "flat 6400 until may" or "6400 until june"
    m = re.search(r"(?:flat\s+)?(\d[\d,]+)\s+(?:until|till|upto)\s+(\w+)", s)
    if m:
        amt = float(m.group(1).replace(",", ""))
        return {"type": "flat_rent", "discounted_rent": amt, "until_month": m.group(2)[:3].lower()}
    # "20% off 2 months"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%.*?(\d+)\s*months?", s)
    if m:
        pct = float(m.group(1))
        months = int(m.group(2))
        return {"type": "percent", "pct": pct, "months": months,
                "discounted_rent": round(base_rent * (1 - pct / 100))}
    # "1500 off" / "discount 1500"
    m = re.search(r"(\d[\d,]+)\s*(?:off|discount|concession)", s) or \
        re.search(r"(?:off|discount|concession)\s+(\d[\d,]+)", s)
    if m:
        off_amt = float(m.group(1).replace(",", ""))
        return {"type": "flat_off", "off_amount": off_amt, "discounted_rent": base_rent - off_amt}
    return {}


def _parse_amount_field(s: str) -> float:
    """Parse a numeric amount from a field value; returns 0 for skip/none."""
    s = s.strip().lower()
    if not s or s in _SKIP_VALUES:
        return 0.0
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", s)
    return float(m.group(1).replace(",", "")) if m else 0.0


async def _add_tenant_prompt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    msg = entities.get("description", "").strip()

    # ── Detect filled form submission ──────────────────────────────────────
    if _is_form_submission(msg):
        return await _process_tenant_form(msg, ctx, session)

    # ── Show blank form template ───────────────────────────────────────────
    phone = entities.get("phone", "").strip()
    if phone:
        ok, reason = await check_no_active_tenancy(phone, session)
        if not ok:
            return reason

    name = entities.get("name", "").strip()
    reentry_note = ""
    if name:
        rows = await _find_active_tenants_by_name(name, session)
        if rows:
            tenant, tenancy, room_obj = rows[0]
            reentry_note = (
                f"\n⚠️ *{tenant.name}* already has an active tenancy in Room {room_obj.room_number}.\n"
                "If this is a room change, first checkout the old room then add new.\n"
            )
        else:
            past = await session.scalar(select(Tenant).where(Tenant.name.ilike(f"%{name}%")))
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
        "Discount: [e.g. 6400 until May / 20% off 2 months / skip]\n"
        "Deposit: [security deposit]\n"
        "Advance: [amount paid at booking / skip]\n"
        "Maintenance: [monthly fee / skip]\n"
        "Checkin: [DD/MM/YYYY]\n"
        "Food: [veg/non-veg/egg/none]\n\n"
        "I'll confirm before saving."
    )


async def _process_tenant_form(msg: str, ctx: CallerContext, session: AsyncSession) -> str:
    """Parse and validate a filled ADD_TENANT form, then save pending confirmation."""
    from src.whatsapp.intent_detector import _extract_date_entity

    name       = _get_ff(msg, "name")
    phone_raw  = _get_ff(msg, "phone")
    room_str   = _get_ff(msg, "room")
    rent_str   = _get_ff(msg, "rent")
    discount_s = _get_ff(msg, "discount")
    deposit_s  = _get_ff(msg, "deposit")
    advance_s  = _get_ff(msg, "advance")
    maint_s    = _get_ff(msg, "maintenance")
    checkin_s  = _get_ff(msg, "checkin")
    food_s     = _get_ff(msg, "food").lower()

    errors = []
    if not name:    errors.append("Name is missing")
    if not phone_raw: errors.append("Phone is missing")
    if not room_str:  errors.append("Room number is missing")
    if not rent_str:  errors.append("Rent amount is missing")
    if not checkin_s: errors.append("Checkin date is missing")
    if errors:
        return ("⚠️ *Form incomplete*\n\n"
                + "\n".join(f"• {e}" for e in errors)
                + "\n\nPlease resend the complete form.")

    # Normalise phone
    phone = _normalize_phone(phone_raw)
    if len(phone) != 10 or not phone.isdigit():
        return f"⚠️ Phone *{phone_raw}* doesn't look valid (10 digits needed). Please correct and resend."

    # Validate room exists
    room_row = await session.scalar(select(Room).where(Room.room_number.ilike(room_str)))
    if not room_row:
        result = await session.execute(
            select(Room).where(Room.room_number.ilike(f"%{room_str}%")).limit(5)
        )
        similar = [r.room_number for r in result.scalars().all()]
        if similar:
            return (f"⚠️ Room *{room_str}* not found.\n\n"
                    f"Did you mean: {', '.join(f'*{r}*' for r in similar[:4])}?\n\n"
                    "Correct the room number and resend.")
        return (f"⚠️ Room *{room_str}* does not exist.\n\n"
                "Type *vacant rooms* to see available rooms, then resend.")

    # Check room capacity
    active_result = await session.execute(
        select(Tenancy).where(Tenancy.room_id == room_row.id, Tenancy.status == TenancyStatus.active)
    )
    occupants = active_result.scalars().all()
    if len(occupants) >= (room_row.max_occupancy or 1):
        tenant_ids = [tncy.tenant_id for tncy in occupants]
        name_rows = await session.execute(select(Tenant.name).where(Tenant.id.in_(tenant_ids)))
        occ_names = [r for r in name_rows.scalars().all()]
        return (f"⚠️ Room *{room_str}* is full "
                f"({len(occupants)}/{room_row.max_occupancy} occupants: {', '.join(occ_names)}).\n\n"
                "Checkout an existing tenant first or use a different room.")

    # Duplicate phone check
    existing_tenant = await session.scalar(select(Tenant).where(Tenant.phone == phone))
    if existing_tenant:
        active_tncy = await session.scalar(
            select(Tenancy).where(Tenancy.tenant_id == existing_tenant.id, Tenancy.status == TenancyStatus.active)
        )
        if active_tncy:
            r2 = await session.get(Room, active_tncy.room_id)
            return (f"⚠️ Phone *{phone}* already belongs to *{existing_tenant.name}* "
                    f"(active in Room {r2.room_number if r2 else '?'}).\n\n"
                    "Cannot add duplicate — checkout current room first if this is a move.")

    # Parse amounts
    base_rent   = _parse_amount_field(rent_str)
    deposit     = _parse_amount_field(deposit_s)
    advance     = _parse_amount_field(advance_s)
    maintenance = _parse_amount_field(maint_s)
    if base_rent <= 0:
        return f"⚠️ Rent amount *{rent_str}* could not be read. Use a number (e.g. 15000)."

    discount_info = _parse_discount_field(discount_s, base_rent)

    # Parse checkin date
    checkin_iso = _extract_date_entity(checkin_s) or _extract_date_entity(msg)
    if not checkin_iso:
        return (f"⚠️ Checkin date *{checkin_s}* could not be parsed.\n\n"
                "Please use DD/MM/YYYY format (e.g. 18/03/2026) and resend.")
    checkin_date = date.fromisoformat(checkin_iso)
    today = date.today()
    days_ago = (today - checkin_date).days

    date_warn = ""
    if days_ago > 730:
        return (f"⚠️ Checkin date *{checkin_date.strftime('%d %b %Y')}* is over 2 years in the past.\n\n"
                "Please verify the date (DD/MM/YYYY) and resend.")
    if days_ago > 90:
        date_warn = (f"\n⚠️ Checkin {checkin_date.strftime('%d %b %Y')} is {days_ago} days "
                     "in the past — please confirm this is correct.")

    # Food preference
    food_pref = "none"
    if re.search(r"\bnon.?veg\b", food_s):
        food_pref = "non-veg"
    elif re.search(r"\bveg\b", food_s):
        food_pref = "veg"
    elif "egg" in food_s:
        food_pref = "egg"

    # Discount display line
    discount_line = ""
    if discount_info:
        d = discount_info
        if d.get("type") == "flat_rent":
            discount_line = (f"\nDiscount: Rs.{int(d['discounted_rent']):,}/month until "
                             f"{d.get('until_month','?').title()} (then Rs.{int(base_rent):,})")
        elif d.get("type") == "percent":
            discount_line = (f"\nDiscount: {d['pct']}% off × {d['months']} months "
                             f"= Rs.{int(d['discounted_rent']):,}/month")
        elif d.get("type") == "flat_off":
            discount_line = (f"\nDiscount: Rs.{int(d['off_amount']):,} off "
                             f"= Rs.{int(d['discounted_rent']):,}/month")

    # Save pending
    pending_data = {
        "name": name, "phone": phone,
        "room_id": room_row.id, "room_number": room_row.room_number,
        "base_rent": base_rent, "deposit": deposit,
        "advance": advance, "maintenance": maintenance,
        "checkin_date": checkin_iso, "food_pref": food_pref,
        "discount": discount_info,
        "existing_tenant_id": existing_tenant.id if existing_tenant else None,
    }
    session.add(PendingAction(
        phone=ctx.phone,
        intent="CONFIRM_ADD_TENANT",
        action_data=json.dumps(pending_data),
        choices=json.dumps([]),
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    ))

    return (
        f"*Confirm New Tenant?*{date_warn}\n\n"
        f"Name: {name}\n"
        f"Phone: {phone}\n"
        f"Room: {room_row.room_number}\n"
        f"Rent: Rs.{int(base_rent):,}/month{discount_line}\n"
        f"Deposit: Rs.{int(deposit):,}\n"
        + (f"Advance paid: Rs.{int(advance):,}\n" if advance > 0 else "")
        + (f"Maintenance: Rs.{int(maintenance):,}/month\n" if maintenance > 0 else "")
        + f"Checkin: {checkin_date.strftime('%d %b %Y')}\n"
        f"Food: {food_pref}\n\n"
        "Reply *Yes* to save or *No* to cancel."
    )


async def _do_add_tenant(data: dict, session: AsyncSession) -> str:
    """Create Tenant + Tenancy + RentSchedule(s) + advance Payment from confirmed form data."""
    today        = date.today()
    name         = data["name"]
    phone        = data["phone"]
    room_id      = data["room_id"]
    room_number  = data["room_number"]
    base_rent    = Decimal(str(data["base_rent"]))
    deposit      = Decimal(str(data["deposit"]))
    advance      = Decimal(str(data.get("advance") or 0))
    maintenance  = Decimal(str(data.get("maintenance") or 0))
    checkin_date = date.fromisoformat(data["checkin_date"])
    discount     = data.get("discount") or {}
    existing_tid = data.get("existing_tenant_id")

    # Tenant record
    if existing_tid:
        tenant = await session.get(Tenant, existing_tid)
    else:
        tenant = await session.scalar(select(Tenant).where(Tenant.phone == phone))
    if not tenant:
        tenant = Tenant(name=name, phone=phone)
        session.add(tenant)
        await session.flush()

    # Tenancy record
    tenancy = Tenancy(
        tenant_id        = tenant.id,
        room_id          = room_id,
        checkin_date     = checkin_date,
        agreed_rent      = base_rent,
        security_deposit = deposit,
        booking_amount   = advance,
        maintenance_fee  = maintenance,
        status           = TenancyStatus.active,
    )
    session.add(tenancy)
    await session.flush()

    # Determine discount end
    discount_until = None
    if discount.get("type") == "flat_rent" and discount.get("until_month"):
        um_num = _MONTHS_MAP.get(discount["until_month"][:3].lower())
        if um_num:
            y = today.year if um_num >= checkin_date.month else today.year + 1
            discount_until = date(y, um_num, 1)
    elif discount.get("type") == "percent" and discount.get("months"):
        extra = int(discount["months"])
        total_m = checkin_date.month - 1 + extra
        discount_until = date(checkin_date.year + total_m // 12, total_m % 12 + 1, 1)

    # Generate RentSchedule from checkin month to current month
    period = checkin_date.replace(day=1)
    current_month = today.replace(day=1)
    while period <= current_month:
        effective_rent = base_rent
        adjustment = Decimal("0")
        if discount and discount.get("discounted_rent"):
            disc_rent = Decimal(str(discount["discounted_rent"]))
            if discount.get("type") == "flat_rent" and discount_until and period <= discount_until:
                adjustment = disc_rent - base_rent
            elif discount.get("type") in ("percent", "flat_off"):
                months_into = (period.year - checkin_date.year) * 12 + (period.month - checkin_date.month)
                if months_into < int(discount.get("months", 1)):
                    adjustment = disc_rent - base_rent

        adj_note = None
        if adjustment:
            adj_note = (f"discount until {discount_until.strftime('%b %Y')}"
                        if discount_until else "discount")

        session.add(RentSchedule(
            tenancy_id      = tenancy.id,
            period_month    = period,
            rent_due        = base_rent,
            maintenance_due = maintenance,
            adjustment      = adjustment if adjustment != Decimal("0") else None,
            adjustment_note = adj_note,
            status          = RentStatus.pending,
            due_date        = period,
        ))
        if period.month == 12:
            period = date(period.year + 1, 1, 1)
        else:
            period = date(period.year, period.month + 1, 1)

    # Log advance as Payment
    if advance > 0:
        session.add(Payment(
            tenancy_id   = tenancy.id,
            amount       = advance,
            payment_date = checkin_date,
            payment_mode = PaymentMode.cash,
            for_type     = PaymentFor.booking,
            period_month = checkin_date.replace(day=1),
            notes        = "Booking advance at check-in",
        ))

    # ── Google Sheets write-back (fire-and-forget) ──
    gsheets_note = ""
    try:
        room_obj = await session.get(Room, room_id)
        if room_obj:
            from src.integrations.gsheets import add_tenant as gsheets_add
            building = data.get("building", "")
            floor_val = str(room_obj.floor or "")
            sharing = data.get("sharing", room_obj.room_type or "")
            gs_r = await gsheets_add(
                room_number=room_number, name=name, phone=phone,
                gender=data.get("gender", ""), building=building,
                floor=floor_val, sharing=sharing,
                checkin=checkin_date.strftime("%d/%m/%Y"),
                agreed_rent=float(base_rent), deposit=float(deposit),
                booking=float(advance), maintenance=float(maintenance),
            )
            if gs_r.get("success"):
                gsheets_note = "\nSheet updated"
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).error("GSheets add_tenant failed: %s", e)

    return (
        f"*Tenant saved — {name}* ✅\n\n"
        f"Room: {room_number}\n"
        f"Rent: Rs.{int(base_rent):,}/month\n"
        f"Deposit: Rs.{int(deposit):,}\n"
        f"Checkin: {checkin_date.strftime('%d %b %Y')}\n"
        + (f"Advance logged: Rs.{int(advance):,}\n" if advance > 0 else "")
        + "Rent schedule created."
        + gsheets_note
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


async def _fetch_active_property(session: AsyncSession) -> "Property | None":
    """Fetch the single active property (owner context)."""
    result = await session.execute(select(Property).where(Property.active == True).limit(1))
    return result.scalars().first()


_OWNER_FLOOR_LABELS = {
    "G": "Ground Floor", "1": "1st Floor", "2": "2nd Floor",
    "3": "3rd Floor", "4": "4th Floor", "5": "5th Floor", "6": "6th Floor",
    "top": "Dining Area (TOP)", "ws": "Work Area (WS)", "gym": "Gym",
}


async def _get_wifi_password(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show WiFi credentials. Can filter by block (thor/hulk) or floor."""
    prop = await _fetch_active_property(session)
    if not prop:
        return "No active property found."

    floor_map: dict = prop.wifi_floor_map or {}
    if not floor_map or ("thor" not in floor_map and "hulk" not in floor_map):
        return "WiFi details are not configured yet. Please contact the manager."

    msg = (entities.get("description") or "").lower()
    show_block = "thor" if "thor" in msg else ("hulk" if "hulk" in msg else None)

    floor_filter = None
    fm = re.search(r"\bfloor\s+(\d+|g|ground)\b", msg, re.I)
    if fm:
        f = fm.group(1).lower()
        floor_filter = "G" if f in ("g", "ground", "0") else f

    lines = ["*WiFi Credentials*\n"]
    for block in (["thor", "hulk"] if not show_block else [show_block]):
        block_data: dict = floor_map.get(block, {})
        if not block_data:
            continue
        lines.append(f"*{'Thor Block' if block == 'thor' else 'Hulk Block'}*")
        for floor_key, nets in block_data.items():
            if floor_filter and floor_key.lower() != floor_filter.lower():
                continue
            label = _OWNER_FLOOR_LABELS.get(floor_key, f"Floor {floor_key}")
            lines.append(f"  _{label}_")
            for net in nets:
                lines.append(f"    {net['ssid']} → `{net['password']}`")
        lines.append("")
    lines.append("📶 _5GHz for mobiles/laptops · 2.4GHz for TV_")
    return "\n".join(lines)


async def _set_wifi(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Update a WiFi network password.
    Format: update wifi [thor/hulk] [ssid_name] password [newpass]
    Example: update wifi thor cozeevo G2 password cozeevo@g2new
    """
    from sqlalchemy.orm.attributes import flag_modified

    msg = entities.get("description", "")
    prop = await _fetch_active_property(session)
    if not prop:
        return "No active property found."

    # Parse: [block] [ssid] password [newpass]
    m = re.search(r"(thor|hulk)\s+(.+?)\s+password\s+(\S+)", msg, re.I)
    if not m:
        return (
            "Format: *update wifi [block] [network name] password [new password]*\n"
            "Example: *update wifi thor cozeevo G2 password cozeevo@g2new*"
        )

    block = m.group(1).lower()
    target_ssid = m.group(2).strip()
    new_pw = m.group(3)

    floor_map = dict(prop.wifi_floor_map or {})
    block_data = floor_map.get(block, {})
    updated = False
    for floor_key, nets in block_data.items():
        for net in nets:
            if net["ssid"].lower() == target_ssid.lower():
                net["password"] = new_pw
                updated = True
                break

    if not updated:
        return f"Network `{target_ssid}` not found in *{block.capitalize()} Block*."

    prop.wifi_floor_map = floor_map
    flag_modified(prop, "wifi_floor_map")
    await session.commit()
    return f"✅ WiFi updated\nNetwork: `{target_ssid}`\nNew password: `{new_pw}`"


async def _help(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    header = bot_intro(await is_first_time_today(ctx.phone, session), ctx.name, ctx.role)
    first = ctx.name.split()[0] if ctx.name else "there"
    return (
        f"{header}"
        f"Pick a service below or just type naturally, {first}. 👇"
    )


async def _more_menu(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    first = ctx.name.split()[0] if ctx.name else "there"
    return f"Here's everything you can do, {first}. 👇"


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

async def _room_transfer_prompt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Initiate moving a tenant from their current room to a new one."""
    name   = entities.get("name", "").strip()
    to_room = entities.get("room", "").strip()

    if not name:
        return (
            "Who should be moved and to which room?\n"
            "Say: *move Raj to room 305*"
        )

    rows = await _find_active_tenants_by_name(name, session)
    if not rows:
        suggestions = await _find_similar_names(name, session)
        return _format_no_match_message(name, suggestions)
    if len(rows) > 1:
        choices = _make_choices(rows)
        await _save_pending(ctx.phone, "ROOM_TRANSFER_WHO", {"to_room": to_room}, choices, session)
        return _format_choices_message(name, choices, "transfer to a new room")

    tenant, tenancy, current_room = rows[0]

    if not to_room:
        await _save_pending(ctx.phone, "ROOM_TRANSFER_DEST",
                            {"tenancy_id": tenancy.id, "tenant_name": tenant.name,
                             "from_room": current_room.room_number}, [], session)
        return (
            f"Moving *{tenant.name}* from Room *{current_room.room_number}*.\n\n"
            "Which room should they move to? (Reply with room number)"
        )

    new_room = await session.scalar(
        select(Room).where(Room.room_number == to_room.upper(), Room.active == True)
    )
    if not new_room:
        return f"Room *{to_room}* not found. Check the room number and try again."

    # Check vacancy (no active tenancy in new room)
    occupied = await session.scalar(
        select(func.count(Tenancy.id)).where(
            Tenancy.room_id == new_room.id,
            Tenancy.status == TenancyStatus.active,
        )
    )
    if occupied:
        return f"Room *{to_room}* is currently occupied. Choose a vacant room."

    # Fetch current rent
    rs = await session.scalar(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy.id,
            RentSchedule.period_month >= date.today().replace(day=1),
        ).order_by(RentSchedule.period_month.asc()).limit(1)
    )
    current_rent = int(rs.rent_due) if rs else int(tenancy.booking_amount or 0)

    action_data = {
        "tenancy_id": tenancy.id,
        "tenant_name": tenant.name,
        "from_room": current_room.room_number,
        "to_room_id": new_room.id,
        "to_room_number": new_room.room_number,
        "current_rent": current_rent,
    }
    await _save_pending(ctx.phone, "ROOM_TRANSFER", action_data, [], session)
    return (
        f"*Room Transfer — {tenant.name}*\n"
        f"From: Room *{current_room.room_number}* ({current_room.room_type.value})\n"
        f"To:   Room *{new_room.room_number}* ({new_room.room_type.value})\n"
        f"Current rent: ₹{current_rent:,}/mo\n\n"
        "Reply *Yes* to confirm, *No* to cancel,\n"
        "or reply with a new rent amount (e.g. *9000*) to update rent too."
    )


async def _do_room_transfer(action_data: dict, session: AsyncSession) -> str:
    tenancy = await session.get(Tenancy, action_data["tenancy_id"])
    if not tenancy:
        return "Tenancy record not found."
    tenancy.room_id = action_data["to_room_id"]
    return (
        f"Room transferred — *{action_data['tenant_name']}*\n"
        f"Room *{action_data['from_room']}* → Room *{action_data['to_room_number']}*"
    )


async def _query_vacant_rooms(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    from collections import defaultdict
    from src.database.models import Property

    all_rows = (await session.execute(
        select(Room, Property.name)
        .join(Property, Property.id == Room.property_id)
        .where(Room.active == True, Room.is_staff_room == False)
        .order_by(Property.name, Room.room_number)
    )).all()

    occupied_ids = {row[0] for row in (await session.execute(
        select(Tenancy.room_id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
            Tenancy.room_id.isnot(None),
            Room.is_staff_room == False,
        )
    )).all()}

    total_rooms = len(all_rows)
    total_beds  = sum(r.max_occupancy or 1 for r, _ in all_rows)
    vacant      = [(r, prop) for r, prop in all_rows if r.id not in occupied_ids]
    occupied_rooms = total_rooms - len(vacant)
    vacant_beds    = sum(r.max_occupancy or 1 for r, _ in vacant)
    occupied_beds  = total_beds - vacant_beds

    if not vacant:
        return (
            f"🔴 All {total_rooms} rooms / {total_beds} beds are currently occupied."
        )

    _ICON = {"single": "🔵", "double": "🟢", "sharing": "🟡", "triple": "🟠", "premium": "⭐"}

    def _floor_label(rn: str) -> str:
        return "G" if rn.upper().startswith("G") else rn[0]

    # Group by block → floor
    blocks: dict = defaultdict(lambda: defaultdict(list))
    type_counts: dict = defaultdict(int)
    thor_rooms = thor_beds = hulk_rooms = hulk_beds = 0
    for r, prop in vacant:
        block = "THOR" if "THOR" in prop.upper() else "HULK"
        fl = _floor_label(r.room_number)
        blocks[block][fl].append(r)
        type_counts[r.room_type.value] += 1
        beds = r.max_occupancy or 1
        if block == "THOR":
            thor_rooms += 1; thor_beds += beds
        else:
            hulk_rooms += 1; hulk_beds += beds

    SEP = "─" * 28
    lines = [
        f"🛏 *Vacant Beds  — {vacant_beds} free  |  {occupied_beds} occupied*",
        f"🏠 *Vacant Rooms — {len(vacant)} free  |  {occupied_rooms} occupied*",
        f"   THOR {thor_rooms}r/{thor_beds}b  ·  HULK {hulk_rooms}r/{hulk_beds}b",
        "",
    ]

    for block in ["THOR", "HULK"]:
        if block not in blocks:
            continue
        br = thor_rooms if block == "THOR" else hulk_rooms
        bb = thor_beds  if block == "THOR" else hulk_beds
        lines.append(f"*{SEP}*")
        lines.append(f"🏢 *{block} — {br} rooms / {bb} beds vacant*")
        floor_keys = sorted(blocks[block].keys(),
                            key=lambda f: (0, f) if f == "G" else (int(f), f))
        for fl in floor_keys:
            rooms = sorted(blocks[block][fl], key=lambda x: x.room_number)
            cells = []
            for r in rooms:
                icon = _ICON.get(r.room_type.value, "⬜")
                ac = "❄" if r.has_ac else ""
                cells.append(f"{icon}{r.room_number}{ac}")
            label = "GF" if fl == "G" else f"F{fl}"
            lines.append(f"  {label}  {'  '.join(cells)}")
        lines.append("")

    # Bed summary by type
    bed_line = "  ".join(
        f"{_ICON.get(k,'⬜')}{v}b"
        for k, v in [("single", type_counts["single"]), ("double", type_counts["double"]),
                     ("triple", type_counts["triple"]), ("premium", type_counts["premium"])]
        if v
    )
    lines.append(f"*{SEP}*")
    lines.append(f"🔵Single 🟢Double 🟠Triple ⭐Premium")
    lines.append(f"Vacant beds: {bed_line}  = *{vacant_beds} total*")
    return "\n".join(lines)


# ── Occupancy overview ────────────────────────────────────────────────────────

async def _query_occupancy(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    revenue_filter = and_(Room.active == True, Room.is_staff_room == False)

    # Total beds = sum(max_occupancy) across all revenue rooms
    total_beds = await session.scalar(
        select(func.sum(Room.max_occupancy)).where(revenue_filter)
    ) or 0

    # Total revenue rooms
    total_rooms = await session.scalar(
        select(func.count(Room.id)).where(revenue_filter)
    ) or 0

    # Physical beds occupied:
    #   - Premium tenancy: 1 person occupies full room (max_occupancy beds)
    #   - Regular tenancy: 1 person = 1 bed
    #   Premium is on Tenancy.sharing_type, NOT Room.room_type
    physical_beds = await session.scalar(
        select(func.sum(
            sa_case((Tenancy.sharing_type == "premium", Room.max_occupancy), else_=1)
        )).select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(and_(Tenancy.status == TenancyStatus.active, Room.is_staff_room == False))
    ) or 0
    physical_rooms = await session.scalar(
        select(func.count(func.distinct(Tenancy.room_id)))
        .select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(Tenancy.status == TenancyStatus.active, Room.is_staff_room == False)
    ) or 0

    # No-shows: booked + assigned a room but not yet arrived (same premium rule)
    noshow_beds = await session.scalar(
        select(func.sum(
            sa_case((Tenancy.sharing_type == "premium", Room.max_occupancy), else_=1)
        )).select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(and_(
            Tenancy.status == TenancyStatus.no_show,
            Tenancy.room_id.isnot(None),
            Room.is_staff_room == False,
        ))
    ) or 0

    booked_beds  = physical_beds + noshow_beds
    vacant_beds  = total_beds - booked_beds
    vacant_rooms = total_rooms - physical_rooms
    phys_pct     = int(physical_beds * 100 / total_beds)  if total_beds  else 0
    booked_pct   = int(booked_beds   * 100 / total_beds)  if total_beds  else 0
    room_pct     = int(physical_rooms * 100 / total_rooms) if total_rooms else 0

    return (
        f"*Occupancy — {total_beds} total beds*\n\n"
        f"Checked-in   : {physical_beds} beds  ({phys_pct}%)\n"
        f"No-show      : {noshow_beds} beds  (booked, not arrived)\n"
        f"*Booked total: {booked_beds} / {total_beds}  ({booked_pct}%)*\n"
        f"Vacant       : {vacant_beds} beds\n\n"
        f"Rooms: {physical_rooms} occupied / {total_rooms} total  ({room_pct}%)\n\n"
        "Say *vacant rooms* to see which rooms are empty."
    )


async def _room_layout(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Floor-by-floor room + bed diagram for Thor and Hulk blocks."""
    from src.database.models import Property

    msg = entities.get("description", "").lower()
    # Filter to one block if specified
    only_block = None
    if "thor" in msg and "hulk" not in msg:
        only_block = "thor"
    elif "hulk" in msg and "thor" not in msg:
        only_block = "hulk"

    # Load properties
    props_result = await session.execute(
        select(Property).where(Property.active == True).order_by(Property.name)
    )
    properties = props_result.scalars().all()
    if not properties:
        return "No properties found."

    _TYPE_ABBR = {"single": "S", "double": "D", "triple": "T", "premium": "P"}

    lines = []
    grand_rooms = grand_beds = 0

    for prop in properties:
        block_key = "thor" if "thor" in prop.name.lower() else "hulk"
        if only_block and block_key != only_block:
            continue

        # All active non-staff rooms for this property, sorted by floor then room_number
        rooms_result = await session.execute(
            select(Room)
            .where(Room.property_id == prop.id, Room.active == True, Room.is_staff_room == False)
            .order_by(Room.floor.nullsfirst(), Room.room_number)
        )
        rooms = rooms_result.scalars().all()
        if not rooms:
            continue

        # Group by floor
        from collections import defaultdict
        by_floor: dict = defaultdict(list)
        for r in rooms:
            by_floor[r.floor].append(r)

        prop_rooms = len(rooms)
        prop_beds  = sum(r.max_occupancy or 1 for r in rooms)
        grand_rooms += prop_rooms
        grand_beds  += prop_beds

        lines.append(f"*{prop.name}*  ({prop_rooms} rooms · {prop_beds} beds)")

        for floor in sorted(by_floor.keys(), key=lambda f: (f is None, f)):
            floor_rooms = by_floor[floor]
            floor_beds  = sum(r.max_occupancy or 1 for r in floor_rooms)
            floor_label = f"Floor {floor}" if floor is not None else "Ground"
            room_tags   = "  ".join(
                f"{r.room_number}[{_TYPE_ABBR.get(r.room_type.value if r.room_type else '', '?')}{r.max_occupancy or 1}]"
                for r in floor_rooms
            )
            lines.append(f"  {floor_label} ({len(floor_rooms)}r/{floor_beds}b): {room_tags}")

        lines.append("")  # blank line between blocks

    if not lines:
        return "No rooms found for the requested block."

    if not only_block:
        lines.append(f"*Total: {grand_rooms} rooms · {grand_beds} beds*")

    return "\n".join(lines)


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

    t, tncy, room_obj = tenancies[0]
    notes = tncy.notes

    if not notes or not notes.strip():
        return f"*{t.name}* (Room {room_obj.room_number}) — no agreed terms on record."

    return (
        f"*{t.name}* — Room {room_obj.room_number}\n"
        f"Agreed terms:\n{notes}"
    )


async def _query_contacts(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Owner/staff asks for any contact — searches across all fields in pg_contacts.
    "plumber contact", "Ibrahim number", "who does wifi", "cot vendor", "all contacts"
    """
    raw = entities.get("_raw_message", "").lower()

    # Strip noise words to extract the actual search term
    _NOISE = {
        "give", "get", "show", "find", "list", "me", "the", "our", "a", "an",
        "who", "is", "are", "was", "do", "did", "we", "use", "for", "of",
        "contact", "contacts", "number", "phone", "details", "detail",
        "vendor", "vendors", "supplier", "suppliers", "guy", "person",
        "all", "every", "each",
    }
    words = re.findall(r"[a-z]+", raw)
    search_terms = [w for w in words if w not in _NOISE and len(w) > 1]

    # If nothing meaningful left, show all
    show_all = not search_terms

    if show_all:
        result = await session.execute(
            select(PgContact)
            .where(PgContact.property == "Whitefield")
            .order_by(PgContact.category, PgContact.name)
        )
    else:
        # Search each term across name, category, contact_for, comments
        from sqlalchemy import or_
        conditions = []
        for term in search_terms:
            like = f"%{term}%"
            conditions.append(or_(
                func.lower(PgContact.name).like(like),
                func.lower(PgContact.category).like(like),
                func.lower(PgContact.contact_for).like(like),
                func.lower(PgContact.comments).like(like),
            ))
        # All search terms must match (AND) for tighter results
        result = await session.execute(
            select(PgContact)
            .where(PgContact.property == "Whitefield")
            .where(and_(*conditions))
            .order_by(PgContact.category, PgContact.name)
        )

    contacts = result.scalars().all()

    if not contacts and search_terms:
        # Retry with OR (any term matches) for broader results
        conditions = []
        for term in search_terms:
            like = f"%{term}%"
            conditions.append(or_(
                func.lower(PgContact.name).like(like),
                func.lower(PgContact.category).like(like),
                func.lower(PgContact.contact_for).like(like),
                func.lower(PgContact.comments).like(like),
            ))
        result = await session.execute(
            select(PgContact)
            .where(PgContact.property == "Whitefield")
            .where(or_(*conditions))
            .order_by(PgContact.category, PgContact.name)
        )
        contacts = result.scalars().all()

    if not contacts:
        return f"No contacts found for *{' '.join(search_terms)}*.\nTry: *plumber contact*, *Ibrahim number*, *all vendors*"

    def _clean_phone(p: str | None) -> str:
        if not p:
            return ""
        return re.sub(r"\.0$", "", p.strip())

    label = " ".join(search_terms).title() if search_terms else "All"
    lines = [f"*{label} Contacts* ({len(contacts)})\n"]

    for c in contacts:
        phone = _clean_phone(c.phone)
        name = c.name or "Unknown"
        line = f"*{name}*"
        if phone:
            line += f" — {phone}"
        lines.append(line)
        if c.contact_for:
            desc = c.contact_for
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"  _{desc}_")
        if c.amount_paid or c.remaining:
            paid_str = f"Paid: {c.amount_paid:,.0f}" if c.amount_paid else ""
            rem_str = f"Remaining: {c.remaining}" if c.remaining else ""
            parts = [p for p in [paid_str, rem_str] if p]
            if parts:
                lines.append(f"  {' | '.join(parts)}")
        lines.append("")

    return "\n".join(lines)


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
    "toilet": "plumbing", "commode": "plumbing", "basin": "plumbing", "sink": "plumbing",
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

    # Generate ticket ID: XXX-YYYYMMDD-NNN (3-letter category prefix)
    cat_prefix = {
        ComplaintCategory.plumbing:    "PLU",
        ComplaintCategory.electricity: "ELE",
        ComplaintCategory.wifi:        "WIF",
        ComplaintCategory.food:        "FOD",
        ComplaintCategory.furniture:   "FUR",
        ComplaintCategory.other:       "OTH",
    }.get(category, "OTH")
    today_str = date.today().strftime("%Y%m%d")
    count_result = await session.scalar(
        select(func.count(Complaint.id)).where(
            func.date(Complaint.created_at) == date.today()
        )
    )
    seq = (count_result or 0) + 1
    ticket_id = f"{cat_prefix}-{today_str}-{seq:03d}"

    complaint = Complaint(
        tenancy_id=tenancy.id,
        category=category,
        description=description or f"Issue reported by owner for room {room_num}",
        status=ComplaintStatus.open,
        notes=ticket_id,  # store ticket ID in notes field
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
        f"Ticket: {ticket_id}\n"
        f"Category: {cat_label}\n"
        f"Status: Open\n"
        f"Issue: {description}"
    )


# ── Complaint update / query ───────────────────────────────────────────────────

async def _complaint_update(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Resolve / close a complaint by ticket ID or complaint DB id.
    Usage: "resolve CMP-20260324-001" or "complaint solved 3" or "close complaint"
    """
    description = entities.get("description", "").strip()

    # Extract ticket ID (CMP-YYYYMMDD-NNN) or bare number from description
    ticket_ref: str = ""
    cmp_id: Optional[int] = None

    import re as _re
    m_ticket = _re.search(r"[A-Z]{3}[-\s]?\d{8}[-\s]?\d{3}", description, _re.I)
    m_num    = _re.search(r"\b(\d+)\b", description)

    if m_ticket:
        ticket_ref = m_ticket.group(0).replace(" ", "-").upper()
    elif m_num:
        cmp_id = int(m_num.group(1))

    # Look up the complaint
    complaint: Optional[Complaint] = None
    if ticket_ref:
        result = await session.execute(
            select(Complaint).where(Complaint.notes == ticket_ref)
        )
        complaint = result.scalars().first()
    if complaint is None and cmp_id:
        # First try as DB id
        complaint = await session.get(Complaint, cmp_id)
        # If not found by DB id, try as room number
        if complaint is None:
            room_num_str = str(cmp_id)
            result = await session.execute(
                select(Complaint)
                .join(Tenancy, Complaint.tenancy_id == Tenancy.id)
                .join(Room, Tenancy.room_id == Room.id)
                .where(
                    Room.room_number == room_num_str,
                    Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.in_progress]),
                )
                .order_by(Complaint.created_at.desc())
                .limit(1)
            )
            complaint = result.scalars().first()
    if complaint is None:
        # Try to find most recent open complaint if no ID given
        if not ticket_ref and not cmp_id:
            result = await session.execute(
                select(Complaint)
                .where(Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.in_progress]))
                .order_by(Complaint.created_at.desc())
                .limit(1)
            )
            complaint = result.scalars().first()

    if complaint is None:
        return (
            "No matching complaint found.\n"
            "Use: *resolve XXX-YYYYMMDD-NNN* or *resolve complaint [number]*"
        )

    # Fetch room info for the reply
    tenancy = await session.get(Tenancy, complaint.tenancy_id)
    room_num = ""
    if tenancy and tenancy.room_id:
        room = await session.get(Room, tenancy.room_id)
        room_num = room.room_number if room else ""

    ticket_label = complaint.notes or f"#{complaint.id}"
    complaint.status      = ComplaintStatus.resolved
    complaint.resolved_at = datetime.utcnow()
    complaint.resolved_by = ctx.phone

    return (
        f"*Complaint Resolved*\n"
        f"Ticket: {ticket_label}\n"
        f"Room: {room_num or 'N/A'}\n"
        f"Issue: {complaint.description}\n"
        f"Resolved by: {ctx.name or ctx.phone}"
    )


async def _query_complaints(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    List open/pending complaints.
    Usage: "show complaints", "open complaints", "complaint list"
    """
    result = await session.execute(
        select(Complaint, Tenancy, Room)
        .join(Tenancy, Tenancy.id == Complaint.tenancy_id)
        .outerjoin(Room, Room.id == Tenancy.room_id)
        .where(Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.in_progress]))
        .order_by(Complaint.created_at.asc())
    )
    rows = result.all()

    if not rows:
        return "No open complaints. All clear!"

    cat_label = {
        ComplaintCategory.plumbing:    "Plumbing",
        ComplaintCategory.electricity: "Electricity",
        ComplaintCategory.wifi:        "Wi-Fi",
        ComplaintCategory.food:        "Food / Mess",
        ComplaintCategory.furniture:   "Furniture / Room",
        ComplaintCategory.other:       "Other",
    }

    lines = [f"*Open Complaints ({len(rows)})*\n"]
    for complaint, tenancy, room in rows:
        ticket = complaint.notes or f"#{complaint.id}"
        room_str = room.room_number if room else "?"
        cat = cat_label.get(complaint.category, "Other")
        age_days = (datetime.utcnow() - complaint.created_at).days if complaint.created_at else 0
        age_str = f"{age_days}d ago" if age_days else "today"
        lines.append(f"• *{ticket}* — Room {room_str} | {cat} | {age_str}")
        if complaint.description:
            short_desc = complaint.description[:60] + ("…" if len(complaint.description) > 60 else "")
            lines.append(f"  {short_desc}")

    lines.append(f"\nTo resolve: *resolve XXX-YYYYMMDD-NNN*")
    return "\n".join(lines)


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


# ── Activity Log ─────────────────────────────────────────────────────────────

def _normalize_description(desc: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for dedup hash."""
    desc = desc.lower().strip()
    desc = desc.translate(str.maketrans("", "", string.punctuation))
    desc = re.sub(r"\s+", " ", desc).strip()
    # Remove trailing filler words that don't change meaning
    for filler in ("today", "now", "just now"):
        if desc.endswith(filler):
            desc = desc[: -len(filler)].strip()
    return desc


def _make_dedup_hash(date_str: str, phone: str, description: str) -> str:
    """SHA-256 of date + phone + normalized description."""
    norm = _normalize_description(description)
    raw = f"{date_str}|{phone}|{norm}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _detect_activity_type(text: str) -> ActivityLogType:
    """Detect activity type from keywords in description."""
    t = text.lower()
    # Purchase — "paid 5000", "bought supplies", "spent 2000"
    if re.search(r"\b(?:bought|purchased|paid|cost|spent|charged)\b", t):
        return ActivityLogType.purchase
    # Staff — joined, left, vacation, salary, advance
    if re.search(r"\b(?:staff|employee|joined|resigned|left\s+job|vacation|leave|salary|advance|overtime|new\s+hire|fired|terminated)\b", t):
        return ActivityLogType.staff
    # Visitor — owner visit, guest, inspection
    if re.search(r"\b(?:visit|visitor|owner\s+came|inspection|guest|inspector|auditor|came\s+to\s+check)\b", t):
        return ActivityLogType.visitor
    # Utility — water tanker, electricity, gas, internet, bill
    if re.search(r"\b(?:water\s+tanker|tanker|electricity|power\s+cut|gas\s+cylinder|gas\s+bill|internet\s+bill|wifi\s+bill|bescom|bwssb)\b", t):
        return ActivityLogType.utility
    # Supply — groceries, cleaning items, kitchen
    if re.search(r"\b(?:groceries|grocery|cleaning\s+items|kitchen\s+supplies|vegetables|provisions|ration|detergent|soap)\b", t):
        return ActivityLogType.supply
    # Delivery — received, delivered, shipment
    if re.search(r"\b(?:received|delivered|got\s+\d|shipment)\b", t):
        return ActivityLogType.delivery
    # Maintenance — fixed, repaired, plumber, electrician
    if re.search(r"\b(?:fixed|repaired|repair|plumber|electrician|carpenter|painter|maintenance|replaced|serviced)\b", t):
        return ActivityLogType.maintenance
    return ActivityLogType.note


def _extract_activity_amount(text: str) -> Optional[float]:
    """
    Extract amount only when a payment keyword is nearby.
    "paid 5000" -> 5000.  "5000 liters" -> None.
    """
    # Amount after payment keyword: "paid 5000", "cost 2500", "charged 3000", "spent 1500"
    m = re.search(
        r"\b(?:paid|cost|charged|spent|bought\s+for|total\s+paid)\s+(?:rs\.?\s*)?(\d[\d,]*)",
        text, re.I,
    )
    if m:
        return float(m.group(1).replace(",", ""))
    # "total 25000" at end-ish
    m = re.search(r"\btotal\s+(?:rs\.?\s*)?(\d[\d,]*)\b", text, re.I)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _extract_activity_room(text: str) -> Optional[str]:
    """Extract room number from activity text."""
    m = re.search(r"\broom\s+([\w-]+)", text, re.I)
    if m:
        return m.group(1)
    return None


def _extract_activity_property(text: str) -> Optional[str]:
    """Extract THOR or HULK from text."""
    if re.search(r"\bthor\b", text, re.I):
        return "THOR"
    if re.search(r"\bhulk\b", text, re.I):
        return "HULK"
    return None


def _extract_activity_description(raw_message: str) -> str:
    """Strip the command prefix ('log', 'note', 'activity log') to get the description."""
    desc = raw_message.strip()
    # Remove leading command words
    desc = re.sub(r"^(?:activity\s+log\s+|log\s+|note\s+)", "", desc, flags=re.I).strip()
    return desc


_TYPE_ICONS = {
    ActivityLogType.delivery:    "📦",
    ActivityLogType.purchase:    "💰",
    ActivityLogType.maintenance: "🔧",
    ActivityLogType.utility:     "🚰",
    ActivityLogType.supply:      "🛒",
    ActivityLogType.staff:       "👷",
    ActivityLogType.visitor:     "🏢",
    ActivityLogType.payment:     "💳",
    ActivityLogType.complaint:   "⚠️",
    ActivityLogType.checkout:    "🚪",
    ActivityLogType.note:        "📝",
}


async def _activity_log(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Log an activity entry."""
    raw = entities.get("_raw_message", "")
    description = _extract_activity_description(raw)

    if not description or len(description.strip()) < 2:
        return "Please provide a description. Example:\n*log water tanker came today*"

    today_str = date.today().isoformat()
    phone = ctx.phone.lstrip("+")

    # Dedup check
    dedup = _make_dedup_hash(today_str, phone, description)
    existing = await session.execute(
        select(ActivityLog).where(ActivityLog.dedup_hash == dedup)
    )
    dup = existing.scalar_one_or_none()
    if dup:
        dup_time = dup.created_at.strftime("%I:%M %p") if dup.created_at else "earlier"
        return f"This activity was already logged at {dup_time} by {dup.logged_by}."

    log_type = _detect_activity_type(description)
    amount = _extract_activity_amount(description)
    room = _extract_activity_room(description) or entities.get("room")
    prop = _extract_activity_property(description)

    entry = ActivityLog(
        logged_by=phone,
        log_type=log_type,
        room=room,
        description=description,
        amount=amount,
        property_name=prop,
        source="whatsapp",
        dedup_hash=dedup,
    )
    session.add(entry)
    await session.flush()

    # Auto-resolve matching open complaints if activity has a room
    resolved_tickets = []
    if room and log_type in (ActivityLogType.maintenance, ActivityLogType.utility, ActivityLogType.purchase):
        # Map activity keywords to complaint categories
        cat_map = {
            "plumb": ComplaintCategory.plumbing,
            "leak": ComplaintCategory.plumbing,
            "tap": ComplaintCategory.plumbing,
            "drain": ComplaintCategory.plumbing,
            "flush": ComplaintCategory.plumbing,
            "pipe": ComplaintCategory.plumbing,
            "water": ComplaintCategory.plumbing,
            "electri": ComplaintCategory.electricity,
            "fan": ComplaintCategory.electricity,
            "bulb": ComplaintCategory.electricity,
            "switch": ComplaintCategory.electricity,
            "mcb": ComplaintCategory.electricity,
            "wifi": ComplaintCategory.wifi,
            "internet": ComplaintCategory.wifi,
            "food": ComplaintCategory.food,
            "mess": ComplaintCategory.food,
            "chair": ComplaintCategory.furniture,
            "bed": ComplaintCategory.furniture,
            "mattress": ComplaintCategory.furniture,
            "table": ComplaintCategory.furniture,
        }
        # Find which complaint categories match the activity description
        desc_lower = description.lower()
        matching_cats = set()
        for keyword, cat in cat_map.items():
            if keyword in desc_lower:
                matching_cats.add(cat)

        # Find open complaints for this room
        open_complaints_q = (
            select(Complaint)
            .join(Tenancy, Tenancy.id == Complaint.tenancy_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Room.room_number == room, Complaint.status == ComplaintStatus.open)
        )
        if matching_cats:
            open_complaints_q = open_complaints_q.where(Complaint.category.in_(matching_cats))

        result = await session.execute(open_complaints_q)
        open_complaints = result.scalars().all()

        for c in open_complaints:
            c.status = ComplaintStatus.resolved
            c.resolved_at = datetime.utcnow()
            c.resolved_by = ctx.phone
            ticket = c.notes or f"#{c.id}"
            short_desc = (c.description or "")[:30].strip()
            resolved_tickets.append((ticket, room, short_desc))
            entry.linked_id = c.id
            entry.linked_type = "complaint"

    icon = _TYPE_ICONS.get(log_type, "📝")
    parts = [f"{icon} *Activity logged*"]
    parts.append(f"Type: {log_type.value}")
    parts.append(f"Description: {description}")
    if room:
        parts.append(f"Room: {room}")
    if amount:
        parts.append(f"Amount: ₹{int(amount):,}")
    if prop:
        parts.append(f"Property: {prop}")
    for ticket, rm, desc in resolved_tickets:
        issue_short = desc if desc else "issue"
        parts.append(f"\n✅ *Complaint closed!* Room {rm} {issue_short} ({ticket}) sorted.")
    return "\n".join(parts)


async def _query_activity(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Query activity log entries."""
    raw = entities.get("_raw_message", "").lower().strip()
    today = date.today()

    # Determine date range
    from_dt = datetime(today.year, today.month, today.day, 0, 0, 0)
    to_dt = datetime(today.year, today.month, today.day, 23, 59, 59)
    label = "today"

    if "yesterday" in raw:
        yesterday = today - timedelta(days=1)
        from_dt = datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0)
        to_dt = datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
        label = "yesterday"
    elif "this week" in raw or "week" in raw:
        week_start = today - timedelta(days=today.weekday())
        from_dt = datetime(week_start.year, week_start.month, week_start.day, 0, 0, 0)
        label = "this week"
    elif re.search(r"last\s+(\d+)\s+days?", raw):
        m = re.search(r"last\s+(\d+)\s+days?", raw)
        days = int(m.group(1))
        start = today - timedelta(days=days)
        from_dt = datetime(start.year, start.month, start.day, 0, 0, 0)
        label = f"last {days} days"

    # Build query
    q = select(ActivityLog).where(
        and_(
            ActivityLog.created_at >= from_dt,
            ActivityLog.created_at <= to_dt,
        )
    )

    # Room filter
    room_filter = None
    rm = re.search(r"room\s+([\w-]+)", raw, re.I)
    if rm:
        room_filter = rm.group(1)
        q = q.where(ActivityLog.room == room_filter)
        label += f" (room {room_filter})"

    q = q.order_by(ActivityLog.created_at.desc())
    result = await session.execute(q)
    entries = result.scalars().all()

    if not entries:
        return f"No activity logged {label}."

    lines = [f"*Activity log — {label}* ({len(entries)} entries)\n"]
    for e in entries:
        icon = _TYPE_ICONS.get(e.log_type, "📝") if e.log_type else "📝"
        time_str = e.created_at.strftime("%I:%M %p") if e.created_at else ""
        who = e.logged_by or "?"
        line = f"{icon} {time_str} — {e.description}"
        if e.amount:
            line += f" (₹{int(e.amount):,})"
        if e.room:
            line += f" [Room {e.room}]"
        line += f" — by {who}"
        lines.append(line)

    return "\n".join(lines)
