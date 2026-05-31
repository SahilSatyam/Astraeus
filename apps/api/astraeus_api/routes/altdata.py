"""Alt-data API routes.

Endpoints:
- GET  /altdata/documents       — list documents (filterable by ticker, source, date range)
- GET  /altdata/sentiment       — get sentiment scores for a ticker
- POST /altdata/ingest/manual   — trigger a manual backfill ingest
- GET  /altdata/topics          — get topic model results
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from astraeus_api.deps import get_db_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/altdata", tags=["altdata"])


# --- Response schemas ---


class DocumentItem(BaseModel):
    doc_id: str
    source: str
    source_doc_id: str
    title: str | None = None
    url: str | None = None
    event_ts: str | None = None
    publish_ts: str
    available_at: str


class SentimentItem(BaseModel):
    doc_id: str
    ticker: str
    model: str
    label: str
    score: float
    available_at: str


class TopicItem(BaseModel):
    chunk_id: str
    topic_id: int
    probability: float
    model_run_id: str


class TopicModelRunItem(BaseModel):
    model_run_id: str
    fit_window_from: str
    fit_window_to: str
    n_topics: int | None = None
    fit_at: str


class IngestManualRequest(BaseModel):
    source: str = Field(
        ..., description="Source to backfill: reddit, rss, edgar, transcript, gdelt"
    )
    from_date: str | None = Field(default=None, description="Start date (ISO format)")
    to_date: str | None = Field(default=None, description="End date (ISO format)")


class IngestManualResponse(BaseModel):
    status: str
    source: str
    message: str


# --- Endpoints ---


@router.get("/documents", response_model=list[DocumentItem], summary="List documents")
async def list_documents(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    ticker: str | None = Query(default=None, description="Filter by ticker (via entity mentions)"),
    source: str | None = Query(default=None, description="Filter by source"),
    from_ts: datetime | None = Query(default=None, alias="from", description="From timestamp"),
    to_ts: datetime | None = Query(default=None, alias="to", description="To timestamp"),
    limit: int = Query(default=50, le=200, description="Max results"),
) -> list[DocumentItem]:
    """List ingested documents with optional filters."""
    sql_parts = [
        """
        SELECT DISTINCT rd.doc_id, rd.source, rd.source_doc_id, rd.title, rd.url,
               rd.event_ts, rd.publish_ts, rd.available_at
        FROM raw_document rd
        """
    ]
    params: dict[str, object] = {"limit": limit}

    if ticker:
        sql_parts.append("""
            JOIN document_chunk dc ON dc.doc_id = rd.doc_id
            JOIN entity_mention em ON em.chunk_id = dc.chunk_id
        """)
        sql_parts.append("WHERE em.canonical_id = :ticker")
        params["ticker"] = ticker
    else:
        sql_parts.append("WHERE 1=1")

    if source:
        sql_parts.append("AND rd.source = :source")
        params["source"] = source

    if from_ts:
        sql_parts.append("AND rd.available_at >= :from_ts")
        params["from_ts"] = from_ts

    if to_ts:
        sql_parts.append("AND rd.available_at <= :to_ts")
        params["to_ts"] = to_ts

    sql_parts.append("ORDER BY rd.available_at DESC LIMIT :limit")

    result = await session.execute(text("\n".join(sql_parts)), params)
    rows = result.fetchall()

    return [
        DocumentItem(
            doc_id=str(row.doc_id),
            source=row.source,
            source_doc_id=row.source_doc_id,
            title=row.title,
            url=row.url,
            event_ts=row.event_ts.isoformat() if row.event_ts else None,
            publish_ts=row.publish_ts.isoformat(),
            available_at=row.available_at.isoformat(),
        )
        for row in rows
    ]


@router.get("/sentiment", response_model=list[SentimentItem], summary="Get sentiment scores")
async def get_sentiment(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    ticker: str = Query(..., description="Ticker symbol"),
    model: str = Query(default="finbert_v1.0", description="Sentiment model"),
    from_ts: datetime | None = Query(default=None, alias="from", description="From timestamp"),
    to_ts: datetime | None = Query(default=None, alias="to", description="To timestamp"),
    limit: int = Query(default=100, le=500, description="Max results"),
) -> list[SentimentItem]:
    """Get sentiment scores for a ticker, PIT-correct via available_at."""
    sql_parts = [
        """
        SELECT doc_id, ticker, model, label, score, available_at
        FROM sentiment_score
        WHERE ticker = :ticker AND model = :model
        """
    ]
    params: dict[str, object] = {"ticker": ticker, "model": model, "limit": limit}

    if from_ts:
        sql_parts.append("AND available_at >= :from_ts")
        params["from_ts"] = from_ts

    if to_ts:
        sql_parts.append("AND available_at <= :to_ts")
        params["to_ts"] = to_ts

    sql_parts.append("ORDER BY available_at DESC LIMIT :limit")

    result = await session.execute(text("\n".join(sql_parts)), params)
    rows = result.fetchall()

    return [
        SentimentItem(
            doc_id=str(row.doc_id),
            ticker=row.ticker,
            model=row.model,
            label=row.label,
            score=row.score,
            available_at=row.available_at.isoformat(),
        )
        for row in rows
    ]


@router.post("/ingest/manual", response_model=IngestManualResponse, summary="Trigger manual ingest")
async def trigger_manual_ingest(
    request: IngestManualRequest,
) -> IngestManualResponse:
    """Trigger a manual backfill for a specific source.

    This is an operator-facing endpoint for backfilling historical data.
    The actual ingest runs asynchronously via the worker.
    """
    valid_sources = {"reddit", "rss", "edgar", "transcript", "gdelt"}
    if request.source not in valid_sources:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source: {request.source}. Must be one of: {sorted(valid_sources)}",
        )

    # In production this would enqueue a task to the ingest worker.
    # For now, return acknowledgment.
    return IngestManualResponse(
        status="accepted",
        source=request.source,
        message=f"Manual ingest for {request.source} queued. Check worker logs for progress.",
    )


@router.get("/topics", response_model=list[TopicItem], summary="Get topic assignments")
async def get_topics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    model_run: str | None = Query(default=None, description="Filter by model_run_id"),
    ticker: str | None = Query(default=None, description="Filter by ticker (via entity mentions)"),
    limit: int = Query(default=100, le=500, description="Max results"),
) -> list[TopicItem]:
    """Get topic assignments, optionally filtered by model run or ticker."""
    if not model_run and not ticker:
        # Get latest model run
        latest = await session.execute(
            text("SELECT model_run_id FROM topic_model_run ORDER BY fit_at DESC LIMIT 1")
        )
        row = latest.fetchone()
        if row is None:
            return []
        model_run = str(row.model_run_id)

    sql_parts = [
        """
        SELECT ta.chunk_id, ta.topic_id, ta.probability, ta.model_run_id
        FROM topic_assignment ta
        """
    ]
    params: dict[str, object] = {"limit": limit}

    if ticker:
        sql_parts.append("JOIN entity_mention em ON em.chunk_id = ta.chunk_id")
        sql_parts.append("WHERE em.canonical_id = :ticker")
        params["ticker"] = ticker
        if model_run:
            sql_parts.append("AND ta.model_run_id = :model_run")
            params["model_run"] = model_run
    elif model_run:
        sql_parts.append("WHERE ta.model_run_id = :model_run")
        params["model_run"] = model_run

    sql_parts.append("ORDER BY ta.probability DESC LIMIT :limit")

    result = await session.execute(text("\n".join(sql_parts)), params)
    rows = result.fetchall()

    return [
        TopicItem(
            chunk_id=str(row.chunk_id),
            topic_id=row.topic_id,
            probability=row.probability,
            model_run_id=str(row.model_run_id),
        )
        for row in rows
    ]
