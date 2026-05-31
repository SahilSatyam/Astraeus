"""Auth configuration — JWT settings."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
