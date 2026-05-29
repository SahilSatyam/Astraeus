"""OpenTelemetry instrumentation and Prometheus metrics for portfolio construction.

Provides:
- OTel spans for optimizer runs, risk gate decisions, and attribution runs.
- Prometheus metrics: optimizer.solve_time_ms, gate.decision, attribution.idio_bps.

Usage:
    from astraeus_portfolio.telemetry import portfolio_tracer, METRICS

    with portfolio_tracer.start_as_current_span("optimize") as span:
        span.set_attribute("optimizer", "mvo")
        ...

    METRICS.optimizer_solve_time.observe(elapsed_ms)
"""

from __future__ import annotations

from opentelemetry import trace
from prometheus_client import CollectorRegistry, Counter, Histogram

# ---------------------------------------------------------------------------
# OpenTelemetry Tracer
# ---------------------------------------------------------------------------

# The global TracerProvider is configured at app startup via
# astraeus_observability.tracing.configure_tracing(). This module just
# acquires a named tracer scoped to the portfolio domain.
portfolio_tracer = trace.get_tracer("astraeus.portfolio", "0.1.0")


# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------


class PortfolioMetrics:
    """Prometheus metrics for the portfolio construction pipeline.

    Metrics:
        optimizer_solve_time: Histogram of optimizer solve times in milliseconds.
        gate_decision: Counter of risk gate decisions (passed/rejected).
        attribution_idio_bps: Histogram of idiosyncratic PnL in basis points.
        pipeline_duration: Histogram of full pipeline duration in milliseconds.
        fallback_actions: Counter of fallback actions taken.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Initialize metrics, optionally with a custom registry.

        Args:
            registry: Prometheus registry. Uses default if None.
        """
        kwargs = {"registry": registry} if registry else {}

        self.optimizer_solve_time = Histogram(
            "astraeus_portfolio_optimizer_solve_time_ms",
            "Optimizer solve time in milliseconds.",
            labelnames=("strategy_id", "optimizer", "status"),
            buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
            **kwargs,
        )

        self.gate_decision = Counter(
            "astraeus_portfolio_gate_decision_total",
            "Risk gate decisions.",
            labelnames=("strategy_id", "decision"),
            **kwargs,
        )

        self.attribution_idio_bps = Histogram(
            "astraeus_portfolio_attribution_idio_bps",
            "Idiosyncratic PnL in basis points.",
            labelnames=("strategy_id", "method"),
            buckets=(-100, -50, -25, -10, -5, 0, 5, 10, 25, 50, 100),
            **kwargs,
        )

        self.pipeline_duration = Histogram(
            "astraeus_portfolio_pipeline_duration_ms",
            "Full daily pipeline duration in milliseconds.",
            labelnames=("strategy_id", "status"),
            buckets=(100, 500, 1000, 2500, 5000, 10000, 30000, 60000),
            **kwargs,
        )

        self.fallback_actions = Counter(
            "astraeus_portfolio_fallback_actions_total",
            "Fallback actions taken after risk rejection.",
            labelnames=("strategy_id", "action"),
            **kwargs,
        )


# Module-level singleton (uses default Prometheus registry)
METRICS = PortfolioMetrics()
