# Phase 7 — Daily Recommendation Engine

**Timeline:** Weeks 22–28 · **Depends on:** Phases 1–6 · **Blocks:** Phase 8

---

## 1. Phase Goals & Refined Exit Criteria

Phase 7 wires the 8-stage recommendation pipeline that the platform's product story orbits around. The discipline that separates this from a retail "AI stock picker" is **rigid stage separation** — signal generation, signal ranking, portfolio construction, risk validation, and execution must be distinct services with distinct contracts. A single function that does "AI thinks AAPL is a buy at 3% size" is the antipattern; the institutional pattern is a pipeline where each stage is testable, replaceable, and auditable.

Refined exit criteria:

- **Daily 06:30 ET pipeline run** completes within 90 minutes, producing N (target ~20) ranked, risk-validated recommendations with thesis, citations, and override path.
- **Stage isolation proven**: replacing the regime detector or the ensemble can be done without touching upstream stages.
- **Replay determinism**: rerunning yesterday's pipeline with the same data hash produces identical recommendations.
- **HITL approval workflow**: every recommendation has a state of `proposed | approved | rejected | overridden` and an override rationale capture.
- **Override-learning feedback** wired (no model training yet — just a clean dataset for the future).
- **Partial-failure tolerance**: a failure in Stage 5 does not corrupt Stage 1–4 outputs; the run is marked `degraded` and the cause is loud.

---

## 2. Scope Boundaries

| In | Out |
|---|---|
| Daily cadence | Intraday recommendations |
| US equities universe | Multi-asset (defer to follow-on) |
| HMM + GMM regime detector | Bayesian switching (track as v2 candidate) |
| Regime-conditional ensemble | Online-learning ensemble |
| HITL approval, override capture | Override-driven retraining (next phase) |
| Phase 4 portfolio + risk reused | New optimizers |

---

## 3. Week-by-Week Breakdown

### Week 22 — Orchestration + Stage 1 (Aggregator)
- Decide orchestrator (Temporal preferred — see Section 9). Define per-stage activity contracts.
- Stage 1 worker: pulls features for the day from Phase 2; persists to `daily_input_snapshot`.

### Week 23 — Stage 2 (Regime Detector)
- HMM (hmmlearn) on macro+vol features; 4–6 states; rolling fit.
- GMM clustering on a separate feature subset for cross-validation.
- Regime stability test: recent regime label only commits if probability > threshold for ≥ 3 days.

### Week 24 — Stage 3 (Signals)
- Five signal generators (technical, statistical, ML, NLP, macro), each its own service with its own state.
- Per-signal SLA: < 5 min daily.

### Week 25 — Stage 4 (Ensemble)
- Regime-conditional weight matrix; correlation penalty; signal-decay tracking.
- Ranking output: top-N candidates with scores and component attribution.

### Week 26 — Stage 5 + 6 (Portfolio + Risk reuse)
- Wire Phase 4 optimizers behind the recommender contract.
- Risk validation gate; rejection log table.

### Week 27 — Stage 7 + 8 (Explanation + HITL)
- Phase 6 thesis generator runs per recommendation.
- Approval UI hook; override capture with rationale.
- Recommendation lifecycle state machine.

### Week 28 — Hardening
- End-to-end replay determinism test on 30 historical days.
- Failure-injection chaos: kill stages mid-run; verify partial-failure handling.
- Override-learning dataset shape locked in.

---

## 4. Component & Service Architecture

```
                     ┌────────────────────────────┐
                     │    Recommender Orchestrator│
                     │    (Temporal Workflow)     │
                     └───────────────┬────────────┘
                                     │
       ┌──────────┬──────────┬──────┼─────────┬──────────┬─────────┬───────────┐
       ▼          ▼          ▼      ▼         ▼          ▼         ▼           ▼
   ┌─────┐   ┌─────┐    ┌─────┐  ┌─────┐  ┌────────┐ ┌──────┐ ┌────────┐ ┌─────┐
   │ S1  │   │ S2  │    │ S3a │  │ S3b │  │  S4    │ │ S5   │ │ S6     │ │ S7  │
   │Aggr.│──►│Regm.│───►│TechS│  │MLS  │ ─►│Ensble  │►│PortC │►│Risk Gt │►│Thes.│
   │     │   │HMM  │    │S3c..│  │S3e  │  │        │ │      │ │        │ │     │
   └─────┘   └─────┘    └─────┘  └─────┘  └────────┘ └──────┘ └────────┘ └─────┘
                                                                              │
                                                                              ▼
                                                                       ┌──────────┐
                                                                       │ Stage 8  │
                                                                       │ HITL Q   │
                                                                       └──────────┘
```

Each stage is a Temporal Activity (idempotent, retryable). The Workflow holds the run-level state and emits per-stage events for observability.

---

## 5. Folder & File Structure

```
apps/
├─ recommender-workflow/   # Temporal worker
├─ recommender-api/        # query / approval API
└─ recommender-ui-bff/     # backend-for-frontend for approval UI
libs/
├─ recommender/
│  ├─ stages/
│  │  ├─ aggregate.py
│  │  ├─ regime.py
│  │  ├─ signals/
│  │  │  ├─ technical.py
│  │  │  ├─ statistical.py
│  │  │  ├─ ml_xgb.py
│  │  │  ├─ nlp_sentiment.py
│  │  │  └─ macro.py
│  │  ├─ ensemble.py
│  │  ├─ portfolio.py     # thin wrapper on Phase 4
│  │  ├─ risk.py          # thin wrapper on Phase 4
│  │  ├─ thesis.py        # thin wrapper on Phase 6
│  │  └─ hitl.py
│  ├─ contracts.py        # Pydantic models for inter-stage messages
│  ├─ statemachine.py     # recommendation lifecycle
│  └─ overrides.py
├─ regime/
│  ├─ hmm.py
│  ├─ gmm.py
│  └─ stability.py
└─ ensemble/
   ├─ weights.py
   ├─ correlation_penalty.py
   └─ decay.py
```

---

## 6. Data Model / Schema Changes

```sql
CREATE TABLE recommender_run (
    run_id         UUID PRIMARY KEY,
    run_date       DATE NOT NULL,
    started_at     TIMESTAMPTZ DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    status         TEXT NOT NULL,                   -- queued|running|done|degraded|failed
    input_snapshot_hash BYTEA NOT NULL,
    code_commit    TEXT NOT NULL,
    notes          TEXT
);

CREATE TABLE regime_state (
    run_id        UUID NOT NULL REFERENCES recommender_run,
    label         TEXT NOT NULL,                    -- risk_on, risk_off, vol_spike, ...
    probability   REAL NOT NULL,
    detected_at   TIMESTAMPTZ DEFAULT now(),
    model         TEXT NOT NULL                     -- hmm_v1
);

CREATE TABLE signal_value (
    run_id   UUID NOT NULL REFERENCES recommender_run,
    signal   TEXT NOT NULL,
    ticker   TEXT NOT NULL,
    score    DOUBLE PRECISION NOT NULL,
    score_z  DOUBLE PRECISION,                       -- z-score for ranking
    confidence REAL,
    PRIMARY KEY (run_id, signal, ticker)
);

CREATE TABLE ensemble_weight (
    run_id   UUID NOT NULL REFERENCES recommender_run,
    signal   TEXT NOT NULL,
    regime   TEXT NOT NULL,
    weight   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, signal, regime)
);

CREATE TABLE recommendation (
    rec_id        UUID PRIMARY KEY,
    run_id        UUID NOT NULL REFERENCES recommender_run,
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL CHECK (side IN ('long','short','flat')),
    target_weight NUMERIC(8,6) NOT NULL,
    rank          INT NOT NULL,
    composite_score DOUBLE PRECISION NOT NULL,
    component_attribution JSONB NOT NULL,           -- per-signal contribution
    risk_passed   BOOLEAN NOT NULL,
    risk_notes    JSONB,
    thesis_run_id UUID,                             -- agent_run from Phase 6
    state         TEXT NOT NULL DEFAULT 'proposed', -- proposed|approved|rejected|overridden|expired
    horizon_days  INT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE recommendation_decision (
    rec_id        UUID NOT NULL REFERENCES recommendation,
    decided_by    TEXT NOT NULL,
    decided_at    TIMESTAMPTZ DEFAULT now(),
    decision      TEXT NOT NULL,                    -- approve|reject|override
    override_weight NUMERIC(8,6),
    rationale     TEXT,
    PRIMARY KEY (rec_id, decided_at)
);

CREATE TABLE risk_rejection (
    rec_id        UUID NOT NULL,
    rule          TEXT NOT NULL,
    detail        JSONB,
    rejected_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (rec_id, rule)
);
```

---

## 7. API Surface

```
GET  /reco/run/{run_id}                  # run status, stage timings
GET  /reco/runs?date=YYYY-MM-DD
GET  /reco/recommendations?run_id=...    # filtered list
POST /reco/recommendations/{rec_id}/decide  # approve/reject/override
GET  /reco/regime?date=YYYY-MM-DD
POST /reco/replay?date=YYYY-MM-DD        # operator replay
```

Each `/reco/recommendations` row carries a thesis-run pointer. The UI hydrates it from the Phase 6 endpoint.

---

## 8. External Dependencies

| Library | Use |
|---|---|
| Temporal | orchestration |
| hmmlearn | HMM regime |
| scikit-learn | GMM, scalers |
| Phase 3 backtest registry | strategy parameters |
| Phase 4 optimizers | portfolio + risk |
| Phase 6 agents | thesis generation |

---

## 9. Key Technical Decisions & Tradeoffs

**Temporal over Celery/Airflow.** Airflow is fine for batch ETL but its retry semantics and signaling for human-in-the-loop are clunky. Celery has no built-in concept of long-running workflows with state. Temporal's Workflow + Activity model fits the daily pipeline plus the HITL stage that may take hours of human time. The cost is operational complexity (a Temporal cluster); we run a small one and accept it as future-proofing.

**Stage separation as a hard architectural rule.** Signal generation, ranking, portfolio construction, risk validation, and execution-suggestion live in different code paths and pass typed Pydantic messages. The penalty for fusing two stages "for performance" is paid forever in maintainability and audit.

**Regime detection: HMM + GMM, with a stability filter.** HMM gives temporal structure; GMM gives cross-sectional clustering. We commit to a regime label only when probability > threshold for ≥ 3 days. Bayesian switching is more elegant but expensive to operate and tune; HMM is the right MVP. Track regime mis-classification rate weekly via overlap with macroeconomic ground-truth labels (NBER recession, VIX terciles).

**Regime-conditional ensemble weights, not naive averaging.** Naive averaging gives the worst signal a vote equal to the best. We learn weights per (regime, signal) from prior performance with shrinkage, penalize correlated signals (negative weight for high cross-signal correlation), and track decay (signal weight halves if its trailing 90-day Sharpe collapses below threshold).

**Signal decay tracking.** Each signal has a rolling-Sharpe and a hit-rate vs its calibration; weight goes to zero if the trailing window underperforms. This is where most retail systems quietly die — they keep using a momentum signal that stopped working in 2022.

**Override-as-feedback.** Every override is captured with rationale text; we don't *yet* feed this back into model training, but the dataset shape is fixed now so we don't break it later. This is the single most valuable corpus this platform will eventually have.

**Partial-failure handling.** A run with Stage 1–4 successful and Stage 5 failed is `degraded`, not `failed`. The aggregator output and regime/signals are written; the operator UI shows what's available. This preserves the next-day analyst conversation even when optimizers have a bad day.

**Hard rule: signals never see ranks.** Stage 3 outputs raw scores; Stage 4 ranks. A signal that knows its rank starts trying to game the rank.

---

## 10. Risks, Failure Modes & Mitigations

| Risk | Mitigation |
|---|---|
| Late data invalidates Stage 1 | Stage 1 input snapshot hash committed; downstream stages reject hash mismatch |
| Regime mis-classification cascades | Stability filter; alert on regime flip frequency |
| Ensemble overfits to recent regime | Shrinkage to flat weights; cross-validation across regimes |
| Cascade failure (Stage 7 LLM outage) | Stage 7 failure → run marked `degraded`; thesis filled "pending" placeholder; recommendations still available |
| Override drift (humans always say no) | Track override rate; alert if > 50%; auto-review of recommendation logic |
| Operator approves blindly | UI requires rationale; sample audits |
| Recommendation expiration | Recs live 1 trading day unless explicitly extended |
| Idempotency on retry | All activities keyed on `(run_id, stage, ticker)`; dedup at write |
| Cost blowup on Stage 7 | Per-recommendation budget cap on thesis generation |
| Survivorship in regime calibration | Calibrate on PIT-correct universe (Phase 2) |

---

## 11. Testing Strategy

**Stage golden tests.** Each stage with frozen inputs produces a hash-pinned output. CI gate.

**End-to-end replay determinism.** 30 sample historical days; rerun, compare recommendation set hash. Expected exact match.

**Override-tracking property tests.** Every approval/rejection writes a `recommendation_decision`; counts reconcile to recommendation rows.

**Regime mis-classification harness.** Compare HMM regime label to ground-truth (VIX terciles + NBER cycles); assert agreement above baseline.

**Cascade-failure tests.** Inject failure at each stage; assert run state becomes `degraded`, not `failed`; assert downstream stages either skip cleanly or carry placeholders.

**Stage-isolation test.** Replace one stage's implementation with a stub; assert pipeline still runs and the stub's output is what flows downstream.

---

## 12. Observability Hooks

| Signal | Type |
|---|---|
| `reco_run_duration_seconds{stage}` | histogram |
| `reco_stage_failure_total{stage}` | counter |
| `reco_regime_label` | gauge (label per state) |
| `reco_recommendations_count{state}` | gauge |
| `reco_override_rate` | gauge (rolling 30d) |
| `reco_risk_rejection_rate{rule}` | gauge |
| `reco_signal_decay{signal}` | gauge (rolling Sharpe) |
| `reco_pipeline_freshness_minutes` | gauge |

Daily SLO: pipeline complete by 08:00 ET, freshness lag < 90 min p99.

---

## 13. Definition of Done

- [ ] All 8 stages implemented as Temporal Activities.
- [ ] 30-day replay determinism test green.
- [ ] HITL approval UI hookable; rationale capture proven.
- [ ] Override dataset shape stable; export job produces a clean CSV.
- [ ] Cascade failure scenarios all marked `degraded` correctly.
- [ ] Regime stability filter active; regime flip alert firing on synthetic flip storms.
- [ ] Ensemble decay logic active; documented weight evolution dashboard.
- [ ] Per-stage SLO dashboards live.
- [ ] Runbooks: "Pipeline degraded", "Regime flip storm", "LLM outage during Stage 7".

---

## 14. Interview Talking Points

- **Hard stage separation is the institutional pattern.** Discuss the antipattern of "AI says buy AAPL at 3%" and why it's unauditable.
- **Regime-conditional ensembling.** Naive averaging dilutes the best signal; regime-conditional weights with correlation penalties match how PMs actually think.
- **Signal decay.** Retail systems die quietly when their best signal stops working. Decay tracking + automatic down-weighting is operational alpha.
- **Override-learning loop.** The most valuable corpus a quant team will ever build is "humans said no, here's why". Designing the schema right on day one matters.
- **Partial-failure tolerance.** The platform produces value even on bad days; an outage in Stage 7 doesn't blank the analyst's morning briefing.
- **Temporal for HITL workflows.** The combination of long-running workflows + retries + signals is exactly Temporal's sweet spot.

---

## 15. Open Questions

1. Recommendation horizon — single horizon (60 days) for MVP or multi-horizon (5/30/60)? Lean single first, add later.
2. Override-learning becoming a model: timeline? Probably 6 months post-Phase 7.
3. Number of recommendations per day — 20 too many for human review? Empirical.
4. Should Stage 7 thesis be precomputed for all candidates or only for top-N? Top-N for cost; revisit.
5. Do we expose the regime label to end-users or keep internal? Lean expose, it's a story-telling lever.

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

**Adjustments**

- **Recommendation count:** drop the target from N≈20 to **N≈5–10**. With one human reviewer (you) and a small live account, 20 daily candidates is unactionable. 5–10 is what gets reviewed; everything below the cutoff goes into a "watchlist" tier that's logged but not surfaced in the approval UI.
- **HITL workflow:** single-approver, no escalation chain. The approval/override schema and UI stay identical to the institutional plan — that's the resume artifact — but the user table has one row.
- **Pipeline schedule:** daily 06:30 ET cron locally on the dev VPS. No K8s CronJob in scope mode (the K8s manifests live in the Phase 10 artifacts).
- **Stage isolation, replay determinism, regime detector, ensemble:** stay 100%. These are the institutional-pattern markers.
- **Override-learning:** deferred indefinitely. Capture the override data anyway (it's cheap and resume-relevant); model on top of it later.

**What stays (resume-load-bearing)**

- Eight-stage pipeline with rigid contracts between stages, regime-conditional ensemble, signal decay tracking, risk validation gate, AI explainability with citations, immutable audit log of every decision. All of it.

**Budget impact:** $0/mo additional. LLM costs roll up from Phase 6.
