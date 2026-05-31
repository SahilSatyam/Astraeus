"""FastAPI dependency factories.

Authentication is handled by the shared ``astraeus_auth`` library.
The ``get_current_user`` dependency validates JWT tokens from the
Authorization header and returns a ``Principal`` with verified identity
and role-based permissions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from astraeus_auth import Principal, get_current_user, require_role
from astraeus_auth.dependencies import require_kill_switch_permission, require_trading_permission
from astraeus_auth.models import Role
from astraeus_config import Settings
from astraeus_db import get_session
from fastapi import Depends, Request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


def get_settings(request: Request) -> Settings:
    """Pull the per-app Settings instance off ``app.state``."""
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_db_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AsyncSession]:
    async with get_session(settings.db) as session:
        yield session


# Re-export auth dependencies for convenience.
# Routes import from here to keep a single import path.
__all__ = [
    "Principal",
    "Role",
    "get_current_user",
    "get_db_session",
    "get_settings",
    "require_kill_switch_permission",
    "require_role",
    "require_trading_permission",
]
