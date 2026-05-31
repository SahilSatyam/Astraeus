# Runbook: Pipeline Degraded

## Trigger
The daily recommendation pipeline completes with `status = degraded` instead of `done`.

## What it means
One or more late-stage components (portfolio optimizer, risk gate, or thesis generator) failed, but the earlier stages (aggregation, regime detection, signals, ensemble) completed successfully. Recommendations may still be available, but with missing information.

## Diagnosis

1. **Check the run record:**
   ```sql
   SELECT run_id, status, notes, started_at, finished_at
   FROM recommender_run
   WHERE run_date = CURRENT_DATE AND status = 'degraded';
   ```

2. **Identify failed stages** from the structured logs:
   ```
   grep "stage_degraded_failure" /var/log/astraeus/recommender.log | tail -5
   ```

3. **Common failure patterns:**

   | Failed Stage | Likely Cause | Impact |
   |---|---|---|
   | `portfolio` | Optimizer infeasibility, solver timeout | No sized positions — recommendations have scores but no weights |
   | `risk` | Risk engine misconfiguration, missing market data for beta/liquidity | Positions not validated — all pass by default |
   | `thesis` | LLM API outage, budget exceeded, timeout | Recommendations available but without AI explanation |

## Resolution

### Portfolio stage failure
- Check if the covariance matrix is PSD (condition number in logs)
- Verify the optimizer solver chain (ECOS → CLARABEL → SCS) isn't exhausted
- Fallback: the pipeline uses score-proportional weighting automatically

### Risk stage failure
- Verify risk limits configuration hasn't been corrupted
- Check if market data (ADV, beta) is stale
- Temporary fix: the pipeline passes allocations through without risk checks

### Thesis stage failure
- Check LLM API status (Anthropic status page)
- Verify per-recommendation budget cap hasn't been set too low
- Check `astraeus_reco_stage_failure_total{stage="thesis"}` metric
- This is the most common degradation — recommendations are fully usable without thesis text

## Recovery
No manual intervention needed. The next day's run will attempt all stages fresh. If the underlying issue persists (e.g., LLM outage), fix the root cause and optionally trigger a replay:

```
POST /reco/replay?date=YYYY-MM-DD
```

## Escalation
If the pipeline is degraded for 3+ consecutive days, investigate the root cause rather than accepting degraded mode as normal.
