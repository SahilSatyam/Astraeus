# GitOps — ArgoCD Manifests

ArgoCD app-of-apps pattern for declarative, auditable deployments.

## Structure

```
gitops/
├── app-of-apps/
│   ├── root.yaml           # Bootstrap — reconciles all child apps
│   ├── projects.yaml       # ArgoCD Projects (RBAC per domain)
│   ├── research.yaml       # API + Workers applications
│   ├── trading.yaml        # OMS application (manual sync)
│   └── web.yaml            # Next.js dashboard
└── overlays/
    ├── dev/                 # Dev environment value overrides
    │   └── api-values.yaml
    └── prod/               # Production value overrides
        ├── api-values.yaml
        ├── oms-values.yaml
        ├── workers-values.yaml
        └── web-values.yaml
```

## Design Decisions

### App-of-Apps Pattern
One root `Application` watches `gitops/app-of-apps/` and spawns child Applications per domain. This gives us:
- Single bootstrap point for new clusters
- Domain-scoped RBAC via ArgoCD Projects
- Independent sync policies per service tier

### Sync Policies by Tier

| Domain | Auto-sync | Self-heal | Prune | Rationale |
|--------|-----------|-----------|-------|-----------|
| Research | ✅ | ✅ | ✅ | Stateless, low blast radius |
| Web | ✅ | ✅ | ✅ | Stateless, fast rollback |
| Trading | ❌ | ❌ | ❌ | Manual approval required; market-hours sync windows |

### Trading Sync Windows
The trading project denies automated syncs during:
- 09:25–09:35 ET (market open)
- 09:30–16:00 ET (market hours — manual sync only)
- 15:55–16:05 ET (market close)

### Secrets
No secrets in git. ExternalSecrets references Vault/AWS Secrets Manager by path. ArgoCD reconciles the ExternalSecret CR, which materializes a real Secret.

## Usage

```bash
# Bootstrap a fresh cluster
kubectl apply -f gitops/app-of-apps/root.yaml

# Check sync status
argocd app list
argocd app get astraeus-root

# Manual sync for trading (required during market hours)
argocd app sync trading-oms
```

## Adding a New Service

1. Create Helm chart at `apps/<service>/deploy/chart/`
2. Add prod values at `gitops/overlays/prod/<service>-values.yaml`
3. Create Application manifest in `gitops/app-of-apps/<domain>.yaml`
4. Ensure the ArgoCD Project allows the target namespace
