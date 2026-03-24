"""
src/whatsapp/gatekeeper.py
===========================
Smart router — maps (role, intent) to the correct worker.

Called by chat_api.py after intent detection instead of the old
flat if/elif chain. This is the only place that knows which worker
handles what; all workers remain unaware of each other.

Routing rules:
  admin / power_user / key_user
    + financial intent  → AccountWorker  (account_handler)
    + operational intent → OwnerWorker   (owner_handler)
  receptionist         → OwnerWorker / AccountWorker (restricted allowlist only)
  tenant               → TenantWorker   (tenant_handler)
  lead / unknown       → LeadWorker     (lead_handler)
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.whatsapp.handlers.account_handler import handle_account, FINANCIAL_INTENTS
from src.whatsapp.handlers.owner_handler import handle_owner
from src.whatsapp.handlers.tenant_handler import handle_tenant
from src.whatsapp.handlers.lead_handler import handle_lead
from src.whatsapp.role_service import CallerContext

OWNER_ROLES: frozenset[str] = frozenset({"admin", "power_user", "key_user"})

# Intents the receptionist role is allowed to use.
# Blocked from: REPORT, BANK_REPORT, BANK_DEPOSIT_MATCH, ADD_TENANT, REMOVE_TENANT,
#               CHECKOUT, RENT_CHANGE, ADD_EXPENSE, ADD_PARTNER, VOID_PAYMENT,
#               VOID_EXPENSE, ADD_REFUND, QUERY_REFUNDS, DEPOSIT_CHANGE, and all
#               destructive/financial-summary intents.
RECEPTIONIST_ALLOWED: frozenset[str] = frozenset({
    # Complaints
    "COMPLAINT_REGISTER",
    "COMPLAINT_UPDATE",
    "QUERY_COMPLAINTS",
    # Payments (log only — no voids, no reports)
    "PAYMENT_LOG",
    # Dues (view only)
    "QUERY_DUES",
    # Occupancy / vacancy
    "QUERY_OCCUPANCY",
    "QUERY_VACANCY",
    "QUERY_VACANT_ROOMS",
    # Tenant info (read-only)
    "QUERY_TENANT",
    "ROOM_STATUS",
    # Contacts (read-only)
    "QUERY_CONTACTS",
    # General
    "HELP",
    "MORE_MENU",
    "GREETING",
    "UNKNOWN",
})


async def route(
    intent: str,
    entities: dict,
    ctx: CallerContext,
    message: str,
    session: AsyncSession,
) -> str:
    # Stash raw message in entities so handlers can access it without signature change
    entities.setdefault("_raw_message", message)

    if ctx.role in OWNER_ROLES:
        if intent in FINANCIAL_INTENTS:
            return await handle_account(intent, entities, ctx, session)
        else:
            return await handle_owner(intent, entities, ctx, session)
    elif ctx.role == "receptionist":
        if intent not in RECEPTIONIST_ALLOWED:
            return (
                "Sorry, that action requires owner-level access.\n"
                "Type *help* to see what you can do."
            )
        if intent in FINANCIAL_INTENTS:
            return await handle_account(intent, entities, ctx, session)
        else:
            return await handle_owner(intent, entities, ctx, session)
    elif ctx.role == "tenant":
        return await handle_tenant(intent, entities, ctx, session)
    else:
        # lead / unknown phone — conversational sales handling
        return await handle_lead(intent, message, ctx, session)
