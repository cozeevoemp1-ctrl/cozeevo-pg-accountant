"""
src/whatsapp/handlers/account_handler.py
=========================================
AccountWorker — dedicated accountant persona for the PG bot.

Owns all financial intents: payments, dues, expenses, reports, rent changes,
refunds, and tenant account queries.

Accounting conventions used throughout:
  - All amounts prefixed with Rs.
  - Full breakdown shown (due / paid / balance)
  - All math delegated to services/property_logic.py — never duplicated here

Routing:
  The Gatekeeper (gatekeeper.py) routes any intent in FINANCIAL_INTENTS to
  handle_account(). Owner-role users (admin / power_user / key_user) reach
  this worker; tenant / lead messages never do.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import (
    Expense, Payment, PaymentFor, PaymentMode,
    PendingAction, Refund, RefundStatus, RentSchedule, RentStatus,
    Room, SharingType, Tenant, Tenancy, TenancyStatus,
)
from src.whatsapp.role_service import CallerContext
from src.database.validators import check_tenancy_active
from services.property_logic import (
    calc_effective_due,
    calc_payment_status,
)
from src.whatsapp.handlers._shared import (
    _find_active_tenants_by_name,
    _find_active_tenants_by_room,
    _find_similar_names,
    _make_choices,
    _save_pending,
    _format_choices_message,
    _format_no_match_message,
    build_dues_snapshot,
    compute_allocation,
    format_allocation,
)


# ── Financial intents owned by this worker ────────────────────────────────────

FINANCIAL_INTENTS: frozenset[str] = frozenset({
    "PAYMENT_LOG",
    "QUERY_DUES",
    "QUERY_TENANT",
    "ADD_EXPENSE",
    "QUERY_EXPENSES",
    "REPORT",
    "RENT_CHANGE",
    "RENT_DISCOUNT",
    "VOID_PAYMENT",
    "VOID_EXPENSE",
    "DEPOSIT_CHANGE",
    "ADD_REFUND",
    "QUERY_REFUNDS",
    "BANK_REPORT",
    "BANK_DEPOSIT_MATCH",
})


# ── Main dispatcher ───────────────────────────────────────────────────────────

async def handle_account(
    intent: str,
    entities: dict,
    ctx: CallerContext,
    session: AsyncSession,
) -> str:
    handlers = {
        "PAYMENT_LOG":    _payment_log,
        "QUERY_DUES":     _query_dues,
        "QUERY_TENANT":   _query_tenant,
        "ADD_EXPENSE":    _add_expense_prompt,
        "QUERY_EXPENSES": _query_expenses,
        "REPORT":         _report,
        "RENT_CHANGE":    _rent_change,
        "RENT_DISCOUNT":  _rent_discount,
        "VOID_PAYMENT":   _void_payment,
        "VOID_EXPENSE":   _void_expense,
        "DEPOSIT_CHANGE": _deposit_change,
        "ADD_REFUND":     _add_refund,
        "QUERY_REFUNDS":  _query_refunds,
    }
    # Bank analytics — delegated to finance_handler
    if intent == "BANK_REPORT":
        from src.whatsapp.handlers.finance_handler import handle_bank_report
        return await handle_bank_report(entities, ctx, session)
    if intent == "BANK_DEPOSIT_MATCH":
        from src.whatsapp.handlers.finance_handler import handle_deposit_match
        return await handle_deposit_match(entities, ctx, session)

    fn = handlers.get(intent, _unknown_financial)
    return await fn(entities, ctx, session)


# ── Payment log ───────────────────────────────────────────────────────────────

async def _payment_log(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name   = entities.get("name", "").strip()
    room   = entities.get("room", "").strip()
    amount = entities.get("amount")
    mode   = entities.get("payment_mode", "cash")
    month_num = entities.get("month")

    # If no amount AND no name -> start step-by-step collect rent form
    if not amount and not name and not room:
        await _save_pending(
            ctx.phone, "COLLECT_RENT_STEP",
            {"step": "ask_name", "logged_by": ctx.name or ctx.phone},
            [], session,
        )
        return "*Collect Rent*\n\n*Who paid?* (tenant name or room number)"

    if not amount:
        return (
            "Please include the amount.\n"
            "Format: *[Name] paid [Amount] [cash/upi]*\n"
            "Example: *Raj paid 15000 upi*"
        )

    if not name and not room:
        return (
            f"Whose payment of Rs.{int(amount):,}? Please say: *[Name] paid [Amount]*\n"
            "For family payments covering multiple tenants, send separately:\n"
            "- *Raj paid 15000 upi*\n"
            "- *Rahul paid 15000 upi*"
        )

    rows: list = []
    search_term = name

    if name:
        rows = await _find_active_tenants_by_name(name, session)
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)
        search_term = f"Room {room}"

    if len(rows) == 0:
        suggestions = await _find_similar_names(name, session) if name else []
        base = _format_no_match_message(name or room, suggestions)
        return base + f"\n\n_(Amount to log: Rs.{int(amount):,} {(mode or 'cash').upper()})_"

    # Determine intended period month
    current_month = date.today().replace(day=1)
    if month_num:
        period_month = date(date.today().year, int(month_num), 1)
    else:
        period_month = None  # let allocation decide

    if len(rows) == 1:
        tenant, tenancy, _room = rows[0]
        snapshot = await build_dues_snapshot(tenancy.id, tenant.name, _room.room_number, session)
        amount_dec = Decimal(str(amount))
        pending_months = snapshot["months"]

        if not pending_months:
            # No dues — log to current month, will trigger overpayment flow
            pm = period_month or current_month
            await _save_pending(
                ctx.phone, "CONFIRM_PAYMENT_LOG",
                {
                    "tenant_id": tenant.id,
                    "tenancy_id": tenancy.id,
                    "amount": amount,
                    "mode": mode,
                    "logged_by": ctx.name or ctx.phone,
                    "period_month": pm.isoformat(),
                    "tenant_name": tenant.name,
                    "room_number": _room.room_number,
                },
                [], session,
            )
            mode_label = (mode or "cash").upper()
            return (
                snapshot["text"] + "\n\n"
                f"*Confirm Payment?*\n"
                f"- Amount : Rs.{int(amount):,}\n"
                f"- Mode   : {mode_label}\n"
                f"- Month  : {pm.strftime('%B %Y')}\n\n"
                "Reply *Yes* to log or *No* to cancel."
            )

        # If user specified a month, force allocation to that month
        if period_month:
            allocation = [{"period": period_month, "amount": amount_dec, "clears": False}]
        else:
            allocation = compute_allocation(amount_dec, pending_months)

        # Build allocation data for pending
        alloc_data = [{"period": a["period"].isoformat(), "amount": float(a["amount"])} for a in allocation]
        pending_data = {
            "tenant_id": tenant.id,
            "tenancy_id": tenancy.id,
            "amount": amount,
            "mode": mode,
            "logged_by": ctx.name or ctx.phone,
            "allocation": alloc_data,
            "tenant_name": tenant.name,
            "room_number": _room.room_number,
        }

        # If multi-month dues, include month data for override parsing
        if len(pending_months) > 1:
            pending_data["pending_months"] = [
                {"period": m["period"].isoformat(), "remaining": float(m["remaining"])}
                for m in pending_months
            ]

        await _save_pending(ctx.phone, "CONFIRM_PAYMENT_ALLOC", pending_data, [], session)
        alloc_text = format_allocation(allocation, amount, mode)

        if len(pending_months) > 1:
            return (
                snapshot["text"] + "\n"
                + alloc_text + "\n\n"
                'Reply *Yes* to confirm, or specify different allocation:\n'
                '  e.g. "all to march" or "feb 3000 march 5000"'
            )
        else:
            return (
                snapshot["text"] + "\n"
                + alloc_text + "\n\n"
                "Reply *Yes* to confirm, or *No* to cancel."
            )

    # Multiple tenant matches — ask which one
    choices = _make_choices(rows)
    await _save_pending(
        ctx.phone, "PAYMENT_LOG",
        {
            "amount": amount, "mode": mode, "name_raw": search_term,
            "logged_by": ctx.name or ctx.phone,
        },
        choices, session,
    )
    return _format_choices_message(search_term, choices, f"log Rs.{int(amount):,} payment")


async def _do_log_payment_by_ids(
    tenant_id: int,
    tenancy_id: int,
    amount,
    mode: str,
    ctx_name: str,
    session: AsyncSession,
    period_month_str: str = "",
    skip_duplicate_check: bool = False,
) -> str:
    tenant = await session.get(Tenant, tenant_id)
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenant or not tenancy:
        return "Could not find tenant record. Please try again."

    # Guard: reject payment if tenancy is not active
    ok, reason = await check_tenancy_active(tenancy_id, session)
    if not ok:
        return reason

    # Resolve period month
    current_month = date.today().replace(day=1)
    try:
        period_month = date.fromisoformat(period_month_str) if period_month_str else current_month
    except ValueError:
        period_month = current_month

    pay_mode = PaymentMode.upi if mode == "upi" else PaymentMode.cash
    amount_dec = Decimal(str(amount))

    # ── Duplicate detection ────────────────────────────────────────────────────
    if not skip_duplicate_check:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        dup = await session.scalar(
            select(Payment).where(
                Payment.tenancy_id == tenancy.id,
                Payment.amount == amount_dec,
                Payment.period_month == period_month,
                Payment.is_void == False,
                Payment.created_at >= cutoff,
            )
        )
        if dup:
            dup_time = dup.created_at.strftime("%d %b %H:%M") if dup.created_at else "recently"
            choices = [
                {"seq": 1, "label": "Log anyway (it's a different payment)"},
                {"seq": 2, "label": "Cancel (it's a duplicate)"},
            ]
            await _save_pending(
                tenant.phone or ctx_name, "DUPLICATE_CONFIRM",
                {
                    "tenant_id": tenant_id, "tenancy_id": tenancy_id,
                    "amount": float(amount_dec), "mode": mode,
                    "logged_by": ctx_name, "period_month": period_month.isoformat(),
                },
                choices, session,
            )
            return (
                f"⚠️ *Possible duplicate!*\n"
                f"Rs.{int(amount_dec):,} for {tenant.name} ({period_month.strftime('%b %Y')}) "
                f"was already logged at {dup_time}.\n\n"
                "1. Log anyway (different payment)\n"
                "2. Cancel (it's a duplicate)\n\n"
                "Reply *1* or *2*."
            )

    # ── Wrong month check ──────────────────────────────────────────────────────
    wrong_month_note = ""
    if period_month != current_month:
        target_rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy.id,
                RentSchedule.period_month == period_month,
            )
        )
        if target_rs and target_rs.status == RentStatus.paid:
            curr_rs = await session.scalar(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == tenancy.id,
                    RentSchedule.period_month == current_month,
                )
            )
            curr_pending = curr_rs and curr_rs.status in (RentStatus.pending, RentStatus.partial)
            note = f"\n⚠️ *{period_month.strftime('%b %Y')} is already PAID*."
            if curr_pending:
                note += f" Did you mean *{current_month.strftime('%b %Y')}* (currently pending)?"
            wrong_month_note = note

    # ── Create payment ─────────────────────────────────────────────────────────
    payment = Payment(
        tenancy_id=tenancy.id,
        amount=amount_dec,
        payment_date=date.today(),
        payment_mode=pay_mode,
        for_type=PaymentFor.rent,
        period_month=period_month,
        notes=f"Logged via WhatsApp by {ctx_name}",
    )
    session.add(payment)

    # ── Update rent schedule ───────────────────────────────────────────────────
    rs = await session.scalar(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy.id,
            RentSchedule.period_month == period_month,
        )
    )

    if not rs:
        # Auto-generate rent_schedule for this month with notes carry-over
        prev_month = period_month.replace(day=1)
        if prev_month.month == 1:
            prev_month = date(prev_month.year - 1, 12, 1)
        else:
            prev_month = date(prev_month.year, prev_month.month - 1, 1)

        prev_rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy.id,
                RentSchedule.period_month == prev_month,
            )
        )
        carry_notes = prev_rs.notes if prev_rs else None

        rs = RentSchedule(
            tenancy_id=tenancy.id,
            period_month=period_month,
            rent_due=tenancy.agreed_rent or Decimal("0"),
            maintenance_due=tenancy.maintenance_fee or Decimal("0"),
            status=RentStatus.pending,
            due_date=period_month,
            notes=carry_notes,
        )
        session.add(rs)
        await session.flush()

    prev_paid = await session.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.tenancy_id == tenancy.id,
            Payment.period_month == period_month,
            Payment.is_void == False,
        )
    ) or Decimal("0")
    total_paid = prev_paid + amount_dec
    rent_due = (rs.rent_due if rs else tenancy.agreed_rent) or Decimal("0")
    adj = (rs.adjustment if rs else Decimal("0")) or Decimal("0")
    effective_due = rent_due + adj  # negative adj = discount

    if rs:
        if total_paid >= effective_due:
            rs.status = RentStatus.paid
        else:
            rs.status = RentStatus.partial

    # ── Underpayment note ──────────────────────────────────────────────────────
    remaining = effective_due - total_paid
    underpayment_note = ""
    if Decimal("0") < remaining <= effective_due:
        underpayment_note = (
            f"\n💡 Rs.{int(remaining):,} still outstanding for {period_month.strftime('%b %Y')}. "
            "Log the rest when received."
        )

    # ── Overpayment check ──────────────────────────────────────────────────────
    overpayment_pending = ""
    extra = total_paid - effective_due
    if extra > Decimal("10"):   # more than Rs.10 extra (ignore rounding noise)
        next_m = period_month.replace(month=period_month.month % 12 + 1) if period_month.month < 12 else date(period_month.year + 1, 1, 1)
        choices = [
            {"seq": 1, "label": f"Advance for {next_m.strftime('%b %Y')}"},
            {"seq": 2, "label": "Add to security deposit"},
            {"seq": 3, "label": "Ask tenant what it's for"},
        ]
        await _save_pending(
            tenant.phone or ctx_name, "OVERPAYMENT_RESOLVE",
            {
                "tenancy_id": tenancy.id, "tenant_name": tenant.name,
                "extra_amount": float(extra), "mode": mode,
                "next_month": next_m.isoformat(),
            },
            choices, session,
        )
        overpayment_pending = (
            f"\n\n⚠️ *Overpayment: Rs.{int(extra):,} extra*\n"
            f"1. Advance for {next_m.strftime('%b %Y')}\n"
            "2. Add to security deposit\n"
            "3. Ask tenant\n\n"
            "Reply *1*, *2*, or *3*."
        )

    status_str = "Paid ✅" if rs and rs.status == RentStatus.paid else "Partial ⏳"
    room_obj = await session.get(Room, tenancy.room_id)
    room_label = f" (Room {room_obj.room_number})" if room_obj else ""

    # ── Google Sheets write-back (fire-and-forget) ────────────────────────────
    gsheets_note = ""
    if room_obj:
        try:
            from src.integrations.gsheets import update_payment as gsheets_update
            gs_result = await gsheets_update(
                room_number=room_obj.room_number,
                tenant_name=tenant.name,
                amount=float(amount_dec),
                method=mode,
                month=period_month.month,
                year=period_month.year,
            )
            if gs_result.get("error"):
                import logging as _logging
                _logging.getLogger(__name__).warning("GSheets: %s", gs_result["error"])
                gsheets_note = f"\n⚠️ Sheet not updated: {gs_result['error']}"
            elif gs_result.get("success"):
                sheet_month = gs_result.get("month", period_month.month)
                month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun"}
                ml = month_names.get(sheet_month, f"M{sheet_month}")
                rent = gs_result.get("rent_due", 0)
                total = gs_result.get("total_paid", 0)
                parts = [f"Sheet updated ({ml})"]
                if rent > 0:
                    parts.append(f"Rs.{int(total):,}/{int(rent):,}")
                overpay = gs_result.get("overpayment", 0)
                if overpay and overpay > 0:
                    parts.append(f"OVERPAID +Rs.{int(overpay):,}")
                warning = gs_result.get("warning")
                if warning:
                    parts.append(warning)
                gsheets_note = "\n" + " | ".join(parts)
                # Previous month dues reminder
                prev_dues = gs_result.get("prev_dues", 0)
                if prev_dues and prev_dues > 0:
                    prev_tab = gs_result.get("prev_tab", "")
                    prev_notes = gs_result.get("prev_notes", "")
                    gsheets_note += f"\n⚠️ *Previous dues: Rs.{int(prev_dues):,}* ({prev_tab})"
                    if prev_notes:
                        gsheets_note += f"\nPrev notes: {prev_notes[:100]}"
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).error("GSheets write-back failed: %s", e)
            # Don't block the payment response on sheet errors

    return (
        f"*Payment logged — {tenant.name}{room_label}*\n"
        f"Amount: Rs.{int(amount_dec):,} ({mode.upper()})\n"
        f"Month: {period_month.strftime('%B %Y')}\n"
        f"Status: {status_str}"
        f"{underpayment_note}"
        f"{wrong_month_note}"
        f"{overpayment_pending}"
        f"{gsheets_note}"
    )


# ── Void payment ──────────────────────────────────────────────────────────────

async def _void_payment(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Void/reverse a payment (UPI reversal, wrong entry, duplicate)."""
    name = entities.get("name", "").strip()
    room = entities.get("room", "").strip()
    month_num = entities.get("month")

    if not name and not room:
        return (
            "Which tenant's payment should be voided?\n"
            "Say: *void payment Raj* or *void payment Room 203*\n"
            "I'll show the most recent payment to void."
        )

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

    if len(rows) > 1:
        choices = _make_choices(rows)
        await _save_pending(ctx.phone, "VOID_WHO", {}, choices, session)
        return _format_choices_message(search_term, choices, "void their payment")

    tenant, tenancy, _room = rows[0]

    q = select(Payment).where(
        Payment.tenancy_id == tenancy.id,
        Payment.is_void == False,
    ).order_by(Payment.created_at.desc())
    if month_num:
        period = date(date.today().year, int(month_num), 1)
        q = q.where(Payment.period_month == period)

    payment = await session.scalar(q)
    if not payment:
        return f"No active payment found for *{tenant.name}*."

    choices = [
        {"seq": 1, "label": "Yes, void it"},
        {"seq": 2, "label": "No, keep it"},
    ]
    await _save_pending(
        ctx.phone, "VOID_PAYMENT",
        {
            "payment_id": payment.id,
            "tenant_name": tenant.name,
            "amount": float(payment.amount),
            "period_month": payment.period_month.isoformat() if payment.period_month else "",
        },
        choices, session,
    )
    period_str = payment.period_month.strftime("%b %Y") if payment.period_month else "unknown month"
    return (
        f"*Void this payment?*\n"
        f"Tenant: {tenant.name}\n"
        f"Amount: Rs.{int(payment.amount):,} ({payment.payment_mode.value if payment.payment_mode else 'unknown'})\n"
        f"Month: {period_str}\n"
        f"Date: {payment.payment_date.strftime('%d %b %Y') if payment.payment_date else 'unknown'}\n\n"
        "1. Yes, void it\n"
        "2. No, keep it\n\n"
        "Reply *1* or *2*."
    )


async def _do_void_payment(payment_id: int, tenant_name: str, session: AsyncSession) -> str:
    """Mark a payment as void and revert rent_schedule status."""
    payment = await session.get(Payment, payment_id)
    if not payment:
        return "Payment record not found."

    payment.is_void = True

    if payment.period_month:
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == payment.tenancy_id,
                RentSchedule.period_month == payment.period_month,
            )
        )
        if rs:
            remaining_paid = await session.scalar(
                select(func.sum(Payment.amount)).where(
                    Payment.tenancy_id == payment.tenancy_id,
                    Payment.period_month == payment.period_month,
                    Payment.is_void == False,
                    Payment.id != payment_id,
                )
            ) or Decimal("0")
            rent_due = rs.rent_due or Decimal("0")
            adj = rs.adjustment or Decimal("0")
            effective_due = rent_due + adj
            if remaining_paid <= Decimal("0"):
                rs.status = RentStatus.pending
            elif remaining_paid < effective_due:
                rs.status = RentStatus.partial
            else:
                rs.status = RentStatus.paid

    period_str = payment.period_month.strftime("%b %Y") if payment.period_month else ""
    return (
        f"*Payment voided — {tenant_name}*\n"
        f"Rs.{int(payment.amount):,} for {period_str} reversed.\n"
        "Rent schedule updated. Log correct payment if needed."
    )


# ── Void expense ──────────────────────────────────────────────────────────────

async def _void_expense(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show filterable expense list for voiding. Filter by keyword if provided."""
    from src.database.models import ExpenseCategory

    keyword = (entities.get("name") or entities.get("description") or "").strip().lower()

    q = (
        select(Expense, ExpenseCategory.name)
        .outerjoin(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .where(Expense.is_void == False)
        .order_by(Expense.expense_date.desc(), Expense.id.desc())
    )
    if keyword:
        q = q.where(
            func.lower(ExpenseCategory.name).contains(keyword) |
            func.lower(Expense.description).contains(keyword)
        )

    rows = (await session.execute(q.limit(10))).all()

    if not rows:
        hint = f" matching *{keyword}*" if keyword else ""
        return (
            f"No active expenses found{hint}.\n"
            "Try: *void expense salary* or *void expense electricity*"
        )

    header = f"*Expenses{' matching ' + keyword if keyword else ''} — pick one to void:*\n"
    lines = [header]
    choices = []
    for i, (exp, cat_name) in enumerate(rows, 1):
        date_str = exp.expense_date.strftime("%d %b") if exp.expense_date else "?"
        desc = f" — {exp.description[:25]}" if exp.description else ""
        label = f"{cat_name or 'General'} ₹{int(exp.amount):,} ({date_str}){desc}"
        lines.append(f"*{i}.* {label}")
        choices.append({"seq": i, "label": label, "expense_id": exp.id})

    n = len(choices)
    lines.append(f"\nReply *1–{n}* to void · *No* to cancel")
    lines.append("Or narrow down: *void expense salary*")
    await _save_pending(ctx.phone, "VOID_EXPENSE", {"choices": choices}, choices, session)
    return "\n".join(lines)


async def _do_void_expense(expense_id: int, session: AsyncSession) -> str:
    expense = await session.get(Expense, expense_id)
    if not expense:
        return "Expense record not found."
    expense.is_void = True
    return f"Expense voided — ₹{int(expense.amount):,} reversed."


# ── Deposit change ─────────────────────────────────────────────────────────────

async def _deposit_change(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Change the security deposit amount for a tenant."""
    name = entities.get("name", "").strip()
    amount = entities.get("amount")

    if not name:
        return (
            "Which tenant's deposit to change?\n"
            "Say: *change deposit Raj 15000*"
        )

    rows = await _find_active_tenants_by_name(name, session)
    if not rows:
        suggestions = await _find_similar_names(name, session)
        return _format_no_match_message(name, suggestions)
    if len(rows) > 1:
        choices = _make_choices(rows)
        await _save_pending(ctx.phone, "DEPOSIT_CHANGE_WHO", {"amount": amount}, choices, session)
        return _format_choices_message(name, choices, "change their deposit")

    tenant, tenancy, room = rows[0]
    current = int(tenancy.security_deposit or 0)

    if not amount:
        await _save_pending(ctx.phone, "DEPOSIT_CHANGE_AMT", {"tenancy_id": tenancy.id, "tenant_name": tenant.name}, [], session)
        return (
            f"*{tenant.name}* — Room {room.room_number}\n"
            f"Current deposit: ₹{current:,}\n\n"
            "Reply with the new deposit amount:"
        )

    new_amt = int(amount)
    choices = [{"seq": 1, "label": "Yes, update"}, {"seq": 2, "label": "No, cancel"}]
    await _save_pending(
        ctx.phone, "DEPOSIT_CHANGE",
        {"tenancy_id": tenancy.id, "tenant_name": tenant.name, "new_amount": new_amt, "old_amount": current},
        choices, session,
    )
    return (
        f"*Change deposit — {tenant.name}*\n"
        f"Room {room.room_number}\n"
        f"Current: ₹{current:,}  →  New: ₹{new_amt:,}\n\n"
        "Reply *Yes* to confirm or *No* to cancel."
    )


async def _do_deposit_change(tenancy_id: int, new_amount: int, tenant_name: str, session: AsyncSession) -> str:
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenancy:
        return "Tenancy record not found."
    tenancy.security_deposit = new_amount
    return f"Deposit updated — *{tenant_name}* ₹{new_amount:,}"


# ── Outstanding dues calculator ───────────────────────────────────────────────

async def _calc_outstanding_dues(tenancy_id: int, session: AsyncSession) -> tuple[Decimal, Decimal]:
    """
    Returns (outstanding_rent, outstanding_maintenance) for a tenancy.
    For partial months, deducts what's already been paid.
    Also imported by owner_handler for _room_status and _do_checkout.
    """
    pending_schedules_result = await session.execute(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy_id,
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
        )
    )
    outstanding_rent = Decimal("0")
    outstanding_maintenance = Decimal("0")

    for rs in pending_schedules_result.scalars().all():
        # Rent: due minus already paid
        paid_rent = await session.scalar(
            select(func.sum(Payment.amount)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.period_month == rs.period_month,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
            )
        ) or Decimal("0")
        effective_due = (rs.rent_due or Decimal("0")) + (rs.adjustment or Decimal("0"))
        outstanding_rent += max(Decimal("0"), effective_due - paid_rent)

        # Maintenance: due minus already paid
        paid_maint = await session.scalar(
            select(func.sum(Payment.amount)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.period_month == rs.period_month,
                Payment.for_type == PaymentFor.maintenance,
                Payment.is_void == False,
            )
        ) or Decimal("0")
        maint_due = rs.maintenance_due or Decimal("0")
        outstanding_maintenance += max(Decimal("0"), maint_due - paid_maint)

    return outstanding_rent, outstanding_maintenance


# ── Query dues ────────────────────────────────────────────────────────────────

async def _query_dues(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    today = date.today()
    month_num = entities.get("month")
    desc = (entities.get("description") or "").lower()

    # If user asked "which month?" rather than specifying one → clarify
    if not month_num and ("which" in desc or (desc.endswith("?") and not any(
        m in desc for m in ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]
    ))):
        await _save_pending(
            ctx.phone, "AWAITING_CLARIFICATION",
            {"original_intent": "QUERY_DUES", "waiting_for": "month", "entities": {}},
            [], session,
        )
        return "Which month's dues would you like to see?\n\nReply: *Jan*, *Feb*, *Mar*, *Apr*, *May*..."

    if month_num:
        year = entities.get("year") or today.year
        query_month = date(int(year), int(month_num), 1)
    else:
        query_month = today.replace(day=1)

    query_month_last = date(
        query_month.year, query_month.month,
        calendar.monthrange(query_month.year, query_month.month)[1],
    )

    result = await session.execute(
        select(Tenant.name, RentSchedule.rent_due, RentSchedule.status)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(RentSchedule, RentSchedule.tenancy_id == Tenancy.id)
        .where(
            Tenancy.status == TenancyStatus.active,
            Tenancy.checkin_date <= query_month_last,
            RentSchedule.period_month == query_month,
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
        )
        .order_by(Tenant.name)
        .distinct(Tenant.name)
    )
    rows = result.all()

    if not rows:
        return f"All tenants are paid up for {query_month.strftime('%B %Y')}!"

    lines = [f"*Pending dues — {query_month.strftime('%B %Y')}*\n"]
    total = Decimal("0")
    seen = set()
    for name, rent_due, status in rows:
        if name in seen:
            continue
        seen.add(name)
        status_str = "Partial" if status == RentStatus.partial else "Pending"
        lines.append(f"• {name}: Rs.{int(rent_due or 0):,} ({status_str})")
        total += rent_due or Decimal("0")

    lines.append(f"\n*Total outstanding: Rs.{int(total):,}*")
    return "\n".join(lines)


# ── Query tenant account ───────────────────────────────────────────────────────

async def _query_tenant(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name = entities.get("name", "").strip()
    room = entities.get("room", "").strip()

    if not name and not room:
        return "Which tenant? Please say: *[Name] balance* or *Room 203 balance*"

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

    if len(rows) == 1:
        tenant, tenancy, _room = rows[0]
        return await _do_query_tenant_by_id(tenant.id, tenancy.id, session)

    choices = _make_choices(rows)
    await _save_pending(ctx.phone, "QUERY_TENANT", {"name_raw": search_term}, choices, session)
    return _format_choices_message(search_term, choices, "view their account")


async def _do_query_tenant_by_id(tenant_id: int, tenancy_id: int, session: AsyncSession) -> str:
    tenant = await session.get(Tenant, tenant_id)
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenant or not tenancy:
        return "Tenant record not found."

    room_obj = await session.get(Room, tenancy.room_id)
    room_label = room_obj.room_number if room_obj else "?"

    current_month = date.today().replace(day=1)
    rs = await session.scalar(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy.id,
            RentSchedule.period_month == current_month,
        )
    )

    status_str = rs.status.value.upper() if rs else "No record"
    o_rent, o_maintenance = await _calc_outstanding_dues(tenancy.id, session)

    sharing_label = tenancy.sharing_type.value if tenancy.sharing_type else ""

    # Deposit gap line
    if tenancy.security_deposit and tenancy.security_deposit > 0:
        _dep = int(tenancy.security_deposit)
        _dep_paid = int(tenancy.booking_amount or 0)
        _dep_remaining = _dep - _dep_paid
        if _dep_remaining > 0:
            deposit_line = f"Deposit: Rs.{_dep:,} (Paid: Rs.{_dep_paid:,} | *Due: Rs.{_dep_remaining:,}*)"
        else:
            deposit_line = f"Deposit: Rs.{_dep:,} (Fully paid)"
    else:
        deposit_line = "Security deposit: Rs.0"

    lines = [
        f"*{tenant.name}*",
        f"Phone: {tenant.phone}",
        f"Room: {room_label}" + (f" ({sharing_label})" if sharing_label else ""),
        f"Room rent: Rs.{int(tenancy.agreed_rent or 0):,}/month",
        deposit_line,
        f"Checkin: {tenancy.checkin_date.strftime('%d %b %Y')}",
        f"This month ({current_month.strftime('%b %Y')}): {status_str}",
    ]

    # Notes / comments
    if tenancy.notes:
        lines += ["", f"Notes: {tenancy.notes}"]

    # Booking advance — show check-in due calculation
    booking_amount = tenancy.booking_amount or Decimal("0")
    if booking_amount > 0:
        checkin_month = tenancy.checkin_date.replace(day=1)
        checkin_rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy.id,
                RentSchedule.period_month == checkin_month,
            )
        )
        if checkin_rs:
            first_rent = (checkin_rs.rent_due or Decimal("0")) + (checkin_rs.adjustment or Decimal("0"))
        else:
            days_in_month = calendar.monthrange(tenancy.checkin_date.year, tenancy.checkin_date.month)[1]
            days_remaining = max(0, days_in_month - tenancy.checkin_date.day + 1)
            first_rent = Decimal(str(int(Decimal(str(tenancy.agreed_rent or 0)) * days_remaining / days_in_month)))
        deposit = tenancy.security_deposit or Decimal("0")
        net_due = deposit + first_rent - booking_amount
        lines += [
            "",
            "*Due at check-in*",
            f"Deposit          : Rs.{int(deposit):,}",
            f"First month rent : Rs.{int(first_rent):,}",
            f"Advance paid     : -Rs.{int(booking_amount):,}",
            "─" * 26,
            f"*Net due: Rs.{int(net_due):,}*",
        ]
    elif o_rent > 0:
        lines += ["", f"*Rent outstanding: Rs.{int(o_rent):,}*"]
    else:
        lines.append("All dues cleared!")

    # ── Month-on-month payment history ────────────────────────────────────────
    all_rs_result = await session.execute(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy.id,
        ).order_by(RentSchedule.period_month)
    )
    all_rs = all_rs_result.scalars().all()

    if all_rs:
        history_lines = ["", "*Payment History:*"]
        month_names = {
            1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
        }
        for sched in all_rs:
            rent_due = (sched.rent_due or Decimal("0")) + (sched.adjustment or Decimal("0"))
            m_label = month_names.get(sched.period_month.month, "?")

            # Get payments for this month grouped by mode
            payments_result = await session.execute(
                select(Payment).where(
                    Payment.tenancy_id == tenancy.id,
                    Payment.period_month == sched.period_month,
                    Payment.is_void == False,
                )
            )
            payments = payments_result.scalars().all()
            total_paid = sum(p.amount for p in payments) or Decimal("0")

            # Build payment breakdown by mode
            by_mode: dict[str, Decimal] = {}
            for p in payments:
                mode_key = p.payment_mode.value.capitalize() if p.payment_mode else "Other"
                by_mode[mode_key] = by_mode.get(mode_key, Decimal("0")) + p.amount

            # Status label
            if sched.status == RentStatus.paid:
                status_tag = "PAID"
            elif sched.status == RentStatus.partial:
                remaining = max(Decimal("0"), rent_due - total_paid)
                status_tag = f"PARTIAL (due Rs.{int(remaining):,})"
            elif sched.status == RentStatus.waived:
                status_tag = "WAIVED"
            elif sched.status in (RentStatus.na, RentStatus.exit):
                status_tag = sched.status.value.upper()
            else:
                status_tag = "PENDING"

            # Format mode breakdown
            if by_mode:
                mode_parts = [f"{mode} Rs.{int(amt):,}" for mode, amt in by_mode.items()]
                mode_str = " (" + " + ".join(mode_parts) + ")"
            else:
                mode_str = ""

            history_lines.append(
                f"  {m_label}: Rs.{int(rent_due):,} — {status_tag}{mode_str}"
            )

        lines += history_lines

    return "\n".join(lines)


# ── Rent change ────────────────────────────────────────────────────────────────

async def _rent_change(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name     = entities.get("name", "").strip()
    room     = entities.get("room", "").strip()
    amount   = entities.get("amount")
    month    = entities.get("month")
    date_str = entities.get("date", "")

    if not amount:
        return (
            "What's the new rent amount?\n"
            "Say: *[Name] rent is now [amount]* or *from March [Name] rent [amount]*"
        )

    rows: list = []
    search_term = name
    if name:
        rows = await _find_active_tenants_by_name(name, session)
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)
        search_term = f"Room {room}"

    if not name and not room:
        return "Which tenant? Say: *[Name] rent is now [amount]*"

    if len(rows) == 0:
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)

    if date_str:
        try:
            effective_month = date.fromisoformat(date_str).replace(day=1)
        except ValueError:
            effective_month = date.today().replace(day=1)
    elif month:
        effective_month = date(date.today().year, month, 1)
    else:
        effective_month = date.today().replace(day=1)

    if len(rows) > 1:
        choices = _make_choices(rows)
        action_data = {
            "new_amount": amount, "month": effective_month.isoformat(),
            "is_discount": False, "reason": "",
        }
        await _save_pending(ctx.phone, "RENT_CHANGE_WHO", action_data, choices, session)
        return _format_choices_message(search_term, choices, f"apply rent change to Rs.{int(amount):,}")

    tenant, tenancy, room_obj = rows[0]
    old_rent = int(tenancy.agreed_rent or 0)

    option_choices = [
        {"seq": 1, "label": f"Only {effective_month.strftime('%b %Y')} (one month)"},
        {"seq": 2, "label": f"Permanent from {effective_month.strftime('%b %Y')} onwards"},
    ]
    action_data = {
        "tenancy_id": tenancy.id, "tenant_name": tenant.name,
        "new_amount": amount, "month": effective_month.isoformat(),
        "is_discount": False, "reason": f"rent change from Rs.{old_rent:,}",
    }
    await _save_pending(ctx.phone, "RENT_CHANGE", action_data, option_choices, session)

    return (
        f"*Rent change for {tenant.name}* (Room {room_obj.room_number})\n"
        f"Current rent: Rs.{old_rent:,}/month\n"
        f"New rent: Rs.{int(amount):,}/month\n"
        f"Effective: {effective_month.strftime('%b %Y')}\n\n"
        f"1. Only {effective_month.strftime('%b %Y')}\n"
        f"2. Permanent from {effective_month.strftime('%b %Y')}\n\n"
        "Reply *1* or *2*."
    )


async def _rent_discount(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name   = entities.get("name", "").strip()
    room   = entities.get("room", "").strip()
    amount = entities.get("amount")

    if not amount:
        return (
            "How much concession/charge?\n"
            "Say: *give [Name] 1000 concession* or *add 500 surcharge to [Name]*\n"
            "Example: *give Asha 1000 discount for water issue*"
        )

    rows: list = []
    search_term = name
    if name:
        rows = await _find_active_tenants_by_name(name, session)
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)
        search_term = f"Room {room}"

    if not name and not room:
        return "Which tenant? Say: *give [Name] [amount] concession*"

    if len(rows) == 0:
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)

    current_month = date.today().replace(day=1)

    if len(rows) > 1:
        choices = _make_choices(rows)
        action_data = {
            "new_amount": amount, "month": current_month.isoformat(),
            "is_discount": True, "reason": "concession",
        }
        await _save_pending(ctx.phone, "RENT_CHANGE_WHO", action_data, choices, session)
        return _format_choices_message(search_term, choices, f"apply Rs.{int(amount):,} concession")

    tenant, tenancy, room_obj = rows[0]

    option_choices = [
        {"seq": 1, "label": f"Only {current_month.strftime('%b %Y')} (one month)"},
        {"seq": 2, "label": "Every month (permanent reduction)"},
    ]
    action_data = {
        "tenancy_id": tenancy.id, "tenant_name": tenant.name,
        "new_amount": amount, "month": current_month.isoformat(),
        "is_discount": True, "reason": "concession",
    }
    await _save_pending(ctx.phone, "RENT_CHANGE", action_data, option_choices, session)

    return (
        f"*Concession for {tenant.name}* (Room {room_obj.room_number})\n"
        f"Amount: Rs.{int(amount):,} off\n"
        f"Month: {current_month.strftime('%b %Y')}\n\n"
        f"1. Only {current_month.strftime('%b %Y')}\n"
        f"2. Every month (permanent)\n\n"
        "Reply *1* or *2*."
    )


async def _do_rent_change(
    tenancy_id: int,
    tenant_name: str,
    new_amount: float,
    month_str: str,
    permanent: bool,
    is_discount: bool,
    reason: str,
    session: AsyncSession,
) -> str:
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenancy:
        return "Tenancy record not found."

    try:
        period_month = date.fromisoformat(month_str) if month_str else date.today().replace(day=1)
    except ValueError:
        period_month = date.today().replace(day=1)

    if is_discount:
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy.id,
                RentSchedule.period_month == period_month,
            )
        )
        adj = -Decimal(str(new_amount))
        if rs:
            rs.adjustment = adj
            rs.adjustment_note = reason or "concession"
        else:
            session.add(RentSchedule(
                tenancy_id=tenancy.id,
                period_month=period_month,
                rent_due=tenancy.agreed_rent or Decimal("0"),
                adjustment=adj,
                adjustment_note=reason or "concession",
            ))
        if permanent:
            tenancy.agreed_rent = (tenancy.agreed_rent or Decimal("0")) - Decimal(str(new_amount))
            return (
                f"*Permanent concession applied — {tenant_name}*\n"
                f"Rent reduced by Rs.{int(new_amount):,} every month.\n"
                f"New rent: Rs.{int(tenancy.agreed_rent):,}/month"
            )
        return (
            f"*Concession applied — {tenant_name}*\n"
            f"Rs.{int(new_amount):,} off for {period_month.strftime('%b %Y')} only.\n"
            f"Reason: {reason or 'concession'}"
        )
    else:
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy.id,
                RentSchedule.period_month == period_month,
            )
        )
        old_rent = int(tenancy.agreed_rent or 0)
        if rs:
            rs.rent_due = Decimal(str(new_amount))
            rs.adjustment_note = reason or f"rent change from Rs.{old_rent:,}"
        else:
            session.add(RentSchedule(
                tenancy_id=tenancy.id,
                period_month=period_month,
                rent_due=Decimal(str(new_amount)),
                adjustment_note=f"rent change from Rs.{old_rent:,}",
            ))
        if permanent:
            tenancy.agreed_rent = Decimal(str(new_amount))
            return (
                f"*Rent updated — {tenant_name}*\n"
                f"Was: Rs.{old_rent:,}/month\n"
                f"Now: Rs.{int(new_amount):,}/month (permanent from {period_month.strftime('%b %Y')})"
            )
        return (
            f"*One-time rent change — {tenant_name}*\n"
            f"Rs.{int(new_amount):,} for {period_month.strftime('%b %Y')} only.\n"
            f"Regular rent (Rs.{old_rent:,}) resumes next month."
        )


# ── Add expense prompt ─────────────────────────────────────────────────────────

async def _add_expense_prompt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    amount = entities.get("amount")
    category = entities.get("category")
    description = entities.get("description", "")

    # Both amount and category known — go straight to confirmation
    if amount and category:
        label = category.capitalize()
        pending = PendingAction(
            phone=ctx.phone,
            intent="CONFIRM_ADD_EXPENSE",
            action_data=json.dumps({"amount": amount, "category": category, "description": description}),
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        )
        session.add(pending)
        await session.commit()
        return (
            f"Log expense?\n"
            f"• Category: {label}\n"
            f"• Amount: ₹{int(amount):,}\n\n"
            "Reply *Yes* to confirm or *No* to cancel."
        )

    if amount and not category:
        # Have amount but no category — start step-by-step from category
        await _save_pending(
            ctx.phone, "LOG_EXPENSE_STEP",
            {"step": "ask_category", "amount": amount, "description": description},
            [], session,
        )
        return (
            f"*Expense: Rs.{int(amount):,}*\n\n"
            "*Category?*\n"
            "1. Electricity  2. Water  3. Internet\n"
            "4. Salary  5. Maintenance  6. Groceries\n"
            "7. Other\n\n"
            "Reply with number or name."
        )

    # No amount, no category — full step-by-step
    await _save_pending(
        ctx.phone, "LOG_EXPENSE_STEP",
        {"step": "ask_category", "description": description},
        [], session,
    )
    return (
        "*Log Expense*\n\n"
        "*Category?*\n"
        "1. Electricity  2. Water  3. Internet\n"
        "4. Salary  5. Maintenance  6. Groceries\n"
        "7. Other\n\n"
        "Reply with number or name."
    )


# ── Monthly report ─────────────────────────────────────────────────────────────

async def _report(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    desc = (entities.get("description") or entities.get("_raw_message") or "").lower()
    is_yearly = (
        entities.get("year") and not entities.get("month")
    ) or any(w in desc for w in ("yearly", "annual", "all months", "this year", "full year"))

    if is_yearly:
        return await _yearly_report(entities, session)

    # Single month report
    if entities.get("date"):
        target_month = date.fromisoformat(entities["date"]).replace(day=1)
    elif entities.get("month"):
        today = date.today()
        year = int(entities.get("year") or today.year)
        m = int(entities["month"])
        if not entities.get("year") and date(year, m, 1) > today.replace(day=1):
            year -= 1
        target_month = date(year, m, 1)
    else:
        target_month = date.today().replace(day=1)

    return await _single_month_report(target_month, session)


async def _single_month_report(current_month: date, session: AsyncSession) -> str:
    """Generate detailed report for a single month."""
    from src.database.models import BankTransaction, Refund, RefundStatus

    collected = await session.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.period_month == current_month,
            Payment.for_type == PaymentFor.rent,
            Payment.is_void == False,
        )
    ) or Decimal("0")

    cash_collected = await session.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.period_month == current_month,
            Payment.for_type == PaymentFor.rent,
            Payment.is_void == False,
            Payment.payment_mode == PaymentMode.cash,
        )
    ) or Decimal("0")

    upi_collected = await session.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.period_month == current_month,
            Payment.for_type == PaymentFor.rent,
            Payment.is_void == False,
            Payment.payment_mode == PaymentMode.upi,
        )
    ) or Decimal("0")

    last_day = date(
        current_month.year, current_month.month,
        calendar.monthrange(current_month.year, current_month.month)[1],
    )

    pending = await session.scalar(
        select(func.sum(RentSchedule.rent_due))
        .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
        .where(
            RentSchedule.period_month == current_month,
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
            Tenancy.status == TenancyStatus.active,
            Tenancy.checkin_date <= last_day,
        )
    ) or Decimal("0")

    active_tenants = await session.scalar(
        select(func.count(Tenancy.id)).where(
            Tenancy.status == TenancyStatus.active,
            Tenancy.checkin_date <= last_day,
        )
    ) or 0

    premium_count = await session.scalar(
        select(func.count(Tenancy.id)).where(
            Tenancy.status == TenancyStatus.active,
            Tenancy.sharing_type == SharingType.premium,
            Tenancy.checkin_date <= last_day,
        )
    ) or 0

    no_show = await session.scalar(
        select(func.count(Tenancy.id)).where(
            Tenancy.status == TenancyStatus.no_show,
        )
    ) or 0

    # Expenses — manual (from expenses table)
    manual_expenses = await session.scalar(
        select(func.sum(Expense.amount)).where(
            func.date_trunc("month", Expense.expense_date) == current_month,
            Expense.is_void == False,
        )
    ) or Decimal("0")

    # Expenses — bank statement (from bank_transactions, type=expense)
    bank_expenses = Decimal("0")
    try:
        bank_expenses = await session.scalar(
            select(func.sum(BankTransaction.amount)).where(
                func.date_trunc("month", BankTransaction.txn_date) == current_month,
                BankTransaction.txn_type == "expense",
            )
        ) or Decimal("0")
    except Exception:
        pass  # bank_transactions table may not exist yet

    total_expenses = manual_expenses + bank_expenses

    # Deposits returned (refunds)
    deposits_returned = Decimal("0")
    try:
        deposits_returned = await session.scalar(
            select(func.sum(Refund.amount)).where(
                func.date_trunc("month", Refund.refund_date) == current_month,
                Refund.status == RefundStatus.completed,
            )
        ) or Decimal("0")
    except Exception:
        pass

    regular = active_tenants - premium_count
    active_beds = regular + (premium_count * 2)
    total_beds = 291
    vacant_beds = total_beds - active_beds - no_show
    net_income = int(collected) - int(total_expenses)

    # Vacant beds by building (THOR / HULK)
    from src.database.models import Property
    building_vacant = {}
    try:
        all_rooms = (await session.execute(
            select(Room, Property.name)
            .join(Property, Property.id == Room.property_id)
            .where(Room.active == True, Room.is_staff_room == False)
        )).all()

        occupied_room_ids = {row[0] for row in (await session.execute(
            select(Tenancy.room_id).where(
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                Tenancy.room_id.isnot(None),
            )
        )).all()}

        for room, prop_name in all_rooms:
            if room.id not in occupied_room_ids:
                block = "THOR" if "THOR" in prop_name.upper() else "HULK"
                building_vacant[block] = building_vacant.get(block, 0) + (room.max_occupancy or 1)
    except Exception:
        pass

    thor_vacant = building_vacant.get("THOR", 0)
    hulk_vacant = building_vacant.get("HULK", 0)
    vacant_line = f"  THOR: {thor_vacant} empty | HULK: {hulk_vacant} empty"

    # Expense source note
    exp_source = ""
    if manual_expenses > 0 and bank_expenses > 0:
        exp_source = f"\n  Manual: Rs.{int(manual_expenses):,} | Bank: Rs.{int(bank_expenses):,}"
    elif bank_expenses > 0:
        exp_source = " (from bank statement)"

    deposit_line = ""
    if deposits_returned > 0:
        deposit_line = f"\nDeposits returned: Rs.{int(deposits_returned):,}"

    month_tag = current_month.strftime("%B %Y")

    return (
        f"*Monthly Report — {month_tag}*\n\n"
        f"*Occupancy*\n"
        f"  Occupied: {active_beds} beds"
        + (f" | No-show: {no_show}" if no_show else "")
        + f"\n  Vacant: {vacant_beds} beds\n"
        f"{vacant_line}\n\n"
        f"*Income*\n"
        f"  Cash: Rs.{int(cash_collected):,}\n"
        f"  UPI:  Rs.{int(upi_collected):,}\n"
        f"  Total: Rs.{int(collected):,}\n"
        f"  Pending: Rs.{int(pending):,}\n\n"
        f"*Expenses*\n"
        f"  Total: Rs.{int(total_expenses):,}{exp_source}\n"
        f"{deposit_line}\n"
        f"*Net: Rs.{net_income:,}*\n\n"
        f"Say *empty beds in thor* or *hulk vacant* for room details"
    )


async def _yearly_report(entities: dict, session: AsyncSession) -> str:
    """Generate year-at-a-glance report — all months with cash/UPI/expenses."""
    from src.database.models import BankTransaction, Refund, RefundStatus

    year = int(entities.get("year") or date.today().year)
    today = date.today()

    # Determine which months to show (up to current month for current year)
    if year == today.year:
        max_month = today.month
    else:
        max_month = 12

    lines = [f"*Yearly Report — {year}*\n"]
    total_cash = total_upi = total_pending = total_expenses = total_deposits = 0

    for m in range(1, max_month + 1):
        period = date(year, m, 1)
        month_label = period.strftime("%b")

        cash = int(await session.scalar(
            select(func.sum(Payment.amount)).where(
                Payment.period_month == period,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
                Payment.payment_mode == PaymentMode.cash,
            )
        ) or 0)

        upi = int(await session.scalar(
            select(func.sum(Payment.amount)).where(
                Payment.period_month == period,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
                Payment.payment_mode == PaymentMode.upi,
            )
        ) or 0)

        collected = cash + upi

        last_day = date(year, m, calendar.monthrange(year, m)[1])
        pend = int(await session.scalar(
            select(func.sum(RentSchedule.rent_due))
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .where(
                RentSchedule.period_month == period,
                RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                Tenancy.status == TenancyStatus.active,
                Tenancy.checkin_date <= last_day,
            )
        ) or 0)

        # Expenses (manual + bank)
        exp = int(await session.scalar(
            select(func.sum(Expense.amount)).where(
                func.date_trunc("month", Expense.expense_date) == period,
                Expense.is_void == False,
            )
        ) or 0)
        try:
            bank_exp = int(await session.scalar(
                select(func.sum(BankTransaction.amount)).where(
                    func.date_trunc("month", BankTransaction.txn_date) == period,
                    BankTransaction.txn_type == "expense",
                )
            ) or 0)
            exp += bank_exp
        except Exception:
            pass

        # Deposits returned
        dep_ret = 0
        try:
            dep_ret = int(await session.scalar(
                select(func.sum(Refund.amount)).where(
                    func.date_trunc("month", Refund.refund_date) == period,
                    Refund.status == RefundStatus.completed,
                )
            ) or 0)
        except Exception:
            pass

        net = collected - exp
        total_cash += cash
        total_upi += upi
        total_pending += pend
        total_expenses += exp
        total_deposits += dep_ret

        dep_note = f" | Dep.Ret: {dep_ret//1000}K" if dep_ret > 0 else ""
        lines.append(
            f"*{month_label}* | Cash {cash//1000}K | UPI {upi//1000}K"
            f" | Exp {exp//1000}K{dep_note}"
            f" | Net {net//1000}K"
            + (f" | Pend {pend//1000}K" if pend > 0 else "")
        )

    total_collected = total_cash + total_upi
    total_net = total_collected - total_expenses

    lines.append(f"\n{'─' * 30}")
    lines.append(
        f"*TOTAL*\n"
        f"  Cash: Rs.{total_cash:,}\n"
        f"  UPI:  Rs.{total_upi:,}\n"
        f"  Collected: Rs.{total_collected:,}\n"
        f"  Expenses:  Rs.{total_expenses:,}\n"
        + (f"  Deposits returned: Rs.{total_deposits:,}\n" if total_deposits > 0 else "")
        + f"  Pending: Rs.{total_pending:,}\n"
        f"  *Net Income: Rs.{total_net:,}*"
    )

    return "\n".join(lines)


# ── Query expenses ─────────────────────────────────────────────────────────────

async def _query_expenses(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    raw = (entities.get("_raw_message") or entities.get("description") or "").lower()

    # Detect smart query — needs LLM
    is_smart = any(w in raw for w in (
        "how much", "total", "compare", "breakdown", "category", "yearly",
        "this year", "all time", "trend", "highest", "lowest", "average",
    ))

    if entities.get("date"):
        target_month = date.fromisoformat(entities["date"]).replace(day=1)
    elif entities.get("month"):
        today = date.today()
        m = int(entities["month"])
        year = today.year if date(today.year, m, 1) <= today.replace(day=1) else today.year - 1
        target_month = date(year, m, 1)
    else:
        target_month = date.today().replace(day=1)

    # For smart queries, search wider range
    if is_smart and "year" in raw:
        search_start = date(date.today().year, 1, 1)
        search_end = date.today()
        label = str(date.today().year)
    elif is_smart:
        search_start = date(2025, 1, 1)
        search_end = date.today()
        label = "all time"
    else:
        search_start = target_month
        last_day = calendar.monthrange(target_month.year, target_month.month)[1]
        search_end = date(target_month.year, target_month.month, last_day)
        label = target_month.strftime('%B %Y')

    result = await session.execute(
        select(Expense)
        .options(selectinload(Expense.category))
        .where(
            Expense.expense_date >= search_start,
            Expense.expense_date <= search_end,
            Expense.is_void == False,
        )
        .order_by(Expense.expense_date.desc())
    )
    expenses = result.scalars().all()

    if not expenses:
        return f"No expenses recorded for {label}."

    # Smart query — use Groq
    if is_smart and len(expenses) > 0:
        log_lines = []
        for e in expenses:
            cat = e.category.name if e.category else "Other"
            log_lines.append(
                f"{e.expense_date.strftime('%d %b %Y')}: {cat} Rs.{int(e.amount):,}"
                + (f" — {e.description[:50]}" if e.description else "")
            )
        try:
            from src.llm_gateway.claude_client import get_claude_client
            ai = get_claude_client()
            answer = await ai.answer_from_logs(raw, log_lines, "expense")
            if answer:
                total = sum(e.amount for e in expenses)
                return (
                    f"*Expense Query* ({len(expenses)} records, {label})\n"
                    f"Total: Rs.{int(total):,}\n\n{answer}"
                )
        except Exception:
            pass  # fall through to simple list

    # Simple list
    total = sum(e.amount for e in expenses)
    lines = [f"*Expenses — {label}*\n"]
    for e in expenses[:30]:
        cat = e.category.name if e.category else str(e.category_id or "Other")
        lines.append(
            f"• {e.expense_date.strftime('%d %b')} {cat.title()}: Rs.{int(e.amount):,}"
            + (f" ({e.description[:30]})" if e.description else "")
        )
    if len(expenses) > 30:
        lines.append(f"\n_...and {len(expenses) - 30} more_")
    lines.append(f"\n*Total: Rs.{int(total):,}*")
    return "\n".join(lines)


# ── Query pending refunds ──────────────────────────────────────────────────────

async def _query_refunds(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    result = await session.execute(
        select(Tenant.name, Refund, Room.room_number)
        .join(Tenancy, Tenancy.id == Refund.tenancy_id)
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(Refund.status == RefundStatus.pending)
        .order_by(Refund.created_at.desc())
    )
    rows = result.all()
    if not rows:
        return "No pending deposit refunds."
    lines = ["*Pending Refunds*\n"]
    total = 0
    for name, refund, room_num in rows:
        lines.append(f"• {name} (Room {room_num}): Rs.{int(refund.amount):,}")
        if refund.reason:
            lines[-1] += f" — {refund.reason[:40]}"
        total += int(refund.amount)
    lines.append(f"\n*Total pending: Rs.{total:,}*")
    return "\n".join(lines)


# ── Add refund ─────────────────────────────────────────────────────────────────

async def _add_refund(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name   = entities.get("name", "").strip()
    room   = entities.get("room", "").strip()
    amount = entities.get("amount")

    if not amount:
        return (
            "How much to refund?\n"
            "Say: *refund [Name] [amount]*\n"
            "Example: *refund Raj 15000 deposit*"
        )

    if not name and not room:
        return (
            f"Which tenant's refund of Rs.{int(amount):,}?\n"
            "Say: *refund [Name] [amount]*\n"
            "Example: *refund Raj 15000 deposit*"
        )

    rows: list = []
    if name:
        rows = await _find_active_tenants_by_name(name, session)
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)

    # Also search exited tenants for deposit refund
    if not rows and name:
        result = await session.execute(
            select(Tenant, Tenancy, Room)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Tenant.name.ilike(f"%{name}%"),
                Tenancy.status == TenancyStatus.exited,
            )
            .order_by(Tenancy.checkout_date.desc())
        )
        rows = result.all()

    if not rows:
        return _format_no_match_message(name or room)

    tenant, tenancy, room_obj = rows[0]
    refund = Refund(
        tenancy_id=tenancy.id,
        amount=Decimal(str(amount)),
        refund_date=date.today(),
        reason="deposit refund",
        status=RefundStatus.pending,
        notes=f"Logged via WhatsApp by {ctx.name or ctx.phone}",
    )
    session.add(refund)
    return (
        f"*Refund recorded — {tenant.name}*\n"
        f"Amount: Rs.{int(amount):,}\n"
        f"Status: Pending\n\n"
        "Mark as processed once payment is sent."
    )


# ── Fallback ───────────────────────────────────────────────────────────────────

async def _unknown_financial(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    return (
        "I couldn't handle that financial request.\n\n"
        "Try:\n"
        "• *[Name] paid [amount]*\n"
        "• *Who hasn't paid?*\n"
        "• *[Name] balance*\n"
        "• *Monthly report*\n"
        "• *help* for full menu"
    )
