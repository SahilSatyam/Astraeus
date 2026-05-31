"""Auth configuration — JWT settings."""

from __future__ import annotations

import os

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default JWT secret used in local development. Reaching staging/prod with this
# value is a critical security failure — `_reject_default_secret_outside_local`
# fails the process at startup if it ever happens.
_DEFAULT_JWT_SECRET = "change-me-in-production"  # noqa: S105 — known dev sentinel
_INSECURE_ENVS = frozenset({"staging", "prod"})


class AuthSettings(BaseSettings):
    """Authentication configuration.

    In scope mode (single-user), the JWT_SECRET is shared between the
    Next.js frontend (NEXTAUTH_SECRET) and the backend services.

    In production multi-user mode, this would point to an OIDC issuer
    and validate tokens against the issuer's JWKS endpoint.
    """

    model_config = SettingsConfigDict(
        env_prefix="ASTRAEUS_AUTH_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # JWT signing secret — MUST match NEXTAUTH_SECRET in the web app
    jwt_secret: SecretStr = SecretStr("change-me-in-production")

    # JWT algorithm
    jwt_algorithm: str = "HS256"

    # Token issuer (for validation)
    jwt_issuer: str = "astraeus"

    # Token audience
    jwt_audience: str = "astraeus-api"

    # Access token expiry in seconds (1 hour)
    access_token_expire_seconds: int = 3600

    # Service token expiry in seconds (24 hours) — for internal service-to-service
    service_token_expire_seconds: int = 86400

    # Whether to enforce auth (disable for local dev if needed)
    enabled: bool = Field(
        default=True,
        description="Set to false to disable auth enforcement (dev only)",
    )

    # Paths that skip authentication (health checks, metrics)
    public_paths: list[str] = Field(
        default_factory=lambda: [
            "/health",
            "/healthz",
            "/readyz",
            "/metrics",
            "/health/live",
            "/health/ready",
            "/docs",
            "/openapi.json",
        ]
    )

    @model_validator(mode="after")
    def _reject_default_secret_outside_local(self) -> AuthSettings:
        """Refuse to start with the dev JWT secret in staging/prod.

        ``ASTRAEUS_ENV`` is owned by ``astraeus_config.Settings`` but
        AuthSettings is constructed independently in some services, so we read
        the env var directly here to avoid an import cycle.
        """
        env = os.environ.get("ASTRAEUS_ENV", "local").strip().lower()
        if env not in _INSECURE_ENVS:
            return self
        if self.jwt_secret.get_secret_value() == _DEFAULT_JWT_SECRET:
            msg = (
                f"Refusing to start in env={env!r} with the default development "
                "JWT secret. Set ASTRAEUS_AUTH_JWT_SECRET to a strong value."
            )
            raise ValueError(msg)
        return self
