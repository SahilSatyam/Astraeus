"""Alt-data ingestion worker entry point.

Runs a scheduled ingestion loop for a specific source adapter.
Fetches documents, deduplicates, stores in MinIO + Postgres, emits outbox events.

Usage:
    python -m astraeus_workers.altdata_ingest --source reddit
    python -m astraeus_workers.altdata_ingest --source rss
    python -m astraeus_workers.altdata_ingest --source edgar
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

import structlog

logger = structlog.get_logger("astraeus.workers.altdata_ingest")

# Ingestion interval per source (seconds)
_INTERVALS = {
    "reddit": 300,  # 5 minutes
    "rss": 600,  # 10 minutes
    "edgar": 3600,  # 1 hour
}


async def run_ingestion_cycle(source: str) -> dict[str, int]:
    """Run a single ingestion cycle for the given source.

    Creates the appropriate adapter, fetches documents, and ingests them.
    """
    from astraeus_altdata.ingestion import ingest_batch
    from astraeus_config.base import Settings
    from astraeus_db.engine import create_async_session_factory
    from minio import Minio

    settings = Settings()
    session_factory = create_async_session_factory(settings.db.dsn)

    minio_client = Minio(
        endpoint=settings.minio.endpoint,
        access_key=settings.minio.access_key,
        secret_key=settings.minio.secret_key.get_secret_value(),
        secure=settings.minio.secure,
    )

    # Create adapter based on source
    adapter = _create_adapter(source)
    run_id = uuid.uuid4()

    logger.info("ingestion_cycle_start", source=source, run_id=str(run_id))

    total_counts = {"ingested": 0, "deduplicated": 0, "failed": 0}

    async for result in adapter.fetch_all(max_pages=5):
        if result.is_empty:
            break

        if result.rate_limited:
            logger.warning("adapter_rate_limited", source=source)
            await asyncio.sleep(60)
            continue

        async with session_factory() as session:
            counts = await ingest_batch(
                session=session,
                minio_client=minio_client,
                documents=result.documents,
                run_id=run_id,
            )
            for k, v in counts.items():
                total_counts[k] += v

    await adapter.close()

    logger.info("ingestion_cycle_complete", source=source, **total_counts)
    return total_counts


def _create_adapter(source: str) -> object:
    """Create the appropriate source adapter."""
    if source == "reddit":
        import praw
        from astraeus_altdata.adapters.reddit import RedditAdapter
        from astraeus_config.base import Settings

        settings = Settings()
        # Reddit client setup
        reddit = praw.Reddit(
            client_id=settings.marketdata.alpaca_api_key.get_secret_value(),  # placeholder
            client_secret=settings.marketdata.alpaca_api_secret.get_secret_value(),  # placeholder
            user_agent="astraeus:v0.1.0 (by /u/astraeus_bot)",
        )
        return RedditAdapter(reddit_client=reddit)

    if source == "rss":
        from astraeus_altdata.adapters.rss import RSSAdapter

        return RSSAdapter()

    if source == "edgar":
        from astraeus_altdata.adapters.edgar import EdgarAdapter

        return EdgarAdapter()

    raise ValueError(f"Unknown source: {source}")


async def main_loop(source: str) -> None:
    """Main ingestion loop — runs indefinitely with scheduled intervals."""
    interval = _INTERVALS.get(source, 600)
    logger.info("ingestion_worker_started", source=source, interval_seconds=interval)

    while True:
        try:
            await run_ingestion_cycle(source)
        except Exception:
            logger.exception("ingestion_cycle_error", source=source)

        await asyncio.sleep(interval)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Alt-data ingestion worker")
    parser.add_argument("--source", required=True, choices=["reddit", "rss", "edgar"])
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    if args.once:
        asyncio.run(run_ingestion_cycle(args.source))
    else:
        asyncio.run(main_loop(args.source))


if __name__ == "__main__":
    main()
