"""Health, readiness, version routes."""

from __future__ import annotations

from typing import Annotated

from astraeus_config import Settings  # noqa: TC002 (FastAPI needs at runtime)
from astraeus_contracts import (
    HealthResponse,
    ReadinessCheck,
    ReadinessResponse,
    VersionResponse,
)
from astraeus_domain import AstraeusError
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 (FastAPI needs at runtime)

from astraeus_api.deps import get_db_session, get_settings

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Liveness probe",
    responses={
        200: {
            "description": "Service is alive.",
            "content": {"application/json": {}},
        },
    },
)
async def healthz(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    return HealthResponse(service=settings.app.name, version=settings.app.version)


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={
        200: {"description": "All dependencies healthy."},
        503: {
            "description": "One or more dependencies unhealthy.",
            "content": {"application/problem+json": {}},
        },
    },
)
async def readyz(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReadinessResponse:
    checks: list[ReadinessCheck] = []
    db_ok = True
    db_detail: str | None = None
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # broad on purpose: probe must classify, not propagate
        db_ok = False
        db_detail = type(exc).__name__
    checks.append(ReadinessCheck(name="postgres", healthy=db_ok, detail=db_detail))

    if not db_ok:
        raise AstraeusError(
            "Dependency unavailable.",
            code="astraeus.api.dependency_unavailable",
            status=503,
            extra={"checks": [c.model_dump() for c in checks]},
        )

    return ReadinessResponse(
        status="ok",
        service=settings.app.name,
        checks=checks,
    )


@router.get("/version", response_model=VersionResponse, summary="Service version metadata")
async def version(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionResponse:
    return VersionResponse(
        service=settings.app.name,
        version=settings.app.version,
        git_sha=settings.app.git_sha,
    )
