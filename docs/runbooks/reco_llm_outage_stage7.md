# Runbook: LLM Outage During Stage 7 (Thesis Generation)

## Trigger
Stage 7 (thesis generation) fails or times out, causing the pipeline run to be marked `degraded`. The metric `astraeus_reco_stage_failure_total{stage="thesis"}` increments.

## What it means
The AI thesis generator could not reach the LLM API (Anthropic Claude) to produce explanations for the day's recommendations. This is the most common and least impactful degradation — all recommendations are still available with scores, weights, and risk validation. Only the natural-language thesis text is missing.

## Impact
- **Recommendations:** Fully available (scores, weights, attribution, risk status)
- **Thesis text:** Shows "Thesis generation pending" placeholder
- **HITL workflow:** Operator can still approve/reject based on quantitative data
- **Override dataset:** Unaffected

## Diagnosis

1. **Check LLM API status:**
   - Anthropic: https://status.anthropic.com
   - Check if the issue is rate limiting vs full outage

2. **Check cost budget:**
   ```
   grep "thesis_generation_failed" /var/log/astraeus/recommender.log | tail -5
   ```
   If error mentions "cost overrun" or "budget exceeded", the per-recommendation budget cap is too low.

3. **Check timeout:**
   Default thesis timeout is 30s per recommendation. If the model is slow (high load), timeouts will cascade.

4. **Verify API key:**
   Ensure the `ANTHROPIC_API_KEY` environment variable is set and valid.

## Resolution

### LLM API is down
- **Do nothing.** The pipeline produced valid recommendations without thesis text. Review them on quantitative merit.
- The next day's run will attempt thesis generation again.
- If you need thesis text for today's recommendations, trigger a partial replay once the API recovers.

### Rate limiting
- Check the `max_concurrent` setting in ThesisStage (default: 3). Reduce to 1 if hitting rate limits.
- Check if other workflows (daily_brief, portfolio_commentary) are consuming the same API quota.

### Budget exceeded
- Increase `budget_per_rec` in ThesisStage config (default: $0.05/recommendation)
- With 10 recommendations at $0.05 each, daily thesis cost is ~$0.50

### Timeout
- Increase `timeout_s` from 30 to 60 if the model is consistently slow
- Consider reducing the thesis prompt complexity

## Recovery
To regenerate theses for an existing run:
```
POST /reco/replay?date=YYYY-MM-DD
```
This re-runs the full pipeline. A future enhancement will support stage-level replay (re-run only Stage 7).

## Prevention
- Monitor `astraeus_reco_stage_failure_total{stage="thesis"}` — alert if >0 for 2+ consecutive days
- Set up a secondary LLM provider as fallback (OpenAI) — not yet implemented
- Keep per-recommendation budget at 2x the typical cost to absorb price increases
