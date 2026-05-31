"""FastAPI dependencies for authentication and authorization.

Drop-in replacements for the Phase 0 stub in apps/api/deps.py.
These validate JWT tokens from the Authorization header and enforce
role-based access control.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from astraeus_auth.config import AuthSettings
from astraeus_auth.models import Principal, Role
from astraeus_auth.tokens import TokenError, decode_token, token_to_principal

logger = structlog.get_logger()

# HTTP Bearer scheme — extracts token from Authorization: Bearer <token>
_bearer_scheme = HTTPBearer(auto_error=False)


def _get_auth_settings(request: Request) -> AuthSettings:
    """Get auth settings from app state, or create defaults."""
    settings = getattr(request.app.state, "auth_settings", None)
    if settings is None:
        settings = AuthSettings()
    return settings


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Principal:
    """Validate the JWT and return the authenticated Principal.

    This is the main auth dependency. Add it to any route that requires
    authentication:

        @router.get("/protected")
        async def protected(user: Annotated[Principal, Depends(get_current_user)]):
            ...

    Behavior:
    - If auth is disabled (dev mode): returns a dev principal
    - If the path is public (health, metrics): returns a dev principal
    - If no token is provided: returns 401
    - If token is invalid: returns 401
    - On success: returns the authenticated Principal
    """
    auth_settings = _get_auth_settings(request)

    # Check if auth is disabled (local dev)
    if not auth_settings.enabled:
        return Principal.from_role(subject="dev", role=Role.OPERATOR)

    # Check if path is public
    path = request.url.path
    for public_path in auth_settings.public_paths:
        if path.startswith(public_path):
            return Principal.from_role(subject="anonymous", role=Role.VIEWER)

    # Require token
    if credentials is None:
        logger.warning("auth.missing_token", path=path, method=request.method)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate token
    try:
        payload = decode_token(credentials.credentials, auth_settings)
        principal = token_to_principal(payload)
    except TokenError as e:
        logger.warning("auth.invalid_token", detail=e.detail, path=path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid credentials: {e.detail}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    logger.debug(
        "auth.authenticated",
        subject=principal.subject,
        role=principal.role.value,
        path=path,
    )
    return principal


def require_role(*roles: Role):
    """Dependency factory: require the user to have one of the specified roles.

    Usage:
        @router.post("/orders")
        async def submit_order(
            user: Annotated[Principal, Depends(require_role(Role.OPERATOR, Role.SERVICE))],
        ):
            ...
    """

    async def _check_role(
        user: Principal = Depends(get_current_user),
    ) -> Principal:
        if user.role not in roles:
            logger.warning(
                "auth.insufficient_role",
                subject=user.subject,
                role=user.role.value,
                required=", ".join(r.value for r in roles),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Insufficient permissions. Required role: "
                    f"{', '.join(r.value for r in roles)}"
                ),
            )
        return user

    return _check_role


def require_trading_permission(
    user: Principal = Depends(get_current_user),
) -> Principal:
    """Dependency: require trading permission (write:orders).

    Use on all OMS order endpoints.
    """
    if not user.can_trade():
        logger.warning(
            "auth.trading_denied",
            subject=user.subject,
            role=user.role.value,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trading permission required. Only operators can submit orders.",
        )
    return user


def require_kill_switch_permission(
    user: Principal = Depends(get_current_user),
) -> Principal:
    """Dependency: require kill-switch permission.

    Use on kill-switch arm/disarm endpoints.
    """
    if not user.can_arm_kill_switch():
        logger.warning(
            "auth.kill_switch_denied",
            subject=user.subject,
            role=user.role.value,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kill-switch permission required. Only operators can arm/disarm.",
        )
    return user
