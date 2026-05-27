"""Routes registered in :func:`astraeus_api.app.create_app`."""

from astraeus_api.routes.health import router as health_router

__all__ = ["health_router"]
