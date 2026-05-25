"""
Role detection + rate limiting for incoming WhatsApp messages.

Every inbound message goes through this gate:
  1. Hardcoded allowlist check → BLOCKED immediately if not on list
  2. Role lookup from hardcoded map
  3. Return CallerContext

Only phones in _HARDCODED_ROLES can use the bot. Everyone else (tenants,
leads, unknown numbers) is silently blocked — no response.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    AuthorizedUser, RateLimitLog, Tenant, UserRole
)

# ── Config ────────────────────────────────────────────────────────────────────
RATE_WINDOW_MINUTES = 10
RATE_WINDOW_LIMIT   = 10    # max messages per 10-min window
RATE_DAY_LIMIT      = 50    # max messages per day

ADMIN_PHONE = os.getenv("ADMIN_PHONE", "")

# ── Hardcoded allowlist — ONLY these phones can use the bot ──────────────────
# Format: normalized_phone → (name, role)
# Roles: "admin" | "owner" | "receptionist"
# To add/remove someone: edit this dict and redeploy.
_HARDCODED_ROLES: dict[str, tuple[str, str]] = {
    "7845952289": ("Kiran",       "admin"),
    "7358341775": ("Lakshmi",     "owner"),
    "9444296681": ("Prabhakaran", "owner"),
    "7680814628": ("Lokesh",      "receptionist"),
}


@dataclass
class CallerContext:
    phone:        str
    role:         str          # "admin" | "owner" | "receptionist" | "tenant" | "lead" | "blocked"
    name:         str
    tenant_id:    Optional[int] = None
    auth_user_id: Optional[int] = None
    is_blocked:   bool = False


async def get_caller_context(phone: str, session: AsyncSession) -> CallerContext:
    """
    Gate check: hardcoded allowlist only.
    Phones not in _HARDCODED_ROLES are silently blocked — no response sent.
    """
    phone = _normalize(phone)

    entry = _HARDCODED_ROLES.get(phone)
    if entry:
        name, role = entry
        return CallerContext(phone=phone, role=role, name=name)

    # Not on the allowlist — block silently (tenants, leads, anyone else)
    return CallerContext(phone=phone, role="blocked", name="", is_blocked=True)


async def _is_rate_limited(phone: str, session: AsyncSession) -> bool:
    """
    Check and update rate limit counters.
    Returns True if the caller should be blocked.
    TEST_MODE=1 in .env bypasses all rate limiting (for automated tests only).
    """
    if os.getenv("TEST_MODE", "").split("#")[0].strip() == "1":
        return False

    now = datetime.utcnow()
    window_start = now.replace(second=0, microsecond=0)
    # Round down to nearest 10-min block
    window_start = window_start.replace(
        minute=(window_start.minute // RATE_WINDOW_MINUTES) * RATE_WINDOW_MINUTES
    )
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Get or create window record
    result = await session.execute(
        select(RateLimitLog).where(
            RateLimitLog.phone == phone,
            RateLimitLog.window_start == window_start,
        )
    )
    log = result.scalars().first()

    if log:
        if log.message_count >= RATE_WINDOW_LIMIT:
            return True
        if log.day_count >= RATE_DAY_LIMIT:
            return True
        log.message_count += 1
        log.day_count += 1
        log.last_seen_at = now
    else:
        # Count today's messages across all windows
        result = await session.execute(
            select(func.sum(RateLimitLog.message_count)).where(
                RateLimitLog.phone == phone,
                RateLimitLog.window_start >= day_start,
            )
        )
        today_count = result.scalar() or 0

        if today_count >= RATE_DAY_LIMIT:
            return True

        log = RateLimitLog(
            phone=phone,
            window_start=window_start,
            message_count=1,
            day_count=int(today_count) + 1,
            last_seen_at=now,
        )
        session.add(log)

    return False


def _normalize(phone: str) -> str:
    """
    Normalize any phone format to a consistent form for DB lookups.

    Indian numbers  → 10-digit  (e.g. 7845952289)
    International   → +prefix   (e.g. +966534015243)

    Handles all real-world formats without manual per-test fixes:
      +917845952289    → 7845952289   (WhatsApp standard: + country code)
       917845952289    → 7845952289   (no leading +)
      0917845952289    → 7845952289   (0 + country code, some diallers)
      00917845952289   → 7845952289   (international dialling prefix 00)
         7845952289    → 7845952289   (already 10-digit)
      whatsapp:+91...  → 7845952289   (n8n prefix variant)
    """
    # Strip provider prefix and whitespace
    phone = re.sub(r"(?i)whatsapp:", "", phone).strip()
    # Keep only digits (drop +, spaces, dashes, dots)
    digits = re.sub(r"\D", "", phone)
    # Remove leading international dialling zeros: 00 → ""
    if digits.startswith("00"):
        digits = digits[2:]
    # Remove single leading 0 (trunk prefix, rare for mobile)
    elif digits.startswith("0") and len(digits) > 10:
        digits = digits[1:]
    # Strip Indian country code 91 if result would be 10-digit starting with 6-9
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        digits = digits[2:]
    # Already a valid 10-digit Indian mobile number
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    # Non-Indian or unusual — restore + prefix so it stays unique
    return "+" + digits
