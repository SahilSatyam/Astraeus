"""Alt-data event contracts for Phase 5.

Defines Pydantic models for events flowing through the alt-data pipeline:
- DocumentIngested: emitted when a new document is stored
- DocumentProcessed: emitted when NLP pipeline completes on a document
- SentimentComputed: emitted when sentiment is scored for a document

Topic: altdata.document.ingested.v1
Topic: altdata.document.processed.v1
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

ALTDATA_SCHEMA_VERSION = 1


class DocumentIngestedEvent(BaseModel):
    """Emitted when a new document is ingested and stored."""

    schema_version: int = Field(default=ALTDATA_SCHEMA_VERSION)
    doc_id: str = Field(..., description="UUID of the document")
    source: str = Field(..., description="Source identifier (reddit, rss, edgar, etc.)")
    source_doc_id: str = Field(..., description="Vendor-side document ID")
    title: str | None = Field(default=None)
    body_uri: str = Field(..., description="MinIO URI for the document body")
    publish_ts: datetime = Field(..., description="When the document was published")
    event_ts: datetime | None = Field(default=None, description="When the event occurred")
    run_id: str = Field(..., description="Ingestion run UUID")


class DocumentProcessedEvent(BaseModel):
    """Emitted when the NLP pipeline finishes processing a document."""

    schema_version: int = Field(default=ALTDATA_SCHEMA_VERSION)
    doc_id: str = Field(..., description="UUID of the document")
    n_chunks: int = Field(..., description="Number of chunks created")
    n_entities: int = Field(..., description="Number of entity mentions found")
    tickers_found: list[str] = Field(default_factory=list, description="Canonical tickers linked")
    sentiment_computed: bool = Field(default=False)
    embeddings_computed: bool = Field(default=False)
    processing_ms: float = Field(default=0.0, description="Total processing time in ms")


class SentimentFeatureEvent(BaseModel):
    """Emitted when sentiment is materialized as a feature."""

    schema_version: int = Field(default=ALTDATA_SCHEMA_VERSION)
    ticker: str = Field(..., description="Ticker symbol")
    date: str = Field(..., description="Feature date (YYYY-MM-DD)")
    model: str = Field(default="finbert_v1.0")
    avg_score: float = Field(..., description="Average sentiment score for the day")
    n_documents: int = Field(..., description="Number of documents contributing")
    available_at: datetime = Field(..., description="PIT availability timestamp")
