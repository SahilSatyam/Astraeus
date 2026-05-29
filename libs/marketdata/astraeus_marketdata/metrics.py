"""Market data ingestion metrics (Prometheus).

Exposes the Phase 1 observability signals:
- md_ingest_lag_seconds: time between data timestamp and ingestion
- md_dlq_depth: number of unresolved DLQ entries
- md_payload_hash_collisions_total: should always be zero
- md_gap_open_total: number of unresolved data gaps
- md_adjust_worker_lag_seconds: time since last adjustment run
- md_outbox_unpublished: count of outbox rows awaiting relay
- md_ingest_rows_total: total rows ingested (counter)
- md_ingest_runs_total: total ingestion runs (counter)
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


def register_marketdata_metrics(registry: CollectorRegistry) -> dict[str, Counter | Gauge | Histogram]:
    """Register all Phase 1 market data metrics and return them as a dict."""

    metrics: dict[str, Counter | Gauge | Histogram] = {}

    metrics["ingest_lag"] = Gauge(
        "md_ingest_lag_seconds",
        "Lag between data timestamp and ingestion time.",
        labelnames=("source", "topic"),
        registry=registry,
    )

    metrics["dlq_depth"] = Gauge(
        "md_dlq_depth",
        "Number of unresolved DLQ entries.",
        labelnames=("source",),
        registry=registry,
    )

    metrics["hash_collisions"] = Counter(
        "md_payload_hash_collisions_total",
        "Payload hash collisions detected (should be zero).",
        labelnames=("source",),
        registry=registry,
    )

    metrics["gap_open"] = Gauge(
        "md_gap_open_total",
        "Number of unresolved data gaps.",
        labelnames=("symbol_class",),
        registry=registry,
    )

    metrics["adjust_lag"] = Gauge(
        "md_adjust_worker_lag_seconds",
        "Seconds since last adjustment worker run.",
        registry=registry,
    )

    metrics["outbox_unpublished"] = Gauge(
        "md_outbox_unpublished",
        "Count of outbox rows awaiting relay, bucketed by age.",
        labelnames=("age_bucket",),
        registry=registry,
    )

    metrics["calendar_cache_hit"] = Gauge(
        "md_calendar_cache_hit_ratio",
        "Calendar cache hit ratio.",
        registry=registry,
    )

    metrics["ingest_rows"] = Counter(
        "md_ingest_rows_total",
        "Total rows ingested across all runs.",
        labelnames=("source", "resolution", "status"),
        registry=registry,
    )

    metrics["ingest_runs"] = Counter(
        "md_ingest_runs_total",
        "Total ingestion runs executed.",
        labelnames=("source", "status"),
        registry=registry,
    )

    metrics["ingest_duration"] = Histogram(
        "md_ingest_duration_seconds",
        "Duration of ingestion runs.",
        labelnames=("source",),
        buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
        registry=registry,
    )

    metrics["streaming_bars"] = Counter(
        "md_streaming_bars_total",
        "Total bars received via streaming.",
        labelnames=("symbol",),
        registry=registry,
    )

    return metrics
