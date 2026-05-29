"""Document ingestion worker — persists documents and triggers NLP pipeline.

Handles:
- Deduplication (by source + source_doc_id)
- Body storage in MinIO
- Metadata persistence in Postgres
- Outbox event emission for NLP pipeline trigger
- DLQ routing for failures

Mirrors the Phase 1 ingestion pattern for market data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from astraeus_altdata.documents import RawDocument
from astraeus_altdata.models import RawDocumentRow
from astraeus_altdata.outbox import emit_dlq_entry, emit_document_ingested

if TYPE_CHECKING:
    from minio import Minio
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.altdata.ingestion")

# MinIO bucket for document bodies
ALTDATA_BUCKET = "altdata-documents"


async def ingest_document(
    session: AsyncSession,
    minio_client: Minio,
    doc: RawDocument,
    run_id: uuid.UUID,
) -> bool:
    """Ingest a single document: store body in MinIO, metadata in Postgres.

    Returns True if the document was ingested (new), False if deduplicated.
    """
    # Deduplication check
    existing = await session.execute(
        select(RawDocumentRow.doc_id).where(
            RawDocumentRow.source == doc.source.value,
            RawDocumentRow.source_doc_id == doc.source_doc_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        logger.debug("document_deduplicated", source=doc.source, source_doc_id=doc.source_doc_id)
        return False

    try:
        # Store body in MinIO
        body_uri = _store_body(minio_client, doc)

        # Compute available_at = max(publish_ts, now())
        now = datetime.now(tz=UTC)
        available_at = max(doc.publish_ts, now)

        # Persist metadata
        row = RawDocumentRow(
            doc_id=doc.doc_id,
            source=doc.source.value,
            source_doc_id=doc.source_doc_id,
            url=doc.url,
            title=doc.title,
            body_uri=body_uri,
            body_hash=doc.body_hash,
            language=doc.language,
            event_ts=doc.event_ts,
            publish_ts=doc.publish_ts,
            available_at=available_at,
        )
        session.add(row)

        # Emit outbox event
        await emit_document_ingested(session, doc, body_uri, run_id)

        await session.flush()

        logger.info(
            "document_ingested",
            doc_id=str(doc.doc_id),
            source=doc.source,
            title=doc.title[:80] if doc.title else None,
        )
        return True

    except Exception as e:
        await emit_dlq_entry(
            session=session,
            source=doc.source.value,
            source_doc_id=doc.source_doc_id,
            error_type=type(e).__name__,
            error_message=str(e)[:500],
            run_id=run_id,
        )
        logger.exception(
            "document_ingest_failed", source=doc.source, source_doc_id=doc.source_doc_id
        )
        return False


def _store_body(minio_client: Minio, doc: RawDocument) -> str:
    """Store document body in MinIO and return the URI."""
    import io

    object_name = f"{doc.source.value}/{doc.doc_id}.txt"
    body_bytes = doc.body.encode("utf-8")

    # Ensure bucket exists
    if not minio_client.bucket_exists(ALTDATA_BUCKET):
        minio_client.make_bucket(ALTDATA_BUCKET)

    minio_client.put_object(
        bucket_name=ALTDATA_BUCKET,
        object_name=object_name,
        data=io.BytesIO(body_bytes),
        length=len(body_bytes),
        content_type="text/plain",
    )

    return f"minio://{ALTDATA_BUCKET}/{object_name}"


async def ingest_batch(
    session: AsyncSession,
    minio_client: Minio,
    documents: list[RawDocument],
    run_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Ingest a batch of documents.

    Returns counts: {"ingested": N, "deduplicated": M, "failed": K}
    """
    if run_id is None:
        run_id = uuid.uuid4()

    counts = {"ingested": 0, "deduplicated": 0, "failed": 0}

    for doc in documents:
        try:
            ingested = await ingest_document(session, minio_client, doc, run_id)
            if ingested:
                counts["ingested"] += 1
            else:
                counts["deduplicated"] += 1
        except Exception:
            counts["failed"] += 1
            logger.exception("batch_ingest_error", source_doc_id=doc.source_doc_id)

    await session.commit()

    logger.info("batch_ingest_complete", **counts)
    return counts
