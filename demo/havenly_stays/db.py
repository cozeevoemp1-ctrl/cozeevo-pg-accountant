"""
Async DB engine/session for the Havenly Stays demo — points at HAVENLY_DATABASE_URL,
a completely separate Supabase project from the Cozeevo production DB.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from demo.havenly_stays.models import Base

_engine = None
_session_factory = None


def _normalize(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def init_engine(database_url: Optional[str] = None, echo: bool = False):
    global _engine, _session_factory
    database_url = database_url or os.getenv("HAVENLY_DATABASE_URL")
    if not database_url:
        raise RuntimeError("HAVENLY_DATABASE_URL not set — see demo/havenly_stays/README.md")
    _engine = create_async_engine(_normalize(database_url), echo=echo, future=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


async def init_db(database_url: Optional[str] = None):
    """Create demo tables if they don't exist."""
    engine = init_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if _session_factory is None:
        init_engine()
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
