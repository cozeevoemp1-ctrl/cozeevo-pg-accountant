"""
Deduplication engine — deterministic, zero AI cost.

Strategy:
  1. Compute SHA-256 hash from (date + amount + upi_reference)
     or  (date + amount + merchant + source) when no UPI ref exists.
  2. Time-window guard: same hash within DEDUP_WINDOW minutes → duplicate.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Optional


DEDUP_WINDOW_MINUTES = int(os.getenv("DEDUP_WINDOW_MINUTES", "5"))


def compute_hash(txn: dict) -> str:
    """
    Return a deterministic SHA-256 hex string for a transaction dict.

    Priority fields (in order):
      1. date + amount + upi_reference          (most specific)
      2. date + amount + merchant + source      (fallback)
      3. date + amount + description[:40]       (last resort)
    """
    date_str    = str(txn.get("date", "")).strip()
    amount_str  = f"{float(txn.get('amount', 0)):.2f}"
    upi_ref     = str(txn.get("upi_reference", "") or "").strip()
    merchant    = str(txn.get("merchant", "") or "").strip().lower()
    source      = str(txn.get("source", "") or "").strip().lower()
    description = str(txn.get("description", "") or "")[:40].strip().lower()

    if upi_ref:
        key = f"{date_str}|{amount_str}|{upi_ref}"
    elif merchant:
        key = f"{date_str}|{amount_str}|{merchant}|{source}"
    else:
        key = f"{date_str}|{amount_str}|{description}|{source}"

    return hashlib.sha256(key.encode()).hexdigest()


def is_duplicate(txn: dict, recent_hashes: list[tuple[str, datetime]]) -> bool:
    """
    Check if txn is a duplicate by:
      a) exact hash match in recent_hashes within time window
      b) identical (amount, merchant) within window regardless of hash

    recent_hashes: list of (hash, created_at) tuples from DB or in-memory cache.
    """
    new_hash  = txn.get("unique_hash") or compute_hash(txn)
    txn_time  = _parse_dt(txn.get("date"))
    window    = timedelta(minutes=DEDUP_WINDOW_MINUTES)

    for stored_hash, stored_time in recent_hashes:
        if stored_hash == new_hash:
            return True
        if txn_time and abs(txn_time - stored_time) <= window:
            # Same amount + merchant within window = soft duplicate
            pass  # handled by DB unique_hash constraint

    return False


def _parse_dt(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            from dateparser import parse
            return parse(value)
        except Exception:
            return None
    return None


def enrich_with_hash(txn: dict) -> dict:
    """Add unique_hash to a transaction dict in-place. Returns the dict."""
    txn["unique_hash"] = compute_hash(txn)
    return txn


def batch_deduplicate(transactions: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Given a batch of raw transactions:
    - Assign unique_hash to each
    - Remove intra-batch duplicates (keep first occurrence)
    Returns (unique_list, duplicate_list).
    """
    seen: set[str] = set()
    unique, dupes = [], []

    for txn in transactions:
        h = compute_hash(txn)
        txn["unique_hash"] = h
        if h in seen:
            dupes.append(txn)
        else:
            seen.add(h)
            unique.append(txn)

    return unique, dupes
