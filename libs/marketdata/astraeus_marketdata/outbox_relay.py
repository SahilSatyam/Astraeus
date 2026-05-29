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
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from sqlalchemy import select

from astraeus_marketdata.models import Outbox

if TYPE_CHECKING:
    pass

logger = structlog.get_logger("astraeus.marketdata.outbox_relay")

# Batch size for each poll cycle
_BATCH_SIZE = 100
# Poll interval when no rows found
_POLL_INTERVAL = 2.0


class KafkaProducer(Protocol):
    """Protocol for Kafka/Redpanda producers (matches aiokafka.AIOKafkaProducer)."""

    async def send(
        self,
        topic: str,
        value: bytes | None = None,
        key: bytes | None = None,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> Any: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


async def create_kafka_producer(
    bootstrap_servers: str,
    client_id: str = "astraeus-outbox-relay",
) -> Any:
    """Create and start an aiokafka producer.

    Returns None if aiokafka is not installed (falls back to log-only mode).
    """
    try:
        from aiokafka import AIOKafkaProducer  # noqa: PLC0415

        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            acks="all",
            enable_idempotence=True,
            max_batch_size=16384,
            linger_ms=10,
        )
        await producer.start()
        logger.info("kafka_producer_started", bootstrap_servers=bootstrap_servers)
        return producer
    except ImportError:
        logger.warning(
            "aiokafka_not_installed",
            msg="Running in log-only mode. Install aiokafka for Redpanda publishing.",
        )
        return None
    except Exception:
        logger.exception("kafka_producer_connect_failed")
        return None


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

    logger.info("outbox_relay_started", mode="publish" if producer else "log-only")

    while not stop_event.is_set():
        try:
            published = await _drain_batch(session_factory, producer)
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
            if producer is not None:
                # Build headers as list of (key, value) tuples for Kafka
                headers: list[tuple[str, bytes]] | None = None
                if row.headers:
                    headers = [
                        (k, v.encode() if isinstance(v, str) else str(v).encode())
                        for k, v in row.headers.items()
                    ]

                try:
                    await producer.send(  # type: ignore[union-attr]
                        topic=row.topic,
                        value=row.payload,
                        key=row.key,
                        headers=headers,
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
