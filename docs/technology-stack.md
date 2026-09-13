# Technology Stack

## Languages

| Language | Version | Usage |
|----------|---------|-------|
| Python | 3.12 | Backend services, ML/NLP pipelines, scripts |
| TypeScript | 5.x | Frontend (Next.js), API client generation |
| SQL | PostgreSQL 16 dialect | Migrations, queries, stored functions |
| Shell (Bash) | — | Scripts, CI/CD, Docker entrypoints |

## Frameworks

| Framework | Version | Purpose |
|-----------|---------|---------|
| FastAPI | latest | HTTP API framework (async, OpenAPI) |
| Uvicorn | latest | ASGI server |
| SQLAlchemy | 2.0 (async) | ORM and database toolkit |
| Alembic | latest | Database migrations |
| Next.js | 16 | Frontend framework (App Router, SSR) |
| React | 19 | UI component library |
| Tailwind CSS | 4 | Utility-first CSS framework |

## Python Dependencies (from pyproject.toml + workspace packages)

### Core Runtime

| Package | Purpose | How Used |
|---------|---------|----------|
| `fastapi` | Web framework | API and OMS service HTTP layer |
| `uvicorn` | ASGI server | Production server with proxy headers |
| `pydantic` + `pydantic-settings` | Validation + config | All DTOs, settings, request/response models |
| `sqlalchemy[asyncio]` | ORM | Async database access, model definitions |
| `asyncpg` | PostgreSQL driver | Async connection pool for SQLAlchemy |
| `psycopg` | PostgreSQL driver (sync) | Used by Alembic for migrations |
| `alembic` | Migrations | Schema versioning (12 migration files) |
| `redis` (redis-py) | Redis client | Cache, rate limiting, Streams, Celery |
| `structlog` | Structured logging | JSON/console logging with context binding |
| `orjson` | Fast JSON | Default response serializer (ORJSONResponse) |
| `python-jose` | JWT | Token creation and validation |
| `minio` | S3 client | Object storage for documents and artifacts |

### Observability

| Package | Purpose | How Used |
|---------|---------|----------|
| `opentelemetry-sdk` | Tracing SDK | TracerProvider, BatchSpanProcessor |
| `opentelemetry-exporter-otlp-proto-grpc` | Trace export | OTLP/gRPC to Jaeger |
| `opentelemetry-instrumentation-fastapi` | Auto-instrumentation | Request span creation |
| `prometheus-client` | Metrics | Counter, Histogram definitions |
| `prometheus-fastapi-instrumentator` | Auto-metrics | `/metrics` endpoint, request duration |

### ML / NLP / Quant

| Package | Purpose | How Used |
|---------|---------|----------|
| `torch` (PyTorch) | Deep learning | NLP model inference |
| `transformers` | HuggingFace models | FinBERT sentiment analysis |
| `sentence-transformers` | Embeddings | Document chunk embeddings (BGE-small) |
| `spacy` | NLP | Named Entity Recognition |
| `bertopic` | Topic modeling | Document topic assignment |
| `hdbscan` | Clustering | BERTopic dependency |
| `umap-learn` | Dimensionality reduction | BERTopic dependency |
| `tiktoken` | Tokenization | Token-aware text chunking |
| `cvxpy` | Convex optimization | Portfolio weight optimization |
| `scipy` | Scientific computing | Statistical functions, optimization |
| `numpy` | Numerical computing | Array operations throughout |
| `hmmlearn` | Hidden Markov Models | Market regime detection |
| `scikit-learn` | ML toolkit | Feature engineering, model evaluation |
| `optuna` | Hyperparameter tuning | Strategy parameter optimization |
| `mlflow` | Experiment tracking | Model registry, metric logging |

### Market Data & Trading

| Package | Purpose | How Used |
|---------|---------|----------|
| `yfinance` | Yahoo Finance | Free historical data backfill |
| `exchange-calendars` | Trading calendars | Gap detection, market hours |
| `alpaca-py` | Alpaca broker | Order execution, position queries |
| `ib_insync` | Interactive Brokers | IBKR adapter (planned) |
| `websockets` | WebSocket client | Alpaca streaming connection |

### Alternative Data

| Package | Purpose | How Used |
|---------|---------|----------|
| `praw` | Reddit API | Subreddit ingestion |
| `feedparser` | RSS parsing | News feed ingestion |
| `beautifulsoup4` | HTML parsing | SEC EDGAR document extraction |

### Development & Testing

| Package | Purpose | How Used |
|---------|---------|----------|
| `ruff` | Linter + formatter | Code quality (replaces black, isort, flake8) |
| `mypy` | Type checker | Strict mode across apps + libs |
| `pytest` | Test framework | Unit + integration tests |
| `pytest-asyncio` | Async test support | Testing async handlers |
| `pytest-cov` | Coverage | Branch coverage reporting |
| `hypothesis` | Property-based testing | Fuzzing domain logic |
| `pre-commit` | Git hooks | Automated checks on commit |

## Frontend Dependencies (from apps/web/package.json)

### Runtime

| Package | Version | Purpose |
|---------|---------|---------|
| `next` | 16.2.6 | React framework with SSR |
| `react` / `react-dom` | 19.2.4 | UI library |
| `@tanstack/react-query` | ^5.100 | Server state management |
| `@tanstack/react-table` | ^8.21 | Data grid component |
| `@tanstack/react-virtual` | ^3.13 | Virtualized lists |
| `zustand` | ^5.0 | Client state management |
| `zod` | ^4.4 | Schema validation |
| `react-hook-form` | ^7.76 | Form management |
| `@hookform/resolvers` | ^5.4 | Zod integration for forms |
| `next-auth` | ^4.24 | Authentication (JWT) |
| `echarts` / `echarts-for-react` | ^6.1 / ^3.0 | Charting library |
| `lightweight-charts` | ^5.2 | Financial candlestick charts |
| `cmdk` | ^1.1 | Command palette |
| `dompurify` | ^3.4 | XSS sanitization |

### Development

| Package | Version | Purpose |
|---------|---------|---------|
| `typescript` | ^5 | Type safety |
| `tailwindcss` | ^4 | CSS framework |
| `eslint` + `eslint-config-next` | ^9 | Linting |
| `vitest` | ^4.1 | Unit testing |
| `@testing-library/react` | ^16.3 | Component testing |
| `@playwright/test` | ^1.60 | E2E testing |
| `storybook` | ^8.6 | Component development |
| `jsdom` | ^29.1 | DOM simulation for tests |

## Infrastructure

| Technology | Version | Purpose |
|------------|---------|---------|
| Docker | ≥ 24.0 | Containerization |
| Docker Compose | v2 | Service orchestration |
| Caddy | 2 (Alpine) | Reverse proxy, auto-TLS |
| PostgreSQL | 16 | Primary database |
| TimescaleDB | 2.15.0 | Time-series extension |
| pgvector | latest | Vector similarity search |
| Redis | 7.2 (Alpine) | Cache, streams, rate limiting |
| MinIO | RELEASE.2025-09-07 | S3-compatible object storage |
| Jaeger | 1.58 | Distributed tracing |
| Prometheus | 2.53.0 | Metrics collection |
| Grafana | 11.1.0 | Dashboards and alerting |
| MLflow | 2.14.0 | Experiment tracking (dev) |
| JupyterLab | python-3.12 | Research notebooks (dev) |

## CI/CD

| Tool | Purpose |
|------|---------|
| GitHub Actions | CI/CD pipeline |
| GHCR (GitHub Container Registry) | Docker image hosting |
| Terraform | Infrastructure as Code (planned) |
| Helm | Kubernetes charts (planned) |
| gitleaks | Secret scanning |
| Trivy | Security scanning |
| kubeconform | K8s manifest validation |

## Package Management

| Tool | Scope | Purpose |
|------|-------|---------|
| `uv` (≥ 0.6.0) | Python | Package manager, workspace, lockfile |
| `npm` | JavaScript | Frontend package management |
| `pre-commit` | Git | Hook management |
