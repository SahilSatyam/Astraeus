# Runbook: Disaster Recovery Restore

**Last drill execution:** TBD
**Target RTO:** < 90 minutes (full platform)
**Target RPO:** < 1 minute (Postgres), < 5 minutes (Redpanda)

## Symptom
- Complete cluster loss (AZ failure, account compromise, catastrophic misconfiguration)
- Decision made to invoke DR

## Severity
- **P0** — all-hands incident

## Prerequisites
- Access to Terraform state bucket (S3 in DR region)
- Access to backup bucket (S3 cross-region replicated)
- AWS credentials with admin-level access
- `terraform`, `kubectl`, `helm`, `argocd` CLI tools installed

## Procedure

### Phase 1: Infrastructure (Target: 30 minutes)

1. **Provision fresh cluster:**
   ```bash
   cd infra/terraform/envs/prod
   terraform init
   terraform apply -auto-approve
   ```

2. **Configure kubectl:**
   ```bash
   aws eks update-kubeconfig --name astraeus-prod --region us-east-1
   ```

3. **Bootstrap ArgoCD:**
   ```bash
   helm repo add argo https://argoproj.github.io/argo-helm
   helm install argocd argo/argo-cd -n argocd --create-namespace \
     --set server.extraArgs="{--insecure}"
   ```

### Phase 2: Platform Services (Target: 15 minutes)

4. **Apply root app-of-apps:**
   ```bash
   kubectl apply -f gitops/app-of-apps/root.yaml
   # ArgoCD will reconcile all applications
   ```

5. **Restore Vault from raft snapshot:**
   ```bash
   # Download latest snapshot from S3
   aws s3 cp s3://astraeus-prod-backups/vault/latest-snapshot.snap /tmp/
   vault operator raft snapshot restore /tmp/latest-snapshot.snap
   ```

### Phase 3: Data Restoration (Target: 30 minutes)

6. **Restore Postgres from CNPG backup:**
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: postgresql.cnpg.io/v1
   kind: Cluster
   metadata:
     name: astraeus-db
     namespace: data
   spec:
     instances: 3
     bootstrap:
       recovery:
         source: astraeus-db-backup
     externalClusters:
       - name: astraeus-db-backup
         barmanObjectStore:
           destinationPath: s3://astraeus-prod-backups/postgres/
           s3Credentials:
             accessKeyId:
               name: backup-creds
               key: ACCESS_KEY_ID
             secretAccessKey:
               name: backup-creds
               key: SECRET_ACCESS_KEY
   EOF
   ```

7. **Restore Redpanda topics from tiered storage:**
   ```bash
   # Redpanda with tiered storage will automatically recover from S3
   # Verify topic recovery:
   rpk topic list
   rpk topic describe market-data-ticks
   ```

8. **Verify S3 data lake accessibility:**
   ```bash
   aws s3 ls s3://astraeus-prod-data-lake/ --summarize
   ```

### Phase 4: Verification (Target: 15 minutes)

9. **Run canonical backtest for bit-for-bit verification:**
   ```bash
   # This backtest was run pre-DR and its result hash is stored
   python scripts/dr-verify-backtest.py --expected-hash <KNOWN_HASH>
   ```

10. **Verify all services healthy:**
    ```bash
    kubectl get pods --all-namespaces | grep -v Running | grep -v Completed
    argocd app list --output json | jq '.[] | select(.status.sync.status != "Synced")'
    ```

11. **Verify SLO metrics flowing:**
    ```bash
    curl -s http://prometheus:9090/api/v1/query?query=up | jq '.data.result | length'
    ```

## Post-Recovery

- Document actual RTO and RPO achieved
- Compare backtest hash — if mismatch, investigate data integrity
- Notify stakeholders of recovery completion
- Schedule post-incident review within 48 hours
- Update this runbook with any gaps found

## What We Explicitly Cannot Recover
- In-flight orders at the moment of failure (broker is source of truth)
- Real-time market data during the outage window
- Any data newer than the RPO window

## Escalation
- If Terraform apply fails: check state lock, verify credentials
- If Postgres restore fails: try point-in-time recovery to earlier timestamp
- If backtest hash mismatch: halt trading, full data audit required
