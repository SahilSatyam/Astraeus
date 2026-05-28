"""Ingestion service — orchestrates adapter → DB → outbox → lineage.

The ingestion service is the core of Phase 1. It:
1. Calls an adapter to fetch bars
2. Computes deterministic payload hashes (idempotency keys)
3. Writes bars to market_bars_raw in the same transaction as outbox entries
4. Records lineage for every row written
5. Skips duplicates (same payload_hash = same data, no re-write)
6. Routes failures to the DLQ for manual inspection
7. Archives raw responses to MinIO for full reproducibility
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from astraeus_marketdata.adapters.base import AdapterResult, BaseAdapter, compute_payload_hash
from astraeus_marketdata.dlq import DLQEntry, send_to_dlq
from astraeus_marketdata.models import DataLineage, MarketBarRaw, Outbox

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from astraeus_marketdata.archival import MinIOArchiver

logger = structlog.get_logger("astraeus.marketdata.ingestion")


class IngestionRun:
    """Tracks a single ingestion run with counters and metadata."""

    def __init__(self, source: str, symbols: list[str], start: date, end: date) -> None:
        self.run_id = uuid.uuid4()
        self.source = source
        self.symbols = symbols
        self.start = start
        self.end = end
        self.started_at = datetime.now(tz=UTC)
        self.completed_at: datetime | None = None
        self.rows_fetched = 0
        self.rows_written = 0
        self.rows_skipped = 0
        self.errors: list[str] = []

    @property
    def status(self) -> str:
        if self.errors:
            return "failed"
        if self.completed_at:
            return "completed"
        return "running"

    def to_dict(self) -> dict:
        return {
            "run_id": str(self.run_id),
            "source": self.source,
            "symbols_count": len(self.symbols),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "rows_fetched": self.rows_fetched,
            "rows_written": self.rows_written,
            "rows_skipped": self.rows_skipped,
            "errors": self.errors,
        }


async def run_ingestion(
    adapter: BaseAdapter,
    session: AsyncSession,
    symbols: list[str],
    start: date,
    end: date,
    resolution: str = "1d",
    topic: str = "md.equity.daily.v1",
    archiver: MinIOArchiver | None = None,
) -> IngestionRun:
    """Execute a full ingestion run: fetch → dedupe → write → outbox → lineage.

    This is the main entry point for backfill operations.

    Args:
        adapter: Data source adapter to use.
        session: Database session (caller manages transaction).
        symbols: List of ticker symbols to fetch.
        start: Start date (inclusive).
        end: End date (inclusive).
        resolution: Bar resolution (1d, 1h, 1m).
        topic: Redpanda topic for outbox events.
        archiver: Optional MinIO archiver for raw response storage.
    """
    run = IngestionRun(
        source=adapter.source_name,
        symbols=symbols,
        start=start,
        end=end,
    )

    logger.info(
        "ingestion_run_start",
        run_id=str(run.run_id),
        source=adapter.source_name,
        symbols_count=len(symbols),
        start=str(start),
        end=str(end),
    )

    try:
        results = await adapter.fetch_bars(symbols, start, end, resolution)

        for result in results:
            run.rows_fetched += len(result.bars)

            # Archive raw response to MinIO
            if archiver and result.raw_response:
                try:
                    primary_symbol = (
                        result.symbols_requested[0] if result.symbols_requested else "batch"
                    )
                    uri = await archiver.archive_response(
                        raw_response=result.raw_response,
                        source=result.source,
                        run_id=run.run_id,
                        symbol=primary_symbol,
                        metadata={"resolution": resolution},
                    )
                    # Store URI for lineage records
                    result._archive_uri = uri  # type: ignore[attr-defined]
                except Exception as archive_exc:
                    # Archival failure is non-fatal — log and continue
                    logger.warning(
                        "archival_failed",
                        run_id=str(run.run_id),
                        error=str(archive_exc),
                    )

            await _persist_result(session, result, run, topic)

        run.completed_at = datetime.now(tz=UTC)

    except Exception as exc:
        run.errors.append(f"{type(exc).__name__}: {exc}")
        logger.error(
            "ingestion_run_error",
            run_id=str(run.run_id),
            error=str(exc),
        )
        raise

    logger.info(
        "ingestion_run_complete",
        run_id=str(run.run_id),
        rows_fetched=run.rows_fetched,
        rows_written=run.rows_written,
        rows_skipped=run.rows_skipped,
    )

    return run


async def _persist_result(
    session: AsyncSession,
    result: AdapterResult,
    run: IngestionRun,
    topic: str,
) -> None:
    """Persist bars from a single adapter result with deduplication."""
    archive_uri = getattr(result, "_archive_uri", None)

    for bar in result.bars:
        try:
            payload_hash = compute_payload_hash(bar, result.source)

            # Check for existing row (idempotency)
            existing = await session.execute(
                select(MarketBarRaw.symbol).where(
                    MarketBarRaw.symbol == bar.symbol,
                    MarketBarRaw.ts == bar.ts,
                    MarketBarRaw.resolution == bar.resolution,
                    MarketBarRaw.source == result.source,
                )
            )
            if existing.scalar_one_or_none() is not None:
                run.rows_skipped += 1
                continue

            # Insert bar
            bar_row = MarketBarRaw(
                symbol=bar.symbol,
                ts=bar.ts,
                resolution=bar.resolution,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                vwap=bar.vwap,
                trades=bar.trades,
                source=result.source,
                schema_version=1,
                ingest_run_id=run.run_id,
                payload_hash=payload_hash,
            )
            session.add(bar_row)

            # Outbox entry (same transaction)
            outbox_payload = json.dumps(
                {
                    "symbol": bar.symbol,
                    "ts": bar.ts.isoformat(),
                    "resolution": bar.resolution,
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": bar.volume,
                    "source": result.source,
                    "run_id": str(run.run_id),
                }
            ).encode()

            outbox_row = Outbox(
                topic=topic,
                key=bar.symbol.encode(),
                payload=outbox_payload,
                headers={"source": result.source, "run_id": str(run.run_id)},
            )
            session.add(outbox_row)

            # Lineage entry (same transaction)
            lineage_row = DataLineage(
                target_table="market_bars_raw",
                target_pk={
                    "symbol": bar.symbol,
                    "ts": bar.ts.isoformat(),
                    "resolution": bar.resolution,
                    "source": result.source,
                },
                source=result.source,
                source_endpoint=result.endpoint,
                source_response_hash=result.response_hash,
                source_response_uri=archive_uri,
                schema_version=1,
                ingest_run_id=run.run_id,
            )
            session.add(lineage_row)

            run.rows_written += 1

        except Exception as exc:
            # Route failed bar to DLQ instead of failing the entire run
            logger.warning(
                "bar_persist_failed",
                symbol=bar.symbol,
                ts=str(bar.ts),
                error=str(exc),
            )
            dlq_entry = DLQEntry(
                original_topic=topic,
                original_key=bar.symbol,
                payload={
                    "symbol": bar.symbol,
                    "ts": bar.ts.isoformat(),
                    "resolution": bar.resolution,
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": bar.volume,
                    "source": result.source,
                },
                error_type=type(exc).__name__,
                error_message=str(exc),
                source=result.source,
                run_id=run.run_id,
            )
            await send_to_dlq(session, dlq_entry)

    # Flush within the session (caller commits the transaction)
    await session.flush()
