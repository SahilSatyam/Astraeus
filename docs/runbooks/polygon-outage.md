# Runbook: Polygon Outage

## Trigger

- Alert: `md_ingest_lag_seconds{source="polygon"} > 300` for 5 minutes
- Alert: `md_dlq_depth{source="polygon"} > 10` for 5 minutes
- Manual: Polygon status page reports degradation

## Impact

- Historical backfills from Polygon will fail or stall
- No impact on streaming (Alpaca WebSocket is independent)
- No impact on existing data — already-ingested bars are immutable

## Diagnosis

1. Check Polygon status: https://status.polygon.io/
2. Check adapter logs:
   ```bash
   docker compose logs workers | grep polygon
   ```
3. Check DLQ depth:
   ```bash
   curl http://localhost:8000/md/dlq?source=polygon
   ```
4. Check outbox backlog:
   ```sql
   SELECT count(*) FROM outbox WHERE published_at IS NULL;
   ```

## Resolution

### If Polygon is down (confirmed outage)

1. **Do nothing for streaming** — Alpaca handles live data independently.

2. **Switch backfills to AlphaVantage** (hot backup):
   ```bash
   # Re-run the failed backfill with alphavantage source
   uv run python scripts/md-backfill.py --source alphavantage \
       --symbols AAPL,MSFT --start 2024-01-01 --end 2024-01-31
   ```
   Note: AlphaVantage free tier is 5 calls/min, 500/day. Only use for
   critical symbols during outage.

3. **Use Yahoo as last-resort cross-check** (unreliable but free):
   ```bash
   uv run python scripts/md-backfill.py --source yahoo \
       --symbols AAPL,MSFT --start 2024-01-01 --end 2024-01-31
   ```

4. **Wait and replay** — once Polygon recovers:
   ```bash
   # Replay the window that was missed
   uv run python scripts/md-replay.py --source polygon \
       --from 2024-01-15 --to 2024-01-20 --verify
   ```

### If it's a rate limit issue (429 responses)

1. Check current rate limit configuration:
   ```python
   # In polygon.py: _RATE_LIMIT = RateLimiter(rate=5, period=60.0)
   ```
2. If on free tier, reduce batch sizes or add delays between symbols.
3. If on paid tier, verify API key is valid and not expired.

### If it's a schema drift (unexpected response format)

1. Check DLQ entries for the error type:
   ```bash
   curl http://localhost:8000/md/dlq?source=polygon | jq '.[0].error_type'
   ```
2. If `KeyError` or `ValidationError`, Polygon changed their response format.
3. Raw responses are archived in MinIO — inspect:
   ```bash
   mc ls local/astraeus-raw-responses/polygon/2024/01/
   ```
4. Update the adapter parser and replay from archive.

## Recovery Verification

After resolution, verify data integrity:

```bash
# Check for gaps in the affected window
curl "http://localhost:8000/md/gaps?symbol=AAPL"

# Verify hash consistency
uv run python scripts/md-replay.py --source polygon \
    --symbol AAPL --from 2024-01-01 --to 2024-01-31 --verify --dry-run
```

## Escalation

- If outage persists > 24 hours: consider Polygon Starter tier ($29/mo)
- If data corruption suspected: full replay from MinIO archive
