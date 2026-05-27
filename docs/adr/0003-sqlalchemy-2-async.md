# ADR-0003 — SQLAlchemy 2.0 async ORM

**Status**: accepted
**Date**: 2026-01-15
**Decider(s)**: Sahil

## Context

Phase 1+ needs typed access to time-series data with windowing, CTEs, and
`LATERAL` joins (for PIT-correct feature retrieval). Pydantic validation must
remain separable from persistence.

## Decision

SQLAlchemy 2.0 async ORM (`Mapped[...]` typing) with `asyncpg` for runtime and
`psycopg` for Alembic. Pydantic v2 lives in `libs/contracts` and never touches
the ORM directly; mapper functions in route handlers convert between DTOs and
ORM models.

## Consequences

- First-class typed ORM, mature handling of complex queries.
- Single declarative `Base` in `libs/db/base.py` discovered by Alembic
  autogenerate.
- Two psql drivers in the dependency tree: `asyncpg` (runtime) and `psycopg`
  (alembic). Acceptable; Alembic doesn't natively run async.
- Discipline required: ORM models must not leak through HTTP boundaries.

## Alternatives considered

- **SQLModel** — conflates ORM and validation, lags SA 2.0 features, breaks
  on Timescale-specific DDL.
- **Tortoise / Piccolo** — smaller ecosystems, weaker typing story.
- **Raw asyncpg** — fast, but rebuilding query construction and migrations is
  not the right place to spend effort.
