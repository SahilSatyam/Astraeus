# Phase 4 — Portfolio Construction & Risk

**Window:** Weeks 14–18 (4 weeks, 1–3 engineers)
**Upstream:** Phase 3 produces ranked signals (alpha forecasts + metadata) per asset per `as_of_ts`.
**Downstream:** Phase 7 consumes target portfolios + risk reports for the daily recommendation table; Phase 8 consumes approved portfolios for execution.
**Parallel:** Phase 5 (sentiment) and Phase 6 (agents) — Phase 6 produces view objects that this phase ingests for Black-Litterman.

---

## 1. Goals & Non-Goals

### Goals

- Deterministic, reproducible portfolio construction: given the same signals, covariance, and constraints, produce byte-identical weights.
- Four optimizers (MVO, Black-Litterman, risk parity, CVaR) sharing a common interface, constraint library, and solver glue.
- A risk engine that computes parametric, historical, and Monte Carlo VaR/CVaR plus four named stress scenarios, on every candidate portfolio, before it leaves the service.
- A risk validation gate that emits a structured pass/fail decision and a rejection log keyed back to the originating signal batch.
- A factor-model PnL attribution job (Fama-French 5 + momentum + idiosyncratic) running on realized portfolios.
- A daily orchestrated pipeline: signals → optimization → risk → attribution → published target portfolio.

### Non-Goals (out of scope for Phase 4)

- **No execution.** No order generation, no broker contact, no slippage realization. Phase 8 owns that.
- **No live order routing or smart order types.** This service produces *target weights*; Phase 7/8 decide how those become orders.
- **No real-time intraday rebalancing.** Daily cadence only. Intraday rebalancing belongs in a later phase.
- **No live alpha generation.** Signals are inputs from Phase 3.
- **No regime detection.** That's Phase 7 Stage 2. Phase 4 *consumes* a regime label as a covariance/constraint conditioner but does not compute it.
- **No model training infrastructure.** Factor model coefficients are estimated within the attribution module but the framework lives in Phase 2's research environment.
- **No HITL approval UI.** Phase 7 owns approvals.

### Hard guardrails

- Lookahead leakage: every input must carry `as_of_ts <= target_ts`. PIT semantics are enforced at the data-access layer (built in Phase 2) — Phase 4 fails loudly if any input violates this.
- A portfolio that fails risk validation is **never** silently mutated to pass. It is rejected, the rejection is logged with a machine-readable reason code, and a fallback policy (defined per-strategy) decides whether to retry with relaxed constraints, fall back to cash, or roll prior weights.

---

## 2. Detailed Work Breakdown

Roughly 4 weeks. Sizing in person-days assuming a single engineer of intermediate quant + Python competence; with two engineers the calendar compresses but the day count is similar.

### Week 1 — Foundations (≈8–10 person-days)

| ID    | Task                                                                                       | Days |
| ----- | ------------------------------------------------------------------------------------------ | ---- |
| P4-01 | `libs/portfolio/contracts.py`: Pydantic schemas (Signal, View, TargetPortfolio, RiskReport, RejectionReason) | 1    |
| P4-02 | DB migrations: `target_portfolios`, `portfolio_weights`, `risk_reports`, `risk_rejections`, `attribution_runs`, `factor_returns` | 1    |
| P4-03 | Covariance estimator service: sample, Ledoit-Wolf shrinkage, factor-model — all behind `CovarianceEstimator` ABC | 2    |
| P4-04 | Constraint library scaffolding: `Constraint` base class + 8 concrete constraints           | 2    |
| P4-05 | Optimizer base class + cvxpy solver glue + infeasibility fallback                          | 2    |
| P4-06 | Unit tests for constraints (toy 5-asset universe)                                          | 1    |

### Week 2 — Optimizers (≈9–10 person-days)

| ID    | Task                                                                       | Days |
| ----- | -------------------------------------------------------------------------- | ---- |
| P4-07 | MVO implementation + tangency / min-vol / target-return modes              | 2    |
| P4-08 | Black-Litterman: prior, view ingestion adapter, posterior, BL-MVO          | 2    |
| P4-09 | Risk parity (equal risk contribution, Newton iteration) + HRP variant      | 2    |
| P4-10 | CVaR optimizer (Rockafellar-Uryasev LP form, scenario generation)          | 2    |
| P4-11 | Optimizer property tests: weights sum, sign, infeasibility recovery        | 1    |

### Week 3 — Risk Engine (≈9–10 person-days)

| ID    | Task                                                                                  | Days |
| ----- | ------------------------------------------------------------------------------------- | ---- |
| P4-12 | VaR/CVaR module: historical, parametric, Monte Carlo                                  | 2    |
| P4-13 | Stress scenarios: 2008, COVID, rate shock, flash crash — each with a calibration script | 3    |
| P4-14 | Correlation clustering + concentration metrics (HRP-style hierarchy, top-N reporting) | 2    |
| P4-15 | Risk validation gate: pass/fail, threshold config, rejection emission                 | 2    |

### Week 4 — Attribution, Orchestration, Reporting (≈9–10 person-days)

| ID    | Task                                                                                   | Days |
| ----- | -------------------------------------------------------------------------------------- | ---- |
| P4-16 | Factor model fit job (FF5 + MOM, monthly refit, OLS with HAC SEs)                       | 2    |
| P4-17 | PnL attribution module (factor exposure × factor return + idiosyncratic residual)       | 2    |
| P4-18 | Celery (or Temporal) DAG: daily orchestrator, idempotency, replay                       | 2    |
| P4-19 | Reporting: exposure report (JSON + HTML via Jinja), PDF via WeasyPrint                  | 2    |
| P4-20 | Integration test: synthetic Phase 3 signals → published portfolio + report             | 1    |

Buffer / hardening: 2–3 days for solver edge cases, covariance instability tuning, and contract review with downstream Phase 7 owner.

---

## 3. Optimizer Architecture

The four optimizers must look identical from the outside. Differences are confined to: (a) the objective expression, (b) optional input artifacts (e.g., views for BL, scenarios for CVaR). Constraints, solver configuration, fallback handling, and result schema are shared.

### Module layout (proposed)

```
libs/portfolio/
  contracts.py              # Pydantic models for I/O
  covariance/
    base.py                 # CovarianceEstimator ABC
    sample.py
    ledoit_wolf.py
    factor_model.py
  optimizers/
    base.py                 # Optimizer ABC + run() pipeline
    mvo.py
    black_litterman.py
    risk_parity.py
    cvar.py
    fallback.py             # constraint relaxation strategy
  constraints/
    base.py                 # Constraint ABC
    box.py                  # long-only, leverage caps
    sector.py
    beta.py
    turnover.py
    liquidity.py
    factor_neutral.py
    concentration.py
  risk/
    var_cvar.py
    stress/
      base.py
      scenarios_2008.py
      scenarios_covid.py
      scenarios_rate.py
      scenarios_flash.py
    clustering.py
    validation.py           # the gate
  attribution/
    factor_model.py
    brinson.py              # optional sector-based attribution
    runner.py
  reporting/
    exposure.py
    pdf.py
    templates/
  orchestration/
    daily_job.py            # Celery or Temporal entrypoint
```

### `Optimizer` base class

Behavior (pseudocode):

```python
class Optimizer(ABC):
    def __init__(self, config: OptimizerConfig): ...

    @abstractmethod
    def build_objective(self, w: cp.Variable, ctx: OptContext) -> cp.Expression: ...

    def run(self, ctx: OptContext) -> OptResult:
        w = cp.Variable(ctx.n_assets)
        objective = cp.Minimize(self.build_objective(w, ctx))
        constraints = [c.to_cvxpy(w, ctx) for c in ctx.constraints]
        prob = cp.Problem(objective, constraints)
        for solver in self.config.solver_chain:  # ECOS → SCS → CLARABEL
            try:
                prob.solve(solver=solver, **self.config.solver_kwargs[solver])
                if prob.status in ("optimal", "optimal_inaccurate"):
                    return OptResult.from_problem(prob, w, ctx)
            except cp.SolverError:
                continue
        return self._handle_infeasible(ctx)
```

Key properties:

- **Single solve loop.** Solver chain is configured per optimizer.
- **`OptContext`** is the immutable input bag: `expected_returns`, `covariance`, `current_weights`, `prices`, `adv`, `sector_map`, `beta`, `factor_loadings`, `views` (BL only), `scenarios` (CVaR only), `regime_label`, `constraints`, `risk_aversion`, `solver_chain`. Each field is `as_of`-tagged.
- **Constraints are first-class.** A constraint exposes `to_cvxpy(w, ctx) -> list[cp.Constraint]`. All optimizers iterate the same constraint list.
- **Fallback on infeasibility.** Deterministic relaxation policy: drop optional constraints in a configured order. Each relaxation step is logged.

### cvxpy modeling notes

- Use `cp.Parameter` for inputs that change across runs but keep problem structure identical. Caching the canonical form speeds repeated solves materially.
- PSD-ify covariance: every covariance matrix passes through a `nearest_psd` helper (eigenvalue floor at 1e-8) before reaching cvxpy.
- Solver chain: ECOS for small/medium QP/SOCP, CLARABEL for large, SCS as last resort. Avoid OSQP for indefinite-shrinkage covariances.

### Infeasibility fallback policy

Constraints carry `priority: int` and `relaxable: bool`. Default relaxation order: turnover (3) → factor neutrality (2) → beta neutrality (2) → sector caps (1) → concentration (1) → liquidity (0, never relaxed) → box (0, never relaxed). Iterates by ascending priority and emits a `RelaxationEvent` for each step.

---

## 4. Each Optimizer in Depth

### 4.1 Mean-Variance (MVO)

**Objective forms (configurable):**

- Tangency / risk-aversion: `min  λ * w'Σw - μ'w`
- Min-variance: `min w'Σw  s.t. constraints`
- Target return: `min w'Σw  s.t. μ'w >= r_target`

**Covariance choice — opinionated default:**

| Estimator        | When to use                                              | Cost      |
| ---------------- | -------------------------------------------------------- | --------- |
| Sample           | Diagnostics only. Never as a production default.         | O(n²·T)   |
| Ledoit-Wolf      | **Default.** Robust, no hyperparameters, well-conditioned. | Closed-form |
| Factor-model (FF5+MOM + idiosyncratic diag) | Universes >300 assets, long horizon (≥3yr) data | Same as factor fit |

Default: Ledoit-Wolf shrinkage on 252-day rolling daily returns. Factor-model covariance offered as alternative for large universes where sample condition number is dangerous.

**Why not vanilla sample?** With T < n the sample covariance is singular; even with T ≈ 2n it underestimates small eigenvalues, which MVO ruthlessly exploits — concentrating in low-variance directions that are mostly noise.

**Practical knobs:**

- `risk_aversion`: 1.0 (aggressive), 5.0 (default), 25.0 (conservative).
- `expected_returns`: from Phase 3 signals, optionally smoothed by EMA (half-life ~5 trading days).
- Always pair with turnover penalty: MVO without one churns 80–120% of the book daily on noisy alpha.

### 4.2 Black-Litterman

**Why we need it:** Phase 3 produces signals; Phase 6 produces qualitative views from agents. BL blends a quantitative prior with discretionary or alternative-source views.

**Prior construction:**

- Market-implied equilibrium returns: `Π = δ * Σ * w_mkt`, where `w_mkt` is cap-weighted universe and `δ` is implied risk aversion (default 2.5).
- For sub-universes, use sector-aggregated cap weights — defensible engineering choice, document explicitly.

**View ingestion contract (Phase 6 integration point):**

```python
class View(BaseModel):
    view_id: str
    as_of_ts: datetime
    source: Literal["phase3_signal", "phase6_agent", "manual"]
    P: list[list[float]]      # picking matrix, k×n
    Q: list[float]             # k expected return values
    confidence: list[float]    # k confidences in [0,1] — used for Omega
    rationale: str
    expires_at: datetime
```

**Tau and Omega calibration:**

- `tau`: scalar scaling prior covariance. Default `tau = 1/T` (Walters convention).
- `Omega`: diagonal covariance of view errors via Idzorek's (2005) confidence-mapping.

**Posterior:**

```
μ_BL = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹ [(τΣ)⁻¹ Π + P'Ω⁻¹ Q]
Σ_BL = Σ + [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹
```

Then run MVO with `(μ_BL, Σ_BL)`.

**Failure modes:**

- Contradictory views: log warning when `cond(P'Ω⁻¹P)` exceeds threshold.
- Single-asset 100%-confidence views: cap maximum Idzorek confidence at 0.99.

### 4.3 Risk Parity

**Equal Risk Contribution (ERC):**

```
RC_i(w) = w_i * (Σw)_i / sqrt(w'Σw)
solve: RC_i = RC_j  for all i, j
```

Convex reformulation (Maillard et al., 2010):

```
min  0.5 * w'Σw - (1/n) * Σ log(w_i)    s.t. w >= 0
```

Solve via Newton iteration with backtracking; convergence in ~10–20 iterations for n ≤ 500.

**Hierarchical Risk Parity (HRP) — alternative:**

Lopez de Prado's algorithm: correlation distance → Ward linkage → recursive bisection with inverse-variance allocation.

HRP advantages over ERC:
- No matrix inversion → robust to singular covariance.
- Hierarchy mirrors economic reality.
- Empirically lower turnover.

Default: ERC. Toggle to HRP when universe > 200 or condition(Σ) > 1e6.

**Constraint compatibility:** Naturally long-only, fully invested. Sector caps and beta neutrality enforced post-hoc via projection, or via constrained-RP (Bruder & Roncalli, 2012).

### 4.4 CVaR Optimization

**Why CVaR over VaR:** VaR is non-coherent (subadditivity fails) and not convex in weights. CVaR is coherent and admits a tractable LP via Rockafellar-Uryasev (2000):

```
min over (w, α, u)   α + (1/(1-β)) * (1/S) * Σ u_s
s.t.  u_s >= -r_s' w - α     ∀ s ∈ scenarios
      u_s >= 0                 ∀ s
      μ' w >= r_target         (optional)
      Σ w_i = 1, plus other linear constraints
```

**Confidence level:** β = 0.95 default for sizing. β = 0.99 for risk report only.

**Scenario generation:**

- **Historical:** S = 1000 most recent daily return vectors.
- **Bootstrap:** 5000 resamples with block size 5. **Default.**
- **Parametric MC:** t-copula calibrated to historical marginals (df=4). Used for stress, not default sizing — model risk too high.

**Why CVaR is preferred for tail-risk-aware sizing:** MVO penalizes variance symmetrically. For asymmetric distributions (options, levered ETFs, crypto), CVaR sizing differs materially during regime transitions. Cost: sensitivity to scenario count (S ≫ n) and longer solve times.

---

## 5. Constraint Library

```python
class Constraint(ABC):
    name: str
    priority: int      # 0 = hard, higher = relaxable first
    relaxable: bool

    def to_cvxpy(self, w: cp.Variable, ctx: OptContext) -> list[cp.Constraint]: ...
    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict: ...
```

### 5.1 Box / leverage (priority 0, never relax)

```
0 <= w <= w_max     # long-only, default w_max = 0.10
||w||_1 <= L_max    # gross leverage cap, default 1.0
```

Long-short:
```
w_long - w_short, w_long >= 0, w_short >= 0
sum(w_long) <= 1.0, sum(w_short) <= 1.0
```

### 5.2 Sector caps (priority 1, relaxable)

GICS Level 1 default. Pull from universe service.

```
S @ w <= s_max     # S is (n_sectors × n_assets) indicator
S @ w >= -s_max    # for long-short
```

Default: 25% gross per GICS L1. Missing GICS → "Unclassified" bucket capped at 5%.

### 5.3 Beta neutrality (priority 2, relaxable)

- **Default:** rolling regression beta vs SPY, 252-day window, OLS.
- **Alt:** Barra-style fundamental beta from factor risk model.

```
β' w = β_target     # default β_target = 0
|β' w - β_target| <= tolerance    # softer form
```

Default soft form with `tolerance = 0.05`.

### 5.4 Turnover penalty (priority 3, relaxable)

**Linear (L1)** default — induces sparsity in trades:

```
objective += λ_turnover * ||w - w_prev||_1
```

**Quadratic (L2)** alternative for smoother trajectories.

Hard cap available:
```
||w - w_prev||_1 <= turnover_max     # default 0.40 daily
```

`λ_turnover` calibrated per strategy. Default 0.5 for daily strategies.

### 5.5 Liquidity-aware sizing (priority 0, never relax)

**% ADV cap (hard):**
```
|w_i - w_prev_i| * NAV <= adv_pct * adv_i * price_i
```
Default `adv_pct = 0.05`.

**Participation rate / impact penalty (soft):**
```
objective += λ_impact * Σ (|w_i - w_prev_i| * NAV / (adv_i * price_i))^1.5
```
Almgren-Chriss-style. Calibrated per asset class.

**Minimum trade size:** Sub-1bps trades zeroed post-solve. Default 5 bps of NAV.

### 5.6 Factor neutrality (priority 2, relaxable, optional)

```
B_factors' w = 0    # B_factors is loadings matrix
```

### 5.7 Concentration (priority 1, relaxable)

```
sum(top_k(w)) <= top_k_cap
||w||_2^2 <= herfindahl_max
```

Default: top-10 ≤ 50%, Herfindahl ≤ 0.05 (≈ effective 20+ names).

### 5.8 Tracking-error band (optional, priority 2)

```
(w - w_bench)' Σ (w - w_bench) <= TE_max^2
```

---

## 6. Risk Engine

### 6.1 VaR

| Method     | When to use                                        | Knobs                    |
| ---------- | -------------------------------------------------- | ------------------------ |
| Historical | Default for the report. Non-parametric, transparent. | Window 252d, β = 0.95 / 0.99 |
| Parametric | Diagnostic, used for sanity-checking historical.    | Assumes Gaussian; explicit. |
| Monte Carlo| Stress only. t-copula with df=4, 10000 paths.       | Slow; not on critical path. |

Always compute and report all three. Discrepancies between historical and parametric VaR are themselves a risk signal.

### 6.2 CVaR

Same three methods. CVaR is the gating metric, not VaR.

### 6.3 Stress scenarios

Each scenario is a realized multi-asset shock applied to current portfolio weights. Two ways:

- **Asset-level shock** `s ∈ R^n`: `PnL = w' s`. Used when historical asset-level returns are available (2008, COVID).
- **Factor-level shock** `f ∈ R^k`: `PnL = w' (B f) + idio_term`. Used for hypothetical shocks (rate shock).

#### Scenario calibrations

**1. 2008 GFC** — factor shocks calibrated from Sep 1 – Nov 30, 2008. Asset-level shocks for assets with sufficient history. Magnitude reference: SPY ≈ -29%, MOM factor ≈ -25%, value factor ≈ -10%.

**2. COVID crash** — asset-level shocks from Feb 19, 2020 (peak) to Mar 23, 2020 (trough). ~33% drawdown on SPY, oil collapse, credit blowout. Captures correlation-going-to-1 dynamics.

**3. Rate shock (+200bps parallel)** — synthetic. Apply factor shocks: market factor proportional to historical rate-shock beta, bond proxies via duration, sector-specific shocks (financials +5%, utilities -8%, tech -10%).

**4. Flash crash (2010-05-06)** — intraday move 14:42–14:47 ET. Model max intraday drawdown. Asset-level shocks from intraday tick data. Stresses liquidity by forcing `adv_pct = 0`.

```python
class StressScenario(ABC):
    name: str
    description: str
    def apply(self, w: np.ndarray, ctx: RiskContext) -> ScenarioResult:
        # returns total PnL, per-asset PnL, factor decomposition, breached caps
```

Calibration scripts run quarterly; coefficients are version-pinned. `scenario_version` field tags every risk report.

### 6.4 Correlation clustering

Hierarchical clustering on `D_ij = sqrt(0.5 * (1 - ρ_ij))` with Ward linkage. Two outputs:

- **Concentration metric:** at k=10, max cluster weight and Herfindahl index over cluster weights.
- **Effective number of bets (ENB):** `1 / Σ p_c^2` where `p_c` is cluster's contribution to portfolio variance.

### 6.5 Stress and hedging interactions

Risk engine reports per-scenario PnL gross and after applying hedges. Hedge effectiveness reported but not gated on — informational for Phase 7's commentary layer.

---

## 7. Risk Validation Gate

```python
def validate(portfolio: TargetPortfolio, report: RiskReport, policy: RiskPolicy) -> ValidationResult:
    # returns ValidationResult.passed | ValidationResult.rejected(reasons=[...])
```

`RiskPolicy` is config — versioned, audited, owned by a notional "Risk Committee" (in practice: a YAML file under code review).

### Gate checks (defaults)

| Check                    | Threshold (default)            | Source                |
| ------------------------ | ------------------------------ | --------------------- |
| Daily 95% CVaR (hist.)   | <= 3% of NAV                   | risk engine §6.2      |
| Daily 99% CVaR (hist.)   | <= 5% of NAV                   | risk engine §6.2      |
| 2008 stress PnL          | >= -25% NAV                    | scenarios §6.3.1      |
| COVID stress PnL         | >= -25% NAV                    | scenarios §6.3.2      |
| Rate-shock stress PnL    | >= -15% NAV                    | scenarios §6.3.3      |
| Flash-crash stress PnL   | >= -15% NAV                    | scenarios §6.3.4      |
| Sector concentration     | constraint-enforced; gate is consistency check | constraints §5.2 |
| Cluster concentration    | top cluster <= 35% portfolio variance | clustering §6.4 |
| Beta deviation           | |β' w - β_target| <= 0.10 | §5.3 |
| Liquidity coverage       | sum liquidatable in 5 days at 5% ADV >= 90% | §5.5 |
| Single-name concentration| max |w_i| <= 12%               | §5.1 / §5.7           |

Portfolio passes only if all checks pass. No partial passes. No "warnings allowed."

### Rejection log schema

```sql
CREATE TABLE risk_rejections (
  rejection_id        UUID PRIMARY KEY,
  portfolio_id        UUID NOT NULL,
  signal_batch_id     UUID NOT NULL REFERENCES signal_batches(batch_id),
  strategy_id         TEXT NOT NULL,
  as_of_ts            TIMESTAMPTZ NOT NULL,
  optimizer           TEXT NOT NULL,
  policy_version      TEXT NOT NULL,
  failed_checks       JSONB NOT NULL,
  full_report_id      UUID REFERENCES risk_reports(report_id),
  fallback_action     TEXT NOT NULL,    -- 'cash', 'hold_prior', 'retry_relaxed', 'escalate_hitl'
  fallback_outcome    JSONB,
  created_at          TIMESTAMPTZ DEFAULT now()
);
```

Indexes: `(strategy_id, as_of_ts DESC)`, `(signal_batch_id)`, GIN on `failed_checks`.

### How rejections surface back

1. Gate writes `risk_rejections` row.
2. Gate emits `PortfolioRejected` event on Redpanda topic `portfolio.rejections.v1`.
3. Phase 3's strategy registry subscribes (loosely coupled). Strategy with high rejection rate (>10% over 30 days) flagged in Phase 9 dashboard.
4. Phase 6's Compliance/Risk Agent subscribes for daily briefing summary.
5. Phase 7's recommendation pipeline applies the configured fallback:
   - `cash`: target portfolio = current cash position.
   - `hold_prior`: target portfolio = previous day's accepted portfolio.
   - `retry_relaxed`: re-run optimization with relaxation policy. **Retry once only**.
   - `escalate_hitl`: pin in human review queue. No portfolio published.

The fallback choice is part of the strategy's config, not the gate's decision. The gate's job is binary.

---

## 8. PnL Attribution

### 8.1 Factor-model attribution (primary)

Run on **realized** PnL after the fact (T+1). Requires realized returns from Phase 1 and realized portfolio weights from Phase 8.

**Factor model:**

- Fama-French 5: MKT, SMB, HML, RMW, CMA
- Plus: MOM (momentum)
- Plus optional: regime factor (binary indicator from Phase 7)

**Factor returns source:** Ken French's data library (refreshed weekly via Phase 1 ingestion job; cached in `factor_returns` table).

**Estimation:**

- Per-asset OLS regression: `r_i,t = α_i + Σ β_i,k * f_k,t + ε_i,t` over 252-day rolling window, refit monthly. HAC standard errors (Newey-West, lag=5).
- Portfolio factor exposure: `B_p = Σ w_i * β_i`.
- Factor PnL contribution: `PnL_factor = B_p · f_realized * NAV`.
- Idiosyncratic PnL: `PnL_idio = realized_PnL - PnL_factor`.

**Idiosyncratic residual handling:**

- Stored as per-asset time series alongside aggregated portfolio idio PnL.
- Persistent positive idio implies alpha not explained by factors.
- Decomposed by sector and by signal source for daily report.

### 8.2 Brinson-Fachler (sector-level) attribution (secondary)

Allocation, selection, interaction effects at GICS sector level vs benchmark (default SPY). Well-understood by traditional analysts.

### 8.3 Storage

```sql
CREATE TABLE attribution_runs (
  run_id          UUID PRIMARY KEY,
  portfolio_id    UUID NOT NULL,
  as_of_ts        TIMESTAMPTZ NOT NULL,
  method          TEXT NOT NULL,          -- 'factor_ff5_mom' | 'brinson'
  total_pnl_bps   NUMERIC(12, 4) NOT NULL,
  factor_pnl      JSONB,                  -- {factor_name: bps}
  idio_pnl_bps    NUMERIC(12, 4),
  sector_pnl      JSONB,
  created_at      TIMESTAMPTZ DEFAULT now()
);
```

Queryable from Phase 9 dashboard.

---

## 9. Daily Job Orchestration

**Orchestrator choice:** Celery for Phase 4 (master plan default; shallow DAG ≤6 nodes). Temporal door kept open by writing orchestrator as thin layer over `Workflow` ABC. Migration to Temporal is a same-day port.

### Daily DAG

```
[ T-1 close + 30min ]
    aggregate_signals (Phase 3 output)
            │
            ▼
    fetch_prior_portfolio (DB read)
            │
            ▼
    estimate_covariance ──────┐
            │                  ├──> these run in parallel
    estimate_betas      ──────┤
            │                  │
    fetch_views (Phase 6) ────┘
            │
            ▼
    optimize (per-strategy fanout)
            │
            ▼
    risk_engine (per-portfolio fanout)
            │
            ▼
    risk_gate
       /        \
  passed       rejected
      │             │
      ▼             ▼
   publish    apply_fallback ──> publish (or HITL escalate)
      │
      ▼
   attribution (T+1 — runs the next morning, separate workflow)
```

### Trigger

- **Primary:** cron at 16:30 ET (post-close, post-Phase 3 batch).
- **Event-driven:** subscribes to `signals.daily_batch.completed.v1`; cron is safety net.

### Idempotency

Every task keys on `(strategy_id, as_of_date)`. Re-running a completed key returns prior result from `task_runs` table.

### Retry / replay

- **Retry:** Celery exponential backoff (1s, 4s, 16s, 64s, 256s) — 5 retries.
- **Replay:** `replay` CLI takes `(strategy_id, as_of_date)`. `--force` overwrites; prior version preserved with `version` column.
- **Backfill:** `backfill` runs DAG over date range serially; used after estimator change or policy update.

### Output destinations

- `target_portfolios` + `portfolio_weights` tables (Postgres)
- `risk_reports` table (JSONB-rich; one row per portfolio)
- `risk_rejections` table (populated only on rejection)
- MinIO/S3: PDF/HTML reports under `s3://astraeus-reports/portfolio/{date}/{strategy_id}/`
- Kafka topic `portfolio.published.v1`: Phase 7 subscribes

---

## 10. Contracts Exposed Downstream

Schemas committed to `libs/contracts/`, version-pinned.

### 10.1 TargetPortfolio

```python
class TargetPortfolio(BaseModel):
    portfolio_id: UUID
    strategy_id: str
    as_of_ts: datetime
    nav_currency: str                  # 'USD'
    nav: Decimal
    weights: list[PortfolioWeight]     # symbol, weight, target_shares?, sector
    status: Literal["passed", "fallback_applied", "rejected"]
    optimizer: str                     # 'mvo' | 'black_litterman' | 'risk_parity' | 'cvar'
    optimizer_config_hash: str
    constraint_set_hash: str
    covariance_estimator: str
    expected_return_source: str
    risk_report_id: UUID
    rejection_id: Optional[UUID]
    parent_portfolio_id: Optional[UUID]  # if fallback held prior
    created_at: datetime
    schema_version: Literal["v1"]
```

### 10.2 RiskReport

```python
class RiskReport(BaseModel):
    report_id: UUID
    portfolio_id: UUID
    as_of_ts: datetime
    var_95_hist: Decimal
    var_99_hist: Decimal
    cvar_95_hist: Decimal
    cvar_99_hist: Decimal
    var_95_param: Decimal
    cvar_95_param: Decimal
    var_95_mc: Decimal
    cvar_95_mc: Decimal
    stress_scenarios: list[ScenarioResult]
    cluster_concentration: ClusterReport
    sector_exposure: dict[str, Decimal]
    factor_exposure: dict[str, Decimal]
    beta: Decimal
    effective_n_bets: Decimal
    liquidity_5day_pct: Decimal
    constraint_diagnostics: list[ConstraintDiag]
    policy_version: str
    schema_version: Literal["v1"]
```

### 10.3 Compatibility

- `schema_version` monotonically increasing. Breaking changes ship as `v2` alongside `v1`.
- Never silently change field semantics under same version. Adding optional fields under `v1` allowed.

---

## 11. Reporting Outputs

### 11.1 Exposure report (HTML + PDF)

- **Sector exposure** — bar chart, GICS L1, with policy caps overlaid.
- **Factor exposure** — bar chart for FF5+MOM, with prior-day delta callouts.
- **Country exposure** — international universes only.
- **Top-N concentration** — top 10 names by absolute weight, with cluster assignment.
- **Cluster dendrogram** — visualizes correlation clustering and weight allocation per cluster.
- **Position changes** — diff vs prior day, sorted by absolute trade size; flags liquidity-bound positions.

### 11.2 Risk report

- VaR/CVaR table at 95%/99% with all three methods side-by-side.
- Stress scenario PnLs as horizontal bar chart with thresholds marked.
- Hedging effectiveness table.
- Constraint diagnostics: tightest constraint (highest shadow price), pre-fallback constraints relaxed if any.

### 11.3 Drawdown attribution (in T+1 attribution daily output)

- Cumulative PnL chart split into factor and idiosyncratic.
- Drawdown timeline with each drawdown decomposed into factor / idio / sector contribution.
- Top 5 contributors and detractors per attribution window (1d, 5d, 30d, ITD).

### 11.4 Daily output PDF

Single PDF per strategy:
- Cover: NAV, daily PnL, status, optimizer used.
- Trade list: target weights and changes.
- Risk dashboard.
- Attribution (from previous day's run).
- Footer: data lineage hashes, code commit, policy version.

Generated via Jinja2 → HTML → WeasyPrint → PDF. Cached to S3.

---

## 12. Exit Criteria Checklist

- [ ] **Reproducibility:** running daily job twice for same `(strategy_id, as_of_date)` produces byte-identical `target_portfolios` and `risk_reports` rows.
- [ ] **All four optimizers wired:** integration test runs MVO, BL, ERC, CVaR against the same `OptContext` on a 50-asset universe and produces feasible portfolios.
- [ ] **Fallback ladder verified:** infeasible problem triggers relaxation ladder; relaxation events persisted and inspectable.
- [ ] **Risk engine completeness:** every `RiskReport` populates VaR/CVaR (3 methods × 2 confidences = 6 numbers), all 4 stress scenarios, cluster concentration, sector + factor exposure.
- [ ] **Stress calibration:** scenario coefficient files exist for all 4 scenarios, version-tagged, with calibration notebooks in research environment.
- [ ] **Gate determinism:** failing portfolio always rejected and `risk_rejections` row exists; passing always reaches `target_portfolios` with `passed`.
- [ ] **Fallback execution:** rejection triggers configured fallback action; resulting state observable in `target_portfolios`.
- [ ] **Attribution runs T+1:** factor model attribution job produces `attribution_runs` rows with non-trivial factor and idio PnL.
- [ ] **Daily job idempotency:** replaying same date returns cached result; `--force` produces new versioned row, prior preserved.
- [ ] **Contracts published:** `TargetPortfolio`, `RiskReport`, `RiskRejection` schemas live in `libs/contracts/`, importable, with `schema_version="v1"`.
- [ ] **PDF report generated:** daily PDF exists in S3 for at least one strategy run, contains all sections from §11.4.
- [ ] **Observability:** every optimizer run, gate decision, attribution run emits OpenTelemetry spans; key Prometheus metrics expose `optimizer.solve_time_ms`, `gate.decision`, `attribution.idio_bps`.
- [ ] **Tests:** unit coverage ≥ 80% on `libs/portfolio/`, integration test runs end-to-end DAG against synthetic Phase 3 signals.
- [ ] **Runbook:** markdown documents how to backfill, how to override policy in emergency, how to interpret rejection codes.

---

## 13. Risks & Open Questions

### Covariance instability
- **Symptom:** Daily MVO weights swing wildly; single outlier flips dominant eigenvector.
- **Mitigations:** Ledoit-Wolf default. Pair with turnover penalty. EWMA covariance with halflife 60d. Factor-model covariance for deeper cases.
- **Open question:** Bayesian shrinkage prior toward previous day's covariance (OU-style) for temporal regularization?

### Optimization degeneracy on small universes
- **Symptom:** With n < 20, MVO produces near-degenerate solutions: 1–2 assets at the box cap.
- **Mitigations:** Auto-detect small-n regimes, switch default to ERC/HRP. Force tighter Herfindahl. For n < 10, refuse MVO entirely.

### Scenario shock calibration
- **Symptom:** Stress scenarios are point-in-time historical snapshots. Coefficients drift; coverage of "the next crisis" is by construction limited.
- **Mitigations:** Quarterly calibration refresh. Add hypothetical scenario sub-library (oil shock, EM crisis, FX shock for multi-asset). Track scenario coverage.
- **Open question:** Add generative scenario module — sample from t-copula calibrated to crisis-only periods? Adds tail coverage but adds model risk.

### Solver flakiness
- **Symptom:** ECOS occasionally returns "optimal_inaccurate" on borderline problems.
- **Mitigations:** Solver chain (ECOS → CLARABEL → SCS) with consistent tolerances. Solver-agnostic L2 regularization toward equal-weight.

### Phase 6 view ingestion
- **Open question:** When agent issues view with confidence 0.9 on sector dislocation, should it dominate BL posterior? Initial proposal: cap agent-sourced confidence at 0.5 until backtested.

### Liquidity in real time vs ADV
- **Symptom:** ADV is 30-day average; on quiet day, actual liquidity much lower.
- **Mitigations:** Pre-flight liquidity check at execution time (Phase 8). Phase 4 reports liquidity coverage metric in risk report.

### Risk policy versioning and governance
- **Open question:** Who owns the `RiskPolicy` YAML? In a real institution: Risk Committee. In our build: standing engineering-lead review? Code-reviewed only? Formalize sign-off process before Phase 8.

### Beta source consistency
- **Symptom:** Rolling-regression beta and factor-model beta can disagree by 20–30%.
- **Resolution:** Single beta source per run. Risk report records source. Default rolling regression for consistency with simple covariance estimator.

### Attribution cold start
- **Symptom:** Factor model needs ≥252 days history; new IPOs have none.
- **Mitigations:** For assets with <252 days, attribute via sector-mean beta with idio = total - factor_via_sector_beta. Flag in report.

---

### Critical Files for Implementation

- `/Users/mukesh/python-projects/Astraeus/libs/portfolio/optimizers/base.py`
- `/Users/mukesh/python-projects/Astraeus/libs/portfolio/constraints/base.py`
- `/Users/mukesh/python-projects/Astraeus/libs/portfolio/risk/validation.py`
- `/Users/mukesh/python-projects/Astraeus/libs/portfolio/orchestration/daily_job.py`
- `/Users/mukesh/python-projects/Astraeus/libs/contracts/portfolio.py`

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

**Adjustments**

- **All four optimizers stay.** MVO, Black-Litterman, risk parity, CVaR — the resume value of "we built four optimizers behind a common interface" is exactly the artifact. Don't cut.
- **Constraint library, risk gate, attribution stay.** These are the discussion topics in any quant interview.
- **Universe:** sized to Phase 1 scope (~150 names). Solver runtimes shrink; CVaR with 1,000 scenarios on 150 names is sub-second on a laptop.
- **Stress scenarios:** keep the canon (2008, COVID, rate shock, flash crash) — the playbook is the value.
- **Daily portfolio job:** runs locally on a cron or as a Prefect flow on the dev VPS. No Kubernetes CronJob in scope mode.
- **Live trading sizing constraint:** when Phase 8 goes live, the optimizer is gated to a small notional (initially $1–2k, scaling to $5–10k after a clean track record). The constraint library handles this naturally — add a `max_gross_notional` constraint per account.

**What stays (resume-load-bearing)**

- Common optimizer interface, constraint library, risk validation gate, factor + idiosyncratic attribution, stress engine, the rejection log. All of it.

**Budget impact:** $0/mo additional.
