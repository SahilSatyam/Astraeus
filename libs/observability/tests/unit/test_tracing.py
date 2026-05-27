import pytest
from astraeus_config import ObservabilitySettings
from astraeus_observability.tracing import configure_tracing
from opentelemetry.sdk.trace import TracerProvider


@pytest.mark.unit
def test_configure_tracing_returns_provider() -> None:
    settings = ObservabilitySettings(otlp_endpoint="http://localhost:4317", sample_rate=1.0)
    provider = configure_tracing(
        settings,
        service_name="api",
        service_version="0.1.0",
        environment="local",
    )
    assert isinstance(provider, TracerProvider)


@pytest.mark.unit
def test_configure_tracing_is_idempotent() -> None:
    settings = ObservabilitySettings()
    p1 = configure_tracing(settings, service_name="api")
    p2 = configure_tracing(settings, service_name="api")
    assert p1 is p2
