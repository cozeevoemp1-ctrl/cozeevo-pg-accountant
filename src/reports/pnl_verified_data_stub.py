"""Demo stub — replaces pnl_verified_data.py in demo deployments (include_verified is
always False there, so these are never rendered)."""
from __future__ import annotations

from typing import Dict, List

MONTHS: List[str] = []

INCOME: Dict[str, List[int]] = {}
CAPITAL_CONTRIBUTIONS: Dict[str, List[int]] = {}
KEY_OPEX_WATER = ""
KEY_OPEX_WASTE = ""
OPEX: Dict[str, List[int]] = {}
EXCLUDED: Dict[str, List[int]] = {}

DEPOSIT_RECEIVED: List[int] = []
DEPOSIT_REFUNDED: List[int] = []

DEPOSITS: Dict[str, List[int]] = {}

BANK_BALANCE_THOR: Dict[str, tuple] = {}
BANK_BALANCE_HULK: Dict[str, tuple] = {}

BANK_CLOSING_BALANCE_THOR = 0
BANK_CLOSING_BALANCE_HULK = 0

CASH_IN_HAND: Dict[str, int] = {}

THOR_CAP_IN: List[int] = []
THOR_CAP_OUT: List[int] = []

RECON_NOTES: List[tuple] = []

KIRAN_REVIEW_FLAGS: List[str] = []

RULES_APPLIED: List[tuple] = []
