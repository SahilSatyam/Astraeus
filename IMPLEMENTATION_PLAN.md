# Astraeus — Phase-Wise Implementation Plan

A structured plan for building the institutional-grade AI trading & research platform described in `description.md`. Each phase ships something usable and de-risks the next.

**Realistic timeline (1–3 engineers):** 8–10 months to a credible end-to-end demo, 14–18 months to institutional-grade. Solo: roughly double.

**Portfolio/MBA cut:** Phases 0–6 alone deliver the resume story. Phases 7–10 push it toward institutional-grade.

---

## Operator Context

The plan is built for a single operator with the following profile. Phase plans contain a "Scope Mode" addendum that adapts the institutional design to this reality.

- **Operator:** Indian resident, solo developer.
- **Project horizon:** 2 years.
- **Purpose:** resume / portfolio artifact + a small live-trading bet that can sustain its own infrastructure cost. No external users, no product launch, no SLA commitments.
- **Trading market:** US equities (SPY/QQQ/IWM, S&P 100, liquid ADRs and sector ETFs — the ~150-name universe defined in Phase 1 scope mode).
- **Trading capital:** $1–2k for the first 3 live months, scaling to $5–10k after a clean track record. Sourced separately from infrastructure spend.
- **Funding path:** LRS (Liberalised Remittance Scheme) outbound remittance to the broker; W-8BEN on file with the broker for the IRS treaty rate on dividends; foreign assets reported in ITR Schedule FA at year-end; foreign tax credit claimed against Indian capital-gains tax.
- **Broker path:**
  - **Paper trading (Phase 8, first 12 months):** Alpaca paper. Free, clean API, fast iteration. Generally accessible to Indian residents for paper accounts and market data; live US-equity trading at Alpaca is gated by US-residency rules, so live execution moves to IBKR.
  - **Live trading (Phase 8, post-paper):** Interactive Brokers (IBKR) — the de facto retail option for Indian residents trading US markets via API. TWS API + `ib_insync` is the Python integration target. KYC takes 2–4 weeks; budget that lead time before Phase 8 live cutover.
  - **Adapter pattern:** the OMS broker interface is identical for both; switching from Alpaca-paper to IBKR-live is a config change, not a rewrite. This keeps the architectural story (broker-agnostic OMS) intact.
- **Brokers explicitly out of scope:** Zerodha / Upstox / Angel One (no US trading), Groww / INDmoney / Vested (US trading available but no public API for retail), GIFT IFSC brokers (API maturity not there yet — revisit in 12–18 months).
- **Ongoing infrastructure budget:** ~$50–100/mo (VPS, optional Polygon Starter, Anthropic with hard cap). One-time ~$300–500 for the Phase 10 cloud-demo window.
- **Operational discipline:** infrastructure costs and trading capital are separate buckets. Trading PnL never funds infra; infra never pulls from trading capital. This avoids the trap of over-leveraging when behind on infra spend.

---

## Phase 0 — Foundation & Scaffolding (Weeks 0–2)

**Goal:** A repo you can build on without rework.

- Monorepo with `apps/` (api, workers, web), `libs/` (domain, contracts, schemas), `infra/`
- `docker-compose.yml`: Postgres+TimescaleDB, Redis, Redpanda, MinIO (S3-compatible), Jaeger, Prometheus, Grafana
- FastAPI skeleton with async DB, Alembic migrations, dependency injection
- Pre-commit (ruff, mypy, black), pytest with fixtures, GitHub Actions (lint → test → build)
- Structured logging (structlog), OpenTelemetry SDK wired but minimal
- `.env.example`, secrets pattern (12-factor), config validation via pydantic-settings

**Exit criteria:** `make dev` brings the stack up; one health-check endpoint traces end-to-end.

---

## Phase 1 — Market Data Platform MVP (Weeks 2–6)

**Goal:** Trustworthy historical + streaming data with lineage.

- Adapters: Polygon, Yahoo, Alpha Vantage, FRED (historical); Alpaca or Binance (WS streaming)
- Schema registry + Avro/Protobuf contracts for ticks, bars, fundamentals, macro
- TimescaleDB hypertables, partitioning by symbol+date, continuous aggregates for OHLCV rollups
- Idempotent ingestion (deterministic keys), DLQ topic, outbox pattern for replay
- Market calendar service (pandas-market-calendars), corporate-action adjustment job
- Data lineage table: `(dataset, source, ingested_at, source_version, hash)`

**Exit criteria:** Reproducible backfill of S&P 500 daily OHLCV + 1 streaming symbol with full audit trail.

---

## Phase 2 — Feature Store & Research Sandbox (Weeks 6–9)

**Goal:** Point-in-time-correct features for research.

- Feature definitions as code (Feast or homegrown over Timescale)
- **Strict PIT semantics** — every feature carries `as_of_ts`; backtest queries cannot see future rows
- Survivorship-bias-aware universe tables (delisted/merged tickers retained)
- Research environment: JupyterHub container with read-only DB role, S3-backed notebook storage
- Experiment tracking: MLflow or W&B

**Exit criteria:** A notebook computes 5 factor exposures across 10 years with provable PIT correctness.

---

## Phase 3 — Strategy Research Engine (Weeks 9–14)

**Goal:** Backtester that doesn't lie to you.

- **Vectorized backtester** (fast, for screening) + **event-driven backtester** (truthful execution simulation)
- Transaction cost model (commission + spread + market-impact via square-root law)
- Slippage and latency simulators
- Walk-forward optimizer, Monte Carlo on returns/parameters, Bayesian optimization (Optuna)
- Strategy registry: versioned, hash-pinned to data + code commit
- First strategies (1 per category): momentum, mean-reversion, pairs, factor blend, simple ML (XGBoost return forecast)
- Metrics module: Sharpe, Sortino, Calmar, max DD, VaR/CVaR, hit ratio, turnover, factor attribution

**Exit criteria:** Walk-forward backtest produces identical results across two machines; deviation between vectorized and event-driven results is bounded and explained.

---

## Phase 4 — Portfolio Construction & Risk (Weeks 14–18)

**Goal:** Turn signals into sized, risk-checked portfolios.

- Optimizers: MVO, Black-Litterman, risk parity, CVaR (cvxpy)
- Constraints: sector caps, beta neutrality, turnover, liquidity-aware sizing
- Risk engine: VaR/CVaR, stress scenarios (2008, COVID, rate shock, flash crash), correlation clustering
- Risk validation gate: every recommendation passes before reaching the recommendation table
- Reporting: PnL attribution (factor + idiosyncratic), exposure reports

**Exit criteria:** A daily job produces a target portfolio with full risk report and rejection log for failed checks.

---

## Phase 5 — Sentiment & Alt Data (Weeks 14–20, parallel with Phase 4)

**Goal:** Institutional-style alt-data pipeline feeding the feature store.

- Ingestion: Reddit (PRAW), X via partner API, RSS news, SEC EDGAR (filings + 8-K stream), earnings transcripts
- Models: FinBERT sentiment, sentence-transformers embeddings, NER (spaCy/finetuned), BERTopic
- pgvector for embedding storage; news-to-ticker linking via NER + ticker dictionary
- Sentiment time-series stored as features (PIT-correct)
- News-impact scoring (event study around publication time)

**Exit criteria:** Per-ticker daily sentiment + topic vectors available as features; demo: divergence detector on one large-cap stock.

---

## Phase 6 — AI Agentic Layer (Weeks 18–24)

**Goal:** Multi-agent orchestration that augments analysts; never the primary alpha source.

- LangGraph (or custom DAG) for stateful workflows; per-agent tool allowlists
- Agents: Research, Sentiment, Strategy, Risk, Execution, Portfolio, Compliance
- RAG over filings/news/research corpus (pgvector + hybrid BM25)
- Structured outputs (Pydantic schemas) — no free-text into downstream systems
- Prompt registry with versioning; cost + latency tracking per call
- Guardrails: PII redaction, prompt-injection isolation (untrusted retrieval is sandboxed), output validators
- HITL queue for any agent action that crosses risk thresholds

**Exit criteria:** "Generate trade thesis for AAPL" runs end-to-end through 4+ agents, produces cited, schema-valid output, logs every prompt/tool call.

---

## Phase 7 — Daily Recommendation Engine (Weeks 22–28)

**Goal:** The 8-stage pipeline, fully wired.

- **Stage 1** aggregator (cron + event-triggered)
- **Stage 2** regime detector (HMM, GMM clustering on macro+vol features)
- **Stage 3** multi-source signal generators (technical, statistical, ML, NLP, macro)
- **Stage 4** ensemble: regime-conditional weights, correlation penalty, decay tracking
- **Stage 5** portfolio construction (reuses Phase 4)
- **Stage 6** risk validation (reuses Phase 4)
- **Stage 7** AI explainability layer (reuses Phase 6 for thesis + commentary)
- **Stage 8** HITL approval workflow with override tracking

**Exit criteria:** Daily run produces N ranked, risk-validated recommendations with explanations and an approval UI.

---

## Phase 8 — Live Trading Infrastructure (Weeks 26–32)

**Goal:** Safe execution. Paper first, live only with kill switches.

- Order service with state machine (NEW → SUBMITTED → PARTIAL → FILLED → DONE/FAILED)
- Idempotency keys end-to-end; reconciliation job vs broker every N seconds
- Brokers in this order: Alpaca paper → Alpaca live → IBKR → Binance
- Risk pre-trade hooks: daily loss, exposure caps, position limits, AI-confidence threshold
- Kill switches at user, strategy, and global level; circuit breakers on PnL drawdown
- Trade journaling (immutable append log)

**Exit criteria:** Paper trading runs autonomously for 2 weeks with zero reconciliation drift.

---

## Phase 9 — Frontend (Weeks 8–32, parallel with backend)

**Goal:** Operator-grade UI built alongside backend phases.

- Next.js + TypeScript + Tailwind; ECharts for time series; WebSocket client for streams
- Module rollout order: Research Terminal → Quant Dashboard → Portfolio → Trading → AI Copilot
- Auth (NextAuth + JWT), RBAC-aware components

**Exit criteria:** Each backend phase has a corresponding visible UI surface.

---

## Phase 10 — Production Hardening (Weeks 28–36)

**Goal:** Make it deployable and explainable to a CTO.

- Kubernetes (kind locally, EKS/GKE prod), Helm charts per service
- Terraform for cloud infra; ArgoCD for GitOps
- Canary + blue/green; chaos testing (LitmusChaos or Chaos Mesh)
- SLOs (p99 latency, freshness, ingestion lag); Prometheus alerts; runbooks
- Security: secrets in Vault/SM, RBAC review, rate limiting, audit log retention, encryption at rest + transit
- Backup/DR drill: restore from backup into a clean cluster

**Exit criteria:** Production readiness checklist signed off; one chaos experiment passes.

---

## Cross-Cutting Concerns (every phase)

- **Observability:** traces, metrics, logs from day 1, not bolted on later
- **Governance:** every model/strategy/prompt version-pinned and auditable
- **Testing pyramid:** unit + integration with real Postgres/Redpanda containers + end-to-end smoke tests
- **Reproducibility:** every backtest result hashes its inputs (data, code, config)

---

## Suggested MVP Cut (time-boxed portfolio path)

**Phases 0 → 1 → 2 → 3 → (slim) 4 → (slim) 6 → 9** gives you a defensible "AI-native quant research platform" demo in **~14–16 weeks**.

Phases 7, 8, and 10 are what take it from "impressive project" to "institutional-grade."

---

## Phase Dependencies (at a glance)

```
0 ── 1 ── 2 ── 3 ── 4 ─┬─ 7 ── 8
              └── 5 ───┤
                  6 ───┘
9 runs parallel to 1–8
10 begins once 7+8 are stable
```
