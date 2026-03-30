# Payment Flow Rework + Notes Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework payment flow to show dues snapshot + notes before confirmation, with smart oldest-first month allocation and two-tier notes (permanent + monthly) with DB/Sheet sync and carry-over.

**Architecture:** Add `build_dues_snapshot()` to `_shared.py` as reusable helper. Modify `_payment_log()` in account_handler and `COLLECT_RENT_STEP` in owner_handler to use it. Add notes sync with retry to gsheets.py. Add carry-over logic inline where rent_schedule rows are created. New `UPDATE_TENANT_NOTES` intent for permanent note editing.

**Tech Stack:** Python, FastAPI, SQLAlchemy async, Google Sheets API (gspread), existing test harness (HTTP-based workflow tests)

**Spec:** `docs/superpowers/specs/2026-03-30-payment-flow-rework-design.md`

---

## File Structure

| File | Responsibility | Change Type |
|------|---------------|-------------|
| `src/whatsapp/handlers/_shared.py` | New `build_dues_snapshot()` + `compute_allocation()` helpers | Modify |
| `src/whatsapp/handlers/account_handler.py` | Rework `_payment_log()` to show snapshot + allocation before confirm | Modify |
| `src/whatsapp/handlers/owner_handler.py` | Rework `COLLECT_RENT_STEP` to show snapshot after tenant ID, allocation at confirm. Add `UPDATE_TENANT_NOTES` pending handler. | Modify |
| `src/whatsapp/intent_detector.py` | Add `UPDATE_TENANT_NOTES` regex patterns | Modify |
| `src/whatsapp/gatekeeper.py` | Route `UPDATE_TENANT_NOTES` to owner_handler | Modify |
| `src/integrations/gsheets.py` | Add `sync_notes_with_retry()`, `update_tenants_tab_notes()` | Modify |
| `src/database/excel_import.py` | Add `--preview-notes` flag, classification JSON loading | Modify |
| `tests/test_workflow_flows.py` | New payment flow tests with snapshot/allocation | Modify |

---

## Task 1: `build_dues_snapshot()` helper in _shared.py

**Files:**
- Modify: `src/whatsapp/handlers/_shared.py`
- Test: `tests/test_workflow_flows.py`

- [ ] **Step 1: Add imports needed for snapshot**

Add to the imports section of `_shared.py` (after line 21):

```python
from src.database.models import PendingAction, Room, Tenant, Tenancy, TenancyStatus, WhatsappLog, RentSchedule, RentStatus, Payment, PaymentFor
from sqlalchemy import func
from decimal import Decimal
```

Replace the existing import line that imports `PendingAction, Room, Tenant, Tenancy, TenancyStatus, WhatsappLog`.

- [ ] **Step 2: Add `build_dues_snapshot()` function**

Add at the end of `_shared.py`:

```python
async def build_dues_snapshot(
    tenancy_id: int,
    tenant_name: str,
    room_number: str,
    session: AsyncSession,
) -> dict:
    """
    Build a complete dues snapshot for a tenant.
    Returns:
        {
            "text": str,              # formatted snapshot string
            "months": [               # list of pending months
                {"period": date, "due": Decimal, "paid": Decimal, "remaining": Decimal,
                 "status": str, "notes": str|None},
            ],
            "total_outstanding": Decimal,
            "tenant_notes": str|None,  # permanent tenancy.notes
        }
    """
    tenancy = await session.get(Tenancy, tenancy_id)
    tenant_notes = tenancy.notes if tenancy else None

    # Get all pending/partial rent_schedule rows, ordered oldest first
    rs_result = await session.execute(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy_id,
            RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
        ).order_by(RentSchedule.period_month.asc())
    )
    months = []
    total_outstanding = Decimal("0")

    for rs in rs_result.scalars().all():
        paid = await session.scalar(
            select(func.sum(Payment.amount)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.period_month == rs.period_month,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
            )
        ) or Decimal("0")
        effective_due = (rs.rent_due or Decimal("0")) + (rs.adjustment or Decimal("0"))
        remaining = max(Decimal("0"), effective_due - paid)
        total_outstanding += remaining
        status_label = "partial" if paid > 0 else "unpaid"
        months.append({
            "period": rs.period_month,
            "due": effective_due,
            "paid": paid,
            "remaining": remaining,
            "status": status_label,
            "notes": rs.notes,
        })

    # Build text
    lines = [f"*{tenant_name}* (Room {room_number})"]
    if tenant_notes:
        lines.append(f"\nTenant notes: {tenant_notes}")
    if months:
        lines.append("\nDues:")
        for m in months:
            month_str = m["period"].strftime("%b %Y")
            status_str = f"({m['status']}"
            if m["paid"] > 0:
                status_str += f" -- Rs.{int(m['paid']):,} of Rs.{int(m['due']):,} paid"
            status_str += ")"
            line = f"  {month_str}: Rs.{int(m['remaining']):,} {status_str}"
            if m["notes"]:
                line += f' -- "{m["notes"]}"'
            lines.append(line)
        lines.append(f"  *Total outstanding: Rs.{int(total_outstanding):,}*")
    else:
        lines.append("\nAll paid up!")

    return {
        "text": "\n".join(lines),
        "months": months,
        "total_outstanding": total_outstanding,
        "tenant_notes": tenant_notes,
    }
```

- [ ] **Step 3: Add `compute_allocation()` function**

Add right after `build_dues_snapshot()`:

```python
def compute_allocation(
    amount: Decimal,
    months: list[dict],
) -> list[dict]:
    """
    Allocate payment amount oldest-first across pending months.
    Returns list of {"period": date, "amount": Decimal, "clears": bool} dicts.
    """
    remaining = Decimal(str(amount))
    allocation = []
    for m in months:
        if remaining <= 0:
            break
        apply = min(remaining, m["remaining"])
        if apply > 0:
            allocation.append({
                "period": m["period"],
                "amount": apply,
                "clears": apply >= m["remaining"],
            })
            remaining -= apply
    return allocation


def format_allocation(allocation: list[dict], amount, mode: str) -> str:
    """Format allocation into a confirmation message section."""
    mode_label = (mode or "cash").upper()
    lines = [f"\nSuggested allocation for Rs.{int(amount):,} {mode_label}:"]
    for a in allocation:
        month_str = a["period"].strftime("%b %Y")
        label = "clears balance" if a["clears"] else "partial"
        lines.append(f"  -> {month_str}: Rs.{int(a['amount']):,} ({label})")
    return "\n".join(lines)


def parse_allocation_override(text: str, months: list[dict]) -> list[dict] | None:
    """
    Parse receptionist override like "all to march" or "feb 3000 march 5000".
    Returns list of {"period": date, "amount": Decimal} or None if unparseable.
    """
    import re as _re
    text_lower = text.strip().lower()

    # Build month name → period map from available months
    month_map = {}
    for m in months:
        month_map[m["period"].strftime("%b").lower()] = m["period"]
        month_map[m["period"].strftime("%B").lower()] = m["period"]

    # "all to march" / "all to feb"
    match = _re.match(r"all\s+to\s+(\w+)", text_lower)
    if match:
        month_name = match.group(1)
        period = month_map.get(month_name)
        if period:
            return [{"period": period, "amount": None}]  # None = full amount
        return None

    # "feb 3000 march 5000" or "feb 3000, march 5000"
    parts = _re.findall(r"(\w+)\s+([\d,]+)", text_lower)
    if parts:
        result = []
        for month_name, amt_str in parts:
            period = month_map.get(month_name)
            if not period:
                return None
            amt = Decimal(amt_str.replace(",", ""))
            result.append({"period": period, "amount": amt})
        return result

    return None
```

- [ ] **Step 4: Verify the module still imports cleanly**

Run: `cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant" && venv/Scripts/python -c "from src.whatsapp.handlers._shared import build_dues_snapshot, compute_allocation, format_allocation, parse_allocation_override; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/whatsapp/handlers/_shared.py
git commit -m "feat: add build_dues_snapshot + compute_allocation helpers"
```

---

## Task 2: Rework `_payment_log()` in account_handler.py

**Files:**
- Modify: `src/whatsapp/handlers/account_handler.py:111-201`

- [ ] **Step 1: Add new imports to account_handler.py**

At the top imports section (around line 42-50), add to the existing `_shared` import:

```python
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
```

- [ ] **Step 2: Rewrite `_payment_log()` to show snapshot + allocation**

Replace the function at line 111-201 with:

```python
async def _payment_log(entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    name   = entities.get("name", "").strip()
    room   = entities.get("room", "").strip()
    amount = entities.get("amount")
    mode   = entities.get("payment_mode", "cash")
    month_num = entities.get("month")    # int 1-12 if mentioned in message

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

    # Determine intended period month (used only for single-month override)
    current_month = date.today().replace(day=1)
    if month_num:
        period_month = date(date.today().year, int(month_num), 1)
    else:
        period_month = None  # let allocation decide

    if len(rows) == 1:
        tenant, tenancy, _room = rows[0]
        # Build dues snapshot
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

        # If user specified a month, force allocation to that month only
        if period_month:
            allocation = [{"period": period_month, "amount": amount_dec, "clears": False}]
        else:
            allocation = compute_allocation(amount_dec, pending_months)

        # Single month due or single allocation entry — straight confirm
        if len(pending_months) == 1 or len(allocation) == 1:
            alloc_data = [{"period": a["period"].isoformat(), "amount": float(a["amount"])} for a in allocation]
            await _save_pending(
                ctx.phone, "CONFIRM_PAYMENT_ALLOC",
                {
                    "tenant_id": tenant.id,
                    "tenancy_id": tenancy.id,
                    "amount": amount,
                    "mode": mode,
                    "logged_by": ctx.name or ctx.phone,
                    "allocation": alloc_data,
                    "tenant_name": tenant.name,
                    "room_number": _room.room_number,
                },
                [], session,
            )
            alloc_text = format_allocation(allocation, amount, mode)
            return (
                snapshot["text"] + "\n"
                + alloc_text + "\n\n"
                "Reply *Yes* to confirm, or *No* to cancel."
            )

        # Multiple months — show allocation, allow override
        alloc_data = [{"period": a["period"].isoformat(), "amount": float(a["amount"])} for a in allocation]
        await _save_pending(
            ctx.phone, "CONFIRM_PAYMENT_ALLOC",
            {
                "tenant_id": tenant.id,
                "tenancy_id": tenancy.id,
                "amount": amount,
                "mode": mode,
                "logged_by": ctx.name or ctx.phone,
                "allocation": alloc_data,
                "tenant_name": tenant.name,
                "room_number": _room.room_number,
                "pending_months": [{"period": m["period"].isoformat(), "remaining": float(m["remaining"])} for m in pending_months],
            },
            [], session,
        )
        alloc_text = format_allocation(allocation, amount, mode)
        return (
            snapshot["text"] + "\n"
            + alloc_text + "\n\n"
            'Reply *Yes* to confirm, or specify different allocation:\n'
            '  e.g. "all to march" or "feb 3000 march 5000"'
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
```

- [ ] **Step 3: Add `CONFIRM_PAYMENT_ALLOC` pending handler in chat_api.py or account_handler confirm flow**

Find where `CONFIRM_PAYMENT_LOG` is handled in `owner_handler.py` (the pending action resolution). After the existing `CONFIRM_PAYMENT_LOG` block, add handling for `CONFIRM_PAYMENT_ALLOC`:

Search for the `CONFIRM_PAYMENT_LOG` pending handler in `owner_handler.py` and add `CONFIRM_PAYMENT_ALLOC` alongside it. The handler needs to:

1. Check if response is affirmative → log payments per allocation split (call `_do_log_payment_by_ids` once per month in allocation)
2. Check if response is negative → cancel
3. Otherwise → try `parse_allocation_override()`, recalculate, show new confirmation

Add to the pending intent routing in `chat_api.py` line 570 — add `"CONFIRM_PAYMENT_ALLOC"` to the list that routes to owner_handler pending resolution.

Then in `owner_handler.py`, find the pending handler section and add:

```python
    if pending.intent == "CONFIRM_PAYMENT_ALLOC":
        from src.whatsapp.handlers._shared import parse_allocation_override
        from src.whatsapp.handlers.account_handler import _do_log_payment_by_ids

        ans = reply_text.strip()
        if is_negative(ans):
            return "Cancelled. No payment logged."

        if is_affirmative(ans):
            # Log payments per allocation
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
                    skip_duplicate_check=(i > 0),  # skip dup check for split payments
                )
                month_label = date.fromisoformat(alloc["period"]).strftime("%b %Y")
                results.append(f"{month_label}: Rs.{int(alloc['amount']):,} -- {r}")
            return "\n".join(results)

        # Try override parsing
        pending_months_raw = action_data.get("pending_months", [])
        if pending_months_raw:
            pending_months = [{"period": date.fromisoformat(m["period"]), "remaining": Decimal(str(m["remaining"]))} for m in pending_months_raw]
            override = parse_allocation_override(ans, pending_months)
            if override:
                amount = Decimal(str(action_data["amount"]))
                # Resolve "all to X" — amount=None means full amount
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
```

- [ ] **Step 4: Register `CONFIRM_PAYMENT_ALLOC` in chat_api.py routing**

In `chat_api.py` line 570, add `"CONFIRM_PAYMENT_ALLOC"` to the tuple:

```python
    if pending_intent in ("ADD_TENANT_STEP", "RECORD_CHECKOUT", "CONFIRM_PAYMENT_LOG", "COLLECT_RENT_STEP", "LOG_EXPENSE_STEP", "CONFIRM_PAYMENT_ALLOC"):
```

- [ ] **Step 5: Verify module imports cleanly**

Run: `cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant" && venv/Scripts/python -c "from src.whatsapp.handlers.account_handler import handle_account; print('OK')"`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/whatsapp/handlers/account_handler.py src/whatsapp/handlers/owner_handler.py src/whatsapp/chat_api.py
git commit -m "feat: rework _payment_log with dues snapshot + smart allocation"
```

---

## Task 3: Rework `COLLECT_RENT_STEP` in owner_handler.py

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py:834-1027`

- [ ] **Step 1: Add snapshot import to owner_handler.py**

Add `build_dues_snapshot, compute_allocation, format_allocation` to the existing `_shared` imports at the top of owner_handler.py.

- [ ] **Step 2: Add snapshot display after tenant identification**

In the `COLLECT_RENT_STEP` handler, after tenant is identified (step `ask_name`, single match — around line 857-885), insert snapshot fetch between tenant identification and asking for cash amount:

```python
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
                # ... existing notes fetch code stays ...
            except Exception:
                pass

            action_data["step"] = "ask_cash"
            await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)
            return snapshot["text"] + "\n\n*Cash amount?* (number, or *skip* if no cash)"
```

Do the same for `pick_tenant` step (around line 893-909) — after resolving the picked tenant, fetch and show snapshot.

- [ ] **Step 3: Add allocation at confirm step**

In the `confirm` step (around line 986), before logging payments, compute allocation and show it:

Replace the existing confirm step with one that:
1. Computes total from cash + upi
2. Calls `compute_allocation(total, pending_months)` using months stored in `action_data["pending_months"]`
3. If multiple months with dues → show allocation for confirmation (save as `CONFIRM_PAYMENT_ALLOC` pending with the split data, reusing the handler from Task 2)
4. If single month → log directly as before

The key change is in the step before `confirm` — after collecting cash + upi + notes, instead of going straight to a basic confirm, show the allocation:

```python
        if step == "ask_notes":
            # ... existing notes handling ...

            cash = action_data.get("cash", 0)
            upi = action_data.get("upi", 0)
            total = cash + upi
            tname = action_data.get("tenant_name", "")
            rnum = action_data.get("room_number", "")

            pending_months_raw = action_data.get("pending_months", [])
            pending_months = [
                {"period": date.fromisoformat(m["period"]), "remaining": Decimal(str(m["remaining"]))}
                for m in pending_months_raw
            ] if pending_months_raw else []

            parts = []
            if cash > 0:
                parts.append(f"Cash: Rs.{int(cash):,}")
            if upi > 0:
                parts.append(f"UPI: Rs.{int(upi):,}")
            notes_str = action_data.get("notes", "")
            notes_action = action_data.get("notes_action", "skip")

            # Compute allocation
            if pending_months and len(pending_months) > 1:
                from src.whatsapp.handlers._shared import compute_allocation, format_allocation
                alloc = compute_allocation(Decimal(str(total)), pending_months)
                alloc_data = [{"period": a["period"].isoformat(), "amount": float(a["amount"])} for a in alloc]
                action_data["allocation"] = alloc_data

                alloc_text = format_allocation(alloc, total, "cash" if cash > 0 else "upi")

                action_data["step"] = "confirm"
                await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)

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
                # Single month or no pending — original behavior
                action_data["step"] = "confirm"
                await _save_pending(pending.phone, "COLLECT_RENT_STEP", action_data, [], session)
                pm = pending_months[0]["period"] if pending_months else date.today().replace(day=1)
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
```

- [ ] **Step 4: Update confirm step to handle allocation**

In the `confirm` step, when user says "yes", check if `action_data` has an `allocation` key. If so, log split payments per allocation (same logic as Task 2's `CONFIRM_PAYMENT_ALLOC`). If not, use existing single-month logic.

If user sends an override text instead of yes/no, parse it with `parse_allocation_override()`, update action_data, re-show confirm.

- [ ] **Step 5: Verify module imports cleanly**

Run: `cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant" && venv/Scripts/python -c "from src.whatsapp.handlers.owner_handler import handle_owner; print('OK')"`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "feat: rework COLLECT_RENT_STEP with dues snapshot + allocation"
```

---

## Task 4: Notes sync with retry in gsheets.py

**Files:**
- Modify: `src/integrations/gsheets.py`

- [ ] **Step 1: Add retry wrapper for notes sync**

Add after the existing `update_notes` function (around line 990):

```python
async def sync_notes_with_retry(
    room_number: str,
    tenant_name: str,
    notes: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    max_retries: int = 3,
) -> dict:
    """
    Update notes in Sheet with retry. Up to max_retries attempts.
    Returns the result dict from the last attempt.
    """
    for attempt in range(max_retries):
        result = await update_notes(room_number, tenant_name, notes, month, year)
        if result.get("success"):
            return result
        if attempt < max_retries - 1:
            await asyncio.sleep(1 * (attempt + 1))  # backoff: 1s, 2s
            logger.warning("GSheets sync retry %d/%d for %s: %s", attempt + 1, max_retries, tenant_name, result.get("error"))
    logger.error("GSheets sync FAILED after %d retries for %s/%s: %s", max_retries, room_number, tenant_name, result.get("error"))
    return result
```

- [ ] **Step 2: Add TENANTS tab notes sync function**

Add after the retry function:

```python
def _update_tenants_tab_notes_sync(room_number: str, tenant_name: str, notes: str) -> dict:
    """Update permanent notes in the TENANTS tab."""
    result: dict[str, Any] = {"success": False, "error": None}
    try:
        ws = _get_worksheet_sync("TENANTS")
        all_vals = ws.get_all_values()
        room_clean = room_number.strip().upper()
        name_lower = tenant_name.strip().lower()
        # Find notes column — scan header for "Notes" or "Comment"
        header = all_vals[0] if all_vals else []
        notes_col = None
        for i, h in enumerate(header):
            if h.strip().lower() in ("notes", "comment", "remarks"):
                notes_col = i
                break
        if notes_col is None:
            result["error"] = "Notes column not found in TENANTS tab"
            return result

        for i in range(1, len(all_vals)):
            r = all_vals[i]
            if (str(r[0]).strip().upper() == room_clean and
                    name_lower in str(r[1]).strip().lower()):
                cell = gspread.utils.rowcol_to_a1(i + 1, notes_col + 1)
                ws.update(values=[[notes]], range_name=cell, value_input_option="USER_ENTERED")
                result["success"] = True
                logger.info("GSheets: updated TENANTS notes for %s row %d", tenant_name, i + 1)
                return result

        result["error"] = f"Row not found for {room_number}/{tenant_name} in TENANTS"
    except Exception as e:
        result["error"] = f"TENANTS notes update failed: {e}"
    return result


async def sync_tenants_tab_notes(
    room_number: str,
    tenant_name: str,
    notes: str,
    max_retries: int = 3,
) -> dict:
    """Async entry point — update permanent notes in TENANTS tab with retry."""
    for attempt in range(max_retries):
        result = await asyncio.to_thread(_update_tenants_tab_notes_sync, room_number, tenant_name, notes)
        if result.get("success"):
            return result
        if attempt < max_retries - 1:
            await asyncio.sleep(1 * (attempt + 1))
            logger.warning("GSheets TENANTS sync retry %d/%d for %s: %s", attempt + 1, max_retries, tenant_name, result.get("error"))
    logger.error("GSheets TENANTS sync FAILED after %d retries for %s: %s", max_retries, tenant_name, result.get("error"))
    return result
```

- [ ] **Step 3: Verify module imports cleanly**

Run: `cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant" && venv/Scripts/python -c "from src.integrations.gsheets import sync_notes_with_retry, sync_tenants_tab_notes; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/integrations/gsheets.py
git commit -m "feat: add notes sync with retry + TENANTS tab notes update"
```

---

## Task 5: Notes carry-over logic

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py` (where RentSchedule rows are created, around line 2382-2415)

- [ ] **Step 1: Add carry-over in the add-tenant RentSchedule generation**

In `owner_handler.py`, in the function that creates RentSchedule rows for a new tenant (around line 2402), add carry-over logic. Since this is a NEW tenant, there are no previous notes to carry over — the first month starts with whatever notes were provided at checkin. No change needed here.

- [ ] **Step 2: Add carry-over where new month RentSchedule is auto-generated**

The payment logging code in `_do_log_payment_by_ids` (account_handler.py around line 305-310) creates a RentSchedule if one doesn't exist for the payment month. Add carry-over there:

```python
    rs = await session.scalar(
        select(RentSchedule).where(
            RentSchedule.tenancy_id == tenancy.id,
            RentSchedule.period_month == period_month,
        )
    )

    if not rs:
        # Auto-generate rent_schedule for this month
        # Carry over notes from previous month
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
```

Check if this auto-generation code already exists in `_do_log_payment_by_ids`. If not, this is the place where it should be added (currently the code just proceeds with `rs = None` and uses `tenancy.agreed_rent` as fallback at line 320).

- [ ] **Step 3: Verify no issues**

Run: `cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant" && venv/Scripts/python -c "from src.whatsapp.handlers.account_handler import handle_account; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/whatsapp/handlers/account_handler.py
git commit -m "feat: add notes carry-over when auto-generating rent_schedule"
```

---

## Task 6: Write `rent_schedule.notes` during payment flow

**Files:**
- Modify: `src/whatsapp/handlers/owner_handler.py` (COLLECT_RENT_STEP confirm step, around line 1013-1027)

- [ ] **Step 1: After logging payment in COLLECT_RENT_STEP, update rent_schedule.notes**

In the confirm step of `COLLECT_RENT_STEP`, after payments are logged and the notes_action is processed, add DB + Sheet sync:

```python
                # Update rent_schedule notes if changed
                notes_action = action_data.get("notes_action", "skip")
                if notes_action in ("update", "delete"):
                    new_notes = action_data.get("notes", "") if notes_action == "update" else None
                    # Update DB — rent_schedule.notes for current month
                    current_month = date.today().replace(day=1)
                    rs = await session.scalar(
                        select(RentSchedule).where(
                            RentSchedule.tenancy_id == action_data["tenancy_id"],
                            RentSchedule.period_month == current_month,
                        )
                    )
                    if rs:
                        rs.notes = new_notes

                    # Sync to Sheet (with retry)
                    try:
                        from src.integrations.gsheets import sync_notes_with_retry
                        await sync_notes_with_retry(rnum, tname, new_notes or "")
                    except Exception as e:
                        import logging as _log
                        _log.getLogger(__name__).error("Notes sync failed: %s", e)
```

This replaces the existing notes update block that only wrote to Sheet.

- [ ] **Step 2: Same for CONFIRM_PAYMENT_ALLOC handler**

In the `CONFIRM_PAYMENT_ALLOC` handler (added in Task 2), after logging split payments, if there are notes in the action_data, update `rent_schedule.notes` for each month that received a payment.

- [ ] **Step 3: Commit**

```bash
git add src/whatsapp/handlers/owner_handler.py
git commit -m "feat: write rent_schedule.notes during payment flow + Sheet sync"
```

---

## Task 7: `UPDATE_TENANT_NOTES` intent + handler

**Files:**
- Modify: `src/whatsapp/intent_detector.py`
- Modify: `src/whatsapp/gatekeeper.py`
- Modify: `src/whatsapp/handlers/owner_handler.py`

- [ ] **Step 1: Add regex patterns for UPDATE_TENANT_NOTES in intent_detector.py**

Add to `_OWNER_RULES` list (before the HELP pattern, near the end of the rules):

```python
    # Update tenant permanent notes / agreement
    (re.compile(r"(?:update\s+(?:tenant\s+)?(?:notes?|agreement)\s+(?:for\s+)?\w+|change\s+(?:tenant\s+)?(?:notes?|agreement)\s+(?:for\s+)?\w+|tenant\s+(?:notes?|agreement)\s+(?:for\s+)?\w+|update\s+agreement\s+(?:for\s+)?\w+|edit\s+(?:tenant\s+)?notes?\s+(?:for\s+)?\w+|modify\s+(?:tenant\s+)?notes?\s+(?:for\s+)?\w+)", re.I), "UPDATE_TENANT_NOTES", 0.93),
```

- [ ] **Step 2: Route UPDATE_TENANT_NOTES in gatekeeper.py**

`UPDATE_TENANT_NOTES` is NOT a financial intent, so it will route to `owner_handler` automatically via the else branch. No change needed in gatekeeper.py — the existing routing handles it.

Verify: `UPDATE_TENANT_NOTES` is NOT in `FINANCIAL_INTENTS` and NOT in `RECEPTIONIST_BLOCKED`, so it routes to `handle_owner()` for all owner-level roles including receptionist. Correct.

- [ ] **Step 3: Add UPDATE_TENANT_NOTES handler in owner_handler.py**

Add in the `handle_owner` dispatcher function:

```python
    if intent == "UPDATE_TENANT_NOTES":
        return await _update_tenant_notes(entities, ctx, session)
```

Then add the handler function:

```python
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
```

- [ ] **Step 4: Add pending handler for UPDATE_TENANT_NOTES_STEP**

Add to the pending resolution section in `owner_handler.py`:

```python
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

                # Sync to Sheet TENANTS tab
                try:
                    from src.integrations.gsheets import sync_tenants_tab_notes
                    await sync_tenants_tab_notes(
                        action_data["room_number"],
                        action_data["tenant_name"],
                        new_notes if notes_action == "update" else "",
                    )
                except Exception as e:
                    import logging as _log
                    _log.getLogger(__name__).error("TENANTS tab sync failed: %s", e)

                return f"Tenant agreement updated for *{action_data['tenant_name']}*."

            return "__KEEP_PENDING__Reply *Yes* to save or *No* to cancel."
```

- [ ] **Step 5: Register UPDATE_TENANT_NOTES_STEP in chat_api.py routing**

In `chat_api.py` line 570, add `"UPDATE_TENANT_NOTES_STEP"` to the routing tuple:

```python
    if pending_intent in ("ADD_TENANT_STEP", "RECORD_CHECKOUT", "CONFIRM_PAYMENT_LOG", "COLLECT_RENT_STEP", "LOG_EXPENSE_STEP", "CONFIRM_PAYMENT_ALLOC", "UPDATE_TENANT_NOTES_STEP"):
```

- [ ] **Step 6: Verify**

Run: `cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant" && venv/Scripts/python -c "from src.whatsapp.intent_detector import detect; print('OK')"`

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/whatsapp/intent_detector.py src/whatsapp/gatekeeper.py src/whatsapp/handlers/owner_handler.py src/whatsapp/chat_api.py
git commit -m "feat: add UPDATE_TENANT_NOTES intent + handler"
```

---

## Task 8: Import reclassification in excel_import.py

**Files:**
- Modify: `src/database/excel_import.py`

- [ ] **Step 1: Add keyword classification constants**

Add near the top of `excel_import.py`:

```python
import re as _re

_PERMANENT_SIGNALS = _re.compile(
    r"(?:always|agreed|checkout|planned|lease|contract|first.*months|from.*month|company|student|parent)",
    _re.I,
)
_MONTHLY_SIGNALS = _re.compile(
    r"(?:will pay|by \d+|next week|balance|partial|collected|pending)",
    _re.I,
)


def classify_comment(comment: str) -> str:
    """Classify a comment as 'permanent', 'monthly', or 'ambiguous'."""
    if not comment or not comment.strip():
        return "permanent"
    if _PERMANENT_SIGNALS.search(comment):
        return "permanent"
    if _MONTHLY_SIGNALS.search(comment):
        return "monthly"
    return "ambiguous"
```

- [ ] **Step 2: Add --preview-notes mode**

In the `main()` function or argument parser section, add:

```python
async def preview_notes():
    """Show classification of all tenant comments for review."""
    import json
    from scripts.clean_and_load import read_history

    tenants = read_history()
    rows_with_comments = [(i, t) for i, t in enumerate(tenants, 1) if t.get("comment", "").strip()]

    print(f"\n{'Row':>4}  {'Tenant':<20}  {'Comment':<45}  Type")
    print("-" * 95)

    ambiguous = []
    for row_num, t in rows_with_comments:
        comment = t["comment"].strip()
        cls = classify_comment(comment)
        tag = "PERM" if cls == "permanent" else ("MONTH" if cls == "monthly" else "???")
        print(f"{row_num:>4}  {t['name']:<20}  {comment:<45}  {tag}")
        if cls == "ambiguous":
            ambiguous.append({
                "row": row_num,
                "tenant": t["name"],
                "comment": comment,
                "type": "permanent",  # default for user to change
            })

    if ambiguous:
        out_path = Path("data/notes_classification.json")
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(ambiguous, indent=2))
        print(f"\n{len(ambiguous)} ambiguous comments need classification.")
        print(f"Edit {out_path} and re-run with --write")
    else:
        print(f"\nAll {len(rows_with_comments)} comments auto-classified. No manual review needed.")
```

- [ ] **Step 3: Modify import to use classification**

In the import function where `tenancy.notes` is set (around line 261), add:

```python
            # Load classification overrides
            classification_path = Path("data/notes_classification.json")
            overrides = {}
            if classification_path.exists():
                import json
                for entry in json.loads(classification_path.read_text()):
                    overrides[entry["tenant"]] = entry["type"]

            # Classify comment
            comment = rec.get('comment') or ""
            cls = overrides.get(rec["name"], classify_comment(comment))

            if cls == "permanent" or cls == "ambiguous":
                tenancy.notes = comment or None
                monthly_note = None
            else:
                tenancy.notes = None  # monthly — will go to rent_schedule
                monthly_note = comment
```

Then in the rent_schedule creation loop (the `for st_key, period, cash_key, upi_key in MONTH_COLS:` loop), track the last rent_schedule created. After the loop, if `monthly_note` is set, update the last rent_schedule's notes:

```python
            last_rs = None
            for st_key, period, cash_key, upi_key in MONTH_COLS:
                # ... existing rent_schedule creation ...
                if rs_obj:  # track last created
                    last_rs = rs_obj

            # Apply monthly-classified comment to most recent rent_schedule
            if monthly_note and last_rs:
                last_rs.notes = monthly_note
```

- [ ] **Step 4: Add CLI argument handling**

Add to the argument parser:

```python
    parser.add_argument("--preview-notes", action="store_true", help="Preview comment classification")
```

And in the main block:

```python
    if args.preview_notes:
        asyncio.run(preview_notes())
        return
```

- [ ] **Step 5: Verify**

Run: `cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant" && venv/Scripts/python -m src.database.excel_import --preview-notes`

Expected: table of tenants with comments and their classifications.

- [ ] **Step 6: Commit**

```bash
git add src/database/excel_import.py
git commit -m "feat: add import notes reclassification with --preview-notes"
```

---

## Task 9: Workflow tests

**Files:**
- Modify: `tests/test_workflow_flows.py`

- [ ] **Step 1: Add payment snapshot tests**

Add to the test file:

```python
# ── Payment Flow with Dues Snapshot ──────────────────────────────────────────

def test_payment_shows_snapshot():
    """Quick payment should show dues snapshot before confirmation."""
    # Assumes test tenant exists with pending dues
    resp = send("Raj paid 8000 cash")
    text = reply_text(resp)
    # Should show snapshot with dues breakdown
    missing = contains(text, "dues", "outstanding", "confirm")
    assert not missing, f"Snapshot missing: {missing}. Got: {text[:200]}"

def test_payment_single_month():
    """Payment for tenant with single month dues — no allocation question."""
    resp = send("Raj paid 14000 cash")
    text = reply_text(resp)
    # Single month — should go straight to confirm without allocation options
    assert "yes" in text.lower() or "confirm" in text.lower(), f"Expected confirm prompt. Got: {text[:200]}"

def test_payment_multi_month_allocation():
    """Payment spanning multiple months should show allocation."""
    resp = send("Raj paid 8000 cash")
    text = reply_text(resp)
    if "allocation" in text.lower() or "->" in text:
        # Multi-month — confirm allocation
        resp2 = send("yes")
        text2 = reply_text(resp2)
        assert "logged" in text2.lower() or "rs." in text2.lower(), f"Expected payment logged. Got: {text2[:200]}"

def test_payment_allocation_override():
    """Override allocation with 'all to march'."""
    resp = send("Raj paid 8000 cash")
    text = reply_text(resp)
    if "allocation" in text.lower() or "->" in text:
        resp2 = send("all to march")
        text2 = reply_text(resp2)
        assert "march" in text2.lower() or "mar" in text2.lower(), f"Expected March allocation. Got: {text2[:200]}"
        resp3 = send("yes")
        text3 = reply_text(resp3)
        assert "logged" in text3.lower() or "rs." in text3.lower(), f"Expected payment logged. Got: {text3[:200]}"
```

- [ ] **Step 2: Add tenant notes tests**

```python
def test_update_tenant_notes():
    """UPDATE_TENANT_NOTES intent should show current notes and allow edit."""
    resp = send("update agreement for Raj")
    text = reply_text(resp)
    missing = contains(text, "agreement", "notes")
    assert any_contains(text, "agreement", "notes", "current"), f"Expected notes prompt. Got: {text[:200]}"
    # Update notes
    resp2 = send("Always cash. Checkout June 2026.")
    text2 = reply_text(resp2)
    assert "yes" in text2.lower() or "confirm" in text2.lower(), f"Expected confirm. Got: {text2[:200]}"
    # Confirm
    resp3 = send("yes")
    text3 = reply_text(resp3)
    assert "updated" in text3.lower(), f"Expected updated. Got: {text3[:200]}"

def test_delete_tenant_notes():
    """Delete tenant notes."""
    resp = send("update notes Raj")
    text = reply_text(resp)
    resp2 = send("delete")
    text2 = reply_text(resp2)
    assert "clear" in text2.lower() or "delete" in text2.lower(), f"Expected clear confirmation. Got: {text2[:200]}"
    resp3 = send("yes")
    text3 = reply_text(resp3)
    assert "updated" in text3.lower(), f"Expected updated. Got: {text3[:200]}"
```

- [ ] **Step 3: Add collect rent snapshot test**

```python
def test_collect_rent_shows_snapshot():
    """Step-by-step collect rent should show snapshot after tenant ID."""
    resp = send("collect rent")
    text = reply_text(resp)
    assert "who paid" in text.lower(), f"Expected name prompt. Got: {text[:200]}"
    resp2 = send("Raj")
    text2 = reply_text(resp2)
    # Should show snapshot + cash prompt
    assert "cash" in text2.lower(), f"Expected cash prompt. Got: {text2[:200]}"
    # Should show dues or "all paid"
    assert any_contains(text2, "dues", "outstanding", "all paid", "unpaid", "partial"), f"Expected dues info. Got: {text2[:200]}"
```

- [ ] **Step 4: Run tests**

Run: `cd "c:/Users/kiran/Desktop/AI Watsapp PG Accountant" && venv/Scripts/python tests/test_workflow_flows.py`

Expected: new tests pass alongside existing tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_workflow_flows.py
git commit -m "test: add payment snapshot + allocation + tenant notes workflow tests"
```

---

## Task 10: Update docs

**Files:**
- Modify: `docs/BOT_FLOWS.md`
- Modify: `docs/RECEPTIONIST_CHEAT_SHEET.md`

- [ ] **Step 1: Update BOT_FLOWS.md**

Add `UPDATE_TENANT_NOTES` to the intent catalog table. Update the PAYMENT_LOG flow example to show the new snapshot + allocation flow.

- [ ] **Step 2: Update RECEPTIONIST_CHEAT_SHEET.md**

Add a new section:

```markdown
## UPDATE TENANT NOTES

| Message | What it does |
|---------|-------------|
| **update agreement for Raj** | View + edit permanent tenant notes |
| **update tenant notes Raj** | Same |
| **change notes for room 301** | Same, by room |
```

Update the COLLECT RENT section to mention that the bot now shows dues before asking for amounts.

- [ ] **Step 3: Commit**

```bash
git add docs/BOT_FLOWS.md docs/RECEPTIONIST_CHEAT_SHEET.md
git commit -m "docs: update bot flows + cheat sheet for payment rework + tenant notes"
```
