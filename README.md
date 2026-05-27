# Astraeus

Institutional-grade AI trading and research platform. See [`description.md`](description.md) for the product vision and [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for the phase-by-phase build plan.

## Status

Phase 0 — Foundation & scaffolding. No business logic yet; this commit establishes the chassis: monorepo layout, observability primitives, async DB engine, FastAPI app factory, Docker Compose stack, CI.

## Quickstart

Prerequisites: `uv`, `docker`, `make`, Python 3.12 (uv installs it).

```bash
git clone <this-repo> && cd Astraeus
./scripts/bootstrap.sh         # one-time: install uv deps, copy .env, etc.
make dev                       # bring up the local stack
curl http://localhost:8000/healthz
```

See [`docs/runbooks/local-dev.md`](docs/runbooks/local-dev.md) for the full first-run guide.

## Layout

```
apps/        FastAPI services (api, workers, web placeholder)
libs/        Shared libraries (domain, contracts, config, db, observability)
infra/       Docker Compose, k8s/terraform placeholders
docs/        ADRs and runbooks
scripts/     Bootstrap, smoke, env-lint
phase-plans/ Per-phase deep-dive plans
```

## License

[MIT](LICENSE).
