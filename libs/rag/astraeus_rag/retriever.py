"""Hybrid retriever — BM25 + vector search with Reciprocal Rank Fusion.

Combines:
1. BM25 (Postgres ts_vector full-text search) — good for exact tokens (CIKs, tickers)
2. Vector similarity (pgvector HNSW cosine) — good for semantic/paraphrase queries
3. RRF combiner — robust across query types, literature consensus

All queries are PIT-correct: the `as_of` filter ensures no future documents leak.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.rag.retriever")

# RRF constant (standard value from the original paper)
_RRF_K = 60


@dataclass(frozen=True, slots=True)
class RetrievalFilter:
    """Filters for RAG retrieval queries."""

    ticker: str | None = None
    sources: list[str] | None = None
    as_of: datetime | None = None  # PIT filter — non-negotiable


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A single retrieved chunk with relevance scores."""

    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    text: str
    score: float  # Combined RRF score
    bm25_rank: int | None = None
    vector_rank: int | None = None
    source: str = ""
    title: str | None = None
    publish_ts: datetime | None = None


@dataclass(slots=True)
class RetrievalResult:
    """Result of a hybrid retrieval query."""

    chunks: list[RetrievedChunk] = field(default_factory=list)
    query: str = ""
    k: int = 10
    method: str = "rrf"  # "rrf", "bm25_only", "vector_only"
    latency_ms: float = 0.0


class HybridRetriever:
    """Hybrid BM25 + vector retriever with RRF fusion.

    Executes both BM25 and vector searches in parallel, then combines
    results using Reciprocal Rank Fusion.
    """

    def __init__(
        self,
        session: AsyncSession,
        embedder: object | None = None,
        rrf_k: int = _RRF_K,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._rrf_k = rrf_k

    async def retrieve(
        self,
        query: str,
        k: int = 10,
        filters: RetrievalFilter | None = None,
        method: str = "rrf",
    ) -> RetrievalResult:
        """Execute a hybrid retrieval query.

        Args:
            query: Natural language query.
            k: Number of results to return.
            filters: PIT and source filters.
            method: "rrf" (default), "bm25_only", or "vector_only".

        Returns:
            RetrievalResult with ranked chunks.
        """
        import time

        start = time.perf_counter()
        filters = filters or RetrievalFilter()

        if method == "bm25_only":
            chunks = await self._bm25_search(query, k=k * 2, filters=filters)
            chunks = chunks[:k]
        elif method == "vector_only":
            chunks = await self._vector_search(query, k=k * 2, filters=filters)
            chunks = chunks[:k]
        else:
            # RRF: fetch more candidates from each, then fuse
            bm25_results = await self._bm25_search(query, k=k * 3, filters=filters)
            vector_results = await self._vector_search(query, k=k * 3, filters=filters)
            chunks = self._rrf_fuse(bm25_results, vector_results, k=k)

        latency_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "rag_retrieval",
            query_len=len(query),
            k=k,
            method=method,
            results=len(chunks),
            latency_ms=round(latency_ms, 1),
        )

        return RetrievalResult(
            chunks=chunks,
            query=query,
            k=k,
            method=method,
            latency_ms=latency_ms,
        )

    async def _bm25_search(
        self, query: str, k: int, filters: RetrievalFilter
    ) -> list[RetrievedChunk]:
        """Full-text search using Postgres ts_vector."""
        from sqlalchemy import text

        # Build the query with PIT filter
        sql_parts = [
            """
            SELECT dc.chunk_id, dc.doc_id, dc.text,
                   ts_rank_cd(to_tsvector('english', dc.text), plainto_tsquery('english', :query)) AS rank,
                   rd.source, rd.title, rd.publish_ts
            FROM document_chunk dc
            JOIN raw_document rd ON rd.doc_id = dc.doc_id
            WHERE to_tsvector('english', dc.text) @@ plainto_tsquery('english', :query)
            """
        ]
        params: dict[str, object] = {"query": query, "k": k}

        if filters.as_of:
            sql_parts.append("AND rd.available_at <= :as_of")
            params["as_of"] = filters.as_of

        if filters.ticker:
            sql_parts.append("""
                AND dc.doc_id IN (
                    SELECT DISTINCT em.chunk_id FROM entity_mention em
                    JOIN document_chunk dc2 ON dc2.chunk_id = em.chunk_id
                    WHERE em.canonical_id = :ticker
                )
            """)
            params["ticker"] = filters.ticker

        if filters.sources:
            sql_parts.append("AND rd.source = ANY(:sources)")
            params["sources"] = filters.sources

        sql_parts.append("ORDER BY rank DESC LIMIT :k")

        result = await self._session.execute(text("\n".join(sql_parts)), params)
        rows = result.fetchall()

        return [
            RetrievedChunk(
                chunk_id=row.chunk_id,
                doc_id=row.doc_id,
                text=row.text,
                score=float(row.rank),
                bm25_rank=i,
                source=row.source,
                title=row.title,
                publish_ts=row.publish_ts,
            )
            for i, row in enumerate(rows)
        ]

    async def _vector_search(
        self, query: str, k: int, filters: RetrievalFilter
    ) -> list[RetrievedChunk]:
        """Vector similarity search using pgvector."""
        from sqlalchemy import text

        # Embed the query
        if self._embedder is None:
            return []

        query_embedding = self._embedder.embed(query)  # type: ignore[union-attr]
        vector_str = "[" + ",".join(str(v) for v in query_embedding.vector) + "]"

        sql_parts = [
            """
            SELECT dc.chunk_id, dc.doc_id, dc.text,
                   1 - (dc.embedding <=> :query_vec::vector) AS similarity,
                   rd.source, rd.title, rd.publish_ts
            FROM document_chunk dc
            JOIN raw_document rd ON rd.doc_id = dc.doc_id
            WHERE dc.embedding IS NOT NULL
            """
        ]
        params: dict[str, object] = {"query_vec": vector_str, "k": k}

        if filters.as_of:
            sql_parts.append("AND rd.available_at <= :as_of")
            params["as_of"] = filters.as_of

        if filters.ticker:
            sql_parts.append("""
                AND dc.chunk_id IN (
                    SELECT em.chunk_id FROM entity_mention em
                    WHERE em.canonical_id = :ticker
                )
            """)
            params["ticker"] = filters.ticker

        if filters.sources:
            sql_parts.append("AND rd.source = ANY(:sources)")
            params["sources"] = filters.sources

        sql_parts.append("ORDER BY dc.embedding <=> :query_vec::vector LIMIT :k")

        result = await self._session.execute(text("\n".join(sql_parts)), params)
        rows = result.fetchall()

        return [
            RetrievedChunk(
                chunk_id=row.chunk_id,
                doc_id=row.doc_id,
                text=row.text,
                score=float(row.similarity),
                vector_rank=i,
                source=row.source,
                title=row.title,
                publish_ts=row.publish_ts,
            )
            for i, row in enumerate(rows)
        ]

    def _rrf_fuse(
        self,
        bm25_results: list[RetrievedChunk],
        vector_results: list[RetrievedChunk],
        k: int,
    ) -> list[RetrievedChunk]:
        """Reciprocal Rank Fusion of BM25 and vector results.

        RRF score = sum(1 / (k + rank)) across all result lists.
        """
        scores: dict[uuid.UUID, float] = {}
        chunk_map: dict[uuid.UUID, RetrievedChunk] = {}
        bm25_ranks: dict[uuid.UUID, int] = {}
        vector_ranks: dict[uuid.UUID, int] = {}

        for rank, chunk in enumerate(bm25_results):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (self._rrf_k + rank)
            chunk_map[chunk.chunk_id] = chunk
            bm25_ranks[chunk.chunk_id] = rank

        for rank, chunk in enumerate(vector_results):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (self._rrf_k + rank)
            if chunk.chunk_id not in chunk_map:
                chunk_map[chunk.chunk_id] = chunk
            vector_ranks[chunk.chunk_id] = rank

        # Sort by RRF score descending
        sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)

        results: list[RetrievedChunk] = []
        for chunk_id in sorted_ids[:k]:
            chunk = chunk_map[chunk_id]
            results.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    score=scores[chunk_id],
                    bm25_rank=bm25_ranks.get(chunk_id),
                    vector_rank=vector_ranks.get(chunk_id),
                    source=chunk.source,
                    title=chunk.title,
                    publish_ts=chunk.publish_ts,
                )
            )

        return results
