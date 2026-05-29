"""phase5: alternative data, NLP pipeline, and RAG corpus tables

Revision ID: 202605291600
Revises: 202605291500
Create Date: 2026-05-29 16:00:00+00:00

Creates:
- raw_document: immutable document metadata (body in MinIO)
- document_chunk: token-aware text chunks with pgvector embeddings
- entity_mention: NER-detected entity spans
- sentiment_score: per-doc per-ticker FinBERT sentiment
- topic_assignment: BERTopic topic assignments per chunk
- topic_model_run: BERTopic refit metadata

Requires pgvector extension (CREATE EXTENSION vector).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605291600"
down_revision: str = "202605291500"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # --- raw_document ---
    op.create_table(
        "raw_document",
        sa.Column("doc_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_doc_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body_uri", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("language", sa.String(8), nullable=True),
        sa.Column("event_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingest_ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False,
                  comment="max(publish_ts, ingest_ts) — the PIT join column"),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.UniqueConstraint("source", "source_doc_id", name="uq_raw_document_source_id"),
    )
    op.create_index("ix_raw_document_publish_ts", "raw_document", ["publish_ts"])
    op.create_index("ix_raw_document_source", "raw_document", ["source"])
    op.create_index("ix_raw_document_available_at", "raw_document", ["available_at"])

    # --- document_chunk ---
    # Use raw SQL for the VECTOR column type (not natively supported by SA)
    op.execute(sa.text("""
        CREATE TABLE document_chunk (
            chunk_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id          UUID NOT NULL REFERENCES raw_document(doc_id),
            chunk_idx       INT NOT NULL,
            text            TEXT NOT NULL,
            token_count     INT NOT NULL,
            embedding       VECTOR(384),
            UNIQUE (doc_id, chunk_idx)
        )
    """))
    op.create_index("ix_document_chunk_doc_id", "document_chunk", ["doc_id"])
    op.execute(sa.text(
        "CREATE INDEX ix_document_chunk_embedding ON document_chunk "
        "USING hnsw (embedding vector_cosine_ops)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_document_chunk_fts ON document_chunk "
        "USING gin (to_tsvector('english', text))"
    ))

    # --- entity_mention ---
    op.create_table(
        "entity_mention",
        sa.Column("mention_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("chunk_id", UUID(as_uuid=True), nullable=False),
        sa.Column("surface_form", sa.Text(), nullable=False),
        sa.Column("entity_kind", sa.String(32), nullable=False),
        sa.Column("canonical_id", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunk.chunk_id"], name="fk_entity_mention_chunk"),
    )
    op.create_index("ix_entity_mention_canonical", "entity_mention", ["canonical_id"])
    op.create_index("ix_entity_mention_chunk", "entity_mention", ["chunk_id"])

    # --- sentiment_score ---
    op.create_table(
        "sentiment_score",
        sa.Column("doc_id", UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("label", sa.String(8), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("doc_id", "ticker", "model", name="pk_sentiment_score"),
    )
    op.create_index("ix_sentiment_score_ticker_available", "sentiment_score", ["ticker", "available_at"])

    # --- topic_model_run ---
    op.create_table(
        "topic_model_run",
        sa.Column("model_run_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("fit_window_from", sa.Date(), nullable=False),
        sa.Column("fit_window_to", sa.Date(), nullable=False),
        sa.Column("n_topics", sa.Integer(), nullable=True),
        sa.Column("topic_summary", JSONB(), nullable=True),
        sa.Column("fit_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- topic_assignment ---
    op.create_table(
        "topic_assignment",
        sa.Column("chunk_id", UUID(as_uuid=True), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("model_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("chunk_id", "topic_id", "model_run_id", name="pk_topic_assignment"),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunk.chunk_id"], name="fk_topic_assignment_chunk"),
        sa.ForeignKeyConstraint(["model_run_id"], ["topic_model_run.model_run_id"], name="fk_topic_assignment_run"),
    )


def downgrade() -> None:
    op.drop_table("topic_assignment")
    op.drop_table("topic_model_run")
    op.drop_table("sentiment_score")
    op.drop_table("entity_mention")
    op.execute(sa.text("DROP TABLE IF EXISTS document_chunk CASCADE"))
    op.drop_table("raw_document")
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector"))
