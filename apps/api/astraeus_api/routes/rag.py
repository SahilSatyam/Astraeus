"""RAG retrieval API routes.

Endpoints:
- POST /rag/retrieve        — hybrid search (BM25 + vector + RRF)
- GET  /rag/chunks/{chunk_id} — get a single chunk by ID
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from astraeus_api.deps import get_db_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/rag", tags=["rag"])


# --- Request/Response schemas ---


class RetrieveFilters(BaseModel):
    ticker: str | None = None
    source: list[str] | None = None
    as_of: datetime | None = Field(default=None, description="PIT filter — non-negotiable")


class RetrieveRequest(BaseModel):
    query: str = Field(..., max_length=500, description="Natural language query")
    k: int = Field(default=12, ge=1, le=50, description="Number of results")
    filters: RetrieveFilters | None = None
    rerank: str = Field(default="rrf", description="Reranking method: rrf, bm25_only, vector_only")


class ChunkResult(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    score: float
    bm25_rank: int | None = None
    vector_rank: int | None = None
    source: str = ""
    title: str | None = None
    publish_ts: str | None = None


class RetrieveResponse(BaseModel):
    chunks: list[ChunkResult]
    query: str
    k: int
    method: str
    latency_ms: float


class ChunkDetail(BaseModel):
    chunk_id: str
    doc_id: str
    chunk_idx: int
    text: str
    token_count: int
    source: str
    title: str | None = None
    publish_ts: str | None = None


# --- Endpoints ---


@router.post("/retrieve", response_model=RetrieveResponse, summary="Hybrid RAG retrieval")
async def retrieve(
    request: RetrieveRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RetrieveResponse:
    """Execute a hybrid BM25 + vector retrieval with RRF fusion.

    The `as_of` filter ensures PIT correctness — no future documents leak.
    """
    from astraeus_rag.retriever import HybridRetriever, RetrievalFilter

    filters = RetrievalFilter(
        ticker=request.filters.ticker if request.filters else None,
        sources=request.filters.source if request.filters else None,
        as_of=request.filters.as_of if request.filters else None,
    )

    retriever = HybridRetriever(session=session)
    result = await retriever.retrieve(
        query=request.query,
        k=request.k,
        filters=filters,
        method=request.rerank,
    )

    return RetrieveResponse(
        chunks=[
            ChunkResult(
                chunk_id=str(c.chunk_id),
                doc_id=str(c.doc_id),
                text=c.text,
                score=c.score,
                bm25_rank=c.bm25_rank,
                vector_rank=c.vector_rank,
                source=c.source,
                title=c.title,
                publish_ts=c.publish_ts.isoformat() if c.publish_ts else None,
            )
            for c in result.chunks
        ],
        query=result.query,
        k=result.k,
        method=result.method,
        latency_ms=round(result.latency_ms, 1),
    )


@router.get("/chunks/{chunk_id}", response_model=ChunkDetail, summary="Get chunk by ID")
async def get_chunk(
    chunk_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChunkDetail:
    """Retrieve a single document chunk by its ID."""
    import uuid as uuid_mod

    from astraeus_rag.chunk_store import get_chunk_by_id

    try:
        cid = uuid_mod.UUID(chunk_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid chunk_id format") from err

    chunk = await get_chunk_by_id(session, cid)
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")

    return ChunkDetail(
        chunk_id=str(chunk["chunk_id"]),
        doc_id=str(chunk["doc_id"]),
        chunk_idx=chunk["chunk_idx"],  # type: ignore[arg-type]
        text=chunk["text"],  # type: ignore[arg-type]
        token_count=chunk["token_count"],  # type: ignore[arg-type]
        source=chunk["source"],  # type: ignore[arg-type]
        title=chunk.get("title"),  # type: ignore[arg-type]
        publish_ts=chunk["publish_ts"].isoformat() if chunk.get("publish_ts") else None,
    )
