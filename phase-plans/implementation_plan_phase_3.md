# Phase 3 — Strategy Research Engine

**Timeline:** Weeks 9–14 · **Depends on:** Phases 1, 2 · **Blocks:** Phase 4, 7

---

## 1. Phase Goals & Refined Exit Criteria

The mission is **a backtester that doesn't lie to you**. Every retail quant project ships a backtester; almost every one of them produces backtests that diverge from live performance by 200–500 bps annualised. The two backtester strategy in this phase — vectorized for screening, event-driven for honesty — is the same pattern Two Sigma and AQR use for the same reason: vectorized is fast enough to scan thousands of parameter sets; event-driven is the only thing that tells you what live execution will actually look like.

Refined exit criteria:

- **Determinism gate:** the same backtest definition (data hash + code commit + config) produces byte-identical results across two clean machines. CI enforces this.
- **Vectorized vs event-driven parity:** for the five seed strategies, the per-day PnL difference is bounded (`|Δ| < 5 bps daily, |Δ_total| < 25 bps annualised`) and a written explanation exists for why the residual is non-zero (slippage, intra-bar fills, dividend timing).
- **Walk-forward correctness:** rolling-window WFO produces non-overlapping train/test splits; no row used in training appears in the corresponding test fold.
- **Cost model installed and used:** every fill goes through commission + spread + market-impact (square-root law); zero-cost backtests are explicitly opt-in via a flag, never default.
- **Five seed strategies live:** momentum (cross-sectional), mean-reversion (Bollinger Z), pairs (cointegration), factor blend (Fama-French + quality), simple ML (XGBoost return forecast).
- **Reproducibility hash on every run:** `(data_hash, universe_hash, code_commit, config_hash) → result_hash`.

---

## 2. Scope Boundaries

| In | Out |
|---|---|
| Daily-frequency vectorized + event-driven | Tick-level event-driven (Phase 8 territory) |
| Equity, ETF universes | Options-pricing backtests (deferred) |
| Walk-forward, K-fold (CPCV later) | Combinatorial purged CV — write the interface, defer |
| Optuna for HPO | Distributed HPO across cluster (Phase 10 may add Ray) |
| Five seed strategies | Strategy zoo / market-microstructure strategies |
| Metrics module | Live PnL attribution (Phase 4) |
| Strategy registry pinned to data + code | Model serving (Phase 7) |

The deflated Sharpe and CPCV (combinatorial purged CV) machinery is *interfaces only* in this phase — production usage waits until we have enough strategies and parameter sweeps to make the multiple-testing problem material.

---

## 3. Week-by-Week Breakdown

### Week 9 — Engine Skeleton
- Define `Strategy` and `BacktestEngine` interfaces; freeze them now, change them never without a version bump.
- Vectorized engine: pandas + numpy core, no business logic yet.
- `BacktestRun` entity, registry tables, hash function.

### Week 10 — Cost Model + Event-Driven Skeleton
- Cost model (commission, spread, square-root market impact) as a pluggable component.
- Event-driven engine skeleton: order book event loop, latency simulator, fills.
- Wire vectorized engine to the cost model.

### Week 11 — Two Seed Strategies
- Momentum (12-1 cross-sectional, top decile long, bottom decile short).
- Mean reversion (Bollinger Z-score, single-name).
- Both run on both engines; document parity within bounds.

### Week 12 — WFO + Optuna
- Walk-forward engine: rolling, anchored, expanding modes.
- Optuna integration; parameter spaces declared in strategy class.
- Optimization run produces a study artifact stored in MLflow.

### Week 13 — Three More Strategies + Metrics
- Pairs trading (Engle-Granger cointegration, Z-score entry/exit).
- Factor blend (size, value, momentum, quality factors).
- XGBoost return forecast (next-day classification, meta-labeled).
- Metrics module: Sharpe, Sortino, Calmar, max DD, VaR/CVaR, turnover, hit ratio, factor attribution skeleton.

### Week 14 — Determinism + Monte Carlo + Reproducibility
- Monte Carlo on returns (block bootstrap) and on parameters (perturbation analysis).
- CI determinism gate: cross-machine reproducibility hash.
- Strategy registry: hash-pinned, immutable past versions.
- Documentation pass + deflated Sharpe interface.

---

## 4. Component & Service Architecture

```
┌─────────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│  Strategy Registry  │───►│  Backtest Engine     │───►│  Result Store    │
│  (versioned)        │    │  ┌──────────────┐    │    │  (Postgres +     │
└─────────────────────┘    │  │ Vectorized   │    │    │   MLflow art.)   │
         ▲                 │  └──────────────┘    │    └──────────────────┘
         │                 │  ┌──────────────┐    │             ▲
┌─────────────────────┐    │  │ Event-driven │    │             │
│  Feature Store      │───►│  └──────────────┘    │             │
│  (Phase 2, PIT)     │    │  ┌──────────────┐    │             │
└─────────────────────┘    │  │ Cost Model   │    │    ┌──────────────────┐
                           │  └──────────────┘    │    │  Metrics &       │
                           │  ┌──────────────┐    │    │  Attribution     │
                           │  │ Slippage Sim │    │    │  Module          │
                           │  └──────────────┘    │    └──────────────────┘
                           └──────────┬───────────┘
                                      │
                           ┌──────────▼───────────┐
                           │  Optimization Layer  │
                           │  (Optuna + WFO)      │
                           └──────────────────────┘
```

The optimization layer is *outside* the engine, not a method on it. This matters: the engine runs one experiment per call, the optimizer choreographs many. Mixing them is how you get accidental data leakage.

---

## 5. Folder & File Structure

```
apps/
├─ research-runner/         # CLI + worker for backtest jobs
└─ optimizer-runner/        # Optuna study runner
libs/
├─ backtest/
│  ├─ engine/
│  │  ├─ vectorized.py
│  │  ├─ event_driven.py
│  │  └─ base.py            # Strategy/Engine ABCs
│  ├─ costs/
│  │  ├─ commission.py
│  │  ├─ spread.py
│  │  └─ market_impact.py   # square-root law + linear
│  ├─ slippage/
│  │  └─ models.py
│  ├─ wfo/
│  │  └─ split.py           # rolling, anchored, CPCV interface
│  ├─ metrics/
│  │  ├─ ratios.py          # Sharpe, Sortino, Calmar
│  │  ├─ drawdown.py
│  │  ├─ var_cvar.py
│  │  ├─ deflated_sharpe.py
│  │  └─ attribution.py
│  ├─ registry/
│  │  └─ strategy_registry.py
│  └─ reproducibility/
│     └─ hashing.py
├─ strategies/
│  ├─ momentum_xs.py
│  ├─ mean_reversion_bb.py
│  ├─ pairs_coint.py
│  ├─ factor_blend.py
│  └─ ml_xgb_forecast.py
└─ optimization/
   ├─ optuna_runner.py
   └─ params.py             # ParamSpace DSL
```

---

## 6. Data Model / Schema Changes

```sql
CREATE TABLE strategy_version (
    strategy_id    TEXT NOT NULL,
    version        SEMVER NOT NULL,                  -- via pgsemver
    code_commit    TEXT NOT NULL,                    -- git sha
    config         JSONB NOT NULL,
    param_space    JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy_id, version)
);

CREATE TABLE backtest_run (
    run_id           UUID PRIMARY KEY,
    strategy_id      TEXT NOT NULL,
    strategy_version SEMVER NOT NULL,
    engine           TEXT NOT NULL CHECK (engine IN ('vectorized','event_driven')),
    universe_hash    BYTEA NOT NULL,
    data_hash        BYTEA NOT NULL,
    code_commit      TEXT NOT NULL,
    config_hash      BYTEA NOT NULL,
    result_hash      BYTEA,                          -- populated after run
    period_from      DATE NOT NULL,
    period_to        DATE NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    status           TEXT NOT NULL,                  -- queued|running|done|failed
    seed             BIGINT NOT NULL,
    cost_model       JSONB NOT NULL,
    notes            TEXT
);
CREATE INDEX ON backtest_run (strategy_id, period_from, period_to);
CREATE INDEX ON backtest_run (result_hash);

CREATE TABLE backtest_metric (
    run_id   UUID NOT NULL REFERENCES backtest_run,
    name     TEXT NOT NULL,
    value    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, name)
);

CREATE TABLE backtest_position_daily (
    run_id    UUID NOT NULL,
    ts        DATE NOT NULL,
    symbol    TEXT NOT NULL,
    weight    DOUBLE PRECISION NOT NULL,
    pnl       DOUBLE PRECISION,
    PRIMARY KEY (run_id, ts, symbol)
);
SELECT create_hypertable('backtest_position_daily', 'ts', chunk_time_interval => INTERVAL '90 days');

CREATE TABLE optimization_study (
    study_id     UUID PRIMARY KEY,
    strategy_id  TEXT NOT NULL,
    objective    TEXT NOT NULL,
    n_trials     INT NOT NULL,
    best_params  JSONB,
    started_at   TIMESTAMPTZ DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

CREATE TABLE optimization_trial (
    study_id     UUID NOT NULL REFERENCES optimization_study,
    trial_no     INT NOT NULL,
    params       JSONB NOT NULL,
    value        DOUBLE PRECISION,
    state        TEXT,
    PRIMARY KEY (study_id, trial_no)
);
```

The result_hash is computed from the canonicalised position series + cash series. Two identical-input runs must produce the same result_hash.

---

## 7. API Surface

```
POST /research/backtest                # submit run
GET  /research/backtest/{run_id}       # status
GET  /research/backtest/{run_id}/result
POST /research/optimize                # start study
GET  /research/optimize/{study_id}
GET  /research/strategies              # registry list
POST /research/strategies              # register version (CI-only)
```

Request shape (omit defaults):
```json
{
  "strategy_id": "momentum_xs",
  "version": "0.4.1",
  "engine": "event_driven",
  "universe": "sp500_pit",
  "period": {"from": "2015-01-01", "to": "2024-12-31"},
  "params": {"lookback": 252, "skip": 21, "deciles": 10},
  "cost_model": {"commission_bps": 0.5, "spread_bps": 1.0, "impact_coef": 0.1},
  "seed": 42,
  "wfo": {"mode": "rolling", "train_years": 5, "test_months": 6}
}
```

---

## 8. External Dependencies

| Library | Use | Notes |
|---|---|---|
| pandas, numpy | vectorized ops | pinned to a tested major |
| numba | hot-loop JIT in event-driven | optional; profile first |
| Optuna | HPO | TPE sampler default; SQLite-backed local, Postgres-backed prod |
| scikit-learn | ML utilities | `TimeSeriesSplit`, metrics |
| XGBoost | one ML strategy | classifier mode |
| statsmodels | cointegration + Engle-Granger | also for OLS in factor blend |
| empyrical (or our own) | risk metrics | thin reimplementation; empyrical is unmaintained |
| MLflow | experiment tracking | also stores artifacts to MinIO |
| cvxpy | factor optimisation | shared with Phase 4 |

**Why not zipline/backtrader/vectorbt?** Zipline is dead (Quantopian shutdown, fork is unmaintained). Backtrader is alive but the API is a museum and event-driven semantics are quirky. Vectorbt is impressive but proprietary in places and the licensing for institutional use is unclear; also it rolls everything into pandas in ways that fight you on transaction-cost integration. The engine is small enough (≈ 1500 lines) that owning it pays off in clarity, debuggability, and our specific cost-model integration.

---

## 9. Key Technical Decisions & Tradeoffs

**Two engines, not one.** Vectorized is fast (millions of bar-evaluations/sec), trivially parallelisable, and *wrong about execution*. Event-driven is slow but truthful: a 14:30:00 fill does not see 14:30:01 information, partial fills happen, latency exists. The contract is that any production trading decision must be event-driven-validated; vectorized is for screening.

**Cost model is non-optional.** A backtest without spread + commission + impact is fiction. Defaults: `commission = 0.5 bps`, `spread = 1 bp`, `impact = 0.1 * (volume_traded / ADV)^0.5 * sigma_daily`. The `impact_coef` is calibrated against TCA literature (Almgren et al.) but is a conservative MVP; real calibration is a quarter of work in itself.

**Optuna over Hyperopt.** Optuna's API is friendlier, the pruning interface is clean, and it integrates with MLflow out of the box. Hyperopt is older and has worse docs.

**Walk-forward over k-fold.** k-fold time-series CV leaks unless you purge gaps and embargo (de Prado's CPCV). For MVP we use rolling/anchored WFO; the CPCV interface is stubbed for when we have enough strategy variants to need it.

**Multiprocessing > Ray for Phase 3.** Backtests are CPU-bound but state-light; `concurrent.futures.ProcessPoolExecutor` does the job. Ray gets earned in Phase 7 when we want to schedule across heterogeneous workloads (NLP + backtest + opt).

**Determinism is a hard requirement.** Seed every RNG (numpy, python, scikit, xgboost). Pin BLAS thread count via `OMP_NUM_THREADS=1` in CI determinism runs (BLAS non-determinism eats reproducibility silently).

**Strategy interface signature:**
```python
class Strategy(Protocol):
    id: str
    version: str
    param_space: ParamSpace
    def generate_signals(
        self,
        data: PITDataView,            # Phase 2 view; raises on lookahead
        params: Mapping[str, Any],
        rng: np.random.Generator,
    ) -> SignalFrame: ...
```
The `PITDataView` is what makes lookahead structurally hard: any access at time `t` is restricted to rows with `as_of_ts <= t`.

---

## 10. Risks, Failure Modes & Mitigations

| Risk | Mitigation |
|---|---|
| Multiple-testing inflated Sharpe | Deflated Sharpe (Bailey & López de Prado); track number of trials per study |
| Lookahead via misuse of `data.shift(-1)` | PITDataView API forbids future indexing; lint rule rejects `shift(<0)` in strategy code |
| Survivorship in universe | Phase 2 universe with `as_of_ts`; backtest engine only consumes that |
| Slippage assumed lower than reality | Calibrate impact coefficient against post-Phase-8 live fills; track `cost_model_version` per run |
| Cost model not used (`zero_costs=True` left on) | Default is *non-zero*; `zero_costs` requires CLI flag and is logged loudly |
| Non-deterministic BLAS | `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1` in determinism gate |
| ML strategy data leakage via target encoding | All encodings use prior-window stats only; unit tests check for leakage |
| Overfitting via many parameter sweeps | Hold out a frozen test period that no optimization ever touches |
| Float drift across machines | Compare result_hash on rounded (e.g., 8-decimal) outputs |
| Memory blow-up on large universe | Chunked computation; `dtype` discipline (`float32` where safe) |

---

## 11. Testing Strategy

**Golden tests.** A handful of strategies + tiny synthetic universes with hand-computed expected returns. Any drift fails CI.

**Vectorized vs event-driven parity test.** Run both engines on each seed strategy on a 2-year window; assert daily PnL difference within 5 bps.

**PIT property test.** Construct a strategy that intentionally tries to read `t+1`; assert PITDataView raises.

**Determinism CI gate.** Two runs of the same backtest config on different runners → same result_hash.

**Cost model regression.** Calibration suite: known-trade-size scenarios produce expected post-cost PnL within 1 bp.

**Cointegration test correctness.** Pre-computed cointegrated pairs (synthetic) → strategy produces the right Z-score path.

**Optuna pruning test.** Mock objective with fast-bad and slow-good trials; assert pruning kills bad ones early.

**Reproducibility audit.** Random sample of 10 historical runs/week; re-run with same hashes; assert `result_hash` matches.

---

## 12. Observability Hooks

- `bt_run_duration_seconds{engine,strategy}` histogram.
- `bt_lookahead_violations_total` counter (should always be 0).
- `bt_determinism_failures_total` counter (alert on any).
- `optuna_trial_duration_seconds`, `optuna_trial_pruned_total`.
- Per-run trace: span tree of the backtest stages (data load → signal gen → portfolio formation → cost calc → metrics).
- MLflow params, metrics, artefacts: full equity curve, position series, factor exposures.

---

## 13. Definition of Done

- [ ] Five seed strategies run on both engines with parity within bounds.
- [ ] WFO produces non-overlapping splits proven by tests.
- [ ] Cost model integrated; `zero_costs` requires explicit flag and is logged.
- [ ] Determinism gate green in CI on two runners.
- [ ] Optuna study end-to-end: 200 trials on momentum_xs in <30 min on a dev machine.
- [ ] Strategy registry CLI: `astraeus strategies register/list/show`.
- [ ] MLflow UI shows runs with artifacts.
- [ ] Lookahead red-team test: intentionally bad strategy fails closed.
- [ ] Documentation: each metric has a docstring with formula + assumption.

---

## 14. Interview Talking Points

- **Why most retail backtests lie.** Survivorship + lookahead + zero costs + multiple testing. We architecturally prevent the first two and operationally guard against the next two.
- **Deflated Sharpe.** Naive Sharpe inflates with the number of trials. Deflated Sharpe ratio (DSR) corrects for selection bias; we track trial counts per study.
- **CPCV vs k-fold.** Time series leak if you naively k-fold. CPCV with purging and embargo addresses both information leakage and overlap. Discuss the cost: many folds, but defensible.
- **Square-root market impact.** Why this functional form is the literature consensus (Almgren). Where it breaks down (large illiquid trades).
- **Two-engine pattern.** Vectorized for screening, event-driven for honesty. Same separation Renaissance/Two Sigma describe publicly.
- **Determinism as a CI gate.** Reproducibility is a property of the pipeline, not a hope.

---

## 15. Open Questions

1. Do we want CPCV as a hard requirement before strategy promotion to Phase 7? Lean yes by Phase 7 cutover.
2. Numba is appealing for event-driven hot loops; profile first, decide in Week 10.
3. How do we surface deflated Sharpe in the UI without confusing reviewers? Dual display: raw Sharpe with DSR badge.
4. Do we backfill an alternative cost model (e.g., Kissell-Glantz) for sensitivity analysis? Stretch goal.
5. When does CPU parallelism stop being enough? Track p99 study duration; if it grows past ~2h regularly, plan Ray.

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

Phase 3 changes the *least* under scope mode — the backtester is the resume centerpiece, and the rigor doesn't get cheaper.

**Adjustments**

- **Compute:** local CPU only. Ray and distributed Optuna are descoped. A 16-core laptop or a $40/mo dedicated VPS is enough for the ~150-name universe.
- **Universe:** the smaller Phase 1 universe means a full walk-forward sweep finishes in tens of minutes, not hours. This is a feature, not a regression — iteration speed > scale theatre.
- **Strategies:** the five seed strategies (momentum, mean-reversion, pairs, factor blend, ML return forecast) all stay. Don't cut any — the breadth is what makes the project credible to a quant interviewer.
- **CPCV, Deflated Sharpe, walk-forward determinism gate:** stay. These are *the* differentiators; cutting them removes the reason this phase exists.
- **Live trading bridge:** when a strategy graduates to Phase 8, the bar is "stable Sharpe ≥ 1.0 over walk-forward + 3 months of paper-traded forward test," not "passes a few backtests." See Phase 8 scope addendum.

**What stays (resume-load-bearing)**

- Vectorized + event-driven parity, transaction-cost model, walk-forward, Optuna with anti-overfitting penalties, CPCV, deflated Sharpe, strategy registry with hash-pinning, determinism gate in CI. All of it.

**Budget impact:** $0/mo additional.
