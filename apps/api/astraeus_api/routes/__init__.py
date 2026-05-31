"""Routes registered in :func:`astraeus_api.app.create_app`."""

from astraeus_api.routes.agents import router as agents_router
from astraeus_api.routes.altdata import router as altdata_router
from astraeus_api.routes.features import router as features_router
from astraeus_api.routes.health import router as health_router
from astraeus_api.routes.hitl import router as hitl_router
from astraeus_api.routes.marketdata import router as marketdata_router
from astraeus_api.routes.rag import router as rag_router
from astraeus_api.routes.recommender import router as recommender_router

__all__ = [
    "agents_router",
    "altdata_router",
    "features_router",
    "health_router",
    "hitl_router",
    "marketdata_router",
    "rag_router",
    "recommender_router",
]
