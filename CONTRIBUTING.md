# Contributing to Astraeus

This is a personal portfolio project (see `IMPLEMENTATION_PLAN.md` operator
context); external contributions aren't expected today, but the conventions
below apply if and when they are.

## Workflow

- Trunk-based: feature branches off `main`, **squash merge**.
- Every PR must pass: `make lint`, `make typecheck`, `make test`, integration
  tests in CI.
- An ADR is required to:
  - Change a top-level dependency.
  - Alter a naming convention.
  - Change error / logging schemas.
  - Add a new top-level directory.

  Use `docs/adr/0000-template.md` as a starting point.

## Code style

- `ruff` is the only formatter and linter. Run `make fmt` before committing.
- `mypy --strict` over `apps` and `libs`. Add types; don't `# type: ignore`
  without a comment explaining why.
- Tests go next to the code they test (per workspace member's `tests/`
  directory).
- Public functions get docstrings; helpers don't need them. Don't write
  comments that restate the code.

## Commits

- Conventional Commits: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`,
  `ci`, `infra`.
- Subject under 70 characters; details in the body.
- One logical change per commit when possible; PRs may bundle related commits.

## Setup

See the [README](README.md) for full local setup instructions, or the quick
version:

```bash
./scripts/bootstrap.sh   # first-time setup
make dev                 # start the full stack
```
