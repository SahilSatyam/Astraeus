# Local Development Runbook

This walks a new contributor (or a returning one after a long break) from a
clone to a healthy stack in under fifteen minutes.

## Prerequisites

- macOS or Linux. Windows via WSL2.
- 16 GB RAM minimum.
- Tools: `git`, `docker` (Docker Desktop, Colima, or OrbStack), `make`, `uv`.
- Python is installed by `uv` automatically (3.12, pinned via `.python-version`).

Install `uv` if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## First-time setup

```bash
git clone <repo> Astraeus
cd Astraeus
make bootstrap
```

`make bootstrap` is idempotent. It:

1. Copies `.env.example` → `.env` (only if `.env` is absent).
2. Verifies `uv` is on the path.
3. Installs Python 3.12 and syncs every workspace member.
4. Installs pre-commit hooks if `pre-commit` is available.

## Bring the stack up

```bash
make dev
```

This builds the `api` and `workers` images, starts every service in
`infra/docker/compose.yml`, waits on healthchecks, and runs the smoke
verification.

The smoke step probes:

| URL | Expected |
|---|---|
| http://localhost:8000/healthz | 200 |
| http://localhost:8000/readyz | 200 |
| http://localhost:8000/version | 200 |
| http://localhost:8000/metrics | 200 |
| http://localhost:16686/ (Jaeger) | 200 |
| http://localhost:9090/-/healthy (Prometheus) | 200 |
| http://localhost:3000/api/health (Grafana) | 200 |

## Manually verify a request → trace → log

```bash
curl -s -H 'x-request-id: hello' http://localhost:8000/healthz
```

Then open Jaeger at http://localhost:16686, pick the `api` service, and you
should see a span tree for the request. The `request_id`, `trace_id`, and
`span_id` all show up in the `api` container's JSON logs:

```bash
docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml logs api
```

## Common operations

| Task | Command |
|---|---|
| Stop containers, keep volumes | `make stop` |
| Stop and remove containers, keep volumes | `make down` |
| Stop and **delete volumes** (destructive) | `make clean` |
| Reset only the Postgres volume | `./scripts/reset-db.sh` |
| Run unit tests | `make test` |
| Run integration tests | `make test-int` |
| Lint | `make lint` |
| Format | `make fmt` |
| Typecheck | `make typecheck` |
| Apply migrations | `make migrate` |
| New migration | `make revision MSG="add foo"` |

## Troubleshooting

### `make dev` hangs on healthchecks

Run `docker compose -f infra/docker/compose.yml ps` to see which container is
unhealthy. Most often it's Redpanda on a low-memory host — increase Docker's
memory allowance to at least 6 GB.

### Port already in use

A prior `make dev` may have left a service running. Run `make down`.

### Trace not appearing in Jaeger

Check `OTel exporter` logs in the API container. Confirm
`ASTRAEUS_OBS__OTLP_ENDPOINT=http://jaeger:4317` (set by
`compose.override.yml`).

### `mypy` strict failures on a fresh clone

Run `uv sync --all-packages` — strict mode is sensitive to a partial install.
