# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| main    | ✅        |

## Reporting a Vulnerability

If you discover a security vulnerability in Astraeus, please report it
responsibly:

1. **Do not** open a public GitHub issue.
2. Email: sahilsatyam@proton.me (or open a private security advisory on GitHub).
3. Include: description, reproduction steps, impact assessment.
4. Expected response time: 72 hours.

## Security Practices

### Secrets Management
- No secrets in source control — enforced by gitleaks in pre-commit and CI.
- Production secrets stored in AWS Secrets Manager, referenced via ExternalSecrets.
- Local development uses `.env` files (gitignored).

### Dependency Scanning
- Trivy scans container images and IaC on every PR.
- Dependabot/Renovate monitors for known CVEs in dependencies.
- `uv.lock` and `package-lock.json` pin exact versions.

### Authentication & Authorization
- Backend: JWT tokens with role-based access control (RBAC).
- Frontend: NextAuth with JWT session strategy.
- Trading operations require explicit `trading` permission.
- Kill switch operations require `kill_switch` permission.

### Network Security
- Kubernetes NetworkPolicies enforce default-deny per namespace.
- Service mesh (Linkerd) provides mTLS for service-to-service communication.
- Ingress terminates TLS; internal traffic is encrypted.

### Data Protection
- Database encryption at rest via AWS KMS.
- All broker API keys encrypted in transit and at rest.
- Audit log retention for all trading operations (immutable append-only journal).

### CI/CD Security
- Import audit enforces LLM ↔ Broker isolation boundary.
- No `latest` tags allowed in Helm charts (enforced in CI).
- Container images signed with Cosign and scanned before deployment.
