#!/usr/bin/env python3
"""Universe load script — imports universe membership and security master data from CSV.

Usage:
    uv run python scripts/load-universe.py --csv data/universe_sp500.csv
    uv run python scripts/load-universe.py --csv data/universe_sp500.csv --dry-run

Expected CSV format:
    universe_id,symbol,effective_from,effective_to,reason_added,reason_removed
    sp500,AAPL,2000-01-01,,IPO,
    sp500,META,2013-12-23,,IPO,
    sp500,FB,2013-12-23,2022-06-09,IPO,renamed to META

Columns:
    - universe_id: Identifier for the universe (e.g., "sp500", "russell2000")
    - symbol: Internal symbol identifier (e.g., "AAPL", "MSFT")
    - effective_from: Date the symbol joined the universe (ISO format: YYYY-MM-DD)
    - effective_to: Date the symbol left the universe (ISO format, empty if still active)
    - reason_added: Why the symbol was added (e.g., "IPO", "spin-off", "index rebalance")
    - reason_removed: Why the symbol was removed (e.g., "delisted", "acquisition", "index rebalance")

Behavior:
    - Inserts rows into the `universe` table (UniverseMembership)
    - Inserts unique symbols into the `security_master` table (SecurityMaster) if not already present
    - Sets knowledge_ts = effective_from (for historical loads)
    - Supports --dry-run flag to preview without writing
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog
from astraeus_config import Settings
from astraeus_db import get_session
from astraeus_observability import configure_logging
from astraeus_universe.models import SecurityMaster, UniverseMembership
from sqlalchemy import select


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load universe membership data from CSV into the database."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        required=True,
        help="Path to the CSV file with universe data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate only, don't write to database",
    )
    return parser.parse_args()


def parse_csv(csv_path: Path) -> list[dict[str, str]]:
    """Parse the CSV file and return a list of row dicts."""
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    rows: list[dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Validate headers
        required_headers = {"universe_id", "symbol", "effective_from"}
        if reader.fieldnames is None:
            print("ERROR: CSV file is empty or has no headers", file=sys.stderr)
            sys.exit(1)

        missing = required_headers - set(reader.fieldnames)
        if missing:
            print(f"ERROR: CSV missing required columns: {sorted(missing)}", file=sys.stderr)
            sys.exit(1)

        for i, row in enumerate(reader, start=2):  # start=2 because line 1 is header
            if not row.get("universe_id") or not row.get("symbol") or not row.get("effective_from"):
                print(f"WARNING: Skipping row {i} — missing required fields", file=sys.stderr)
                continue
            rows.append(row)

    return rows


def parse_date(date_str: str) -> datetime | None:
    """Parse an ISO date string to a timezone-aware datetime, or None if empty."""
    if not date_str or not date_str.strip():
        return None
    return datetime.fromisoformat(date_str.strip()).replace(tzinfo=UTC)


async def main() -> None:
    args = parse_args()
    settings = Settings()
    configure_logging(settings.observability, service="load-universe")
    log = structlog.get_logger("astraeus.scripts.load_universe")

    rows = parse_csv(args.csv)
    log.info("csv_parsed", rows=len(rows), csv_path=str(args.csv))

    if not rows:
        print("No rows to process.")
        return

    if args.dry_run:
        print(f"\n[DRY RUN] Would process {len(rows)} rows:")
        symbols = sorted({r["symbol"] for r in rows})
        universes = sorted({r["universe_id"] for r in rows})
        print(f"  Universes: {', '.join(universes)}")
        print(f"  Unique symbols: {len(symbols)}")
        print(f"  Sample symbols: {', '.join(symbols[:10])}")
        return

    universe_count = 0
    security_count = 0
    seen_symbols: set[str] = set()

    async with get_session(settings.db) as session:
        for row in rows:
            symbol = row["symbol"].strip().upper()
            universe_id = row["universe_id"].strip()
            effective_from = parse_date(row["effective_from"])

            if effective_from is None:
                continue

            effective_to = parse_date(row.get("effective_to", ""))
            reason_added = row.get("reason_added", "").strip() or None
            reason_removed = row.get("reason_removed", "").strip() or None

            # knowledge_ts = effective_from for historical loads
            knowledge_ts = effective_from

            # Insert into universe table
            membership = UniverseMembership(
                universe_id=universe_id,
                symbol=symbol,
                effective_from=effective_from,
                knowledge_ts=knowledge_ts,
                effective_to=effective_to,
                reason_added=reason_added,
                reason_removed=reason_removed,
            )
            session.add(membership)
            universe_count += 1

            # Insert into security_master if not already seen
            if symbol not in seen_symbols:
                seen_symbols.add(symbol)

                # Check if symbol already exists in security_master
                existing = await session.execute(
                    select(SecurityMaster).where(SecurityMaster.symbol == symbol)
                )
                if existing.scalar_one_or_none() is None:
                    security = SecurityMaster(
                        symbol=symbol,
                        listed_ticker=symbol,
                        listed_from=effective_from,
                    )
                    session.add(security)
                    security_count += 1

        await session.commit()

    log.info(
        "load_complete",
        universe_rows=universe_count,
        new_securities=security_count,
    )

    print(f"\nLoad complete:")
    print(f"  Universe rows inserted: {universe_count}")
    print(f"  New securities added:   {security_count}")
    print(f"  Total unique symbols:   {len(seen_symbols)}")


if __name__ == "__main__":
    asyncio.run(main())
