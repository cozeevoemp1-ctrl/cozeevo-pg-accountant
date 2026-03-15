"""
migrate_wifi.py — Add WiFi columns to properties table.
Idempotent: safe to run multiple times.

Run:
    python -m src.database.migrate_wifi
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_DDL = """
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS wifi_ssid       TEXT,
    ADD COLUMN IF NOT EXISTS wifi_password   TEXT,
    ADD COLUMN IF NOT EXISTS wifi_floor_map  JSONB DEFAULT '{}';
"""


async def run():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set in environment")
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(_DDL))
    await engine.dispose()
    print("OK: WiFi columns added to properties table (idempotent - safe to re-run).")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(run())
