"""Prefect 2 flow for feature backfill.

Wraps the existing backfill_feature function in a Prefect flow with:
- Chunked task execution for parallelism and observability
- Resumability: skips chunks with existing successful run_hash
- Structured logging via structlog

Prefect is an optional dependency — this module gracefully degrades
if prefect is not installed.

Usage:
    from astraeus_features.flows import backfill_feature_flow

    # Run directly (requires prefect)
    await backfill_feature_flow(
        feature_name="momentum_20d",
        start="2020-01-01",
        end="2024-12-31",
        universe_id="sp500",
    )
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.features.flows")

# --- Optional Prefect imports ---
try:
    from prefect import flow, task
except ImportError:  # pragma: no cover
    # Graceful degradation: define no-op decorators if prefect is not installed
    from functools import wraps
    from typing import Any

    def flow(**kwargs: Any):  # type: ignore[no-redef]
        """No-op flow decorator when prefect is not installed."""
        def decorator(fn: Any) -> Any:
            @wraps(fn)
            async def wrapper(*args: Any, **kw: Any) -> Any:
                return await fn(*args, **kw)
            return wrapper
        return decorator

    def task(**kwargs: Any):  # type: ignore[no-redef]
        """No-op task decorator when prefect is not installed."""
        def decorator(fn: Any) -> Any:
            @wraps(fn)
            async def wrapper(*args: Any, **kw: Any) -> Any:
                return await fn(*args, **kw)
            return wrapper
        return decorator


def _date_chunks(start: date, end: date, chunk_size: int) -> list[tuple[date, date]]:
    """Split a date range into chunks of chunk_size days."""
    chunks: list[tuple[date, date]] = []
    current = start
    delta = timedelta(days=chunk_size)
    while current <= end:
        chunk_end = min(current + delta - timedelta(days=1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def _compute_chunk_hash(
    feature_name: str,
    definition_hash: str,
    chunk_start: date,
    chunk_end: date,
) -> str:
    """Deterministic hash for a single chunk run."""
    canonical = f"{feature_name}|{definition_hash}|{chunk_start.isoformat()}|{chunk_end.isoformat()}"
    return hashlib.sha256(canonical.encode()).hexdigest()


@task(name="materialize_chunk", retries=2, retry_delay_seconds=30)
async def materialize_chunk(
    feature_name: str,
    definition_hash: str,
    chunk_start: date,
    chunk_end: date,
    universe_id: str | None,
) -> dict[str, object]:
    """Materialize a single chunk of a feature backfill.

    This task is idempotent — if a successful run with the same hash
    already exists, it is skipped.
    """
    from astraeus_config import Settings
    from astraeus_db import get_session
    from astraeus_features.backfill import _compute_run_hash, _materialize_chunk
    from astraeus_features.models import MaterializationRun
    from astraeus_features.registry import get_definition

    from sqlalchemy import select

    settings = Settings()
    chunk_hash = _compute_chunk_hash(feature_name, definition_hash, chunk_start, chunk_end)

    async with get_session(settings.db) as session:
        # Check if this chunk already has a successful run
        existing = await session.execute(
            select(MaterializationRun).where(
                MaterializationRun.feature_name == feature_name,
                MaterializationRun.run_hash == chunk_hash,
                MaterializationRun.status == "completed",
            )
        )
        if existing.scalar_one_or_none() is not None:
            logger.info(
                "chunk_skipped",
                feature=feature_name,
                chunk_start=str(chunk_start),
                chunk_end=str(chunk_end),
                reason="existing_successful_run",
            )
            return {
                "status": "skipped",
                "chunk_start": str(chunk_start),
                "chunk_end": str(chunk_end),
                "rows": 0,
            }

        # Get feature definition from registry
        registry_entry = await get_definition(session, feature_name)
        if registry_entry is None:
            msg = f"Feature {feature_name!r} not found in registry"
            raise ValueError(msg)

        # Build a minimal FeatureDefinition for the chunk materialization
        from astraeus_features.dsl import FeatureDefinition

        feature_def = FeatureDefinition(
            name=registry_entry.name,
            group=registry_entry.group,
            transform=registry_entry.transform_sql or "",
            entity=registry_entry.entity,
            dtype=registry_entry.dtype,
        )

        # Materialize the chunk
        rows = await _materialize_chunk(
            session=session,
            feature_def=feature_def,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
            run_hash=chunk_hash,
        )

        await session.commit()

    logger.info(
        "chunk_complete",
        feature=feature_name,
        chunk_start=str(chunk_start),
        chunk_end=str(chunk_end),
        rows=rows,
    )

    return {
        "status": "completed",
        "chunk_start": str(chunk_start),
        "chunk_end": str(chunk_end),
        "rows": rows,
    }


@flow(name="backfill_feature")
async def backfill_feature_flow(
    feature_name: str,
    start: str,
    end: str,
    universe_id: str | None = None,
    chunk_size: int = 30,
) -> dict[str, object]:
    """Prefect flow that orchestrates a feature backfill.

    Splits the date range into chunks and submits each as a task.
    Resumable: chunks with existing successful runs are skipped.

    Args:
        feature_name: Name of the registered feature to backfill.
        start: Start date (ISO format, inclusive).
        end: End date (ISO format, inclusive).
        universe_id: Optional universe filter for symbols.
        chunk_size: Number of days per chunk.

    Returns:
        Summary dict with total rows and chunk statuses.
    """
    from astraeus_config import Settings
    from astraeus_db import get_session
    from astraeus_features.registry import get_definition

    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    logger.info(
        "flow_start",
        feature=feature_name,
        start=start,
        end=end,
        universe_id=universe_id,
        chunk_size=chunk_size,
    )

    # Resolve definition hash from registry
    settings = Settings()
    async with get_session(settings.db) as session:
        registry_entry = await get_definition(session, feature_name)
        if registry_entry is None:
            msg = f"Feature {feature_name!r} not found in registry"
            raise ValueError(msg)
        definition_hash = registry_entry.definition_hash

    chunks = _date_chunks(start_date, end_date, chunk_size)
    logger.info("flow_chunks_planned", total_chunks=len(chunks))

    results: list[dict[str, object]] = []
    total_rows = 0
    skipped = 0

    for chunk_start, chunk_end in chunks:
        result = await materialize_chunk(
            feature_name=feature_name,
            definition_hash=definition_hash,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
            universe_id=universe_id,
        )
        results.append(result)
        total_rows += result.get("rows", 0)  # type: ignore[arg-type]
        if result.get("status") == "skipped":
            skipped += 1

    logger.info(
        "flow_complete",
        feature=feature_name,
        total_chunks=len(chunks),
        skipped_chunks=skipped,
        total_rows=total_rows,
    )

    return {
        "feature_name": feature_name,
        "start": start,
        "end": end,
        "total_chunks": len(chunks),
        "skipped_chunks": skipped,
        "total_rows": total_rows,
        "status": "completed",
    }
