"""FastAPI factory and instrumentation wiring."""

from __future__ import annotations

from astraeus_auth import AuthSettings
from astraeus_config import Settings
from astraeus_observability import configure_logging, configure_tracing
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from astraeus_api.errors import register_exception_handlers
from astraeus_api.lifespan import lifespan
from astraeus_api.middleware import RequestContextMiddleware
from astraeus_api.rate_limit import RateLimitMiddleware
from astraeus_api.routes import (
    agents_router,
    altdata_router,
    features_router,
    health_router,
    hitl_router,
    marketdata_router,
    rag_router,
    recommender_router,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Tests call this with their own ``settings`` to keep instances isolated.
    """
    settings = settings or Settings()

    configure_logging(settings.observability, service=settings.app.name)
    configure_tracing(
        settings.observability,
        service_name=settings.app.name,
        service_version=settings.app.version,
        environment=settings.env.value,
    )

    app = FastAPI(
        title="Astraeus API",
        version=settings.app.version,
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )
    app.state.settings = settings
    app.state.auth_settings = AuthSettings()

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(marketdata_router)
    app.include_router(features_router)
    app.include_router(altdata_router)
    app.include_router(rag_router)
    app.include_router(agents_router)
    app.include_router(hitl_router)
    app.include_router(recommender_router)

    _instrument(app)
    return app


def _instrument(app: FastAPI) -> None:
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
    Instrumentator(
        excluded_handlers=["/healthz", "/readyz", "/metrics"],
    ).instrument(app).expose(app, include_in_schema=False, endpoint="/metrics")
