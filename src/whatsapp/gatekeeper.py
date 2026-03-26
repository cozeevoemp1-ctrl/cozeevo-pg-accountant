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

# Intents the receptionist role is BLOCKED from.
# Only financial summary reports and bank statement features are restricted.
RECEPTIONIST_BLOCKED: frozenset[str] = frozenset({
    "REPORT",            # monthly financial report
    "BANK_REPORT",       # bank statement analysis
    "BANK_DEPOSIT_MATCH",# bank deposit matching
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
        if intent in RECEPTIONIST_BLOCKED:
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
