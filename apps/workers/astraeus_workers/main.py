"""Placeholder worker loop.

Boots structlog + tracing using the same primitives as the API, then sleeps in
a graceful loop. Replaced in Phase 1 with whichever scheduler we adopt.
"""

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING

import structlog
from astraeus_config import Settings
from astraeus_observability import configure_logging, configure_tracing

if TYPE_CHECKING:
    from collections.abc import Iterable


_TICK_SECONDS = 30.0


async def _run(settings: Settings) -> None:
    log = structlog.get_logger("astraeus.workers")
    log.info(
        "worker_started",
        env=settings.env.value,
        version=settings.app.version,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in _signals():
        loop.add_signal_handler(sig, stop_event.set)

    try:
        while not stop_event.is_set():
            log.debug("worker_tick")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_TICK_SECONDS)
            except TimeoutError:
                continue
    finally:
        log.info("worker_stopped")


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
