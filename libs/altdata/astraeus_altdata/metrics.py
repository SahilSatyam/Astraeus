"""Observability metrics for the alt-data pipeline.

Prometheus metrics exposed via the standard /metrics endpoint.
All metrics follow the naming convention: altdata_{domain}_{metric_type}.

Metrics:
- altdata_docs_ingested_total{source} — counter
- altdata_pipeline_lag_seconds{stage} — histogram
- nlp_inference_latency_ms{model} — histogram
- entity_link_confidence — histogram (distribution)
- sentiment_score_distribution{ticker_bucket} — histogram
- rag_query_latency_ms — histogram
- topic_model_drift_score — gauge
- pit_violation_alerts_total — counter (must stay 0)
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger("astraeus.altdata.metrics")

try:
    from prometheus_client import Counter, Gauge, Histogram

    # --- Ingestion metrics ---
    DOCS_INGESTED = Counter(
        "altdata_docs_ingested_total",
        "Total documents ingested by source",
        ["source"],
    )

    DOCS_DEDUPLICATED = Counter(
        "altdata_docs_deduplicated_total",
        "Total documents skipped due to deduplication",
        ["source"],
    )

    DOCS_FAILED = Counter(
        "altdata_docs_failed_total",
        "Total documents that failed ingestion",
        ["source", "error_type"],
    )

    # --- Pipeline lag ---
    PIPELINE_LAG = Histogram(
        "altdata_pipeline_lag_seconds",
        "Time from document publish to pipeline completion",
        ["stage"],
        buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
    )

    # --- NLP inference ---
    NLP_LATENCY = Histogram(
        "nlp_inference_latency_ms",
        "NLP model inference latency in milliseconds",
        ["model"],
        buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
    )

    # --- Entity linking ---
    ENTITY_LINK_CONFIDENCE = Histogram(
        "entity_link_confidence",
        "Distribution of entity linking confidence scores",
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0],
    )

    ENTITIES_LINKED = Counter(
        "altdata_entities_linked_total",
        "Total entity mentions successfully linked",
        ["entity_kind"],
    )

    # --- Sentiment ---
    SENTIMENT_SCORE = Histogram(
        "sentiment_score_distribution",
        "Distribution of sentiment scores",
        ["source"],
        buckets=[-1.0, -0.8, -0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    )

    # --- RAG retrieval ---
    RAG_QUERY_LATENCY = Histogram(
        "rag_query_latency_ms",
        "RAG retrieval query latency in milliseconds",
        ["method"],
        buckets=[10, 25, 50, 100, 250, 500, 1000, 2500],
    )

    RAG_RESULTS_COUNT = Histogram(
        "rag_results_count",
        "Number of results returned per RAG query",
        buckets=[0, 1, 3, 5, 10, 15, 20, 50],
    )

    # --- Topic modeling ---
    TOPIC_DRIFT_SCORE = Gauge(
        "topic_model_drift_score",
        "Topic vocabulary drift between consecutive refits (0=stable, 1=complete change)",
    )

    TOPIC_REFIT_DURATION = Histogram(
        "topic_refit_duration_seconds",
        "Duration of topic model refit",
        buckets=[10, 30, 60, 120, 300, 600, 1800],
    )

    # --- PIT violations (must stay 0) ---
    PIT_VIOLATIONS = Counter(
        "pit_violation_alerts_total",
        "PIT violations detected (MUST stay at 0)",
        ["source"],
    )

    _METRICS_AVAILABLE = True

except ImportError:
    _METRICS_AVAILABLE = False
    logger.warning("prometheus_client_not_installed", msg="Metrics disabled")


# --- Helper functions for recording metrics ---


def record_doc_ingested(source: str) -> None:
    """Record a successful document ingestion."""
    if _METRICS_AVAILABLE:
        DOCS_INGESTED.labels(source=source).inc()


def record_doc_deduplicated(source: str) -> None:
    """Record a deduplicated document."""
    if _METRICS_AVAILABLE:
        DOCS_DEDUPLICATED.labels(source=source).inc()


def record_doc_failed(source: str, error_type: str) -> None:
    """Record a failed document ingestion."""
    if _METRICS_AVAILABLE:
        DOCS_FAILED.labels(source=source, error_type=error_type).inc()


def record_pipeline_lag(stage: str, seconds: float) -> None:
    """Record pipeline processing lag."""
    if _METRICS_AVAILABLE:
        PIPELINE_LAG.labels(stage=stage).observe(seconds)


def record_nlp_latency(model: str, ms: float) -> None:
    """Record NLP inference latency."""
    if _METRICS_AVAILABLE:
        NLP_LATENCY.labels(model=model).observe(ms)


def record_entity_confidence(confidence: float) -> None:
    """Record entity linking confidence score."""
    if _METRICS_AVAILABLE:
        ENTITY_LINK_CONFIDENCE.observe(confidence)


def record_entity_linked(entity_kind: str) -> None:
    """Record a successfully linked entity."""
    if _METRICS_AVAILABLE:
        ENTITIES_LINKED.labels(entity_kind=entity_kind).inc()


def record_sentiment_score(source: str, score: float) -> None:
    """Record a sentiment score."""
    if _METRICS_AVAILABLE:
        SENTIMENT_SCORE.labels(source=source).observe(score)


def record_rag_query(method: str, latency_ms: float, n_results: int) -> None:
    """Record a RAG retrieval query."""
    if _METRICS_AVAILABLE:
        RAG_QUERY_LATENCY.labels(method=method).observe(latency_ms)
        RAG_RESULTS_COUNT.observe(n_results)


def record_topic_drift(drift_score: float) -> None:
    """Record topic model drift score."""
    if _METRICS_AVAILABLE:
        TOPIC_DRIFT_SCORE.set(drift_score)


def record_pit_violation(source: str) -> None:
    """Record a PIT violation (should NEVER be called in production)."""
    if _METRICS_AVAILABLE:
        PIT_VIOLATIONS.labels(source=source).inc()
    logger.critical("pit_violation_detected", source=source)
