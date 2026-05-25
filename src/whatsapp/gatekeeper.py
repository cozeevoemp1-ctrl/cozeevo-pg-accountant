"""
src/whatsapp/gatekeeper.py
===========================
Smart router — maps (role, intent) to the correct worker.

Called by chat_api.py after intent detection instead of the old
flat if/elif chain. This is the only place that knows which worker
handles what; all workers remain unaware of each other.

Routing rules (3 tiers):
  admin        → operational (financial queries blocked — use Kozzy app)
  owner        → operational (financial queries blocked — use Kozzy app)
  receptionist → operational queries only (no financial access)
  tenant       → TenantWorker   (tenant_handler)
  lead / unknown → LeadWorker  (lead_handler)
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.whatsapp.handlers.account_handler import FINANCIAL_INTENTS
from src.whatsapp.handlers.owner_handler import handle_owner
from src.whatsapp.handlers.tenant_handler import handle_tenant
from src.whatsapp.handlers.lead_handler import handle_lead
from src.whatsapp.role_service import CallerContext

OWNER_ROLES: frozenset[str] = frozenset({"admin", "owner"})

_FINANCE_BLOCKED_MSG = (
    "Finance queries are not available via WhatsApp.\n"
    "Please use the Kozzy app to view payments, reports, dues, and expenses."
)


async def route(
    intent: str,
    entities: dict,
    ctx: CallerContext,
    message: str,
    session: AsyncSession,
) -> str | None:
    # Stash raw message in entities so handlers can access it without signature change
    entities.setdefault("_raw_message", message)

    if ctx.role in OWNER_ROLES:
        if intent in FINANCIAL_INTENTS:
            return _FINANCE_BLOCKED_MSG
        else:
            return await handle_owner(intent, entities, ctx, session)
    elif ctx.role == "receptionist":
        if intent in FINANCIAL_INTENTS:
            return _FINANCE_BLOCKED_MSG
        else:
            return await handle_owner(intent, entities, ctx, session)
    elif ctx.role == "tenant":
        # Tenant auto-reply disabled — handle manually
        return None
    else:
        # Lead / unknown phone — auto-reply disabled, handle manually
        return None
