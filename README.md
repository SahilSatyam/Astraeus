# Astraeus

AI-powered quantitative trading and research platform. Built for a solo engineer, designed to scale.

Astraeus combines real-time market data ingestion, NLP-driven alternative data analysis, portfolio optimization, and an AI copilot into a single deployable stack. It runs on a single VPS (~$30/mo) and scales to ~500 users before needing infrastructure changes.

---

## Quick Start (TL;DR)

Already have Docker and Git installed? Here's the fastest path:

```bash
# 1. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone and setup
git clone https://github.com/SahilSatyam/Astraeus.git
cd Astraeus
./scripts/bootstrap.sh

# 3. Start everything
make dev

# 4. Verify (wait ~2 min on first run)
curl http://localhost:8000/healthz
```

That's it. No API keys needed. No database to install. No configuration to change. See [Local Setup](#local-setup) below for detailed platform-specific instructions.

---

## What It Does

- **Real-time market data** — WebSocket streaming from Alpaca, Polygon.io, Alpha Vantage, FRED, Yahoo Finance
- **Order management** — Event-sourced OMS with pre-trade risk checks and circuit breakers
- **Portfolio optimization** — Convex optimization (cvxpy), regime detection (HMM), ensemble strategies
- **Alternative data** — Reddit, RSS, SEC EDGAR ingestion with NLP pipeline (sentiment, NER, embeddings, topic modeling)
- **AI copilot** — Claude/GPT-4 powered research assistant with RAG (pgvector hybrid retrieval)
- **Recommendations engine** — ML-driven trade recommendations with explainability
- **Real-time reconciliation** — 5-second loop comparing local state vs broker positions
- **Full observability** — Structured logging, distributed tracing (OpenTelemetry), Prometheus metrics, Grafana dashboards

---

## Architecture

```
apps/          Application services (API, OMS, Workers, Recon Worker, Web)
libs/          22 shared libraries (domain logic, contracts, config, DB, auth, trading, NLP, ...)
infra/docker/  Docker Compose (local dev + production)
scripts/       Setup, deploy, backup, backfill, load test
docs/          Infrastructure evaluation, hosting guide
```

### Services

| Service | Description | Port (local) |
|---------|-------------|:------------:|
| **API** | Main FastAPI service — CRUD, AI copilot, recommendations, health | 8000 |
| **OMS** | Order Management System — event sourcing, pre-trade risk, circuit breakers | 8001 |
| **Workers** | Background jobs — outbox relay, streaming, nightly batch, alt-data, NLP | — |
| **Recon Worker** | 5-second reconciliation loop (local state vs broker) | — |
| **Web** | Next.js 16 frontend (React 19, App Router, Tailwind CSS 4) | 3001* |

*\* Run separately via `cd apps/web && npm run dev`. Uses port 3001 because Grafana occupies 3000.*

### Data Layer

| Service | Purpose | Port (local) |
|---------|---------|:------------:|
| **PostgreSQL + TimescaleDB** | Primary data, time-series hypertables, vector embeddings (pgvector) | 5432 |
| **Redis** | Cache, trading state, event streaming (Streams), task queue (Celery) | 6379 |
| **MinIO** | S3-compatible object storage — raw documents, model artifacts | 9000/9001 |

### Observability (Local Dev)

| Service | Purpose | URL |
|---------|---------|-----|
| **Jaeger** | Distributed tracing (OpenTelemetry) | http://localhost:16686 |
| **Prometheus** | Metrics collection | http://localhost:9090 |
| **Grafana** | Dashboards and alerting (login: admin/astraeus) | http://localhost:3000 |

### Research Sandbox (Local Dev)

| Service | Purpose | URL |
|---------|---------|-----|
| **MLflow** | Experiment tracking, model registry | http://localhost:5000 |
| **JupyterLab** | Interactive notebooks with full stack access | http://localhost:8888 |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.0 (async), Alembic |
| Frontend | TypeScript 5, Next.js 16, React 19, Tailwind CSS 4, Zustand, TanStack Query |
| Database | PostgreSQL 16 + TimescaleDB + pgvector |
| Cache/Queue | Redis 7.2 (cache + Streams + Celery broker) |
| ML/NLP | PyTorch, Transformers (FinBERT), sentence-transformers, spaCy, BERTopic |
| LLM | Anthropic Claude, OpenAI GPT-4 (API-only, no local models) |
| Quant | cvxpy, scipy, numpy, hmmlearn, scikit-learn |
| Auth | JWT (python-jose) + NextAuth 4 |
| Observability | structlog, OpenTelemetry, Prometheus, Grafana, Jaeger |
| CI/CD | GitHub Actions → GHCR → SSH deploy |
| Package Mgmt | uv (Python), npm (JavaScript) |

---

## Local Setup

### Key Concepts (if you're new to these tools)

**What is Docker?**
Docker runs applications in isolated "containers" — think of them as lightweight virtual machines. Instead of installing PostgreSQL, Redis, etc. on your computer, Docker runs them in containers that don't interfere with your system. Docker Desktop gives you a GUI to manage these containers.

**What is uv?**
uv is a fast Python package manager (like pip, but 10–100× faster). It also manages Python versions — you don't need to install Python 3.12 separately. uv handles it.

**What is Make?**
Make is a task runner. Instead of remembering long commands, you type `make dev` or `make test`. The `Makefile` in the project root defines all available commands.

**What is a monorepo?**
All code (backend, frontend, libraries) lives in one Git repository. The 22 Python libraries in `libs/` are separate packages that share one virtual environment and lockfile.

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Python** | 3.12 | Managed by uv (installed automatically) |
| **uv** | ≥ 0.6.0 | [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **Docker Desktop** | ≥ 24.0 | [docker.com](https://www.docker.com/products/docker-desktop/) |
| **Make** | any | Pre-installed on macOS/Linux; `choco install make` on Windows |
| **Git** | any | [git-scm.com](https://git-scm.com/) |
| **Node.js** | ≥ 20 | Only needed if working on the frontend |

> **Disk space:** First run pulls ~5GB of Docker images. Allow 10GB total for images + volumes.
>
> **RAM:** The full local stack uses ~4–6GB. 16GB system RAM recommended.

---

### macOS

**1. Install Docker Desktop**

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) and install. Make sure the whale icon appears in your menu bar (Docker is running).

**2. Install uv**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen your terminal (or run `source ~/.zshrc`) so the `uv` command is available.

Verify:
```bash
uv --version
# uv 0.6.x
```

**3. Clone the repository**

```bash
git clone https://github.com/SahilSatyam/Astraeus.git
cd Astraeus
```

**4. Run bootstrap**

```bash
./scripts/bootstrap.sh
```

This does:
- Copies `.env.example` → `.env` (if `.env` doesn't exist)
- Installs Python 3.12 via uv
- Syncs all Python dependencies (all 22 workspace packages)
- Installs pre-commit hooks (formatting, linting on every commit)

**5. Start the full stack**

```bash
make dev
```

First run takes 2–3 minutes (downloading Docker images). Subsequent starts take ~15 seconds.

**6. Verify it works**

```bash
curl http://localhost:8000/healthz
# {"status":"ok","service":"api","version":"0.1.0-dev"}
```

Open in your browser:
- API health: http://localhost:8000/healthz
- Jaeger (traces): http://localhost:16686
- Grafana (dashboards): http://localhost:3000 (password: `astraeus`)
- MinIO Console: http://localhost:9001 (user: `astraeus`, password: `astraeus123`)
- JupyterLab: http://localhost:8888
- MLflow: http://localhost:5000

---

### Linux (Ubuntu/Debian)

**1. Install Docker**

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
```

**2. Install uv**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

**3. Install Make (if not already installed)**

```bash
sudo apt update && sudo apt install -y make
```

**4. Clone, bootstrap, and start**

```bash
git clone https://github.com/SahilSatyam/Astraeus.git
cd Astraeus
./scripts/bootstrap.sh
make dev
```

**5. Verify**

```bash
curl http://localhost:8000/healthz
```

---

### Windows (Recommended: WSL 2)

WSL 2 gives you a full Linux environment inside Windows. This is the recommended approach.

**1. Install WSL 2**

Open PowerShell as Administrator:
```powershell
wsl --install
```

Restart your computer. After restart, Ubuntu opens automatically — create a username and password when prompted.

**2. Install Docker Desktop**

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/). During installation:
- Enable "Use WSL 2 based engine" (should be default)
- After install, go to Docker Desktop → Settings → Resources → WSL Integration → Enable for your Ubuntu distro

**3. Set up inside WSL (Ubuntu terminal)**

Open the Ubuntu app from your Start menu, then:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# Install Make
sudo apt update && sudo apt install -y make

# Clone the repo (inside WSL filesystem for best performance)
git clone https://github.com/SahilSatyam/Astraeus.git
cd Astraeus

# Bootstrap
./scripts/bootstrap.sh

# Start the stack
make dev
```

**4. Verify**

```bash
curl http://localhost:8000/healthz
```

> **Important:** Clone the repo inside the WSL filesystem (`~/Astraeus`), not on the Windows mount (`/mnt/c/...`). File operations on the Windows mount are 10–50× slower.

---

### Windows (Native, without WSL)

If you prefer not to use WSL:

1. Install [Git for Windows](https://git-scm.com/download/win) (includes Git Bash)
2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Hyper-V or WSL 2 backend)
3. Install uv: download from [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/#windows)
4. Install Make via [Chocolatey](https://chocolatey.org/): `choco install make`
5. Open Git Bash:

```bash
git clone https://github.com/SahilSatyam/Astraeus.git
cd Astraeus
./scripts/bootstrap.sh
make dev
```

> **Note:** Some shell scripts may not work perfectly in Git Bash. WSL 2 is strongly recommended for the best experience.

---

## First Steps After Setup

Once `make dev` succeeds and `curl http://localhost:8000/healthz` returns OK, here's what to explore:

### 1. Open the API docs

FastAPI auto-generates interactive API documentation:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

You can try API calls directly from the browser — click "Try it out" on any endpoint.

### 2. Look at traces in Jaeger

Open http://localhost:16686. Select "api" from the Service dropdown and click "Find Traces." You'll see every request broken down into spans — useful for understanding how the system works internally.

### 3. Check Grafana dashboards

Open http://localhost:3000. Login with `admin` / `astraeus`. Browse pre-configured dashboards for API metrics, database performance, etc.

### 4. Try backfilling market data

```bash
# Download historical data for SPY and AAPL (no API key needed — uses Yahoo Finance)
make backfill SYMBOLS=SPY,AAPL START=2024-01-01 END=2024-12-31
```

### 5. Open JupyterLab

Go to http://localhost:8888. You have a full notebook environment connected to the database, MLflow, and MinIO. Great for exploratory analysis.

### 6. Start the frontend (optional, separate terminal)

The Next.js frontend runs separately from the Docker stack:

```bash
cd apps/web
npm install       # First time only
npm run dev       # Starts on http://localhost:3001 (or next available port)
```

> **Note:** Grafana uses port 3000 in the Docker stack. Next.js will auto-detect this and use port 3001 instead. Check the terminal output for the actual URL.

---

## Development Workflow

### Making changes to backend code

The backend services (API, OMS, Workers) run inside Docker containers. When you change Python code:

```bash
# Option 1: Rebuild and restart (picks up all changes)
make dev

# Option 2: Restart just one service (faster, but doesn't rebuild the image)
docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml restart api
```

> **Tip:** For rapid iteration, you can run the API directly on your host machine:
> ```bash
> # Make sure the stack is running (for Postgres, Redis, etc.)
> make dev
>
> # Stop the containerized API
> docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml stop api
>
> # Run API locally with hot-reload
> uv run uvicorn astraeus_api.main:app --reload --port 8000
> ```
> Now code changes reload instantly without rebuilding Docker images.

### Making changes to frontend code

The frontend has its own dev server with hot-reload:

```bash
cd apps/web
npm install        # First time only
npm run dev        # Starts on http://localhost:3000 with hot-reload
```

Changes to `.tsx` / `.ts` files appear instantly in the browser.

### Running checks before committing

Pre-commit hooks run automatically on `git commit`, but you can run them manually:

```bash
make fmt           # Fix formatting
make lint          # Check for issues
make typecheck     # Type checking
make test          # Run unit tests
```

Or all at once:
```bash
make fmt lint typecheck test
```

### Adding a new Python dependency

```bash
# Add to a specific library
cd libs/nlp
uv add some-package

# Add a dev dependency (testing, linting tools)
uv add --dev pytest-mock
```

This updates `pyproject.toml` and `uv.lock` automatically.

### Creating a new database migration

When you change SQLAlchemy models:

```bash
make revision MSG="add portfolio_snapshots table"
# This creates a new file in libs/db/astraeus_db/migrations/versions/

# Apply it
make migrate
```

### Understanding the logs

The API outputs structured JSON logs. They look like this:

```json
{"event": "request_started", "method": "GET", "path": "/healthz", "timestamp": "2025-05-31T10:00:00Z", "level": "info", "service": "api"}
```

To make logs more readable during development, set in your `.env`:
```
ASTRAEUS_OBS_LOG_FORMAT=console
```

Then restart the stack. Logs will be human-readable instead of JSON.

---

## Common Commands

### Stack Management

```bash
make dev              # Build images and start the full stack
make stop             # Stop containers (keep data)
make down             # Stop and remove containers (keep data volumes)
make clean            # Stop, remove containers AND volumes (fresh start)
make logs             # Tail logs for all services
make ps               # Show container status
```

### Code Quality

```bash
make fmt              # Auto-format code (ruff format + fix)
make lint             # Lint check (ruff, no autofix)
make typecheck        # mypy strict type checking
make env-lint         # Verify .env.example covers all Settings fields
```

### Testing

```bash
make test             # Unit tests only (no containers needed)
make test-int         # Integration tests (needs running stack)
make load-test        # Load test against local API
                      # Options: DURATION=30 CONCURRENCY=10
```

### Database

```bash
make migrate          # Apply all pending Alembic migrations
make downgrade        # Roll back one migration
make revision MSG="add users table"   # Create a new migration
```

### Market Data

```bash
# Backfill specific symbols
make backfill SYMBOLS=SPY,AAPL START=2024-01-01 END=2024-12-31

# Backfill full universe
make backfill-universe START=2020-01-01 END=2024-12-31

# Replay historical data
make replay SOURCE=yahoo START=2024-01-01 END=2024-01-31
```

### Production

```bash
make prod             # Start production stack locally (uses compose.prod.yml)
make prod-logs        # Tail production logs
make prod-down        # Stop production stack
make backup           # Run database backup
```

### Frontend (apps/web)

```bash
cd apps/web
npm install           # Install JS dependencies
npm run dev           # Start Next.js dev server (hot reload)
npm run build         # Production build
npm run lint          # ESLint
npm run test          # Vitest
```

### Utilities

```bash
make generate-client  # Generate TypeScript API client from OpenAPI spec
make precommit-install  # Re-install git hooks
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/healthz` | GET | Liveness probe |
| `/readyz` | GET | Readiness probe (checks DB + Redis) |
| `/version` | GET | Service version metadata |
| `/metrics` | GET | Prometheus metrics (scrape target) |
| `/api/...` | — | Main API routes (CRUD, copilot, recommendations) |
| `/oms/...` | — | Order Management System routes |
| `/ws/...` | — | WebSocket endpoints (market data streaming) |

---

## Local Database Setup

**You don't need to install PostgreSQL, Redis, or MinIO on your machine.** Everything runs inside Docker containers managed by `make dev`.

### What happens automatically on first `make dev`:

1. **PostgreSQL + TimescaleDB** container starts with:
   - Database `astraeus` (main OLTP — services, control plane)
   - Database `astraeus_research` (TimescaleDB hypertables, time-series data)
   - Extensions enabled: `timescaledb`, `pg_stat_statements`
   - pgvector extension is created by Alembic migrations (for RAG embeddings)

2. **Alembic migrations** run automatically on API startup — all tables, hypertables, indexes, and pgvector columns are created for you.

3. **Redis** starts with append-only persistence (data survives container restarts).

4. **MinIO** starts and the `minio-init` container creates required buckets.

### Connecting to the local database directly

If you want to inspect data or run queries manually:

```bash
# PostgreSQL (psql inside the container)
docker exec -it astraeus-postgres-1 psql -U astraeus -d astraeus

# Or connect from your host machine (if you have psql installed):
psql -h localhost -p 5432 -U astraeus -d astraeus
# Password: astraeus

# Redis
docker exec -it astraeus-redis-1 redis-cli

# MinIO — open the web console:
# http://localhost:9001 (user: astraeus, password: astraeus123)
```

### Data persistence

Docker volumes keep your data between `make stop` / `make dev` cycles:
- `pgdata` — PostgreSQL data
- `redisdata` — Redis AOF
- `miniodata` — MinIO objects

Only `make clean` destroys these volumes (fresh start).

---

## Environment Variables

All configuration is via environment variables. The `.env` file (created by `./scripts/bootstrap.sh`) has sensible defaults for local development — **you can run the entire stack without changing anything**.

### .env File Reference (Local Development)

The bootstrap script copies `.env.example` → `.env`. Here's what each section does:

#### Core Settings (work out of the box)

| Variable | Purpose | Default | Change needed? |
|----------|---------|---------|:--------------:|
| `ASTRAEUS_ENV` | Environment name | `local` | No |
| `ASTRAEUS_APP_NAME` | Service identifier for logs | `astraeus` | No |
| `ASTRAEUS_APP_VERSION` | Version string | `0.1.0` | No |

#### Database (work out of the box)

| Variable | Purpose | Default | Change needed? |
|----------|---------|---------|:--------------:|
| `ASTRAEUS_DB_HOST` | Postgres hostname | `localhost` | No |
| `ASTRAEUS_DB_PORT` | Postgres port | `5432` | No |
| `ASTRAEUS_DB_USER` | Postgres username | `astraeus` | No |
| `ASTRAEUS_DB_PASSWORD` | Postgres password | `astraeus` | No |
| `ASTRAEUS_DB_NAME` | Database name | `astraeus` | No |
| `ASTRAEUS_DB_POOL_SIZE` | Connection pool size | `10` | No |
| `ASTRAEUS_DB_POOL_MAX_OVERFLOW` | Extra connections allowed | `20` | No |
| `ASTRAEUS_DB_ECHO` | Log all SQL queries | `false` | Set `true` to debug |

#### Redis (works out of the box)

| Variable | Purpose | Default | Change needed? |
|----------|---------|---------|:--------------:|
| `ASTRAEUS_REDIS_HOST` | Redis hostname | `localhost` | No |
| `ASTRAEUS_REDIS_PORT` | Redis port | `6379` | No |
| `ASTRAEUS_REDIS_DB` | Redis database number | `0` | No |
| `ASTRAEUS_REDIS_PASSWORD` | Redis password | empty (none) | No |

#### MinIO / Object Storage (works out of the box)

| Variable | Purpose | Default | Change needed? |
|----------|---------|---------|:--------------:|
| `ASTRAEUS_MINIO_ENDPOINT` | MinIO address | `localhost:9000` | No |
| `ASTRAEUS_MINIO_ACCESS_KEY` | MinIO username | `astraeus` | No |
| `ASTRAEUS_MINIO_SECRET_KEY` | MinIO password | `astraeus123` | No |
| `ASTRAEUS_MINIO_SECURE` | Use HTTPS | `false` | No |

#### Observability (works out of the box)

| Variable | Purpose | Default | Change needed? |
|----------|---------|---------|:--------------:|
| `ASTRAEUS_OBS_LOG_LEVEL` | Log verbosity | `INFO` | Set `DEBUG` for more detail |
| `ASTRAEUS_OBS_LOG_FORMAT` | Log format | `json` | Use `console` for readable local logs |
| `ASTRAEUS_OBS_OTLP_ENDPOINT` | Tracing collector | `http://localhost:4317` | No |
| `ASTRAEUS_OBS_SAMPLE_RATE` | Trace sampling rate | `1.0` (100%) | No |

#### Authentication (works out of the box)

| Variable | Purpose | Default | Change needed? |
|----------|---------|---------|:--------------:|
| `ASTRAEUS_AUTH_ENABLED` | Enable/disable JWT auth | `true` | Set `false` to skip auth in dev |
| `ASTRAEUS_AUTH_JWT_SECRET` | JWT signing secret | `change-me-in-production` | No (only matters in prod) |
| `ASTRAEUS_AUTH_JWT_ALGORITHM` | JWT algorithm | `HS256` | No |
| `ASTRAEUS_AUTH_ACCESS_TOKEN_EXPIRE_SECONDS` | Token TTL | `3600` (1 hour) | No |

#### Rate Limiting (works out of the box)

| Variable | Purpose | Default | Change needed? |
|----------|---------|---------|:--------------:|
| `ASTRAEUS_RATE_LIMIT_REDIS_URL` | Redis URL for distributed limiting | empty (uses in-memory) | No |
| `ASTRAEUS_RATE_LIMIT_GLOBAL` | Requests per window | `300` | No |
| `ASTRAEUS_RATE_LIMIT_WINDOW_SECONDS` | Window duration | `60` | No |

#### Market Data API Keys (optional — add when you want real data)

| Variable | Purpose | How to get |
|----------|---------|-----------|
| `ASTRAEUS_MD_ALPACA_API_KEY` | Real-time + historical market data | [alpaca.markets](https://alpaca.markets/) (free tier available) |
| `ASTRAEUS_MD_ALPACA_API_SECRET` | Alpaca secret | Same as above |
| `ASTRAEUS_MD_POLYGON_API_KEY` | Historical market data | [polygon.io](https://polygon.io/) (free tier: 5 calls/min) |
| `ASTRAEUS_MD_ALPHAVANTAGE_API_KEY` | Fundamentals, forex | [alphavantage.co](https://www.alphavantage.co/support/#api-key) (free) |
| `ASTRAEUS_MD_FRED_API_KEY` | Economic indicators | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) (free) |

#### LLM API Keys (optional — add when you want AI features)

| Variable | Purpose | How to get |
|----------|---------|-----------|
| `ASTRAEUS_LLM_ANTHROPIC_API_KEY` | Claude AI copilot | [console.anthropic.com](https://console.anthropic.com/) |
| `ASTRAEUS_LLM_OPENAI_API_KEY` | GPT-4 fallback | [platform.openai.com](https://platform.openai.com/api-keys) |

#### Alternative Data (optional — add when you want NLP features)

| Variable | Purpose | How to get |
|----------|---------|-----------|
| `ASTRAEUS_ALTDATA_REDDIT_CLIENT_ID` | Reddit data ingestion | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) — create a "script" app |
| `ASTRAEUS_ALTDATA_REDDIT_CLIENT_SECRET` | Reddit secret | Same as above |
| `ASTRAEUS_ALTDATA_NLP_DEVICE` | PyTorch device | `cpu` (default) or `cuda` if you have a GPU |
| `ASTRAEUS_ALTDATA_EMBEDDING_MODEL` | Embedding model | `BAAI/bge-small-en-v1.5` (default, 384-dim) |
| `ASTRAEUS_ALTDATA_SENTIMENT_MODEL` | Sentiment model | `ProsusAI/finbert` (default) |

### What works without any API keys?

Everything except:
- Real-time market data streaming (needs Alpaca key)
- AI copilot chat (needs Anthropic or OpenAI key)
- Reddit alt-data ingestion (needs Reddit app credentials)

The following work with **no API keys at all**:
- Full UI and navigation
- Portfolio management and optimization
- Backtesting with locally backfilled data (Yahoo Finance doesn't need a key)
- Order management system
- Database, Redis, MinIO
- All observability (traces, metrics, dashboards)
- NLP pipeline (models download from HuggingFace on first use — no key needed)

### Production .env

For production deployment, see [`docs/hosting-guide.md`](docs/hosting-guide.md). The production `.env.prod` file requires:
- Strong random passwords for DB, MinIO, JWT secret
- Your real domain name
- API keys for services you use

Template: `infra/docker/.env.prod.example`

---

## Project Structure

```
Astraeus/
├── apps/
│   ├── api/              # Main FastAPI service
│   ├── oms/              # Order Management System
│   ├── workers/          # Background workers (NLP, streaming, batch)
│   ├── recon_worker/     # 5-second reconciliation loop
│   └── web/              # Next.js frontend
├── libs/
│   ├── agent_runtime/    # AI agent execution framework
│   ├── altdata/          # Alternative data ingestion (Reddit, RSS, EDGAR)
│   ├── auth/             # JWT authentication
│   ├── brokers/          # Broker adapters (Alpaca, IBKR, Binance)
│   ├── config/           # Centralized settings (pydantic-settings)
│   ├── contracts/        # Event schemas and topic naming
│   ├── db/               # SQLAlchemy models, Alembic migrations
│   ├── domain/           # Core domain types
│   ├── ensemble/         # Strategy ensemble logic
│   ├── entities/         # Business entities
│   ├── features/         # Feature store DSL
│   ├── marketdata/       # Market data ingestion and streaming
│   ├── nlp/              # NLP pipeline (sentiment, NER, embeddings, topics)
│   ├── observability/    # Logging, tracing, metrics setup
│   ├── portfolio/        # Portfolio optimization (cvxpy)
│   ├── rag/              # RAG retrieval (pgvector hybrid search)
│   ├── recommender/      # ML recommendation engine
│   ├── regime/           # Market regime detection (HMM)
│   ├── risk/             # Risk management and limits
│   ├── strategy/         # Trading strategies and cost models
│   ├── trading/          # Order execution and state management
│   └── universe/         # Asset universe management
├── infra/
│   └── docker/           # Docker Compose (dev + prod), Caddy, Postgres init
├── scripts/              # Setup, deploy, backup, backfill, load test
├── docs/
│   ├── infrastructure-evaluation.md   # Infrastructure decisions
│   └── hosting-guide.md              # Step-by-step deployment guide
├── .github/workflows/    # CI (lint, test, typecheck) + CD (build, deploy)
├── pyproject.toml        # uv workspace root
├── Makefile              # Task runner
└── .env.example          # Environment variable template
```

---

## Monorepo Structure

This is a **uv workspace monorepo**. All 22 Python libraries and 4 Python apps share a single lockfile (`uv.lock`) and virtual environment. Dependencies between packages are declared in each package's `pyproject.toml`.

```bash
# Install everything (all packages, all dev deps)
uv sync

# Run a command in the workspace
uv run pytest -m unit

# Add a dependency to a specific package
cd libs/nlp
uv add transformers
```

The frontend (`apps/web`) is a separate npm project with its own `package.json`.

---

## Troubleshooting

### Stack won't start / port conflicts

```bash
make down        # Clean up existing containers
make dev         # Try again
```

If a port is already in use (e.g., another Postgres on 5432):
```bash
# Find what's using the port
lsof -i :5432   # macOS/Linux
netstat -ano | findstr :5432   # Windows

# Either stop the conflicting service or change the port in compose.override.yml
```

### Database connection errors

```bash
# Check if Postgres is healthy
docker ps | grep postgres
# Should show "(healthy)"

# The API runs migrations on startup automatically.
# If you need to run them manually:
make migrate
```

### Out of memory

The full stack needs ~4–6GB RAM. If Docker is constrained:
- **Docker Desktop** → Settings → Resources → increase Memory to 8GB+
- **WSL 2** → Create/edit `%USERPROFILE%\.wslconfig`:
  ```ini
  [wsl2]
  memory=8GB
  ```

### MinIO init failed

```bash
# Re-run the bucket initialization
docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml \
  --profile init run --rm minio-init
```

### Pre-commit hooks failing

```bash
# Fix formatting issues automatically
make fmt

# Re-install hooks if they're broken
make precommit-install
```

### Reset everything (nuclear option)

```bash
make clean       # Removes all containers AND data volumes
make dev         # Fresh start from scratch
```

> **Warning:** `make clean` deletes all local database data, Redis cache, and MinIO files. Only use when you want a completely fresh environment.

---

## Production Deployment

See [`docs/hosting-guide.md`](docs/hosting-guide.md) for the complete step-by-step deployment guide.

**TL;DR:** Single Hetzner VPS (16GB, ~$18/mo) + Docker Compose + Caddy (auto-HTTPS) + Cloudflare (DNS/DDoS). GitHub Actions builds and deploys on push to `main`.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for guidelines.

```bash
# Development workflow
git checkout -b feature/my-feature
make fmt lint typecheck test   # Verify before pushing
git push -u origin feature/my-feature
# Open a PR on GitHub
```

---

## FAQ

**Q: Do I need to know Python and TypeScript to work on this?**
The backend is Python, the frontend is TypeScript. You can work on either independently. The backend doesn't require any frontend knowledge, and vice versa.

**Q: Do I need a trading account or real money?**
No. The platform works with paper trading (simulated) accounts. Alpaca offers free paper trading accounts. You can also backfill historical data and run backtests without any broker connection.

**Q: How much does it cost to run locally?**
Nothing. Local development is free. The only costs are optional API keys (LLM APIs charge per use, market data providers have free tiers).

**Q: The first `make dev` is taking forever. Is that normal?**
Yes. The first run downloads ~5GB of Docker images (PostgreSQL, Redis, MinIO, Jaeger, Prometheus, Grafana, Python base images). Subsequent runs start in ~15 seconds because images are cached.

**Q: Can I run just the backend without the frontend?**
Yes. The frontend (`apps/web`) is optional. The API works independently. Just don't run `npm run dev` in `apps/web`.

**Q: Can I run just the frontend without the backend?**
Partially. The UI will load but API calls will fail. You need at least the API + Postgres + Redis running.

**Q: I don't have 16GB RAM. Can I still run this?**
You can run a minimal stack by stopping services you don't need:
```bash
make dev
docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml stop grafana prometheus jaeger mlflow jupyterlab
```
This frees ~1.5GB RAM. The core services (API, Postgres, Redis) need ~3GB.

**Q: How do I update to the latest version?**
```bash
git pull origin main
uv sync                # Update Python dependencies
make dev               # Rebuild and restart
```

**Q: Where are the database tables defined?**
SQLAlchemy models are in `libs/db/astraeus_db/models/`. Migrations are in `libs/db/astraeus_db/migrations/versions/`.

**Q: How do I add a new API endpoint?**
Look at existing routes in `apps/api/astraeus_api/routes/` for examples. Create a new file, define your FastAPI router, and register it in the app factory.

**Q: What's the difference between `make stop`, `make down`, and `make clean`?**
- `make stop` — pauses containers. Data preserved. Fast restart.
- `make down` — removes containers but keeps data volumes. Next `make dev` recreates containers.
- `make clean` — removes containers AND data. Complete fresh start. You'll lose all local database data.

**Q: I'm getting "permission denied" errors on Linux.**
Make sure your user is in the `docker` group:
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

**Q: How do I see what's in the database?**
```bash
# Connect to Postgres
docker exec -it astraeus-postgres-1 psql -U astraeus -d astraeus

# List tables
\dt

# Query something
SELECT * FROM some_table LIMIT 10;

# Exit
\q
```

Or use a GUI tool like [DBeaver](https://dbeaver.io/) or [pgAdmin](https://www.pgadmin.org/) — connect to `localhost:5432` with user `astraeus`, password `astraeus`.

---

## License

[MIT](LICENSE)
