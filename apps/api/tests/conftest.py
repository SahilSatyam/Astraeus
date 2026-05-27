"""Pytest fixtures for apps/api."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator  # noqa: TC003

import pytest
from astraeus_api import create_app
from astraeus_config import (
    AppSettings,
    DatabaseSettings,
    Environment,
    KafkaSettings,
    ObservabilitySettings,
    RedisSettings,
    Settings,
)
from fastapi import FastAPI  # noqa: TC002
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr


@pytest.fixture
def settings() -> Settings:
    """Test settings: in-memory friendly, no real connections."""
    return Settings(
        env=Environment.LOCAL,
        app=AppSettings(name="api", version="0.0.0-test"),
        db=DatabaseSettings(
            host="localhost",
            port=5432,
            user="test",
            password=SecretStr("test"),
            name="astraeus_test",
        ),
        redis=RedisSettings(),
        kafka=KafkaSettings(),
        observability=ObservabilitySettings(log_format="console", log_level="WARNING"),
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    """Build a fresh FastAPI app for each test."""
    yield create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
