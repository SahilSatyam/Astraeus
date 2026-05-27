# ADR-0005 — Redpanda over Kafka for streaming

**Status**: accepted
**Date**: 2026-01-15
**Decider(s)**: Sahil

## Context

Phase 1+ needs a durable streaming broker for tick ingestion, audit topics,
and event-driven workflows. Phase 0 only needs the broker present; producers
and consumers ship later. Local-dev resource consumption matters in scope mode.

## Decision

Redpanda (single binary, Kafka-API compatible) for both local dev and
production. No ZooKeeper. Kafka SDKs work unchanged so a future swap to
MSK / Confluent Cloud is a config change.

## Consequences

- ~50% lower memory footprint than Kafka in local dev.
- Single binary simplifies the docker-compose story.
- `rpk` CLI for topic and cluster ops.
- We track Redpanda's open-source license terms (BSL with conversion to
  Apache 2.0 after four years); in scope mode the local-dev usage is fine.

## Alternatives considered

- **Apache Kafka (Bitnami images)** — heavier, more dev friction.
- **RabbitMQ / NATS** — different semantics; we want log-structured, not
  message-broker semantics.
- **Pulsar** — operator-heavy for the team size.
