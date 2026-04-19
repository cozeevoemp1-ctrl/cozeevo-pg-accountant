"""
src/whatsapp/conversation/handlers/confirm_add_expense.py
==========================================================
Yes/No confirmation for logging an operational expense.

Supports mid-flow amount correction: if user types a new amount before
yes/no, we update action_data and re-prompt.
"""
from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..memory import ConversationMemory
from ..state import ConversationState, UserInput
from ..router import RouteResult, register


def _action_data(mem: ConversationMemory) -> dict:
    try:
        d = json.loads(mem.pending.action_data or "{}")  # type: ignore[union-attr]
    except (json.JSONDecodeError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


@register("CONFIRM_ADD_EXPENSE", ConversationState.AWAITING_CONFIRMATION)
async def on_confirm_add_expense(
    mem: ConversationMemory,
    inp: UserInput,
    session: AsyncSession,
) -> RouteResult:
    action = _action_data(mem)

    # Mid-flow amount correction — user typed a new number before yes/no
    amt_m = re.search(r"\b(\d[\d,]+)\b", inp.raw)
    if amt_m:
        new_amt = float(amt_m.group(1).replace(",", ""))
        current_amt = action.get("amount", 0) or 0
        if new_amt > 0 and new_amt != current_amt and not inp.parsed_yes and not inp.parsed_no:
            action["amount"] = new_amt
            mem.pending.action_data = json.dumps(action)  # type: ignore[union-attr]
            await session.flush()
            cat = (action.get("category") or "").capitalize()
            return RouteResult(
                reply=(f"✏️ Updated. Log expense?\n"
                       f"• Category: {cat}\n"
                       f"• Amount: ₹{int(new_amt):,}\n\n"
                       "Reply *Yes* to confirm or *No* to cancel."),
                keep_pending=True,
            )

    if inp.parsed_no:
        return RouteResult(
            reply="What would you like to change? Type the correction or *cancel* to stop.",
            keep_pending=True,
        )

    if inp.parsed_yes:
        amount      = action.get("amount", 0) or 0
        cat_name    = action.get("category", "Miscellaneous")
        description = action.get("description", "")

        from src.database.models import Expense, ExpenseCategory
        from src.whatsapp.handlers.owner_handler import _fetch_active_property

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
        return RouteResult(
            reply=f"✅ Expense logged — {label} ₹{int(amount):,} on {date.today().strftime('%d %b %Y')}.",
            keep_pending=False,
        )

    # Neither yes/no/amount → re-prompt
    amt = action.get("amount", 0) or 0
    cat = (action.get("category") or "").capitalize()
    return RouteResult(
        reply=(f"Log expense?\n"
               f"• Category: {cat}\n"
               f"• Amount: ₹{int(amt):,}\n\n"
               "Reply *Yes* to confirm or *No* to cancel."),
        keep_pending=True,
    )
