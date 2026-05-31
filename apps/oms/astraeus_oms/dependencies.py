"""FastAPI dependency injection for the OMS service."""

from __future__ import annotations

from collections.abc import AsyncIterator

from astraeus_brokers.base import BrokerAdapter
from astraeus_config import Settings

# Module-level state (set during app startup)
_settings: Settings | None = None
_broker: BrokerAdapter | None = None


def configure(settings: Settings, broker: BrokerAdapter) -> None:
    """Configure module-level dependencies. Called during app startup."""
    global _settings, _broker
    _settings = settings
    _broker = broker


async def get_session() -> AsyncIterator:
    """Yield an async DB session."""
    from astraeus_db import get_sessionmaker

    assert _settings is not None
    sm = get_sessionmaker(_settings.db)
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_broker() -> BrokerAdapter:
    """Return the configured broker adapter."""
    assert _broker is not None
    return _broker
