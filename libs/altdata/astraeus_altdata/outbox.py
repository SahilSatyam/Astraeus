"""Alt-data outbox — mirrors the Phase 1 outbox pattern for document events.

When a new document is ingested, an outbox entry is created in the same
transaction. The relay publishes it to Redis Streams, triggering the NLP pipeline.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from astraeus_marketdata.models import Outbox

from astraeus_altdata.documents import RawDocument

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.altdata.outbox")

# Topic for new document events
ALTDATA_DOC_TOPIC = "altdata.document.ingested.v1"
ALTDATA_DLQ_TOPIC = "altdata.dlq.v1"


async def emit_document_ingested(
    session: AsyncSession,
    doc: RawDocument,
    body_uri: str,
    run_id: uuid.UUID,
) -> None:
    """Write an outbox entry for a newly ingested document.

    The NLP pipeline worker consumes these events to trigger processing.
    """
    payload = json.dumps(
        {
            "doc_id": str(doc.doc_id),
            "source": doc.source.value,
            "source_doc_id": doc.source_doc_id,
            "title": doc.title,
            "body_uri": body_uri,
            "publish_ts": doc.publish_ts.isoformat(),
            "event_ts": doc.event_ts.isoformat() if doc.event_ts else None,
            "run_id": str(run_id),
        }
    ).encode()

    session.add(
        Outbox(
            topic=ALTDATA_DOC_TOPIC,
            key=doc.source.value.encode(),
            payload=payload,
            headers={
                "source": doc.source.value,
                "doc_id": str(doc.doc_id),
                "run_id": str(run_id),
            },
        )
    )
    await session.flush()


async def emit_dlq_entry(
    session: AsyncSession,
    source: str,
    source_doc_id: str,
    error_type: str,
    error_message: str,
    run_id: uuid.UUID,
) -> None:
    """Write a DLQ entry for a failed document ingestion."""
    payload = json.dumps(
        {
            "dlq_id": str(uuid.uuid4()),
            "source": source,
            "source_doc_id": source_doc_id,
            "error": {"type": error_type, "message": error_message},
            "run_id": str(run_id),
            "failed_at": datetime.now(tz=UTC).isoformat(),
        }
    ).encode()

    session.add(
        Outbox(
            topic=ALTDATA_DLQ_TOPIC,
            key=source.encode(),
            payload=payload,
            headers={
                "error_type": error_type,
                "source": source,
                "run_id": str(run_id),
            },
        )
    )
    await session.flush()

    logger.warning(
        "altdata_dlq_entry",
        source=source,
        source_doc_id=source_doc_id,
        error_type=error_type,
    )
