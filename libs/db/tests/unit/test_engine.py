from collections.abc import AsyncGenerator

import pytest
from astraeus_config import DatabaseSettings
from astraeus_db import dispose_engines, get_engine, get_sessionmaker
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


@pytest.fixture(autouse=True)
async def _cleanup() -> AsyncGenerator[None, None]:
    yield
    await dispose_engines()


@pytest.mark.unit
def test_get_engine_returns_async_engine() -> None:
    settings = DatabaseSettings(
        host="db",
        port=5432,
        user="u",
        password=SecretStr("p"),
        name="astraeus_test",
    )
    engine = get_engine(settings)
    assert isinstance(engine, AsyncEngine)


@pytest.mark.unit
def test_get_engine_caches_per_dsn() -> None:
    settings = DatabaseSettings(
        host="db",
        port=5432,
        user="u",
        password=SecretStr("p"),
        name="astraeus_cache",
    )
    e1 = get_engine(settings)
    e2 = get_engine(settings)
    assert e1 is e2


@pytest.mark.unit
def test_get_sessionmaker_returns_async_sessionmaker() -> None:
    settings = DatabaseSettings(
        host="db",
        port=5432,
        user="u",
        password=SecretStr("p"),
        name="astraeus_sm",
    )
    sm = get_sessionmaker(settings)
    assert isinstance(sm, async_sessionmaker)
