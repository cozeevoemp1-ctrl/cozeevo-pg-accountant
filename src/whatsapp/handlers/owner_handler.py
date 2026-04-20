"""
Owner handler.
Processes intents for admin, owner, receptionist roles.

Disambiguation flow:
  - Fuzzy name search → 0 results  → suggest similar names, save pending action
  - Fuzzy name search → 1 result   → confirm inline, proceed
  - Fuzzy name search → 2+ results → numbered list, save pending action
  - User replies "1" / "2" / "yes" → chat_api resolves via resolve_pending_action()
"""
from __future__ import annotations

import asyncio
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
    build_dues_snapshot, compute_allocation, format_allocation,
)
from src.whatsapp.handlers.account_handler import (
    _calc_outstanding_dues,       # needed by _room_status + _do_checkout
)
from src.whatsapp.handlers.update_handler import (
    update_sharing_type as _update_sharing_type,
    update_rent as _update_rent,
    update_phone as _update_phone,
    update_gender as _update_gender,
    update_room as _update_room,
    resolve_field_update as _resolve_field_update,
    query_audit as _query_audit,
    query_rent_history as _query_rent_history,
    query_staff_rooms as _query_staff_rooms,
    assign_staff_to_room as _assign_staff_to_room,
    exit_staff_from_room as _exit_staff_from_room,
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
        "UPDATE_CHECKOUT_DATE": _update_checkout_date,
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
        "UPDATE_TENANT_NOTES": _update_tenant_notes,
        "QUERY_CONTACTS":     _query_contacts,
        "ADD_CONTACT":        _add_contact,
        "UPDATE_CONTACT":     _update_contact,
        "ACTIVITY_LOG":       _activity_log,
        "QUERY_ACTIVITY":     _query_activity,
        "RULES":              _rules,
        "HELP":               _help,
        "MORE_MENU":          _more_menu,
        "UPDATE_SHARING_TYPE": _update_sharing_type,
        "UPDATE_RENT":        _update_rent,
        "UPDATE_PHONE":       _update_phone,
        "UPDATE_GENDER":      _update_gender,
        "UPDATE_ROOM":        _update_room,
        "QUERY_AUDIT":        _query_audit,
        "QUERY_RENT_HISTORY": _query_rent_history,
        "QUERY_STAFF_ROOMS":  _query_staff_rooms,
        "ASSIGN_STAFF_ROOM":  _assign_staff_to_room,
        "EXIT_STAFF":         _exit_staff_from_room,
        "CHANGE_ROOM":        _room_transfer_prompt,  # alias for ROOM_TRANSFER
        "ASSIGN_ROOM":        _assign_room_prompt,
        "QUERY_UNHANDLED":    _query_unhandled,
        "UNKNOWN":            _unknown,
    }
    fn = handlers.get(intent, _unknown)
    return await fn(entities, ctx, session)


# ── Pending action resolver (called from chat_api before intent detection) ────

async def resolve_pending_action(
    pending: PendingAction, reply_text: str, session: AsyncSession,
    media_id: str | None = None, media_type: str | None = None, media_mime: str | None = None,
) -> Optional[str]:
    """
    Called when the user replies to a disambiguation question.
    Returns the final reply string, or None if the reply wasn't a valid choice.
    """
    # Lazy imports to avoid circular import at module load time
    from src.whatsapp.handlers.account_handler import (
        _do_log_payment_by_ids, _do_void_payment, _do_rent_change, _do_query_tenant_by_id,
    )
    reply_text = reply_text.strip()
    choices = json.loads(pending.choices or "[]")
    action_data = json.loads(pending.action_data or "{}")
    # Handle double-serialized action_data (legacy bug: json.dumps called twice)
    if isinstance(action_data, str):
        try:
            action_data = json.loads(action_data)
        except (json.JSONDecodeError, TypeError):
            action_data = {}

    # Parse user's choice: "1", "2", "1." etc.
    chosen_idx = None
    if reply_text.rstrip(".").isdigit():
        num = int(reply_text.rstrip("."))
        if 1 <= num <= len(choices):
            chosen_idx = num - 1

    # ── Multi-step text-based flows — handled BEFORE numeric check ───────────

    # ── Onboarding approval (highest priority) ────────────────────────────
    if pending.intent == "APPROVE_ONBOARDING":
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
                import asyncio as _aio
                from src.integrations.gsheets import sync_tenant_all_fields as _sta
                _aio.create_task(_sta(tenant.id))
            except Exception:
                pass

            # Mark onboarding complete
            from src.database.models import OnboardingSession
            ob = await session.get(OnboardingSession, onboarding_id)
            if ob:
                ob.completed = True
                ob.step = "done"

            # Notify tenant
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp
                await _send_whatsapp(tenant.phone, f"Your check-in has been approved! Welcome to Cozeevo, {tenant.name}.")
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

        elif ans in ("no", "n", "reject", "2"):
            from src.database.models import OnboardingSession
            ob = await session.get(OnboardingSession, action_data.get("onboarding_id"))
            if ob:
                ob.completed = True
                ob.step = "rejected"

            tenant = await session.get(Tenant, action_data.get("tenant_id"))
            if tenant:
                try:
                    from src.whatsapp.webhook_handler import _send_whatsapp
                    await _send_whatsapp(tenant.phone, "Your check-in request was not approved. Please contact the reception.")
                except Exception:
                    pass

            return "Onboarding rejected."

        else:
            return "__KEEP_PENDING__Reply *yes* to approve or *no* to reject."

    # ── Helper: after gender resolved, check food → advance → sharing ───
    async def _next_form_step(action_data, extracted, pending, session):
        """Chain: food (if missing) → advance (if missing) → sharing."""
        from src.whatsapp.handlers._shared import _save_pending

        # 1. Food
        food_val = (extracted.get("food_preference") or "").strip().lower()
        if not food_val or food_val in ("", "none", "skip"):
            action_data["step"] = "ask_food_form"
            await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
            return "*Food preference?*\n\n*1.* Veg\n*2.* Non-veg\n*3.* Egg\n\nOr type *skip*"

        # 2. Advance (amount + mode)
        advance_val = extracted.get("advance", "")
        if not advance_val or str(advance_val).strip().lower() in ("", "0", "skip", "none"):
            action_data["step"] = "ask_advance_form"
            await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
            deposit_s = extracted.get("deposit", "0")
            deposit_amt = int(re.sub(r"[^0-9]", "", str(deposit_s)) or "0")
            deposit_note = f" (deposit: Rs.{deposit_amt:,})" if deposit_amt else ""
            return f"*Any advance paid at check-in?*{deposit_note}\n\nEnter amount, *full* if fully paid, or *0* / *skip* if none."

        # 2b. Advance mode (cash/upi)
        advance_mode = extracted.get("advance_mode", "")
        if not advance_mode:
            action_data["step"] = "ask_advance_mode_form"
            await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
            return f"Advance: Rs.{advance_val}\n\n*Cash or UPI?*"

        # 3. Sharing
        return await _goto_sharing(action_data, pending, session)

    async def _goto_sharing(action_data, pending, session):
        """Transition to sharing type confirmation."""
        from src.whatsapp.handlers._shared import _save_pending
        rt_str = action_data.get("room_type", "double")
        max_occ = action_data.get("max_occupancy", 2)
        current_occ = action_data.get("current_occupants", 0)
        room_num = action_data.get("room_number", "?")

        action_data["step"] = "confirm_sharing"
        await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)

        if rt_str == "single":
            return await _finalize_form_checkin(action_data, pending, session, sharing_type="single")

        return (
            f"*Room {room_num}* — {rt_str} sharing room ({current_occ}/{max_occ} occupied)\n\n"
            f"Checking in as:\n"
            f"*1.* {rt_str.title()} sharing\n"
            f"*2.* Premium (single occupancy — all beds)\n\n"
            f"Reply *1* or *2*"
        )

    # ── Form image extraction confirmation ────────────────────────────────
    if pending.intent == "FORM_EXTRACT_CONFIRM":
        from src.whatsapp.form_extractor import format_extracted_data
        from src.whatsapp.handlers._shared import _save_pending
        ans = reply_text.strip().lower()
        step = action_data.get("step", "")

        if ans in ("no", "n", "cancel", "abort"):
            pending.resolved = True
            return "Cancelled. Tenant not added."

        # ── Edit a field ──────────────────────────────────────────────────
        if ans.startswith("edit ") or "\nedit " in reply_text.lower():
            # Multi-edit support: parse each line starting with "edit"
            key_aliases = {
                "name": "name", "phone": "phone", "room": "room_number",
                "room_number": "room_number", "gender": "gender",
                "rent": "monthly_rent", "monthly_rent": "monthly_rent",
                "deposit": "deposit", "maintenance": "maintenance",
                "checkin": "date_of_admission", "date_of_admission": "date_of_admission",
                "dob": "date_of_birth", "date_of_birth": "date_of_birth",
                "father": "father_name", "father_name": "father_name",
                "father_phone": "father_phone",
                "address": "permanent_address", "permanent_address": "permanent_address",
                "emergency": "emergency_contact", "emergency_contact": "emergency_contact",
                "relationship": "emergency_relationship",
                "email": "email", "mail": "email", "mail_id": "email",
                "occupation": "occupation", "employee": "occupation", "company": "occupation",
                "id_type": "id_proof_type", "id_number": "id_proof_number",
                "id_proof": "id_proof_number", "id": "id_proof_number",
                "food": "food_preference", "food_preference": "food_preference",
                "education": "educational_qualification", "educational_qualification": "educational_qualification",
                "office_address": "office_address", "office": "office_address",
                "office_phone": "office_phone",
                "rent_remarks": "rent_remarks", "rent_terms": "rent_remarks",
                "deposit_remarks": "deposit_remarks", "deposit_terms": "deposit_remarks",
                "maintenance_remarks": "maintenance_remarks", "maint_terms": "maintenance_remarks",
            }

            extracted = action_data.get("extracted", {})
            edits_made = []
            errors = []

            # Parse each line
            for line in reply_text.strip().splitlines():
                line = line.strip()
                if not line.lower().startswith("edit "):
                    continue
                raw = line[5:].strip()  # skip "edit "
                parts = raw.split(None, 1)
                if len(parts) < 2:
                    continue
                field_key = parts[0].lower().rstrip(":")
                new_val = parts[1].lstrip(": ").strip()
                actual_key = key_aliases.get(field_key)
                if actual_key:
                    extracted[actual_key] = new_val
                    edits_made.append(field_key)
                else:
                    errors.append(field_key)

            if not edits_made and not errors:
                return "__KEEP_PENDING__Format: *edit field_name new_value*\nExample: *edit name Rahul Sharma*"

            action_data["extracted"] = extracted
            await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)

            msg = format_extracted_data(extracted, "")
            if errors:
                msg += f"\n\nUnknown fields (skipped): {', '.join(errors)}"
            msg += "\n\nReply *yes* to save, *no* to cancel."
            msg += "\nTo edit more: *edit field_name new_value*"
            return msg

        # ── Confirm and save — run room validation first ────────────────
        if step == "confirm_extracted" and ans in ("yes", "y", "confirm", "save", "ok", "done"):
            extracted = action_data.get("extracted", {})

            # Validate room exists
            room_str = extracted.get("room_number", "")
            room_row = await session.scalar(select(Room).where(Room.room_number.ilike(room_str)))
            if not room_row:
                similar_res = await session.execute(
                    select(Room).where(Room.room_number.ilike(f"%{room_str}%")).limit(5)
                )
                similar = [r.room_number for r in similar_res.scalars().all()]
                hint = f"\nDid you mean: {', '.join(f'*{r}*' for r in similar)}?" if similar else ""
                return f"__KEEP_PENDING__Room *{room_str}* not found.{hint}\n\nUse *edit room T-201* to correct."

            # Check duplicate phone
            phone_raw = extracted.get("phone", "")
            phone_clean = re.sub(r"[^0-9]", "", phone_raw)
            if len(phone_clean) > 10:
                phone_clean = phone_clean[-10:]
            if phone_clean and len(phone_clean) == 10:
                existing = await session.scalar(select(Tenant).where(Tenant.phone == phone_clean))
                if existing:
                    active_tncy = await session.scalar(
                        select(Tenancy).where(Tenancy.tenant_id == existing.id, Tenancy.status == TenancyStatus.active)
                    )
                    if active_tncy:
                        r2 = await session.get(Room, active_tncy.room_id)
                        return (f"__KEEP_PENDING__Phone *{phone_clean}* already belongs to *{existing.name}* "
                                f"(active in Room {r2.room_number if r2 else '?'}).\n\n"
                                "Checkout that tenant first, or *edit phone* to correct.")

            # Check room occupancy
            active_res = await session.execute(
                select(Tenancy).where(Tenancy.room_id == room_row.id, Tenancy.status == TenancyStatus.active)
            )
            occupants = active_res.scalars().all()
            max_occ = room_row.max_occupancy or 1
            rt = room_row.room_type
            rt_str = rt.value if hasattr(rt, 'value') else str(rt or "")

            if len(occupants) >= max_occ:
                # Room full — offer checkout option
                occ_lines = []
                for i, tncy in enumerate(occupants, 1):
                    t = await session.get(Tenant, tncy.tenant_id)
                    checkin_str = tncy.checkin_date.strftime('%d %b %Y') if tncy.checkin_date else "?"
                    occ_lines.append(f"*{i}.* {t.name} (since {checkin_str})")

                action_data["step"] = "resolve_room_full"
                action_data["room_id"] = room_row.id
                action_data["room_number"] = room_row.room_number
                action_data["room_type"] = rt_str
                action_data["max_occupancy"] = max_occ
                action_data["occupant_tenancies"] = [
                    {"tenancy_id": tncy.id, "tenant_id": tncy.tenant_id}
                    for tncy in occupants
                ]
                await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)

                return (
                    f"*Room {room_row.room_number} is full* ({len(occupants)}/{max_occ} — {rt_str} sharing)\n\n"
                    + "\n".join(occ_lines) + "\n\n"
                    "*What would you like to do?*\n\n"
                    "*1.* Checkout existing tenant & proceed\n"
                    "*2.* Use a different room\n"
                    "*3.* Cancel"
                )

                # Note: step stays as "resolve_room_full", handled below

            # Gender — ALWAYS require it. If not in form, ask before proceeding.
            gender_s = extracted.get("gender", "").lower()
            if not gender_s:
                action_data["step"] = "ask_gender_form"
                action_data["room_id"] = room_row.id
                action_data["room_number"] = room_row.room_number
                action_data["room_type"] = rt_str
                action_data["max_occupancy"] = max_occ
                action_data["current_occupants"] = len(occupants)
                await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                return f"*Gender not found in form.* Please enter: *male* or *female*"

            if gender_s and occupants:
                occ_t_ids = [tncy.tenant_id for tncy in occupants]
                occ_g_res = await session.execute(select(Tenant.gender).where(Tenant.id.in_(occ_t_ids)))
                occ_genders = [g for g in occ_g_res.scalars().all() if g]
                if occ_genders and any(g != gender_s for g in occ_genders):
                    action_data["step"] = "confirm_gender_mismatch"
                    action_data["room_id"] = room_row.id
                    action_data["room_number"] = room_row.room_number
                    action_data["room_type"] = rt_str
                    await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                    return (
                        f"*Gender mismatch:* New tenant is *{gender_s}*, "
                        f"existing occupant(s) in Room {room_row.room_number} are *{', '.join(set(occ_genders))}*.\n\n"
                        "Reply *yes* to proceed anyway, *edit room* to change room, or *no* to cancel."
                    )

            # Room has space — ask advance if not in form, then sharing
            action_data["room_id"] = room_row.id
            action_data["room_number"] = room_row.room_number
            action_data["room_type"] = rt_str
            action_data["max_occupancy"] = max_occ
            action_data["current_occupants"] = len(occupants)

            # Chain: food → advance → sharing (via helper)
            return await _next_form_step(action_data, extracted, pending, session)

        # ── Gender prompt from form extraction ──────────────────────────
        if step == "ask_gender_form":
            g = ans.strip().lower()
            if g in ("male", "m", "boy", "man", "gents"):
                extracted = action_data.get("extracted", {})
                extracted["gender"] = "male"
                action_data["extracted"] = extracted
            elif g in ("female", "f", "girl", "woman", "ladies"):
                extracted = action_data.get("extracted", {})
                extracted["gender"] = "female"
                action_data["extracted"] = extracted
            else:
                return "__KEEP_PENDING__Please enter *male* or *female*:"

            # Resume: go to sharing type confirmation
            room_row = await session.get(Room, action_data["room_id"])
            rt_str = action_data.get("room_type", "double")
            max_occ = action_data.get("max_occupancy", 1)
            current_occ = action_data.get("current_occupants", 0)

            # Check gender mismatch with existing occupants
            if current_occ > 0:
                active_res = await session.execute(
                    select(Tenancy).where(Tenancy.room_id == room_row.id, Tenancy.status == TenancyStatus.active)
                )
                occupants = active_res.scalars().all()
                occ_t_ids = [tncy.tenant_id for tncy in occupants]
                occ_g_res = await session.execute(select(Tenant.gender).where(Tenant.id.in_(occ_t_ids)))
                occ_genders = [gg for gg in occ_g_res.scalars().all() if gg]
                gender_s = extracted["gender"]
                if occ_genders and any(gg != gender_s for gg in occ_genders):
                    action_data["step"] = "confirm_gender_mismatch"
                    await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                    return (
                        f"*Gender mismatch:* New tenant is *{gender_s}*, "
                        f"existing occupant(s) in Room {room_row.room_number} are *{', '.join(set(occ_genders))}*.\n\n"
                        "Reply *yes* to proceed anyway, *edit room* to change room, or *no* to cancel."
                    )

            # Chain: food → advance → sharing (via helper)
            return await _next_form_step(action_data, extracted, pending, session)

        # ── Food preference prompt from form extraction ────────────────
        if step == "ask_food_form":
            extracted = action_data.get("extracted", {})
            f = ans.strip().lower()
            if f in ("skip", "none", "na", "no", "-", "4"):
                extracted["food_preference"] = ""
            elif f in ("1", "veg"):
                extracted["food_preference"] = "veg"
            elif f in ("2", "non-veg", "nonveg", "non veg"):
                extracted["food_preference"] = "non-veg"
            elif "non" in f:
                extracted["food_preference"] = "non-veg"
            elif f in ("3", "egg"):
                extracted["food_preference"] = "egg"
            elif "egg" in f:
                extracted["food_preference"] = "egg"
            elif "veg" in f:
                extracted["food_preference"] = "veg"
            else:
                return "__KEEP_PENDING__Please enter *1* (Veg), *2* (Non-veg), *3* (Egg), or *skip*:"
            action_data["extracted"] = extracted
            # Continue chain: advance → sharing
            return await _next_form_step(action_data, extracted, pending, session)

        # ── Advance payment prompt from form extraction ────────────────
        if step == "ask_advance_form":
            extracted = action_data.get("extracted", {})
            deposit_s = extracted.get("deposit", "0")
            deposit_amt = int(re.sub(r"[^0-9]", "", str(deposit_s)) or "0")

            a = ans.strip().lower()
            if a in ("skip", "none", "no", "nil", "0"):
                extracted["advance"] = "0"
                extracted["advance_mode"] = ""  # no advance, no mode needed
                action_data["extracted"] = extracted
                # Continue chain: sharing
                return await _next_form_step(action_data, extracted, pending, session)
            elif a in ("full", "all", "complete", "paid", "yes"):
                extracted["advance"] = str(deposit_amt) if deposit_amt else "0"
            else:
                amt_str = re.sub(r"[^0-9]", "", a)
                if not amt_str:
                    return "__KEEP_PENDING__Enter an amount, *full*, or *0* / *skip*."
                extracted["advance"] = amt_str

            action_data["extracted"] = extracted
            # Ask payment mode
            action_data["step"] = "ask_advance_mode_form"
            await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
            return f"Advance: Rs.{extracted['advance']}\n\n*Cash or UPI?*"

        if step == "ask_advance_mode_form":
            extracted = action_data.get("extracted", {})
            m = ans.strip().lower()
            if m in ("cash", "c", "1"):
                extracted["advance_mode"] = "cash"
            elif m in ("upi", "u", "2", "online", "gpay", "phonepe", "paytm"):
                extracted["advance_mode"] = "upi"
            else:
                return "__KEEP_PENDING__*Cash or UPI?*"
            action_data["extracted"] = extracted
            # Continue chain: sharing
            return await _next_form_step(action_data, extracted, pending, session)

        # ── Resolve room full — step 1: pick action ─────────────────────
        if step == "resolve_room_full":
            if ans == "1":
                # Checkout existing tenant — ask which one (or go straight to date if only 1)
                occupant_list = action_data.get("occupant_tenancies", [])
                if len(occupant_list) == 1:
                    occ = occupant_list[0]
                    t = await session.get(Tenant, occ["tenant_id"])
                    action_data["step"] = "ask_checkout_date"
                    action_data["checkout_idx"] = 0
                    await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                    return (
                        f"Checking out *{t.name}*\n\n"
                        f"*When did they leave?*\n\n"
                        f"*1.* Today\n"
                        f"*2.* Type a date (e.g. 03 April)"
                    )
                else:
                    # Multiple occupants — ask which one
                    lines = ["*Who is checking out?*\n"]
                    for i, occ in enumerate(occupant_list, 1):
                        t = await session.get(Tenant, occ["tenant_id"])
                        lines.append(f"*{i}.* {t.name}")
                    action_data["step"] = "pick_checkout_occupant"
                    await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                    return "\n".join(lines)

            elif ans == "2":
                # Different room
                action_data["step"] = "ask_new_room"
                await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                return "*Which room?* (e.g. T-201)"

            elif ans == "3":
                pending.resolved = True
                return "Cancelled. Tenant not added."

            return "__KEEP_PENDING__Reply *1*, *2*, or *3*."

        # ── Pick which occupant to checkout ───────────────────────────────
        if step == "pick_checkout_occupant":
            occupant_list = action_data.get("occupant_tenancies", [])
            if ans.rstrip(".").isdigit():
                idx = int(ans.rstrip(".")) - 1
                if 0 <= idx < len(occupant_list):
                    t = await session.get(Tenant, occupant_list[idx]["tenant_id"])
                    action_data["step"] = "ask_checkout_date"
                    action_data["checkout_idx"] = idx
                    await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                    return (
                        f"Checking out *{t.name}*\n\n"
                        f"*When did they leave?*\n\n"
                        f"*1.* Today\n"
                        f"*2.* Type a date (e.g. 03 April)"
                    )
            return f"__KEEP_PENDING__Reply with a number (1-{len(occupant_list)})."

        # ── Ask checkout date ─────────────────────────────────────────────
        if step == "ask_checkout_date":
            from src.whatsapp.intent_detector import _extract_date_entity
            occupant_list = action_data.get("occupant_tenancies", [])
            idx = action_data.get("checkout_idx", 0)

            if ans == "1" or ans.lower() in ("today", "now"):
                exit_iso = date.today().isoformat()
            else:
                exit_iso = _extract_date_entity(reply_text.strip())

            if not exit_iso:
                return "__KEEP_PENDING__Could not read that date.\nTry: *today* or *03 April* or *31/03/2026*"

            exit_date = date.fromisoformat(exit_iso)
            occ = occupant_list[idx]
            tenancy = await session.get(Tenancy, occ["tenancy_id"])
            tenant = await session.get(Tenant, occ["tenant_id"])

            if tenancy:
                tenancy.status = TenancyStatus.exited
                tenancy.checkout_date = exit_date
                checkout_name = tenant.name if tenant else "Tenant"

                action_data["step"] = "confirm_extracted"
                await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                return (
                    f"*{checkout_name}* checked out ({exit_date.strftime('%d %b %Y')})\n\n"
                    f"Room {action_data.get('room_number', '')} now has space.\n"
                    f"Reply *yes* to proceed with new check-in."
                )

            return "__KEEP_PENDING__Something went wrong. Try again or say *no* to cancel."

        # ── Ask for new room ──────────────────────────────────────────────
        if step == "ask_new_room":
            new_room = reply_text.strip()
            if new_room:
                extracted = action_data.get("extracted", {})
                extracted["room_number"] = new_room
                action_data["extracted"] = extracted
                action_data["step"] = "confirm_extracted"
                await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                return f"Room changed to *{new_room}*.\nReply *yes* to proceed."
            return "__KEEP_PENDING__Please type the room number (e.g. T-201)."

        # ── Gender mismatch confirmation ──────────────────────────────────
        if step == "confirm_gender_mismatch":
            if ans in ("yes", "y", "proceed", "ok"):
                extracted = action_data.get("extracted", {})
                # Chain: food → advance → sharing (via helper)
                return await _next_form_step(action_data, extracted, pending, session)
            if ans.startswith("edit room"):
                new_room = ans.replace("edit room", "").strip()
                if new_room:
                    extracted = action_data.get("extracted", {})
                    extracted["room_number"] = new_room
                    action_data["extracted"] = extracted
                    action_data["step"] = "confirm_extracted"
                    await _save_pending(pending.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)
                    return f"__KEEP_PENDING__Room changed to *{new_room}*. Reply *yes* to proceed."
            return "__KEEP_PENDING__Reply *yes* to proceed, *edit room T-201* to change, or *no* to cancel."

        # ── Sharing type confirmation ─────────────────────────────────────
        if step == "confirm_sharing":
            rt_str = action_data.get("room_type", "double")
            if ans in ("1", rt_str, "sharing", "shared"):
                return await _finalize_form_checkin(action_data, pending, session, sharing_type=rt_str)
            elif ans in ("2", "premium", "single", "solo"):
                return await _finalize_form_checkin(action_data, pending, session, sharing_type="premium")
            return f"__KEEP_PENDING__Reply *1* for {rt_str} sharing or *2* for premium (single occupancy)."

        if step == "confirm_extracted":
            return "__KEEP_PENDING__Reply *yes* to save, *no* to cancel, or *edit field_name value* to correct."

    # ── Checkout form extraction confirmation ────────────────────────────
    if pending.intent == "CHECKOUT_FORM_CONFIRM":
        from src.whatsapp.form_extractor import format_checkout_data
        from src.whatsapp.handlers._shared import _save_pending
        ans = reply_text.strip().lower()
        step = action_data.get("step", "")

        if ans in ("no", "n", "cancel", "abort"):
            pending.resolved = True
            return "Checkout cancelled."

        # Edit a field
        if ans.startswith("edit "):
            raw_edit = reply_text.strip()[5:].strip()
            parts = raw_edit.split(None, 1)
            if len(parts) < 2:
                return "__KEEP_PENDING__Format: *edit field_name new_value*"

            field_key = parts[0].lower()
            new_val = parts[1].strip()

            key_aliases = {
                "name": "name", "phone": "phone", "room": "room_number",
                "room_number": "room_number",
                "checkout_date": "checkout_date", "date": "checkout_date",
                "deposit": "security_deposit", "security_deposit": "security_deposit",
                "deductions": "deductions", "deduction": "deductions",
                "reason": "deductions_reason",
                "refund": "refund_amount", "refund_amount": "refund_amount",
                "refund_mode": "refund_mode", "mode": "refund_mode",
                "room_check": "room_investigation", "investigation": "room_investigation",
                "room_key": "room_key_returned", "wardrobe_key": "wardrobe_key_returned",
                "biometric": "biometric_removed",
            }

            actual_key = key_aliases.get(field_key)
            if not actual_key:
                return f"__KEEP_PENDING__Unknown field *{field_key}*. Try: name, room, date, deposit, deductions, refund, mode, room_key, wardrobe_key, biometric"

            extracted = action_data.get("extracted", {})
            extracted[actual_key] = new_val
            action_data["extracted"] = extracted
            await _save_pending(pending.phone, "CHECKOUT_FORM_CONFIRM", action_data, [], session)

            msg = format_checkout_data(extracted, "")
            msg += "\n\nReply *yes* to process, *no* to cancel."
            msg += "\nTo edit: *edit field_name new_value*"
            return msg

        # Confirm and process checkout
        if step == "confirm_checkout_extracted" and ans in ("yes", "y", "confirm", "ok", "done"):
            extracted = action_data.get("extracted", {})

            # Find the tenant
            name = extracted.get("name", "")
            room_str = extracted.get("room_number", "")
            phone_raw = extracted.get("phone", "")

            # Search by name first, then room
            rows = await _find_active_tenants_by_name(name, session) if name else []
            if not rows and room_str:
                rows = await _find_active_tenants_by_room(room_str, session)
            if not rows and phone_raw:
                phone_clean = re.sub(r"[^0-9]", "", phone_raw)
                if len(phone_clean) > 10:
                    phone_clean = phone_clean[-10:]
                if phone_clean:
                    t = await session.scalar(select(Tenant).where(Tenant.phone.like(f"%{phone_clean}")))
                    if t:
                        tncy = await session.scalar(
                            select(Tenancy).where(Tenancy.tenant_id == t.id, Tenancy.status == TenancyStatus.active)
                        )
                        if tncy:
                            r = await session.get(Room, tncy.room_id)
                            rows = [(t, tncy, r)]

            if not rows:
                return f"__KEEP_PENDING__No active tenant found for *{name}* / Room *{room_str}*.\nUse *edit name* or *edit room* to correct."

            if len(rows) > 1:
                lines = ["Multiple matches:\n"]
                for i, (t, tncy, rm) in enumerate(rows, 1):
                    lines.append(f"*{i}.* {t.name} — Room {rm.room_number}")
                action_data["step"] = "pick_checkout_tenant"
                action_data["candidates"] = [
                    {"tenant_id": t.id, "tenancy_id": tncy.id, "name": t.name, "room": rm.room_number}
                    for t, tncy, rm in rows
                ]
                await _save_pending(pending.phone, "CHECKOUT_FORM_CONFIRM", action_data, [], session)
                return "\n".join(lines) + "\n\nReply with number."

            # Single match — process checkout
            tenant, tenancy, room_obj = rows[0]
            return await _process_checkout_from_form(
                extracted, tenant, tenancy, room_obj, action_data, pending, session,
            )

        if step == "pick_checkout_tenant":
            candidates = action_data.get("candidates", [])
            if ans.rstrip(".").isdigit():
                idx = int(ans.rstrip(".")) - 1
                if 0 <= idx < len(candidates):
                    c = candidates[idx]
                    tenant = await session.get(Tenant, c["tenant_id"])
                    tenancy = await session.get(Tenancy, c["tenancy_id"])
                    room_obj = await session.get(Room, tenancy.room_id)
                    extracted = action_data.get("extracted", {})
                    return await _process_checkout_from_form(
                        extracted, tenant, tenancy, room_obj, action_data, pending, session,
                    )
            return f"__KEEP_PENDING__Reply with a number (1-{len(candidates)})."

        if step == "confirm_checkout_extracted":
            return "__KEEP_PENDING__Reply *yes* to process checkout, *no* to cancel, or *edit field value*."

    # ── Document collection (ID proofs + rules page after check-in) ───────
    if pending.intent == "COLLECT_DOCS":
        from src.whatsapp.handlers._shared import _save_pending
        ans = reply_text.strip().lower()

        if ans in ("done", "finish", "finished", "that's all", "thats all", "complete", "skip"):
            docs_count = action_data.get("docs_saved", 0)
            pending.resolved = True
            return f"Documents saved ({docs_count} total) for {action_data.get('tenant_name', 'tenant')}."

        if ans in ("cancel", "abort", "no"):
            pending.resolved = True
            return "Document collection cancelled."

        # Image received — save it
        if media_id and media_type == "image":
            from src.whatsapp.webhook_handler import _fetch_media_bytes
            from src.whatsapp.media_handler import MEDIA_DIR
            from src.database.models import Document, DocumentType
            from pathlib import Path

            img_bytes = await _fetch_media_bytes(media_id)
            if not img_bytes:
                return "__KEEP_PENDING__Could not download. Please resend the image."

            # Determine doc type: rules page or ID proof
            # Rules page detection: check image size and use simple heuristic
            # Rules pages are typically the 2nd page with "RULES & REGULATIONS" header
            # For efficiency, we check if user caption hints at it, otherwise default to id_proof
            caption = reply_text.strip().lower()
            if any(w in caption for w in ("rule", "sign", "declaration", "terms")):
                doc_type = DocumentType.rules_page
                doc_label = "rules_page"
            else:
                doc_type = DocumentType.id_proof
                doc_label = "id_proof"

            # Save to disk
            ext = ".jpg"
            if "png" in (media_mime or ""):
                ext = ".png"
            elif "webp" in (media_mime or ""):
                ext = ".webp"

            t_name = re.sub(r"[^a-zA-Z0-9]", "_", action_data.get("tenant_name", "tenant")).lower()
            room = action_data.get("room_number", "unknown")
            save_dir = MEDIA_DIR / doc_label / datetime.now().strftime("%Y-%m")
            save_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = save_dir / f"{room}_{t_name}_{ts}{ext}"
            file_path.write_bytes(img_bytes)
            rel_path = str(file_path.relative_to(MEDIA_DIR))

            # Save Document record
            session.add(Document(
                doc_type=doc_type,
                file_path=rel_path,
                original_name=f"{doc_label}_{t_name}_{room}",
                file_size_kb=len(img_bytes) // 1024,
                mime_type=media_mime or "image/jpeg",
                tenant_id=action_data.get("tenant_id"),
                tenancy_id=action_data.get("tenancy_id"),
                uploaded_by=pending.phone,
                notes=f"{doc_label} - {action_data.get('tenant_name', '')} - Room {room}",
            ))

            action_data["docs_saved"] = action_data.get("docs_saved", 0) + 1
            await _save_pending(pending.phone, "COLLECT_DOCS", action_data, [], session)

            count = action_data["docs_saved"]
            type_label = "Rules page" if doc_type == DocumentType.rules_page else "ID proof"
            return f"__KEEP_PENDING__{type_label} saved ({count} docs total).\n\nSend more or say *done*."

        # Text message but no image — remind them
        return "__KEEP_PENDING__Send photos of ID proof (front & back) and signed rules page.\nOr say *done* if finished."

    # ── Receipt slip collection (after payment/refund confirmation) ────────
    if pending.intent == "COLLECT_RECEIPT":
        from src.whatsapp.handlers._shared import _save_pending
        ans = reply_text.strip().lower()

        if ans in ("done", "skip", "no", "cancel", "later"):
            return "OK, no receipt saved."

        if media_id and media_type == "image":
            from src.whatsapp.webhook_handler import _fetch_media_bytes
            from src.whatsapp.media_handler import MEDIA_DIR
            from src.database.models import Document, DocumentType

            img_bytes = await _fetch_media_bytes(media_id)
            if not img_bytes:
                return "__KEEP_PENDING__Could not download. Please resend."

            t_name = re.sub(r"[^a-zA-Z0-9]", "_", action_data.get("tenant_name", "tenant")).lower()
            room = action_data.get("room_number", "unknown")
            ext = ".png" if "png" in (media_mime or "") else ".webp" if "webp" in (media_mime or "") else ".jpg"
            save_dir = MEDIA_DIR / "receipts" / datetime.now().strftime("%Y-%m")
            save_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = save_dir / f"{room}_{t_name}_{ts}{ext}"
            file_path.write_bytes(img_bytes)
            rel_path = str(file_path.relative_to(MEDIA_DIR))

            session.add(Document(
                doc_type=DocumentType.receipt,
                file_path=rel_path,
                original_name=f"receipt_{t_name}_{room}",
                file_size_kb=len(img_bytes) // 1024,
                mime_type=media_mime or "image/jpeg",
                tenant_id=action_data.get("tenant_id"),
                tenancy_id=action_data.get("tenancy_id"),
                uploaded_by=pending.phone,
                notes=action_data.get("receipt_note", f"Payment receipt - {action_data.get('tenant_name', '')} - Room {room}"),
            ))

            return f"Receipt saved for {action_data.get('tenant_name', 'tenant')} (Room {room})."

        return "__KEEP_PENDING__Send photo of the receipt slip, or say *skip*."

    if pending.intent == "CONFIRM_PAYMENT_LOG":
        # ── Correction check (before yes/no) ──────────────────────────────────
        _MODE_MAP = {
            "upi": "upi", "cash": "cash", "gpay": "upi", "phonepe": "upi",
            "paytm": "upi", "online": "upi", "bank": "upi",
            "neft": "upi", "cheque": "cheque", "imps": "upi",
            "netbanking": "upi", "net banking": "upi",
        }
        _corrected = False
        _rl = reply_text.lower()
        for _word, _norm in _MODE_MAP.items():
            if _word in _rl and _norm != action_data.get("mode", "").lower():
                action_data["mode"] = _norm
                _corrected = True
                break
        _amt_m = re.search(r"\b(\d[\d,]+)\b", reply_text)
        if _amt_m:
            _new_amt = float(_amt_m.group(1).replace(",", ""))
            if _new_amt != action_data.get("amount", 0) and _new_amt > 0:
                action_data["amount"] = _new_amt
                _corrected = True
        _MONTH_MAP = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            "january": 1, "february": 2, "march": 3, "april": 4,
            "june": 6, "july": 7, "august": 8, "september": 9,
            "october": 10, "november": 11, "december": 12,
        }
        for _mname, _mnum in _MONTH_MAP.items():
            if re.search(r"\b" + _mname + r"\b", _rl):
                from datetime import date as _date
                _today = _date.today()
                _yr = _today.year if _mnum <= _today.month + 1 else _today.year - 1
                _new_period = f"{_yr}-{_mnum:02d}-01"
                if _new_period != action_data.get("period_month", ""):
                    action_data["period_month"] = _new_period
                    _corrected = True
                break
        if _corrected:
            pending.action_data = json.dumps(action_data)
            await session.flush()
            _amt   = int(action_data["amount"])
            _mode  = (action_data.get("mode") or "cash").upper()
            _tname = action_data.get("tenant_name", "")
            _room  = action_data.get("room_number", "")
            _tlabel = f"{_tname} (Room {_room})" if _room else _tname
            _pm = action_data.get("period_month", "")
            _month_label = ""
            if _pm:
                try:
                    from datetime import datetime as _dt
                    _month_label = _dt.strptime(_pm, "%Y-%m-%d").strftime("%B %Y")
                except Exception:
                    _month_label = _pm
            return (
                "__KEEP_PENDING__"
                f"✏️ Updated. Please confirm:\n"
                f"• Tenant: {_tlabel}\n"
                f"• Amount: ₹{_amt:,}\n"
                f"• Mode: {_mode}\n"
                + (f"• Month: {_month_label}\n" if _month_label else "")
                + "\nReply *Yes* to confirm or *No* to cancel."
            )
        if is_affirmative(reply_text):
            result = await _do_log_payment_by_ids(
                tenant_id=action_data["tenant_id"],
                tenancy_id=action_data["tenancy_id"],
                amount=action_data["amount"],
                mode=action_data["mode"],
                ctx_name=action_data["logged_by"],
                period_month_str=action_data["period_month"],
                session=session,
            )
            # Start receipt collection
            from src.whatsapp.handlers._shared import _save_pending as _sp_r
            await _sp_r(pending.phone, "COLLECT_RECEIPT", {
                "tenant_id": action_data.get("tenant_id"),
                "tenancy_id": action_data.get("tenancy_id"),
                "tenant_name": action_data.get("tenant_name", ""),
                "room_number": action_data.get("room_number", ""),
                "receipt_note": f"Rent Rs.{int(action_data['amount']):,} {action_data.get('mode', '')} - {action_data.get('tenant_name', '')}",
            }, [], session)
            result += "\n\nSend photo of *receipt slip* to save, or say *skip*."
            return result
        if is_negative(reply_text):
            _room  = action_data.get("room_number", "")
            _tname = action_data.get("tenant_name", "")
            _tlabel = f"{_tname} (Room {_room})" if _room else _tname
            _mode  = (action_data.get("mode") or "cash").upper()
            _pm = action_data.get("period_month", "")
            _month_label = ""
            if _pm:
                try:
                    from datetime import datetime as _dt
                    _month_label = _dt.strptime(_pm, "%Y-%m-%d").strftime("%B %Y")
                except Exception:
                    _month_label = _pm
            return (
                "__KEEP_PENDING__"
                "What would you like to change?\n"
                f"  Tenant: {_tlabel}\n"
                f"  Amount: Rs.{int(action_data['amount']):,}\n"
                f"  Mode: {_mode}\n"
                + (f"  Month: {_month_label}\n" if _month_label else "")
                + "\nType the correction (e.g. *amount 15000*, *mode UPI*) or *cancel* to stop."
            )
        _room  = action_data.get("room_number", "")
        _tname = action_data.get("tenant_name", "")
        _tlabel = f"{_tname} (Room {_room})" if _room else _tname
        return (
            "__KEEP_PENDING__"
            f"Reply *Yes* to confirm logging Rs.{int(action_data['amount']):,} "
            f"for {_tlabel}, or *No* to change."
        )

    if pending.intent == "CONFIRM_PAYMENT_ALLOC":
        from src.whatsapp.handlers._shared import parse_allocation_override

        ans = reply_text.strip()
        if is_negative(ans):
            return (
                "__KEEP_PENDING__"
                "What would you like to change? Type the correction or *cancel* to stop."
            )

        # ── Mode/amount correction (same logic as CONFIRM_PAYMENT_LOG) ────────
        _MODE_MAP_ALLOC = {
            "upi": "upi", "cash": "cash", "gpay": "upi", "phonepe": "upi",
            "paytm": "upi", "online": "upi", "transfer": "upi",
            "neft": "upi", "cheque": "cheque", "imps": "upi",
            "netbanking": "upi", "net banking": "upi", "bank": "upi",
        }
        _corrected_alloc = False
        _rl_alloc = ans.lower()
        for _word, _norm in _MODE_MAP_ALLOC.items():
            if _word in _rl_alloc and _norm != action_data.get("mode", "").lower():
                action_data["mode"] = _norm
                _corrected_alloc = True
                break
        _amt_m_alloc = re.search(r"\b(\d[\d,]+)\b", ans)
        if _amt_m_alloc and not is_affirmative(ans):
            _new_amt = float(_amt_m_alloc.group(1).replace(",", ""))
            if _new_amt != action_data.get("amount", 0) and _new_amt > 0:
                action_data["amount"] = _new_amt
                _corrected_alloc = True
        if _corrected_alloc and not is_affirmative(ans):
            pending.action_data = json.dumps(action_data)
            await session.flush()
            _amt   = int(action_data["amount"])
            _mode  = (action_data.get("mode") or "cash").upper()
            _tname = action_data.get("tenant_name", "")
            _room  = action_data.get("room_number", "")
            _tlabel = f"{_tname} (Room {_room})" if _room else _tname
            return (
                "__KEEP_PENDING__"
                f"Updated. Please confirm:\n"
                f"- Tenant: {_tlabel}\n"
                f"- Amount: Rs.{_amt:,}\n"
                f"- Mode: {_mode}\n\n"
                "Reply *Yes* to confirm or *No* to cancel."
            )

        if is_affirmative(ans):
            allocation = action_data.get("allocation", [])
            results = []
            for i, alloc in enumerate(allocation):
                r = await _do_log_payment_by_ids(
                    tenant_id=action_data["tenant_id"],
                    tenancy_id=action_data["tenancy_id"],
                    amount=alloc["amount"],
                    mode=action_data["mode"],
                    ctx_name=action_data["logged_by"],
                    session=session,
                    period_month_str=alloc["period"],
                    skip_duplicate_check=(i > 0),
                )
                month_label = date.fromisoformat(alloc["period"]).strftime("%b %Y")
                results.append(f"{month_label}: Rs.{int(alloc['amount']):,} -- {r}")
            return "\n".join(results)

        # Try override parsing
        pending_months_raw = action_data.get("pending_months", [])
        if pending_months_raw:
            pending_months = [
                {"period": date.fromisoformat(m["period"]), "remaining": Decimal(str(m["remaining"]))}
                for m in pending_months_raw
            ]
            override = parse_allocation_override(ans, pending_months)
            if override:
                amount = Decimal(str(action_data["amount"]))
                new_alloc = []
                remaining_amt = amount
                for o in override:
                    alloc_amt = Decimal(str(o["amount"])) if o["amount"] is not None else remaining_amt
                    new_alloc.append({
                        "period": o["period"].isoformat(),
                        "amount": float(alloc_amt),
                    })
                    remaining_amt -= alloc_amt

                action_data["allocation"] = new_alloc
                await _save_pending(pending.phone, "CONFIRM_PAYMENT_ALLOC", action_data, [], session)

                mode_label = (action_data.get("mode") or "cash").upper()
                lines = [f"Updated allocation for Rs.{int(amount):,} {mode_label}:"]
                for a in new_alloc:
                    ml = date.fromisoformat(a["period"]).strftime("%b %Y")
                    lines.append(f"  -> {ml}: Rs.{int(a['amount']):,}")
                lines.append("\nReply *Yes* to confirm or *No* to cancel.")
                return "__KEEP_PENDING__" + "\n".join(lines)

        return "__KEEP_PENDING__Reply *Yes* to confirm, *No* to cancel, or specify allocation (e.g. 'all to march')."

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
            return (
                "__KEEP_PENDING__"
                "What would you like to change? Type the correction or *cancel* to stop."
            )
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

    if pending.intent == "CONFIRM_FIELD_UPDATE":
        from src.whatsapp.handlers.update_handler import _is_confirm_choice
        if _is_confirm_choice(reply_text):
            result = await _resolve_field_update("1", action_data, session, changed_by=pending.phone)
        else:
            result = await _resolve_field_update("2", action_data, session, changed_by=pending.phone)
        pending.resolved = True
        return result

    if pending.intent in ("ASSIGN_STAFF_WHO", "EXIT_STAFF_WHO"):
        # Disambiguating which staff the user meant
        if chosen_idx is None or chosen_idx < 0 or chosen_idx >= len(choices):
            return None  # invalid reply — keep pending alive
        from src.database.models import Staff as _Staff, Room as _Room
        from src.whatsapp.handlers.update_handler import (
            _apply_staff_assignment, _apply_staff_exit,
        )
        picked = choices[chosen_idx]
        staff_id = picked.get("staff_id")
        staff = await session.get(_Staff, staff_id) if staff_id else None
        if not staff:
            pending.resolved = True
            return "That staff record is no longer available."
        pending.resolved = True
        if pending.intent == "EXIT_STAFF_WHO":
            # Need a ctx for audit writes — synthesise one from pending.phone
            from src.whatsapp.role_service import CallerContext
            _ctx = CallerContext(phone=pending.phone, role="admin", name="")
            return await _apply_staff_exit(staff, _ctx, session)
        # ASSIGN_STAFF_WHO
        room_id = action_data.get("room_id")
        room = await session.get(_Room, room_id) if room_id else None
        if not room:
            return "That room is no longer available."
        from src.whatsapp.role_service import CallerContext
        _ctx = CallerContext(phone=pending.phone, role="admin", name="")
        return await _apply_staff_assignment(
            staff, staff.name, room,
            action_data.get("role"), action_data.get("phone"),
            _ctx, session,
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

    if pending.intent == "UPDATE_CHECKOUT_DATE_ASK":
        from src.whatsapp.intent_detector import _extract_date_entity
        if is_negative(reply_text):
            return "Cancelled."
        date_iso = _extract_date_entity(reply_text.strip())
        if not date_iso:
            return "__KEEP_PENDING__Couldn't parse that date. Try: *15 April* or *15/04/2026*"
        # Resolve tenant — might be from choices or from single match
        tenancy_id = action_data.get("tenancy_id")
        tenant_name = action_data.get("tenant_name", "")
        if not tenancy_id and choices:
            # Single match was stored in choices[0]
            tenancy_id = choices[0].get("tenancy_id")
            tenant_name = choices[0].get("label", "")
        if not tenancy_id:
            return "Something went wrong. Please try again: *change checkout date [Name] to [date]*"
        return await _do_update_checkout_date(tenancy_id, tenant_name, date_iso, session)

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
            action_data["step"]        = "ask_exit_date"
            action_data["tenancy_id"]  = chosen_tenant["tenancy_id"]
            action_data["tenant_name"] = chosen_tenant["label"]
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
            return (
                f"*Checkout Form — {chosen_tenant['label']}*\n\n"
                "*Exit date?* (e.g. *today* or *29 March*)"
            )

        # Steps 1–5 are text-based
        ans = reply_text.lower().strip()
        yes = ans in ("yes", "y", "haan", "ha", "done", "returned", "1")

        if step == "ask_exit_date":
            from src.whatsapp.intent_detector import _extract_date_entity
            if ans in ("today", "now", "aaj"):
                action_data["exit_date"] = date.today().isoformat()
            else:
                exit_iso = _extract_date_entity(reply_text)
                if not exit_iso:
                    return "__KEEP_PENDING__Couldn't parse that date. Try: *today* or *29 March* or *29/03/2026*"
                action_data["exit_date"] = exit_iso
            exit_d = date.fromisoformat(action_data["exit_date"])
            action_data["step"] = "ask_cupboard_key"
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
            return (
                f"Exit date: *{exit_d.strftime('%d %b %Y')}*\n\n"
                "*Q1/5* Was the *cupboard/almirah key* returned?\n"
                "Reply: *yes* or *no*"
            )

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
            action_data["step"] = "ask_fingerprint"
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)
            return "*Q4/5* Has *fingerprint/biometric access* been deleted?\nReply: *yes* or *no*"

        if step == "ask_fingerprint":
            action_data["fingerprint_deleted"] = yes
            action_data["step"] = "confirm_checkout"
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)

            # Auto-calculate dues from DB
            tenancy_id = action_data.get("tenancy_id")
            tenancy = await session.get(Tenancy, tenancy_id) if tenancy_id else None
            deposit = int(tenancy.security_deposit or 0) if tenancy else 0
            maintenance = int(tenancy.maintenance_fee or 0) if tenancy else 0
            o_rent, o_maint = await _calc_outstanding_dues(tenancy_id, session) if tenancy_id else (Decimal("0"), Decimal("0"))
            total_dues = int(o_rent) + int(o_maint)

            # Deposit forfeiture: notice after 5th = deposit forfeited, refund = 0
            deposit_forfeited = False
            notice_line = ""
            if tenancy and not tenancy.notice_date:
                deposit_forfeited = True
                notice_line = "\nNo notice on record — *deposit forfeited*"
            elif tenancy and tenancy.notice_date:
                if tenancy.notice_date.day > _NOTICE_BY_DAY:
                    deposit_forfeited = True
                    notice_line = (f"\nNotice given: {tenancy.notice_date.strftime('%d %b %Y')} "
                                   f"(after {_NOTICE_BY_DAY}th) — *deposit Rs.{deposit:,} forfeited*")
                else:
                    notice_line = (f"\nNotice given: {tenancy.notice_date.strftime('%d %b %Y')} "
                                   f"(before {_NOTICE_BY_DAY}th) — deposit eligible for refund")

            if deposit_forfeited:
                refund = 0
            else:
                refund = max(0, deposit - total_dues - maintenance)

            action_data["auto_dues"] = total_dues
            action_data["auto_maintenance"] = maintenance
            action_data["auto_deposit"] = deposit
            action_data["auto_refund"] = refund
            action_data["deposit_forfeited"] = deposit_forfeited
            await _save_pending(pending.phone, "RECORD_CHECKOUT", action_data, [], session)

            if deposit_forfeited:
                settlement = (
                    f"Deposit held: Rs.{deposit:,}\n"
                    f"*FORFEITED — Refund: Rs.0*"
                )
            else:
                settlement = (
                    f"Deposit held: Rs.{deposit:,}\n"
                    f"Unpaid rent: -Rs.{int(o_rent):,}\n"
                    f"Maintenance: -Rs.{maintenance:,}\n"
                    f"{'─' * 25}\n"
                    f"*Refund: Rs.{refund:,}*"
                )

            return (
                f"*Q5/5 — Settlement Summary*\n\n"
                f"Exit date: {date.fromisoformat(action_data.get('exit_date', date.today().isoformat())).strftime('%d %b %Y')}\n"
                f"Cupboard key: {'Returned' if action_data.get('cupboard_key') else 'NOT returned'}\n"
                f"Main key: {'Returned' if action_data.get('main_key') else 'NOT returned'}\n"
                f"Damages: {action_data.get('damage') or 'None'}\n"
                f"Fingerprint: {'Deleted' if action_data.get('fingerprint_deleted') else 'NOT deleted'}\n"
                f"{notice_line}\n\n"
                f"{settlement}\n\n"
                "Reply *confirm* to process checkout\n"
                "or *cancel* to abort"
            )

        if step == "confirm_checkout":
            if ans in ("confirm", "yes", "y", "done", "ok", "proceed"):
                tenancy_id = action_data.get("tenancy_id")
                exit_date = date.fromisoformat(action_data["exit_date"]) if action_data.get("exit_date") else date.today()
                refund_amt = action_data.get("auto_refund", 0)
                deposit_forfeited = action_data.get("deposit_forfeited", False)

                cr = CheckoutRecord(
                    tenancy_id=tenancy_id,
                    cupboard_key_returned=action_data.get("cupboard_key", False),
                    main_key_returned=action_data.get("main_key", False),
                    damage_notes=action_data.get("damage") or None,
                    pending_dues_amount=action_data.get("auto_dues", 0),
                    deposit_refunded_amount=refund_amt,
                    deposit_refund_date=exit_date if refund_amt > 0 else None,
                    actual_exit_date=exit_date,
                    recorded_by=pending.phone,
                )
                session.add(cr)

                if tenancy_id:
                    reason = "deposit forfeited — late notice" if deposit_forfeited else "deposit refund on checkout"
                    session.add(Refund(
                        tenancy_id  = tenancy_id,
                        amount      = Decimal(str(refund_amt)),
                        refund_date = exit_date if refund_amt > 0 else None,
                        reason      = reason,
                        status      = RefundStatus.pending if refund_amt > 0 else RefundStatus.cancelled,
                        notes       = f"Recorded during checkout by {pending.phone}",
                    ))

                # Mark tenancy as exited
                tenancy = await session.get(Tenancy, tenancy_id)
                if tenancy:
                    tenancy.status = TenancyStatus.exited
                    tenancy.checkout_date = exit_date

                # Google Sheets write-back: TENANTS tab + month tab EXIT
                gsheets_note = ""
                if tenancy:
                    room_obj = await session.get(Room, tenancy.room_id)
                    if room_obj:
                        try:
                            from src.integrations.gsheets import record_checkout as gsheets_checkout
                            notice_str = tenancy.notice_date.strftime("%d/%m/%Y") if tenancy.notice_date else None
                            gs_r = await gsheets_checkout(
                                room_obj.room_number,
                                action_data.get("tenant_name", ""),
                                notice_str,
                                exit_date.strftime("%d/%m/%Y"),
                            )
                            if gs_r.get("success"):
                                gsheets_note = "\nSheet updated"
                        except Exception:
                            pass
                        # Update month tab status to EXIT

                name = action_data.get("tenant_name", "Tenant")
                deposit = action_data.get("auto_deposit", 0)

                if deposit_forfeited:
                    settlement_line = f"Deposit: Rs.{deposit:,} — *FORFEITED*\n*Refund: Rs.0*"
                else:
                    settlement_line = (
                        f"Deposit: Rs.{deposit:,}\n"
                        f"Dues deducted: -Rs.{action_data.get('auto_dues', 0):,}\n"
                        f"Maintenance: -Rs.{action_data.get('auto_maintenance', 0):,}\n"
                        f"*Refund: Rs.{refund_amt:,}*"
                    )

                return (
                    f"*Checkout Complete — {name}*\n"
                    f"Exit date: {exit_date.strftime('%d %b %Y')}\n\n"
                    f"Keys: {'collected' if action_data.get('cupboard_key') and action_data.get('main_key') else 'PENDING'}\n"
                    f"Fingerprint: {'deleted' if action_data.get('fingerprint_deleted') else 'NOT DELETED'}\n"
                    f"Damages: {action_data.get('damage') or 'None'}\n\n"
                    f"{settlement_line}\n\n"
                    f"Saved to DB. Room is now vacant."
                    f"{gsheets_note}"
                )
            else:
                return "Cancelled. Nothing was changed."

        return None  # Unrecognised step

    if pending.intent == "COLLECT_RENT_STEP":
        from src.whatsapp.handlers._shared import _save_pending
        ans = reply_text.strip()
        step = action_data.get("step", "")

        # Cancel detection
        if ans.lower() in ("cancel", "no", "stop", "abort"):
            return "Cancelled. No payment logged."

        if step == "ask_name":
            # Search for tenant by name or room
            search = ans
            rows = await _find_active_tenants_by_name(ans, session)
            if not rows:
                room_clean = re.sub(r"[^0-9a-zA-Z\-]", "", ans)
                rows = await _find_active_tenants_by_room(room_clean, session)
                search = f"Room {room_clean}"
            if not rows:
                suggestions = await _find_similar_names(ans, session)
                hint = ""
                if suggestions:
                    hint = "\nDid you mean: " + ", ".join(f"*{s}*" for s in suggestions[:3]) + "?"
                return f"__KEEP_PENDING__No tenant found for *{ans}*.{hint}\n\n*Who paid?* (name or room number)"

            if len(rows) == 1:
                tenant, tenancy, room_obj = rows[0]
                action_data["tenant_id"] = tenant.id
                action_data["tenancy_id"] = tenancy.id
                action_data["tenant_name"] = tenant.name
                action_data["room_number"] = room_obj.room_number

                # Build dues snapshot
                snapshot = await build_dues_snapshot(tenancy.id, tenant.name, room_obj.room_number, session)
                action_data["snapshot_text"] = snapshot["text"]
                action_data["pending_months"] = [
                    {"period": m["period"].isoformat(), "remaining": float(m["remaining"])}
                    for m in snapshot["months"]
                ]

                # Fetch existing notes from sheet (keep existing logic)
                try:
                    from src.integrations.gsheets import get_sheet
                    ws = await get_sheet()
                    all_vals = ws.get_all_values()
                    header = all_vals[3] if len(all_vals) > 3 else []
                    is_new = "phone" in str(header[2] if len(header) > 2 else "").lower()
                    notes_col = 14 if is_new else 12
                    rclean = room_obj.room_number.strip().upper()
                    nlow = tenant.name.strip().lower()
                    for row in all_vals[4:]:
                        if str(row[0]).strip().upper() == rclean and nlow in str(row[1]).strip().lower():
                            existing_notes = str(row[notes_col]).strip() if len(row) > notes_col else ""
                            if existing_notes and not existing_notes.replace(".", "").replace("-", "").isdigit():
                                action_data["existing_notes"] = existing_notes
                            break
                except Exception:
                    pass

                action_data["step"] = "ask_cash"
                await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)
                return snapshot["text"] + "\n\n*Cash amount?* (number, or *skip* if no cash)"

            # Multiple matches — ask which one
            choices = _make_choices(rows)
            action_data["step"] = "pick_tenant"
            await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, choices, session)
            return _format_choices_message(search, choices, "collect rent")

        if step == "pick_tenant":
            if not ans.rstrip(".").isdigit():
                return "__KEEP_PENDING__Reply with a *number* to pick the tenant."
            num = int(ans.rstrip("."))
            if not (1 <= num <= len(choices)):
                return f"__KEEP_PENDING__Pick a number between 1 and {len(choices)}."
            chosen = choices[num - 1]
            tenant = await session.get(Tenant, chosen["tenant_id"])
            tenancy = await session.get(Tenancy, chosen["tenancy_id"])
            room_obj = await session.get(Room, tenancy.room_id) if tenancy else None
            action_data["tenant_id"] = chosen["tenant_id"]
            action_data["tenancy_id"] = chosen["tenancy_id"]
            action_data["tenant_name"] = chosen["label"].split(" (Room")[0]
            action_data["room_number"] = room_obj.room_number if room_obj else ""

            # Build dues snapshot
            snapshot = await build_dues_snapshot(tenancy.id, action_data["tenant_name"], action_data["room_number"], session)
            action_data["snapshot_text"] = snapshot["text"]
            action_data["pending_months"] = [
                {"period": m["period"].isoformat(), "remaining": float(m["remaining"])}
                for m in snapshot["months"]
            ]

            action_data["step"] = "ask_cash"
            await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)
            return snapshot["text"] + "\n\n*Cash amount?* (number, or *skip* if no cash)"

        if step == "ask_cash":
            cash = _parse_amount_field(ans)
            if ans.lower() not in ("skip", "0", "nil", "none", "no", "nahi") and cash <= 0:
                # They typed something but it's not a valid number
                if not re.search(r"\d", ans):
                    return "__KEEP_PENDING__Please enter a *number* for cash amount (e.g. 14000), or *skip*:"
                if cash < 0:
                    return "__KEEP_PENDING__Amount can't be negative. *Cash amount?* (number, or *skip*)"
            action_data["cash"] = cash
            action_data["step"] = "ask_upi"
            await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)
            return "*UPI amount?* (number, or *skip* if no UPI)"

        if step == "ask_upi":
            upi = _parse_amount_field(ans)
            if ans.lower() not in ("skip", "0", "nil", "none", "no", "nahi") and upi <= 0:
                if not re.search(r"\d", ans):
                    return "__KEEP_PENDING__Please enter a *number* for UPI amount (e.g. 5000), or *skip*:"
                if upi < 0:
                    return "__KEEP_PENDING__Amount can't be negative. *UPI amount?* (number, or *skip*)"
            action_data["upi"] = upi

            cash = action_data.get("cash", 0)
            total = cash + upi
            if total <= 0:
                action_data["step"] = "ask_cash"
                await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)
                return "__KEEP_PENDING__Total can't be zero. Enter at least one amount.\n\n*Cash amount?* (number, or *skip*)"

            action_data["step"] = "ask_notes"
            await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)

            # Show existing notes if any
            existing = action_data.get("existing_notes", "")
            prompt = "*Notes?* (add/update comment, or *skip*)"
            if existing:
                prompt = f"Current notes: _{existing}_\n\n*Update notes?* (type new text, *delete* to clear, or *skip* to keep)"
            return prompt

        if step == "ask_notes":
            if ans.lower() == "delete":
                action_data["notes"] = ""
                action_data["notes_action"] = "delete"
            elif ans.lower() not in ("skip", "none", "no", "na", "nil", "-"):
                action_data["notes"] = ans
                action_data["notes_action"] = "update"
            else:
                action_data["notes_action"] = "skip"

            action_data["step"] = "confirm"
            await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)

            cash = action_data.get("cash", 0)
            upi = action_data.get("upi", 0)
            total = cash + upi
            tname = action_data.get("tenant_name", "")
            rnum = action_data.get("room_number", "")

            pending_months_raw = action_data.get("pending_months", [])

            parts = []
            if cash > 0:
                parts.append(f"Cash: Rs.{int(cash):,}")
            if upi > 0:
                parts.append(f"UPI: Rs.{int(upi):,}")
            notes_str = action_data.get("notes", "")
            notes_action = action_data.get("notes_action", "skip")

            # Compute allocation if multiple months
            if pending_months_raw and len(pending_months_raw) > 1:
                from decimal import Decimal as _Dec
                pending_months = [
                    {"period": date.fromisoformat(m["period"]), "remaining": _Dec(str(m["remaining"]))}
                    for m in pending_months_raw
                ]
                alloc = compute_allocation(_Dec(str(total)), pending_months)
                alloc_data = [{"period": a["period"].isoformat(), "amount": float(a["amount"])} for a in alloc]
                action_data["allocation"] = alloc_data
                await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)

                alloc_text = format_allocation(alloc, total, "cash" if cash > 0 else "upi")

                return (
                    f"*Confirm Payment?*\n\n"
                    f"Tenant: {tname} (Room {rnum})\n"
                    + "\n".join(f"  {p}" for p in parts)
                    + f"\n*Total: Rs.{int(total):,}*"
                    + (f"\nNotes: {notes_str}" if notes_action == "update" else "")
                    + ("\nNotes: _cleared_" if notes_action == "delete" else "")
                    + alloc_text + "\n\n"
                    'Reply *yes* to save, *no* to cancel, or specify allocation:\n'
                    '  e.g. "all to march" or "feb 3000 march 5000"'
                )
            else:
                pm = date.fromisoformat(pending_months_raw[0]["period"]) if pending_months_raw else date.today().replace(day=1)
                return (
                    f"*Confirm Payment?*\n\n"
                    f"Tenant: {tname} (Room {rnum})\n"
                    + "\n".join(f"  {p}" for p in parts)
                    + f"\n*Total: Rs.{int(total):,}*"
                    + f"\nMonth: {pm.strftime('%B %Y')}"
                    + (f"\nNotes: {notes_str}" if notes_action == "update" else "")
                    + ("\nNotes: _cleared_" if notes_action == "delete" else "")
                    + "\n\nReply *yes* to save or *no* to cancel."
                )

        if step == "confirm":
            if ans.lower() in ("yes", "y", "confirm", "save", "ok", "done"):
                cash = action_data.get("cash", 0)
                upi = action_data.get("upi", 0)
                tname = action_data.get("tenant_name", "")
                rnum = action_data.get("room_number", "")
                allocation = action_data.get("allocation")

                if allocation:
                    # Log split payments per allocation
                    results = []
                    for i, alloc in enumerate(allocation):
                        if cash > 0 and i == 0:
                            # First allocation entry uses cash mode
                            r = await _do_log_payment_by_ids(
                                tenant_id=action_data["tenant_id"],
                                tenancy_id=action_data["tenancy_id"],
                                amount=alloc["amount"],
                                mode="cash",
                                ctx_name=pending.phone, session=session,
                                period_month_str=alloc["period"],
                            )
                        else:
                            mode = "upi" if upi > 0 else "cash"
                            r = await _do_log_payment_by_ids(
                                tenant_id=action_data["tenant_id"],
                                tenancy_id=action_data["tenancy_id"],
                                amount=alloc["amount"],
                                mode=mode,
                                ctx_name=pending.phone, session=session,
                                period_month_str=alloc["period"],
                                skip_duplicate_check=(i > 0),
                            )
                        month_label = date.fromisoformat(alloc["period"]).strftime("%b %Y")
                        results.append(f"{month_label}: Rs.{int(alloc['amount']):,} -- {r}")

                    # Update notes
                    notes_action = action_data.get("notes_action", "skip")
                    notes_note = ""
                    if notes_action in ("update", "delete"):
                        try:
                            new_notes = action_data.get("notes", "") if notes_action == "update" else ""
                            # Update DB — rent_schedule.notes for current month
                            current_month = date.today().replace(day=1)
                            rs = await session.scalar(
                                select(RentSchedule).where(
                                    RentSchedule.tenancy_id == action_data["tenancy_id"],
                                    RentSchedule.period_month == current_month,
                                )
                            )
                            if rs:
                                rs.notes = new_notes if notes_action == "update" else None
                            from src.integrations.gsheets import sync_notes_with_retry
                            await sync_notes_with_retry(rnum, tname, new_notes)
                            notes_note = "\nNotes updated"
                        except Exception as e:
                            import logging as _log
                            _log.getLogger(__name__).error("Notes sync failed: %s", e)

                    total = cash + upi
                    return (
                        f"*Payment logged — {tname}* (Room {rnum})\n"
                        + "\n".join(results)
                        + f"\nTotal: Rs.{int(total):,}"
                        + notes_note
                    )
                else:
                    # Single month — original behavior
                    results = []
                    if cash > 0:
                        r = await _do_log_payment_by_ids(
                            tenant_id=action_data["tenant_id"],
                            tenancy_id=action_data["tenancy_id"],
                            amount=cash, mode="cash",
                            ctx_name=pending.phone, session=session,
                        )
                        results.append(f"Cash Rs.{int(cash):,} -- {r}")
                    if upi > 0:
                        r = await _do_log_payment_by_ids(
                            tenant_id=action_data["tenant_id"],
                            tenancy_id=action_data["tenancy_id"],
                            amount=upi, mode="upi",
                            ctx_name=pending.phone, session=session,
                            skip_duplicate_check=(cash > 0),
                        )
                        results.append(f"UPI Rs.{int(upi):,} -- {r}")

                    notes_action = action_data.get("notes_action", "skip")
                    notes_note = ""
                    if notes_action in ("update", "delete"):
                        try:
                            new_notes = action_data.get("notes", "") if notes_action == "update" else ""
                            # Update DB — rent_schedule.notes for current month
                            current_month = date.today().replace(day=1)
                            rs = await session.scalar(
                                select(RentSchedule).where(
                                    RentSchedule.tenancy_id == action_data["tenancy_id"],
                                    RentSchedule.period_month == current_month,
                                )
                            )
                            if rs:
                                rs.notes = new_notes if notes_action == "update" else None
                            from src.integrations.gsheets import sync_notes_with_retry
                            await sync_notes_with_retry(rnum, tname, new_notes)
                            notes_note = "\nNotes updated"
                        except Exception as e:
                            import logging as _log
                            _log.getLogger(__name__).error("Notes sync failed: %s", e)

                    total = cash + upi
                    return (
                        f"*Payment logged — {tname}* (Room {rnum})\n"
                        + "\n".join(results)
                        + f"\nTotal: Rs.{int(total):,}"
                        + notes_note
                    )

            # Check for allocation override
            pending_months_raw = action_data.get("pending_months", [])
            if pending_months_raw and len(pending_months_raw) > 1:
                from src.whatsapp.handlers._shared import parse_allocation_override
                from decimal import Decimal as _Dec
                pending_months = [
                    {"period": date.fromisoformat(m["period"]), "remaining": _Dec(str(m["remaining"]))}
                    for m in pending_months_raw
                ]
                override = parse_allocation_override(ans, pending_months)
                if override:
                    amount = _Dec(str(action_data.get("cash", 0) + action_data.get("upi", 0)))
                    new_alloc = []
                    remaining_amt = amount
                    for o in override:
                        alloc_amt = _Dec(str(o["amount"])) if o["amount"] is not None else remaining_amt
                        new_alloc.append({
                            "period": o["period"].isoformat(),
                            "amount": float(alloc_amt),
                        })
                        remaining_amt -= alloc_amt
                    action_data["allocation"] = new_alloc
                    await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)

                    mode_label = "CASH" if action_data.get("cash", 0) > 0 else "UPI"
                    lines = [f"Updated allocation for Rs.{int(amount):,} {mode_label}:"]
                    for a in new_alloc:
                        ml = date.fromisoformat(a["period"]).strftime("%b %Y")
                        lines.append(f"  -> {ml}: Rs.{int(a['amount']):,}")
                    lines.append("\nReply *yes* to confirm or *no* to cancel.")
                    return "__KEEP_PENDING__" + "\n".join(lines)

            if is_negative(ans):
                return "Cancelled. No payment logged."

            return "__KEEP_PENDING__Reply *yes* to save, *no* to cancel, or specify allocation."

        return None

    if pending.intent == "LOG_EXPENSE_STEP":
        from src.whatsapp.handlers._shared import _save_pending
        ans = reply_text.strip()
        step = action_data.get("step", "")

        if ans.lower() in ("cancel", "no", "stop", "abort"):
            return "Cancelled. No expense logged."

        _EXPENSE_CATEGORIES = {
            "1": "electricity", "2": "water", "3": "internet",
            "4": "salary", "5": "maintenance", "6": "groceries", "7": "other",
            "electricity": "electricity", "water": "water", "internet": "internet",
            "salary": "salary", "maintenance": "maintenance", "groceries": "groceries",
            "other": "other", "food": "groceries", "wifi": "internet", "eb": "electricity",
            "electric": "electricity", "plumber": "maintenance", "repair": "maintenance",
            "cleaning": "maintenance", "diesel": "maintenance", "generator": "maintenance",
            "pest": "maintenance", "security": "salary",
        }

        if step == "ask_category":
            cat = _EXPENSE_CATEGORIES.get(ans.lower().strip())
            if not cat:
                return (
                    "__KEEP_PENDING__Pick a category:\n"
                    "1. Electricity  2. Water  3. Internet\n"
                    "4. Salary  5. Maintenance  6. Groceries\n"
                    "7. Other"
                )
            action_data["category"] = cat
            if action_data.get("amount"):
                # Already have amount — skip to description
                action_data["step"] = "ask_description"
                await _save_pending(pending.phone, "LOG_EXPENSE_STEP", action_data, [], session)
                return f"*{cat.capitalize()}* — Rs.{int(action_data['amount']):,}\n\n*Description?* (or *skip*)"

            action_data["step"] = "ask_amount"
            await _save_pending(pending.phone, "LOG_EXPENSE_STEP", action_data, [], session)
            return f"*{cat.capitalize()}*\n\n*Amount?* (number)"

        if step == "ask_amount":
            amt = _parse_amount_field(ans)
            if amt <= 0:
                if not re.search(r"\d", ans):
                    return "__KEEP_PENDING__Enter a *number* for the amount (e.g. 4500):"
                return "__KEEP_PENDING__Amount must be greater than 0. *Amount?*"
            action_data["amount"] = amt
            action_data["step"] = "ask_description"
            await _save_pending(pending.phone, "LOG_EXPENSE_STEP", action_data, [], session)
            return f"*{action_data['category'].capitalize()}* — Rs.{int(amt):,}\n\n*Description?* (e.g. 'March bill' or *skip*)"

        if step == "ask_description":
            desc = ans if ans.lower() not in ("skip", "none", "no", "nil", "-") else ""
            action_data["final_description"] = desc
            action_data["step"] = "ask_photo"
            await _save_pending(pending.phone, "LOG_EXPENSE_STEP", action_data, [], session)
            return "*Receipt photo?* Send a photo or type *skip*"

        if step == "ask_photo":
            skip = ans.lower() in ("skip", "none", "no", "nil", "-", "na")
            if not skip and media_id and media_type == "image":
                try:
                    from src.whatsapp.media_handler import download_whatsapp_media
                    from src.database.models import Document, DocumentType
                    file_path = await download_whatsapp_media(media_id, media_mime or "image/jpeg", "expense_receipts")
                    if file_path:
                        action_data["receipt_path"] = file_path
                except Exception:
                    pass  # photo save failed — continue without
            elif not skip:
                return "__KEEP_PENDING__Please *send a photo* or type *skip*."

            action_data["step"] = "confirm"
            await _save_pending(pending.phone, "LOG_EXPENSE_STEP", action_data, [], session)

            cat = action_data["category"].capitalize()
            amt = int(action_data["amount"])
            desc = action_data.get("final_description", "")
            desc_line = f"\nDescription: {desc}" if desc else ""
            photo_line = "\nReceipt: attached" if action_data.get("receipt_path") else ""

            return (
                f"*Confirm Expense?*\n\n"
                f"Category: {cat}\n"
                f"Amount: Rs.{amt:,}"
                f"{desc_line}{photo_line}\n\n"
                "Reply *yes* to save or *no* to cancel."
            )

        if step == "confirm":
            if ans.lower() in ("yes", "y", "confirm", "save", "ok", "done"):
                cat = action_data["category"]
                amt = Decimal(str(action_data["amount"]))
                desc = action_data.get("final_description", "") or action_data.get("description", "")

                # Find or create expense category
                cat_row = await session.scalar(
                    select(ExpenseCategory).where(ExpenseCategory.name.ilike(cat))
                )
                if not cat_row:
                    cat_row = ExpenseCategory(name=cat)
                    session.add(cat_row)
                    await session.flush()

                expense = Expense(
                    category_id=cat_row.id,
                    amount=amt,
                    expense_date=date.today(),
                    description=desc[:500] if desc else f"{cat} expense",
                    recorded_by=pending.phone,
                )
                session.add(expense)

                return (
                    f"*Expense logged* ✅\n\n"
                    f"Category: {cat.capitalize()}\n"
                    f"Amount: Rs.{int(amt):,}\n"
                    + (f"Description: {desc}\n" if desc else "")
                    + f"Date: {date.today().strftime('%d %b %Y')}"
                )
            return "Cancelled. No expense logged."

        return None

    if pending.intent == "ADD_TENANT_INCOMPLETE":
        # Legacy — clear and re-prompt
        return "Please send *add tenant* to start the checkin form."

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

    # ── Room Transfer step-by-step (before cancel/chosen_idx checks) ─────────
    if pending.intent == "ROOM_TRANSFER" and action_data.get("step"):
        step = action_data.get("step", "confirm")
        ans = reply_text.strip()

        if is_negative(reply_text):
            return "Room transfer cancelled."

        if step == "confirm":
            if ans == "1":
                action_data["new_rent"] = action_data["current_rent"]
                action_data["step"] = "ask_deposit"
                await _save_pending(pending.phone, "ROOM_TRANSFER", action_data, [], session)
                deposit = int(action_data.get("current_deposit", 0))
                return (
                    f"Rent stays *Rs.{int(action_data['current_rent']):,}*\n\n"
                    f"*Additional deposit needed?*\n"
                    f"Current deposit: Rs.{deposit:,}\n"
                    "(enter amount, or *skip* if no change)"
                )
            if ans == "2":
                action_data["step"] = "ask_new_rent"
                await _save_pending(pending.phone, "ROOM_TRANSFER", action_data, [], session)
                return "*New rent amount?* (number)"
            return "__KEEP_PENDING__Reply *1* to keep current rent or *2* to enter new amount."

        if step == "ask_new_rent":
            new_rent = _parse_amount_field(ans)
            if new_rent <= 0:
                return "__KEEP_PENDING__Enter a valid rent amount (e.g. 15000):"
            action_data["new_rent"] = new_rent
            action_data["step"] = "ask_deposit"
            await _save_pending(pending.phone, "ROOM_TRANSFER", action_data, [], session)
            deposit = int(action_data.get("current_deposit", 0))
            return (
                f"New rent: *Rs.{int(new_rent):,}*\n\n"
                f"*Additional deposit needed?*\n"
                f"Current deposit: Rs.{deposit:,}\n"
                "(enter amount, or *skip* if no change)"
            )

        if step == "ask_deposit":
            extra_deposit = _parse_amount_field(ans)
            action_data["extra_deposit"] = extra_deposit
            action_data["step"] = "final_confirm"
            await _save_pending(pending.phone, "ROOM_TRANSFER", action_data, [], session)

            new_rent = int(action_data.get("new_rent", action_data["current_rent"]))
            rent_changed = new_rent != action_data["current_rent"]
            deposit_line = f"\nAdditional deposit: Rs.{int(extra_deposit):,}" if extra_deposit > 0 else ""

            return (
                f"*Confirm Room Transfer?*\n\n"
                f"Tenant: {action_data['tenant_name']}\n"
                f"Room: {action_data['from_room']} → {action_data['to_room_number']}\n"
                + (f"Rent: Rs.{int(action_data['current_rent']):,} → Rs.{new_rent:,}\n" if rent_changed else f"Rent: Rs.{new_rent:,} (no change)\n")
                + deposit_line
                + "\n\nReply *yes* to confirm or *no* to cancel."
            )

        if step == "final_confirm":
            if is_affirmative(reply_text):
                new_rent = action_data.get("new_rent")
                extra_deposit = action_data.get("extra_deposit", 0)
                action_data["changed_by"] = pending.phone
                result = await _do_room_transfer(action_data, session)

                if new_rent and new_rent != action_data["current_rent"]:
                    # Update current month's RentSchedule (agreed_rent already set in _do_room_transfer)
                    current_period = date.today().replace(day=1)
                    rs = await session.scalar(
                        select(RentSchedule).where(
                            RentSchedule.tenancy_id == action_data["tenancy_id"],
                            RentSchedule.period_month == current_period,
                        )
                    )
                    if rs:
                        rs.rent_due = Decimal(str(new_rent))

                if extra_deposit > 0:
                    tenancy = await session.get(Tenancy, action_data["tenancy_id"])
                    if tenancy:
                        tenancy.security_deposit = (tenancy.security_deposit or 0) + Decimal(str(extra_deposit))
                        result += f"\nDeposit increased by Rs.{int(extra_deposit):,}"
                        # Systemic rule: any tenancy field change → sheet sync.
                        try:
                            import asyncio as _aio
                            from src.integrations.gsheets import sync_tenant_all_fields as _sta
                            _aio.create_task(_sta(tenancy.tenant_id))
                        except Exception:
                            pass

                return result
            return "Room transfer cancelled."

        return None

    # ── Assign Room step-by-step ─────────────────────────────────────────────
    if pending.intent == "ASSIGN_ROOM_STEP" and action_data.get("step"):
        step = action_data["step"]
        ans = reply_text.strip()

        if is_negative(reply_text):
            return "Room assignment cancelled."

        if step == "pick_tenant":
            try:
                idx = int(ans) - 1
                chosen = action_data["choices"][idx]
            except (ValueError, IndexError):
                return "__KEEP_PENDING__Reply with the number of the tenant."
            action_data["tenant_id"] = chosen["tenant_id"]
            action_data["tenant_name"] = chosen["label"]
            if action_data.get("room"):
                # Validate room
                new_room = await session.scalar(
                    select(Room).where(Room.room_number == action_data["room"].upper(), Room.active == True)
                )
                if not new_room:
                    return f"Room *{action_data['room']}* not found."
                occ = await session.scalar(
                    select(func.count(Tenancy.id)).where(
                        Tenancy.room_id == new_room.id, Tenancy.status == TenancyStatus.active))
                if occ:
                    return f"Room *{action_data['room']}* is occupied. Pick a vacant room."
                action_data["step"] = "confirm"
                action_data["room_id"] = new_room.id
                action_data["room_number"] = new_room.room_number
                await _save_pending(pending.phone, "ASSIGN_ROOM_STEP", action_data, [], session)
                return (
                    f"*Assign Room?*\n\n"
                    f"Tenant: {chosen['label']}\n"
                    f"Room: {new_room.room_number}\n\n"
                    "Reply *yes* to confirm or *no* to cancel."
                )
            action_data["step"] = "ask_room"
            await _save_pending(pending.phone, "ASSIGN_ROOM_STEP", action_data, [], session)
            return f"Selected *{chosen['label']}*.\nWhich room? (e.g. 305-A)"

        if step == "ask_room":
            rm = re.search(r"(\d{2,4}[A-Za-z]?(?:-[A-Za-z])?)", ans)
            if not rm:
                return "__KEEP_PENDING__Enter a valid room number (e.g. 305-A):"
            room_str = rm.group(1).upper()
            new_room = await session.scalar(
                select(Room).where(Room.room_number == room_str, Room.active == True)
            )
            if not new_room:
                return f"__KEEP_PENDING__Room *{room_str}* not found. Try again:"
            occ = await session.scalar(
                select(func.count(Tenancy.id)).where(
                    Tenancy.room_id == new_room.id, Tenancy.status == TenancyStatus.active))
            if occ:
                return f"__KEEP_PENDING__Room *{room_str}* is occupied. Pick a vacant room:"
            action_data["room_id"] = new_room.id
            action_data["room_number"] = new_room.room_number
            action_data["step"] = "confirm"
            await _save_pending(pending.phone, "ASSIGN_ROOM_STEP", action_data, [], session)
            tenant_name = action_data.get("tenant_name", "Tenant")
            return (
                f"*Assign Room?*\n\n"
                f"Tenant: {tenant_name}\n"
                f"Room: {new_room.room_number}\n\n"
                "Reply *yes* to confirm or *no* to cancel."
            )

        if step == "confirm":
            if is_affirmative(reply_text):
                tenant_id = action_data["tenant_id"]
                room_id = action_data["room_id"]
                room_number = action_data["room_number"]

                # Create new active tenancy
                tenant = await session.get(Tenant, tenant_id)
                if not tenant:
                    return "Tenant not found in DB."

                tenancy = Tenancy(
                    tenant_id=tenant_id,
                    room_id=room_id,
                    checkin_date=date.today(),
                    status=TenancyStatus.active,
                    agreed_rent=Decimal("0"),  # will be set via rent flow
                )
                session.add(tenancy)
                await session.flush()

                # Audit log
                from src.database.models import AuditLog
                session.add(AuditLog(
                    changed_by=pending.phone,
                    entity_type="tenancy",
                    entity_id=tenancy.id,
                    entity_name=tenant.name,
                    field="room_assigned",
                    old_value=None,
                    new_value=room_number,
                    room_number=room_number,
                    source="whatsapp",
                    note=f"Room assigned via ASSIGN_ROOM",
                ))

                # Google Sheet sync
                gsheets_note = ""
                try:
                    from src.integrations.gsheets import add_tenant as gsheets_add
                    gs_r = await gsheets_add(
                        room_number=room_number, name=tenant.name, phone=tenant.phone,
                        gender=tenant.gender or "", building="", floor="", sharing="",
                        checkin=date.today().strftime("%d/%m/%Y"),
                        agreed_rent=0, deposit=0, booking=0, maintenance=0, notes="Assigned via bot",
                    )
                    if gs_r.get("success"):
                        gsheets_note = "\nSheet updated"
                except Exception:
                    pass

                return (
                    f"Room assigned — *{tenant.name}* ({tenant.phone})\n"
                    f"Room: *{room_number}*\n"
                    f"Check-in: {date.today().strftime('%d %b %Y')}\n"
                    f"_Set rent via: change {tenant.name} rent to [amount]_{gsheets_note}"
                )
            return "Room assignment cancelled."

        return None

    # ── Cancel any pending confirmation with "no" ─────────────────────────────

    if is_negative(reply_text) and pending.intent in (
        "CHECKOUT", "SCHEDULE_CHECKOUT", "PAYMENT_LOG", "QUERY_TENANT",
        "GET_TENANT_NOTES", "NOTICE_GIVEN", "RENT_CHANGE_WHO", "RENT_CHANGE",
        "VOID_PAYMENT", "VOID_EXPENSE", "DUPLICATE_CONFIRM", "OVERPAYMENT_RESOLVE",
        "OVERPAYMENT_ADD_NOTE", "UNDERPAYMENT_NOTE",
        "DEPOSIT_CHANGE", "DEPOSIT_CHANGE_AMT", "DEPOSIT_CHANGE_WHO",
        "ROOM_TRANSFER_WHO", "ROOM_TRANSFER_DEST",
        "FIELD_UPDATE_WHO",
        "AWAITING_CLARIFICATION", "UPDATE_CHECKOUT_DATE", "ASSIGN_ROOM_STEP",
    ):
        # Mark resolved so the NEXT user message starts a fresh flow
        # — otherwise the pending row stays alive and swallows their reply.
        pending.resolved = True
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

    # ── Numbered-choice disambiguation ────────────────────────────────────────
    # If chosen_idx is set, resolve the numbered choice.
    # If chosen_idx is None, skip to intent-specific text handlers below.
    if chosen_idx is not None:
        chosen = choices[chosen_idx]
    else:
        chosen = None

    if chosen is not None and pending.intent == "PAYMENT_LOG":
        return await _do_log_payment_by_ids(
            tenant_id=chosen["tenant_id"],
            tenancy_id=chosen["tenancy_id"],
            amount=action_data["amount"],
            mode=action_data.get("mode", "cash"),
            ctx_name=action_data.get("logged_by", "owner"),
            period_month_str=action_data.get("period_month", ""),
            session=session,
        )

    if chosen is not None and pending.intent in ("CHECKOUT", "SCHEDULE_CHECKOUT"):
        # Redirect to RECORD_CHECKOUT checklist instead of instant checkout
        date_str = action_data.get("checkout_date", "")
        try:
            checkout_date_val = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            checkout_date_val = date.today()

        if checkout_date_val > date.today():
            # Future date → schedule only, no checklist yet
            return await _do_checkout(
                tenancy_id=chosen["tenancy_id"],
                tenant_name=chosen["label"],
                checkout_date_val=checkout_date_val,
                session=session,
            )

        # Today/past → start checklist
        new_action = {
            "step": "ask_cupboard_key",
            "tenancy_id": chosen["tenancy_id"],
            "tenant_name": chosen["label"],
            "checkout_date": date_str,
        }
        await _save_pending(pending.phone, "RECORD_CHECKOUT", new_action, [], session)

        # Show pre-checkout summary with auto-calculated dues
        tenancy = await session.get(Tenancy, chosen["tenancy_id"])
        deposit = int(tenancy.security_deposit or 0) if tenancy else 0
        o_rent, o_maint = await _calc_outstanding_dues(chosen["tenancy_id"], session)
        notice_status = "On record" if (tenancy and tenancy.notice_date) else "No notice given"

        return (
            f"*Checkout — {chosen['label']}*\n\n"
            f"Deposit held: Rs.{deposit:,}\n"
            f"Unpaid rent: Rs.{int(o_rent):,}\n"
            f"Unpaid maintenance: Rs.{int(o_maint):,}\n"
            f"Notice: {notice_status}\n\n"
            "*Please complete the checklist:*\n\n"
            "*Q1/5* Was the *cupboard/almirah key* returned?\n"
            "Reply: *yes* or *no*"
        )

    if chosen is not None and pending.intent == "UPDATE_CHECKIN":
        return await _do_update_checkin(
            tenancy_id=chosen["tenancy_id"],
            tenant_name=chosen["label"],
            new_checkin_str=action_data.get("new_checkin", ""),
            session=session,
        )

    if chosen is not None and pending.intent == "UPDATE_CHECKOUT_DATE":
        new_checkout_str = action_data.get("new_checkout", "")
        if new_checkout_str:
            return await _do_update_checkout_date(
                tenancy_id=chosen["tenancy_id"],
                tenant_name=chosen["label"],
                new_checkout_str=new_checkout_str,
                session=session,
            )
        else:
            # No date provided — ask for it
            tenancy = await session.get(Tenancy, chosen["tenancy_id"])
            old_checkout = tenancy.checkout_date if tenancy else None
            old_str = old_checkout.strftime('%d %b %Y') if old_checkout else "not set"
            action_data["tenancy_id"] = chosen["tenancy_id"]
            action_data["tenant_name"] = chosen["label"]
            await _save_pending(pending.phone, "UPDATE_CHECKOUT_DATE_ASK", action_data, [], session)
            return (
                f"*{chosen['label']}*\n"
                f"Current checkout: {old_str}\n\n"
                f"*New checkout date?* (e.g. *15 April* or *15/04/2026*)"
            )

    if chosen is not None and pending.intent == "NOTICE_GIVEN":
        tenancy = await session.get(Tenancy, chosen["tenancy_id"])
        if tenancy:
            notice_date_val = None
            last_day_val = None
            try:
                notice_date_val = date.fromisoformat(action_data["notice_date"])
                last_day_val = date.fromisoformat(action_data["last_day"])
                tenancy.notice_date = notice_date_val
                tenancy.expected_checkout = last_day_val
            except (ValueError, KeyError):
                pass
            last_day_str = action_data.get("last_day", "")
            try:
                last_day_fmt = date.fromisoformat(last_day_str).strftime("%d %b %Y")
            except ValueError:
                last_day_fmt = last_day_str
            deposit_note = action_data.get("deposit_note", "")

            # Google Sheets write-back
            gsheets_note = ""
            try:
                room_obj = await session.get(Room, tenancy.room_id)
                if room_obj:
                    from src.integrations.gsheets import record_notice as gsheets_notice
                    notice_fmt = notice_date_val.strftime("%d/%m/%Y") if notice_date_val else action_data.get("notice_date", "")
                    exit_fmt = last_day_val.strftime("%d/%m/%Y") if last_day_val else ""
                    gs_r = await gsheets_notice(room_obj.room_number, chosen["label"].split(" (Room")[0], notice_fmt, exit_fmt)
                    if gs_r.get("success"):
                        gsheets_note = "\nSheet updated"
            except Exception:
                pass

            return (
                f"*Notice recorded — {chosen['label']}*\n"
                f"Notice date: {action_data.get('notice_date', '')}\n"
                f"Last day: {last_day_fmt}\n\n"
                f"{deposit_note}{gsheets_note}"
            )
        return "Tenancy not found."

    if chosen is not None and pending.intent == "RENT_CHANGE_WHO":
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
        if chosen is None:
            return "__KEEP_PENDING__Reply *1* for one-time or *2* for permanent change."
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

    if chosen is not None and pending.intent == "QUERY_TENANT":
        return await _do_query_tenant_by_id(
            tenant_id=chosen["tenant_id"],
            tenancy_id=chosen["tenancy_id"],
            session=session,
        )

    if chosen is not None and pending.intent == "GET_TENANT_NOTES":
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
                # Systemic rule: any tenancy field change → sheet sync.
                try:
                    import asyncio as _aio
                    from src.integrations.gsheets import sync_tenant_all_fields as _sta
                    _aio.create_task(_sta(tenancy.tenant_id))
                except Exception:
                    pass
            return (
                f"*Overpayment allocated — {tenant_name}*\n"
                f"Rs.{int(extra):,} added to security deposit.\n"
                f"New deposit: Rs.{int(tenancy.security_deposit or 0):,}"
            )
        elif seq == 4:  # Add a note
            await _save_pending(
                pending.phone, "OVERPAYMENT_ADD_NOTE",
                {"tenancy_id": tenancy_id, "tenant_name": tenant_name, "extra_amount": extra},
                [], session,
            )
            return (
                f"Rs.{int(extra):,} overpayment for {tenant_name}.\n"
                "Reply with your note (e.g. reason for overpayment):"
            )
        else:  # Keep as credit / ask tenant
            return (
                f"Rs.{int(extra):,} extra for {tenant_name} left as unallocated credit.\n"
                "Confirm with tenant what it's for."
            )

    if pending.intent == "OVERPAYMENT_ADD_NOTE":
        # Free-text note for overpayment
        from src.database.models import AuditLog
        tenancy_id = action_data["tenancy_id"]
        tenant_name = action_data["tenant_name"]
        extra = action_data["extra_amount"]
        session.add(AuditLog(
            changed_by=pending.phone,
            entity_type="payment",
            entity_id=tenancy_id,
            field="overpayment_note",
            old_value=None,
            new_value=reply_text,
            source="whatsapp",
            note=f"Overpayment Rs.{int(extra):,} for {tenant_name}: {reply_text}",
        ))
        return (
            f"Note saved for {tenant_name}'s overpayment (Rs.{int(extra):,}):\n"
            f"_{reply_text}_"
        )

    if pending.intent == "UNDERPAYMENT_NOTE":
        # Free-text note for underpayment (or skip)
        payment_id = action_data["payment_id"]
        tenant_name = action_data["tenant_name"]
        remaining = action_data["remaining"]
        if reply_text.lower().strip() in ("skip", "no", "n"):
            return "OK, no note added."
        from src.database.models import Payment as _Pay, AuditLog
        pay = await session.get(_Pay, payment_id)
        if pay:
            pay.notes = (pay.notes or "") + f" | Note: {reply_text}"
        session.add(AuditLog(
            changed_by=pending.phone,
            entity_type="payment",
            entity_id=payment_id,
            field="underpayment_note",
            old_value=None,
            new_value=reply_text,
            source="whatsapp",
            note=f"Underpayment Rs.{int(remaining):,} for {tenant_name}: {reply_text}",
        ))
        return (
            f"Note saved for {tenant_name}'s underpayment (Rs.{int(remaining):,} remaining):\n"
            f"_{reply_text}_"
        )

    if pending.intent == "VOID_PAYMENT":
        if chosen.get("seq") == 1:
            return await _do_void_payment(
                payment_id=action_data["payment_id"],
                tenant_name=action_data["tenant_name"],
                session=session,
            )
        return "Void cancelled — payment remains as logged."

    if pending.intent == "VOID_WHICH":
        # User picked which payment to void from the list
        from src.whatsapp.handlers._shared import _save_pending
        choices_data = json.loads(pending.choices or "[]")
        seq = chosen.get("seq")
        match = next((c for c in choices_data if c["seq"] == seq), None)
        if not match:
            return "Invalid choice. Void cancelled."
        # Now confirm before voiding
        p_id = match["payment_id"]
        t_name = match["tenant_name"]
        amt = match["amount"]
        pm = match.get("period_month", "")
        pm_label = date.fromisoformat(pm).strftime("%b %Y") if pm else "?"
        confirm_choices = [
            {"seq": 1, "label": "Yes, void it"},
            {"seq": 2, "label": "No, keep it"},
        ]
        await _save_pending(
            pending.phone, "VOID_PAYMENT",
            {"payment_id": p_id, "tenant_name": t_name, "amount": amt, "period_month": pm},
            confirm_choices, session, state="awaiting_choice",
        )
        return (
            f"__KEEP_PENDING__"
            f"*Void this payment?*\n"
            f"Tenant: {t_name}\n"
            f"Amount: Rs.{int(amt):,}\n"
            f"Month: {pm_label}\n\n"
            "1. Yes, void it\n"
            "2. No, keep it\n\n"
            "Reply *1* or *2*."
        )

    if pending.intent == "VOID_EXPENSE":
        choices_data = json.loads(pending.choices or "[]")
        seq = chosen.get("seq")
        match = next((c for c in choices_data if c["seq"] == seq), None)
        if match:
            from src.whatsapp.handlers.account_handler import _do_void_expense
            return await _do_void_expense(match["expense_id"], session)
        return "Void cancelled."

    if pending.intent == "VOID_WHO":
        # User picked which tenant to void — now find their latest payment
        tenant_id = chosen.get("tenant_id")
        tenancy_id = chosen.get("tenancy_id")
        if not tenant_id or not tenancy_id:
            return "Invalid selection. Try again."
        # Get most recent non-void payment for current month
        from src.database.models import Payment as _Pay
        current_period = date.today().replace(day=1)
        q = select(_Pay).where(
            _Pay.tenancy_id == tenancy_id,
            _Pay.is_void == False,
            _Pay.period_month == current_period,
        ).order_by(_Pay.created_at.desc())
        payment = await session.scalar(q)
        if not payment:
            # Try any recent payment
            q2 = select(_Pay).where(
                _Pay.tenancy_id == tenancy_id,
                _Pay.is_void == False,
                _Pay.period_month.isnot(None),
            ).order_by(_Pay.created_at.desc())
            payment = await session.scalar(q2)
        if not payment:
            return f"No active payment found for this tenant."
        # Show void confirmation
        t_name = chosen.get("label", "").split(" (Room")[0]
        period_str = payment.period_month.strftime("%b %Y") if payment.period_month else "?"
        void_choices = [
            {"seq": 1, "label": "Yes, void it"},
            {"seq": 2, "label": "No, keep it"},
        ]
        from src.whatsapp.handlers._shared import _save_pending
        await _save_pending(
            pending.phone, "VOID_PAYMENT",
            {"payment_id": payment.id, "tenant_name": t_name,
             "amount": float(payment.amount), "period_month": payment.period_month.isoformat() if payment.period_month else ""},
            void_choices, session,
        )
        return (
            "__KEEP_PENDING__"
            f"*Void this payment?*\n"
            f"Tenant: {t_name}\n"
            f"Amount: Rs.{int(payment.amount):,} ({payment.payment_mode.value if payment.payment_mode else '?'})\n"
            f"Month: {period_str}\n\n"
            "1. Yes, void it\n"
            "2. No, keep it\n\n"
            "Reply *1* or *2*."
        )

    if chosen is not None and pending.intent == "REFUND_WHO":
        tenant_id = chosen.get("tenant_id")
        tenancy_id = chosen.get("tenancy_id")
        if not tenant_id or not tenancy_id:
            return "Invalid selection. Refund cancelled."
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            return "Tenant record not found."
        amount = float(action_data.get("amount") or 0)
        if amount <= 0:
            return "Missing refund amount."
        from src.whatsapp.handlers.account_handler import _do_add_refund_by_ids
        from src.whatsapp.role_service import CallerContext
        _ctx = CallerContext(phone=pending.phone, role="admin", name="")
        pending.resolved = True
        return await _do_add_refund_by_ids(
            tenancy_id, tenant.name, amount, _ctx, session,
        )

    if chosen is not None and pending.intent == "ROOM_TRANSFER_WHO":
        tenant = await session.get(Tenant, chosen["tenant_id"])
        tenancy = await session.get(Tenancy, chosen["tenancy_id"])
        if not tenant or not tenancy:
            return "Tenant not found."
        current_room = await session.get(Room, tenancy.room_id) if tenancy.room_id else None
        from_room = current_room.room_number if current_room else ""
        to_room = (action_data.get("to_room") or "").strip()

        if not to_room:
            await _save_pending(
                pending.phone, "ROOM_TRANSFER_DEST",
                {"tenancy_id": tenancy.id, "tenant_name": tenant.name,
                 "from_room": from_room}, [], session,
            )
            return (
                f"Moving *{tenant.name}* from Room *{from_room}*.\n\n"
                "Which room should they move to? (Reply with room number)"
            )
        return await _finalize_room_transfer(
            pending.phone, tenancy.id, tenant.name,
            from_room, to_room, session,
        )

    if pending.intent == "ROOM_TRANSFER_DEST":
        to_room = reply_text.strip()
        if not to_room:
            return "__KEEP_PENDING__Reply with the destination room number."
        return await _finalize_room_transfer(
            pending.phone,
            action_data["tenancy_id"],
            action_data["tenant_name"],
            action_data.get("from_room", ""),
            to_room,
            session,
        )

    if chosen is not None and pending.intent == "DEPOSIT_CHANGE_WHO":
        tenant = await session.get(Tenant, chosen["tenant_id"])
        tenancy = await session.get(Tenancy, chosen["tenancy_id"])
        if not tenant or not tenancy:
            return "Tenant not found."
        room = await session.get(Room, tenancy.room_id) if tenancy.room_id else None
        room_num = room.room_number if room else ""
        current = int(tenancy.security_deposit or 0)
        amount = action_data.get("amount")

        if not amount:
            await _save_pending(
                pending.phone, "DEPOSIT_CHANGE_AMT",
                {"tenancy_id": tenancy.id, "tenant_name": tenant.name},
                [], session,
            )
            return (
                f"*{tenant.name}* — Room {room_num}\n"
                f"Current deposit: Rs.{current:,}\n\n"
                "Reply with the new deposit amount:"
            )

        new_amt = int(amount)
        option_choices = [{"seq": 1, "label": "Yes, update"}, {"seq": 2, "label": "No, cancel"}]
        await _save_pending(
            pending.phone, "DEPOSIT_CHANGE",
            {"tenancy_id": tenancy.id, "tenant_name": tenant.name,
             "new_amount": new_amt, "old_amount": current},
            option_choices, session,
        )
        return (
            f"*Change deposit — {tenant.name}*\n"
            f"Room {room_num}\n"
            f"Current: Rs.{current:,}  ->  New: Rs.{new_amt:,}\n\n"
            "Reply *Yes* to confirm or *No* to cancel."
        )

    if pending.intent == "DEPOSIT_CHANGE":
        if is_affirmative(reply_text):
            from src.whatsapp.handlers.account_handler import _do_deposit_change
            return await _do_deposit_change(
                tenancy_id=action_data["tenancy_id"],
                new_amount=action_data["new_amount"],
                tenant_name=action_data["tenant_name"],
                session=session,
                changed_by=pending.phone,
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
                changed_by=pending.phone,
            )
        return "__KEEP_PENDING__Reply with the new deposit amount (numbers only):"

    if chosen is not None and pending.intent == "FIELD_UPDATE_WHO":
        from src.whatsapp.handlers._shared import _save_pending
        tenant = await session.get(Tenant, chosen["tenant_id"])
        tenancy = await session.get(Tenancy, chosen["tenancy_id"])
        if not tenant or not tenancy:
            return "Tenant not found."
        room = await session.get(Room, tenancy.room_id) if tenancy.room_id else None
        room_label = f" (Room {room.room_number})" if room else ""
        field = (action_data.get("field") or "").strip()
        new_value = action_data.get("new_value")

        # Read old_value + display line per field.
        if field == "sharing_type":
            raw = tenancy.sharing_type
            old_value = raw.value if hasattr(raw, "value") else (raw or "not set")
            if str(old_value).lower() == str(new_value).lower():
                return f"*{tenant.name}* is already {new_value} sharing."
            display_line = f"Sharing: {old_value} → *{new_value}*"
        elif field == "agreed_rent":
            old_value = int(tenancy.agreed_rent or 0)
            if int(old_value) == int(new_value):
                return f"*{tenant.name}*'s rent is already Rs.{int(new_value):,}."
            display_line = f"Rent: Rs.{int(old_value):,} → *Rs.{int(new_value):,}*"
        elif field == "security_deposit":
            old_value = int(tenancy.security_deposit or 0)
            if int(old_value) == int(new_value):
                return f"*{tenant.name}*'s deposit is already Rs.{int(new_value):,}."
            display_line = f"Deposit: Rs.{int(old_value):,} → *Rs.{int(new_value):,}*"
        elif field == "phone":
            old_value = tenant.phone or "not set"
            if str(old_value) == str(new_value):
                return f"*{tenant.name}*'s phone is already {new_value}."
            display_line = f"Phone: {old_value} → *{new_value}*"
        elif field == "gender":
            old_value = tenant.gender or "not set"
            if str(old_value).lower() == str(new_value).lower():
                return f"*{tenant.name}* is already {new_value}."
            display_line = f"Gender: {old_value} → *{new_value}*"
        else:
            return f"Unknown update field: {field}."

        action_data_confirm = {
            "tenancy_id": tenancy.id,
            "field": field,
            "old_value": str(old_value),
            "new_value": new_value,
            "tenant_name": tenant.name,
        }
        if field == "phone":
            action_data_confirm["tenant_id"] = tenant.id
            action_data_confirm["table"] = "tenants"

        option_choices = [
            {"seq": 1, "intent": "CONFIRM_UPDATE", "label": "Yes, update"},
            {"seq": 2, "intent": "CANCEL_UPDATE", "label": "No, cancel"},
        ]
        await _save_pending(
            pending.phone, "CONFIRM_FIELD_UPDATE",
            action_data_confirm, option_choices, session,
        )
        return (
            f"Update *{tenant.name}*{room_label}?\n\n"
            f"{display_line}\n\n"
            f"Reply *1* to confirm or *2* to cancel."
        )

    # (ROOM_TRANSFER step-by-step handled earlier, before cancel/chosen_idx checks)

    if pending.intent == "CONFIRM_ADD_TENANT":
        if is_negative(reply_text):
            return "Tenant check-in cancelled. Nothing was saved."
        if is_affirmative(reply_text):
            action_data["entered_by"] = action_data.get("entered_by", "") or "bot"
            result = await _do_add_tenant(action_data, session)

            # Save KYC extra fields from image extraction if present
            kyc = action_data.get("_kyc_extra")
            if kyc:
                phone_clean = re.sub(r"[^0-9]", "", action_data.get("phone", ""))
                if len(phone_clean) > 10:
                    phone_clean = phone_clean[-10:]
                if phone_clean:
                    tenant = await session.scalar(
                        select(Tenant).where(Tenant.phone.like(f"%{phone_clean}"))
                    )
                    if tenant:
                        if kyc.get("father_name"):
                            tenant.father_name = kyc["father_name"]
                        if kyc.get("father_phone"):
                            tenant.father_phone = kyc["father_phone"]
                        if kyc.get("date_of_birth"):
                            try:
                                for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
                                    try:
                                        tenant.date_of_birth = datetime.strptime(kyc["date_of_birth"], fmt).date()
                                        break
                                    except ValueError:
                                        continue
                            except Exception:
                                pass
                        if kyc.get("permanent_address"):
                            tenant.permanent_address = kyc["permanent_address"]
                        if kyc.get("emergency_contact"):
                            ec = kyc["emergency_contact"]
                            ec_digits = re.sub(r"[^0-9]", "", ec)
                            if len(ec_digits) >= 10:
                                tenant.emergency_contact_phone = ec_digits[-10:]
                            else:
                                tenant.emergency_contact_name = ec
                        if kyc.get("emergency_relationship"):
                            tenant.emergency_contact_relationship = kyc["emergency_relationship"]
                        if kyc.get("email"):
                            tenant.email = kyc["email"]
                        if kyc.get("occupation"):
                            tenant.occupation = kyc["occupation"]
                        if kyc.get("educational_qualification"):
                            tenant.educational_qualification = kyc["educational_qualification"]
                        if kyc.get("office_address"):
                            tenant.office_address = kyc["office_address"]
                        if kyc.get("office_phone"):
                            tenant.office_phone = kyc["office_phone"]
                        if kyc.get("id_proof_type"):
                            tenant.id_proof_type = kyc["id_proof_type"]
                        if kyc.get("id_proof_number"):
                            tenant.id_proof_number = kyc["id_proof_number"]
                        result += "\nKYC data saved."
                        # Systemic rule: DB mutation → sheet sync.
                        try:
                            import asyncio as _aio
                            from src.integrations.gsheets import sync_tenant_all_fields as _sta
                            _aio.create_task(_sta(tenant.id))
                        except Exception:
                            pass

            # Save registration form image as Document + start doc collection
            form_image_path = action_data.get("form_image_path")
            if form_image_path:
                from src.database.models import Document, DocumentType
                phone_clean = re.sub(r"[^0-9]", "", action_data.get("phone", ""))
                if len(phone_clean) > 10:
                    phone_clean = phone_clean[-10:]
                t = await session.scalar(select(Tenant).where(Tenant.phone.like(f"%{phone_clean}"))) if phone_clean else None
                t_id = t.id if t else None
                tn = None
                if t_id:
                    tn = await session.scalar(
                        select(Tenancy).where(Tenancy.tenant_id == t_id, Tenancy.status == TenancyStatus.active)
                    )
                session.add(Document(
                    doc_type=DocumentType.reg_form,
                    file_path=form_image_path,
                    original_name=f"reg_form_{action_data.get('name', 'tenant')}",
                    mime_type="image/jpeg",
                    tenant_id=t_id,
                    tenancy_id=tn.id if tn else None,
                    uploaded_by=pending.phone,
                    notes=f"Registration form - {action_data.get('name', '')} - Room {action_data.get('room_number', '')}",
                ))

                from src.whatsapp.handlers._shared import _save_pending as _sp
                doc_data = {
                    "step": "collecting",
                    "tenant_id": t_id,
                    "tenancy_id": tn.id if tn else None,
                    "tenant_name": action_data.get("name", ""),
                    "room_number": action_data.get("room_number", ""),
                    "phone": action_data.get("phone", ""),
                    "docs_saved": 1,
                }
                await _sp(pending.phone, "COLLECT_DOCS", doc_data, [], session)
                result += "\n\nNow send:\n- *ID proof front & back* (Aadhaar/DL/Passport)\n- *Signed rules page*\n\nJust send the photos — I'll save them automatically.\nSay *done* when finished."

            return result
        return "__KEEP_PENDING__Reply *Yes* to save the new tenant or *No* to cancel."

    if pending.intent == "UPDATE_TENANT_NOTES_STEP":
        ans = reply_text.strip()
        step = action_data.get("step", "")

        if ans.lower() in ("cancel", "stop", "abort"):
            return "Cancelled."

        if step == "pick_tenant":
            if not ans.rstrip(".").isdigit():
                return "__KEEP_PENDING__Reply with a *number* to pick the tenant."
            num = int(ans.rstrip("."))
            if not (1 <= num <= len(choices)):
                return f"__KEEP_PENDING__Pick a number between 1 and {len(choices)}."
            chosen = choices[num - 1]
            tenant = await session.get(Tenant, chosen["tenant_id"])
            tenancy = await session.get(Tenancy, chosen["tenancy_id"])
            room_obj = await session.get(Room, tenancy.room_id) if tenancy else None
            current_notes = tenancy.notes or "(no notes)"
            action_data.update({
                "step": "enter_notes",
                "tenant_id": chosen["tenant_id"],
                "tenancy_id": chosen["tenancy_id"],
                "tenant_name": chosen["label"].split(" (Room")[0],
                "room_number": room_obj.room_number if room_obj else "",
                "current_notes": tenancy.notes or "",
            })
            await _save_pending(pending.phone, "UPDATE_TENANT_NOTES_STEP", action_data, [], session)
            return (
                f"*{action_data['tenant_name']}* (Room {action_data['room_number']})\n\n"
                f"Current tenant agreement: _{current_notes}_\n\n"
                "Type new agreement notes, or *delete* to clear:"
            )

        if step == "enter_notes":
            if ans.lower() == "delete":
                new_notes = None
                action_data["new_notes"] = ""
                action_data["notes_action"] = "delete"
            else:
                new_notes = ans
                action_data["new_notes"] = ans
                action_data["notes_action"] = "update"

            action_data["step"] = "confirm"
            await _save_pending(pending.phone, "UPDATE_TENANT_NOTES_STEP", action_data, [], session)

            display = f'"{new_notes}"' if new_notes else "_cleared_"
            return (
                f"*Updated tenant agreement for {action_data['tenant_name']}:*\n"
                f"{display}\n\n"
                "Reply *Yes* to save or *No* to cancel."
            )

        if step == "confirm":
            if is_negative(ans):
                return "Cancelled. Notes not changed."
            if is_affirmative(ans):
                tenancy = await session.get(Tenancy, action_data["tenancy_id"])
                if not tenancy:
                    return "Tenancy not found."

                notes_action = action_data.get("notes_action", "skip")
                new_notes = action_data.get("new_notes", "")
                tenancy.notes = new_notes if notes_action == "update" else None

                # Audit log — note edits matter for accountability.
                from src.database.models import AuditLog
                session.add(AuditLog(
                    changed_by=action_data.get("changed_by", "system"),
                    entity_type="tenancy",
                    entity_id=tenancy.id,
                    entity_name=action_data["tenant_name"],
                    field="notes",
                    old_value=None,
                    new_value=new_notes if notes_action == "update" else None,
                    room_number=action_data["room_number"],
                    source="whatsapp",
                ))

                # Sync BOTH sheet tabs: TENANTS (master) + current monthly tab.
                _notes_value = new_notes if notes_action == "update" else ""
                try:
                    from src.integrations.gsheets import sync_tenants_tab_notes, update_notes
                    import asyncio as _aio
                    _aio.create_task(sync_tenants_tab_notes(
                        action_data["room_number"], action_data["tenant_name"], _notes_value,
                    ))
                    _aio.create_task(update_notes(
                        action_data["room_number"], action_data["tenant_name"], _notes_value,
                    ))
                except Exception as e:
                    import logging as _log
                    _log.getLogger(__name__).error("Notes sheet sync failed: %s", e)

                return f"Tenant agreement updated for *{action_data['tenant_name']}*."

            return "__KEEP_PENDING__Reply *Yes* to save or *No* to cancel."

    if pending.intent == "ADD_CONTACT_STEP":
        import hashlib
        ans = reply_text.strip()

        # Only hard-cancel on explicit cancel words (not "no" — that means correction)
        if ans.lower() in ("cancel", "stop", "abort"):
            return "Cancelled. Contact not saved."

        step = action_data.get("step", "")

        # "No" during confirm → ask what to change, don't cancel
        if step == "confirm" and is_negative(ans):
            return (
                "__KEEP_PENDING__"
                "What would you like to change?\n"
                f"  Name: {action_data.get('name', '')}\n"
                f"  Phone: {action_data.get('phone', '')}\n"
                f"  Category: {action_data.get('category', '')}\n\n"
                "Type the correction (e.g. *name is Mahadevapura lineman*) or *cancel* to stop."
            )

        if step == "ask_name":
            # Strip parenthesized category hints like "(Electrician)" from name
            clean_name = re.sub(r'\s*\([^)]*\)\s*', ' ', ans).strip()
            action_data["name"] = clean_name.title()
            if action_data.get("phone"):
                if action_data.get("category"):
                    action_data["step"] = "ask_notes"
                else:
                    action_data["step"] = "ask_category"
            else:
                action_data["step"] = "ask_phone"
            await _save_pending(pending.phone, "ADD_CONTACT_STEP", action_data, [], session)
            if action_data["step"] == "ask_phone":
                return f"*{action_data['name']}*\n\n*Phone number?*"
            elif action_data["step"] == "ask_category":
                return f"*{action_data['name']}* — {action_data['phone']}\n\n*What do they do?* (e.g. electrician, plumber)"
            else:
                phone_str = f"\nPhone: {action_data['phone']}" if action_data.get('phone') else ""
                return (
                    f"*{action_data['name']}* — {action_data['category']}{phone_str}\n\n"
                    "*Any notes?* (e.g. light installation, 20K agreed)\n"
                    "Type notes or *skip*"
                )

        if step == "ask_phone":
            # Strip all non-digits, then extract 10-digit phone (drop country code)
            clean_digits = re.sub(r'[^\d]', '', ans)
            if clean_digits.startswith('91') and len(clean_digits) == 12:
                clean_digits = clean_digits[2:]
            if clean_digits.startswith('0') and len(clean_digits) == 11:
                clean_digits = clean_digits[1:]
            phone_match = re.search(r'\d{7,15}', clean_digits)
            if not phone_match:
                return "__KEEP_PENDING__Please enter a valid phone number (at least 7 digits):"
            action_data["phone"] = phone_match.group()
            if action_data.get("category"):
                action_data["step"] = "ask_notes"
            else:
                action_data["step"] = "ask_category"
            await _save_pending(pending.phone, "ADD_CONTACT_STEP", action_data, [], session)
            if action_data["step"] == "ask_category":
                return f"*{action_data['name']}* — {action_data['phone']}\n\n*What do they do?* (e.g. electrician, plumber)"
            return (
                f"*{action_data['name']}* — {action_data['category']}\n\n"
                "*Any notes?* (e.g. light installation, 20K agreed)\n"
                "Type notes or *skip*"
            )

        if step == "ask_category":
            action_data["category"] = ans.strip().title()
            action_data["step"] = "ask_notes"
            await _save_pending(pending.phone, "ADD_CONTACT_STEP", action_data, [], session)
            return (
                f"*{action_data['name']}* — {action_data['category']}\n\n"
                "*Any notes?* (e.g. light installation, 20K agreed)\n"
                "Type notes or *skip*"
            )

        if step == "ask_notes":
            if ans.lower() not in ("skip", "no", "none", "-"):
                action_data["notes"] = ans
            action_data["step"] = "confirm"
            await _save_pending(pending.phone, "ADD_CONTACT_STEP", action_data, [], session)
            notes_line = f"\nNotes: {action_data.get('notes', '')}" if action_data.get('notes') else ""
            return (
                f"*Add Contact?*\n\n"
                f"Name: {action_data['name']}\n"
                f"Phone: {action_data['phone']}\n"
                f"Category: {action_data['category']}"
                f"{notes_line}\n\n"
                "Reply *Yes* to save or *No* to cancel."
            )

        if step == "confirm":
            if is_affirmative(ans):
                name = action_data["name"]
                phone = action_data["phone"]
                category = action_data["category"]
                dedup = hashlib.sha256(f"{phone}:{name}".encode()).hexdigest()

                # Check duplicate by hash (exact same name + phone)
                existing = await session.scalar(
                    select(PgContact).where(PgContact.unique_hash == dedup)
                )
                if existing:
                    return f"Contact *{name}* ({phone}) already exists."

                # Check same-name contacts — ask replace/new/cancel
                same_name = (await session.execute(
                    select(PgContact).where(func.lower(PgContact.name) == name.lower())
                )).scalars().all()
                if same_name and not action_data.get("_name_confirmed"):
                    lines = [f"*Contact(s) with name \"{name}\" already exist:*\n"]
                    for i, c in enumerate(same_name, 1):
                        lines.append(f"*{i}.* {c.name} — {c.phone} ({c.category or ''})")
                    lines.append(f"\n*{len(same_name)+1}.* Add as NEW contact")
                    lines.append(f"*{len(same_name)+2}.* Cancel")
                    action_data["step"] = "resolve_duplicate"
                    action_data["_same_name_ids"] = [c.id for c in same_name]
                    await _save_pending(pending.phone, "ADD_CONTACT_STEP", action_data, [], session)
                    return "\n".join(lines)

                notes = action_data.get("notes", "")
                contact_for = f"{category} — {notes}" if notes else category
                contact = PgContact(
                    name=name,
                    phone=phone,
                    category=category,
                    contact_for=contact_for,
                    property="Whitefield",
                    unique_hash=dedup,
                )
                session.add(contact)
                notes_str = f"\n  _{notes}_" if notes else ""
                return f"Contact saved — *{name}* ({category}) {phone}{notes_str}"

            return "__KEEP_PENDING__Reply *Yes* to save or *No* to cancel."

        if step == "resolve_duplicate":
            same_ids = action_data.get("_same_name_ids", [])
            n_options = len(same_ids) + 2  # existing contacts + "Add new" + "Cancel"

            if ans.rstrip(".").isdigit():
                choice = int(ans.rstrip("."))
                if 1 <= choice <= len(same_ids):
                    # Replace existing contact
                    old_contact = await session.get(PgContact, same_ids[choice - 1])
                    if old_contact:
                        old_contact.phone = action_data["phone"]
                        old_contact.category = action_data["category"]
                        old_contact.contact_for = action_data["category"]
                        old_contact.unique_hash = hashlib.sha256(
                            f"{action_data['phone']}:{action_data['name']}".encode()
                        ).hexdigest()
                        return f"Contact updated — *{old_contact.name}* ({action_data['category']}) {action_data['phone']}"
                elif choice == len(same_ids) + 1:
                    # Add as new
                    action_data["_name_confirmed"] = True
                    action_data["step"] = "confirm"
                    await _save_pending(pending.phone, "ADD_CONTACT_STEP", action_data, [], session)
                    return (
                        f"*Add as new contact?*\n\n"
                        f"Name: {action_data['name']}\n"
                        f"Phone: {action_data['phone']}\n"
                        f"Category: {action_data['category']}\n\n"
                        "Reply *Yes* to save."
                    )
                elif choice == n_options:
                    return "Cancelled."

            return f"__KEEP_PENDING__Reply with a number (1-{n_options})."

    # APPROVE_ONBOARDING is handled at the TOP of resolve_pending_action (line ~132)

    if pending.intent == "UPDATE_CONTACT_STEP":
        ans = reply_text.strip()

        if ans.lower() in ("cancel", "stop", "abort"):
            return "Cancelled."

        step = action_data.get("step", "")

        if step == "ask_name":
            # Search for the contact
            from sqlalchemy import or_
            like = f"%{ans.lower()}%"
            contacts = (await session.execute(
                select(PgContact).where(
                    PgContact.property == "Whitefield",
                    or_(
                        func.lower(PgContact.name).like(like),
                        func.lower(PgContact.category).like(like),
                    ),
                ).order_by(PgContact.name)
            )).scalars().all()

            if not contacts:
                return f"__KEEP_PENDING__No contact found matching *{ans}*. Try another name:"

            if len(contacts) == 1:
                c = contacts[0]
                action_data["step"] = "ask_field"
                action_data["contact_id"] = c.id
                action_data["contact_name"] = c.name
                action_data["contact_phone"] = c.phone
                action_data["contact_notes"] = c.contact_for or ""
                await _save_pending(pending.phone, "UPDATE_CONTACT_STEP", action_data, [], session)
                return (
                    f"*Update: {c.name}*\n"
                    f"  Phone: {c.phone}\n"
                    f"  Category: {c.category or ''}\n"
                    f"  Notes: {c.contact_for or '—'}\n\n"
                    "What to update?\n"
                    "*1.* Phone number\n"
                    "*2.* Notes/description\n"
                    "*3.* Both\n"
                    "*4.* Cancel"
                )

            lines = [f"*Found {len(contacts)} contacts:*\n"]
            for i, c in enumerate(contacts, 1):
                lines.append(f"*{i}.* {c.name} — {c.phone} ({c.category or ''})")
            lines.append(f"\n*{len(contacts)+1}.* Cancel")
            action_data["step"] = "pick_contact"
            action_data["_contact_ids"] = [c.id for c in contacts]
            await _save_pending(pending.phone, "UPDATE_CONTACT_STEP", action_data, [], session)
            return "\n".join(lines)

        if step == "pick_contact":
            ids = action_data.get("_contact_ids", [])
            if ans.rstrip(".").isdigit():
                choice = int(ans.rstrip("."))
                if choice == len(ids) + 1:
                    return "Cancelled."
                if 1 <= choice <= len(ids):
                    c = await session.get(PgContact, ids[choice - 1])
                    if not c:
                        return "Contact not found."
                    action_data["step"] = "ask_field"
                    action_data["contact_id"] = c.id
                    action_data["contact_name"] = c.name
                    action_data["contact_phone"] = c.phone
                    action_data["contact_notes"] = c.contact_for or ""
                    await _save_pending(pending.phone, "UPDATE_CONTACT_STEP", action_data, [], session)
                    return (
                        f"*Update: {c.name}*\n"
                        f"  Phone: {c.phone}\n"
                        f"  Notes: {c.contact_for or '—'}\n\n"
                        "What to update?\n"
                        "*1.* Phone number\n"
                        "*2.* Notes/description\n"
                        "*3.* Both\n"
                        "*4.* Cancel"
                    )
            return f"__KEEP_PENDING__Reply with a number (1-{len(ids)+1})."

        if step == "ask_field":
            if ans in ("4", "cancel"):
                return "Cancelled."
            if ans == "1":
                action_data["step"] = "enter_phone"
                action_data["update_what"] = "phone"
            elif ans == "2":
                action_data["step"] = "enter_notes"
                action_data["update_what"] = "notes"
            elif ans == "3":
                action_data["step"] = "enter_phone"
                action_data["update_what"] = "both"
            else:
                return "__KEEP_PENDING__Reply *1* (phone), *2* (notes), *3* (both), or *4* (cancel)."
            await _save_pending(pending.phone, "UPDATE_CONTACT_STEP", action_data, [], session)
            if action_data["step"] == "enter_phone":
                return f"*{action_data['contact_name']}*\nCurrent phone: {action_data['contact_phone']}\n\n*New phone number?*"
            return f"*{action_data['contact_name']}*\nCurrent notes: {action_data['contact_notes'] or '—'}\n\n*New notes/description?*"

        if step == "enter_phone":
            clean_digits = re.sub(r'[^\d]', '', ans)
            if clean_digits.startswith('91') and len(clean_digits) == 12:
                clean_digits = clean_digits[2:]
            if clean_digits.startswith('0') and len(clean_digits) == 11:
                clean_digits = clean_digits[1:]
            phone_match = re.search(r'\d{7,15}', clean_digits)
            if not phone_match:
                return "__KEEP_PENDING__Please enter a valid phone number:"
            action_data["new_phone"] = phone_match.group()
            if action_data.get("update_what") == "both":
                action_data["step"] = "enter_notes"
                await _save_pending(pending.phone, "UPDATE_CONTACT_STEP", action_data, [], session)
                return f"Phone: {action_data['new_phone']}\n\nNow enter *notes/description:*"
            else:
                action_data["step"] = "confirm_update"
                await _save_pending(pending.phone, "UPDATE_CONTACT_STEP", action_data, [], session)
                return (
                    f"*Update {action_data['contact_name']}?*\n"
                    f"  Phone: {action_data['contact_phone']} → *{action_data['new_phone']}*\n\n"
                    "Reply *Yes* to save or *No* to cancel."
                )

        if step == "enter_notes":
            action_data["new_notes"] = ans
            action_data["step"] = "confirm_update"
            await _save_pending(pending.phone, "UPDATE_CONTACT_STEP", action_data, [], session)
            changes = []
            if action_data.get("new_phone"):
                changes.append(f"  Phone: {action_data['contact_phone']} → *{action_data['new_phone']}*")
            changes.append(f"  Notes: *{ans}*")
            return (
                f"*Update {action_data['contact_name']}?*\n"
                + "\n".join(changes) + "\n\n"
                "Reply *Yes* to save or *No* to cancel."
            )

        if step == "confirm_update":
            if is_affirmative(ans):
                contact = await session.get(PgContact, action_data["contact_id"])
                if not contact:
                    return "Contact not found."
                changes = []
                if action_data.get("new_phone"):
                    contact.phone = action_data["new_phone"]
                    changes.append(f"phone → {action_data['new_phone']}")
                if action_data.get("new_notes"):
                    contact.contact_for = action_data["new_notes"]
                    changes.append(f"notes updated")
                import hashlib
                contact.unique_hash = hashlib.sha256(
                    f"{contact.phone}:{contact.name}".encode()
                ).hexdigest()
                return f"Updated *{contact.name}* — {', '.join(changes)}"
            if is_negative(ans):
                return "Cancelled."
            return "__KEEP_PENDING__Reply *Yes* to save or *No* to cancel."

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
        await _save_pending(ctx.phone, intent_type, action_data, choices, session, state="awaiting_choice")

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
    await _save_pending(ctx.phone, intent_type, action_data, choices, session, state="awaiting_choice")
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
        await session.commit()
        # Gap A fix: propagate the expected_checkout to the sheet so the
        # Event / Notice Date columns reflect the scheduled exit instantly
        # (previously only the nightly cron picked this up).
        try:
            from src.integrations.gsheets import sync_tenant_all_fields as _sync_all
            import asyncio as _aio
            _aio.create_task(_sync_all(tenancy.tenant_id))
        except Exception:
            pass
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
            try:
                from src.integrations.gsheets import _queue_failed_write
                _queue_failed_write("record_checkout", {
                    "room_number": room_obj.room_number, "tenant_name": tenant_name,
                    "notice_date": tenancy.notice_date.strftime("%d/%m/%Y") if tenancy.notice_date else None,
                })
            except Exception:
                pass

    # ── Checkout confirmation WhatsApp template (fire-and-forget) ──
    # Template: cozeevo_checkout_confirmation — 5 vars
    # Falls back to free-text inside the 24-hr session window if PENDING.
    try:
        tenant_obj = await session.get(Tenant, tenancy.tenant_id)
        tenant_phone = (tenant_obj.phone or "").strip() if tenant_obj else ""
        if tenant_phone:
            phone_wa = tenant_phone.lstrip("+").replace(" ", "")
            if not phone_wa.startswith("91"):
                phone_wa = "91" + phone_wa
            room_str = room_obj.room_number if room_obj else "-"
            date_str = checkout_date_val.strftime("%d %b %Y")
            if net > 0:
                refund_str = f"Rs.{int(net):,}"
                balance_str = "Rs.0 (settled)"
            elif net == 0:
                refund_str = "Rs.0"
                balance_str = "Rs.0 (settled)"
            else:
                refund_str = "Rs.0"
                balance_str = f"Rs.{int(abs(net)):,}"

            async def _send_checkout_msg() -> None:
                try:
                    from src.whatsapp.webhook_handler import (
                        _send_whatsapp_template, _send_whatsapp,
                    )
                    tpl_sent = await _send_whatsapp_template(
                        phone_wa,
                        "cozeevo_checkout_confirmation",
                        [tenant_name, room_str, date_str, refund_str, balance_str],
                    )
                    if not tpl_sent:
                        await _send_whatsapp(
                            phone_wa,
                            f"Hi {tenant_name}, your check-out is recorded.\n\n"
                            f"Room: {room_str}\n"
                            f"Checkout date: {date_str}\n"
                            f"Deposit refund: {refund_str}\n"
                            f"Final balance: {balance_str}\n\n"
                            f"Thank you for staying with Cozeevo — it was a pleasure having you. "
                            f"If you enjoyed your stay, we'd love a quick review and a recommendation "
                            f"to friends. And whenever you're in town again, our doors are open to "
                            f"welcome you back.",
                            intent="CHECKOUT_CONFIRMATION",
                        )
                except Exception as _e:
                    import logging as _log
                    _log.getLogger(__name__).warning(
                        "Checkout confirmation send failed: %s", _e
                    )

            asyncio.create_task(_send_checkout_msg())
    except Exception as _e:
        import logging as _log
        _log.getLogger(__name__).warning(
            "Checkout confirmation prep failed: %s", _e
        )

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

        # Google Sheets write-back
        gsheets_note = ""
        try:
            from src.integrations.gsheets import record_notice as gsheets_notice
            gs_r = await gsheets_notice(room_obj.room_number, tenant.name, notice_date_val.strftime("%d/%m/%Y"), last_day.strftime("%d/%m/%Y"))
            if gs_r.get("success"):
                gsheets_note = "\nSheet updated"
        except Exception:
            pass

        return (
            f"*Notice recorded — {tenant.name}* (Room {room_obj.room_number})\n"
            f"Notice date: {notice_date_val.strftime('%d %b %Y')}{assumed_note}\n"
            f"Expected exit: {last_day.strftime('%d %b %Y')}\n\n"
            f"{deposit_note}{gsheets_note}"
        )

    choices = _make_choices(rows)
    action_data = {
        "notice_date": notice_date_val.isoformat(),
        "last_day": last_day.isoformat(),
        "deposit_note": deposit_note,
    }
    await _save_pending(ctx.phone, "NOTICE_GIVEN", action_data, choices, session, state="awaiting_choice")
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

    # Google Sheets write-back
    gsheets_note = ""
    try:
        room_obj = await session.get(Room, tenancy.room_id)
        if room_obj:
            from src.integrations.gsheets import update_checkin as gsheets_update_checkin
            gs_r = await gsheets_update_checkin(
                room_obj.room_number, tenant_name, new_checkin.strftime("%d/%m/%Y")
            )
            if gs_r.get("success"):
                gsheets_note = "\nSheet updated"
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).error("GSheets update_checkin failed: %s", e)

    return (
        f"*Checkin updated — {tenant_name}*\n"
        f"Was: {old_checkin.strftime('%d %b %Y')}\n"
        f"Now: {new_checkin.strftime('%d %b %Y')}\n"
        f"{gsheets_note}\n\n"
        "Note: rent schedule rows are not auto-adjusted.\n"
        "Send *report* to verify dues."
    )


# ── Update checkout date ─────────────────────────────────────────────────────

async def _update_checkout_date(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Change an already-recorded checkout date for a tenant."""
    name     = entities.get("name", "").strip()
    room     = entities.get("room", "").strip()
    date_str = entities.get("date", "")

    if not name and not room:
        return "Whose checkout date? Say: *change checkout date [Name] to [date]*"

    rows: list = []
    search_term = name

    if name:
        # Search exited tenants first, then active (for expected_checkout)
        rows = await _find_tenants_by_name_any_status(name, session)
    if not rows and room:
        rows = await _find_tenants_by_room_any_status(room, session)
        search_term = f"Room {room}"

    if len(rows) == 0:
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)

    action_data = {"name_raw": search_term, "new_checkout": date_str}

    if len(rows) == 1:
        tenant, tenancy, room_obj = rows[0]
        choices = _make_choices(rows)
        if date_str:
            await _save_pending(ctx.phone, "UPDATE_CHECKOUT_DATE", action_data, choices, session)
            try:
                new_checkout = date.fromisoformat(date_str)
            except ValueError:
                return "Couldn't parse that date. Use: *20 Apr* or *20/04/2026*"
            old_checkout = tenancy.checkout_date
            old_str = old_checkout.strftime('%d %b %Y') if old_checkout else "not set"
            return (
                f"Update checkout for *{tenant.name}* (Room {room_obj.room_number})?\n\n"
                f"Current: {old_str}\n"
                f"New:     {new_checkout.strftime('%d %b %Y')}\n\n"
                f"Reply *1* to confirm."
            )
        else:
            # No date provided — ask for it
            await _save_pending(ctx.phone, "UPDATE_CHECKOUT_DATE_ASK", action_data, choices, session)
            old_checkout = tenancy.checkout_date
            old_str = old_checkout.strftime('%d %b %Y') if old_checkout else "not set"
            return (
                f"*{tenant.name}* (Room {room_obj.room_number})\n"
                f"Current checkout: {old_str}\n\n"
                f"*New checkout date?* (e.g. *15 April* or *15/04/2026*)"
            )

    choices = _make_choices(rows)
    await _save_pending(ctx.phone, "UPDATE_CHECKOUT_DATE", action_data, choices, session)
    action_label = f"update checkout to {date_str}" if date_str else "update checkout date"
    return _format_choices_message(search_term, choices, action_label)


async def _do_update_checkout_date(
    tenancy_id: int,
    tenant_name: str,
    new_checkout_str: str,
    session: AsyncSession,
) -> str:
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenancy:
        return "Tenancy record not found."

    try:
        new_checkout = date.fromisoformat(new_checkout_str)
    except (ValueError, TypeError):
        return "Invalid date. Please try again."

    if new_checkout <= tenancy.checkin_date:
        return (
            f"Cannot update: new checkout {new_checkout.strftime('%d %b %Y')} is on/before "
            f"checkin {tenancy.checkin_date.strftime('%d %b %Y')}."
        )

    old_checkout = tenancy.checkout_date
    old_str = old_checkout.strftime('%d %b %Y') if old_checkout else "not set"
    tenancy.checkout_date = new_checkout
    await session.flush()

    # Push Checkout Date to TENANTS sheet — dashboard occupancy / exit
    # KPIs read this column.
    try:
        import asyncio as _aio
        from src.integrations.gsheets import sync_tenant_all_fields as _sync
        _aio.create_task(_sync(tenancy.tenant_id))
    except Exception:
        pass  # fire-and-forget; DB is authoritative

    return (
        f"*Checkout date updated — {tenant_name}*\n"
        f"Was: {old_str}\n"
        f"Now: {new_checkout.strftime('%d %b %Y')}\n\n"
        "Send *report* to verify."
    )


async def _find_tenants_by_name_any_status(name: str, session: AsyncSession) -> list:
    """Find tenants by name across all statuses (active + exited)."""
    from sqlalchemy import or_
    rows = (await session.execute(
        select(Tenant, Tenancy, Room)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(or_(
            Tenant.name.ilike(f"%{name}%"),
            Tenant.name.ilike(f"{name}%"),
        ))
        .order_by(Tenancy.checkin_date.desc())
        .limit(10)
    )).all()
    return rows


async def _find_tenants_by_room_any_status(room: str, session: AsyncSession) -> list:
    """Find tenants by room across all statuses (active + exited)."""
    rows = (await session.execute(
        select(Tenant, Tenancy, Room)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(Room.room_number.ilike(room))
        .order_by(Tenancy.checkin_date.desc())
        .limit(10)
    )).all()
    return rows


# ── Other handlers ────────────────────────────────────────────────────────────

_SKIP_VALUES = {"skip", "none", "no", "nil", "-", "n/a", "na", "0"}

_MONTHS_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _get_ff(text: str, field: str) -> str:
    """Extract value from 'Field: value' or 'Field value' in multi-line form text."""
    # Try "Field: value" first
    m = re.search(rf"^{field}\s*[:=]\s*(.+?)$", text, re.I | re.M)
    if m:
        return m.group(1).strip()
    # Try "Field value" (no colon, just space)
    m = re.search(rf"^{field}\s+(.+?)$", text, re.I | re.M)
    if m:
        return m.group(1).strip()
    return ""


def _is_form_submission(text: str) -> bool:
    """Return True if message looks like a filled ADD_TENANT form."""
    # Check for label:value format (≥3 fields)
    keys = ["name", "phone", "room", "rent", "deposit", "checkin", "check.?in", "food",
            "discount", "advance", "maintenance", "maintence"]
    matches = sum(1 for k in keys if re.search(rf"^{k}\s*[:\s]", text, re.I | re.M))
    if matches >= 3:
        return True
    # Check for positional format: ≥5 lines, first line is text (name),
    # second line is digits (phone), third line is short digits (room)
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) >= 5:
        has_name = bool(lines[0]) and not lines[0][0].isdigit()
        has_phone = bool(re.match(r"^\d{7,12}$", lines[1])) if len(lines) > 1 else False
        has_room = bool(re.match(r"^\d{1,4}$", lines[2])) if len(lines) > 2 else False
        if has_name and has_phone and has_room:
            return True
    return False


def _parse_positional_form(text: str) -> dict:
    """Parse a line-by-line form without labels into field dict."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    result = {}
    if len(lines) < 5:
        return result

    result["name"] = lines[0]
    result["phone"] = lines[1]
    result["room"] = lines[2]

    # Remaining lines: match by content
    for line in lines[3:]:
        ll = line.lower().strip()
        # Discount
        if re.match(r"discount\s", ll, re.I):
            result["discount"] = re.sub(r"^discount\s*:?\s*", "", line, flags=re.I).strip()
        elif "until" in ll or "% off" in ll:
            result.setdefault("discount", line)
            # Also might contain rent: "11500 until June from July 12500"
            rent_m = re.match(r"(\d[\d,]+)", line)
            if rent_m and "rent" not in result:
                result["rent"] = line
        # Advance
        elif re.match(r"advance\s", ll, re.I):
            result["advance"] = re.sub(r"^advance\s*:?\s*", "", line, flags=re.I).strip()
        # Maintenance
        elif re.match(r"maint", ll, re.I):
            result["maintenance"] = re.sub(r"^(?:maintenance|maintence)\s*:?\s*", "", line, flags=re.I).strip()
        # Deposit
        elif re.match(r"deposit\s", ll, re.I):
            result["deposit"] = re.sub(r"^deposit\s*:?\s*", "", line, flags=re.I).strip()
        # Checkin
        elif re.match(r"check\s*in", ll, re.I):
            result["checkin"] = re.sub(r"^check\s*in\s*:?\s*", "", line, flags=re.I).strip()
        # Food
        elif ll in ("veg", "non veg", "non-veg", "egg", "none", "nonveg"):
            result["food"] = line
        elif re.match(r"food\s", ll, re.I):
            result["food"] = re.sub(r"^food\s*:?\s*", "", line, flags=re.I).strip()
        # Pure number = rent (if not yet assigned)
        elif re.match(r"^\d[\d,]*$", ll) and "rent" not in result:
            result["rent"] = line

    return result


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


async def _finalize_form_checkin(
    action_data: dict, pending, session: AsyncSession, sharing_type: str = "double",
) -> str:
    """After all validations pass, create tenant via _process_tenant_form pipeline."""
    extracted = action_data.get("extracted", {})

    # Build form lines for _process_tenant_form
    form_lines = [
        f"Name: {extracted.get('name', '')}",
        f"Phone: {extracted.get('phone', '')}",
        f"Room: {action_data.get('room_number', extracted.get('room_number', ''))}",
        f"Rent: {extracted.get('monthly_rent', 'skip')}",
        f"Deposit: {extracted.get('deposit', 'skip')}",
        f"Advance: {extracted.get('advance', 'skip')}",
        f"Maintenance: {extracted.get('maintenance', 'skip')}",
        f"Checkin: {extracted.get('date_of_admission', '')}",
        f"Food: {extracted.get('food_preference', 'none')}",
        f"Gender: {extracted.get('gender', '')}",
    ]

    # Build notes from agreed terms/remarks
    remarks_parts = []
    if extracted.get("rent_remarks"):
        remarks_parts.append(f"Rent: {extracted['rent_remarks']}")
    if extracted.get("deposit_remarks"):
        remarks_parts.append(f"Deposit: {extracted['deposit_remarks']}")
    if extracted.get("maintenance_remarks"):
        remarks_parts.append(f"Maintenance: {extracted['maintenance_remarks']}")
    agreed_terms = " | ".join(remarks_parts) if remarks_parts else ""
    if agreed_terms:
        form_lines.append(f"Notes: {agreed_terms}")

    form_msg = "\n".join(form_lines)

    # Mark this pending as resolved before creating new one
    pending.resolved = True

    from src.whatsapp.role_service import get_caller_context
    ctx = await get_caller_context(pending.phone, session)

    result = await _process_tenant_form(form_msg, ctx, session)

    # Store KYC extra + sharing type in the new pending action
    from src.whatsapp.chat_api import _get_active_pending
    new_pending = await _get_active_pending(pending.phone, session)

    # Build KYC dict
    kyc_extra = {
        "father_name": extracted.get("father_name", ""),
        "father_phone": extracted.get("father_phone", ""),
        "date_of_birth": extracted.get("date_of_birth", ""),
        "permanent_address": extracted.get("permanent_address", ""),
        "emergency_contact": extracted.get("emergency_contact", ""),
        "emergency_relationship": extracted.get("emergency_relationship", ""),
        "email": extracted.get("email", ""),
        "occupation": extracted.get("occupation", ""),
        "educational_qualification": extracted.get("educational_qualification", ""),
        "office_address": extracted.get("office_address", ""),
        "office_phone": extracted.get("office_phone", ""),
        "id_proof_type": extracted.get("id_proof_type", ""),
        "id_proof_number": extracted.get("id_proof_number", ""),
    }

    # Only show KYC fields NOT already in the main form display (format_extracted_data)
    # office_address, office_phone are in the main display — skip to avoid doubling
    extra_fields = [f"{l}: {kyc_extra[k]}" for k, l in [
        ("father_name", "Father"), ("father_phone", "Father Phone"),
        ("date_of_birth", "DOB"), ("permanent_address", "Address"),
        ("emergency_contact", "Emergency"), ("emergency_relationship", "Relationship"),
        ("email", "Email"), ("occupation", "Occupation"),
        ("educational_qualification", "Education"),
        ("id_proof_type", "ID Type"), ("id_proof_number", "ID Number"),
    ] if kyc_extra.get(k)]

    if new_pending and new_pending.intent in ("CONFIRM_ADD_TENANT",):
        import json as _j
        ad = _j.loads(new_pending.action_data or "{}")
        ad["_kyc_extra"] = kyc_extra
        ad["_sharing_type"] = sharing_type
        ad["form_image_path"] = action_data.get("form_image_path", "")
        ad["advance_mode"] = extracted.get("advance_mode", "")
        new_pending.action_data = _j.dumps(ad)

    if extra_fields:
        result += "\n\n_KYC data (saved on confirm):_\n" + "\n".join(extra_fields)

    result += f"\n_Sharing: {sharing_type}_"

    return result


async def _process_checkout_from_form(
    extracted: dict, tenant, tenancy, room_obj, action_data: dict, pending, session: AsyncSession,
) -> str:
    """Process checkout from extracted form data."""
    from src.whatsapp.intent_detector import _extract_date_entity
    from src.database.models import Document, DocumentType, Refund

    # Parse checkout date
    checkout_str = extracted.get("checkout_date", "")
    checkout_iso = _extract_date_entity(checkout_str) if checkout_str else None
    if not checkout_iso:
        checkout_date = date.today()
    else:
        checkout_date = date.fromisoformat(checkout_iso)

    # Update tenancy
    tenancy.status = TenancyStatus.exited
    tenancy.checkout_date = checkout_date

    # Parse refund info
    refund_amount = 0
    try:
        refund_amount = float(re.sub(r"[^0-9.]", "", extracted.get("refund_amount", "") or "0"))
    except (ValueError, TypeError):
        pass

    deposit = float(tenancy.security_deposit or 0)
    deductions = 0
    try:
        deductions = float(re.sub(r"[^0-9.]", "", extracted.get("deductions", "") or "0"))
    except (ValueError, TypeError):
        pass

    refund_mode = (extracted.get("refund_mode", "") or "cash").lower()
    if refund_mode not in ("cash", "upi", "bank"):
        refund_mode = "cash"

    # Create refund record if refund amount > 0
    if refund_amount > 0:
        from decimal import Decimal
        mode_map = {"cash": PaymentMode.cash, "upi": PaymentMode.upi, "bank": PaymentMode.upi}
        session.add(Refund(
            tenancy_id=tenancy.id,
            amount=Decimal(str(refund_amount)),
            refund_date=checkout_date,
            payment_mode=mode_map.get(refund_mode, PaymentMode.cash),
            reason="deposit refund",
            notes=f"Deposit: {int(deposit)}, Deductions: {int(deductions)}. {extracted.get('deductions_reason', '')}".strip(),
        ))

    # Save checkout form as document
    form_path = action_data.get("form_image_path", "")
    if form_path:
        session.add(Document(
            doc_type=DocumentType.checkout_form,
            file_path=form_path,
            original_name=f"checkout_{tenant.name}_{room_obj.room_number}",
            mime_type="image/jpeg",
            tenant_id=tenant.id,
            tenancy_id=tenancy.id,
            uploaded_by=pending.phone,
            notes=f"Checkout form - {tenant.name} - Room {room_obj.room_number} - {checkout_date.strftime('%d %b %Y')}",
        ))

    # Google Sheets update
    gsheets_note = ""
    try:
        from src.integrations.gsheets import record_checkout as gsheets_checkout
        notice_str = tenancy.notice_date.strftime("%d/%m/%Y") if tenancy.notice_date else None
        gs_r = await gsheets_checkout(
            room_obj.room_number,
            tenant.name,
            notice_str,
            checkout_date.strftime("%d/%m/%Y"),
        )
        if gs_r.get("success"):
            gsheets_note = "\nSheet updated"

        # Update refund amount in Sheet
        if refund_amount > 0:
            from src.integrations.gsheets import _get_worksheet_sync, _find_row_in_tenants, T_REFUND_AMOUNT, T_REFUND_STATUS
            import asyncio, gspread as _gspread
            def _update_refund_sync():
                ws = _get_worksheet_sync("TENANTS")
                found = _find_row_in_tenants(ws, room_obj.room_number, tenant.name)
                if found:
                    row, _ = found
                    ws.batch_update([
                        {"range": _gspread.utils.rowcol_to_a1(row, T_REFUND_STATUS + 1), "values": [[f"{refund_mode} refunded"]]},
                        {"range": _gspread.utils.rowcol_to_a1(row, T_REFUND_AMOUNT + 1), "values": [[refund_amount]]},
                    ], value_input_option="USER_ENTERED")
            await asyncio.to_thread(_update_refund_sync)
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).error("GSheets checkout update failed: %s", e)

    pending.resolved = True

    # Verification checklist
    room_check = extracted.get("room_investigation", "").lower()
    room_key = extracted.get("room_key_returned", "").lower()
    wardrobe_key = extracted.get("wardrobe_key_returned", "").lower()
    biometric = extracted.get("biometric_removed", "").lower()

    checklist = []
    if room_check == "ok":
        checklist.append("Room: OK")
    elif room_check:
        checklist.append(f"Room: {room_check.upper()}")
    if room_key:
        checklist.append(f"Room key: {'returned' if room_key == 'yes' else 'NOT returned'}")
    if wardrobe_key:
        checklist.append(f"Wardrobe key: {'returned' if wardrobe_key == 'yes' else 'NOT returned'}")
    if biometric:
        checklist.append(f"Biometric: {'removed' if biometric == 'yes' else 'NOT removed'}")

    result = (
        f"*Checkout Complete — {tenant.name}*\n"
        f"Room: {room_obj.room_number}\n"
        f"Exit: {checkout_date.strftime('%d %b %Y')}\n\n"
        f"Deposit: Rs.{int(deposit):,}\n"
        f"Deductions: Rs.{int(deductions):,}\n"
        f"*Refund: Rs.{int(refund_amount):,}* ({refund_mode})\n\n"
        + ("\n".join(checklist) + "\n\n" if checklist else "")
        + f"Saved to DB.{gsheets_note}"
    )

    # Start receipt collection for refund slip
    if refund_amount > 0:
        from src.whatsapp.handlers._shared import _save_pending
        await _save_pending(pending.phone, "COLLECT_RECEIPT", {
            "tenant_id": tenant.id,
            "tenancy_id": tenancy.id,
            "tenant_name": tenant.name,
            "room_number": room_obj.room_number,
            "receipt_note": f"Refund Rs.{int(refund_amount):,} {refund_mode} - {tenant.name} - Room {room_obj.room_number} checkout",
        }, [], session)
        result += "\n\nSend photo of *refund receipt slip* to save, or say *skip*."

    return result


async def _extract_checkout_from_image(
    media_id: str, media_mime: str, ctx: CallerContext, session: AsyncSession,
) -> str:
    """Download checkout form image, extract data via Haiku, show confirmation."""
    from src.whatsapp.webhook_handler import _fetch_media_bytes
    from src.whatsapp.form_extractor import extract_checkout_form, format_checkout_data
    from src.whatsapp.handlers._shared import _save_pending
    from src.whatsapp.media_handler import MEDIA_DIR
    from pathlib import Path

    image_bytes = await _fetch_media_bytes(media_id)
    if not image_bytes:
        return "Could not download the image. Please try again."

    # Save the form image
    save_dir = MEDIA_DIR / "checkout_forms" / datetime.now().strftime("%Y-%m")
    save_dir.mkdir(parents=True, exist_ok=True)
    ext = ".png" if "png" in (media_mime or "") else ".webp" if "webp" in (media_mime or "") else ".jpg"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    form_path = save_dir / f"checkout_{ts}{ext}"
    form_path.write_bytes(image_bytes)
    form_rel_path = str(form_path.relative_to(MEDIA_DIR))

    result = await extract_checkout_form(image_bytes, media_mime)
    data = result.get("result")

    if not data:
        return "Could not extract data from the checkout form. Please use the step-by-step flow:\n\nSend *record checkout [name]*"

    action_data = {
        "step": "confirm_checkout_extracted",
        "extracted": data,
        "form_image_path": form_rel_path,
    }
    await _save_pending(ctx.phone, "CHECKOUT_FORM_CONFIRM", action_data, [], session)

    msg = format_checkout_data(data, "haiku")
    msg += "\n\nReply *yes* to process checkout, *no* to cancel."
    msg += "\nTo edit: *edit refund_amount 15000*"
    return msg


async def _extract_tenant_from_image(
    media_id: str, media_mime: str, ctx: CallerContext, session: AsyncSession,
) -> str:
    """Download form image, extract data via Claude Haiku, show confirmation."""
    from src.whatsapp.webhook_handler import _fetch_media_bytes
    from src.whatsapp.form_extractor import extract_form_from_image, format_extracted_data
    from src.whatsapp.handlers._shared import _save_pending

    image_bytes = await _fetch_media_bytes(media_id)
    if not image_bytes:
        return "Could not download the image. Please try again."

    # Save the form image to disk immediately
    from src.whatsapp.media_handler import MEDIA_DIR
    from pathlib import Path
    save_dir = MEDIA_DIR / "reg_forms" / datetime.now().strftime("%Y-%m")
    save_dir.mkdir(parents=True, exist_ok=True)
    ext = {".jpeg": ".jpg"}.get("", ".jpg")
    if "png" in (media_mime or ""):
        ext = ".png"
    elif "webp" in (media_mime or ""):
        ext = ".webp"
    else:
        ext = ".jpg"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    form_path = save_dir / f"reg_form_{ts}{ext}"
    form_path.write_bytes(image_bytes)
    form_rel_path = str(form_path.relative_to(MEDIA_DIR))

    result = await extract_form_from_image(image_bytes, media_mime)
    data = result.get("result")

    if not data:
        return "Could not extract data from the image. Please try the step-by-step flow instead:\n\nSend *add tenant* again without an image."

    action_data = {
        "step": "confirm_extracted",
        "extracted": data,
        "provider": "haiku",
        "form_image_path": form_rel_path,
    }
    await _save_pending(ctx.phone, "FORM_EXTRACT_CONFIRM", action_data, [], session)

    msg = format_extracted_data(data, "haiku")
    msg += "\n\nReply *yes* to save, *no* to cancel."
    msg += "\nTo edit a field: *edit name Rahul Sharma*"
    return msg


async def _add_tenant_prompt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    msg = entities.get("description", "").strip()

    # ── Image-based form extraction ───────────────────────────────────────
    media_id = entities.get("_media_id")
    media_type = entities.get("_media_type")
    media_mime = entities.get("_media_mime")
    if media_id and media_type == "image":
        return await _extract_tenant_from_image(media_id, media_mime or "image/jpeg", ctx, session)

    # ── Detect filled form submission ──────────────────────────────────────
    if _is_form_submission(msg):
        # Check if positional (no labels) — convert to labeled format
        pos = _parse_positional_form(msg)
        if pos and pos.get("name") and pos.get("phone") and pos.get("room"):
            # Rebuild as labeled form for _process_tenant_form
            rebuilt_lines = []
            rebuilt_lines.append(f"Name: {pos.get('name', '')}")
            rebuilt_lines.append(f"Phone: {pos.get('phone', '')}")
            rebuilt_lines.append(f"Room: {pos.get('room', '')}")
            rebuilt_lines.append(f"Rent: {pos.get('rent', 'skip')}")
            rebuilt_lines.append(f"Discount: {pos.get('discount', 'skip')}")
            rebuilt_lines.append(f"Deposit: {pos.get('deposit', 'skip')}")
            rebuilt_lines.append(f"Advance: {pos.get('advance', 'skip')}")
            rebuilt_lines.append(f"Maintenance: {pos.get('maintenance', 'skip')}")
            rebuilt_lines.append(f"Checkin: {pos.get('checkin', '')}")
            rebuilt_lines.append(f"Food: {pos.get('food', 'none')}")
            msg = "\n".join(rebuilt_lines)
        return await _process_tenant_form(msg, ctx, session)

    # ── No step-by-step — use digital form or image ──────────────────────
    return (
        "*New tenant check-in*\n\n"
        "You can:\n"
        "1. Send a *photo of the registration form* to auto-extract details\n"
        "2. Use the *digital onboarding form* at /admin/onboarding to create a link"
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
    if not name:    errors.append("Name")
    if not phone_raw: errors.append("Phone")
    if not room_str:  errors.append("Room number")
    if not rent_str:  errors.append("Rent amount")
    if not checkin_s: errors.append("Checkin date")
    if errors:
        # Save partial data so context is held
        partial = {
            "step": "collect_missing", "missing": errors,
            "name": name, "phone_raw": phone_raw, "room_str": room_str,
            "rent_str": rent_str, "discount_s": discount_s, "deposit_s": deposit_s,
            "advance_s": advance_s, "maint_s": maint_s, "checkin_s": checkin_s,
            "food_s": food_s, "original_msg": msg,
        }
        session.add(PendingAction(
            phone=ctx.phone, intent="ADD_TENANT_INCOMPLETE",
            action_data=json.dumps(partial), choices=json.dumps([]),
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        ))
        return ("*Missing info:*\n"
                + "\n".join(f"• {e}" for e in errors)
                + "\n\nPlease send the missing details (e.g. just type the value).\n"
                + "Or send *cancel* to start over.")

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

    # Room occupancy info
    room_info = f"{room_row.room_number}"
    rt = room_row.room_type
    rt_str = rt.value if hasattr(rt, 'value') else str(rt or "")
    max_occ = room_row.max_occupancy or 1
    occ_line = ""
    if occupants:
        occ_tenant_ids = [tncy.tenant_id for tncy in occupants]
        occ_name_rows = await session.execute(select(Tenant.name).where(Tenant.id.in_(occ_tenant_ids)))
        occ_names = list(occ_name_rows.scalars().all())
        occ_line = f"\nCurrent occupants: {', '.join(occ_names)} ({len(occupants)}/{max_occ})"
    room_info += f" ({rt_str} sharing, {len(occupants)}/{max_occ} occupied)"

    # Gender check for warnings
    gender_s = _get_ff(msg, "gender").lower() if _get_ff(msg, "gender") else ""
    gender_warn = ""
    if gender_s and occupants:
        # Check if existing occupants have a different gender
        occ_t_ids = [tncy.tenant_id for tncy in occupants]
        occ_tenants_res = await session.execute(select(Tenant.gender).where(Tenant.id.in_(occ_t_ids)))
        occ_genders = [g for g in occ_tenants_res.scalars().all() if g]
        if occ_genders and gender_s not in ("", "none"):
            if any(g != gender_s for g in occ_genders):
                gender_warn = f"\n*Warning:* Gender mismatch — new tenant is {gender_s}, existing occupant(s) are {', '.join(set(occ_genders))}"

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
        state="awaiting_confirmation",  # routed via conversation framework
        action_data=json.dumps(pending_data),
        choices=json.dumps([]),
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    ))

    return (
        f"*Confirm New Tenant?*{date_warn}{gender_warn}\n\n"
        f"Name: {name}\n"
        f"Phone: {phone}\n"
        f"Room: {room_info}{occ_line}\n"
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
    gender = data.get("gender", "")
    food_pref = data.get("food_pref", "")
    if food_pref in ("none", "skip"):
        food_pref = ""
    if existing_tid:
        tenant = await session.get(Tenant, existing_tid)
    else:
        tenant = await session.scalar(select(Tenant).where(Tenant.phone == phone))
    if not tenant:
        tenant = Tenant(name=name, phone=phone, gender=gender or None, food_preference=food_pref or None)
        session.add(tenant)
        await session.flush()
    else:
        if gender and not tenant.gender:
            tenant.gender = gender
        if food_pref and not tenant.food_preference:
            tenant.food_preference = food_pref

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

        from src.services.rent_schedule import first_month_rent_due
        session.add(RentSchedule(
            tenancy_id      = tenancy.id,
            period_month    = period,
            rent_due        = first_month_rent_due(tenancy, period),
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
        adv_mode_str = data.get("advance_mode", "")
        adv_mode = PaymentMode.upi if adv_mode_str == "upi" else PaymentMode.cash
        session.add(Payment(
            tenancy_id   = tenancy.id,
            amount       = advance,
            payment_date = checkin_date,
            payment_mode = adv_mode,
            for_type     = PaymentFor.booking,
            period_month = checkin_date.replace(day=1),
            notes        = f"Booking advance at check-in ({adv_mode_str})",
        ))

    # ── Google Sheets write-back (fire-and-forget) ──
    gsheets_note = ""
    try:
        room_obj = await session.get(Room, room_id)
        if room_obj:
            from src.integrations.gsheets import add_tenant as gsheets_add
            # Get building from property — use DB name as-is
            building = data.get("building", "")
            if not building and room_obj.property_id:
                prop = await session.get(Property, room_obj.property_id)
                building = prop.name if prop else ""
            floor_val = str(room_obj.floor or "")
            rt = data.get("sharing", "") or room_obj.room_type
            sharing = rt.value if hasattr(rt, 'value') else str(rt or "")
            kyc = data.get("_kyc_extra") or {}
            gs_r = await gsheets_add(
                room_number=room_number, name=name, phone=phone,
                gender=data.get("gender", ""), building=building,
                floor=floor_val, sharing=sharing,
                checkin=checkin_date.strftime("%d/%m/%Y"),
                agreed_rent=float(base_rent), deposit=float(deposit),
                booking=float(advance), maintenance=float(maintenance),
                notes=data.get("notes", ""),
                dob=kyc.get("date_of_birth", ""),
                father_name=kyc.get("father_name", ""),
                father_phone=kyc.get("father_phone", ""),
                address=kyc.get("permanent_address", ""),
                emergency_contact=kyc.get("emergency_contact", ""),
                emergency_relationship=kyc.get("emergency_relationship", ""),
                email=kyc.get("email", ""),
                occupation=kyc.get("occupation", ""),
                education=kyc.get("educational_qualification", ""),
                office_address=kyc.get("office_address", ""),
                office_phone=kyc.get("office_phone", ""),
                id_type=kyc.get("id_proof_type", ""),
                id_number=kyc.get("id_proof_number", ""),
                food_pref=data.get("food_pref", ""),
                entered_by=data.get("entered_by", "bot"),
                advance_amount=float(advance),
                advance_mode=data.get("advance_mode", ""),
            )
            if gs_r.get("success"):
                gsheets_note = "\nSheet updated"
            elif gs_r.get("error"):
                import logging as _log
                _log.getLogger(__name__).warning("GSheets add_tenant: %s", gs_r["error"])
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).error("GSheets add_tenant failed: %s", e)
        try:
            from src.integrations.gsheets import _queue_failed_write
            _queue_failed_write("add_tenant", {
                "room_number": room_number, "name": name, "phone": phone,
                "gender": data.get("gender", ""), "building": data.get("building", ""),
                "floor": "", "sharing": data.get("sharing", ""),
                "checkin": checkin_date.strftime("%d/%m/%Y"),
                "agreed_rent": float(base_rent), "deposit": float(deposit),
                "booking": float(advance), "maintenance": float(maintenance),
                "notes": data.get("notes", ""),
            })
        except Exception:
            pass

    # Auto-chain: start collect rent flow for this tenant
    # Save pending so next message goes into COLLECT_RENT_STEP
    from src.whatsapp.handlers._shared import _save_pending as _sp
    # We need the caller phone — get it from the pending action that triggered this
    # The caller phone is passed via the session context, but we don't have it here.
    # Instead, append a prompt to the reply — the next message will trigger collect rent.

    return (
        f"*Tenant saved — {name}* ✅\n\n"
        f"Room: {room_number}\n"
        f"Rent: Rs.{int(base_rent):,}/month\n"
        f"Deposit: Rs.{int(deposit):,}\n"
        f"Checkin: {checkin_date.strftime('%d %b %Y')}\n"
        + (f"Advance logged: Rs.{int(advance):,}\n" if advance > 0 else "")
        + "Rent schedule created."
        + gsheets_note
        + "\n\nSay *collect rent* to log their first payment."
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
        f"Type naturally or try these, {first}:\n\n"
        "*Rent & Payments*\n"
        "  _collect rent_ — step-by-step\n"
        "  _Raj paid 14000 cash_ — quick log\n"
        "  _who owes_ — unpaid list\n"
        "  _report_ — monthly summary\n"
        "  _void payment Raj_ — reverse entry\n\n"
        "*Check-in & Checkout*\n"
        "  _add tenant_ — new check-in\n"
        "  _add tenant_ + photo — auto-extract from form\n"
        "  _checkout_ + photo — checkout via form\n"
        "  _checkout Raj_ — manual exit process\n"
        "  _Raj gave notice_ — record notice\n\n"
        "*Rooms & Tenants*\n"
        "  _Raj balance_ — payment history\n"
        "  _room 422_ — who's in this room\n"
        "  _vacant rooms_ — all empty beds\n"
        "  _transfer Raj to 305_ — room change\n\n"
        "*Expenses & Complaints*\n"
        "  _log EB bill_ + photo — log expense\n"
        "  _no water room 415_ — register complaint\n"
        "  _plumber fixed 201_ — update complaint\n\n"
        "*Other*\n"
        "  _remind unpaid_ — send reminders\n"
        "  _rules_ — PG rules & regulations\n"
        "  _cancel_ — stop any form mid-way"
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

    # Fallback: "transfer Arjun to 307" → room parsed as amount, extract via regex
    if not to_room:
        desc = entities.get("description", "") or entities.get("_raw_message", "")
        _to_match = re.search(r"(?:to|->|→)\s*(?:room\s*)?(\d{2,4}[A-Za-z]?)", desc, re.I)
        if _to_match:
            to_room = _to_match.group(1)

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

    return await _finalize_room_transfer(
        ctx.phone, tenancy.id, tenant.name,
        current_room.room_number, to_room, session,
    )


async def _finalize_room_transfer(
    phone: str, tenancy_id: int, tenant_name: str,
    from_room: str, to_room: str, session: AsyncSession,
) -> str:
    """Shared tail of room-transfer flow: validate destination, check vacancy,
    fetch current rent/deposit, save ROOM_TRANSFER pending, return confirm prompt.

    Used by:
      - _room_transfer_prompt (direct single-match path)
      - resolve_pending_action ROOM_TRANSFER_WHO branch (after tenant picked)
      - resolve_pending_action ROOM_TRANSFER_DEST branch (after room typed)
    """
    tenancy = await session.get(Tenancy, tenancy_id)
    if not tenancy:
        return "Tenancy record not found."

    new_room = await session.scalar(
        select(Room).where(Room.room_number == to_room.upper(), Room.active == True)
    )
    if not new_room:
        return f"Room *{to_room}* not found. Check the room number and try again."

    occupied_rows = (await session.execute(
        select(Tenant.name, Tenant.phone, Tenancy.id).where(
            Tenancy.room_id == new_room.id,
            Tenancy.status == TenancyStatus.active,
            Tenancy.tenant_id == Tenant.id,
        )
    )).all()
    if occupied_rows:
        occ_lines = "\n".join(f"  - {r[0]} ({r[1]})" for r in occupied_rows)
        return (
            f"Room *{to_room}* is occupied by:\n{occ_lines}\n\n"
            f"Options:\n"
            f"*1.* Checkout the current occupant(s) first, then retry\n"
            f"*2.* Pick a different room\n\n"
            f"_I can't auto-swap yet — checkout the occupant first, then move {tenant_name}._"
        )

    rs = await session.scalar(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy.id,
            RentSchedule.period_month >= date.today().replace(day=1),
        ).order_by(RentSchedule.period_month.asc()).limit(1)
    )
    current_rent = int(rs.rent_due) if rs else int(tenancy.booking_amount or 0)
    current_deposit = int(tenancy.security_deposit or 0)

    action_data = {
        "tenancy_id": tenancy.id,
        "tenant_name": tenant_name,
        "from_room": from_room,
        "to_room_id": new_room.id,
        "to_room_number": new_room.room_number,
        "current_rent": current_rent,
        "current_deposit": current_deposit,
        "step": "confirm",
    }
    await _save_pending(phone, "ROOM_TRANSFER", action_data, [], session)
    return (
        f"*Room Transfer — {tenant_name}*\n"
        f"From: Room *{from_room}*\n"
        f"To:   Room *{new_room.room_number}*\n"
        f"Current rent: Rs.{current_rent:,}/mo\n\n"
        "*Rent for new room?*\n"
        f"*1.* Keep current (Rs.{current_rent:,})\n"
        "*2.* Enter new amount\n\n"
        "or *no* to cancel."
    )


async def _do_room_transfer(action_data: dict, session: AsyncSession) -> str:
    tenancy = await session.get(Tenancy, action_data["tenancy_id"])
    if not tenancy:
        return "Tenancy record not found."

    old_room = action_data["from_room"]
    new_room_number = action_data["to_room_number"]
    tenant_name = action_data["tenant_name"]

    # Update DB
    tenancy.room_id = action_data["to_room_id"]

    # Update rent if changed
    new_rent = action_data.get("new_rent")
    if new_rent:
        tenancy.agreed_rent = Decimal(str(new_rent))

    # Audit log
    from src.database.models import AuditLog
    session.add(AuditLog(
        changed_by=action_data.get("changed_by", "system"),
        entity_type="tenancy",
        entity_id=tenancy.id,
        entity_name=tenant_name,
        field="room_id",
        old_value=old_room,
        new_value=new_room_number,
        room_number=new_room_number,
        source="whatsapp",
        note=f"Room transfer: {old_room} -> {new_room_number}",
    ))

    # Google Sheet sync — fire-and-forget but covers BOTH tabs:
    # 1. TENANTS master tab Room column (uses old name match, sets new room)
    # 2. Trigger full monthly sheet sync (handles row-key change correctly,
    #    far easier than patching cell-by-cell when the lookup key itself
    #    is what's changing). Same approach for rent if changed.
    gsheets_note = ""
    import asyncio as _aio
    from src.integrations import gsheets as _gs
    try:
        _aio.create_task(_gs.update_tenants_tab_field(
            old_room, tenant_name, "room", new_room_number
        ))
        if new_rent:
            _aio.create_task(_gs.update_tenants_tab_field(
                new_room_number, tenant_name, "agreed_rent", int(new_rent)
            ))
        today = date.today()
        _gs.trigger_monthly_sheet_sync(today.month, today.year)
        gsheets_note = "\nSheet update queued"
    except Exception:
        pass

    rent_note = ""
    if new_rent:
        rent_note = f"\nNew rent: Rs.{int(new_rent):,}/mo"

    return (
        f"Room transferred — *{tenant_name}*\n"
        f"Room *{old_room}* -> Room *{new_room_number}*"
        f"{rent_note}{gsheets_note}"
    )


async def _query_beds_by_gender(gender: str, building_filter: str | None, session: AsyncSession) -> str:
    """Show rooms with empty beds where current occupant(s) match the given gender."""
    from collections import defaultdict
    from src.database.models import Property

    # Get all multi-bed rooms (double/triple) with their occupants
    q = (
        select(Room, Property.name, Tenant.name, Tenant.gender)
        .join(Property, Property.id == Room.property_id)
        .join(Tenancy, and_(Tenancy.room_id == Room.id, Tenancy.status == TenancyStatus.active))
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .where(
            Room.active == True,
            Room.is_staff_room == False,
            Room.max_occupancy > 1,  # only multi-bed rooms
        )
    )
    if building_filter:
        q = q.where(Property.name.ilike(f"%{building_filter}%"))
    q = q.order_by(Property.name, Room.room_number)

    rows = (await session.execute(q)).all()

    # Group by room: {room_id: {room, prop, occupants: [(name, gender)]}}
    room_data: dict = {}
    for room, prop_name, tenant_name, tenant_gender in rows:
        if room.id not in room_data:
            room_data[room.id] = {
                "room": room,
                "prop": prop_name,
                "occupants": [],
            }
        room_data[room.id]["occupants"].append((tenant_name, (tenant_gender or "").lower()))

    # Day-wise guests per room (reduce free bed count)
    from src.database.models import DaywiseStay
    from datetime import date as _date
    _today = _date.today()
    dw_per_room = {row[0]: row[1] for row in (await session.execute(
        select(DaywiseStay.room_number, func.count())
        .where(
            DaywiseStay.checkin_date <= _today,
            DaywiseStay.checkout_date >= _today,
            DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
        )
        .group_by(DaywiseStay.room_number)
    )).all()}

    # Premium rooms: fully occupied, no free beds
    premium_rooms = {row[0] for row in (await session.execute(
        select(Tenancy.room_id).where(
            Tenancy.status == TenancyStatus.active,
            Tenancy.room_id.isnot(None),
            Tenancy.sharing_type == "premium",
        )
    )).all()}

    # Filter: rooms where occupancy < max AND at least one occupant matches gender
    matching = []
    for rid, data in room_data.items():
        room = data["room"]
        if rid in premium_rooms:
            continue  # premium = both beds taken, not sellable
        occupants = data["occupants"]
        max_occ = room.max_occupancy or 2
        dw_count = dw_per_room.get(room.room_number, 0)
        total_occupied = len(occupants) + dw_count
        if total_occupied < max_occ:
            genders = [g for _, g in occupants]
            if gender in genders:
                free_beds = max_occ - total_occupied
                matching.append({
                    "room": room.room_number,
                    "prop": data["prop"],
                    "occupants": occupants,
                    "free_beds": free_beds,
                    "max": max_occ,
                })

    # Gender query: only show rooms with a matching gender occupant, not fully vacant rooms
    gender_label = gender.capitalize()
    bld_label = f" in {building_filter}" if building_filter else ""

    if not matching:
        return f"No rooms with a {gender_label} occupant and an empty bed{bld_label}."

    lines = [f"*Beds available for {gender_label}{bld_label}*\n"]
    for m in sorted(matching, key=lambda x: x["room"]):
        block = "THOR" if "THOR" in m["prop"].upper() else "HULK"
        names = ", ".join(n for n, _ in m["occupants"])
        lines.append(f"  Room *{m['room']}* ({block}) — {names} | *{m['free_beds']} bed free*")

    total_beds = sum(m["free_beds"] for m in matching)
    lines.append(f"\n*Total: {total_beds} beds with {gender_label} roommate*")

    return "\n".join(lines)


async def _query_vacant_rooms(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show ALL empty beds — fully vacant rooms + partial rooms with free beds."""
    from collections import defaultdict
    from src.database.models import Property

    # Detect building + gender filter from message
    desc = (entities.get("description") or entities.get("_raw_message") or "").lower()
    building_filter = None
    if "thor" in desc:
        building_filter = "THOR"
    elif "hulk" in desc:
        building_filter = "HULK"

    gender_filter = None
    if any(w in desc for w in ("female", "girl", "woman", "women", "ladies", "lady")):
        gender_filter = "female"
    elif any(w in desc for w in ("male", "boy", "man", "men", "gents")):
        gender_filter = "male"

    if gender_filter:
        return await _query_beds_by_gender(gender_filter, building_filter, session)

    # ── Get all revenue rooms with their tenant counts ────────────────────
    room_q = (
        select(Room, Property.name)
        .join(Property, Property.id == Room.property_id)
        .where(Room.active == True, Room.is_staff_room == False)
    )
    if building_filter:
        room_q = room_q.where(Property.name.ilike(f"%{building_filter}%"))
    room_q = room_q.order_by(Property.name, Room.room_number)
    all_rows = (await session.execute(room_q)).all()

    # Count active + no-show tenants per room (no-shows are booked, bed reserved)
    tenant_q = (
        select(Tenancy.room_id, func.count().label("cnt"))
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
            Tenancy.room_id.isnot(None),
            Room.is_staff_room == False,
        )
        .group_by(Tenancy.room_id)
    )
    tenant_counts = {row[0]: row[1] for row in (await session.execute(tenant_q)).all()}

    # Count day-wise guests currently occupying beds (checkin <= today <= checkout)
    from src.database.models import DaywiseStay
    from datetime import date
    today = date.today()
    dw_q = (
        select(DaywiseStay.room_number, func.count().label("cnt"))
        .where(
            DaywiseStay.checkin_date <= today,
            DaywiseStay.checkout_date >= today,
            DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
        )
        .group_by(DaywiseStay.room_number)
    )
    daywise_counts = {row[0]: row[1] for row in (await session.execute(dw_q)).all()}

    # Map room_number -> room_id for daywise stays
    room_number_to_id = {r.room_number: r.id for r, _ in all_rows}
    for rn, cnt in daywise_counts.items():
        rid = room_number_to_id.get(rn)
        if rid:
            tenant_counts[rid] = tenant_counts.get(rid, 0) + cnt

    # Premium rooms: 1 person = BOTH beds booked, second bed NOT sellable
    premium_room_ids = {row[0] for row in (await session.execute(
        select(Tenancy.room_id).where(
            Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
            Tenancy.room_id.isnot(None),
            Tenancy.sharing_type == "premium",
        )
    )).all()}

    # For premium rooms, set occupied = max_occupancy (room is full, no free beds)
    for r, _ in all_rows:
        if r.id in premium_room_ids:
            tenant_counts[r.id] = r.max_occupancy or 1

    # ── Build list of rooms with empty beds ───────────────────────────────
    total_beds = sum(r.max_occupancy or 1 for r, _ in all_rows)

    rooms_with_empty = []
    for r, prop in all_rows:
        max_occ = r.max_occupancy or 1
        occupied = tenant_counts.get(r.id, 0)
        free = max_occ - occupied
        if free > 0:
            rooms_with_empty.append((r, prop, occupied, free))

    total_empty = sum(f for _, _, _, f in rooms_with_empty)
    total_occupied = total_beds - total_empty

    bld = f" in *{building_filter}*" if building_filter else ""
    if not rooms_with_empty:
        return f"All {total_beds} beds{bld} are occupied. No empty beds."

    _ICON = {"single": "🔵", "double": "🟢", "sharing": "🟡", "triple": "🟠", "premium": "⭐"}

    def _floor_label(rn: str) -> str:
        return "G" if rn.upper().startswith("G") else rn[0]

    # Group: fully vacant vs partially occupied
    fully_vacant = [(r, p, o, f) for r, p, o, f in rooms_with_empty if o == 0]
    partial = [(r, p, o, f) for r, p, o, f in rooms_with_empty if o > 0]

    # Stats by building
    blocks: dict = defaultdict(lambda: {"rooms": 0, "beds": 0, "floors": defaultdict(list)})
    for r, prop, occupied, free in rooms_with_empty:
        block = "THOR" if "THOR" in prop.upper() else "HULK"
        blocks[block]["rooms"] += 1
        blocks[block]["beds"] += free
        fl = _floor_label(r.room_number)
        blocks[block]["floors"][fl].append((r, occupied, free))

    SEP = "─" * 28
    thor = blocks.get("THOR", {"rooms": 0, "beds": 0})
    hulk = blocks.get("HULK", {"rooms": 0, "beds": 0})

    lines = [
        f"🛏 *Empty Beds: {total_empty}*  |  Occupied: {total_occupied} / {total_beds}{bld}",
        f"   THOR: {thor['beds']} beds  |  HULK: {hulk['beds']} beds",
        "",
    ]

    for block_name in ["THOR", "HULK"]:
        if block_name not in blocks:
            continue
        bd = blocks[block_name]
        lines.append(f"*{SEP}*")
        lines.append(f"🏢 *{block_name} — {bd['beds']} empty beds in {bd['rooms']} rooms*")
        floor_keys = sorted(bd["floors"].keys(),
                            key=lambda f: (0, f) if f == "G" else (int(f), f))
        for fl in floor_keys:
            rooms = sorted(bd["floors"][fl], key=lambda x: x[0].room_number)
            cells = []
            for r, occupied, free in rooms:
                try:
                    _rt = r.room_type.value if r.room_type else "double"
                except (LookupError, AttributeError):
                    _rt = "double"
                icon = _ICON.get(_rt, "⬜")
                ac = "❄" if r.has_ac else ""
                status = f"({free}free)" if occupied > 0 else ""
                cells.append(f"{icon}{r.room_number}{ac}{status}")
            label = "GF" if fl == "G" else f"F{fl}"
            lines.append(f"  {label}  {'  '.join(cells)}")
        lines.append("")

    # Summary
    lines.append(f"*{SEP}*")
    lines.append(f"Fully vacant rooms: {len(fully_vacant)}  |  Partial: {len(partial)}")
    lines.append(f"🔵Single 🟢Double 🟠Triple ⭐Premium")
    lines.append(f"(Nfree) = partially occupied room")
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

    # Beds occupied: premium = 2 beds (full room), regular = 1 bed
    physical_beds = await session.scalar(
        select(func.sum(
            sa_case((Tenancy.sharing_type == "premium", Room.max_occupancy), else_=1)
        )).select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(Tenancy.status == TenancyStatus.active, Room.is_staff_room == False)
    ) or 0
    physical_rooms = await session.scalar(
        select(func.count(func.distinct(Tenancy.room_id)))
        .select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(Tenancy.status == TenancyStatus.active, Room.is_staff_room == False)
    ) or 0

    # No-shows: premium noshow = 2 beds reserved, regular = 1 bed
    noshow_beds = await session.scalar(
        select(func.sum(
            sa_case((Tenancy.sharing_type == "premium", Room.max_occupancy), else_=1)
        )).select_from(Tenancy).join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status == TenancyStatus.no_show,
            Tenancy.room_id.isnot(None),
            Room.is_staff_room == False,
        )
    ) or 0

    # Day-wise guests currently occupying beds
    from src.database.models import DaywiseStay
    from datetime import date as _date
    _today = _date.today()
    daywise_beds = await session.scalar(
        select(func.count()).select_from(DaywiseStay).where(
            DaywiseStay.checkin_date <= _today,
            DaywiseStay.checkout_date >= _today,
            DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
        )
    ) or 0

    booked_beds  = physical_beds + noshow_beds + daywise_beds
    vacant_beds  = total_beds - booked_beds
    vacant_rooms = total_rooms - physical_rooms
    phys_pct     = int(physical_beds * 100 / total_beds)  if total_beds  else 0
    booked_pct   = int(booked_beds   * 100 / total_beds)  if total_beds  else 0
    room_pct     = int(physical_rooms * 100 / total_rooms) if total_rooms else 0

    daywise_line = f"\nDay-wise     : {daywise_beds} beds  (short stays)\n" if daywise_beds else "\n"

    return (
        f"*Occupancy — {total_beds} total beds*\n\n"
        f"Checked-in   : {physical_beds} beds  ({phys_pct}%)\n"
        f"No-show      : {noshow_beds} beds  (booked, not arrived)"
        f"{daywise_line}"
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
        return f"No notices or upcoming checkouts in {today.strftime('%B %Y')}."

    notice_count = sum(1 for _, t, _ in rows if t.notice_date and t.notice_date >= today.replace(day=1))
    lines = [f"*{notice_count} notice(s) / {len(rows)} upcoming exit(s) — {today.strftime('%B %Y')}*\n"]
    for name, tenancy, room in rows:
        exit_str = tenancy.expected_checkout.strftime("%d %b") if tenancy.expected_checkout else "TBD"
        notice_str = tenancy.notice_date.strftime("%d %b") if tenancy.notice_date else "No notice"
        deposit = int(tenancy.security_deposit or 0)
        # Check forfeiture
        if tenancy.notice_date and tenancy.notice_date.day > _NOTICE_BY_DAY:
            deposit_note = f"Deposit Rs.{deposit:,} *forfeited*"
        elif tenancy.notice_date:
            refund = max(0, deposit - int(tenancy.maintenance_fee or 0))
            deposit_note = f"Refund ~Rs.{refund:,}"
        else:
            deposit_note = f"Deposit Rs.{deposit:,}"
        lines.append(f"• {name} (Room {room.room_number})\n  Notice: {notice_str} | Exit: {exit_str} | {deposit_note}")
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
            rt = room_obj.room_type
            rt_str = rt.value if hasattr(rt, 'value') else str(rt or "")
            max_occ = room_obj.max_occupancy or 1
            return (
                f"*Room {room_obj.room_number}* ({rt_str} sharing)\n"
                f"Status: VACANT (0/{max_occ} beds)\n\n"
                f"No active tenants."
            )
        return f"Room {room} not found."

    first_room = rows[0][2]
    rt = first_room.room_type
    rt_str = rt.value if hasattr(rt, 'value') else str(rt or "")
    max_occ = first_room.max_occupancy or 1
    lines = [
        f"*Room {first_room.room_number}* ({rt_str} sharing, {len(rows)}/{max_occ} occupied)\n"
    ]
    for tenant, tenancy, room_obj in rows:
        o_rent, o_maint = await _calc_outstanding_dues(tenancy.id, session)
        rent_str = f"Rs.{int(tenancy.agreed_rent or 0):,}/month"
        due_note = f" | Due: Rs.{int(o_rent):,}" if o_rent > 0 else " | Paid"
        lines.append(
            f"• {tenant.name} — {rent_str}\n"
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
        return _format_choices_message(name or room or "tenant", choices, "see notes")

    t, tncy, room_obj = tenancies[0]
    notes = tncy.notes

    if not notes or not notes.strip():
        return f"*{t.name}* (Room {room_obj.room_number}) — no agreed terms on record."

    return (
        f"*{t.name}* — Room {room_obj.room_number}\n"
        f"Agreed terms:\n{notes}"
    )


async def _update_tenant_notes(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show current tenant agreement notes and prompt for update."""
    name = entities.get("name", "").strip()
    room = entities.get("room", "").strip()

    if not name and not room:
        return "Which tenant? Reply with: *update notes [Name]* or *update notes room [Number]*"

    rows = await _find_active_tenants_by_name(name, session) if name else []
    if not rows and room:
        rows = await _find_active_tenants_by_room(room, session)

    if not rows:
        suggestions = await _find_similar_names(name, session) if name else []
        return _format_no_match_message(name or room, suggestions)

    if len(rows) > 1:
        choices = _make_choices(rows)
        await _save_pending(
            ctx.phone, "UPDATE_TENANT_NOTES_STEP",
            {"step": "pick_tenant"},
            choices, session,
        )
        return _format_choices_message(name or room, choices, "update notes")

    tenant, tenancy, room_obj = rows[0]
    current_notes = tenancy.notes or "(no notes)"

    await _save_pending(
        ctx.phone, "UPDATE_TENANT_NOTES_STEP",
        {
            "step": "enter_notes",
            "tenant_id": tenant.id,
            "tenancy_id": tenancy.id,
            "tenant_name": tenant.name,
            "room_number": room_obj.room_number,
            "current_notes": tenancy.notes or "",
        },
        [], session,
    )
    return (
        f"*{tenant.name}* (Room {room_obj.room_number})\n\n"
        f"Current tenant agreement: _{current_notes}_\n\n"
        "Type new agreement notes, or *delete* to clear:"
    )


async def _add_contact(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Parse contact details from message and confirm before saving."""
    import hashlib
    raw = entities.get("_raw_message", "").strip()

    # Extract phone number (7+ digits) — strip spaces/dashes/country code
    raw_digits = re.sub(r'[^\d]', '', raw)
    if raw_digits.startswith('91') and len(raw_digits) >= 12:
        raw_digits = raw_digits[2:]
    if raw_digits.startswith('0') and len(raw_digits) == 11:
        raw_digits = raw_digits[1:]
    phone_match = re.search(r'\d{7,15}', raw_digits)
    phone = phone_match.group() if phone_match else ""

    # Extract category — match known service keywords
    _CATEGORIES = {
        "electrician": "Electrician", "plumber": "Plumber", "carpenter": "Carpenter",
        "painter": "Painter", "vendor": "Vendor", "supplier": "Supplier",
        "cleaner": "Cleaner", "cleaning": "Cleaner", "security": "Security",
        "pest": "Pest Control", "internet": "Internet/WiFi", "wifi": "Internet/WiFi",
        "water": "Water", "gas": "Gas", "furniture": "Furniture", "gym": "Gym",
        "cctv": "CCTV", "lift": "Lift/Elevator", "cook": "Cook", "maid": "Housekeeping",
        "housekeeping": "Housekeeping", "caretaker": "Caretaker", "watchman": "Security",
        "building": "Building Services", "maintenance": "Maintenance",
        "lineman": "Electrician", "line man": "Electrician", "bescom": "Electricity",
        "bwssb": "Water", "cable": "Cable/Internet", "ac": "AC Service",
        "mason": "Mason", "welder": "Welder", "laundry": "Laundry",
        "driver": "Driver", "transport": "Transport", "ambulance": "Emergency",
    }
    raw_lower = raw.lower()
    category = ""
    for keyword, cat in _CATEGORIES.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', raw_lower):
            category = cat
            break

    # Extract name — remove noise words, phone number, "add/save/contact" etc.
    # Category keywords are KEPT in the name (e.g. "Mahadevapura lineman" → name is full string)
    _NOISE = {"add", "save", "store", "new", "contact", "contacts", "to", "as", "vendor", "supplier", "number", "phone"}
    words = raw.split()
    name_parts = []
    for w in words:
        w_clean = re.sub(r'[^\w]', '', w)
        if not w_clean:
            continue
        if w_clean.lower() in _NOISE:
            continue
        if w_clean == phone:
            continue
        if w_clean.isdigit():
            continue
        name_parts.append(w_clean)

    name = " ".join(name_parts).strip()
    # Capitalize first letter of each word
    name = " ".join(w.capitalize() for w in name.split()) if name else ""

    if not name and not phone:
        await _save_pending(
            ctx.phone, "ADD_CONTACT_STEP",
            {"step": "ask_name", "logged_by": ctx.name or ctx.phone},
            [], session,
        )
        return "*Add Contact*\n\n*Name?*"

    if not phone:
        await _save_pending(
            ctx.phone, "ADD_CONTACT_STEP",
            {"step": "ask_phone", "name": name, "category": category, "logged_by": ctx.name or ctx.phone},
            [], session,
        )
        return f"*Add Contact: {name}*" + (f" ({category})" if category else "") + "\n\n*Phone number?*"

    if not name:
        await _save_pending(
            ctx.phone, "ADD_CONTACT_STEP",
            {"step": "ask_name", "phone": phone, "category": category, "logged_by": ctx.name or ctx.phone},
            [], session,
        )
        return f"*Add Contact*\n\nPhone: {phone}" + (f"\nCategory: {category}" if category else "") + "\n\n*Name?*"

    # Have name + phone — ask for category if missing, then confirm
    if not category:
        await _save_pending(
            ctx.phone, "ADD_CONTACT_STEP",
            {"step": "ask_category", "name": name, "phone": phone, "logged_by": ctx.name or ctx.phone},
            [], session,
        )
        return (
            f"*Add Contact: {name}*\nPhone: {phone}\n\n"
            "*What do they do?* (e.g. electrician, plumber, vendor, or type a description)"
        )

    # All fields present — ask for notes
    await _save_pending(
        ctx.phone, "ADD_CONTACT_STEP",
        {"step": "ask_notes", "name": name, "phone": phone, "category": category, "logged_by": ctx.name or ctx.phone},
        [], session,
    )
    phone_str = f"\nPhone: {phone}" if phone else ""
    return (
        f"*{name}* — {category}{phone_str}\n\n"
        "*Any notes?* (e.g. light installation, 20K agreed)\n"
        "Type notes or *skip*"
    )


async def _update_contact(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """
    Update an existing vendor contact — phone, notes, or both.
    "update contact Shiva — paid 5K more", "change Balu number to 9876543210"
    """
    raw = entities.get("_raw_message", "").strip()

    # Extract search name — remove noise words
    _NOISE = {
        "update", "edit", "change", "modify", "contact", "contacts",
        "vendor", "supplier", "number", "phone", "notes", "note",
        "comment", "comments", "to", "for", "the",
    }
    words = raw.split()
    name_parts = []
    for w in words:
        w_clean = re.sub(r'[^\w]', '', w)
        if not w_clean:
            continue
        if w_clean.lower() in _NOISE:
            continue
        if w_clean.isdigit():
            continue
        name_parts.append(w_clean)
    search_name = " ".join(name_parts).strip()

    if not search_name:
        await _save_pending(
            ctx.phone, "UPDATE_CONTACT_STEP",
            {"step": "ask_name", "logged_by": ctx.name or ctx.phone},
            [], session,
        )
        return "*Update Contact*\n\n*Name?* (which contact to update)"

    # Search for matching contacts
    from sqlalchemy import or_
    like = f"%{search_name.lower()}%"
    contacts = (await session.execute(
        select(PgContact).where(
            PgContact.property == "Whitefield",
            or_(
                func.lower(PgContact.name).like(like),
                func.lower(PgContact.category).like(like),
            ),
        ).order_by(PgContact.name)
    )).scalars().all()

    if not contacts:
        return f"No contact found matching *{search_name}*. Check the name and try again."

    if len(contacts) == 1:
        c = contacts[0]
        await _save_pending(
            ctx.phone, "UPDATE_CONTACT_STEP",
            {"step": "ask_field", "contact_id": c.id, "contact_name": c.name,
             "contact_phone": c.phone, "contact_notes": c.contact_for or "",
             "logged_by": ctx.name or ctx.phone},
            [], session,
        )
        return (
            f"*Update: {c.name}*\n"
            f"  Phone: {c.phone}\n"
            f"  Category: {c.category or ''}\n"
            f"  Notes: {c.contact_for or '—'}\n\n"
            "What to update?\n"
            "*1.* Phone number\n"
            "*2.* Notes/description\n"
            "*3.* Both\n"
            "*4.* Cancel"
        )

    # Multiple matches — ask which one
    lines = [f"*Found {len(contacts)} contacts matching \"{search_name}\":*\n"]
    for i, c in enumerate(contacts, 1):
        lines.append(f"*{i}.* {c.name} — {c.phone} ({c.category or ''})")
    lines.append(f"\n*{len(contacts)+1}.* Cancel")
    choices = [{"seq": i+1, "contact_id": c.id, "label": f"{c.name} — {c.phone}"}
               for i, c in enumerate(contacts)]
    await _save_pending(
        ctx.phone, "UPDATE_CONTACT_STEP",
        {"step": "pick_contact", "logged_by": ctx.name or ctx.phone},
        choices, session,
    )
    return "\n".join(lines)


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
        "all", "every", "each", "send", "want", "need", "tell", "share",
        "please", "can", "you", "i", "to", "my", "have", "whats", "what",
    }
    words = re.findall(r"[a-z]+", raw)
    # Strip trailing 's' for fuzzy matching (vinays → vinay, plumbers → plumber)
    search_terms = [w.rstrip("s") if len(w) > 3 and w.endswith("s") and w not in _NOISE else w
                    for w in words if w not in _NOISE and len(w) > 1]

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


# ── ASSIGN ROOM (unassigned/future booking → active with room) ────────────────

async def _assign_room_prompt(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Assign a room to a tenant who has an unassigned/future booking."""
    name = entities.get("name", "").strip()
    room_str = entities.get("room", "").strip()

    if not room_str:
        desc = entities.get("description", "") or entities.get("_raw_message", "")
        rm = re.search(r"(?:room\s*)?(\d{2,4}[A-Za-z]?(?:-[A-Za-z])?)", desc, re.I)
        if rm:
            room_str = rm.group(1)

    if not name:
        return (
            "Who should be assigned a room?\n"
            "Say: *assign room 305-A to Raj* or *assign Raj to room 305-A*"
        )

    # Find tenant — prefer unassigned/future bookings
    from src.database.models import TenancyStatus
    unassigned = (await session.execute(
        select(Tenant, Tenancy, Room)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id, isouter=True)
        .where(
            Tenant.name.ilike(f"%{name}%"),
            Tenancy.status.in_([TenancyStatus.active]),
        )
        .order_by(Tenancy.checkin_date.desc())
    )).all()

    # Also check for tenants without any active tenancy (future booking with no room)
    no_tenancy = (await session.execute(
        select(Tenant).where(
            Tenant.name.ilike(f"%{name}%"),
            ~Tenant.id.in_(
                select(Tenancy.tenant_id).where(Tenancy.status == TenancyStatus.active)
            )
        )
    )).scalars().all()

    # Check if any active tenancy already has a room assigned
    for tenant, tenancy, room in unassigned:
        if room and room.active:
            return (
                f"*{tenant.name}* ({tenant.phone}) already has active room *{room.room_number}*.\n"
                f"Did you mean *move {tenant.name} to {room_str or 'new room'}*?"
            )

    # Match future bookings / unassigned
    if no_tenancy:
        if len(no_tenancy) == 1:
            tenant = no_tenancy[0]
        else:
            choices = [{"label": f"{t.name} ({t.phone})", "tenant_id": t.id} for t in no_tenancy]
            choice_lines = "\n".join(f"*{i+1}.* {c['label']}" for i, c in enumerate(choices))
            await _save_pending(ctx.phone, "ASSIGN_ROOM_STEP",
                                {"step": "pick_tenant", "room": room_str, "choices": choices}, [], session)
            return f"Multiple matches for *{name}*:\n{choice_lines}\n\nReply with number."

        if not room_str:
            await _save_pending(ctx.phone, "ASSIGN_ROOM_STEP",
                                {"step": "ask_room", "tenant_id": tenant.id, "tenant_name": tenant.name,
                                 "tenant_phone": tenant.phone}, [], session)
            return (
                f"Assigning room to *{tenant.name}* ({tenant.phone}).\n"
                "Which room? (e.g. 305-A)"
            )

        # Validate room
        new_room = await session.scalar(
            select(Room).where(Room.room_number == room_str.upper(), Room.active == True)
        )
        if not new_room:
            return f"Room *{room_str}* not found. Check room number."

        # Check vacancy
        occupied = await session.scalar(
            select(func.count(Tenancy.id)).where(
                Tenancy.room_id == new_room.id, Tenancy.status == TenancyStatus.active,
            )
        )
        if occupied:
            return f"Room *{room_str}* is occupied. Pick a vacant room."

        # Confirm
        await _save_pending(ctx.phone, "ASSIGN_ROOM_STEP",
                            {"step": "confirm", "tenant_id": tenant.id, "tenant_name": tenant.name,
                             "tenant_phone": tenant.phone, "room_id": new_room.id,
                             "room_number": new_room.room_number}, [], session)
        return (
            f"*Assign Room?*\n\n"
            f"Tenant: {tenant.name} ({tenant.phone})\n"
            f"Room: {new_room.room_number}\n\n"
            "Reply *yes* to confirm or *no* to cancel."
        )

    if not unassigned and not no_tenancy:
        return (
            f"No unassigned tenant found matching *{name}*.\n"
            "Use *add tenant* for new check-ins."
        )

    return f"Could not find an unassigned booking for *{name}*."


async def _query_unhandled(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    """Show recent unhandled requests (admin only)."""
    from src.database.models import UnhandledRequest
    rows = (await session.execute(
        select(UnhandledRequest)
        .where(UnhandledRequest.resolved == False)
        .order_by(UnhandledRequest.created_at.desc())
        .limit(20)
    )).scalars().all()

    if not rows:
        return "No unhandled requests. The bot understood everything recently."

    lines = [f"*Unhandled Requests* ({len(rows)} unresolved):\n"]
    for r in rows:
        ts = r.created_at.strftime("%d %b %H:%M") if r.created_at else "?"
        lines.append(f"- _{ts}_ ({r.role or '?'}): {r.message[:80]}")

    return "\n".join(lines)


async def _unknown(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    # Log unhandled request for future intent building
    try:
        from src.database.models import UnhandledRequest
        msg = entities.get("description", "") or entities.get("raw_message", "")
        if msg and len(msg) > 2:  # skip garbage like "sn"
            session.add(UnhandledRequest(
                phone=ctx.phone,
                message=msg[:500],
                role=ctx.role,
            ))
    except Exception:
        pass  # don't break the reply over logging
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
        step="ask_dob",
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
    # Image-based checkout form extraction
    media_id = entities.get("_media_id")
    media_type = entities.get("_media_type")
    media_mime = entities.get("_media_mime")
    if media_id and media_type == "image":
        return await _extract_checkout_from_image(media_id, media_mime or "image/jpeg", ctx, session)

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
            "step": "ask_exit_date",
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
        "*Exit date?* (e.g. *today* or *29 March*)"
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
    """
    Smart activity log query — uses keyword SQL filter + Groq for complex questions.

    Simple queries (activity today, activity this week) → list entries.
    Complex queries (how many TVs, chairs status, pending maintenance) → Groq answers.
    """
    raw = entities.get("_raw_message", "").lower().strip()
    today = date.today()

    # Detect if this is a SMART query (needs LLM) or SIMPLE list query
    is_smart = any(w in raw for w in (
        "how many", "how much", "status", "pending", "total", "count",
        "ordered", "delivered", "needed", "remaining", "summary",
        "what", "which", "did we", "have we", "was the", "is the",
    ))

    # ── SIMPLE: time-based activity list ──────────────────────────────────
    from_dt = datetime(today.year, today.month, today.day, 0, 0, 0)
    to_dt = datetime.now()
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
    elif "this month" in raw or "month" in raw:
        from_dt = datetime(today.year, today.month, 1, 0, 0, 0)
        label = "this month"
    elif re.search(r"last\s+(\d+)\s+days?", raw):
        m = re.search(r"last\s+(\d+)\s+days?", raw)
        days_back = int(m.group(1))
        start = today - timedelta(days=days_back)
        from_dt = datetime(start.year, start.month, start.day, 0, 0, 0)
        label = f"last {days_back} days"
    elif is_smart:
        # Smart queries search ALL time — no date filter
        from_dt = datetime(2025, 1, 1, 0, 0, 0)
        label = "all time"

    # Build query
    q = select(ActivityLog).where(
        and_(
            ActivityLog.created_at >= from_dt,
            ActivityLog.created_at <= to_dt,
        )
    )

    # Room filter
    rm = re.search(r"room\s+([\w-]+)", raw, re.I)
    if rm:
        q = q.where(ActivityLog.room == rm.group(1))
        label += f" (room {rm.group(1)})"

    # Keyword filter for smart queries — extract topic words
    if is_smart:
        # Extract meaningful keywords (skip stop words)
        _STOP = {"how", "many", "much", "what", "which", "the", "is", "are", "was",
                 "were", "did", "do", "we", "have", "has", "any", "all", "show",
                 "tell", "me", "about", "for", "and", "or", "in", "on", "to",
                 "status", "pending", "total", "count", "needed", "activity", "log"}
        keywords = [w for w in re.findall(r"[a-z]+", raw) if w not in _STOP and len(w) > 2]
        if keywords:
            # Search description for ANY keyword
            keyword_filters = [ActivityLog.description.ilike(f"%{kw}%") for kw in keywords]
            q = q.where(or_(*keyword_filters))

    q = q.order_by(ActivityLog.created_at.desc()).limit(200)
    result = await session.execute(q)
    entries = result.scalars().all()

    if not entries:
        return f"No activity logs found for this query."

    # ── SMART: use Groq to answer ─────────────────────────────────────────
    if is_smart:
        log_lines = []
        for e in entries:
            dt = e.created_at.strftime("%d %b %Y %I:%M %p") if e.created_at else ""
            room_tag = f" [Room {e.room}]" if e.room else ""
            amt = f" (Rs.{int(e.amount):,})" if e.amount else ""
            log_lines.append(f"{dt}: {e.description}{room_tag}{amt}")

        try:
            from src.llm_gateway.claude_client import get_claude_client
            ai = get_claude_client()
            answer = await ai.answer_from_logs(raw, log_lines, "activity")
            if answer:
                return f"*Activity Query*\n_{len(entries)} logs searched_\n\n{answer}"
        except Exception:
            pass  # fall through to simple list

    # ── SIMPLE: list entries ──────────────────────────────────────────────
    lines = [f"*Activity log — {label}* ({len(entries)} entries)\n"]
    for e in entries[:30]:  # cap display at 30
        icon = _TYPE_ICONS.get(e.log_type, "📝") if e.log_type else "📝"
        time_str = e.created_at.strftime("%d %b %I:%M %p") if e.created_at else ""
        line = f"{icon} {time_str} — {e.description}"
        if e.amount:
            line += f" (Rs.{int(e.amount):,})"
        if e.room:
            line += f" [Room {e.room}]"
        lines.append(line)

    if len(entries) > 30:
        lines.append(f"\n_...and {len(entries) - 30} more_")

    return "\n".join(lines)
