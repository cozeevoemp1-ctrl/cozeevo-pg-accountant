"""
src/utils/room_floor.py
=======================
Single source of truth for deriving floor number from a room number string.

Convention (Cozeevo):
    "G01"..."G20" → floor 0 (ground)
    "101".."120"  → floor 1
    "201".."220"  → floor 2
    ...
    "601".."620"  → floor 6
    "508/509"     → first numeric prefix (5)

Returns int or None if the room number is non-numeric / unknown.
"""
from __future__ import annotations


def derive_floor(room_number: str | None) -> int | None:
    if not room_number:
        return None
    rn = str(room_number).strip().upper()
    if rn.startswith("G"):
        return 0
    # First digit of the first numeric chunk
    for ch in rn:
        if ch.isdigit():
            return int(ch)
    return None
