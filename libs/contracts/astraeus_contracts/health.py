"""Health and version DTOs returned by every service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HealthStatus = Literal["ok", "degraded", "unhealthy"]


class HealthResponse(BaseModel):
    """Response model for ``/healthz`` (liveness)."""

    model_config = ConfigDict(extra="forbid")

    status: HealthStatus = "ok"
    service: str = Field(..., description="Service name, e.g. ``api``.")
    version: str = Field(..., description="Service version (semver).")


class ReadinessCheck(BaseModel):
    """A single dependency check result included in the ``/readyz`` response."""

    model_config = ConfigDict(extra="forbid")

    name: str
    healthy: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """Response model for ``/readyz`` (readiness)."""

    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    service: str
    checks: list[ReadinessCheck]


class VersionResponse(BaseModel):
    """Response model for ``/version``."""

    model_config = ConfigDict(extra="forbid")

    service: str
    version: str
    git_sha: str | None = None
    build_time: datetime | None = None
