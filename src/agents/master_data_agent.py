"""
Master data agent — handles detection and approval of new entities.

When a transaction references an unknown customer / vendor / employee:
  1. Suggest entity fields (rules-first, AI if unclear)
  2. Queue in pending_entities table
  3. Present interactive VS Code terminal prompt for approval
  4. On approval → insert into master table
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

import questionary
from loguru import logger

from src.database import db_manager


# ── Detection ──────────────────────────────────────────────────────────────

async def detect_unknown_entities(transactions: list[dict]) -> list[dict]:
    """
    For each transaction, try to match customer/vendor/employee by UPI ID or phone.
    Returns list of unmatched entity suggestions.
    """
    suggestions = []

    for txn in transactions:
        merchant    = txn.get("merchant", "")
        upi_ref     = txn.get("upi_reference", "")
        description = txn.get("description", "")
        txn_type    = txn.get("txn_type", "expense")

        if txn_type == "income":
            # Incoming payment → likely a customer (tenant)
            customer = await db_manager.get_customer_by_phone_or_upi(upi_ref or merchant)
            if not customer and merchant:
                suggestions.append({
                    "entity_type": "customer",
                    "txn": txn,
                    "suggested_name": merchant,
                    "suggested_upi": upi_ref,
                })

    return suggestions


# ── Interactive VS Code / Terminal Approval ────────────────────────────────

async def prompt_approval_interactive(suggestions: list[dict]) -> list[dict]:
    """
    Uses questionary to show interactive prompts in VS Code terminal.
    Returns list of approved entities.
    approved_entities includes the final data dict ready for DB insert.
    """
    approved = []

    for s in suggestions:
        entity_type    = s["entity_type"]
        txn            = s["txn"]
        suggested_name = s.get("suggested_name", "Unknown")
        suggested_upi  = s.get("suggested_upi", "")

        print(f"\n{'='*60}")
        print(f"  New {entity_type.upper()} detected in transaction:")
        print(f"  Date:   {txn.get('date')}")
        print(f"  Amount: ₹{txn.get('amount')}")
        print(f"  Desc:   {txn.get('description', '')[:60]}")
        print(f"  Party:  {suggested_name}")
        print(f"{'='*60}")

        confirm = questionary.confirm(
            f"Add '{suggested_name}' as a new {entity_type}?",
            default=True,
        ).ask()

        if not confirm:
            logger.info(f"Rejected new {entity_type}: {suggested_name}")
            continue

        # Collect details
        name = questionary.text("Name:", default=suggested_name).ask()
        phone = questionary.text("Phone (optional):", default="").ask()
        upi_id = questionary.text("UPI ID (optional):", default=suggested_upi or "").ask()

        data = {
            "name":   name.strip(),
            "phone":  phone.strip() or None,
            "upi_id": upi_id.strip() or None,
        }

        if entity_type == "customer":
            room = questionary.text("Room number (optional):", default="").ask()
            rent = questionary.text("Monthly rent amount (optional):", default="0").ask()
            data["room_number"]  = room.strip() or None
            data["rent_amount"]  = float(rent or 0)
            data["move_in_date"] = str(date.today())

        elif entity_type == "vendor":
            cat = questionary.text("Vendor category (e.g. Electricity, Groceries):", default="Miscellaneous").ask()
            data["category"] = cat.strip()

        elif entity_type == "employee":
            role   = questionary.text("Role (e.g. Cook, Cleaner):", default="").ask()
            salary = questionary.text("Monthly salary:", default="0").ask()
            data["role"]           = role.strip()
            data["monthly_salary"] = float(salary or 0)
            data["join_date"]      = str(date.today())

        # Queue and immediately approve
        pe = await db_manager.queue_pending_entity(
            entity_type=entity_type,
            data=data,
            source_hash=txn.get("unique_hash", ""),
            suggested_by="user_approved",
        )
        result = await db_manager.approve_pending_entity(pe.id)
        if result:
            approved.append(result)
            logger.info(f"Added {entity_type}: {name}")

    return approved


# ── Non-interactive (WhatsApp) approval ───────────────────────────────────

async def queue_for_whatsapp_approval(suggestions: list[dict]) -> str:
    """
    Queue suggestions and return a WhatsApp message asking for confirmation.
    The user can reply 'yes' or 'no [id]'.
    """
    if not suggestions:
        return ""

    queued_ids = []
    for s in suggestions:
        pe = await db_manager.queue_pending_entity(
            entity_type=s["entity_type"],
            data={"name": s["suggested_name"], "upi_id": s.get("suggested_upi", "")},
            source_hash=s["txn"].get("unique_hash", ""),
            suggested_by="ai",
        )
        queued_ids.append((pe.id, s["entity_type"], s["suggested_name"]))

    lines = ["New entries detected — approve?"]
    for pid, etype, name in queued_ids:
        lines.append(f"  [{pid}] {etype.title()}: {name}")
    lines.append("\nReply: 'approve <id>' or 'reject <id>'")
    return "\n".join(lines)
