"""Dead Letter Queue (DLQ) for failed ingestion records.

When a bar fails validation, deduplication conflict resolution, or
persistence, it's routed to the DLQ topic for manual inspection and
potential replay. The DLQ entry preserves the full context of the failure.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from astraeus_marketdata.models import Outbox

logger = structlog.get_logger("astraeus.marketdata.dlq")

# DLQ topic name in Redpanda
DLQ_TOPIC = "md.dlq.v1"


class DLQEntry:
    """Represents a failed record destined for the dead letter queue."""

    def __init__(
        self,
        original_topic: str,
        original_key: str | None,
        payload: dict[str, Any],
        error_type: str,
        error_message: str,
        source: str,
        run_id: uuid.UUID | None = None,
        attempt_count: int = 1,
    ) -> None:
        self.id = uuid.uuid4()
        self.original_topic = original_topic
        self.original_key = original_key
        self.payload = payload
        self.error_type = error_type
        self.error_message = error_message
        self.source = source
        self.run_id = run_id
        self.attempt_count = attempt_count
        self.failed_at = datetime.now(tz=UTC)

    def to_outbox_payload(self) -> bytes:
        """Serialize the DLQ entry for the outbox table."""
        return json.dumps(
            {
                "dlq_id": str(self.id),
                "original_topic": self.original_topic,
                "original_key": self.original_key,
                "payload": self.payload,
                "error": {
                    "type": self.error_type,
                    "message": self.error_message,
                },
                "source": self.source,
                "run_id": str(self.run_id) if self.run_id else None,
                "attempt_count": self.attempt_count,
                "failed_at": self.failed_at.isoformat(),
            }
        ).encode()


async def send_to_dlq(
    session: AsyncSession,
    entry: DLQEntry,
) -> None:
    """Write a DLQ entry to the outbox for relay to Redpanda.

    Uses the same transactional outbox pattern as normal bar events,
    ensuring DLQ entries are never lost even if the relay is down.
    """
    outbox_row = Outbox(
        topic=DLQ_TOPIC,
        key=entry.original_key.encode() if entry.original_key else None,
        payload=entry.to_outbox_payload(),
        headers={
            "error_type": entry.error_type,
            "source": entry.source,
            "run_id": str(entry.run_id) if entry.run_id else "",
            "original_topic": entry.original_topic,
        },
    )
    session.add(outbox_row)
    await session.flush()

    logger.warning(
        "dlq_entry_created",
        dlq_id=str(entry.id),
        error_type=entry.error_type,
        source=entry.source,
        original_topic=entry.original_topic,
        original_key=entry.original_key,
    )


async def get_dlq_entries(
    session: AsyncSession,
    limit: int = 100,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve DLQ entries from the outbox for inspection.

    Returns parsed DLQ payloads from the outbox table.
    """
    query = select(Outbox).where(Outbox.topic == DLQ_TOPIC)

    if source:
        query = query.where(Outbox.headers["source"].astext == source)

    query = query.order_by(Outbox.created_at.desc()).limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()

    entries: list[dict[str, Any]] = []
    for row in rows:
        try:
            parsed = json.loads(row.payload.decode())
            parsed["outbox_id"] = row.id
            parsed["published_at"] = row.published_at.isoformat() if row.published_at else None
            entries.append(parsed)
        except (json.JSONDecodeError, UnicodeDecodeError):
            entries.append(
                {
                    "outbox_id": row.id,
                    "error": "Failed to parse DLQ payload",
                    "raw_size": len(row.payload),
                }
            )

    return entries
