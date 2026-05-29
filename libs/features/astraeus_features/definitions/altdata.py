"""Alt-data feature definitions for Phase 5.

Sentiment, topic exposure, and embedding features materialized from the
NLP pipeline output. All features use `available_at` for PIT correctness.

These features are inputs to the Phase 7 ensemble — they are NOT standalone
alpha signals. Naive sentiment trading lost its edge by 2018; the value is
in combinations (sentiment × earnings surprise × short interest).
"""

from __future__ import annotations

from datetime import timedelta

from astraeus_features.dsl import Entity, FeatureDefinition, sql_transform

# --- Daily Sentiment Score (FinBERT) ---

sentiment_daily = FeatureDefinition(
    name="sentiment_daily",
    group="altdata",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description=(
        "Daily average FinBERT sentiment score per ticker. "
        "Range [-1, 1]. Aggregated from all documents mentioning the ticker "
        "with available_at on that day."
    ),
    dependencies=["sentiment_score", "raw_document"],
    freshness_sla=timedelta(hours=6),
    knowledge_lag=timedelta(hours=1),
    materialization="incremental",
    transform=sql_transform("""
        SELECT
            ss.ticker AS symbol,
            date_trunc('day', ss.available_at) AS event_ts,
            max(ss.available_at) AS knowledge_ts,
            avg(ss.score) AS value,
            1 AS value_version
        FROM sentiment_score ss
        WHERE ss.model = 'finbert_v1.0'
          AND ss.available_at <= :as_of
        GROUP BY ss.ticker, date_trunc('day', ss.available_at)
    """),
    owner="quant-research",
    tags=["altdata", "sentiment", "finbert"],
)

# --- Sentiment Document Count ---

sentiment_doc_count = FeatureDefinition(
    name="sentiment_doc_count",
    group="altdata",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description=(
        "Daily count of documents with sentiment scores per ticker. "
        "Proxy for attention/coverage intensity."
    ),
    dependencies=["sentiment_score"],
    freshness_sla=timedelta(hours=6),
    knowledge_lag=timedelta(hours=1),
    materialization="incremental",
    transform=sql_transform("""
        SELECT
            ss.ticker AS symbol,
            date_trunc('day', ss.available_at) AS event_ts,
            max(ss.available_at) AS knowledge_ts,
            count(DISTINCT ss.doc_id)::numeric AS value,
            1 AS value_version
        FROM sentiment_score ss
        WHERE ss.model = 'finbert_v1.0'
          AND ss.available_at <= :as_of
        GROUP BY ss.ticker, date_trunc('day', ss.available_at)
    """),
    owner="quant-research",
    tags=["altdata", "sentiment", "coverage"],
)

# --- Sentiment 5-day Moving Average ---

sentiment_ma5 = FeatureDefinition(
    name="sentiment_ma5",
    group="altdata",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description=(
        "5-day moving average of daily sentiment. Smooths noise; "
        "useful for detecting sustained sentiment shifts."
    ),
    dependencies=["feature_altdata_sentiment_daily"],
    freshness_sla=timedelta(hours=6),
    knowledge_lag=timedelta(hours=1),
    materialization="incremental",
    transform=sql_transform("""
        WITH daily AS (
            SELECT
                symbol,
                event_ts,
                knowledge_ts,
                value AS daily_score
            FROM feature_altdata_sentiment_daily
            WHERE event_ts <= :as_of
              AND knowledge_ts <= :as_of
        )
        SELECT
            symbol,
            event_ts,
            knowledge_ts,
            avg(daily_score) OVER (
                PARTITION BY symbol ORDER BY event_ts
                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
            ) AS value,
            1 AS value_version
        FROM daily
    """),
    owner="quant-research",
    tags=["altdata", "sentiment", "smoothed"],
)

# --- Sentiment Dispersion (std dev across documents) ---

sentiment_dispersion = FeatureDefinition(
    name="sentiment_dispersion",
    group="altdata",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description=(
        "Daily standard deviation of sentiment scores across documents. "
        "High dispersion = disagreement in coverage; potential regime change."
    ),
    dependencies=["sentiment_score"],
    freshness_sla=timedelta(hours=6),
    knowledge_lag=timedelta(hours=1),
    materialization="incremental",
    transform=sql_transform("""
        SELECT
            ss.ticker AS symbol,
            date_trunc('day', ss.available_at) AS event_ts,
            max(ss.available_at) AS knowledge_ts,
            stddev(ss.score) AS value,
            1 AS value_version
        FROM sentiment_score ss
        WHERE ss.model = 'finbert_v1.0'
          AND ss.available_at <= :as_of
        GROUP BY ss.ticker, date_trunc('day', ss.available_at)
        HAVING count(*) >= 3
    """),
    owner="quant-research",
    tags=["altdata", "sentiment", "dispersion"],
)

# --- Topic Exposure (dominant topic probability per ticker per day) ---

topic_exposure = FeatureDefinition(
    name="topic_exposure",
    group="altdata",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description=(
        "Average topic assignment probability for the dominant topic "
        "across documents mentioning a ticker on a given day. "
        "Captures narrative concentration."
    ),
    dependencies=["topic_assignment", "entity_mention", "document_chunk"],
    freshness_sla=timedelta(hours=24),
    knowledge_lag=timedelta(hours=2),
    materialization="incremental",
    transform=sql_transform("""
        WITH ticker_topics AS (
            SELECT
                em.canonical_id AS ticker,
                date_trunc('day', rd.available_at) AS day,
                rd.available_at,
                ta.topic_id,
                ta.probability
            FROM topic_assignment ta
            JOIN document_chunk dc ON dc.chunk_id = ta.chunk_id
            JOIN entity_mention em ON em.chunk_id = ta.chunk_id
            JOIN raw_document rd ON rd.doc_id = dc.doc_id
            WHERE em.canonical_id IS NOT NULL
              AND rd.available_at <= :as_of
        )
        SELECT
            ticker AS symbol,
            day AS event_ts,
            max(available_at) AS knowledge_ts,
            avg(probability) AS value,
            1 AS value_version
        FROM ticker_topics
        GROUP BY ticker, day
    """),
    owner="quant-research",
    tags=["altdata", "topic", "exposure"],
)

# --- Embedding Similarity to Market (cosine sim of ticker embedding to SPY) ---

embedding_market_sim = FeatureDefinition(
    name="embedding_market_sim",
    group="altdata",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description=(
        "Daily cosine similarity between a ticker's mean document embedding "
        "and SPY's mean document embedding. Captures narrative correlation "
        "with the broad market."
    ),
    dependencies=["document_chunk", "entity_mention", "raw_document"],
    freshness_sla=timedelta(hours=12),
    knowledge_lag=timedelta(hours=2),
    materialization="incremental",
    transform=sql_transform("""
        WITH ticker_embeddings AS (
            SELECT
                em.canonical_id AS ticker,
                date_trunc('day', rd.available_at) AS day,
                rd.available_at,
                dc.embedding
            FROM document_chunk dc
            JOIN entity_mention em ON em.chunk_id = dc.chunk_id
            JOIN raw_document rd ON rd.doc_id = dc.doc_id
            WHERE em.canonical_id IS NOT NULL
              AND dc.embedding IS NOT NULL
              AND rd.available_at <= :as_of
        ),
        daily_avg AS (
            SELECT
                ticker,
                day,
                max(available_at) AS knowledge_ts,
                avg(embedding) AS avg_embedding
            FROM ticker_embeddings
            GROUP BY ticker, day
        )
        SELECT
            ticker AS symbol,
            day AS event_ts,
            knowledge_ts,
            1 - (avg_embedding <=> (
                SELECT avg(embedding)
                FROM ticker_embeddings
                WHERE ticker = 'SPY' AND day = daily_avg.day
            )) AS value,
            1 AS value_version
        FROM daily_avg
        WHERE ticker != 'SPY'
    """),
    owner="quant-research",
    tags=["altdata", "embedding", "market-correlation"],
)
