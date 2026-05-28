#!/usr/bin/env python3
"""Market data backfill CLI.

Usage:
    uv run python scripts/md-backfill.py --source yahoo --symbols SPY,AAPL,MSFT \
        --start 2020-01-01 --end 2024-12-31

    uv run python scripts/md-backfill.py --source yahoo --symbols-file universe.txt \
        --start 2020-01-01 --end 2024-12-31

    uv run python scripts/md-backfill.py --source yahoo --symbols SPY --start 2024-01-01 \
        --end 2024-01-31 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

import structlog
from astraeus_config import Settings
from astraeus_db import get_session
from astraeus_marketdata.adapters.alpaca import AlpacaAdapter
from astraeus_marketdata.adapters.fred import FredAdapter
from astraeus_marketdata.adapters.yahoo import YahooAdapter
from astraeus_marketdata.ingestion import run_ingestion
from astraeus_observability import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market data backfill tool")
    parser.add_argument(
        "--source",
        choices=["yahoo", "alpaca", "fred"],
        default="yahoo",
        help="Data source adapter",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        help="Comma-separated list of symbols",
    )
    parser.add_argument(
        "--symbols-file",
        type=Path,
        help="File with one symbol per line",
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--resolution", default="1d", choices=["1d", "1h", "1m"])
    parser.add_argument("--batch-size", type=int, default=10, help="Symbols per batch")
    parser.add_argument("--dry-run", action="store_true", help="Fetch only, don't persist")
    return parser.parse_args()


def get_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [s.strip().upper() for s in args.symbols.split(",")]
    if args.symbols_file:
        return [
            line.strip().upper()
            for line in args.symbols_file.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    print("ERROR: provide --symbols or --symbols-file", file=sys.stderr)
    sys.exit(1)


async def main() -> None:
    args = parse_args()
    settings = Settings()
    configure_logging(settings.observability, service="md-backfill")
    log = structlog.get_logger("astraeus.md.backfill")

    symbols = get_symbols(args)
    log.info(
        "backfill_start",
        source=args.source,
        symbols=len(symbols),
        start=str(args.start),
        end=str(args.end),
        resolution=args.resolution,
        dry_run=args.dry_run,
    )

    # Select adapter
    if args.source == "yahoo":
        adapter = YahooAdapter()
    elif args.source == "alpaca":
        adapter = AlpacaAdapter(
            api_key=os.environ["ALPACA_API_KEY"],
            api_secret=os.environ["ALPACA_API_SECRET"],
        )
    elif args.source == "fred":
        adapter = FredAdapter(api_key=os.environ["FRED_API_KEY"])
    else:
        print(f"Unknown source: {args.source}", file=sys.stderr)
        sys.exit(1)

    total_fetched = 0
    total_written = 0
    total_skipped = 0

    try:
        # Process in batches
        for i in range(0, len(symbols), args.batch_size):
            batch = symbols[i : i + args.batch_size]
            log.info("batch_start", batch_num=i // args.batch_size + 1, symbols=batch)

            if args.dry_run:
                results = await adapter.fetch_bars(batch, args.start, args.end, args.resolution)
                for r in results:
                    total_fetched += len(r.bars)
                log.info("batch_dry_run", fetched=sum(len(r.bars) for r in results))
            else:
                async with get_session(settings.db) as session:
                    run = await run_ingestion(
                        adapter=adapter,
                        session=session,
                        symbols=batch,
                        start=args.start,
                        end=args.end,
                        resolution=args.resolution,
                    )
                    total_fetched += run.rows_fetched
                    total_written += run.rows_written
                    total_skipped += run.rows_skipped
    finally:
        await adapter.close()

    log.info(
        "backfill_complete",
        total_fetched=total_fetched,
        total_written=total_written,
        total_skipped=total_skipped,
    )

    print("\nBackfill complete:")
    print(f"  Source:  {args.source}")
    print(f"  Symbols: {len(symbols)}")
    print(f"  Range:   {args.start} → {args.end}")
    print(f"  Fetched: {total_fetched}")
    print(f"  Written: {total_written}")
    print(f"  Skipped: {total_skipped}")


if __name__ == "__main__":
    asyncio.run(main())
