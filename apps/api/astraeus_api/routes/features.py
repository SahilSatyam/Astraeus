"""Feature store API routes.

Endpoints:
- GET  /features          — list registered features (filterable by group, owner)
- GET  /features/{name}   — get feature definition details
- POST /features/register — register a new feature definition
- GET  /features/{name}/runs — list materialization runs for a feature
- POST /features/{name}/backfill — trigger a backfill
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated

from astraeus_domain.exceptions import NotFoundError
from astraeus_features.models import FeatureRegistry, MaterializationRun
from astraeus_features.registry import get_definition, list_features, register
from astraeus_features.dsl import FeatureDefinition
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from astraeus_api.deps import get_db_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/features", tags=["features"])


# --- Request/Response schemas ---


class FeatureListItem(BaseModel):
    name: str
    group: str
    entity: str
    dtype: str
    description: str | None = None
    owner: str | None = None
    materialization: str
    definition_hash: str
    table_name: str
    registered_at: str
    updated_at: str


class FeatureDetail(BaseModel):
    name: str
    group: str
    entity: str
    dtype: str
    description: str | None = None
    dependencies: dict[str, object] | None = None
    transform_sql: str | None = None
    definition_hash: str
    materialization: str
    freshness_sla_seconds: int | None = None
    knowledge_lag_seconds: int
    owner: str | None = None
    tags: dict[str, object] | None = None
    table_name: str
    code_commit: str | None = None
    registered_at: str
    updated_at: str


class RegisterFeatureRequest(BaseModel):
    name: str = Field(..., description="Unique feature name", max_length=128)
    group: str = Field(..., description="Feature group", max_length=64)
    transform_sql: str = Field(..., description="SQL transform producing (symbol, event_ts, knowledge_ts, value, value_version)")
    entity: str = Field(default="symbol", description="Entity type: symbol, universe, macro")
    dtype: str = Field(default="numeric", description="Value data type")
    description: str = Field(default="", description="Human-readable description")
    dependencies: list[str] = Field(default_factory=list, description="Upstream table dependencies")
    materialization: str = Field(default="incremental", description="incremental, full, or on_demand")
    freshness_sla_seconds: int | None = Field(default=None, description="Max staleness in seconds")
    knowledge_lag_seconds: int = Field(default=0, description="Knowledge lag in seconds")
    owner: str = Field(default="", description="Owner team or person")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    code_commit: str | None = Field(default=None, description="Git commit SHA")


class RegisterFeatureResponse(BaseModel):
    name: str
    group: str
    definition_hash: str
    table_name: str
    status: str


class MaterializationRunResponse(BaseModel):
    id: str
    feature_name: str
    definition_hash: str
    start_date: str
    end_date: str
    status: str
    rows_written: int
    run_hash: str | None = None
    started_at: str
    completed_at: str | None = None
    error: str | None = None


class BackfillRequest(BaseModel):
    start: date = Field(..., description="Start date (inclusive)")
    end: date = Field(..., description="End date (inclusive)")
    universe_id: str | None = Field(default=None, description="Universe filter")
    chunk_size: int = Field(default=30, ge=1, le=365, description="Days per chunk")


class BackfillResponse(BaseModel):
    feature_name: str
    start: str
    end: str
    total_chunks: int
    status: str


# --- Endpoints ---


@router.get("", response_model=list[FeatureListItem], summary="List registered features")
async def list_features_route(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    group: str | None = Query(default=None, description="Filter by feature group"),
    owner: str | None = Query(default=None, description="Filter by owner"),
) -> list[FeatureListItem]:
    """List all registered features, optionally filtered by group or owner."""
    features = await list_features(session, group=group, owner=owner)

    return [
        FeatureListItem(
            name=f.name,
            group=f.group,
            entity=f.entity,
            dtype=f.dtype,
            description=f.description,
            owner=f.owner,
            materialization=f.materialization,
            definition_hash=f.definition_hash,
            table_name=f.table_name,
            registered_at=f.registered_at.isoformat(),
            updated_at=f.updated_at.isoformat(),
        )
        for f in features
    ]


@router.get("/{name}", response_model=FeatureDetail, summary="Get feature details")
async def get_feature_route(
    name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeatureDetail:
    """Get full details of a registered feature definition."""
    feature = await get_definition(session, name)
    if feature is None:
        raise NotFoundError(
            f"Feature {name!r} not found",
            code="astraeus.features.not_found",
        )

    return FeatureDetail(
        name=feature.name,
        group=feature.group,
        entity=feature.entity,
        dtype=feature.dtype,
        description=feature.description,
        dependencies=feature.dependencies,
        transform_sql=feature.transform_sql,
        definition_hash=feature.definition_hash,
        materialization=feature.materialization,
        freshness_sla_seconds=feature.freshness_sla_seconds,
        knowledge_lag_seconds=feature.knowledge_lag_seconds,
        owner=feature.owner,
        tags=feature.tags,
        table_name=feature.table_name,
        code_commit=feature.code_commit,
        registered_at=feature.registered_at.isoformat(),
        updated_at=feature.updated_at.isoformat(),
    )


@router.post("/register", response_model=RegisterFeatureResponse, summary="Register a feature")
async def register_feature_route(
    request: RegisterFeatureRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegisterFeatureResponse:
    """Register a new feature definition (or update if hash changed)."""
    from datetime import timedelta

    feature_def = FeatureDefinition(
        name=request.name,
        group=request.group,
        transform=request.transform_sql,
        entity=request.entity,
        dtype=request.dtype,
        description=request.description,
        dependencies=request.dependencies,
        materialization=request.materialization,
        freshness_sla=timedelta(seconds=request.freshness_sla_seconds) if request.freshness_sla_seconds else None,
        knowledge_lag=timedelta(seconds=request.knowledge_lag_seconds),
        owner=request.owner,
        tags=request.tags,
    )

    row = await register(session, feature_def, code_commit=request.code_commit)

    return RegisterFeatureResponse(
        name=row.name,
        group=row.group,
        definition_hash=row.definition_hash,
        table_name=row.table_name,
        status="registered",
    )


@router.get(
    "/{name}/runs",
    response_model=list[MaterializationRunResponse],
    summary="List materialization runs",
)
async def list_runs_route(
    name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str | None = Query(default=None, description="Filter by status"),
    limit: int = Query(default=20, le=100),
) -> list[MaterializationRunResponse]:
    """List materialization runs for a feature, newest first."""
    query = select(MaterializationRun).where(MaterializationRun.feature_name == name)

    if status:
        query = query.where(MaterializationRun.status == status)

    query = query.order_by(MaterializationRun.started_at.desc()).limit(limit)
    result = await session.execute(query)
    runs = result.scalars().all()

    return [
        MaterializationRunResponse(
            id=str(run.id),
            feature_name=run.feature_name,
            definition_hash=run.definition_hash,
            start_date=run.start_date.isoformat(),
            end_date=run.end_date.isoformat(),
            status=run.status,
            rows_written=run.rows_written,
            run_hash=run.run_hash,
            started_at=run.started_at.isoformat(),
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            error=run.error,
        )
        for run in runs
    ]


@router.post(
    "/{name}/backfill",
    response_model=BackfillResponse,
    summary="Trigger a feature backfill",
)
async def trigger_backfill_route(
    name: str,
    request: BackfillRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BackfillResponse:
    """Trigger a backfill for the specified feature.

    If prefect is available, this submits a flow run. Otherwise, it
    executes the backfill directly using the backfill engine.
    """
    from datetime import timedelta

    from astraeus_features.backfill import backfill_feature

    # Verify feature exists
    feature_reg = await get_definition(session, name)
    if feature_reg is None:
        raise NotFoundError(
            f"Feature {name!r} not found",
            code="astraeus.features.not_found",
        )

    # Build FeatureDefinition from registry
    feature_def = FeatureDefinition(
        name=feature_reg.name,
        group=feature_reg.group,
        transform=feature_reg.transform_sql or "",
        entity=feature_reg.entity,
        dtype=feature_reg.dtype,
    )

    # Execute backfill directly
    run = await backfill_feature(
        session=session,
        feature_def=feature_def,
        start=request.start,
        end=request.end,
        universe_id=request.universe_id,
        chunk_size=timedelta(days=request.chunk_size),
    )

    chunks = len(
        list(
            range(
                0,
                (request.end - request.start).days + 1,
                request.chunk_size,
            )
        )
    )

    return BackfillResponse(
        feature_name=name,
        start=request.start.isoformat(),
        end=request.end.isoformat(),
        total_chunks=chunks,
        status=run.status,
    )
