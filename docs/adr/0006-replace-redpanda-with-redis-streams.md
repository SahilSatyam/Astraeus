# ADR-0006 — Replace Redpanda with Redis Streams

**Status**: accepted
**Date**: 2026-05-31
**Decider(s)**: Sahil
**Supersedes**: ADR-0005

## Context

The original architecture (ADR-0005) chose Redpanda as the streaming broker for
event-driven workflows. In practice, the system never grew beyond a single-VPS
deployment target, and the only real producer is the outbox relay draining
published market-data rows into a stream. Redpanda adds ~500 MB RAM overhead,
a schema registry dependency (Karapace), and operational complexity that is
unjustified for the current scale.

Redis is already in the stack for caching and rate-limiting. Redis Streams
provides ordered, durable, consumer-group-capable log semantics — sufficient
for the outbox relay pattern and future NLP pipeline fan-out.

## Decision

Replace Redpanda (and Karapace schema registry) with Redis Streams for all
event streaming. The outbox relay publishes via `XADD`; consumers (when needed)
use `XREADGROUP`. The outbox table remains the source of truth — Redis Streams
is the transport layer only.

## Consequences

**Positive:**
- Eliminates ~500 MB RAM and a JVM-class process from the stack.
- Removes Karapace dependency entirely.
- One fewer service to monitor, back up, and upgrade.
- Simpler Docker Compose (fewer services, fewer health checks).
- Redis is already battle-tested in the stack.

**Negative:**
- Redis Streams lacks native schema enforcement (Karapace provided Avro/JSON
  Schema validation). Mitigated by Pydantic models at the application boundary.
- No built-in exactly-once semantics. Mitigated by the outbox table acting as
  the idempotency layer (rows are marked published after successful XADD).
- If Redis memory fills, streams may be evicted under `allkeys-lru`. Mitigated
  by setting `MAXLEN` on streams and relying on the outbox table for replay.

**Neutral:**
- Topic naming convention stays the same (e.g., `md.equity.daily.v1`).
- Kafka-compatible client libraries (aiokafka) are removed from dependencies.
- Helm charts and Terraform for future k8s/EKS deployment are shelved, not deleted.

## Alternatives considered

- **Keep Redpanda** — too heavy for single-VPS; adds cost and ops burden with
  no current benefit.
- **NATS JetStream** — viable but adds another service; Redis is already present.
- **PostgreSQL LISTEN/NOTIFY** — no durability or consumer groups; not suitable
  for replay.
