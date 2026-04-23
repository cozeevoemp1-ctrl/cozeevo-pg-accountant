"""Canonical rent-status computation.

Single source of truth for the PAID / PARTIAL / NO-SHOW / EXIT classification
shown in every monthly tab and bot reply. Must stay in lockstep with the
Apps Script onEdit recalc in `scripts/gsheet_apps_script.js`.

Kiran 2026-04-23: rule is rent-only. prev_due is tracked via Balance, not
Status. UNPAID does not exist on live months — any shortfall on this month's
rent is PARTIAL. See docs/CHANGELOG.md 1.51.0.
"""
from __future__ import annotations

from typing import Final

# Canonical status strings. Kept as module-level constants (not Enum) so they
# serialise cleanly to Sheet cells without `.value` juggling.
PAID: Final[str] = "PAID"
PARTIAL: Final[str] = "PARTIAL"
UNPAID: Final[str] = "UNPAID"  # historical (Dec–Mar 2026 frozen cells only)
NO_SHOW: Final[str] = "NO-SHOW"
EXIT: Final[str] = "EXIT"

# Non-billed statuses that skip the paid/partial computation entirely.
NON_BILLED: Final[frozenset[str]] = frozenset({NO_SHOW, EXIT, "ADVANCE", "CANCELLED"})


def compute_status(effective_paid: float, rent_due: float) -> str:
    """Rent-only status. Called from every site that sets a Status cell.

    - rent_due == 0     → PAID  (no bill this month → treated as cleared)
    - effective_paid >= rent_due → PAID
    - effective_paid < rent_due  → PARTIAL

    `effective_paid` must already include any first-month booking/deposit
    credits that count toward the monthly bundle. `rent_due` is the schedule's
    (rent_due + adjustment), NOT rent_due + prev_due.
    """
    if rent_due <= 0:
        return PAID
    if effective_paid >= rent_due:
        return PAID
    return PARTIAL
