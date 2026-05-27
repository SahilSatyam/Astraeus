# Astraeus

Institutional-grade AI trading and research platform. See [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for the phase-by-phase build plan.

## Status

**Phase 0 — Foundation & Scaffolding** ✅

Monorepo layout, observability primitives, async DB engine, FastAPI app factory, Docker Compose stack, CI pipeline, structured logging, and OpenTelemetry tracing.

## Architecture

```
apps/        FastAPI services (api, workers, web placeholder)
libs/        Shared libraries (domain, contracts, config, db, observability)
infra/       Docker Compose, Prometheus/Grafana configs, k8s placeholders
docs/        ADRs and runbooks
scripts/     Bootstrap, smoke test, env-lint
```

### Services (Docker Compose)

| Service | Image | Port |
|---------|-------|------|
| API | astraeus/api:dev | 8000 |
| Workers | astraeus/workers:dev | — |
| PostgreSQL + TimescaleDB | timescale/timescaledb:2.15.0-pg16 | 5432 |
| Redis | redis:7.2-alpine | 6379 |
| Redpanda (Kafka) | redpandadata/redpanda:v24.1.10 | 19092 |
| MinIO (S3) | minio/minio | 9000, 9001 |
| Jaeger (tracing) | jaegertracing/all-in-one:1.58 | 16686 |
| Prometheus | prom/prometheus:v2.53.0 | 9090 |
| Grafana | grafana/grafana:11.1.0 | 3000 |

---

## Local Setup

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12 | Runtime (managed by uv) |
| uv | ≥ 0.6.0 | Python package/project manager |
| Docker | ≥ 24.0 | Container runtime |
| Docker Compose | ≥ 2.20 (bundled with Docker Desktop) | Service orchestration |
| Make | any | Task runner |
| Git | any | Version control |

---

### macOS Setup

**1. Install Docker Desktop**

Download from https://www.docker.com/products/docker-desktop/ and install. Ensure it's running (whale icon in menu bar).

**2. Install uv**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal or run `source ~/.zshrc` after installation.

**3. Clone and bootstrap**

```bash
git clone https://github.com/SahilSatyam/Astraeus.git
cd Astraeus
./scripts/bootstrap.sh
```

This copies `.env.example` → `.env`, installs Python 3.12 via uv, syncs all dependencies, and sets up pre-commit hooks.

**4. Start the stack**

```bash
make dev
```

This builds the app images, starts all services, runs MinIO bucket initialization, and verifies health. First run takes 2–3 minutes (image pulls).

**5. Verify**

```bash
curl http://localhost:8000/healthz
# {"status":"ok","service":"api","version":"0.1.0-dev"}
```

---

### Windows Setup

**1. Install Docker Desktop**

Download from https://www.docker.com/products/docker-desktop/ and install. Enable WSL 2 backend during setup (recommended). Ensure Docker Desktop is running.

**2. Use WSL 2 (recommended)**

Open PowerShell as Administrator:

```powershell
wsl --install
```

Restart, then open the Ubuntu terminal from Start menu.

**3. Install uv (inside WSL)**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

**4. Install Make (inside WSL)**

```bash
sudo apt update && sudo apt install -y make
```

**5. Clone and bootstrap (inside WSL)**

```bash
git clone https://github.com/SahilSatyam/Astraeus.git
cd Astraeus
./scripts/bootstrap.sh
```

**6. Start the stack**

```bash
make dev
```

**7. Verify**

```bash
curl http://localhost:8000/healthz
```

> **Note:** If using native Windows (without WSL), you'll need Git Bash or similar for the shell scripts. WSL 2 is strongly recommended for the best experience.

---

### Windows (Native, without WSL)

If you prefer not to use WSL:

1. Install [Git for Windows](https://git-scm.com/download/win) (includes Git Bash)
2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with Hyper-V or WSL 2 backend
3. Install uv: download from https://docs.astral.sh/uv/getting-started/installation/#windows
4. Install Make via [Chocolatey](https://chocolatey.org/): `choco install make`
5. Open Git Bash and run:

```bash
git clone https://github.com/SahilSatyam/Astraeus.git
cd Astraeus
./scripts/bootstrap.sh
make dev
```

---

## Common Commands

```bash
make dev          # Build and start the full stack
make stop         # Stop containers (keep volumes)
make down         # Stop and remove containers (keep volumes)
make clean        # Stop, remove containers AND volumes (destructive)
make logs         # Tail logs for all services
make ps           # Show container status

make fmt          # Auto-format code (ruff)
make lint         # Lint check (ruff)
make typecheck    # mypy strict

make test         # Unit tests only
make test-int     # Integration tests (needs running stack)

make migrate      # Apply Alembic migrations
make revision MSG="description"  # Create new migration
```

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /healthz` | Liveness probe |
| `GET /readyz` | Readiness probe (checks DB) |
| `GET /version` | Service version metadata |
| `GET /metrics` | Prometheus metrics |

## Observability UIs

| UI | URL |
|----|-----|
| Jaeger (traces) | http://localhost:16686 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/astraeus) |
| MinIO Console | http://localhost:9001 (astraeus/astraeus123) |

## Troubleshooting

**Stack won't start / port conflicts**

```bash
make down        # clean up existing containers
make dev         # try again
```

**Database connection errors**

Ensure Postgres is healthy: `docker ps | grep postgres`. The API runs migrations on startup automatically.

**MinIO init failed**

Re-run manually:

```bash
docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml --profile init run --rm minio-init
```

**Reset everything**

```bash
make clean       # removes all containers and volumes
make dev         # fresh start
```

## License

[MIT](LICENSE)
