# Runbook: Secret Rotation

## Symptom
- Scheduled rotation reminder (quarterly)
- Secret leak detected by gitleaks
- Credential expiry warning from Vault/AWS SM

## Severity
- **P1** if secret was leaked (rotate immediately)
- **P3** if scheduled rotation

## Secrets Inventory

| Secret | Location | Rotation Cadence | Owner |
|--------|----------|-----------------|-------|
| Broker API key (Alpaca) | AWS Secrets Manager | Quarterly | operator |
| Broker API key (IBKR) | AWS Secrets Manager | Quarterly | operator |
| Database credentials | Vault dynamic | Auto (1h TTL) | platform |
| Polygon API key | AWS Secrets Manager | Quarterly | operator |
| Anthropic API key | AWS Secrets Manager | Quarterly | operator |
| GitHub PAT (ArgoCD) | Vault | Quarterly | platform |
| Grafana admin | Vault | Quarterly | platform |

## Procedure: Scheduled Rotation

1. **Generate new credential at the source** (broker dashboard, API console, etc.)

2. **Update in Secrets Manager / Vault:**
   ```bash
   # AWS Secrets Manager
   aws secretsmanager update-secret --secret-id astraeus/prod/broker-alpaca \
     --secret-string '{"api_key":"NEW_KEY","api_secret":"NEW_SECRET"}'

   # Vault
   vault kv put secret/astraeus/prod/polygon api_key=NEW_KEY
   ```

3. **Trigger ExternalSecrets sync:**
   ```bash
   # Force refresh (normally auto-syncs within refreshInterval)
   kubectl annotate externalsecret -n trading broker-creds force-sync=$(date +%s) --overwrite
   ```

4. **Verify workloads picked up new secret:**
   ```bash
   # Pods using file-mounted secrets will see changes without restart
   # Pods using env vars need a rollout restart
   kubectl rollout restart deployment/astraeus-oms -n trading
   ```

5. **Revoke old credential at the source.**

## Procedure: Emergency Rotation (Leak Detected)

1. **Immediately revoke the leaked credential at the source.**
2. **Generate new credential.**
3. **Update in Secrets Manager / Vault (step 2 above).**
4. **Audit: check if the leaked credential was used maliciously:**
   ```bash
   # Check broker activity
   # Check audit logs for unauthorized access
   kubectl logs -n trading -l app=astraeus-oms --since=24h | grep -i "auth\|unauthorized"
   ```
5. **If malicious use detected: escalate to full incident response.**

## Post-Rotation
- Verify all services healthy after rotation
- Update rotation log (date, which secret, who rotated)
- If leak: file incident report, update gitleaks rules

## Escalation
- If rotation breaks a service: rollback to old secret (if not revoked), investigate
- If malicious use of leaked secret: full incident, notify affected parties
