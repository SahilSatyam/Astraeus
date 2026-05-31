"""JWT token creation and validation.

Handles both:
- User tokens (issued by NextAuth, validated here)
- Service tokens (issued here for service-to-service calls)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from jose import JWTError, jwt

from astraeus_auth.config import AuthSettings
from astraeus_auth.models import Principal, Role


class TokenError(Exception):
    """Raised when token validation fails."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def decode_token(token: str, settings: AuthSettings) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Validates:
    - Signature (using shared secret)
    - Expiration
    - Required claims (sub)

    Returns the decoded payload on success.
    Raises TokenError on any validation failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            # NextAuth tokens may not have aud/iss — be lenient
            options={
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except JWTError as e:
        raise TokenError(f"Invalid token: {e}") from e

    if "sub" not in payload and "name" not in payload:
        raise TokenError("Token missing subject claim")

    return cast("dict[str, Any]", payload)


def token_to_principal(payload: dict[str, Any]) -> Principal:
    """Convert a decoded JWT payload to a Principal.

    Handles both NextAuth tokens (which use 'name' and 'role') and
    service tokens (which use 'sub' and 'role').
    """
    # NextAuth puts user info in 'name', service tokens use 'sub'
    subject = payload.get("sub") or payload.get("name") or "unknown"
    role_str = payload.get("role", "viewer")

    try:
        role = Role(role_str)
    except ValueError:
        role = Role.VIEWER

    return Principal.from_role(subject=subject, role=role)


def create_service_token(
    service_name: str,
    settings: AuthSettings,
    *,
    expire_seconds: int | None = None,
) -> str:
    """Create a JWT for service-to-service authentication.

    Used by internal services (workers, recon, agents) to call the OMS
    or API with proper identity.
    """
    expire = expire_seconds or settings.service_token_expire_seconds
    now = datetime.now(UTC)

    payload = {
        "sub": service_name,
        "role": Role.SERVICE.value,
        "iat": now,
        "exp": now + timedelta(seconds=expire),
        "iss": settings.jwt_issuer,
        "type": "service",
    }

    return cast(
        "str",
        jwt.encode(
            payload,
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        ),
    )


def create_access_token(
    subject: str,
    role: Role,
    settings: AuthSettings,
    *,
    expire_seconds: int | None = None,
) -> str:
    """Create a user access token.

    Used by the auth endpoint to issue tokens after credential validation.
    """
    expire = expire_seconds or settings.access_token_expire_seconds
    now = datetime.now(UTC)

    payload = {
        "sub": subject,
        "role": role.value,
        "iat": now,
        "exp": now + timedelta(seconds=expire),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": "access",
    }

    return cast(
        "str",
        jwt.encode(
            payload,
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        ),
    )
