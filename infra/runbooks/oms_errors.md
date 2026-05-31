# Runbook: OMS Error Rate Spike

**SLO:** OMS error rate < 0.1% (hard gate)

## Symptom
- `OMSHighErrorRate` alert fires
- Order submissions returning 5xx
- Kill-switch may auto-arm if errors correlate with reconciliation drift

## Severity
- **P1** during market hours — orders may be failing
- **P2** outside market hours

## Immediate Stabilization

1. **Check if kill-switch is armed:**
   ```bash
   curl -s http://oms.trading:8000/killswitch/status | jq .
   ```

2. **If not armed and errors are order-related, arm it:**
   ```bash
   curl -X POST http://oms.trading:8000/killswitch/global/arm \
     -H "Content-Type: application/json" \
     -d '{"armed_by": "operator", "reason": "OMS error rate spike"}'
   ```

3. **Check which endpoint is failing:**
   ```bash
   kubectl logs -n trading -l app.kubernetes.io/name=astraeus-oms --since=5m | grep -i "error\|500\|exception"
   ```

## Diagnosis

1. **Database connectivity:**
   ```bash
   kubectl exec -n trading deploy/astraeus-oms -- python -c "from astraeus_oms.dependencies import get_db; print('OK')"
   ```

2. **Broker connectivity:**
   ```bash
   kubectl logs -n trading -l app.kubernetes.io/name=astraeus-oms | grep -i "broker\|alpaca\|ibkr\|connection"
   ```

3. **Resource pressure:**
   ```bash
   kubectl top pods -n trading
   kubectl describe pod -n trading -l app.kubernetes.io/name=astraeus-oms | grep -A5 "Conditions"
   ```

4. **Recent deployment:**
   ```bash
   # Check if a rollout just happened
   kubectl argo rollouts status astraeus-oms -n trading
   kubectl argo rollouts history astraeus-oms -n trading
   ```

## Recovery

1. **If caused by bad deployment — rollback:**
   ```bash
   kubectl argo rollouts undo astraeus-oms -n trading
   ```

2. **If database issue — check CNPG:**
   ```bash
   kubectl get cluster -n data astraeus-db -o jsonpath='{.status.phase}'
   ```

3. **If broker issue — see broker_disconnect runbook.**

4. **Once resolved, disarm kill-switch:**
   ```bash
   curl -X POST http://oms.trading:8000/killswitch/global/disarm \
     -H "Content-Type: application/json" \
     -d '{"armed_by": "operator", "reason": "error rate resolved"}'
   ```

## Post-Incident
- Verify zero reconciliation drift
- Check if any orders were left in intermediate states
- Review error budget consumption
- If rollback was needed: investigate what the bad deployment changed

## Escalation
- If errors persist after rollback: page on-call, full incident
- If reconciliation drift detected: see recon_drift runbook
