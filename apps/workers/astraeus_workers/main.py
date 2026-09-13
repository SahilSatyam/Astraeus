"""Market data workers — scheduler for Phase 1 background tasks.

Runs the following tasks on configurable schedules:
- Outbox relay: drains outbox table into Redis Streams (every 2s)
- Gap detection: compares calendar vs actual data (nightly)
- Corporate action adjustment: rebuilds adjusted bars (nightly, after gap detection)
- Streaming ingestion: WebSocket connection for live bars (continuous)

Uses asyncio tasks with graceful shutdown on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import date, timedelta
from typing import TYPE_CHECKING

import structlog
from astraeus_config import Settings
from astraeus_db.session import get_sessionmaker
from astraeus_marketdata.adjustments import adjust_symbol
from astraeus_marketdata.gaps import detect_gaps
from astraeus_marketdata.models import CorporateAction, Instrument
from astraeus_marketdata.outbox_relay import create_stream_publisher, relay_loop
from astraeus_observability import configure_logging, configure_tracing
from sqlalchemy import select

from astraeus_workers.streaming import StreamingWorker

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = structlog.get_logger("astraeus.workers")


async def _run(settings: Settings) -> None:
    logger.info(
        "worker_started",
        env=settings.env.value,
        version=settings.app.version,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in _signals():
        loop.add_signal_handler(sig, stop_event.set)

    session_factory = get_sessionmaker(settings.db)

    # Create Redis Streams publisher (falls back to log-only if unavailable)
    publisher = await create_stream_publisher(redis_url=settings.redis.url)

    # Launch background tasks
    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(
            _outbox_relay_task(session_factory, publisher, stop_event),
            name="outbox-relay",
        ),
        asyncio.create_task(
            _nightly_scheduler(session_factory, stop_event),
            name="nightly-scheduler",
        ),
    ]

    # Launch streaming worker if Alpaca credentials are configured
    if settings.alpaca_api_key:
        streaming_worker = StreamingWorker(
            session_factory=session_factory,
            api_key=settings.alpaca_api_key,
            api_secret=settings.alpaca_api_secret,
        )
        tasks.append(
            asyncio.create_task(
                _streaming_task(streaming_worker, stop_event),
                name="streaming-alpaca",
            )
        )
    else:
        logger.info("streaming_disabled", reason="No Alpaca API credentials configured")

    # Wait for stop signal
    await stop_event.wait()

    # Cancel all tasks gracefully
    logger.info("worker_shutting_down")
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    # Cleanup publisher
    if publisher is not None:
        try:
            await publisher.close()
        except Exception:
            logger.exception("stream_publisher_close_error")

    logger.info("worker_stopped")


async def _outbox_relay_task(
    session_factory: object,
    publisher: object | None,
    stop_event: asyncio.Event,
) -> None:
    """Run the outbox relay loop."""
    try:
        await relay_loop(
            session_factory=session_factory,
            publisher=publisher,
            stop_event=stop_event,
        )
    except asyncio.CancelledError:
        logger.info("outbox_relay_cancelled")


async def _streaming_task(
    worker: StreamingWorker,
    stop_event: asyncio.Event,
) -> None:
    """Run the Alpaca streaming worker with auto-restart on failure."""
    while not stop_event.is_set():
        try:
            logger.info("streaming_task_starting")
            # Run until stop or failure
            stream_task = asyncio.create_task(worker.start())
            stop_task = asyncio.create_task(stop_event.wait())

            done, pending = await asyncio.wait(
                {stream_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            if stop_event.is_set():
                await worker.stop()
                return

            # Stream task finished (likely error) — restart after backoff
            for task in done:
                if task.exception():
                    logger.error(
                        "streaming_task_failed",
                        error=str(task.exception()),
                    )

            logger.info("streaming_task_restarting", backoff_seconds=10)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=10.0)
                await worker.stop()
                return
            except TimeoutError:
                continue

        except asyncio.CancelledError:
            await worker.stop()
            logger.info("streaming_task_cancelled")
            return


async def _nightly_scheduler(
    session_factory: object,
    stop_event: asyncio.Event,
) -> None:
    """Run nightly tasks: gap detection + adjustment rebuild.

    Executes once at startup (if past market close) and then every 24h.
    In practice, this runs after US market close (~21:00 UTC).
    """
    # Wait a bit on startup to let other services stabilize
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=30.0)
        return  # Stop was signaled during startup delay
    except TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            await _run_nightly_jobs(session_factory)
        except Exception:
            logger.exception("nightly_job_error")

        # Sleep until next run (24 hours)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=86400.0)
            return
        except TimeoutError:
            continue


async def _run_nightly_jobs(session_factory: object) -> None:
    """Execute the nightly maintenance jobs."""
    logger.info("nightly_jobs_start")

    sm = session_factory

    async with sm() as session:  # type: ignore[operator]
        # 1. Gap detection for active instruments
        result = await session.execute(
            select(Instrument.symbol).where(Instrument.is_active.is_(True))
        )
        active_symbols = [row[0] for row in result.all()]

        if active_symbols:
            today = date.today()
            # Check last 7 days for gaps
            start = today - timedelta(days=7)

            gaps = await detect_gaps(
                session=session,
                symbols=active_symbols,
                exchange="NYSE",
                start=start,
                end=today,
                resolution="1d",
            )
            logger.info("nightly_gap_detection_complete", new_gaps=len(gaps))

            # 2. Rebuild adjustments for symbols with corporate actions
            ca_result = await session.execute(select(CorporateAction.symbol).distinct())
            symbols_with_actions = [row[0] for row in ca_result.all()]

            adjusted_count = 0
            for symbol in symbols_with_actions:
                count = await adjust_symbol(session, symbol)
                adjusted_count += count

            logger.info(
                "nightly_adjustments_complete",
                symbols=len(symbols_with_actions),
                adjusted_bars=adjusted_count,
            )

        await session.commit()

    logger.info("nightly_jobs_complete")


def _signals() -> Iterable[int]:
    return (signal.SIGINT, signal.SIGTERM)


def main() -> None:
    settings = Settings()
    configure_logging(settings.observability, service="workers")
    configure_tracing(
        settings.observability,
        service_name="workers",
        service_version=settings.app.version,
        environment=settings.env.value,
    )
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
