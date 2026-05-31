# Kubernetes Infrastructure

Production-grade Kubernetes manifests for the Astraeus platform.

## Structure

```
infra/k8s/
├── chaos/                  # Chaos Mesh experiment CRDs
│   ├── pod-kill.yaml       # Random pod kill (non-trading)
│   ├── node-drain.yaml     # Node drain simulation
│   ├── db-failover.yaml    # Postgres primary kill
│   ├── network-partition.yaml  # AZ partition
│   └── broker-latency.yaml # Broker API latency injection
└── observability/
    └── slo-rules.yaml      # Prometheus SLO recording + alerting rules
```

## Helm Charts

Each service has its own Helm chart at `apps/<service>/deploy/chart/`:

| Service | Strategy | Namespace |
|---------|----------|-----------|
| API | Canary (Argo Rollouts) | research |
| Workers | Rolling update | research |
| OMS | Blue/Green (manual cutover) | trading |
| Web | Canary (Argo Rollouts) | web |

## Local Development

```bash
# Spin up full kind cluster with all platform services
make dev-k8s

# Lint all charts
make helm-lint

# Render templates (dry-run)
make helm-template

# Tear down
make k8s-down
```

## Chaos Experiments

All experiments are scheduled off-hours. The trading namespace is never targeted during market hours (09:30–16:00 ET).

| Experiment | Frequency | Blast Radius |
|-----------|-----------|--------------|
| Pod kill | Weekly (Sat 02:00 UTC) | Low |
| Node drain | Monthly | Medium |
| DB failover | Monthly | High |
| AZ partition | Monthly | High |
| Broker latency | Weekly (Sat 06:00 UTC) | Medium |

## SLO Alerts

Burn-rate alerts (not threshold-crossing) per Google SRE playbook. Every alert has a runbook URL. See `infra/k8s/observability/slo-rules.yaml`.
