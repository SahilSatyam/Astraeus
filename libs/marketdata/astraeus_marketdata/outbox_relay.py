"""Outbox relay — drains the outbox table into Redis Streams.

The relay runs as a background loop (inside the workers service). It:
1. Polls for unpublished outbox rows (published_at IS NULL)
2. Publishes each to the designated Redis Stream (XADD)
3. Marks the row as published (sets published_at)

This gives effectively-once semantics: the bar write + outbox insert happen
in the same DB transaction. The relay is idempotent — if it crashes mid-batch,
it re-publishes on restart; downstream consumers deduplicate on payload_hash.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy import select

from astraeus_marketdata.models import Outbox

logger = structlog.get_logger("astraeus.marketdata.outbox_relay")

# Batch size for each poll cycle
_BATCH_SIZE = 100
# Poll interval when no rows found
_POLL_INTERVAL = 2.0


class StreamPublisher(Protocol):
    """Protocol for stream publishers (Redis Streams implementation)."""

    async def publish(
        self,
        stream: str,
        data: dict[str, str | bytes],
    ) -> str: ...

    async def close(self) -> None: ...


class RedisStreamPublisher:
    """Publishes outbox events to Redis Streams via XADD."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def publish(
        self,
        stream: str,
        data: dict[str, str | bytes],
    ) -> str:
        """Publish a message to a Redis Stream. Returns the message ID."""
        message_id: str = await self._redis.xadd(stream, data)  # type: ignore[assignment]
        return message_id

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        await self._redis.aclose()


async def create_stream_publisher(redis_url: str) -> RedisStreamPublisher | None:
    """Create a Redis Streams publisher.

    Returns None if redis is not available (falls back to log-only mode).
    """
    try:
        from redis.asyncio import from_url

        redis = from_url(redis_url, decode_responses=False)
        # Verify connectivity
        await redis.ping()
        logger.info("stream_publisher_started", redis_url=redis_url)
        return RedisStreamPublisher(redis)
    except ImportError:
        logger.warning(
            "redis_not_installed",
            msg="Running in log-only mode. Install redis for stream publishing.",
        )
        return None
    except Exception:
        logger.exception("stream_publisher_connect_failed")
        return None


async def relay_loop(
    session_factory: object,
    publisher: StreamPublisher | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Main relay loop. Runs until stop_event is set.

    Args:
        session_factory: async_sessionmaker for DB access.
        publisher: Redis Streams publisher (None = log-only mode for dev).
        stop_event: Signal to stop the loop gracefully.
    """
    if stop_event is None:
        stop_event = asyncio.Event()

    logger.info("outbox_relay_started", mode="publish" if publisher else "log-only")

    while not stop_event.is_set():
        try:
            published = await _drain_batch(session_factory, publisher)
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
    publisher: StreamPublisher | None,
) -> int:
    """Fetch and publish one batch of outbox rows. Returns count published."""

    sm = session_factory
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
            if publisher is not None:
                # Build the stream message fields
                data: dict[str, str | bytes] = {
                    "payload": row.payload,
                }
                if row.key:
                    data["key"] = row.key
                if row.headers:
                    for k, v in row.headers.items():
                        data[f"h:{k}"] = v.encode() if isinstance(v, str) else str(v).encode()

                try:
                    await publisher.publish(
                        stream=row.topic,
                        data=data,
                    )
                except Exception:
                    logger.exception(
                        "outbox_publish_failed",
                        topic=row.topic,
                        outbox_id=row.id,
                    )
                    # Skip this row for now; it'll be retried next cycle
                    continue
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
