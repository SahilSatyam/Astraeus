"""Outbox relay — drains the outbox table into Redpanda/Kafka.

The relay runs as a background loop (inside the workers service). It:
1. Polls for unpublished outbox rows (published_at IS NULL)
2. Publishes each to the designated Redpanda topic
3. Marks the row as published (sets published_at)

This gives effectively-once semantics: the bar write + outbox insert happen
in the same DB transaction. The relay is idempotent — if it crashes mid-batch,
it re-publishes on restart; downstream consumers deduplicate on payload_hash.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from astraeus_marketdata.models import Outbox

logger = structlog.get_logger("astraeus.marketdata.outbox_relay")

# Batch size for each poll cycle
_BATCH_SIZE = 100
# Poll interval when no rows found
_POLL_INTERVAL = 2.0


async def relay_loop(
    session_factory: object,
    producer: object | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Main relay loop. Runs until stop_event is set.

    Args:
        session_factory: async_sessionmaker for DB access.
        producer: Kafka/Redpanda producer (None = log-only mode for dev).
        stop_event: Signal to stop the loop gracefully.
    """
    if stop_event is None:
        stop_event = asyncio.Event()

    logger.info("outbox_relay_started")

    while not stop_event.is_set():
        try:
            published = await _drain_batch(session_factory, producer)  # type: ignore[arg-type]
            if published == 0:
                # No work — back off
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=_POLL_INTERVAL)
                except TimeoutError:
                    continue
        except Exception:
            logger.exception("outbox_relay_error")
            await asyncio.sleep(_POLL_INTERVAL)

    logger.info("outbox_relay_stopped")


async def _drain_batch(
    session_factory: object,
    producer: object | None,
) -> int:
    """Fetch and publish one batch of outbox rows. Returns count published."""

    sm = session_factory  # type: ignore[assignment]
    async with sm() as session:  # type: ignore[operator]
        # Fetch unpublished rows
        result = await session.execute(
            select(Outbox)
            .where(Outbox.published_at.is_(None))
            .order_by(Outbox.created_at)
            .limit(_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars().all())

        if not rows:
            return 0

        now = datetime.now(tz=UTC)

        for row in rows:
            # Publish to Kafka/Redpanda (or log in dev mode)
            if producer is not None:
                # TODO(phase1): wire real Redpanda producer
                pass
            else:
                logger.debug(
                    "outbox_relay_publish",
                    topic=row.topic,
                    key=row.key.decode() if row.key else None,
                    payload_size=len(row.payload),
                )

            row.published_at = now

        await session.commit()

        logger.info("outbox_relay_batch", published=len(rows))
        return len(rows)
