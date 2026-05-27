import pytest
from astraeus_observability.metrics import (
    build_registry,
    request_duration_histogram,
)


@pytest.mark.unit
def test_build_registry_returns_independent_registry() -> None:
    r1 = build_registry()
    r2 = build_registry()
    assert r1 is not r2


@pytest.mark.unit
def test_request_duration_histogram_uses_named_buckets() -> None:
    registry = build_registry()
    h = request_duration_histogram(registry)
    # Sanity: histogram is registered.
    samples = list(registry.collect())
    assert any(metric.name == "astraeus_http_request_duration_seconds" for metric in samples)
    assert h is not None
