# Terraform Infrastructure

Cloud infrastructure modules for the Astraeus platform on AWS.

## Structure

```
infra/terraform/
├── backend.tf              # Remote state config (S3 + DynamoDB)
├── versions.tf             # Provider version constraints
├── modules/
│   ├── network/            # VPC, subnets, NAT, route tables
│   ├── eks/                # EKS cluster + node groups + OIDC
│   ├── rds/                # Managed PostgreSQL (multi-AZ, encrypted)
│   ├── s3/                 # Data lake + backups (versioned, lifecycle)
│   ├── kms/                # Encryption keys
│   └── iam-irsa/           # Workload identity (IAM Roles for Service Accounts)
└── envs/
    ├── dev/                # Ephemeral, spot instances, minimal
    ├── staging/            # Mirrors prod topology at smaller scale
    └── prod/               # Full production with multi-AZ, dedicated pools
```

## Node Pool Strategy (Production)

| Pool | Instance Type | Capacity | Purpose |
|------|--------------|----------|---------|
| system | t3.medium | ON_DEMAND | ArgoCD, Vault, ingress, observability |
| general | t3.large | ON_DEMAND | APIs, web, light workers |
| data | r6g.large | ON_DEMAND | Postgres, Redis, Redpanda |
| compute | c6i.xlarge | SPOT | Research workers, backtests |
| trading | t3.large | ON_DEMAND | OMS, reconciliation (never spot) |

## Usage

```bash
# Validate all modules
make tf-validate

# Plan against dev
make tf-plan

# Apply (manual, never automated for prod)
cd infra/terraform/envs/prod
terraform init
terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

## Design Decisions

- **IRSA over node-IAM:** Pods get AWS permissions via ServiceAccount-bound roles, not node instance profiles.
- **Single NAT gateway:** Cost optimization for dev/staging; multi-AZ NAT for prod if budget allows.
- **Drift detection:** `terraform plan` runs in CI on schedule; non-empty plan opens an issue.
- **No secrets in Terraform:** Credentials managed via Vault/AWS Secrets Manager, referenced by path.

## Scope Mode

Per the project's scope-mode posture, Terraform modules live in the repo and are validated in CI (`terraform validate`, `tflint`). Continuous `apply` against a live cluster is limited to the time-boxed demo window (~2 weeks, ~$300–500 budget).
