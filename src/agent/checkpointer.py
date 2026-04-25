"""
Checkpointer factory.
Production: AsyncPostgresSaver with psycopg3 pool (Supabase PostgreSQL).
Tests: MemorySaver (in-memory, no DB required).
"""
from __future__ import annotations

import os

from langgraph.checkpoint.memory import MemorySaver


def make_memory_checkpointer() -> MemorySaver:
    """For tests — no DB required."""
    return MemorySaver()


async def make_postgres_checkpointer():
    """
    For production (FastAPI lifespan startup).
    Requires DATABASE_URL_PSYCOPG in environment.
    Returns (checkpointer, pool) — caller must hold pool to close on shutdown.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    db_url = os.environ["DATABASE_URL_PSYCOPG"]
    pool = AsyncConnectionPool(db_url, open=False, max_size=5)
    await pool.open()
    cp = AsyncPostgresSaver(pool)
    await cp.setup()    # creates langgraph_checkpoints table if not exists
    return cp, pool
