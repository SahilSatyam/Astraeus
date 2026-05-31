# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added
- Production hardening: Helm charts, Terraform modules, GitOps manifests (Phase 10)
- Auth library with JWT validation, RBAC, and trading permissions
- OMS kill switch routes with audit journaling
- Next.js operator terminal with full page coverage
- Chaos engineering experiments (pod-kill, broker-latency, network-partition)
- SLO rules and Grafana dashboards for API and OMS
- Runbooks for all critical failure scenarios
- Tiltfile for live-reload development on kind cluster
- Infrastructure lint CI pipeline (Terraform, Helm, policy checks, security scan)
- DR verification script for backtest reproducibility

### Changed
- Upgraded Docker CI to build all service images
- Enhanced API deps with auth integration
- OMS routes now require authenticated principal with trading permission

## [0.8.0] — 2026-05-15

### Added
- Order Management System (OMS) with state machine and event sourcing
- Broker adapters: Alpaca (paper + live), IBKR, Binance paper
- Pre-trade risk gateway with circuit breakers
- Reconciliation worker for broker drift detection
- Kill switch (global, account, strategy scopes)
- Trade journaling (immutable append-only log)
- Position tracking service

## [0.7.0] — 2026-04-20

### Added
- Daily recommendation engine (8-stage pipeline)
- Regime detector (HMM + GMM clustering)
- Multi-source signal ensemble with decay tracking
- HITL approval workflow with override tracking
- Recommendation replay for debugging

## [0.6.0] — 2026-03-25

### Added
- AI agentic layer with LangGraph orchestration
- Research, Sentiment, Strategy, Risk, Execution agents
- RAG over filings/news corpus (pgvector + hybrid BM25)
- Prompt registry with versioning and cost tracking
- Agent guardrails: PII redaction, output validators

## [0.5.0] — 2026-03-01

### Added
- Sentiment and alt-data pipeline
- FinBERT sentiment scoring
- NER entity linking (spaCy + custom)
- BERTopic clustering
- Reddit, RSS, SEC EDGAR ingestion adapters

## [0.4.0] — 2026-02-10

### Added
- Portfolio construction: MVO, Black-Litterman, risk parity, CVaR
- Risk engine: VaR/CVaR, stress scenarios, correlation clustering
- PnL attribution (factor + idiosyncratic)
- Constraint system: sector caps, beta neutrality, turnover limits

## [0.3.0] — 2026-01-25

### Added
- Strategy research engine with vectorized + event-driven backtesters
- Transaction cost model (commission + spread + market impact)
- Walk-forward optimizer with Monte Carlo and Bayesian optimization
- Strategy registry with version pinning
- Metrics module: Sharpe, Sortino, Calmar, max DD, VaR/CVaR

## [0.2.0] — 2026-01-15

### Added
- Feature store with strict point-in-time semantics
- Survivorship-bias-aware universe tables
- Experiment tracking integration

## [0.1.0] — 2026-01-08

### Added
- Market data platform: Polygon, Yahoo, Alpha Vantage, FRED adapters
- TimescaleDB hypertables with continuous aggregates
- Streaming ingestion via Alpaca WebSocket
- Schema registry (Karapace) with Avro contracts
- Outbox pattern for reliable event publishing
- Data lineage tracking

## [0.0.1] — 2025-12-20

### Added
- Monorepo scaffolding with uv workspace
- FastAPI app factory with async DB, Alembic migrations
- Docker Compose stack (Postgres, Redis, Redpanda, MinIO, Jaeger, Prometheus, Grafana)
- Structured logging (structlog) + OpenTelemetry tracing
- CI pipeline: lint, typecheck, unit tests, integration tests
- Pre-commit hooks: ruff, mypy, gitleaks, env-lint
