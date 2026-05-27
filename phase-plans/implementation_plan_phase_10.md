# Phase 10 — Production Hardening

**Timeline:** Weeks 28–36 · **Depends on:** Phases 7 (recommender) and 8 (live trading) stable · **Blocks:** none (final phase)

---

## 1. Phase Goals & Refined Exit Criteria

Phase 10 is the difference between "impressive demo" and "a CTO would let this near a live trading account." The work isn't building new features — it's making the existing platform survivable: deployable from cold metal, observable when things go wrong, recoverable when something corrupts, and explainable to someone holding a checklist.

The bar is not "we use Kubernetes." The bar is "we can lose any single node, any single pod, the primary database, or the entire AZ, and either keep running or recover within a stated, tested RTO." Trading platforms have asymmetric failure cost — a quiet wrong number is worse than a loud outage — so the hardening priorities are biased toward *truthful failure*: the system fails closed, the kill switch is the last thing to die, and stale data is loudly stale rather than quietly served.

Refined exit criteria:

- **Cold-start reproducible.** A new engineer can spin up a full local stack via `make dev` (kind cluster) in under 20 minutes, with no manual steps. A new cloud environment is produced from Terraform + ArgoCD bootstrap in under 90 minutes.
- **GitOps is the only path to prod.** No `kubectl apply` against prod from a laptop; ArgoCD reconciles every workload, drift is alerted on.
- **Progressive delivery proven.** At least one service ships via canary with automatic rollback on SLO violation; one ships via blue/green for instant cutover.
- **Chaos experiment passes weekly.** Pod kill, network partition, primary-DB failover, and broker disconnect each have a scheduled experiment with pass/fail criteria.
- **SLOs defined per service tier** with error budgets; alerts fire on burn-rate, not threshold-crossing; every alert has a runbook URL.
- **Security baseline.** Secrets in Vault/Cloud SM (zero secrets in env files), network policies default-deny, mTLS service-to-service, audit-log retention ≥ 7 years for trading-adjacent events.
- **Backup/DR drill executed end-to-end.** Restore Postgres + TimescaleDB + S3 + Redpanda topics into a clean cluster, verify a sample backtest reproduces bit-for-bit, document the RTO/RPO actually achieved.
- **Production readiness checklist signed off.** A real, written checklist (Section 14) — not a vibe.

---

## 2. Scope Boundaries

| In | Out |
|---|---|
| Kubernetes (kind local, EKS or GKE prod) | Bare-metal / on-prem |
| Helm charts per service, one umbrella chart | Custom operators (use existing: cnpg, redpanda-op, vault-op) |
| Terraform for cloud infra (VPC, EKS, RDS, S3, IAM) | CloudFormation / CDK / Pulumi |
| ArgoCD app-of-apps for GitOps | Flux (chosen Argo for UI + multi-tenancy) |
| Argo Rollouts for canary; native Deployment for blue/green | Flagger (Argo Rollouts integrates better with ArgoCD) |
| Chaos Mesh for experiments | LitmusChaos (Chaos Mesh has cleaner CRDs and better partition primitives) |
| Vault (or AWS Secrets Manager + External Secrets) for secrets | Secrets in env vars, sealed-secrets-only |
| OpenTelemetry collector → Tempo/Loki/Mimir or Datadog | Splunk, Elastic-only stacks |
| Prometheus + Alertmanager + Grafana | Nagios, Zabbix |
| Velero for cluster-state backup; CNPG for Postgres backups | Hand-rolled cron dumps |
| SOC 2-style audit-log discipline | Full SOC 2 attestation (consultancy-grade engagement) |
| Cost guardrails (Kubecost or OpenCost) | FinOps maturity model |
| Multi-region active/passive DR posture | Multi-region active/active |

**Why these boundaries.** This is one platform built by a small team, not a Fortune 100 with seven SREs. Active/active multi-region is a 6-month project on its own and adds Byzantine consistency problems that a single-region active/passive setup avoids. SOC 2 attestation requires an auditor; what we *can* do is build the controls so an attestation is a paperwork exercise, not a re-architecture.

---

## 3. Reference Architecture

### 3.1 Cluster topology (production)

```
                    ┌──────────────────────────────────────────┐
                    │             AWS Region: us-east-1         │
                    │                                            │
   Cloudflare ──►   │   ┌────────────────────────────────┐      │
   (WAF + CDN)      │   │  EKS Cluster (3 AZ)             │      │
                    │   │                                  │      │
                    │   │  ns: ingress       (NGINX, Cert) │      │
                    │   │  ns: platform      (Vault, OTel) │      │
                    │   │  ns: data          (CNPG, Redis) │      │
                    │   │  ns: streaming     (Redpanda)    │      │
                    │   │  ns: research      (api, workers)│      │
                    │   │  ns: trading       (oms, recon)  │      │
                    │   │  ns: agents        (ai workers)  │      │
                    │   │  ns: web           (next.js)     │      │
                    │   │  ns: observability (graf, prom)  │      │
                    │   │  ns: argocd        (gitops)      │      │
                    │   └────────────────────────────────┘      │
                    │                                            │
                    │   RDS (managed Postgres for control plane) │
                    │   S3 (data lake, backups, MLflow)          │
                    │   KMS (encryption keys)                    │
                    └──────────────────────────────────────────┘
                                      │
                                      ▼  (warm DR)
                    ┌──────────────────────────────────────────┐
                    │             AWS Region: us-west-2         │
                    │   S3 cross-region replication             │
                    │   RDS read replica (promotable)           │
                    │   EKS cluster pre-provisioned, scaled-to-0│
                    └──────────────────────────────────────────┘
```

**Namespace strategy.** Domain-based, not environment-based — environment is the cluster. Each namespace gets:
- Default-deny `NetworkPolicy`, allowlist via labels.
- Per-namespace `ResourceQuota` and `LimitRange`.
- Dedicated `ServiceAccount` per workload, no `default` SA usage.
- Pod Security Admission at `restricted` level.

**Node pools.**
- `system` (taint=critical) — Argo, Vault, ingress, observability.
- `general` — APIs, web, light workers.
- `data` — Postgres/TimescaleDB (CNPG), Redpanda; `local-ssd`-backed where available.
- `compute` — research workers, backtests; spot-eligible with PodDisruptionBudget.
- `gpu` (optional) — embedding workers, FinBERT inference.
- `trading` (taint=trading) — OMS, reconciliation; on-demand only, never spot, anti-affinity across AZ.

**Why a dedicated trading pool.** Spot interruption on the OMS during a fill is the kind of incident that ends a platform. Pay the premium, take the headache off the table.

### 3.2 Local topology

`kind` cluster + `tilt` for live reload. Same Helm charts, values files differ. Vault dev-mode, MinIO instead of S3, single-replica everything. The local stack is *the same shape* as prod — divergence is what makes "works on my machine" failures.

---

## 4. Repository & Folder Structure

This phase creates two new top-level repos (or top-level folders if monorepo): `infra/` for Terraform and `gitops/` for ArgoCD manifests. Helm charts live alongside services.

```
Astraeus/
├─ apps/
│  ├─ api/
│  │  └─ deploy/chart/                # Helm chart for this service
│  ├─ workers/
│  │  └─ deploy/chart/
│  ├─ oms/
│  │  └─ deploy/chart/
│  └─ web/
│     └─ deploy/chart/
├─ infra/
│  ├─ terraform/
│  │  ├─ modules/
│  │  │  ├─ network/                  # VPC, subnets, NAT
│  │  │  ├─ eks/                      # cluster + node groups
│  │  │  ├─ rds/                      # control-plane Postgres
│  │  │  ├─ s3/                       # data lake, backups
│  │  │  ├─ kms/                      # encryption keys
│  │  │  ├─ iam-irsa/                 # workload identity
│  │  │  └─ observability/            # managed Grafana, optional
│  │  ├─ envs/
│  │  │  ├─ dev/                      # ephemeral
│  │  │  ├─ staging/
│  │  │  └─ prod/
│  │  └─ backend.tf                   # remote state (S3 + DynamoDB)
│  ├─ kind/
│  │  ├─ cluster.yaml                 # local kind config
│  │  └─ bootstrap.sh                 # installs argocd, vault dev, etc.
│  └─ runbooks/
│     ├─ db-failover.md
│     ├─ broker-disconnect.md
│     ├─ kill-switch.md
│     └─ dr-restore.md
├─ gitops/
│  ├─ apps/                           # ArgoCD Application manifests
│  │  ├─ platform/
│  │  ├─ data/
│  │  ├─ research/
│  │  ├─ trading/
│  │  └─ web/
│  ├─ app-of-apps/
│  │  ├─ root.yaml                    # bootstraps everything
│  │  └─ projects.yaml                # ArgoCD Projects (RBAC)
│  └─ overlays/                       # per-env Helm values
│     ├─ dev/
│     ├─ staging/
│     └─ prod/
└─ charts/
   └─ astraeus/                       # umbrella chart for local dev
```

**Why split `infra/` and `gitops/`.** Terraform owns *cloud* state (VPC, IAM, RDS), Argo owns *cluster* state (workloads, configmaps, network policies). Mixing them produces circular dependencies (the cluster needs IAM, IAM needs the cluster's OIDC, etc.) and chimeric state files. The split has a clear handshake: Terraform outputs (cluster name, OIDC issuer, IAM role ARNs) become inputs to Helm values via a sealed config.

---

## 5. Helm Chart Conventions

One chart per deployable service; an umbrella chart for the local `make dev` experience and for ArgoCD app-of-apps.

```
apps/api/deploy/chart/
├─ Chart.yaml
├─ values.yaml                        # safe defaults
├─ values.schema.json                 # validated by helm lint
├─ templates/
│  ├─ deployment.yaml
│  ├─ rollout.yaml                    # Argo Rollouts (canary)
│  ├─ service.yaml
│  ├─ servicemonitor.yaml             # Prometheus scrape
│  ├─ networkpolicy.yaml
│  ├─ pdb.yaml                        # PodDisruptionBudget
│  ├─ hpa.yaml                        # HorizontalPodAutoscaler
│  ├─ externalsecret.yaml             # ExternalSecrets / Vault
│  ├─ ingress.yaml
│  └─ _helpers.tpl
└─ ci/
   └─ values-test.yaml                # for `helm template --dry-run` tests
```

**Conventions enforced by lint.**
- Every `Deployment`/`Rollout` has resource requests *and* limits.
- Every workload has `livenessProbe` and `readinessProbe` distinct (a slow GC must not kill the pod).
- `securityContext`: `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, drop all capabilities, `seccompProfile: RuntimeDefault`.
- `topologySpreadConstraints` across AZs for any replica > 1.
- Image tag is a digest (`@sha256:…`) in prod, mutable tag in dev — pinned by ArgoCD Image Updater.
- No `latest` tag anywhere; CI fails if found.

```yaml
# templates/rollout.yaml — canary skeleton
apiVersion: argoproj.io/v1alpha1
kind: Rollout
spec:
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: { duration: 5m }
        - analysis:
            templates:
              - templateName: error-rate
              - templateName: p99-latency
        - setWeight: 50
        - pause: { duration: 10m }
        - analysis: { templates: [{ templateName: error-rate }] }
        - setWeight: 100
```

`AnalysisTemplate`s query Prometheus for SLI burn during the pause windows; failure reverses the rollout automatically.

---

## 6. Terraform Layout

State in S3 + DynamoDB lock, one bucket per environment, KMS-encrypted. Modules consumed by per-env root modules — no env-conditional logic in modules.

```hcl
# infra/terraform/envs/prod/main.tf
module "network" {
  source = "../../modules/network"
  cidr   = "10.20.0.0/16"
  azs    = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

module "eks" {
  source       = "../../modules/eks"
  cluster_name = "astraeus-prod"
  vpc_id       = module.network.vpc_id
  subnet_ids   = module.network.private_subnet_ids
  node_groups  = local.node_groups
}

module "rds_control" {
  source            = "../../modules/rds"
  identifier        = "astraeus-prod-control"
  multi_az          = true
  backup_retention  = 35
  deletion_protection = true
}

module "irsa_workloads" {
  for_each   = local.workload_iam_roles
  source     = "../../modules/iam-irsa"
  cluster    = module.eks.cluster
  namespace  = each.value.namespace
  service_account = each.value.sa
  policies   = each.value.policies
}
```

**IRSA over node-IAM.** Workload identity (IAM Roles for Service Accounts) is the only way pods get AWS perms. No node-instance-profile wide-grant. A pod that wants S3 has a SA bound to a role with the *exact* prefix it needs.

**Drift detection.** `terraform plan` runs in CI on a schedule against prod; non-empty plan opens an issue. Manual cloud-console changes are an incident, not a shrug.

---

## 7. GitOps with ArgoCD

App-of-apps pattern: one root `Application` watches `gitops/app-of-apps/`, which spawns child Applications per domain.

```
gitops/app-of-apps/root.yaml
        │
        ├── platform-app  ───►  vault, cert-manager, external-secrets, otel-collector
        ├── observability-app ─►  prometheus, grafana, tempo, loki
        ├── data-app      ───►  cnpg, redis, redpanda
        ├── research-app  ───►  api, workers, mlflow
        ├── trading-app   ───►  oms, recon, killswitch
        ├── agents-app    ───►  ai-orchestrator, embeddings-worker
        └── web-app       ───►  next.js
```

**ArgoCD Projects** scope which destinations (clusters/namespaces) each Application can write to. The trading project is locked: only the trading namespace, only specific paths. Compromise of a research-app commit cannot reach OMS manifests.

**Sync policies.**
- `automated: { prune: true, selfHeal: true }` for everything except trading and data — those require manual sync to prevent surprise reconciliations during market hours.
- Sync windows on trading project: deny syncs 09:25–09:35 ET (open) and 15:55–16:05 ET (close); allow only outside market hours.
- Image Updater pins tags to digests on merge to `main`; Renovate handles upstream chart upgrades behind a PR.

**Secrets in GitOps.** No secrets in git. ExternalSecrets references Vault/AWS SM by path; ArgoCD reconciles the ExternalSecret CR, which materializes a real Secret. Sealed-Secrets considered and rejected — re-encryption ergonomics are bad, key rotation is painful.

---

## 8. Progressive Delivery

| Service tier | Strategy | Rationale |
|---|---|---|
| Web (Next.js) | Argo Rollouts canary (10%→50%→100%) | Stateless, fast metrics, rollback cheap |
| Research API | Canary with analysis on error-rate + p99 | Read-heavy, low blast radius |
| Workers (research) | Rolling with `maxSurge=1` | Job-based, idempotent |
| OMS / Trading | **Blue/green with manual cutover** | A canary that splits orders across versions is a reconciliation nightmare |
| Data services (Postgres, Redpanda) | Operator-managed, no app-level rollout | StatefulSet rolling with PDB |
| Agents | Canary with offline shadow mode first | LLM behavior changes between models; shadow before serving |

**Why blue/green for OMS.** A canary at 10% means 10% of orders go through a new code path. If a partial-fill state-machine bug appears in canary, you've split the order book across two versions and reconciliation has to merge them. Blue/green is one moment of cutover, one source of truth at any instant, easy rollback (flip back).

**Shadow mode for agents.** New LLM versions or prompt changes run in parallel against live requests; outputs are diffed and logged but not served. After a week of clean diffs, promote.

---

## 9. Chaos Engineering

Chaos Mesh with experiments scheduled via `Workflow` CRDs. Run weekly in staging, monthly in prod (off-hours).

| Experiment | Hypothesis | Pass criteria |
|---|---|---|
| Random pod kill (any non-trading ns, 1 pod / 10min) | Workloads tolerate single-pod loss | No alert fires; SLO unaffected |
| Node drain (cordon + drain 1 worker) | PDBs hold; workloads reschedule | Drain completes ≤ 5min; zero failed requests |
| AZ partition (network-loss to 1 AZ) | Cluster keeps quorum; data services continue | Postgres failover succeeds; Redpanda re-elects leaders |
| Postgres primary kill (CNPG) | Failover within 30s | RTO ≤ 30s observed; zero data loss |
| Redpanda broker kill | Producers retry, consumers continue | No data loss in topic; lag returns to 0 within 2min |
| Broker API latency injection (Alpaca/IBKR mock) | OMS retries with backoff, kill-switch arms on threshold | Kill-switch arms; no double-submits |
| DNS slow (5s lookup latency on egress) | Services degrade gracefully | Liveness probes don't false-positive |
| Time skew (NTP offset 30s on 1 node) | Timestamp-sensitive code (PIT, audit) detects | Alert fires; node is cordoned |

**The market-hours rule.** No chaos experiment touches the trading namespace during 09:30–16:00 ET. Period. Off-hours chaos is fine; market-hours chaos is irresponsible.

**Game days.** Quarterly, a half-day exercise where one engineer fires an undisclosed experiment and another runs the runbook. Outcome is timed; the runbook is updated based on what was missing or wrong.

---

## 10. SLOs, Alerts, and Runbooks

### 10.1 SLOs per service tier

| Service | SLI | SLO | Error budget |
|---|---|---|---|
| Research API | Successful response rate | 99.9% over 30d | 43 min/month |
| Research API | p99 latency | < 800ms over 30d | 1% of requests |
| Market data ingest | Tick-to-DB freshness | p99 < 5s during market hours | 1% of windows |
| Market data ingest | Daily backfill completeness | 100% by 07:00 ET | 0 (hard gate) |
| OMS | Order ack latency | p99 < 200ms | 0.1% |
| OMS | Reconciliation drift | 0 drift events / day | 0 (hard gate) |
| Recommender pipeline | Daily completion by 09:00 ET | 99% | 3 days/year |
| Web | TTI on key dashboards | p75 < 3s | 5% |

**Hard-gate SLOs** (drift, backfill completeness) skip the burn-rate model — any breach is a P1 page, no error budget.

### 10.2 Alert design

- **Burn-rate alerts**, not threshold-crossing. (`error_rate > 1%` for 5min is a flapping mess; "burning 14d budget in 1h" is a real signal.)
- Multi-window multi-burn-rate per Google SRE playbook: fast burn (2% in 1h) pages; slow burn (10% in 6h) tickets.
- Every alert has: SLO it relates to, suspected cause taxonomy, runbook URL, owner team. Alerts without a runbook are deleted in review.
- Alert fatigue audit monthly: if an alert fired > N times without action, it's wrong.

### 10.3 Runbooks (in `infra/runbooks/`)

Each runbook follows a fixed shape:
1. Symptom and how to recognize.
2. Severity and who to page.
3. Immediate stabilization (kill-switch, scale-down, fail-over).
4. Diagnosis steps with exact commands.
5. Recovery steps.
6. Post-incident actions (recon, audit-log review).
7. "If this runbook didn't help, escalate to X."

Initial runbooks: db-failover, broker-disconnect, kill-switch (arm and disarm), recon-drift, market-data-stall, agent-runaway-cost, secret-rotation-failure, dr-restore.

---

## 11. Security Hardening

### 11.1 Secrets

- Vault (or AWS Secrets Manager + External Secrets Operator) is the only secret store.
- Workloads never read env-var secrets at startup; ESO syncs into a Secret, mounted as files for rotation-friendliness.
- Database credentials are *dynamic* via Vault's database engine — short-lived, auto-rotated.
- Broker API keys: per-environment, never shared across paper/live, rotation playbook tested quarterly.
- The repo is scanned by gitleaks pre-commit and in CI; a secret in a PR blocks merge and triggers rotation of the leaked credential.

### 11.2 Network

- Default-deny `NetworkPolicy` per namespace; explicit allow for needed flows.
- Service-to-service mTLS via Istio or Linkerd (lean Linkerd — simpler, lighter). Trading-namespace traffic *must* be mTLS; CI fails if a chart in `trading/` lacks the annotation.
- Egress is allowlisted: workloads can only reach broker APIs, market-data vendors, and observability endpoints. No wildcard egress.
- WAF (Cloudflare or AWS WAF) in front of public ingress; rate limiting per IP and per authenticated user.

### 11.3 Identity & access

- Workload identity (IRSA / Workload Identity) for cloud perms.
- Human access via SSO (Okta / Google Workspace) to ArgoCD, Grafana, the platform itself; short-lived tokens.
- `kubectl` access tiered: read-only for everyone, write for platform engineers, prod-trading-namespace requires break-glass with audit.
- Audit log (Kubernetes audit policy + app-level audit topic) retained 7 years for trading actions, 90 days for everything else, in immutable S3 (object-lock).

### 11.4 Supply chain

- All images built reproducibly with Buildkit; SBOM generated (Syft) and stored as an OCI artifact.
- Vulnerability scan (Trivy) in CI; high/critical fails the build, medium opens a ticket.
- Image signing with Cosign; admission controller (Kyverno or Sigstore policy-controller) rejects unsigned images in prod.
- Base images pinned to digests; renewed weekly via Renovate.

### 11.5 Encryption

- KMS-managed keys; envelope encryption for S3, RDS, EBS.
- TLS 1.3 minimum on all ingress; cert-manager + Let's Encrypt for public, internal CA via Vault PKI for service mesh.
- At-rest: every persistent volume is encrypted. CNPG-managed Postgres uses storage-class encryption; backups are encrypted with a separate key.

---

## 12. Backup, DR, and Recovery

### 12.1 What gets backed up

| Asset | Mechanism | Frequency | RPO | RTO |
|---|---|---|---|---|
| Postgres (all) | CNPG continuous WAL archiving + daily base | continuous | < 1min | < 30min |
| TimescaleDB | Same as Postgres | continuous | < 1min | < 30min |
| S3 data lake | Cross-region replication + versioning | continuous | < 15min | minutes |
| Redpanda topics | Tiered storage to S3 + topic-level replication | continuous | < 5min | < 1h |
| Vault | Raft snapshot to S3, every 6h | 6h | 6h | 1h |
| Cluster manifests | Git is the source of truth + Velero for stateful CRDs | per commit | 0 | 1h (rebuild via ArgoCD) |
| MLflow artifacts | S3 with versioning | continuous | 0 | minutes |

### 12.2 The DR drill

A quarterly exercise, scripted, timed, documented:

1. Spin up a clean kind cluster (or a fresh staging EKS).
2. Bootstrap with Terraform + ArgoCD root app.
3. Restore Vault from raft snapshot.
4. Restore Postgres from latest base + WAL.
5. Re-attach S3 data lake (or replicate from DR region).
6. Re-create Redpanda topics from tiered storage.
7. Run a canonical backtest from Phase 3 against restored data; assert bit-for-bit equality with the pre-DR result hash.
8. Document actual RTO + RPO; update if drift from target.

The drill *must produce a green signal*; if any step is manual-tribal-knowledge, that's a finding and gets scripted before the next drill.

### 12.3 What we explicitly do not promise

- Active/active failover across regions.
- Sub-minute RTO for the entire platform — only the trading namespace gets that.
- Restoring an arbitrary historical point-in-time older than the WAL retention (35 days).

These are decisions, not gaps. A future phase could buy them, at significant cost.

---

## 13. Cost Controls

- Kubecost or OpenCost installed; per-namespace cost dashboards in Grafana.
- HPAs and KEDA on workers (queue depth → replica count); scale-to-zero on dev environments after 18:00 local.
- Spot for batch / research; on-demand for trading and data.
- S3 lifecycle: raw ticks → Glacier after 180d; backups → Glacier after 30d.
- LLM cost tracking: every agent call is tagged with run_id, agent, prompt_version; daily cost report alerts on per-agent budget breach.
- Quarterly cost review with a written "what changed and why" doc; surprise invoices are an incident.

---

## 14. Production Readiness Checklist (the actual sign-off)

Per service:

- [ ] Helm chart passes `helm lint` and schema validation.
- [ ] Resource requests/limits set; verified via load test.
- [ ] Liveness and readiness probes distinct; both tested under load.
- [ ] PDB present; `maxUnavailable` ≤ 1 (or proportionally appropriate).
- [ ] HPA configured where load varies; tested via synthetic load.
- [ ] ServiceMonitor scraped; default Grafana dashboard exists.
- [ ] At least one SLO with burn-rate alert and runbook.
- [ ] NetworkPolicy default-deny + explicit allows.
- [ ] mTLS enforced for service-to-service.
- [ ] Secrets via ExternalSecret; no env-var secrets.
- [ ] IRSA / workload identity configured; least privilege confirmed.
- [ ] Image signed (Cosign), scanned (Trivy), pinned by digest.
- [ ] Logs structured JSON; trace ID propagated.
- [ ] Chaos experiment(s) scoped and passing.
- [ ] Graceful shutdown handles in-flight work; tested by pod kill.

Cluster-wide:

- [ ] Argo CD root app reconciles a clean cluster end-to-end.
- [ ] Terraform `plan` is empty against prod (no drift).
- [ ] Backup restoration tested quarterly; last drill ≤ 90 days old.
- [ ] All alerts have runbook URLs; runbook coverage = 100%.
- [ ] Audit log retention configured per data class.
- [ ] DR drill documented and passing.
- [ ] On-call rotation defined; pager tested.
- [ ] Security scan (kube-bench, kube-hunter, Trivy) clean of high/critical.
- [ ] Cost dashboards live; budget alerts armed.
- [ ] Game day completed in last 90 days; runbooks updated from findings.

This list is the deliverable. A signature on it (literal or in PR description) is the phase exit.

---

## 15. Risks, Failure Modes & Mitigations

| Risk | Mitigation |
|---|---|
| GitOps reconciles a bad config during market hours | Sync windows on trading project; human approval required intra-day |
| Chaos experiment cascades beyond blast radius | All experiments labeled and namespace-scoped; blast-radius review on every new experiment |
| Vault unavailability stalls everything | HA Raft mode (3+ nodes); pods cache leased secrets; degraded-mode runbook |
| Backup restores succeed but data is logically corrupt | Restore drill includes a hash-verified backtest replay, not just "tables exist" |
| Secrets leak via logs | structured logger with allowlist of fields; CI grep for forbidden patterns |
| Container drift via pod exec changes | Read-only root filesystem; `kubectl exec` audited and rate-flagged |
| Argo CD itself drifts / is mis-reconciled | `argocd-image-updater` and Argo are themselves managed by another Argo app (recursive); manual rebuild runbook |
| Multi-AZ cost balloons | Right-size node pools; spot where safe; quarterly review |
| Engineers bypass GitOps "just this once" | `kubectl apply` blocked in prod by admission controller; break-glass requires written justification |
| DR drill becomes annual ritual that hides drift | Quarterly cadence; surprise drill once a year (engineer-on-call doesn't know the date) |
| LLM/embedding costs spike unobserved | Per-agent budget alerts; daily cost diff posted to ops channel |
| Image scanner flags every base-image weekly | Renovate updates base images on a schedule; CVE budget per service |

---

## 16. Testing Strategy for Phase 10 Itself

The infrastructure code is code, and it gets tests:

- **Terraform:** `terraform validate`, `tflint`, `tfsec` in CI; `terraform plan` against a sandbox env on every PR; `terratest` for module-level integration where modules are non-trivial.
- **Helm:** `helm lint`, `helm template | kubeconform` for K8s schema validation, `helm template | conftest` (OPA) for policy tests (no `latest`, requests set, etc.).
- **Argo CD:** dry-run sync against a kind cluster in CI; manifest diff against the deployed state on PR.
- **Chaos:** experiments are themselves CRDs in git; PRs review them like code.
- **Runbooks:** each runbook has at least one game-day execution per year; "did it work" recorded in the runbook header.
- **Backup/DR:** the restore script is the test.

CI pipeline gate order: lint → unit → terraform-plan → helm-template → policy-checks → integration (kind) → security-scan. Anything that fails blocks merge.

---

## 17. Observability Surface (cross-phase, finalized here)

Phase 10 is when observability stops being "we have Jaeger" and becomes "we have a coherent picture."

- **Metrics:** Prometheus + Mimir for long-term; one shared dashboard taxonomy (Service / SLO / Capacity).
- **Logs:** Loki, structured JSON only, trace_id field mandatory.
- **Traces:** Tempo, OTel SDK in every app, sampling 100% in dev / 5% baseline + 100% on error in prod.
- **Profiles:** Pyroscope, on-demand for cost-sensitive workloads (agents, backtests).
- **Frontend:** Sentry + browser OTel SDK (Phase 9) feeds into the same trace store.
- **One-click correlation:** click an alert → land on a Grafana dashboard with the relevant time range, log query, and trace lookup pre-filled.

Service catalog (Backstage or a homegrown markdown index) documents every service: owner, SLOs, dashboards, runbooks, dependencies.

---

## 18. Compliance Posture (preparing for SOC 2, not achieving it)

The following controls are built so an auditor's checklist is mostly "yes":

- **CC6 (Logical access):** SSO with MFA; quarterly access reviews; offboarding playbook; least-privilege via IRSA and ArgoCD Projects.
- **CC7 (System monitoring):** alert + runbook coverage; immutable audit logs.
- **CC8 (Change management):** every prod change is a PR + ArgoCD reconciliation; manual changes are incidents; backups tested quarterly.
- **CC9 (Risk mitigation):** DR drill; vendor inventory (broker, market data, cloud).
- **A1 (Availability):** SLOs published; incident postmortems with RCA template.

What's deferred: penetration test (annual once we go live), formal third-party auditor engagement, data-residency contracts.

---

## 19. Definition of Done

- [ ] Local: `make dev` brings up the full stack on kind in < 20 min, with one health-check trace passing.
- [ ] Cloud: `terraform apply` + Argo bootstrap creates a fresh prod-shaped environment in < 90 min.
- [ ] All services pass the per-service production readiness checklist (Section 14).
- [ ] All cluster-wide checklist items signed off (Section 14).
- [ ] One canary deployment proven (Web or API) with automatic rollback on injected error.
- [ ] One blue/green proven (OMS) with manual cutover and rollback documented.
- [ ] At least four chaos experiments scheduled and passing (pod kill, node drain, DB failover, broker disconnect).
- [ ] Backup restoration drill passes with bit-for-bit backtest replay.
- [ ] Production readiness review held with stakeholder; checklist signed.

---

## 20. Interview / Stakeholder Talking Points

- **Why GitOps is non-negotiable for a trading platform.** Drift is the silent killer. Every prod change in git, every reconciliation auditable, no laptops with cluster-admin.
- **Canary vs blue/green by service tier.** Statefulness and order semantics drive the choice; canary on the OMS would split the order book.
- **Burn-rate alerts vs threshold alerts.** SRE-textbook reasoning, with one war-story-worth of "we deleted 40 alerts in our first audit."
- **Chaos as assertion, not theater.** Each experiment has a hypothesis and a pass criterion; we run them on a schedule, not when someone gets bored.
- **The trading namespace gets a different deal.** Dedicated nodes, no spot, market-hours sync windows, blue/green only, mTLS enforced at admission. The blast radius is the business; we treat it that way.
- **DR drill as a verb, not a noun.** Quarterly, timed, scripted, ends in a hash-equal backtest. If it didn't run end-to-end, it didn't happen.
- **Compliance posture without a compliance team.** Built the controls so an attestation is paperwork; explicit about what's deferred.

---

## 21. Open Questions

1. Single-cluster prod vs cluster-per-domain (data / trading / research)? Lean single-cluster with strong namespace boundaries for now; revisit if blast-radius incidents force separation.
2. Service mesh: Linkerd vs Istio? Linkerd unless we hit a feature wall (advanced traffic policy, multi-cluster), then re-evaluate.
3. Managed Prometheus (AMP / GMP) vs self-hosted Mimir? Self-hosted Mimir for retention control; switch to managed if ops cost rises.
4. Active/passive DR vs pilot-light? Pilot-light (S3 replication + scaled-to-zero EKS) is the current target; warm standby is a budget upgrade.
5. Image registry: ECR vs Harbor? ECR for IAM integration; Harbor only if we need pull-through caching for air-gapped envs.
6. Continuous-deployment cadence on trading services — daily, weekly, or only on-demand? Lean weekly with batched changes; daily once two clean quarters have passed.
7. Penetration test timing — pre- or post-go-live? Pre, on a staging environment that mirrors prod; one round before any real money is at risk.

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

Phase 10 changes shape, not depth. The **artifacts** (Helm charts, Terraform modules, ArgoCD manifests, runbooks, chaos YAMLs, SLO definitions) are the resume value. **Continuously running them on EKS is not** — a prod-shape cluster is $1,500–3,500/mo, which would consume any realistic two-year trading PnL.

**Posture: artifact-first, not always-on**

- All Phase 10 code lives in the repo as designed. A reviewer can read it, understand it, and ask questions about it. That's the bar.
- The "production" runtime for these two years is a single VPS or a beefy local machine running `docker-compose`. No K8s, no Argo, no Vault Enterprise day-to-day.
- The K8s/Argo/Terraform stack runs **on demand** for two purposes:
  1. **Local kind cluster:** `make dev-k8s` brings up the full Helm-charted stack locally for development screenshots, demo recordings, and "yes, it actually works" verification.
  2. **Time-boxed cloud demo:** once during the project, allocate ~$300 of free-tier AWS credit (or budget $300–500 of real spend) for a 2-week prod-shape deployment. Capture screenshots of Grafana dashboards, run one chaos experiment, execute the DR drill end-to-end, record a screen capture, then `terraform destroy`.

**What stays (resume-load-bearing) and what gets adjusted**

| Topic | Scope-mode posture |
|---|---|
| Helm charts per service | **Stay.** Lint + schema validation in CI. Run `helm template | kubeconform` on every PR. |
| Terraform modules | **Stay.** `terraform plan` runs in CI against a sandbox; never `apply` continuously. |
| ArgoCD manifests | **Stay.** Reconcile against local kind on PR; cloud apply only during the time-boxed demo. |
| Argo Rollouts canary + blue/green | **Stay** as YAML; demonstrated locally on kind. |
| Chaos Mesh experiments | **Stay** as YAML; run on kind. The market-hours rule is moot when there's no live cluster, but the labels and blast-radius scoping stay correct. |
| SLOs + burn-rate alerts | **Stay** as Prometheus rules. Run them against the self-hosted Prometheus on the VPS. |
| Vault | **Replace with `sops` + `age`** for one user. The institutional pattern is in the docs; the runtime is `sops` because Vault HA for one human is silly. ExternalSecrets manifests live in the repo for the demo. |
| mTLS / Linkerd | **Stay as artifact.** Demonstrated on kind during the demo window; not used continuously on the VPS. |
| Backup / DR drill | **Execute once during the demo window.** Document RTO/RPO, capture a screen recording. The script lives in the repo and gets re-run if anything material changes. |
| Cost dashboards (Kubecost / OpenCost) | **Skip continuously; demo-only.** |
| SOC 2 controls posture | **Document in the repo, don't pursue attestation.** The point is the controls exist in code. |
| Secrets scanning, image signing, SBOM, Trivy | **Stay continuously in CI.** These are cheap and run on every PR. |

**Demo plan (the one cloud spend during the project)**

When: late in Year 2, after the platform is mature enough to look impressive.
Cost: budget $300–500 for a ~2-week window.
Goals:
1. `terraform apply` produces a fresh prod-shape EKS environment.
2. ArgoCD root app reconciles all services.
3. Run one canary deployment, one blue/green, one chaos experiment, one DR drill.
4. Capture screenshots and a screen recording for the README and resume.
5. `terraform destroy` and confirm zero residual cost.

**What's explicitly deferred**

- 24/7 production cluster.
- Active/passive multi-region.
- Quarterly DR drills (one drill, in the demo window, is the artifact).
- Penetration testing (no live attack surface beyond the VPS, which is a single user's responsibility).
- SOC 2 attestation.

**Budget impact:** $0/mo continuous. ~$300–500 one-time for the demo window. The VPS that runs the actual workloads is $25–80/mo and accounted under earlier phases, not Phase 10.
