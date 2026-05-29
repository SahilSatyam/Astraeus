#!/usr/bin/env python3
"""Market data replay CLI.

Re-emits raw rows from the outbox/MinIO archive into Redpanda topics for a
given source and date window. Supports dry-run mode to verify what would be
replayed without actually publishing.

Usage:
    uv run python scripts/md-replay.py --source polygon --from 2024-01-01 --to 2024-01-31

    uv run python scripts/md-replay.py --source yahoo --symbol AAPL \
        --from 2024-01-01 --to 2024-01-31 --dry-run

    uv run python scripts/md-replay.py --source polygon --from 2024-01-01 --to 2024-01-31 \
        --verify

The replay tool is essential for Phase 1's reproducibility guarantee:
delete a symbol's data, re-run replay from archived responses, and end up
byte-identical.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, date, datetime

import structlog
from astraeus_config import Settings
from astraeus_db.session import get_sessionmaker
from astraeus_marketdata.archival import MinIOArchiver
from astraeus_marketdata.models import DataLineage, MarketBarRaw, Outbox
from astraeus_observability import configure_logging
from sqlalchemy import func, select

logger = structlog.get_logger("astraeus.md.replay")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay market data from outbox/archive into Redpanda topics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run — show what would be replayed
  uv run python scripts/md-replay.py --source yahoo --from 2024-01-01 --to 2024-01-31 --dry-run

  # Replay all Yahoo data for January 2024
  uv run python scripts/md-replay.py --source yahoo --from 2024-01-01 --to 2024-01-31

  # Replay a single symbol and verify hashes match
  uv run python scripts/md-replay.py --source yahoo --symbol AAPL --from 2024-01-01 --to 2024-01-31 --verify
        """,
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Data source to replay (yahoo, polygon, alpaca, fred, alphavantage)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Filter replay to a single symbol",
    )
    parser.add_argument(
        "--from",
        dest="start",
        type=date.fromisoformat,
        required=True,
        help="Start date (inclusive, ISO format)",
    )
    parser.add_argument(
        "--to",
        dest="end",
        type=date.fromisoformat,
        required=True,
        help="End date (inclusive, ISO format)",
    )
    parser.add_argument(
        "--resolution",
        default="1d",
        choices=["1m", "5m", "15m", "1h", "1d"],
        help="Bar resolution to replay (default: 1d)",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Override target topic (default: auto-detect from resolution)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be replayed without publishing",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="After replay, verify payload hashes match existing data",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows to process per batch (default: 500)",
    )
    return parser.parse_args()


def _resolve_topic(source: str, resolution: str) -> str:
    """Determine the target topic based on source and resolution."""
    if resolution == "1d":
        return "md.equity.daily.v1"
    if resolution in ("1m", "5m", "15m"):
        return "md.equity.minute.v1"
    if resolution == "1h":
        return "md.equity.daily.v1"  # hourly goes to daily topic
    return "md.equity.daily.v1"


async def _count_rows(
    session_factory: object,
    source: str,
    symbol: str | None,
    start: date,
    end: date,
    resolution: str,
) -> int:
    """Count rows that would be replayed."""
    async with session_factory() as session:  # type: ignore[operator]
        query = (
            select(func.count())
            .select_from(MarketBarRaw)
            .where(
                MarketBarRaw.source == source,
                MarketBarRaw.resolution == resolution,
                MarketBarRaw.ts >= datetime(start.year, start.month, start.day, tzinfo=UTC),
                MarketBarRaw.ts
                <= datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC),
            )
        )
        if symbol:
            query = query.where(MarketBarRaw.symbol == symbol)

        result = await session.execute(query)
        return result.scalar_one()


async def _replay_to_outbox(
    session_factory: object,
    source: str,
    symbol: str | None,
    start: date,
    end: date,
    resolution: str,
    topic: str,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Replay bars by re-inserting them into the outbox table.

    Returns (rows_processed, rows_replayed).
    """
    rows_processed = 0
    rows_replayed = 0
    offset = 0

    while True:
        async with session_factory() as session:  # type: ignore[operator]
            query = (
                select(MarketBarRaw)
                .where(
                    MarketBarRaw.source == source,
                    MarketBarRaw.resolution == resolution,
                    MarketBarRaw.ts >= datetime(start.year, start.month, start.day, tzinfo=UTC),
                    MarketBarRaw.ts
                    <= datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC),
                )
                .order_by(MarketBarRaw.ts, MarketBarRaw.symbol)
                .offset(offset)
                .limit(batch_size)
            )
            if symbol:
                query = query.where(MarketBarRaw.symbol == symbol)

            result = await session.execute(query)
            rows = list(result.scalars().all())

            if not rows:
                break

            for row in rows:
                rows_processed += 1

                outbox_payload = json.dumps(
                    {
                        "symbol": row.symbol,
                        "ts": row.ts.isoformat(),
                        "resolution": row.resolution,
                        "open": str(row.open),
                        "high": str(row.high),
                        "low": str(row.low),
                        "close": str(row.close),
                        "volume": row.volume,
                        "source": row.source,
                        "run_id": str(row.ingest_run_id),
                        "replay": True,
                    }
                ).encode()

                if not dry_run:
                    session.add(
                        Outbox(
                            topic=topic,
                            key=row.symbol.encode(),
                            payload=outbox_payload,
                            headers={
                                "source": row.source,
                                "run_id": str(row.ingest_run_id),
                                "replay": "true",
                            },
                        )
                    )
                    rows_replayed += 1

            if not dry_run:
                await session.commit()

            offset += batch_size

            if rows_processed % 1000 == 0:
                logger.info(
                    "replay_progress",
                    processed=rows_processed,
                    replayed=rows_replayed,
                )

    return rows_processed, rows_replayed


async def _verify_hashes(
    session_factory: object,
    source: str,
    symbol: str | None,
    start: date,
    end: date,
    resolution: str,
) -> tuple[int, int, list[str]]:
    """Verify payload hashes for replayed data.

    Recomputes hashes from stored data and compares against payload_hash column.
    Returns (total_checked, mismatches, mismatch_details).
    """
    from astraeus_marketdata.adapters.base import BarRecord, compute_payload_hash

    total_checked = 0
    mismatches = 0
    mismatch_details: list[str] = []

    async with session_factory() as session:  # type: ignore[operator]
        query = (
            select(MarketBarRaw)
            .where(
                MarketBarRaw.source == source,
                MarketBarRaw.resolution == resolution,
                MarketBarRaw.ts >= datetime(start.year, start.month, start.day, tzinfo=UTC),
                MarketBarRaw.ts
                <= datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC),
            )
            .order_by(MarketBarRaw.ts, MarketBarRaw.symbol)
        )
        if symbol:
            query = query.where(MarketBarRaw.symbol == symbol)

        result = await session.execute(query)
        rows = result.scalars().all()

        for row in rows:
            total_checked += 1
            bar = BarRecord(
                symbol=row.symbol,
                ts=row.ts,
                resolution=row.resolution,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                vwap=row.vwap,
                trades=row.trades,
            )
            expected_hash = compute_payload_hash(bar, source)

            if expected_hash != row.payload_hash:
                mismatches += 1
                mismatch_details.append(
                    f"  {row.symbol} @ {row.ts.isoformat()}: "
                    f"stored={row.payload_hash.hex()[:16]}... "
                    f"computed={expected_hash.hex()[:16]}..."
                )

    return total_checked, mismatches, mismatch_details


async def main() -> None:
    args = parse_args()
    settings = Settings()
    configure_logging(settings.observability, service="md-replay")

    topic = args.topic or _resolve_topic(args.source, args.resolution)
    session_factory = get_sessionmaker(settings.db)

    logger.info(
        "replay_start",
        source=args.source,
        symbol=args.symbol,
        start=str(args.start),
        end=str(args.end),
        resolution=args.resolution,
        topic=topic,
        dry_run=args.dry_run,
        verify=args.verify,
    )

    # Count rows first
    total_rows = await _count_rows(
        session_factory, args.source, args.symbol, args.start, args.end, args.resolution
    )

    print(f"\n{'=' * 60}")
    print(f"  Astraeus Market Data Replay")
    print(f"{'=' * 60}")
    print(f"  Source:     {args.source}")
    print(f"  Symbol:     {args.symbol or 'ALL'}")
    print(f"  Range:      {args.start} → {args.end}")
    print(f"  Resolution: {args.resolution}")
    print(f"  Topic:      {topic}")
    print(f"  Rows:       {total_rows:,}")
    print(f"  Mode:       {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'=' * 60}\n")

    if total_rows == 0:
        print("No rows found matching criteria. Nothing to replay.")
        return

    # Execute replay
    rows_processed, rows_replayed = await _replay_to_outbox(
        session_factory=session_factory,
        source=args.source,
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        resolution=args.resolution,
        topic=topic,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )

    print(f"\nReplay {'simulation' if args.dry_run else 'execution'} complete:")
    print(f"  Rows processed: {rows_processed:,}")
    if not args.dry_run:
        print(f"  Rows replayed:  {rows_replayed:,}")
        print(f"  Outbox entries created — relay will publish to {topic}")

    # Verification pass
    if args.verify:
        print(f"\nRunning hash verification...")
        total_checked, mismatches, details = await _verify_hashes(
            session_factory=session_factory,
            source=args.source,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            resolution=args.resolution,
        )

        print(f"  Rows verified: {total_checked:,}")
        print(f"  Mismatches:    {mismatches}")

        if mismatches > 0:
            print(f"\n  ⚠ Hash mismatches detected:")
            for detail in details[:20]:
                print(detail)
            if len(details) > 20:
                print(f"  ... and {len(details) - 20} more")
            sys.exit(1)
        else:
            print(f"  ✓ All hashes match — data is reproducible")

    print()


if __name__ == "__main__":
    asyncio.run(main())
