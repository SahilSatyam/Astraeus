"""SQLAlchemy ORM models for Phase 5 alt-data tables.

Tables:
- raw_document: Immutable document metadata (body stored in MinIO)
- document_chunk: Token-aware text chunks with embeddings
- entity_mention: NER-detected entity spans linked to chunks
- sentiment_score: Per-doc per-ticker sentiment from FinBERT
- topic_assignment: BERTopic topic assignments per chunk
- topic_model_run: BERTopic refit metadata
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from astraeus_db.base import Base
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class RawDocumentRow(Base):
    """Raw document metadata. Body stored in MinIO, referenced by body_uri."""

    __tablename__ = "raw_document"
    __table_args__ = (
        UniqueConstraint("source", "source_doc_id", name="uq_raw_document_source_id"),
        Index("ix_raw_document_publish_ts", "publish_ts"),
        Index("ix_raw_document_source", "source"),
    )

    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_doc_id: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_uri: Mapped[str] = mapped_column(Text, nullable=False)
    body_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    event_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingest_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="max(publish_ts, ingest_ts) — the PIT join column",
    )
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class DocumentChunkRow(Base):
    """Token-aware text chunk with embedding vector."""

    __tablename__ = "document_chunk"
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_idx", name="uq_document_chunk_doc_idx"),
        Index("ix_document_chunk_doc_id", "doc_id"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chunk_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # embedding stored as VECTOR(384) — created via raw SQL in migration
    # (SQLAlchemy doesn't natively support pgvector type)


class EntityMentionRow(Base):
    """NER-detected entity mention linked to a chunk."""

    __tablename__ = "entity_mention"
    __table_args__ = (
        Index("ix_entity_mention_canonical", "canonical_id"),
        Index("ix_entity_mention_chunk", "chunk_id"),
    )

    mention_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    surface_form: Mapped[str] = mapped_column(Text, nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SentimentScoreRow(Base):
    """Per-document per-ticker sentiment score from FinBERT."""

    __tablename__ = "sentiment_score"
    __table_args__ = (Index("ix_sentiment_score_ticker_available", "ticker", "available_at"),)

    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(8), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TopicAssignmentRow(Base):
    """BERTopic topic assignment for a chunk."""

    __tablename__ = "topic_assignment"

    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    topic_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    probability: Mapped[float] = mapped_column(Float, nullable=False)


class TopicModelRunRow(Base):
    """Metadata for a BERTopic refit run."""

    __tablename__ = "topic_model_run"

    model_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fit_window_from: Mapped[date] = mapped_column(Date, nullable=False)
    fit_window_to: Mapped[date] = mapped_column(Date, nullable=False)
    n_topics: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topic_summary: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    fit_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
