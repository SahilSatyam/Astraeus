# ADR-0004 — structlog + OpenTelemetry for observability

**Status**: accepted
**Date**: 2026-01-15
**Decider(s)**: Sahil

## Context

Every service emits logs, traces, and metrics from day one. Phase 1+ relies on
trace-correlated logs (a user-facing error must map to a Jaeger search via
trace_id). Inventing a new logging or tracing format mid-project is a Phase 0
bug.

## Decision

- **Logs**: structlog with a frozen processor chain emitting JSON in CI/prod
  and console-rendered output in local dev. The chain includes a `Redactor`
  processor that scrubs `password|token|api_key|secret` keys recursively.
- **Traces**: OpenTelemetry SDK, OTLP/gRPC exporter directly to Jaeger
  (collector deferred to Phase 10). `ParentBased(TraceIdRatioBased(rate))`
  sampler. Auto-instrumentations for FastAPI, SQLAlchemy, asyncpg, httpx wired
  in `apps/api/.../app.py::instrument()`.
- **Metrics**: Prometheus pull, naming `astraeus_<domain>_<noun>_<unit>`.
  Default Grafana dashboard ships with the API for HTTP RED.

## Consequences

- Single shared `libs/observability` module with `configure_logging` /
  `configure_tracing` / `configure_metrics` callable from any service.
- Trace ID propagated to log records via structlog contextvars; included in
  RFC 7807 Problem Details responses.
- Phase 1+ is structurally incapable of inventing a new envelope; reviewers can
  enforce the convention.

## Alternatives considered

- **stdlib logging only** — rejected; structured logs are the only useful
  format at scale and stdlib's structured story is awkward.
- **OTel collector in Phase 0** — rejected; one moving part to debug for zero
  benefit at one service. Added in Phase 10 for fan-out and tail sampling.
- **Datadog / Honeycomb agent** — rejected for cost during the 2-year scope-mode
  period; can swap the OTLP endpoint later without code change.
