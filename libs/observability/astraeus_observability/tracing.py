"""OpenTelemetry tracing bootstrap.

Phase 0 ships a single configure entrypoint that any service calls during
startup. Auto-instrumentations (FastAPI, SQLAlchemy, asyncpg, httpx) live in the
calling app — this module only sets up the global ``TracerProvider`` so libs
stay framework-agnostic.

In Phase 0 there is no OTel Collector; spans are exported directly to Jaeger via
OTLP/gRPC. Phase 10 will add a Collector for fan-out and tail-based sampling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.semconv.resource import ResourceAttributes

if TYPE_CHECKING:
    from astraeus_config import ObservabilitySettings


def configure_tracing(
    settings: ObservabilitySettings,
    *,
    service_name: str,
    service_version: str = "0.1.0",
    environment: str = "local",
) -> TracerProvider:
    """Configure the global OTel ``TracerProvider``.

    Idempotent — repeated calls reuse the existing provider so test fixtures
    and ``create_app()`` factories can both invoke it freely.
    """
    existing = trace.get_tracer_provider()
    if isinstance(existing, TracerProvider):
        return existing

    resource = Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: service_name,
            ResourceAttributes.SERVICE_VERSION: service_version,
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: environment,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.sample_rate)),
    )
    exporter = OTLPSpanExporter(
        endpoint=settings.otlp_endpoint,
        insecure=settings.otlp_insecure,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def reset_tracing_for_tests() -> None:
    """Test helper: replace the global tracer provider with a fresh one.

    OTel intentionally rejects overriding the global ``TracerProvider`` so this
    helper has limited reach — it primarily exists to mark intent in fixtures.
    """
