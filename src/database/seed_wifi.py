"""
src/database/seed_wifi.py
=========================
One-time seed script — loads all WiFi credentials for Thor Block and Hulk Block
into the first active property's wifi_floor_map JSON column.

Run:  python -m src.database.seed_wifi

Floor key mapping (numeric):
  "G"  = Ground floor
  "1"  = 1st floor
  "2"  = 2nd floor
  "3"  = 3rd floor
  "4"  = 4th floor
  "5"  = 5th floor
  "6"  = 6th floor
  "top"= Dining (TOP)
  "ws" = Work Area (WS)
  "gym"= Gym (B)

Structure:
  wifi_floor_map = {
    "thor": { "G": [{"ssid": "...", "password": "..."},...], "1": [...], ... },
    "hulk": { "G": [...], "1": [...], ... },
  }
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.database.db_manager import get_async_session
from src.database.models import Property

# ─── WiFi data ────────────────────────────────────────────────────────────────

WIFI_DATA = {
    "thor": {
        "G": [
            {"ssid": "cozeevo G1", "password": "cozeevo@g1"},
            {"ssid": "cozeevo G2", "password": "cozeevo@g2"},
            {"ssid": "cozeevo G3", "password": "cozeevo@g3"},
            {"ssid": "cozeevo G4", "password": "cozeevo@g4"},
        ],
        "1": [
            {"ssid": "cozeevo F1", "password": "cozeevo@f1"},
            {"ssid": "cozeevo F2", "password": "cozeevo@f2"},
            {"ssid": "cozeevo F3", "password": "cozeevo@f3"},
            {"ssid": "cozeevo F4", "password": "cozeevo@f4"},
        ],
        "2": [
            {"ssid": "cozeevo S1", "password": "cozeevo@s1"},
            {"ssid": "cozeevo S2", "password": "cozeevo@s2"},
            {"ssid": "cozeevo S3", "password": "cozeevo@s3"},
            {"ssid": "cozeevo S4", "password": "cozeevo@s4"},
        ],
        "3": [
            {"ssid": "cozeevo T1", "password": "cozeevo@t1"},
            {"ssid": "cozeevo T2", "password": "cozeevo@t2"},
            {"ssid": "cozeevo T3", "password": "cozeevo@t3"},
            {"ssid": "cozeevo T4", "password": "cozeevo@t4"},
        ],
        "4": [
            {"ssid": "cozeevo F1", "password": "cozeevo@f1"},
            {"ssid": "cozeevo F2", "password": "cozeevo@f2"},
            {"ssid": "cozeevo F3", "password": "cozeevo@f3"},
            {"ssid": "cozeevo F4", "password": "cozeevo@f4"},
        ],
        "5": [
            {"ssid": "cozeevo FI1", "password": "cozeevo@fi1"},
            {"ssid": "cozeevo FI2", "password": "cozeevo@fi2"},
            {"ssid": "cozeevo FI3", "password": "cozeevo@fi3"},
            {"ssid": "cozeevo FI4", "password": "cozeevo@fi4"},
        ],
        "6": [
            {"ssid": "cozeevo S1", "password": "cozeevo@s1"},
            {"ssid": "cozeevo S2", "password": "cozeevo@s2"},
            {"ssid": "cozeevo S3", "password": "cozeevo@s3"},
            {"ssid": "cozeevo S4", "password": "cozeevo@s4"},
        ],
        "top": [
            {"ssid": "cozeevo TOP", "password": "cozeevo@top"},
        ],
        "ws": [
            {"ssid": "cozeevo WS",  "password": "cozeevo@ws"},
            {"ssid": "cozeevo WS1", "password": "cozeevo@ws1"},
        ],
        "gym": [
            {"ssid": "cozeevo B", "password": "cozeevo@b"},
        ],
    },
    "hulk": {
        "G": [
            {"ssid": "Cozeehulk G1", "password": "cozeehulk@g1"},
            {"ssid": "Cozeehulk G2", "password": "cozeehulk@g2"},
            {"ssid": "Cozeehulk G3", "password": "cozeehulk@g3"},
            {"ssid": "Cozeehulk G4", "password": "cozeehulk@g4"},
        ],
        "1": [
            {"ssid": "Cozeehulk F1", "password": "cozeehulk@f1"},
            {"ssid": "Cozeehulk F2", "password": "cozeehulk@f2"},
            {"ssid": "Cozeehulk F3", "password": "cozeehulk@f3"},
            {"ssid": "Cozeehulk F4", "password": "cozeehulk@f4"},
        ],
        "2": [
            {"ssid": "Cozeehulk S1", "password": "cozeehulk@s1"},
            {"ssid": "Cozeehulk S2", "password": "cozeehulk@s2"},
            {"ssid": "Cozeehulk S3", "password": "cozeehulk@s3"},
            {"ssid": "Cozeehulk S4", "password": "cozeehulk@s4"},
        ],
        "3": [
            {"ssid": "Cozeehulk T1", "password": "cozeehulk@t1"},
            {"ssid": "Cozeehulk T2", "password": "cozeehulk@t2"},
            {"ssid": "Cozeehulk T3", "password": "cozeehulk@t3"},
            {"ssid": "Cozeehulk T4", "password": "cozeehulk@t4"},
        ],
        "4": [
            {"ssid": "Cozeehulk F1", "password": "cozeehulk@f1"},
            {"ssid": "Cozeehulk F2", "password": "cozeehulk@f2"},
            {"ssid": "Cozeehulk F3", "password": "cozeehulk@f3"},
            {"ssid": "Cozeehulk F4", "password": "cozeehulk@f4"},
        ],
        "5": [
            {"ssid": "cozeehulk FI1", "password": "cozeehulk@fi1"},
            {"ssid": "cozeehulk FI2", "password": "cozeehulk@fi2"},
            {"ssid": "cozeehulk FI3", "password": "cozeehulk@fi3"},
            {"ssid": "cozeehulk FI4", "password": "cozeehulk@fi4"},
        ],
        "6": [
            {"ssid": "cozeehulk S1", "password": "cozeehulk@s1"},
            {"ssid": "cozeehulk S2", "password": "cozeehulk@s2"},
            {"ssid": "cozeehulk S3", "password": "cozeehulk@s3"},
            {"ssid": "cozeehulk S4", "password": "cozeehulk@s4"},
        ],
    },
}

# Floor label for display
FLOOR_LABELS = {
    "G": "Ground Floor",
    "1": "1st Floor",
    "2": "2nd Floor",
    "3": "3rd Floor",
    "4": "4th Floor",
    "5": "5th Floor",
    "6": "6th Floor",
    "top": "Dining Area (TOP)",
    "ws": "Work Area (WS)",
    "gym": "Gym",
}


async def seed():
    async with get_async_session() as session:
        prop = await session.scalar(select(Property).limit(1))
        if not prop:
            print("ERROR: No property found in DB. Run migrate_all first.")
            return

        prop.wifi_floor_map = WIFI_DATA
        flag_modified(prop, "wifi_floor_map")
        await session.commit()
        print(f"WiFi data seeded for property: {prop.name or prop.id}")
        print(f"  Thor block: {len(WIFI_DATA['thor'])} zones")
        print(f"  Hulk block: {len(WIFI_DATA['hulk'])} zones")


if __name__ == "__main__":
    asyncio.run(seed())
