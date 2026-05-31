# Kubernetes Infrastructure

Production-grade Kubernetes manifests for the Astraeus platform.

## Structure

```
infra/k8s/
├── chaos/                          # Chaos Mesh experiment CRDs
│   ├── pod-kill.yaml               # Random pod kill (non-trading)
│   ├── node-drain.yaml             # Node drain simulation
│   ├── db-failover.yaml            # Postgres primary kill
│   ├── network-partition.yaml      # AZ partition
│   └── broker-latency.yaml         # Broker API latency injection
├── data/
│   └── cnpg-cluster.yaml           # CloudNativePG Postgres cluster (HA, WAL archiving)
├── namespaces/                     # Namespace definitions with security
│   ├── research.yaml               # PSA restricted + ResourceQuota + LimitRange
│   ├── trading.yaml                # PSA restricted + Linkerd mTLS + quotas
│   ├── web.yaml
│   ├── agents.yaml
│   ├── data.yaml
│   └── streaming.yaml
├── observability/
│   ├── slo-rules.yaml              # Prometheus SLO recording + alerting rules
│   ├── cost-controls.yaml          # OpenCost config + budget alerts
│   └── grafana-dashboards/
│       ├── api-slo.json            # Research API SLO dashboard
│       ├── oms-slo.json            # OMS SLO dashboard
│       └── cluster-capacity.json   # Cluster capacity + cost dashboard
└── platform/
    ├── otel-collector.yaml         # OpenTelemetry Collector (traces → Tempo, logs → Loki)
    ├── kyverno-policies.yaml       # Admission policies (signed images, no latest, resources)
    ├── linkerd-config.yaml         # mTLS authorization policies for trading
    └── velero-schedule.yaml        # Backup schedules (daily + weekly)
```

## Helm Charts

Each service has its own Helm chart at `apps/<service>/deploy/chart/`:

| Service | Strategy | Namespace | Templates |
|---------|----------|-----------|-----------|
| API | Canary (Argo Rollouts) | research | deployment, rollout, hpa, pdb, networkpolicy, servicemonitor, ingress, externalsecret, analysis-template |
| Workers | Rolling update | research | deployment, hpa, pdb, networkpolicy, servicemonitor |
| OMS | Blue/Green (manual cutover) | trading | rollout, pdb, networkpolicy, servicemonitor |
| Web | Canary (Argo Rollouts) | web | deployment, rollout, hpa, pdb, networkpolicy, servicemonitor, ingress |

Umbrella chart at `charts/astraeus/` for local dev (all services, minimal resources).

## Local Development

```bash
# Spin up full kind cluster with all platform services
make dev-k8s

# Live-reload development (requires tilt)
tilt up

# Lint all charts
make helm-lint

# Render templates (dry-run)
make helm-template

# Tear down
make k8s-down
```

## Security Posture

- **Pod Security Admission:** `restricted` level on all application namespaces
- **NetworkPolicy:** default-deny per namespace; explicit allowlists
- **mTLS:** Linkerd service mesh; trading namespace requires authenticated mesh traffic
- **Admission control:** Kyverno policies enforce signed images, resource limits, no `latest` tag
- **Secrets:** ExternalSecrets → Vault/AWS SM; no env-var secrets
- **IRSA:** Workload identity for AWS access; no node-instance-profile grants

## Chaos Experiments

All experiments are scheduled off-hours. The trading namespace is never targeted during market hours (09:30–16:00 ET).

| Experiment | Frequency | Blast Radius | Pass Criteria |
|-----------|-----------|--------------|---------------|
| Pod kill | Weekly (Sat 02:00 UTC) | Low | No alert fires |
| Node drain | Monthly | Medium | Drain ≤ 5min, zero failed requests |
| DB failover | Monthly | High | RTO ≤ 30s, zero data loss |
| AZ partition | Monthly | High | Postgres failover, Redpanda re-elects |
| Broker latency | Weekly (Sat 06:00 UTC) | Medium | Kill-switch arms, no double-submits |

## SLO Alerts

Burn-rate alerts (not threshold-crossing) per Google SRE playbook. Every alert has a runbook URL.

| Service | SLI | SLO | Alert Type |
|---------|-----|-----|------------|
| Research API | Error rate | 99.9% / 30d | Fast burn (page) + slow burn (ticket) |
| Research API | p99 latency | < 800ms | Warning |
| OMS | Error rate | 99.9% | Critical (hard gate) |
| OMS | Order ack p99 | < 200ms | Critical |
| OMS | Recon drift | 0 events | Critical (hard gate) |
| Market data | Tick freshness | p99 < 5s | Warning |
