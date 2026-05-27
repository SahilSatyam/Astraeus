"""Lifespan: configure observability, dispose engines on shutdown."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from astraeus_db import dispose_engines

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Service lifespan. No DB warmup in Phase 0; ``/readyz`` does the probing."""
    try:
        yield
    finally:
        await dispose_engines()
