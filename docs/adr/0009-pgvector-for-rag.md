# ADR-0009 — pgvector for RAG Embeddings

**Status**: accepted
**Date**: 2026-03-10
**Decider(s)**: Sahil

## Context

The AI agentic layer (Phase 6) needs vector similarity search for RAG over
financial documents (SEC filings, news, research notes). Options:
1. Dedicated vector DB (Pinecone, Weaviate, Qdrant, Milvus)
2. pgvector extension in existing PostgreSQL

## Decision

pgvector in the existing TimescaleDB/PostgreSQL instance.

## Rationale

- **Operational simplicity:** No additional service to deploy, monitor, or pay for.
  The platform already runs PostgreSQL; pgvector is a `CREATE EXTENSION`.
- **Scale fit:** The corpus is ~100k documents max (SEC filings for 150 symbols × 10 years).
  pgvector handles millions of vectors with HNSW indexes comfortably.
- **Hybrid search:** Combine vector similarity with SQL filters (date range, ticker, document type)
  in a single query. Dedicated vector DBs require a separate metadata filter step.
- **Cost:** $0 additional infrastructure. Dedicated vector DBs start at $25–100/mo.
- **Transactional consistency:** Embeddings and metadata are in the same transaction.
  No eventual consistency between a vector DB and the relational store.

## Consequences

- HNSW index build time is acceptable for batch ingestion (not real-time).
- Embedding dimension limited to 2000 (sufficient for all current models).
- If corpus grows to 10M+ documents, revisit with a dedicated solution.
- Hybrid BM25 + vector search implemented via `ts_rank` + cosine similarity fusion.

## Alternatives considered

- **Pinecone** — managed, fast, but adds cost and a network hop.
- **Qdrant** — excellent performance but another service to operate.
- **ChromaDB** — too simple for production; no ACID guarantees.
- **Elasticsearch** — could work but heavier than needed for this scale.
