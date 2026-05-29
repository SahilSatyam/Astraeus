"""Async session helpers.

Services obtain a session via ``get_session(settings)`` (a context manager) and
expose it through their FastAPI dependency layer. The session is committed if
the block exits cleanly and rolled back on any exception.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from astraeus_db.engine import get_engine

if TYPE_CHECKING:
    from astraeus_config import DatabaseSettings


_sessionmakers: dict[str, async_sessionmaker[AsyncSession]] = {}


def get_sessionmaker(settings: DatabaseSettings) -> async_sessionmaker[AsyncSession]:
    """Return (or build) the sessionmaker for the engine of these settings."""
    dsn = settings.dsn
    sm = _sessionmakers.get(dsn)
    if sm is None:
        sm = async_sessionmaker(
            bind=get_engine(settings),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        _sessionmakers[dsn] = sm
    return sm


@asynccontextmanager
async def get_session(settings: DatabaseSettings) -> AsyncIterator[AsyncSession]:
    """Yield a session, committing on success and rolling back on error."""
    sm = get_sessionmaker(settings)
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
