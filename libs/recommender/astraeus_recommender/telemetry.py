"""Prometheus metrics for the recommendation pipeline.

Naming convention: astraeus_reco_<noun>_<unit>
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


def register_metrics(registry: CollectorRegistry) -> RecommenderMetrics:
    """Register all recommender metrics on the given registry."""
    return RecommenderMetrics(registry)


class RecommenderMetrics:
    """Prometheus metrics for the recommendation engine."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.run_duration = Histogram(
            "astraeus_reco_run_duration_seconds",
            "Pipeline run duration by stage.",
            labelnames=("stage",),
            buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
            registry=registry,
        )

        self.stage_failure_total = Counter(
            "astraeus_reco_stage_failure_total",
            "Total stage failures.",
            labelnames=("stage",),
            registry=registry,
        )

        self.regime_label = Gauge(
            "astraeus_reco_regime_label",
            "Current regime label (encoded as label value).",
            labelnames=("label",),
            registry=registry,
        )

        self.recommendations_count = Gauge(
            "astraeus_reco_recommendations_count",
            "Number of recommendations by state.",
            labelnames=("state",),
            registry=registry,
        )

        self.override_rate = Gauge(
            "astraeus_reco_override_rate",
            "Rolling 30-day override rate.",
            registry=registry,
        )

        self.risk_rejection_rate = Gauge(
            "astraeus_reco_risk_rejection_rate",
            "Risk rejection rate by rule.",
            labelnames=("rule",),
            registry=registry,
        )

        self.signal_decay = Gauge(
            "astraeus_reco_signal_decay",
            "Signal decay factor (rolling Sharpe proxy).",
            labelnames=("signal",),
            registry=registry,
        )

        self.pipeline_freshness = Gauge(
            "astraeus_reco_pipeline_freshness_minutes",
            "Minutes since last successful pipeline completion.",
            registry=registry,
        )
