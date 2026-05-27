# ADR-0001 — Monorepo layout

**Status**: accepted
**Date**: 2026-01-15
**Decider(s)**: Sahil

## Context

Astraeus ships ~10 services and ~5 shared libraries over the project lifetime.
Splitting them into N repositories on day one creates cross-cutting change
friction (an OTel processor change touching every repo) and makes the build
graph opaque.

## Decision

A single repository with three top-level directories:

- `apps/` — deployable services (`api`, `workers`, `web`).
- `libs/` — shared libraries (`domain`, `contracts`, `config`, `db`,
  `observability`).
- `infra/` — Docker Compose, Helm, Terraform.

Each `apps/*` and `libs/*` is a uv workspace member with its own
`pyproject.toml`. Public Python packages use `astraeus_<name>` (snake_case);
distribution names use `astraeus-<name>` (kebab-case).

## Consequences

- Cross-cutting refactors land in a single PR.
- Build graph is explicit via uv workspace.
- Initial test runs touch the whole tree; mitigated by pytest markers and
  per-package CI lanes once it matters.
- License: MIT (see `LICENSE`). Single license keeps audit trivial.

## Alternatives considered

- **Polyrepo** — heavier coordination cost than the team can carry.
- **Two repos (backend + frontend)** — defers the question; Phase 9 frontend
  consumes generated TypeScript types from the backend's OpenAPI spec, so
  co-location is the simpler path.
