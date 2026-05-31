# Runbook: Research API Error Budget Burn

**SLO:** 99.9% availability over 30 days (43 min/month error budget)

## Symptom
- `ResearchAPIHighErrorBurnRate` (critical) — burning 14d budget in 1h
- `ResearchAPISlowErrorBurn` (warning) — burning 30d budget in 6h

## Severity
- **P1** if fast burn (critical alert)
- **P3** if slow burn (warning alert) — investigate within 4 hours

## Immediate Stabilization

1. **Check current error rate:**
   ```bash
   curl -s "http://prometheus:9090/api/v1/query?query=slo:api_requests:error_ratio_5m" | jq '.data.result[0].value[1]'
   ```

2. **Check which endpoints are failing:**
   ```bash
   kubectl logs -n research -l app.kubernetes.io/name=astraeus-api --since=10m | grep -c "500\|error"
   kubectl logs -n research -l app.kubernetes.io/name=astraeus-api --since=10m | grep "500" | awk '{print $NF}' | sort | uniq -c | sort -rn
   ```

3. **If a canary is in progress, check if it's the canary:**
   ```bash
   kubectl argo rollouts status astraeus-api -n research
   # If canary is active and errors correlate, abort:
   kubectl argo rollouts abort astraeus-api -n research
   ```

## Diagnosis

1. **Recent deployment?**
   ```bash
   kubectl argo rollouts history astraeus-api -n research
   ```

2. **Dependency health:**
   ```bash
   # Database
   kubectl get cluster -n data astraeus-db -o jsonpath='{.status.phase}'
   # Redis
   kubectl exec -n data deploy/redis -- redis-cli ping
   # Downstream services
   curl -s http://api.research:8000/health/ready | jq .
   ```

3. **Resource exhaustion:**
   ```bash
   kubectl top pods -n research -l app.kubernetes.io/name=astraeus-api
   kubectl describe hpa -n research astraeus-api
   ```

## Recovery

1. **If bad deployment — rollback:**
   ```bash
   kubectl argo rollouts undo astraeus-api -n research
   ```

2. **If dependency failure — fix the dependency** (see relevant runbook).

3. **If resource exhaustion — scale:**
   ```bash
   kubectl scale deployment/astraeus-api -n research --replicas=4
   ```

4. **If unknown — restart pods** (clears potential memory leaks):
   ```bash
   kubectl rollout restart deployment/astraeus-api -n research
   ```

## Post-Incident
- Calculate actual error budget consumed
- If > 50% budget consumed: freeze non-critical deployments until budget recovers
- File post-incident review if fast-burn alert fired
- Update this runbook with the specific failure mode encountered

## Escalation
- If error rate > 5% sustained: page on-call
- If all replicas are failing: check cluster-wide issues (DNS, network, node health)
