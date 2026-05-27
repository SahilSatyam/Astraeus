"""Async SQLAlchemy engine factory.

A single engine is created per service process. Use ``get_engine(settings)``
during startup; the function caches the engine keyed on the DSN so test
fixtures and ``create_app()`` factories converge on the same instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

if TYPE_CHECKING:
    from astraeus_config import DatabaseSettings


_engines: dict[str, AsyncEngine] = {}


def get_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Return (or build) the async engine for the given settings.

    Each unique DSN gets its own engine; tests can pass a per-test settings
    instance with a unique database name to avoid pool sharing.
    """
    dsn = settings.dsn
    engine = _engines.get(dsn)
    if engine is None:
        engine = create_async_engine(
            dsn,
            echo=settings.echo,
            pool_size=settings.pool_size,
            max_overflow=settings.pool_max_overflow,
            pool_timeout=settings.pool_timeout_seconds,
            pool_pre_ping=True,
        )
        _engines[dsn] = engine
    return engine


async def dispose_engines() -> None:
    """Dispose all cached engines. Call on shutdown."""
    for engine in list(_engines.values()):
        await engine.dispose()
    _engines.clear()
