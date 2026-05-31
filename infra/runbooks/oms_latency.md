# Runbook: OMS High Latency

**SLO:** Order ack p99 < 200ms

## Symptom
- `OMSHighOrderLatency` alert fires
- Orders taking longer than expected to acknowledge
- Dashboard shows p99 latency spike

## Severity
- **P1** during market hours — slow acks can cause missed fills or stale prices
- **P3** outside market hours

## Immediate Stabilization

1. **Check if it's a systemic issue or isolated:**
   ```bash
   # Check per-endpoint latency
   kubectl logs -n trading -l app.kubernetes.io/name=astraeus-oms --since=5m | grep "duration_ms" | sort -t= -k2 -rn | head -20
   ```

2. **Check pod resource usage:**
   ```bash
   kubectl top pods -n trading -l app.kubernetes.io/name=astraeus-oms
   ```

3. **If CPU/memory saturated, scale up (if not at limit):**
   ```bash
   kubectl scale deployment/astraeus-oms -n trading --replicas=3
   ```

## Diagnosis

1. **Database query latency:**
   ```bash
   # Check slow queries in Postgres
   kubectl exec -n data -l cnpg.io/cluster=astraeus-db,role=primary -- \
     psql -c "SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;"
   ```

2. **Broker API latency:**
   ```bash
   # Check if broker responses are slow
   kubectl logs -n trading -l app.kubernetes.io/name=astraeus-oms | grep "broker_response_ms"
   ```

3. **Network issues:**
   ```bash
   # Check if NetworkPolicy is causing drops
   kubectl describe networkpolicy -n trading
   # Check DNS resolution time
   kubectl exec -n trading deploy/astraeus-oms -- nslookup api.alpaca.markets
   ```

4. **GC pressure (Python):**
   ```bash
   kubectl logs -n trading -l app.kubernetes.io/name=astraeus-oms | grep -i "gc\|garbage"
   ```

## Recovery

1. **If database slow queries — check for missing indexes or lock contention.**

2. **If broker API slow — this is external; nothing to fix. Monitor and document.**

3. **If resource pressure — increase limits in Helm values and redeploy:**
   ```bash
   # Update values and sync
   argocd app sync trading-oms
   ```

4. **If GC pressure — consider increasing memory limits or tuning GC settings.**

## Post-Incident
- Record the actual p99 during the incident
- If broker-side: document for SLA tracking
- If internal: file optimization ticket
- Review if the 200ms SLO is realistic given current architecture

## Escalation
- If latency > 1s sustained: arm kill-switch (stale prices risk)
- If correlated with errors: see oms_errors runbook
