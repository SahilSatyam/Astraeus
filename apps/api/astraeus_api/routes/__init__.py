"""Routes registered in :func:`astraeus_api.app.create_app`."""

from astraeus_api.routes.features import router as features_router
from astraeus_api.routes.health import router as health_router
from astraeus_api.routes.marketdata import router as marketdata_router

__all__ = ["features_router", "health_router", "marketdata_router"]
