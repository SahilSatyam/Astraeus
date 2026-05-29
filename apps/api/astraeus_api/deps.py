"""FastAPI dependency factories.

Two seams that downstream phases will extend:

- :func:`get_db_session` yields an :class:`AsyncSession` for the request.
- :func:`get_current_user` is a Phase 0 stub that returns a ``Principal`` with a
  fixed dev identity. Phase 10 will wire real auth (OIDC/JWT). Every Phase 1+
  route should already declare ``Depends(get_current_user)`` so the migration
  is a one-line change here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from astraeus_config import Settings
from astraeus_db import get_session
from fastapi import Depends, Request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated principal. Phase 0 always returns the dev identity."""

    subject: str
    roles: tuple[str, ...]


def get_settings(request: Request) -> Settings:
    """Pull the per-app Settings instance off ``app.state``."""
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_db_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AsyncSession]:
    async with get_session(settings.db) as session:
        yield session


def get_current_user(_request: Request) -> Principal:
    """Phase 0 auth stub. Returns a fixed dev principal.

    Replaced in Phase 10 by the OIDC/JWT verifier. Routes should already
    declare ``user: Annotated[Principal, Depends(get_current_user)]`` so no
    route signature changes when real auth lands.
    """
    return Principal(subject="dev", roles=("operator",))
