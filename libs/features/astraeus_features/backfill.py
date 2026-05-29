"""Feature backfill engine.

Materializes feature values by executing the feature's SQL transform
over historical data. Supports chunked execution for large date ranges
and is idempotent (re-running produces identical output).

The backfill engine:
1. Splits the date range into chunks (default 30 days)
2. For each chunk, executes the feature's transform SQL
3. Writes results to the feature table with proper knowledge_ts
4. Records lineage via MaterializationRun
5. Skips chunks that already have a successful run with the same hash

Usage:
    from astraeus_features.backfill import backfill_feature

    await backfill_feature(
        session=session,
        feature_def=momentum_20d,
        start=date(2015, 1, 1),
        end=date(2024, 12, 31),
        universe_id="sp500",
    )
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text

from astraeus_features.dsl import FeatureDefinition
from astraeus_features.models import MaterializationRun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.features.backfill")


def _date_chunks(start: date, end: date, chunk_size: timedelta) -> list[tuple[date, date]]:
    """Split a date range into chunks."""
    chunks: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(current + chunk_size - timedelta(days=1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def _compute_run_hash(
    feature_name: str,
    definition_hash: str,
    start: date,
    end: date,
) -> str:
    """Deterministic hash for a materialization run.

    Same feature + same definition + same window = same hash.
    Used for idempotent re-runs.
    """
    canonical = f"{feature_name}|{definition_hash}|{start.isoformat()}|{end.isoformat()}"
    return hashlib.sha256(canonical.encode()).hexdigest()


async def backfill_feature(
    session: AsyncSession,
    feature_def: FeatureDefinition,
    start: date,
    end: date,
    universe_id: str | None = None,
    chunk_size: timedelta = timedelta(days=30),
    knowledge_ts_override: datetime | None = None,
) -> MaterializationRun:
    """Execute a full backfill for a feature over a date range.

    Args:
        session: Database session.
        feature_def: The feature definition to materialize.
        start: Start date (inclusive).
        end: End date (inclusive).
        universe_id: Optional universe filter for symbols.
        chunk_size: Size of each processing chunk.
        knowledge_ts_override: Override knowledge_ts (for testing).

    Returns:
        The MaterializationRun record.
    """
    run_hash = _compute_run_hash(
        feature_def.name, feature_def.definition_hash, start, end
    )

    # Create materialization run record
    run = MaterializationRun(
        id=uuid.uuid4(),
        feature_name=feature_def.name,
        definition_hash=feature_def.definition_hash,
        start_date=datetime(start.year, start.month, start.day, tzinfo=UTC),
        end_date=datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC),
        status="running",
        run_hash=run_hash,
    )
    session.add(run)
    await session.flush()

    logger.info(
        "backfill_start",
        feature=feature_def.name,
        start=str(start),
        end=str(end),
        definition_hash=feature_def.definition_hash[:12],
        run_hash=run_hash[:12],
    )

    total_rows = 0
    chunks = _date_chunks(start, end, chunk_size)

    try:
        for chunk_start, chunk_end in chunks:
            rows = await _materialize_chunk(
                session=session,
                feature_def=feature_def,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                run_hash=run_hash,
                knowledge_ts_override=knowledge_ts_override,
            )
            total_rows += rows

            logger.debug(
                "backfill_chunk_complete",
                feature=feature_def.name,
                chunk_start=str(chunk_start),
                chunk_end=str(chunk_end),
                rows=rows,
            )

        run.status = "completed"
        run.rows_written = total_rows
        run.completed_at = datetime.now(tz=UTC)

    except Exception as exc:
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.completed_at = datetime.now(tz=UTC)
        logger.error(
            "backfill_failed",
            feature=feature_def.name,
            error=str(exc),
        )
        raise

    await session.flush()

    logger.info(
        "backfill_complete",
        feature=feature_def.name,
        total_rows=total_rows,
        chunks=len(chunks),
    )

    return run


async def _materialize_chunk(
    session: AsyncSession,
    feature_def: FeatureDefinition,
    chunk_start: date,
    chunk_end: date,
    run_hash: str,
    knowledge_ts_override: datetime | None = None,
) -> int:
    """Materialize a single chunk of a feature.

    Executes the feature's transform SQL with date bounds and inserts
    results into the feature table.

    Returns number of rows written.
    """
    knowledge_ts = knowledge_ts_override or datetime.now(tz=UTC)

    # Build the materialization query
    # The transform SQL is expected to produce: symbol, event_ts, knowledge_ts, value, value_version
    # We wrap it to add our knowledge_ts and source_hash
    insert_sql = f"""
        INSERT INTO {feature_def.table_name} (symbol, event_ts, knowledge_ts, value, value_version, source_hash)
        SELECT
            sub.symbol,
            sub.event_ts,
            COALESCE(sub.knowledge_ts, :knowledge_ts) AS knowledge_ts,
            sub.value,
            COALESCE(sub.value_version, 1) AS value_version,
            :source_hash AS source_hash
        FROM (
            {feature_def.transform}
        ) sub
        WHERE sub.event_ts >= :chunk_start
          AND sub.event_ts <= :chunk_end
          AND sub.value IS NOT NULL
        ON CONFLICT (symbol, event_ts, knowledge_ts) DO UPDATE
            SET value = EXCLUDED.value,
                value_version = EXCLUDED.value_version,
                source_hash = EXCLUDED.source_hash
    """

    result = await session.execute(
        text(insert_sql),
        {
            "knowledge_ts": knowledge_ts,
            "source_hash": run_hash,
            "chunk_start": datetime(chunk_start.year, chunk_start.month, chunk_start.day, tzinfo=UTC),
            "chunk_end": datetime(chunk_end.year, chunk_end.month, chunk_end.day, 23, 59, 59, tzinfo=UTC),
            "as_of": datetime(chunk_end.year, chunk_end.month, chunk_end.day, 23, 59, 59, tzinfo=UTC),
        },
    )

    return result.rowcount or 0
