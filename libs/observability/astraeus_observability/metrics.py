"""Prometheus metrics primitives.

Naming convention (frozen): ``astraeus_<domain>_<noun>_<unit>``.

Phase 0 only ships the registry and a couple of common helpers. Each service
defines its own counters/histograms in its own module and imports the registry
from here so the ``/metrics`` endpoint surfaces the union.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram


def build_registry() -> CollectorRegistry:
    """Return a fresh registry. Tests use this to avoid global-state leakage."""
    return CollectorRegistry()


def request_counter(registry: CollectorRegistry, *, service: str) -> Counter:
    counter = Counter(
        "astraeus_http_requests_total",
        "Total HTTP requests received.",
        labelnames=("service", "method", "route", "status"),
        registry=registry,
    )
    counter.labels(service=service, method="", route="", status="")
    return counter


def request_duration_histogram(registry: CollectorRegistry) -> Histogram:
    return Histogram(
        "astraeus_http_request_duration_seconds",
        "HTTP request duration in seconds.",
        labelnames=("service", "method", "route"),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=registry,
    )
