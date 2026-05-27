# Phase 3 — Strategy Research Engine

**Window:** Weeks 9–14 (5 weeks, 1–3 engineers)
**Prerequisites assumed live:** Phase 0 scaffolding, Phase 1 market data + lineage, Phase 2 PIT feature store + survivorship-aware universe.
**Downstream consumers:** Phase 4 (portfolio construction), Phase 7 (recommendation engine), Phase 9 (research UI).

---

## 1. Goals & Non-Goals

### Goals

1. A research engine that produces backtest results a quant would defend in a meeting: PIT-correct, survivorship-aware, with realistic execution costs.
2. **Two engines**, one strategy interface. Vectorized for screening tens of thousands of parameter combos; event-driven for the truth before any candidate is promoted.
3. A **strategy registry** where every backtest run is content-addressable and reproducible: same commit + same data lineage hash + same seeds → byte-identical results on a clean machine.
4. Walk-forward optimization with Bayesian search (Optuna), Monte Carlo on returns and parameters, deflated Sharpe to keep us honest about p-hacking.
5. **Five reference strategies** spanning the major archetypes (momentum, mean-reversion, pairs, factor blend, ML) — proof the framework generalizes, and seed alpha for Phase 7.
6. Metrics module covering risk-adjusted return, drawdown, tail risk, attribution.
7. A reconciliation harness that proves the two engines agree within a known, explained tolerance band.

### Explicit Non-Goals (Phase 3)

- **No live trading, no paper trading.** Order routing, broker integration, kill switches → Phase 8.
- **No options.** Vol surface, greeks, exotic payoffs are out. The cost model and event loop assume linear instruments.
- **No futures roll handling.** Continuous contract construction, calendar-spread costs, basis risk all out.
- **No intraday strategies.** Bar resolution is daily (1d) by default; the engine accepts 1m bars but no signal in this phase trades intraday. Microstructure-grade simulation deferred.
- **No multi-currency portfolios.** USD-denominated only. FX hedging deferred.
- **No live alt-data integration.** Phase 5 fills sentiment features into the feature store; we consume what's there, but no Phase 3 strategy depends on alt-data.
- **No production scaling.** Backtests run on a workstation or single-node Ray cluster. K8s scheduling, distributed sweeps → Phase 10.

---

## 2. Detailed Work Breakdown

### Week 1 — Core scaffolding (must ship before anything else)

| ID | Task | Days |
|---|---|---|
| C1 | `libs/strategy_core` package: `Strategy` protocol, `Bar`, `Signal`, `Target`, `Order`, `Fill`, `Portfolio` dataclasses (frozen, hashable) | 2 |
| C2 | `DataDependency` declaration API: feature names, universe, calendar, history horizon, frequency. Resolves against Phase 2 feature store | 1 |
| C3 | `BacktestRun` schema (Postgres) + `StrategyEntry` registry table | 1 |
| C4 | Content-hashing utility: `hash(code_commit_sha, params_json_canonical, data_lineage_hashes, feature_versions, seed)` → run_id | 1 |
| C5 | Random seed plumbing: every stochastic component takes seed from config; numpy/torch/random initialized at run entry | 0.5 |
| C6 | CLI: `astraeus backtest run <strategy_id> --params <yaml> --range <date-range>` | 1 |

### Week 2 — Vectorized engine + cost model v1

| ID | Task | Days |
|---|---|---|
| V1 | Polars-based PIT join engine: feature panel × universe × calendar | 2 |
| V2 | Vectorized executor: targets → positions → returns → PnL with daily rebal | 2 |
| V3 | Universe-change correctness: delistings, IPOs, ticker changes pulled from Phase 1 corp-action table | 1 |
| V4 | Cost model v1: per-share commission, half-spread proxy, square-root impact | 1.5 |
| V5 | Metrics module: Sharpe, Sortino, Calmar, max DD, hit ratio, turnover, VaR/CVaR (historical + parametric) | 1.5 |

### Week 3 — Event-driven engine

| ID | Task | Days |
|---|---|---|
| E1 | Event loop: `MarketEvent → SignalEvent → OrderEvent → FillEvent → PortfolioEvent`. Priority queue keyed by `(ts, seq, type_priority)` | 2 |
| E2 | Market data replay from Phase 1 (uses lineage hash to pin exact data version) | 1 |
| E3 | Order book / depth model: synthetic L1 from OHLCV; optional L2 replay if Phase 1 has depth | 2 |
| E4 | Fill model: market, limit, stop, MOC. Partial fills, halts, gaps. Latency injection | 2 |
| E5 | Cost model v2: shared with vectorized; event engine adds latency-conditional slippage | 0.5 |

### Week 4 — Optimization, walk-forward, MC, registry

| ID | Task | Days |
|---|---|---|
| O1 | Walk-forward harness: anchored + rolling, train/val/OOS, purged k-fold for ML strategies (López de Prado purge + embargo) | 2 |
| O2 | Optuna integration: study persistence in Postgres, parallelism via Ray (single node ok) | 1.5 |
| O3 | Monte Carlo: (a) bootstrap returns (stationary block bootstrap), (b) parameter perturbation sweeps | 1.5 |
| O4 | Deflated Sharpe + Probabilistic Sharpe (Bailey & López de Prado 2014) | 1 |
| O5 | Strategy registry: write API, query API, artifact upload (MinIO) for equity curves, signal panels, fill logs | 1 |
| O6 | Two-machine reproducibility CI job | 1 |

### Week 5 — Strategies, attribution, reconciliation, polish

| ID | Task | Days |
|---|---|---|
| S1 | Momentum (12-1 cross-sectional) | 1 |
| S2 | Mean-reversion (5-day reversal, liquid universe) | 1 |
| S3 | Pairs (cointegration screen + z-score entry) | 2 |
| S4 | Factor blend (value + quality + momentum + low-vol, equal-risk-weighted) | 1.5 |
| S5 | ML — XGBoost return forecast with meta-labeling | 2 |
| F1 | Factor attribution module (Fama-French 3 + Carhart momentum) | 1 |
| R1 | Reconciliation harness: vectorized vs event-driven on all 5 strategies, tolerance report | 1 |
| D1 | Documentation + notebook tutorial | 1 |

**Critical path:** C1–C4 → V1–V2 → E1–E4 → O1–O5 → R1. Strategies (S1–S5) and metrics parallelize off the core. With three engineers: one owns the engines, one owns optimization+registry, one owns strategies+metrics.

---

## 3. Two-Engine Architecture

### Why two engines

- **Vectorized only:** fast (10k parameter combos in minutes), but execution is fictional. Strategies that look great here die in the event-driven engine.
- **Event-driven only:** truthful, but slow. You cannot afford 10k Optuna trials.

The honest pipeline is: **screen with vectorized, promote candidates to event-driven, and refuse to ship a strategy that hasn't passed both.** A strategy whose vectorized Sharpe is 2.5 and event-driven Sharpe is 0.6 is telling you it depends on optimistic execution. That is a finding to surface.

### Where each is used

| Use case | Engine |
|---|---|
| Optuna hyperparameter sweep | Vectorized |
| Monte Carlo on bootstrapped returns | Vectorized (analytical from equity curve) |
| Monte Carlo on parameter perturbation | Vectorized |
| Walk-forward OOS validation | Event-driven (final OOS only); vectorized on train/val |
| Promotion gate to Phase 4 | **Both** — registry entry must contain both engines' results |
| Strategy debugging / fill diagnostics | Event-driven |
| Cross-machine reproducibility CI | Both |

### Shared contract

Both engines consume the same `Strategy` object. The strategy never sees the engine type:

- The vectorized engine calls `generate_targets` over the full panel at once and computes returns by lagging signals one bar.
- The event-driven engine calls `on_bar` per (ts, symbol) tuple in temporal order, then runs the order book + fill model, then routes fills back to the strategy via `on_fill`.

The contract: **strategy code receives only data dated `<= as_of_ts` and emits decisions for `as_of_ts + 1` execution.** Enforced at the data layer, not by trust.

### Reconciliation test

Both engines run the same five reference strategies on the same date range with the same seed. Tolerance:

| Metric | Tolerance |
|---|---|
| Annualized return | ≤ 30 bps absolute deviation |
| Annualized Sharpe | ≤ 0.15 absolute deviation |
| Max drawdown | ≤ 100 bps absolute deviation |
| Turnover | ≤ 5% relative deviation |

Two acceptable causes for divergence:
1. **Cost model headroom** — event-driven applies depth-conditional impact; vectorized uses average. Quantify and accept.
2. **Fill timing** — event-driven respects partial fills and halts. Quantify and accept.

Anything else fails CI. A Sharpe gap > 0.15 not attributable to cost or timing is a leak — usually a look-ahead in the strategy's feature transform.

---

## 4. Strategy Interface

A strategy is a Python class implementing the `Strategy` protocol.

### Protocol (informal)

```python
class Strategy(Protocol):
    name: str
    version: str  # semver; bumped on logic change
    dependencies: DataDependency

    def generate_targets(
        self,
        as_of_ts: pd.Timestamp,
        feature_panel: pl.LazyFrame,   # rows ts <= as_of_ts only
        universe: list[str],
        portfolio_state: PortfolioState,
        params: dict,
    ) -> dict[str, float]:
        """Return {symbol: target_weight}. Sum |weights| <= 1 by convention."""

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Order]: ...
    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None: ...
```

Three semantic rules enforced at the engine level:

1. **PIT enforcement.** `feature_panel` is filtered before being handed to the strategy. Audited via a fuzzer in CI that injects future-dated rows and asserts the strategy never references them.
2. **Idempotence.** `generate_targets(as_of_ts, ...)` called twice with the same inputs returns identical output. Verified by hash of `(inputs, output)` per call.
3. **Deterministic randomness.** Any randomness goes through `ctx.rng` (a seeded `np.random.Generator`). Direct `np.random.randn()` is banned; CI greps for it.

### Declaring data dependencies

```python
DataDependency(
    features=[
        FeatureRef("returns_1d", version="1.2.0"),
        FeatureRef("dollar_volume_20d", version="1.0.0"),
        FeatureRef("market_cap", version="1.1.0"),
    ],
    universe=UniverseRef("sp500_pit", version="2024.10"),
    calendar="XNYS",
    frequency="1d",
    history_horizon=timedelta(days=400),
)
```

The registry resolves these against Phase 2's feature store and pins exact versions in the run record.

### Hash-pinning a strategy

```
strategy_hash = sha256(
    code_commit_sha             # last commit touching strategy file + imports
    + canonical_json(params)
    + dependency_resolution_hash  # hashes of resolved feature versions + universe snapshot id
    + engine_version
    + cost_model_version
)
```

The `code_commit_sha` is the commit at which the *strategy file* and its imports were last modified — extracted via `git log -1 --format=%H -- <file>`. A doc-only commit doesn't invalidate prior runs.

### Worked example: 12-1 cross-sectional momentum

```python
class Momentum_12_1(Strategy):
    name = "momentum_12_1"
    version = "1.0.0"
    dependencies = DataDependency(
        features=[
            FeatureRef("returns_1d", version="1.2.0"),
            FeatureRef("dollar_volume_20d", version="1.0.0"),
        ],
        universe=UniverseRef("us_equity_top_2000_pit", version="2024.10"),
        calendar="XNYS",
        frequency="1d",
        history_horizon=timedelta(days=300),
    )

    def generate_targets(self, as_of_ts, feature_panel, universe, state, params):
        # 1. Filter universe to liquidity floor (PIT)
        # 2. Compute t-252 to t-21 cumulative return per symbol
        # 3. Cross-sectional rank, z-score
        # 4. Long top decile, short bottom decile, equal-weighted within deciles
        # 5. Apply gross/net exposure caps from params
        # 6. Return target weights summing to gross_target
        ...
```

Honesty checks in this strategy:
- Liquidity floor uses `as_of_ts`-dated dollar volume.
- Universe is PIT membership of "top 2000 by market cap as of rebalance date".
- t-252 to t-21 explicitly excludes most recent month.

---

## 5. Vectorized Backtester

### Library choice: Polars (with pandas escape hatch)

- Lazy execution: PIT join can be planned and pushed down without materializing intermediates.
- Native columnar streaming: 20-year × 3000-symbol × 50-feature panel doesn't fit in pandas memory.
- Deterministic by default.
- 5–20× faster on the joins that dominate vectorized backtest cost.

We **reject** vectorbt (opinionated framework with its own portfolio/event abstractions), zipline (unmaintained), backtrader (single-asset bias, slow).

### PIT join at the dataframe level

The vectorized engine produces a single panel:
```
| ts | symbol | feature_1 | feature_2 | ... | universe_member | calendar_open |
```

with the invariant: **every row's `feature_n` value was knowable at `ts`**.

Procedure:
1. Resolve universe membership panel from Phase 2.
2. For each feature, query feature store with `as_of_ts <= ts` and forward-fill within each symbol up to its delisting date. Forward-fill **only** for low-frequency features.
3. Join all features on `(ts, symbol)` using Polars lazy `join` with `how="left"`. NaN policy is per-feature.

### Honesty under universe changes

- Universe panel is hard constraint. If symbol X exits the S&P 500 on day t, day t+1 has `in_universe=False` for X.
- IPOs are first-tradable on listing date + 1.
- Delistings: positions in delisting symbol are marked at last known price; liquidation PnL is delisting return from Phase 1.
- **Survivorship audit:** CI test runs each reference strategy with biased universe vs PIT universe. Sharpe gap < 0.1 is suspicious.

### Vectorized execution model

After the strategy returns target weights:
1. Compute target dollar position = target_weight × portfolio_value.
2. Compute trade size = target - current position.
3. Apply cost model row-wise: spread + commission + market impact (square-root law).
4. Settle at next bar's open by default.
5. Compute next-bar return on settled position.

---

## 6. Event-Driven Backtester

### Event loop

Single priority-queue loop keyed by `(ts, sequence, type_priority)`:

```
event_types_in_priority_order = [
    MarketDataEvent,    # bar / tick from replay
    StrategyEvent,      # on_bar fires, may emit OrderEvent
    OrderEvent,         # submitted to simulator
    FillEvent,          # simulator returns fills
    PortfolioEvent,     # state update
]
```

Single-threaded. Determinism beats speed; parallelism comes from running multiple backtests concurrently.

### Market data replay

Reads from Phase 1's TimescaleDB tables. Records lineage hash of every dataset touched into the run record.

### Order book / depth model

Two-tier model:

**Tier 1 (default for daily):** synthetic L1 from OHLCV. Spread from Roll (1984) or Corwin-Schultz (2012) high-low estimator. Top-of-book size is fraction of daily volume (default 1%).

**Tier 2 (intraday, opt-in):** L2 replay if Phase 1 has tick-level depth.

```
best_bid(ts, symbol) -> price
best_ask(ts, symbol) -> price
top_of_book_size(ts, symbol, side) -> shares
depth(ts, symbol, side, price_levels) -> list[(price, size)]   # tier 2
```

### Fill model

- **MARKET:** filled at next bar open + half-spread + market impact. Capped at top-of-book × N.
- **LIMIT:** filled if next bar's range crosses limit price. Partial-fill probability proportional to price-time priority.
- **STOP:** triggered at first bar where price crosses stop, then converts to MARKET.
- **MOC/MOO:** filled at close/open with reduced impact.

### Partial fills, halts, gaps

- **Partial fill:** child order remains for next bar with `attempts` counter.
- **Halt:** Phase 1 publishes `trading_status` per (ts, symbol). Halted symbols generate no fills.
- **Gap:** stop fill is at next available price (open of gap bar), not stop price. Realistic and painful.
- **Limit-up/limit-down:** treated as halts.

---

## 7. Transaction Cost Model

### 7.1 Commission

Tiered, configurable per broker profile:

| Profile | Per-share | Min | Max |
|---|---|---|---|
| `interactive_brokers_pro` | $0.0035 | $0.35/order | 1% of trade value |
| `alpaca_zero` | $0.00 | $0.00 | $0.00 |

Crypto profile bps-based (Binance default 10 bps maker / 10 bps taker).

### 7.2 Spread

Three estimators:
1. **`fixed_bps`** (default for crypto)
2. **`roll_estimator`**: Roll (1984) implied spread from daily bar serial covariance
3. **`corwin_schultz`**: high-low estimator. Default for equity profile.
4. **`quote_replay`**: realized half-spread from intraday quotes. Most accurate.

Cost: `0.5 × spread_bps × |trade_dollars|`.

### 7.3 Market impact: square-root law

```
impact_bps = sigma_daily_bps × eta × sqrt(|Q| / ADV)
```

- `sigma_daily_bps`: 20-day realized vol in bps
- `Q`: trade quantity in shares
- `ADV`: 20-day average daily volume (PIT)
- `eta`: 0.5 default (Almgren et al. 2005 fits)

Sources documented in code:
- Almgren, Thum, Hauptmann, Li (2005), "Direct estimation of equity market impact"
- Kyle (1985), "Continuous auctions and insider trading"
- Frazzini, Israel, Moskowitz (2018), "Trading costs"

### 7.4 Slippage simulator

- Normal noise term, `N(0, slip_bps)`, default `slip_bps = 2` for liquid US equities.
- Latency-conditional component: if order arrives `tau` ms after bar starts, apply `tau / bar_duration × bar_range_bps` adverse drift.

### 7.5 Calibration

```
astraeus costs calibrate --venue alpaca --period 2023-01:2024-12
```

Refits `eta` and `slip_bps` per liquidity bucket from realized fills (Phase 8).

---

## 8. Walk-Forward + Optimization

### Walk-forward windowing

**Anchored (expanding):** train grows over time, OOS slides.
**Rolling (fixed):** train slides at fixed length.

Default: 70% train, 15% val, 15% OOS, with **purge** and **embargo** between train/val and val/OOS (López de Prado 2018, Ch. 7). Purge ≥ max(feature_horizon, label_horizon); embargo = 1% of train length, min 5 days.

For ML strategies, **purged k-fold cross-validation** replaces simple split.

### Optuna integration

- Each study persists in Postgres.
- Sampler: TPE with `n_startup_trials=20`.
- Pruner: `MedianPruner` only for ML.
- Parallelism: Ray on single node, 8 workers default.
- Each trial is a vectorized backtest. Event-driven only after top-k selected.

### Monte Carlo

**(a) Bootstrapped returns.** Stationary block bootstrap (Politis & Romano 1994), block length per Politis & White (2004). 1000 paths default. Reports 5th/95th percentile band.

**(b) Parameter perturbation.** Around optimal params, perturb each ±1σ on a grid. 200 runs default. A sharp peak at the optimum is overfitting; wide plateau is more credible.

### Multiple-testing correction: deflated Sharpe

Deflated Sharpe Ratio (Bailey & López de Prado 2014):
```
DSR = PSR with σ_SR adjusted for trial count and skew/kurtosis
PSR = Pr(true SR > SR* | observed SR)
```

Strategy doesn't get registered as "promoted" unless `DSR(SR*) > 0.95` against benchmark `SR* = 0.5`.

---

## 9. Strategy Registry

### Schema (Postgres)

```sql
TABLE strategy (
    id              UUID PK,
    name            TEXT NOT NULL,
    version         TEXT NOT NULL,
    code_commit_sha TEXT NOT NULL,
    code_path       TEXT NOT NULL,
    params_default  JSONB,
    dependency_spec JSONB,
    strategy_hash   TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ,
    created_by      TEXT,
    description     TEXT,
    status          TEXT  -- 'draft' | 'candidate' | 'promoted' | 'retired'
)

TABLE backtest_run (
    id                   UUID PK,
    strategy_id          UUID FK,
    run_hash             TEXT NOT NULL UNIQUE,
    engine               TEXT NOT NULL,         -- 'vectorized' | 'event_driven'
    engine_version       TEXT NOT NULL,
    cost_model_version   TEXT NOT NULL,
    params               JSONB NOT NULL,
    seed                 BIGINT NOT NULL,
    date_range_start     DATE NOT NULL,
    date_range_end       DATE NOT NULL,
    universe_snapshot_id TEXT NOT NULL,
    feature_versions     JSONB NOT NULL,
    data_lineage_hashes  JSONB NOT NULL,
    metrics              JSONB NOT NULL,
    artifacts_uri        TEXT NOT NULL,
    duration_seconds     INT,
    machine_fingerprint  JSONB,
    created_at           TIMESTAMPTZ,
    status               TEXT
)

TABLE walk_forward_run (
    id            UUID PK,
    strategy_id   UUID FK,
    config        JSONB,
    summary       JSONB,
    child_run_ids UUID[]
)

TABLE optuna_study (
    name         TEXT PK,
    strategy_id  UUID FK,
    sampler      TEXT,
    n_trials     INT,
    best_params  JSONB,
    best_value   DOUBLE PRECISION,
    deflated_sr  DOUBLE PRECISION
)
```

### Artifact storage

Under `s3://astraeus-runs/<run_hash>/`:
```
equity_curve.parquet
positions.parquet
fills.parquet                  # event-driven only
signals.parquet
metrics.json
config.yaml
git_diff.patch                 # FAILS run if non-empty in CI
machine_info.json
```

### Reproducibility from a registry entry

Given a `run_hash`:
1. `git checkout <code_commit_sha>`
2. Restore env from lockfile in `machine_info.json`
3. Resolve features at pinned versions from Phase 2
4. Rerun: `astraeus backtest replay <run_hash>`
5. Compare new `run_hash` to old. Equal → pass.

---

## 10. Metrics Module

### Risk-adjusted return

| Metric | Formula | Notes |
|---|---|---|
| Annualized return | `(1 + r̄)^252 - 1` | |
| Annualized vol | `σ × sqrt(252)` | sample stdev |
| Sharpe | `(r̄ - r_f/252) / σ × sqrt(252)` | r_f from FRED 3m T-bill |
| Sortino | `(r̄ - r_f/252) / σ_downside × sqrt(252)` | downside σ uses returns < MAR |
| Calmar | `annualized_return / |max_DD|` | |
| Information ratio | `(r̄_p - r̄_b) / σ(r_p - r_b) × sqrt(252)` | b = SPY default |
| Probabilistic SR | per Bailey & López de Prado 2012 | |
| Deflated SR | per Bailey & López de Prado 2014 | |
| Sharpe CI | bootstrap or Lo (2002) closed-form | |

### Drawdown / tail risk

| Metric | Formula |
|---|---|
| Max drawdown | `max(peak - trough) / peak` |
| Max DD duration | days from peak to recovery |
| Avg DD | mean of all drawdowns > 1% |
| VaR (historical) | 5th percentile of daily returns |
| VaR (parametric) | `-(μ + z_0.05 × σ)`, z=1.645 |
| CVaR | mean of returns ≤ VaR |
| Tail ratio | `q_95 / |q_5|` |
| Skewness | sample skew |
| Kurtosis | sample excess kurtosis |

### Activity / cost

| Metric | Definition |
|---|---|
| Hit ratio | by trade |
| Avg win / avg loss | by trade |
| Profit factor | `Σ wins / |Σ losses|` |
| Turnover | annualized |
| Avg holding days | per closed position |
| Total cost bps | spread + commission + impact |

### Factor attribution

OLS time-series regression:
```
r_p = α + β_M × MKT + β_S × SMB + β_H × HML + β_U × UMD + ε
```

Factor returns from Ken French data library. Output: factor exposures (β), R², alpha (and t-stat), residual return.

### Confidence intervals

- **Lo (2002) closed-form** for Sharpe (assumes iid; flagged when violated).
- **Stationary block bootstrap** for everything else.

Reported as `0.94 [0.71, 1.18]`.

---

## 11. First Five Strategies

### 11.1 Cross-Sectional Momentum (12-1)

**Thesis.** Stocks that outperformed over past 12 months (excluding last) tend to continue (Jegadeesh & Titman 1993; Asness, Moskowitz, Pedersen 2013).

**Universe.** Top 2000 US equities by market cap, PIT.

**Logic.** Monthly rebalance. Compute t-252 to t-21 return. Cross-sectional z-score after liquidity filter. Long top decile, short bottom decile, equal-weight. Gross 200%, net 0%.

**Expected behavior.** Sharpe 0.5–0.9 raw; meaningful drawdowns in 2009 and 2020 (momentum crashes). High turnover (~2–4×/year).

### 11.2 Short-Horizon Mean Reversion

**Thesis.** Liquid stocks overreact to short-term moves; 5-day winners underperform losers over next 5 days (Lehmann 1990; Lo & MacKinlay 1990).

**Universe.** Top 1000 US equities by dollar volume.

**Logic.** Daily rebalance. Rank by t-5 to t-1 return. Long bottom quintile, short top quintile. Risk filter on volatility spikes.

**Expected behavior.** Pre-cost Sharpe 1.2–1.6, very high turnover (~50×/year). Post-cost Sharpe collapses to 0.3–0.6 — best test of cost model honesty.

### 11.3 Cointegration Pairs Trading

**Thesis.** Two assets driven by common factors form stationary spread (Gatev, Goetzmann, Rouwenhorst 2006).

**Universe.** Pairs within same GICS sub-industry, top 500 by liquidity.

**Logic.** Quarterly: Engle-Granger or Johansen test on candidate pairs. Daily: spread = log(p1) - β × log(p2), z-score over 60 days. Enter when |z| > 2; exit when |z| < 0.5. Stop on |z| > 4.

**Expected behavior.** Train Sharpe 0.6–1.0; OOS often degrades — good test for walk-forward and DSR. Cointegration breaks in regime shifts.

### 11.4 Factor Blend (Value + Quality + Momentum + Low Vol)

**Thesis.** Equal-risk-weighted blend of academic factors diversifies idiosyncratic factor risk (Asness & Frazzini 2013).

**Universe.** Russell 1000.

**Logic.** Monthly rebalance. For each factor, build long-short z-scored decile portfolio. Combine with equal-risk weights (inverse vol of recent 12-month return series). Gross 200%, net 0%, sector-neutralized.

**Expected behavior.** Sharpe 0.7–1.0 with lower max DD than any single factor. Benchmark for Phase 7's ensemble.

### 11.5 ML Return Forecast (XGBoost + Meta-Labeling)

**Thesis.** Cross-sectional ML on rich features forecasts next-week return. Meta-labeling (López de Prado 2018, Ch. 3) trains second model to predict primary's correctness, used for sizing.

**Universe.** Top 1000 US equities by liquidity.

**Logic.** Weekly rebalance. Primary: XGBoost binary classifier on ~50 cross-sectional features, target = sign of next-5d return. Purged 5-fold CV, embargo = 5 days. Meta: XGBoost classifier predicting was-primary-correct. Position size = meta prob × primary direction.

**Expected behavior.** Heavily overfittable. Raw Sharpe 1.5+ in train, 0.4–0.7 OOS. DSR adjustment after Optuna lands at 0.5–0.7 if anything is real.

---

## 12. Reproducibility Infrastructure

### Content-addressable runs
Every run identified by `run_hash`. Two runs with same hash MUST produce byte-identical artifacts.

### Deterministic random seeds
- Single `seed` field per run. Default: `42`.
- Propagates to `numpy.random.default_rng(seed)`, `random.seed(seed)`, `torch.manual_seed(seed)`, xgboost `random_state`, Optuna sampler seed, bootstrap RNG.
- Linter forbids `np.random.randn`, `random.random` outside seed-init module.
- `PYTHONHASHSEED=0` and `OMP_NUM_THREADS=1` enforced for reproducibility CI.

### Dependency lockfiles
- `pyproject.toml` + `uv.lock`. Lock includes hashes.
- `python_version` pinned. **Python 3.12**.
- C-library hashes (numpy, scipy, polars, xgboost) recorded in `machine_info.json`.
- Container image digest recorded.

### Two-machine reproducibility CI

Nightly GitHub Action:
1. Two distinct runners (different OS images: `ubuntu-22.04` + `macos-14`).
2. Run canonical backtest suite: 5 strategies × 1-year × default params.
3. Capture `run_hash` and `metrics.json`.
4. **Pass:** `metrics.json` matches byte-for-byte AND `run_hash` matches.
5. **Soft pass:** metrics differ within 1e-9 due to BLAS; hash equity curve at 8-decimal precision.
6. **Fail:** larger drift. Blocks merge.

This job's pass status is the literal exit criterion of Phase 3.

---

## 13. Contracts Exposed Downstream

### 13.1 Strategy registry API (read)

```
GET /api/strategies
GET /api/strategies/{strategy_id}
GET /api/strategies/{strategy_id}/runs?status=promoted&limit=10
GET /api/runs/{run_hash}
GET /api/runs/{run_hash}/artifacts/{name}
```

### 13.2 Run-results table

The `backtest_run` table is the primary interop surface. Phase 4/7 query directly with read-only DB credentials.

### 13.3 Signal output schema

Daily **signal panel** to MinIO + Postgres view:

```
signal_panel:
  ts            DATE NOT NULL
  symbol        TEXT NOT NULL
  strategy_id   UUID NOT NULL
  run_hash      TEXT NOT NULL
  raw_score     DOUBLE PRECISION    -- strategy's native score
  ranked_score  DOUBLE PRECISION    -- cross-sectional rank, [-1, 1]
  target_weight DOUBLE PRECISION    -- intended weight, pre-portfolio-construction
  confidence    DOUBLE PRECISION    -- [0, 1], strategy-specific
  PRIMARY KEY (ts, symbol, strategy_id)
```

Phase 7's ensembler consumes `ranked_score` + `confidence`. Schema published as Avro contract in `libs/contracts/`.

---

## 14. Exit Criteria Checklist

- [ ] `Strategy` protocol implemented; 5 reference strategies pass `mypy --strict`.
- [ ] Vectorized engine produces equity curves on 10 years × top 1000 universe in < 60s per strategy.
- [ ] Event-driven engine produces equity curves on 10 years × top 1000 universe in < 30 min per strategy.
- [ ] Cost model includes commission, spread (≥2 estimators), square-root impact, with eta exposed.
- [ ] Walk-forward harness with purge + embargo runs end-to-end on all 5 strategies.
- [ ] Optuna study persists in Postgres; resumable; parallelism via Ray on single node.
- [ ] Monte Carlo (a) bootstrapped returns and (b) parameter perturbation runnable from CLI on any registered run.
- [ ] DSR computed and gate-enforced at promotion: DSR > 0.95 vs SR* = 0.5.
- [ ] Strategy registry tables exist; every backtest run is content-addressable and replayable.
- [ ] Reconciliation harness runs all 5 strategies on both engines; deviation report fits §3 tolerance.
- [ ] **Two-machine reproducibility CI passes.** Run green ≥3 consecutive nights before phase exit.
- [ ] Factor attribution module produces FF3 + Carhart regression for any registered run.
- [ ] Documentation: tutorial notebook walks researcher from idea to promoted strategy in under an hour.
- [ ] Phase 4 team has reviewed signal output schema and signed off.

---

## 15. Risks & Open Questions

### Risk: survivorship bias leaking through universe drift
- **Mitigation:** Universe panel feeds in *as of `ts`*. CI test compares biased-universe vs PIT-universe Sharpes — gap < 0.1 is canary.
- **Open question.** Index reconstitutions: official effective date or announcement date? Default to effective; let strategies override.

### Risk: cost model miscalibrated, hiding impact
- **Mitigation.** Liquidity guardrails: every strategy declares `max_trade_fraction_of_adv` (default 1%). Engine refuses fills exceeding it. Metrics breaks out total cost in bps; cost > 100 bps gets yellow flag.
- **Open question.** Per-symbol calibration of `eta` is a research project. Phase 3 ships global.

### Risk: look-ahead in feature transforms
**Mitigations:**
1. Strategy interface forbids global transforms. Polars frame partitioned by `as_of_ts`. CI lints flag `.mean()`, `.std()`, `.quantile()` on the panel.
2. Reconciliation harness compares vectorized vs event-driven Sharpe. Look-ahead shows as anomalous gap.
3. **Synthetic future fuzz test:** corrupt future rows; if outputs change, leak found.

### Open question: ML strategy + Phase 5 sentiment
Phase 3 lands before Phase 5 stable. Architecture accommodates: dependencies as superset, Phase 5 features behind `--include-sentiment` flag default off.

### Open question: distributed Optuna
Single-node Ray fine for hundreds of trials. 10k-trial sweep wants distributed cluster (Phase 10).

### Risk: "two-machine" test passes by accident
GitHub runners on same OS image with same x86_64 family agree because they're effectively the same machine.
**Mitigation.** One runner must be different architecture (macOS arm64). Float bit-equivalence across architectures is hard; relax to 8-decimal cross-arch, demand bit-exactness same-arch.

### Open question: depth simulation level
Phase 3 strategies all daily; don't need queue position. Phase 8 will. Event loop accommodates L2 depth (tier 2 model), implementation is stub.

---

### Critical Files for Implementation

- `/Users/mukesh/python-projects/Astraeus/libs/strategy_core/src/astraeus/strategy_core/protocol.py`
- `/Users/mukesh/python-projects/Astraeus/libs/strategy_core/src/astraeus/strategy_core/cost_model.py`
- `/Users/mukesh/python-projects/Astraeus/apps/research/src/astraeus/research/engines/vectorized.py`
- `/Users/mukesh/python-projects/Astraeus/apps/research/src/astraeus/research/engines/event_driven.py`
- `/Users/mukesh/python-projects/Astraeus/apps/research/src/astraeus/research/registry/models.py`
