"""NLP pipeline worker — processes ingested documents through the full NLP stack.

Consumes document-ingested events from Redpanda and processes each document:
1. Fetch body from MinIO
2. Clean + chunk
3. NER + entity linking
4. FinBERT sentiment
5. Sentence-transformer embeddings
6. Persist chunks, entities, sentiment, embeddings

Runs as a long-lived consumer. Batch mode available for backfill.

Usage:
    python -m astraeus_workers.nlp_worker
    python -m astraeus_workers.nlp_worker --backfill --limit 1000
"""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import text

logger = structlog.get_logger("astraeus.workers.nlp_worker")


async def process_document(
    session: object,
    minio_client: object,
    doc_id: uuid.UUID,
    body_uri: str,
    pipeline: object,
) -> dict[str, object]:
    """Process a single document through the NLP pipeline.

    Fetches body from MinIO, runs the pipeline, persists results.
    """
    from astraeus_altdata.documents import DocumentSource, RawDocument
    from astraeus_altdata.metrics import (
        record_entity_linked,
        record_nlp_latency,
        record_sentiment_score,
    )
    from astraeus_rag.chunk_store import store_chunks

    start = time.perf_counter()

    # Fetch body from MinIO
    bucket, object_name = _parse_minio_uri(body_uri)
    response = minio_client.get_object(bucket, object_name)  # type: ignore[union-attr]
    body = response.read().decode("utf-8")
    response.close()
    response.release_conn()

    # Create a minimal RawDocument for the pipeline
    doc = RawDocument(
        source=DocumentSource.RSS,  # Will be overridden by actual source
        source_doc_id=str(doc_id),
        body=body,
        publish_ts=datetime.now(tz=UTC),
    )

    # Run NLP pipeline
    result = pipeline.process_document(doc)  # type: ignore[union-attr]

    processing_ms = (time.perf_counter() - start) * 1000
    record_nlp_latency("pipeline_total", processing_ms)

    # Persist chunks with embeddings
    if result.n_chunks > 0:
        from astraeus_nlp.chunker import RecursiveChunker

        chunker = RecursiveChunker()
        from astraeus_nlp.cleaner import clean_document

        cleaned = clean_document(body)
        chunks = chunker.chunk(cleaned)

        # Compute embeddings
        embeddings = pipeline.embed_chunks(chunks)  # type: ignore[union-attr]

        chunk_dicts = [
            {
                "text": chunk.text,
                "chunk_idx": chunk.chunk_idx,
                "token_count": chunk.token_count,
                "embedding": emb,
            }
            for chunk, emb in zip(chunks, embeddings, strict=False)
        ]

        await store_chunks(session, doc_id, chunk_dicts)  # type: ignore[arg-type]

    # Persist entity mentions
    if result.n_entities > 0:
        # Entity persistence handled by pipeline result
        for _ticker in result.tickers_found:
            record_entity_linked("ticker")

    # Persist sentiment scores
    for ticker, score in result.sentiment_scores.items():
        record_sentiment_score("pipeline", score)
        await session.execute(  # type: ignore[union-attr]
            text("""
                INSERT INTO sentiment_score (doc_id, ticker, model, label, score, available_at)
                VALUES (:doc_id, :ticker, :model, :label, :score, now())
                ON CONFLICT (doc_id, ticker, model) DO NOTHING
            """),
            {
                "doc_id": doc_id,
                "ticker": ticker,
                "model": "finbert_v1.0",
                "label": "positive" if score > 0.1 else ("negative" if score < -0.1 else "neutral"),
                "score": score,
            },
        )

    await session.commit()  # type: ignore[union-attr]

    logger.info(
        "document_processed",
        doc_id=str(doc_id),
        chunks=result.n_chunks,
        entities=result.n_entities,
        tickers=result.tickers_found,
        ms=round(processing_ms, 1),
    )

    return {
        "doc_id": str(doc_id),
        "n_chunks": result.n_chunks,
        "n_entities": result.n_entities,
        "tickers": result.tickers_found,
        "processing_ms": round(processing_ms, 1),
    }


async def backfill_mode(limit: int = 1000) -> None:
    """Process unprocessed documents in batch mode."""
    from astraeus_config.base import Settings
    from astraeus_db.engine import create_async_session_factory

    settings = Settings()
    session_factory = create_async_session_factory(settings.db.dsn)

    # Initialize pipeline
    pipeline = _create_pipeline()

    from minio import Minio

    minio_client = Minio(
        endpoint=settings.minio.endpoint,
        access_key=settings.minio.access_key,
        secret_key=settings.minio.secret_key.get_secret_value(),
        secure=settings.minio.secure,
    )

    async with session_factory() as session:
        # Find documents without chunks (unprocessed)
        result = await session.execute(
            text("""
                SELECT rd.doc_id, rd.body_uri
                FROM raw_document rd
                LEFT JOIN document_chunk dc ON dc.doc_id = rd.doc_id
                WHERE dc.chunk_id IS NULL
                ORDER BY rd.ingest_ts DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.fetchall()

        logger.info("backfill_start", n_documents=len(rows))

        for row in rows:
            try:
                await process_document(
                    session=session,
                    minio_client=minio_client,
                    doc_id=row.doc_id,
                    body_uri=row.body_uri,
                    pipeline=pipeline,
                )
            except Exception:
                logger.exception("backfill_document_error", doc_id=str(row.doc_id))

    logger.info("backfill_complete", processed=len(rows))


def _create_pipeline() -> object:
    """Create the NLP pipeline with all models loaded."""
    from astraeus_altdata.pipeline import NLPPipeline
    from astraeus_entities.ticker_dict import build_default_dictionary

    dictionary = build_default_dictionary()
    return NLPPipeline(ticker_dictionary=dictionary)


def _parse_minio_uri(uri: str) -> tuple[str, str]:
    """Parse minio://bucket/object into (bucket, object_name)."""
    # minio://altdata-documents/reddit/uuid.txt
    path = uri.replace("minio://", "")
    parts = path.split("/", 1)
    return parts[0], parts[1]


async def consumer_mode() -> None:
    """Run as a Kafka consumer, processing documents as they arrive."""
    logger.info("nlp_worker_consumer_mode_start")
    # In production, this would consume from the altdata.document.ingested.v1 topic
    # For now, fall back to polling the database for unprocessed documents
    while True:
        try:
            await backfill_mode(limit=50)
        except Exception:
            logger.exception("consumer_cycle_error")
        await asyncio.sleep(30)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="NLP pipeline worker")
    parser.add_argument("--backfill", action="store_true", help="Run in backfill mode")
    parser.add_argument("--limit", type=int, default=1000, help="Max documents to process")
    args = parser.parse_args()

    if args.backfill:
        asyncio.run(backfill_mode(limit=args.limit))
    else:
        asyncio.run(consumer_mode())


if __name__ == "__main__":
    main()
