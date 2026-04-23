"""Onboarding-related pending-action resolvers.

Extracted from owner_handler.resolve_pending_action on 2026-04-23 (Phase 2A).
See plan: docs/superpowers/plans/2026-04-23-phase2-handler-refactor.md
"""
from __future__ import annotations

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
