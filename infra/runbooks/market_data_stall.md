# Runbook: Market Data Stall

**SLO:** Tick-to-DB freshness p99 < 5s during market hours

## Symptom
- `MarketDataStale` alert fires
- Dashboard shows gap in tick data
- Workers report empty topic reads

## Severity
- **P1** during market hours (09:30–16:00 ET)
- **P3** outside market hours (expected — no ticks flowing)

## Immediate Stabilization

1. **Verify it's not a market holiday / pre-market:**
   ```bash
   # Check if market is actually open
   curl -s https://paper-api.alpaca.markets/v2/clock | jq '.is_open'
   ```

2. **Check Redpanda topic lag:**
   ```bash
   rpk group describe market-data-consumer
   # Look for increasing lag on market-data-ticks topic
   ```

3. **Check ingest worker health:**
   ```bash
   kubectl logs -n streaming -l app=market-data-ingest --tail=50
   kubectl get pods -n streaming -l app=market-data-ingest
   ```

## Diagnosis

1. **Data source connectivity:**
   ```bash
   # Check if the data source (Polygon/Alpaca) WebSocket is connected
   kubectl logs -n streaming -l app=market-data-ingest | grep -i "websocket\|disconnect\|error"
   ```

2. **Redpanda health:**
   ```bash
   rpk cluster health
   rpk topic describe market-data-ticks --print-all
   ```

3. **Network egress:**
   ```bash
   # Check if NetworkPolicy is blocking egress to data vendor
   kubectl describe networkpolicy -n streaming
   ```

## Recovery

1. **If ingest worker crashed — restart:**
   ```bash
   kubectl rollout restart deployment/market-data-ingest -n streaming
   ```

2. **If data source is down — wait and monitor:**
   - Check vendor status page
   - Data will backfill once source recovers (if vendor supports replay)

3. **If Redpanda is unhealthy:**
   - See Redpanda-specific runbook
   - Check broker logs: `kubectl logs -n streaming -l app=redpanda`

## Post-Incident
- Verify no gaps in stored tick data
- If gaps exist during market hours, trigger backfill for affected symbols
- Update monitoring thresholds if false positive

## Escalation
- If stall > 5 minutes during market hours: arm kill-switch for affected strategies
- If Redpanda cluster unhealthy: page on-call
