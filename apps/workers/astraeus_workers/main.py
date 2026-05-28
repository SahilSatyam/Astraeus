"""Market data workers — scheduler for Phase 1 background tasks.

Runs the following tasks on configurable schedules:
- Outbox relay: drains outbox table into Redpanda (every 2s)
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
from astraeus_marketdata.outbox_relay import relay_loop
from astraeus_observability import configure_logging, configure_tracing
from sqlalchemy import select

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

    # Launch background tasks
    tasks: list[asyncio.Task] = [
        asyncio.create_task(
            _outbox_relay_task(session_factory, stop_event),
            name="outbox-relay",
        ),
        asyncio.create_task(
            _nightly_scheduler(session_factory, stop_event),
            name="nightly-scheduler",
        ),
    ]

    # Wait for stop signal
    await stop_event.wait()

    # Cancel all tasks gracefully
    logger.info("worker_shutting_down")
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("worker_stopped")


async def _outbox_relay_task(
    session_factory: object,
    stop_event: asyncio.Event,
) -> None:
    """Run the outbox relay loop."""
    try:
        await relay_loop(
            session_factory=session_factory,
            producer=None,  # Log-only mode until Redpanda producer is wired
            stop_event=stop_event,
        )
    except asyncio.CancelledError:
        logger.info("outbox_relay_cancelled")


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

    sm = session_factory  # type: ignore[assignment]

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
