# Portfolio Construction Runbook

Operational guide for the Phase 4 daily portfolio pipeline.

---

## 1. Daily Pipeline Overview

The pipeline runs at **16:30 ET** (post-close) and produces:
- A target portfolio per strategy
- A risk report per portfolio
- A rejection log (if gate fails)
- A PDF report cached to S3

**Trigger:** Cron at 16:30 ET OR event-driven via `signals.daily_batch.completed.v1`.

---

## 2. How to Backfill

After an estimator change, policy update, or data correction:

```bash
# Single date
python -m astraeus_portfolio.orchestration.replay replay \
    --strategy momentum_daily --date 2026-05-28

# Date range (serial)
python -m astraeus_portfolio.orchestration.replay backfill \
    --strategy momentum_daily --start 2026-01-01 --end 2026-05-28

# Force overwrite (preserves prior version)
python -m astraeus_portfolio.orchestration.replay replay \
    --strategy momentum_daily --date 2026-05-28 --force
```

**Important:** `--force` creates a new version row; the prior version is preserved in `task_runs.version`. Never deletes data.

---

## 3. How to Verify Determinism

```bash
python -m astraeus_portfolio.orchestration.replay verify \
    --strategy momentum_daily --date 2026-05-28
```

Exit code 0 = deterministic. Exit code 1 = hash mismatch (investigate).

A determinism violation emits to `portfolio.determinism_violations.v1` and should trigger an alert.

---

## 4. How to Override Risk Policy in Emergency

The risk policy is defined in `RiskPolicy` (code) or a YAML config file. To temporarily relax thresholds:

1. **Identify the failing check** from the `risk_rejections` table:
   ```sql
   SELECT failed_checks, fallback_action
   FROM risk_rejections
   WHERE strategy_id = 'momentum_daily'
   ORDER BY as_of_ts DESC LIMIT 5;
   ```

2. **Adjust the threshold** in the strategy's pipeline config:
   ```python
   RiskPolicy(
       policy_version="v1.1-emergency",
       thresholds=RiskPolicyThresholds(
           cvar_95_hist_max=0.05,  # Relaxed from 0.03
       ),
   )
   ```

3. **Re-run the pipeline** for the affected date:
   ```bash
   python -m astraeus_portfolio.orchestration.replay replay \
       --strategy momentum_daily --date 2026-05-28 --force
   ```

4. **Revert the policy** once the emergency passes. The `policy_version` field in `risk_reports` tracks which version was active.

**Never** edit thresholds without incrementing `policy_version`.

---

## 5. How to Interpret Rejection Codes

Query the rejection log:

```sql
SELECT rejection_id, strategy_id, as_of_ts, optimizer,
       failed_checks, fallback_action, fallback_outcome
FROM risk_rejections
WHERE strategy_id = 'momentum_daily'
ORDER BY as_of_ts DESC;
```

### Common failed checks

| Check | Meaning | Action |
|-------|---------|--------|
| `cvar_95_hist` | 95% CVaR exceeds 3% NAV | Reduce position sizes or add hedges |
| `cvar_99_hist` | 99% CVaR exceeds 5% NAV | Same as above, more aggressive |
| `stress_gfc_2008` | GFC scenario loss > 25% | Reduce equity beta |
| `stress_rate_shock` | Rate shock loss > 15% | Reduce duration-sensitive positions |
| `max_cluster_weight` | Single cluster > 35% variance | Diversify across clusters |
| `beta_deviation` | Portfolio beta > 0.10 from target | Add/remove market hedge |
| `liquidity_5day_pct` | < 90% liquidatable in 5 days | Reduce illiquid positions |
| `single_name_weight` | Single position > 12% | Reduce concentrated position |

### Fallback actions

| Action | Behavior |
|--------|----------|
| `cash` | Portfolio = 100% cash. Safest but zero alpha. |
| `hold_prior` | Reuse yesterday's accepted portfolio. Low risk if market hasn't moved much. |
| `retry_relaxed` | Re-run optimizer with one constraint dropped. **Once only.** |
| `escalate_hitl` | No portfolio published. Requires manual intervention. |

---

## 6. Monitoring & Alerts

### Key Prometheus metrics

| Metric | Alert threshold |
|--------|----------------|
| `astraeus_portfolio_optimizer_solve_time_ms` | p99 > 5000ms |
| `astraeus_portfolio_gate_decision_total{decision="rejected"}` | > 3 rejections in 24h |
| `astraeus_portfolio_pipeline_duration_ms` | p99 > 30000ms |
| `astraeus_portfolio_fallback_actions_total{action="escalate_hitl"}` | Any occurrence |

### Grafana dashboard panels

1. **Pipeline health:** success/failure rate over 7 days
2. **Solve time distribution:** per-optimizer histogram
3. **Gate rejection rate:** rolling 30-day rejection % per strategy
4. **Attribution decomposition:** factor vs idio PnL time series

---

## 7. Troubleshooting

### Pipeline fails with "covariance estimation failed"

- **Cause:** Insufficient return history (< n+1 observations) or NaN in returns.
- **Fix:** Check Phase 1 data ingestion. Verify `returns_matrix` has no gaps.

### Optimizer returns "infeasible" after all relaxations

- **Cause:** Hard constraints (box, liquidity) are contradictory with the universe.
- **Fix:** Check if universe has changed (delistings, new IPOs with no data). Verify ADV data is fresh.

### Determinism violation on replay

- **Cause:** Non-deterministic input (e.g., random seed not fixed, data changed between runs).
- **Fix:** Verify `seed` is set in OptContext. Check if upstream data was backfilled between runs.

### Attribution shows 100% idiosyncratic

- **Cause:** Factor return history is missing or misaligned.
- **Fix:** Verify `factor_returns` table has data for the attribution date. Check Ken French data ingestion job.

---

## 8. Database Queries

### Latest portfolio for a strategy
```sql
SELECT * FROM target_portfolios
WHERE strategy_id = 'momentum_daily'
ORDER BY as_of_ts DESC, version DESC
LIMIT 1;
```

### Portfolio weights
```sql
SELECT pw.symbol, pw.weight, pw.sector
FROM portfolio_weights pw
JOIN target_portfolios tp ON tp.portfolio_id = pw.portfolio_id
WHERE tp.strategy_id = 'momentum_daily'
  AND tp.as_of_ts = '2026-05-28'
ORDER BY abs(pw.weight) DESC;
```

### Risk report for a portfolio
```sql
SELECT * FROM risk_reports
WHERE portfolio_id = '<uuid>'
LIMIT 1;
```

### Rejection history (last 30 days)
```sql
SELECT as_of_ts::date, count(*) as rejections,
       jsonb_array_elements(failed_checks)->>'check_name' as check
FROM risk_rejections
WHERE strategy_id = 'momentum_daily'
  AND as_of_ts > now() - interval '30 days'
GROUP BY 1, 3
ORDER BY 1 DESC;
```

### Task run history (idempotency check)
```sql
SELECT task_name, status, version, result_hash, duration_ms
FROM task_runs
WHERE strategy_id = 'momentum_daily'
  AND as_of_date = '2026-05-28'
ORDER BY task_name, version DESC;
```
