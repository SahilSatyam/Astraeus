"""Chunk store — persistence layer for document chunks and embeddings.

Handles writing chunks to Postgres (with pgvector embeddings) and
reading them back for retrieval or reprocessing.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.rag.chunk_store")


async def store_chunks(
    session: AsyncSession,
    doc_id: uuid.UUID,
    chunks: list[dict[str, object]],
) -> int:
    """Store document chunks with embeddings.

    Each chunk dict should have: text, chunk_idx, token_count, embedding (list[float] or None).

    Returns the number of chunks stored.
    """
    stored = 0

    for chunk in chunks:
        chunk_id = uuid.uuid4()
        embedding = chunk.get("embedding")

        # Use raw SQL for pgvector embedding column
        if embedding:
            vector_str = "[" + ",".join(str(v) for v in embedding) + "]"  # type: ignore[union-attr]
            await session.execute(
                text("""
                    INSERT INTO document_chunk (chunk_id, doc_id, chunk_idx, text, token_count, embedding)
                    VALUES (:chunk_id, :doc_id, :chunk_idx, :text, :token_count, :embedding::vector)
                    ON CONFLICT (doc_id, chunk_idx) DO NOTHING
                """),
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "chunk_idx": chunk["chunk_idx"],
                    "text": chunk["text"],
                    "token_count": chunk["token_count"],
                    "embedding": vector_str,
                },
            )
        else:
            await session.execute(
                text("""
                    INSERT INTO document_chunk (chunk_id, doc_id, chunk_idx, text, token_count)
                    VALUES (:chunk_id, :doc_id, :chunk_idx, :text, :token_count)
                    ON CONFLICT (doc_id, chunk_idx) DO NOTHING
                """),
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "chunk_idx": chunk["chunk_idx"],
                    "text": chunk["text"],
                    "token_count": chunk["token_count"],
                },
            )

        stored += 1

    await session.flush()
    return stored


async def get_chunks_for_doc(
    session: AsyncSession,
    doc_id: uuid.UUID,
) -> list[dict[str, object]]:
    """Retrieve all chunks for a document, ordered by chunk_idx."""
    result = await session.execute(
        text("""
            SELECT chunk_id, doc_id, chunk_idx, text, token_count
            FROM document_chunk
            WHERE doc_id = :doc_id
            ORDER BY chunk_idx
        """),
        {"doc_id": doc_id},
    )
    rows = result.fetchall()
    return [
        {
            "chunk_id": row.chunk_id,
            "doc_id": row.doc_id,
            "chunk_idx": row.chunk_idx,
            "text": row.text,
            "token_count": row.token_count,
        }
        for row in rows
    ]


async def get_chunk_by_id(
    session: AsyncSession,
    chunk_id: uuid.UUID,
) -> dict[str, object] | None:
    """Retrieve a single chunk by ID."""
    result = await session.execute(
        text("""
            SELECT dc.chunk_id, dc.doc_id, dc.chunk_idx, dc.text, dc.token_count,
                   rd.source, rd.title, rd.publish_ts
            FROM document_chunk dc
            JOIN raw_document rd ON rd.doc_id = dc.doc_id
            WHERE dc.chunk_id = :chunk_id
        """),
        {"chunk_id": chunk_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "chunk_id": row.chunk_id,
        "doc_id": row.doc_id,
        "chunk_idx": row.chunk_idx,
        "text": row.text,
        "token_count": row.token_count,
        "source": row.source,
        "title": row.title,
        "publish_ts": row.publish_ts,
    }
