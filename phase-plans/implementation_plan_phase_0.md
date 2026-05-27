# Phase 0 — Foundation & Scaffolding

**Window:** Weeks 0–2 (10 working days)
**Owner:** 1–3 engineers
**Charter:** Stand up a monorepo, local dev stack, and the cross-cutting primitives (config, logging, tracing, migrations, CI) that every subsequent phase will build on. No business logic. No data. No models. Just the chassis.

---

## 1. Goals and Non-Goals

### Goals
1. Repository structure and tooling that scales to 10 services without rework.
2. `make dev` boots the full local stack reproducibly on macOS/Linux in under three minutes from a cold cache.
3. A single FastAPI service (`apps/api`) with one health endpoint that emits structured logs, exports a complete OTLP trace to Jaeger, and runs against an async SQLAlchemy engine with at least one Alembic migration applied.
4. Pre-commit, CI, and test scaffolding catch issues before review (lint, types, unit, container-backed integration).
5. Conventions documented in ADRs so Phases 1–10 don't relitigate them.

### Non-Goals (explicit)
- No market data adapters, no ingestion, no schemas beyond a single `system_health` table demonstrating the migration loop.
- No auth, no RBAC, no JWT issuance. Auth design is Phase 10's deliverable; Phase 0 only reserves the seam (`apps/api/deps.py`).
- No Kubernetes manifests, no Helm, no Terraform, no ArgoCD. `infra/k8s/` and `infra/terraform/` exist as empty placeholders with READMEs.
- No frontend implementation. `apps/web/` is a placeholder; Next.js init is Phase 9.
- No Celery/Temporal, no agent framework, no LLM integration. Worker app exists as a process scaffold only.
- No production deployment story. Local Docker Compose is the only target.
- No multi-tenant or RBAC primitives in the DB schema.

If a sibling phase asks Phase 0 to "just add X for me," the answer is no unless X is a primitive in the list above.

---

## 2. Architecture Decisions (with rationale and pushback)

### 2.1 Package manager: `uv` (not Poetry, not pip-tools)
- **Why:** 10–100x faster resolves, lockfiles compatible with PEP 751 direction, native workspace support that fits a monorepo, single binary, no Python bootstrap chicken-and-egg.
- **Alternatives:** Poetry (slower, workspace story is poor), pip-tools + Hatch (split-tool friction), Rye (now folded into uv).
- **Implication:** Lockfile is `uv.lock` at repo root. Each app/lib is a workspace member with its own `pyproject.toml`. CI uses `uv sync --frozen` and `uv run`.

### 2.2 Linter/formatter: ruff only (drop black)
- **Pushback on master plan:** The master plan lists "ruff, mypy, black." Running ruff and black is redundant — `ruff format` is now black-compatible and 30x faster. Keeping both means two formatter runs in pre-commit and double the CI time for zero benefit.
- **Decision:** `ruff check` + `ruff format` + `mypy --strict` (incrementally tightened). Configure both in `pyproject.toml`.

### 2.3 ORM: SQLAlchemy 2.0 async (not SQLModel)
- **Why:** SA 2.0's typed ORM (`Mapped[...]`) is mature and handles complex queries (windowing, CTEs, `LATERAL` joins) we'll need for time-series in Phase 2+. SQLModel conflates ORM and validation, lags SA 2.0 features, and breaks down on Timescale-specific DDL.
- **Validation:** Pydantic v2 in a separate `libs/contracts` layer. Never let request/response models touch the ORM directly — DTO conversion happens in route handlers via mapper functions.

### 2.4 Migrations: Alembic, async-aware, single env
- One alembic env in `libs/db/astraeus_db/migrations/`, called from any service that owns DDL.
- **Convention:** migrations are versioned by `YYYYMMDDHHMM_short_slug.py`, not opaque hashes (alembic supports `file_template`).
- **Convention:** every migration must be reversible (`downgrade()` implemented) until we adopt a forward-only policy in Phase 10. Justification: Phase 1+ will iterate on schema rapidly and rollback during local dev is a real thing.
- **Convention:** no data migrations in alembic. DDL only. Data backfills go in `scripts/migrations_data/` and run as one-shot jobs.

### 2.5 Config: pydantic-settings v2, nested, fail-fast
- One `Settings` class composed of typed sub-models (`DatabaseSettings`, `RedisSettings`, `KafkaSettings`, `ObservabilitySettings`, `AppSettings`).
- Loaded once at startup; raised `ValidationError` aborts boot. No silent defaults for production-relevant secrets.
- `.env.example` is the source of truth for variable names. CI lint job checks `.env.example` is a superset of every variable referenced in the Settings class.

### 2.6 Logging: structlog with JSON in prod, console in dev
- **Schema (frozen for the lifetime of the project):**
  ```
  timestamp        ISO8601 UTC
  level            DEBUG|INFO|WARNING|ERROR|CRITICAL
  logger           dotted module path
  service          "api"|"workers"|...
  env              "local"|"ci"|"staging"|"prod"
  trace_id         16-byte hex (from OTel context, if present)
  span_id          8-byte hex
  event            short snake_case verb phrase
  ...              arbitrary structured context
  ```
- `event` is the indexable verb (`http_request_completed`, `db_query_failed`); free-text goes into `message` only when needed.
- Loggers must never log secrets; `libs/observability` ships a `Redactor` processor that scrubs known sensitive keys (`password`, `token`, `api_key`, `secret`) regardless of caller discipline.

### 2.7 Tracing: OpenTelemetry, OTLP/gRPC direct to Jaeger (no Collector yet)
- **Why no Collector in Phase 0:** Adds a moving part to debug for zero benefit at one service. Jaeger 1.35+ accepts OTLP natively. Add the Collector in Phase 10 when we need fan-out (Tempo + Honeycomb) or sampling policy.
- Auto-instrumentation: FastAPI, SQLAlchemy, httpx, asyncpg, redis-py. All wired in `libs/observability/tracing.py::configure_tracing(settings)`.
- **Convention:** every cross-service call propagates W3C `traceparent`. Background tasks (Phase 1+ Celery/Arq) carry trace context via message metadata.
- **Convention:** span names are `verb.noun` (`http.request`, `db.query`, `kafka.produce`); attributes follow OTel semantic conventions.

### 2.8 Metrics: Prometheus pull, OTel SDK bridges
- App exposes `/metrics` via `prometheus-fastapi-instrumentator` plus OTel meter bridge for custom counters/histograms.
- **Convention:** metric names are `astraeus_<domain>_<noun>_<unit>` (`astraeus_http_requests_total`, `astraeus_ingestion_lag_seconds`).
- Grafana provisioned with one starter dashboard (HTTP RED metrics) so downstream phases have a template.

### 2.9 Streaming: Redpanda (not Kafka, not RabbitMQ)
- **Why:** Single binary, Kafka-API compatible, no ZooKeeper, half the memory in dev. We retain the option to swap to MSK/Confluent in prod with no code change.
- **Alternative considered:** Apache Kafka via Bitnami images. Rejected for dev ergonomics.
- Phase 0 only stands the broker up; no producers, no consumers, no schema registry. Schema registry slot reserved (`infra/docker/redpanda/console.yml` includes it commented).

### 2.10 Object store: MinIO (S3-compatible)
- Standalone single-node container in Phase 0. Buckets created by an init container on boot (`astraeus-research`, `astraeus-artifacts`, `astraeus-data-lake`). Same SDK code (`aioboto3`) works against AWS S3 in prod.

### 2.11 Database: Postgres 16 + TimescaleDB 2.x extension
- One Postgres instance, two logical databases: `astraeus` (OLTP) and `astraeus_research` (analytics, where heavy hypertables live in Phase 1+). Logical separation now avoids a painful migration later.
- Timescale extension is enabled in the migration that creates the first hypertable (Phase 1), but the image must support it from day one, hence `timescale/timescaledb:latest-pg16`.

### 2.12 Dependency injection: FastAPI `Depends`, no DI framework
- Constructor-injected services in routes via `Depends(get_x)`; service factories in `apps/api/astraeus_api/deps.py`.
- **Pushback:** `dependency-injector` and `punq` add ceremony for negligible benefit at this size. Revisit if cross-app wiring complexity warrants it.

### 2.13 Error handling: RFC 7807 Problem Details
- Single base exception `AstraeusError(code: str, status: int, detail: str)` in `libs/domain/exceptions.py`.
- Global FastAPI exception handler converts to `application/problem+json`.
- **Convention:** error codes are namespaced — `astraeus.<domain>.<short_name>` (e.g., `astraeus.market_data.symbol_not_found`). Codes are stable across versions; messages are not.

### 2.14 Testing: pytest + pytest-asyncio + testcontainers
- Three test tiers, separate pytest markers: `unit`, `integration`, `e2e`.
- Integration tests spin up Postgres, Redis, Redpanda via `testcontainers` (not docker-compose) so each test session is isolated and parallelizable.
- **Convention:** every public service function has at least a unit test; every route has a contract test.

---

## 3. Directory Layout

```
astraeus/
├── apps/
│   ├── api/                                # FastAPI service
│   │   ├── astraeus_api/
│   │   │   ├── __init__.py
│   │   │   ├── main.py                     # uvicorn entrypoint
│   │   │   ├── app.py                      # create_app() factory
│   │   │   ├── lifespan.py                 # startup/shutdown
│   │   │   ├── settings.py                 # API-specific settings
│   │   │   ├── deps.py                     # FastAPI Depends factories
│   │   │   ├── errors.py                   # RFC 7807 handlers
│   │   │   ├── middleware.py               # request_id, access log
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       └── health.py               # /healthz, /readyz, /version
│   │   ├── tests/
│   │   │   ├── conftest.py
│   │   │   ├── unit/
│   │   │   └── integration/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── workers/                            # process scaffold only
│   │   ├── astraeus_workers/
│   │   │   ├── __init__.py
│   │   │   └── main.py                     # placeholder loop
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   └── web/                                # Next.js (Phase 9)
│       └── README.md
├── libs/
│   ├── domain/                             # pure types, no IO
│   │   ├── astraeus_domain/
│   │   │   ├── __init__.py
│   │   │   ├── exceptions.py
│   │   │   └── ids.py                      # typed IDs (NewType)
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── contracts/                          # pydantic DTOs / Avro later
│   │   ├── astraeus_contracts/
│   │   │   ├── __init__.py
│   │   │   └── health.py
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── config/                             # shared base settings
│   │   ├── astraeus_config/
│   │   │   ├── __init__.py
│   │   │   └── base.py                     # BaseSettings, Environment enum
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── db/                                 # SQLA engine + alembic
│   │   ├── astraeus_db/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py                   # create_async_engine
│   │   │   ├── session.py                  # async_sessionmaker, get_session
│   │   │   ├── base.py                     # DeclarativeBase
│   │   │   └── migrations/
│   │   │       ├── env.py                  # async-aware
│   │   │       ├── script.py.mako
│   │   │       └── versions/
│   │   │           └── 202601011200_initial.py
│   │   ├── alembic.ini
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── observability/                      # structlog + OTel
│       ├── astraeus_observability/
│       │   ├── __init__.py
│       │   ├── logging.py                  # configure_logging()
│       │   ├── tracing.py                  # configure_tracing()
│       │   ├── metrics.py                  # configure_metrics()
│       │   └── context.py                  # request_id, trace correlation
│       ├── tests/
│       └── pyproject.toml
├── infra/
│   ├── docker/
│   │   ├── compose.yml                     # canonical stack
│   │   ├── compose.override.yml            # dev-only ports/volumes
│   │   ├── postgres/
│   │   │   ├── init.sql                    # CREATE DATABASE astraeus_research
│   │   │   └── timescale.sh                # CREATE EXTENSION timescaledb
│   │   ├── redpanda/
│   │   │   └── bootstrap.sh                # topic init
│   │   ├── minio/
│   │   │   └── bootstrap.sh                # bucket init
│   │   ├── prometheus/
│   │   │   └── prometheus.yml
│   │   ├── grafana/
│   │   │   └── provisioning/
│   │   │       ├── datasources/datasources.yml
│   │   │       └── dashboards/
│   │   │           ├── dashboards.yml
│   │   │           └── api-red.json
│   │   └── jaeger/                         # uses defaults
│   ├── k8s/                                # Phase 10 placeholder
│   │   └── README.md
│   └── terraform/                          # Phase 10 placeholder
│       └── README.md
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                          # lint + typecheck + test
│   │   ├── docker.yml                      # build + push images on tag
│   │   └── adr-check.yml                   # ensure ADRs render
│   ├── CODEOWNERS
│   ├── pull_request_template.md
│   └── ISSUE_TEMPLATE/
├── docs/
│   ├── architecture/
│   │   └── overview.md
│   ├── adr/
│   │   ├── 0000-template.md
│   │   ├── 0001-monorepo-layout.md
│   │   ├── 0002-uv-package-manager.md
│   │   ├── 0003-sqlalchemy-2-async.md
│   │   ├── 0004-structlog-otel.md
│   │   └── 0005-redpanda-vs-kafka.md
│   └── runbooks/
│       └── local-dev.md
├── scripts/
│   ├── bootstrap.sh                        # first-time setup
│   ├── reset-db.sh
│   ├── wait-for.sh                         # generic TCP/HTTP waiter
│   └── verify-stack.sh                     # smoke check after make dev
├── .env.example
├── .pre-commit-config.yaml
├── .gitignore
├── .gitattributes
├── .editorconfig
├── .python-version                         # 3.12
├── pyproject.toml                          # root: uv workspace + tool config
├── uv.lock
├── Makefile
├── README.md
├── CONTRIBUTING.md
├── description.md
└── IMPLEMENTATION_PLAN.md
```

---

## 4. Key Files: Content Sketches

### 4.1 Root `pyproject.toml` (workspace + shared tool config)

```toml
[project]
name = "astraeus"
version = "0.1.0"
requires-python = ">=3.12,<3.13"

[tool.uv.workspace]
members = ["apps/*", "libs/*"]

[tool.uv.sources]
astraeus-domain         = { workspace = true }
astraeus-contracts      = { workspace = true }
astraeus-config         = { workspace = true }
astraeus-db             = { workspace = true }
astraeus-observability  = { workspace = true }

[tool.ruff]
target-version = "py312"
line-length = 100
src = ["apps", "libs"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "S", "C4", "SIM", "RET", "TCH", "ARG", "PTH", "ERA", "PL", "RUF", "ASYNC", "PERF"]
ignore = ["S101", "PLR0913"]  # allow asserts in tests, don't nit on arg count

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S", "PLR2004", "ARG"]
"libs/db/**/migrations/**" = ["E501", "I001"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_ignores = true
disallow_any_explicit = true
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["alembic.*", "testcontainers.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
addopts = "-ra -q --strict-markers --strict-config"
asyncio_mode = "auto"
markers = [
  "unit: fast in-process tests",
  "integration: tests requiring containers",
  "e2e: full-stack smoke tests",
]
```

### 4.2 `apps/api/pyproject.toml`

```toml
[project]
name = "astraeus-api"
version = "0.1.0"
dependencies = [
  "fastapi>=0.111",
  "uvicorn[standard]>=0.30",
  "sqlalchemy[asyncio]>=2.0.30",
  "asyncpg>=0.29",
  "alembic>=1.13",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "structlog>=24.1",
  "opentelemetry-api>=1.25",
  "opentelemetry-sdk>=1.25",
  "opentelemetry-exporter-otlp>=1.25",
  "opentelemetry-instrumentation-fastapi>=0.46b0",
  "opentelemetry-instrumentation-sqlalchemy>=0.46b0",
  "opentelemetry-instrumentation-asyncpg>=0.46b0",
  "prometheus-fastapi-instrumentator>=7.0",
  "httpx>=0.27",
  # workspace
  "astraeus-domain",
  "astraeus-contracts",
  "astraeus-config",
  "astraeus-db",
  "astraeus-observability",
]

[dependency-groups]
dev = [
  "pytest>=8.2",
  "pytest-asyncio>=0.23",
  "pytest-cov>=5.0",
  "testcontainers[postgres,redis,kafka]>=4.7",
  "httpx>=0.27",
  "ruff>=0.5",
  "mypy>=1.10",
]
```

### 4.3 `apps/api/astraeus_api/app.py`

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.observability)
    configure_tracing(settings.observability, service_name="api")
    configure_metrics()

    app = FastAPI(
        title="Astraeus API",
        version=settings.app.version,
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )
    app.state.settings = settings

    register_middleware(app)            # request_id, access log, CORS
    register_exception_handlers(app)    # RFC 7807
    register_routes(app)                # health, version
    instrument(app)                     # OTel + Prometheus

    return app
```

The factory pattern keeps tests fast (each test can spin up an isolated app with overridden settings) and forbids module-level side effects.

### 4.4 `libs/config/astraeus_config/base.py` (sketch)

```python
class Environment(str, Enum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PROD = "prod"

class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTRAEUS_DB_")
    host: str
    port: int = 5432
    user: str
    password: SecretStr
    name: str = "astraeus"
    pool_size: int = 10
    pool_max_overflow: int = 20
    pool_timeout_seconds: int = 30
    echo: bool = False

    @property
    def dsn(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.name}"

class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTRAEUS_OBS_")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    otlp_endpoint: str = "http://jaeger:4317"
    otlp_insecure: bool = True
    sample_rate: float = 1.0  # parent-based sampler in prod

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")
    env: Environment = Environment.LOCAL
    db: DatabaseSettings
    redis: RedisSettings
    kafka: KafkaSettings
    observability: ObservabilitySettings
    app: AppSettings
```

Every service composes `Settings` once at boot. The `.env` namespace convention is `ASTRAEUS_<DOMAIN>_<KEY>` — collisions are impossible.

### 4.5 `libs/observability/astraeus_observability/tracing.py` (sketch)

```python
def configure_tracing(settings: ObservabilitySettings, *, service_name: str) -> None:
    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: service_name,
        ResourceAttributes.SERVICE_VERSION: __version__,
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.env.value,
    })
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.sample_rate)),
    )
    exporter = OTLPSpanExporter(
        endpoint=settings.otlp_endpoint,
        insecure=settings.otlp_insecure,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
```

Auto-instrumentation is invoked from `apps/api/.../app.py::instrument(app)` so libs stay framework-agnostic.

### 4.6 `infra/docker/compose.yml` (services overview)

```yaml
services:
  postgres:
    image: timescale/timescaledb:2.15.0-pg16
    environment:
      POSTGRES_DB: astraeus
      POSTGRES_USER: astraeus
      POSTGRES_PASSWORD: astraeus
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/00-init.sql
      - ./postgres/timescale.sh:/docker-entrypoint-initdb.d/01-timescale.sh
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U astraeus -d astraeus"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7.2-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

  redpanda:
    image: redpandadata/redpanda:v24.1.10
    command: >
      redpanda start
        --smp 1 --memory 1G --reserve-memory 0M
        --overprovisioned --node-id 0
        --kafka-addr PLAINTEXT://0.0.0.0:9092
        --advertise-kafka-addr PLAINTEXT://redpanda:9092
    healthcheck:
      test: ["CMD", "rpk", "cluster", "health"]

  minio:
    image: minio/minio:RELEASE.2024-06-13T22-53Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: astraeus
      MINIO_ROOT_PASSWORD: astraeus123
    volumes:
      - miniodata:/data

  minio-init:
    image: minio/mc
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: ["/bin/sh", "/scripts/bootstrap.sh"]

  jaeger:
    image: jaegertracing/all-in-one:1.58
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    ports:
      - "16686:16686"  # UI
      - "4317:4317"    # OTLP gRPC

  prometheus:
    image: prom/prometheus:v2.53.0
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:11.1.0
    environment:
      GF_SECURITY_ADMIN_PASSWORD: astraeus
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning

volumes:
  pgdata: {}
  miniodata: {}
```

Notes that matter:
- All services declare healthchecks. `make dev` waits on health, not on `sleep`.
- No `latest` tags. Every image is pinned; ADR-0006 governs the upgrade cadence.
- App services (`api`, `workers`) live in `compose.override.yml` so the base file is reusable in CI.

### 4.7 `Makefile` (canonical entry points)

```make
.PHONY: dev down logs clean fmt lint typecheck test test-int migrate revision build smoke

dev:                ## Bring up full stack
	docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml up -d --wait
	./scripts/verify-stack.sh

down:
	docker compose -f infra/docker/compose.yml down

clean:
	docker compose -f infra/docker/compose.yml down -v

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy apps libs

test:
	uv run pytest -m "unit"

test-int:
	uv run pytest -m "integration"

migrate:
	uv run --package astraeus-db alembic upgrade head

revision:
	uv run --package astraeus-db alembic revision --autogenerate -m "$(MSG)"

build:
	docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml build

smoke:
	./scripts/verify-stack.sh
```

`make` is the only blessed entry point. Anything not in the Makefile doesn't exist for new contributors.

### 4.8 `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.5
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.1
    hooks:
      - id: mypy
        additional_dependencies: [pydantic, sqlalchemy, types-redis]
        pass_filenames: false
        args: [apps, libs]
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-merge-conflict
      - id: check-added-large-files
        args: [--maxkb=500]
      - id: detect-private-key
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks
```

### 4.9 `.github/workflows/ci.yml` (job topology)

```
lint           ─┐
typecheck      ─┼─ all run on every push/PR, parallel
test-unit      ─┤
test-integration┘  (uses services: postgres, redis, redpanda)
build-docker      runs on main + tags only
```

Cache keys: `uv-${{ hashFiles('uv.lock') }}` for the venv; pre-built buildx cache per Dockerfile.

---

## 5. Conventions and Contracts (frozen for downstream phases)

These are the rules Phases 1–10 inherit. Changes require an ADR.

### 5.1 Naming
- **Python packages:** `astraeus_<domain>` (snake_case). Distribution name: `astraeus-<domain>` (kebab-case).
- **DB tables:** snake_case, plural (`market_data_bars`, `strategy_runs`). No prefixes.
- **Topics (Redpanda):** `astraeus.<domain>.<entity>.<event>` (e.g., `astraeus.market_data.bar.created`).
- **Metrics:** `astraeus_<domain>_<noun>_<unit>` (Prometheus convention).
- **Trace span names:** `verb.noun` lowercase.
- **Error codes:** `astraeus.<domain>.<short_name>`.
- **HTTP routes:** `/v1/<resource>` plural; resource names match table names where they correspond 1:1.

### 5.2 Error handling contract
- All exceptions raised across a service boundary inherit from `AstraeusError`.
- HTTP responses to errors are `application/problem+json` per RFC 7807. Body shape:
  ```json
  {"type": "https://astraeus.dev/errors/<code>", "title": "...", "status": 404, "code": "astraeus.market_data.symbol_not_found", "detail": "...", "trace_id": "..."}
  ```
- `trace_id` is always included so a user-facing error maps directly to a Jaeger search.

### 5.3 Logging contract
- See Section 2.6 schema. Loggers are obtained via `structlog.get_logger(__name__)`.
- **Convention:** every log line in a request handler must inherit `request_id` and `trace_id` via the structlog context (handled by middleware).
- **Convention:** log at INFO for state changes, DEBUG for verbose tracing, WARNING for recoverable anomalies, ERROR for unhandled or business-critical failures. No `print`.

### 5.4 Config contract
- Every service exposes a `Settings` class composed of the shared sub-settings in `libs/config`. Adding new config requires:
  1. Update `libs/config` if shared, otherwise local `settings.py`.
  2. Update `.env.example` with the new variable.
  3. CI `env-lint` job verifies parity.

### 5.5 Migration workflow
- New tables/columns: `make revision MSG="add <thing>"` → autogenerate → review SQL → commit.
- **Convention:** never edit a merged migration. Add a new one.
- **Convention:** index changes are separate migrations from column changes (so they can be rolled back independently in prod).
- **Convention:** any migration touching tables larger than 10M rows must be reviewed for lock behavior; checklist lives in `docs/runbooks/migrations.md`.

### 5.6 Test layout
- `tests/unit/` runs in <30s, no IO, no containers.
- `tests/integration/` may use testcontainers; isolated fixtures per test class.
- `tests/e2e/` runs against `make dev` stack; only invoked in nightly CI.
- `conftest.py` provides shared fixtures: `settings`, `engine`, `session`, `client`.
- **Convention:** every PR that adds a route adds a contract test.
- **Convention:** flaky tests are quarantined within 24h, fixed within 7 days, or deleted.

### 5.7 ADR workflow
- Every architectural decision lives in `docs/adr/` numbered sequentially.
- States: `proposed | accepted | superseded by NNNN | rejected`.
- An ADR is required to: change a top-level dependency, alter a naming convention, change error/logging schemas, or add a new top-level directory.

### 5.8 Branching and PR contract
- Trunk-based. Feature branches off `main`, squash merge.
- PR checks (mandatory): lint, typecheck, unit, integration, ADR check.
- CODEOWNERS enforces review on `libs/`, `infra/`, `.github/`, ADRs.

---

## 6. Detailed Work Breakdown

Sized in working hours. Total ≈ 80–110h (one engineer full-time fits in the 2-week window with slack; two engineers can parallelize most of weeks 1–2).

### Week 1 (foundation, must be sequential at the top)

| ID | Task | Hrs | Depends |
|----|------|-----|---------|
| F-01 | Repo init: `.gitignore`, `.editorconfig`, `.python-version`, `README.md`, license decision (ADR-0001) | 2 | — |
| F-02 | `pyproject.toml` root + uv workspace; create empty members | 3 | F-01 |
| F-03 | `libs/config` with base Settings + Environment enum + tests | 4 | F-02 |
| F-04 | `libs/domain` with AstraeusError + typed IDs | 2 | F-02 |
| F-05 | `libs/contracts` with one DTO (HealthResponse) | 1 | F-04 |
| F-06 | `libs/observability/logging.py` structlog setup + tests | 4 | F-03 |
| F-07 | `libs/observability/tracing.py` OTel bootstrap + tests | 4 | F-03 |
| F-08 | `libs/observability/metrics.py` Prometheus + OTel meter | 2 | F-03 |
| F-09 | `libs/db/engine.py` async engine + session + tests | 3 | F-03 |
| F-10 | `libs/db/migrations` alembic init (async env.py) + first migration creating `system_health` | 4 | F-09 |

Parallelizable from F-03 onwards across two engineers.

### Week 1 (continued, services)

| ID | Task | Hrs | Depends |
|----|------|-----|---------|
| A-01 | `apps/api` skeleton: factory, lifespan, settings | 3 | F-03..F-08 |
| A-02 | `apps/api/routes/health.py`: `/healthz` (liveness), `/readyz` (DB ping), `/version` | 3 | A-01, F-09 |
| A-03 | RFC 7807 error handlers + middleware (request_id) | 3 | A-01 |
| A-04 | OTel + Prometheus instrumentation wiring | 2 | A-01, F-07 |
| A-05 | API Dockerfile (multi-stage, distroless final) | 3 | A-01 |
| A-06 | Workers app scaffold (placeholder loop, no logic) | 1 | F-06 |
| A-07 | Workers Dockerfile | 2 | A-06 |

### Week 2 (infra, CI, polish)

| ID | Task | Hrs | Depends |
|----|------|-----|---------|
| I-01 | `infra/docker/compose.yml` core services (Postgres, Redis, Redpanda, MinIO) | 4 | — |
| I-02 | `infra/docker/compose.override.yml` for app services | 2 | I-01, A-05, A-07 |
| I-03 | Postgres init: research DB + Timescale extension hook | 1 | I-01 |
| I-04 | MinIO init container creating buckets | 1 | I-01 |
| I-05 | Jaeger + Prometheus + Grafana provisioning | 3 | I-01 |
| I-06 | Grafana starter dashboard (HTTP RED) | 2 | I-05 |
| I-07 | `Makefile` with all targets | 2 | I-01, F-10 |
| I-08 | `scripts/verify-stack.sh` end-to-end smoke | 3 | I-02, A-02 |
| C-01 | `.pre-commit-config.yaml` + bootstrap script | 2 | F-02 |
| C-02 | GitHub Actions: ci.yml (lint, typecheck, unit, integration) | 5 | F-02, A-01 |
| C-03 | GitHub Actions: docker.yml (build + push on tag) | 3 | A-05 |
| C-04 | CODEOWNERS, PR template, issue templates | 1 | F-01 |
| C-05 | `.env.example` + env-lint script | 2 | F-03 |
| D-01 | ADR-0001..0005 written | 4 | parallel |
| D-02 | `README.md` quickstart + `docs/runbooks/local-dev.md` | 3 | I-07, I-08 |
| D-03 | `CONTRIBUTING.md` | 1 | C-01..C-04 |

### Buffer / slack
~10–15h reserved for the inevitable docker-compose and CI yak-shaving.

---

## 7. Sequencing and Critical Path

1. **F-01 → F-02 → F-03** unblocks everything. One engineer, day 1.
2. **Observability (F-06/07/08) and DB (F-09/10) run in parallel** by day 2.
3. **API skeleton (A-01)** depends on settings + observability; workers (A-06) similarly.
4. **Compose stack (I-01..I-05)** can start in parallel with API work because it doesn't depend on app code.
5. **CI (C-02)** must wait for at least one app target to test. Stub initially with `pytest --collect-only` if needed.
6. **Smoke verify (I-08)** is the last gate before exit-criteria sign-off.

Critical path runs through: F-03 → F-09 → F-10 → A-01 → A-02 → I-01 → I-02 → I-08.

---

## 8. Exit Criteria Checklist (verifiable)

- [ ] `git clone && ./scripts/bootstrap.sh && make dev` succeeds on a fresh macOS or Ubuntu host with Docker installed, in < 3 minutes after image cache.
- [ ] `make lint` exits 0 on a clean tree.
- [ ] `make typecheck` exits 0; mypy strict mode is enforced.
- [ ] `make test` runs ≥ 10 unit tests across `libs/*` and `apps/api`; coverage ≥ 70% for `libs/`.
- [ ] `make test-int` runs ≥ 3 integration tests using testcontainers (Postgres, Redis, Redpanda) and exits 0.
- [ ] `curl localhost:8000/healthz` returns 200 with `{"status": "ok"}`.
- [ ] `curl localhost:8000/readyz` returns 200 only when Postgres is reachable (returns 503 with Problem Details when DB is paused).
- [ ] `curl localhost:8000/version` returns service name, version, git sha, build time.
- [ ] One trace from `/healthz` is visible in Jaeger UI at `localhost:16686`, with at least three spans (HTTP server → DB ping → response).
- [ ] Trace ID present in the JSON log line for the request matches the trace ID in Jaeger.
- [ ] Prometheus scrapes `/metrics`; Grafana "API RED" dashboard renders QPS, latency p50/p95/p99, error rate.
- [ ] Alembic upgrade runs cleanly from empty DB; downgrade is reversible.
- [ ] `.env.example` contains every variable referenced in `Settings`; CI `env-lint` job enforces this.
- [ ] Pre-commit blocks a commit containing a hardcoded `password = "..."` pattern (gitleaks).
- [ ] GitHub Actions CI runs on every PR: lint, typecheck, unit, integration; all green for the merge that closes Phase 0.
- [ ] ADRs 0001–0005 merged to `docs/adr/`, status accepted.
- [ ] `docs/runbooks/local-dev.md` walks a new contributor from clone to first request in < 15 minutes.

---

## 9. Risks and Open Questions

### High-impact decisions to lock by end of week 1
1. **Python version:** 3.12 (recommended) vs 3.13. 3.12 is a safer floor; some libs still flake on 3.13. Decision: 3.12, revisit Q1 of next year.
2. **Worker runtime for Phase 1+:** Celery vs Arq vs Temporal vs Dramatiq. Out of scope for Phase 0, but the choice affects whether `apps/workers` carries Celery boilerplate. **Recommendation:** punt — keep `apps/workers` empty so Phase 1 can pick.
3. **Auth surface in Phase 0:** include a `Depends(get_current_user)` no-op stub or not? **Recommendation:** include the seam (returns a fake principal in dev), to avoid every Phase 1+ route adding it themselves.
4. **OTel sample rate:** parent-based 1.0 in Phase 0 (single service, no volume). Tail-based sampling is a Phase 10 concern.

### Risks
- **Risk:** Docker Compose v2 on Apple Silicon has known ARM image gaps for Redpanda/MinIO. Mitigation: pin to `linux/arm64`-published tags; tested on M1/M2/M3.
- **Risk:** uv workspaces are still maturing; edge cases around editable installs across workspace members. Mitigation: pin uv to a known-good version in `bootstrap.sh`; document the workaround for anyone on an older version.
- **Risk:** Alembic autogenerate against async engine has historically been flaky for type changes. Mitigation: review every autogenerated migration manually, document the gotcha in runbooks.
- **Risk:** mypy strict mode causes friction with FastAPI's dependency injection annotations. Mitigation: typed `Annotated[X, Depends(...)]` aliases in `apps/api/deps.py`; document pattern.
- **Risk:** Time-zone discipline. Postgres `TIMESTAMPTZ` everywhere, never `TIMESTAMP`. Convention added to migration runbook now to avoid Phase 1 PIT bugs.

### Push-back on the master plan
- **"ruff, mypy, black"** — drop black, use ruff format. (Section 2.2)
- **"OpenTelemetry SDK wired but minimal"** — go further: ship auto-instrumentation for FastAPI/SQLAlchemy/asyncpg in Phase 0. The marginal cost is one afternoon and the value is enormous because Phase 1's first lineage trace will already work. Skipping it now means re-doing every span definition later.
- **"GitHub Actions (lint → test → build)"** — sequential is wasteful. Run lint, typecheck, unit, and integration as parallel jobs; build only on main/tags.

---

## 10. Definition of Done — Handoff to Phase 1

Phase 0 is "done" when Phase 1 can begin work without:
- Touching `libs/db/engine.py` or `libs/db/session.py` (extending it is fine; rewriting it is not).
- Adding a new top-level directory.
- Choosing a logging or tracing library.
- Inventing an error envelope.
- Writing alembic env boilerplate.
- Standing up Postgres/Redis/Redpanda/MinIO locally.

Concrete artifacts handed to Phase 1:
1. **Working compose stack** with healthchecked Postgres+Timescale, Redpanda, MinIO, Redis, Jaeger, Prometheus, Grafana.
2. **`libs/db`** ready to add Phase 1 hypertable migrations; Timescale extension creation pattern established.
3. **`libs/observability`** with `configure_logging`, `configure_tracing`, `configure_metrics` callable from any new service.
4. **`libs/contracts`** ready to receive Avro/Protobuf schemas — Phase 1 adds `astraeus-contracts[avro]` extra and a `schemas/` subpackage.
5. **`libs/config`** with `KafkaSettings` already present (unused but defined) so Phase 1 just imports it.
6. **CI** that runs against any new app or lib added under `apps/*` or `libs/*` without workflow edits.
7. **Naming, error, logging, metric, trace conventions** documented and ADR'd.
8. **A runbook** explaining how to add a new service, a new migration, a new Kafka topic, and a new Grafana dashboard.

If Phase 1 finds itself editing more than 50 lines in `libs/db`, `libs/observability`, or `libs/config` during week 1 of their phase, that's a Phase 0 bug and gets backported.

---

## 11. Files Most Critical for Implementing This Plan

These files do the heaviest lifting; getting them right unblocks the rest.

- `/Users/mukesh/python-projects/Astraeus/pyproject.toml` (root workspace + tool config)
- `/Users/mukesh/python-projects/Astraeus/Makefile` (canonical entry points)
- `/Users/mukesh/python-projects/Astraeus/infra/docker/compose.yml` (local stack contract)
- `/Users/mukesh/python-projects/Astraeus/libs/observability/astraeus_observability/tracing.py` (OTel bootstrap reused everywhere)
- `/Users/mukesh/python-projects/Astraeus/libs/db/astraeus_db/migrations/env.py` (async alembic env, the template for all future migrations)
- `/Users/mukesh/python-projects/Astraeus/apps/api/astraeus_api/app.py` (factory pattern other services will mirror)
- `/Users/mukesh/python-projects/Astraeus/.github/workflows/ci.yml` (parallel CI topology)

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

This project is a personal portfolio + a small live trading account, not a product. The full plan above is the *artifact* — what lives in the repo and on the resume. The runtime version is trimmed for one user and ~$50–100/mo of running cost.

**What changes for Phase 0**

- Solo timeline: 3–4 weeks instead of 2. Don't measure against a 3-engineer baseline.
- Local-only stack. `docker-compose` is the dev *and* "prod" environment for the first ~12 months. Kubernetes/Helm charts get written in Phase 10 as resume artifacts; they don't run continuously.
- One repo, on GitHub Free or Pro. No Linear/Jira; GitHub Issues is enough.
- Pre-commit + Actions CI stays — these are cheap and the resume cares.
- OTel + Jaeger + Prometheus + Grafana stay in `docker-compose` — they're the observability story; self-hosted is fine for one user.
- Skip: managed CI runners, secret-management vendors, anything billed per seat.

**What stays (resume-load-bearing)**

- Monorepo layout, contracts library, schema registry shape, structured logging, OTel wiring, Alembic, FastAPI factory, CI matrix. These are the discussion topics in interviews — keep the rigor.

**Budget impact:** $0/mo in this phase. Domain optional ($12/year).
