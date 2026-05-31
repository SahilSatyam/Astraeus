# ADR-0007 — Event-Sourced Order Management System

**Status**: accepted
**Date**: 2026-04-15
**Decider(s)**: Sahil

## Context

The OMS handles real money. Every state transition must be auditable,
reproducible, and debuggable after the fact. Traditional CRUD updates
lose the "why" — we need to know not just the current state but the
full history of how we got there.

## Decision

Event-sourced order lifecycle with an append-only event log.

- Orders have a state machine (NEW → PENDING_NEW → SUBMITTED → PARTIAL_FILL → FILLED / CANCELLED / REJECTED).
- Every state transition is recorded as an `OrderEvent` with timestamp, payload, and source.
- The `TradeJournal` is a separate append-only log for cross-cutting audit (fills, kill switch flips, recon drifts).
- Current state is derived from the event stream but also stored denormalized on the order row for fast queries.

## Consequences

- Full audit trail for every order from creation to terminal state.
- Debugging production issues: replay the event stream to understand what happened.
- Reconciliation can compare event history against broker's reported timeline.
- Slightly more complex write path (event + state update), but the OMS is low-throughput (~100 orders/day max).
- No CQRS separation needed at this scale — single DB with denormalized read model.

## Alternatives considered

- **Pure CRUD with audit columns** — loses intermediate states and transition reasons.
- **Full CQRS + event store** — overkill for single-user, ~100 orders/day throughput.
- **Blockchain/immutable ledger** — unnecessary complexity for a single-operator system.
