"""OMS FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from astraeus_auth import AuthSettings
from astraeus_brokers.alpaca import AlpacaAdapter
from astraeus_config import Settings
from astraeus_db import get_engine
from fastapi import FastAPI

from astraeus_oms import dependencies
from astraeus_oms.kill_switch_routes import router as ks_router
from astraeus_oms.position_routes import router as pos_router
from astraeus_oms.recon_routes import router as recon_router
from astraeus_oms.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the OMS FastAPI application."""
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Initialize broker adapter
        broker = AlpacaAdapter(
            api_key=settings.alpaca_api_key,
            api_secret=settings.alpaca_api_secret,
            paper=True,  # Always paper for now
        )
        dependencies.configure(settings, broker)

        # Ensure engine is created
        get_engine(settings.db)

        yield

        # Cleanup
        await broker.close()

    app = FastAPI(
        title="Astraeus OMS",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.auth_settings = AuthSettings()

    app.include_router(router)
    app.include_router(ks_router)
    app.include_router(pos_router)
    app.include_router(recon_router)

    return app
