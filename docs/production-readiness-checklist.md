# Production Readiness Checklist

Phase 10 exit gate. Every item must be signed off before the platform is considered production-ready.

## Per-Service Checklist

### Research API

- [ ] Helm chart passes `helm lint` and schema validation
- [ ] Resource requests/limits set; verified via load test
- [ ] Liveness and readiness probes distinct; both tested under load
- [ ] PDB present; `maxUnavailable` ≤ 1
- [ ] HPA configured; tested via synthetic load
- [ ] ServiceMonitor scraped; Grafana dashboard exists
- [ ] SLO (99.9% availability, p99 < 800ms) with burn-rate alert and runbook
- [ ] NetworkPolicy default-deny + explicit allows
- [ ] mTLS enforced for service-to-service
- [ ] Secrets via ExternalSecret; no env-var secrets
- [ ] IRSA configured; least privilege confirmed
- [ ] Image signed (Cosign), scanned (Trivy), pinned by digest
- [ ] Logs structured JSON; trace ID propagated
- [ ] Chaos experiment (pod-kill) passing
- [ ] Graceful shutdown handles in-flight requests; tested by pod kill

### OMS (Order Management System)

- [ ] Helm chart passes `helm lint` and schema validation
- [ ] Resource requests/limits set; verified via load test
- [ ] Liveness and readiness probes distinct; both tested under load
- [ ] PDB present; `maxUnavailable` ≤ 1
- [ ] Blue/green rollout configured; manual cutover tested
- [ ] ServiceMonitor scraped; Grafana dashboard exists
- [ ] SLO (p99 ack < 200ms, zero recon drift) with alerts and runbooks
- [ ] NetworkPolicy default-deny + explicit allows
- [ ] mTLS enforced (trading namespace)
- [ ] Secrets via ExternalSecret; broker keys in Vault/SM
- [ ] IRSA configured; least privilege confirmed
- [ ] Image signed, scanned, pinned by digest
- [ ] Logs structured JSON; trace ID propagated
- [ ] Chaos experiments (broker-latency, pod-kill) passing
- [ ] Graceful shutdown preserves in-flight orders; tested by pod kill
- [ ] Kill-switch survives pod restarts

### Workers

- [ ] Helm chart passes `helm lint`
- [ ] Resource requests/limits set
- [ ] Liveness and readiness probes configured
- [ ] PDB present
- [ ] Rolling update with `maxSurge=1`
- [ ] ServiceMonitor scraped
- [ ] NetworkPolicy configured
- [ ] Image signed and scanned
- [ ] Idempotent processing verified

### Web (Next.js)

- [ ] Helm chart passes `helm lint`
- [ ] Resource requests/limits set
- [ ] Health probes configured
- [ ] PDB present
- [ ] Canary rollout configured and tested
- [ ] ServiceMonitor scraped
- [ ] NetworkPolicy configured
- [ ] Image signed and scanned

## Cluster-Wide Checklist

- [ ] ArgoCD root app reconciles a clean cluster end-to-end
- [ ] Terraform `plan` is empty against prod (no drift)
- [ ] Backup restoration tested; last drill ≤ 90 days old
- [ ] All alerts have runbook URLs; runbook coverage = 100%
- [ ] Audit log retention configured per data class
- [ ] DR drill documented and passing
- [ ] On-call rotation defined; pager tested
- [ ] Security scan (kube-bench, Trivy) clean of high/critical
- [ ] Cost dashboards live; budget alerts armed
- [ ] Game day completed in last 90 days; runbooks updated from findings
- [ ] `make dev-k8s` brings up full stack in < 20 minutes
- [ ] No `latest` tag in any chart; CI fails if found

## Sign-Off

| Reviewer | Date | Status |
|----------|------|--------|
| | | |

---

*This checklist is the Phase 10 deliverable. A signature here is the phase exit.*
