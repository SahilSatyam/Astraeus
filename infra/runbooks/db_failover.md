# Runbook: Database Failover

**Last game-day execution:** TBD
**SLO:** Postgres failover RTO ≤ 30s; zero data loss

## Symptom
- `PostgresFailoverTriggered` alert fires
- Application logs show connection refused / timeout to primary
- CNPG cluster status shows switchover in progress

## Severity
- **P1** if during market hours (trading affected)
- **P2** if off-hours (research/workers affected)

## Immediate Stabilization

1. **Verify CNPG handled it automatically:**
   ```bash
   kubectl get cluster -n data astraeus-db -o jsonpath='{.status.phase}'
   # Expected: "Cluster in healthy state" within 30s
   ```

2. **Check new primary:**
   ```bash
   kubectl get pods -n data -l cnpg.io/cluster=astraeus-db,role=primary
   ```

3. **If CNPG did NOT failover automatically:**
   ```bash
   kubectl cnpg promote -n data astraeus-db <replica-pod-name>
   ```

## Diagnosis

1. Check why the primary died:
   ```bash
   kubectl logs -n data <old-primary-pod> --previous
   kubectl describe pod -n data <old-primary-pod>
   ```

2. Check WAL continuity:
   ```bash
   kubectl cnpg status -n data astraeus-db
   # Verify "Continuous Archiving" shows no gaps
   ```

3. Check application reconnection:
   ```bash
   kubectl logs -n research -l app.kubernetes.io/name=astraeus-api --since=5m | grep -i "database\|connection"
   ```

## Recovery

1. Once new primary is healthy, verify replication:
   ```bash
   kubectl cnpg status -n data astraeus-db
   # All replicas should show "Streaming" state
   ```

2. If the old primary pod is stuck, delete it (CNPG will recreate as replica):
   ```bash
   kubectl delete pod -n data <old-primary-pod>
   ```

3. Verify application health:
   ```bash
   curl -s http://api.astraeus.local/health/ready | jq .
   ```

## Post-Incident

- Record actual RTO (time from primary death to new primary accepting writes)
- Verify zero data loss by checking WAL continuity
- If RTO > 30s, investigate and file improvement ticket
- Update this runbook with any new findings

## Escalation
- If failover does not complete within 2 minutes: manual promote
- If data loss suspected: STOP all writes, engage full incident response
