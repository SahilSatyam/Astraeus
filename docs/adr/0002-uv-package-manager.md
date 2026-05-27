# ADR-0002 — uv as the package manager

**Status**: accepted
**Date**: 2026-01-15
**Decider(s)**: Sahil

## Context

The project is a Python monorepo with multiple workspace members (apps + libs).
We need a package manager that handles workspaces well, has fast resolves, and
won't be the long pole in CI.

## Decision

`uv` (Astral) is the package manager and Python toolchain. `uv.lock` is
committed; CI uses `uv sync --frozen`. Each workspace member has its own
`pyproject.toml`; the root `[tool.uv.workspace]` section enumerates them.

## Consequences

- 10–100× faster dependency resolves than Poetry. CI cycle time benefits.
- Single binary, no Python bootstrap chicken-and-egg. New contributors install
  `uv` once and `make bootstrap` does the rest.
- Lockfile format aligned with PEP 751 direction.
- `uv` is younger than Poetry; some edge cases around editable installs across
  workspace members. Pinned to a known-good version in CI.

## Alternatives considered

- **Poetry** — slower, weak workspace story.
- **pip-tools + Hatch** — split-tool friction, two configs to maintain.
- **Rye** — folded into uv.
