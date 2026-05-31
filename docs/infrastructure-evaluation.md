# Astraeus — Infrastructure & Hosting Evaluation

> **Context:** Personal project. Optimize for low cost, minimal ops, minimal maintenance, maximum developer productivity. Support AI/ML workloads. Scale comfortably from 1 to ~500 users. Provide a migration path if growth exceeds expectations.

---

## 1. Project Analysis

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Language (Backend) | Python 3.12 |
| Language (Frontend) | TypeScript 5 |
| API Framework | FastAPI + Uvicorn |
| Frontend Framework | Next.js 16 (React 19) |
| Database | PostgreSQL 16 + TimescaleDB + pgvector |
| Cache / Queue | Redis 7.2 (+ Redis Streams for event pub/sub) |
| Object Storage | MinIO (S3-compatible) |
| ML/NLP | PyTorch, Transformers, spaCy, sentence-transformers |
| LLM | Anthropic Claude, OpenAI |
| Portfolio Optimization | cvxpy, scipy, numpy |
| Regime Detection | hmmlearn, scikit-learn |
| Auth | JWT (python-jose) + NextAuth 4 |
| Observability | OpenTelemetry, Prometheus, Grafana, Jaeger |
| CI/CD | GitHub Actions |
| Package Mgmt | uv (Python), npm (JS) |

### Architecture Shape

- **5 application services:** API, OMS, Workers, Recon Worker, Web
- **22 internal libraries** (uv workspace monorepo)
- **Stateful dependencies:** Postgres/TimescaleDB, Redis, MinIO
- **ML workloads:** NLP pipeline (~2GB RAM), sentiment analysis, embeddings, topic modeling
- **Real-time:** WebSocket market data streaming, 5-second recon loop
- **Batch:** Alt-data ingestion (Reddit, RSS, EDGAR), nightly jobs, topic refit

### Frontend

- Next.js 16, React 19, App Router
- Tailwind CSS 4, Zustand, TanStack Query/Table/Virtual
- ECharts 6, Lightweight Charts (TradingView)
- NextAuth 4 (credentials provider, JWT)
- Feature flags via environment variables
- Route groups: quant, research, portfolio, trading, recommendations, operator

### Backend Services

| Service | Role |
|---------|------|
| `apps/api` | Main FastAPI service — health, version, CRUD, AI copilot, recommendations |
| `apps/oms` | Order Management System — event sourcing, pre-trade risk, circuit breakers |
| `apps/workers` | Background workers — outbox relay, streaming, nightly, alt-data, NLP |
| `apps/recon_worker` | 5-second reconciliation loop (local state vs broker) |
| `apps/web` | Next.js frontend |

### Database Requirements

- PostgreSQL 16 + TimescaleDB (hypertables for OHLCV time-series)
- pgvector (RAG hybrid retrieval)
- Async SQLAlchemy 2.0 + asyncpg
- Alembic migrations
- Configurable connection pool (size, overflow, timeout)

### AI/LLM Requirements

| Component | Library | Model | Memory (loaded) |
|-----------|---------|-------|-----------------|
| LLM (chat/agent) | anthropic, openai | Claude, GPT-4 | API-only (no local) |
| Sentiment | transformers | ProsusAI/finbert | ~700MB |
| Embeddings | sentence-transformers | BAAI/bge-small-en-v1.5 | ~300MB |
| NER | spaCy | en_core_web_sm | ~12MB |
| Topics | BERTopic + HDBSCAN + UMAP | — | ~1GB (batch only) |
| Regime | hmmlearn, scikit-learn | HMM, GMM | <100MB |
| Portfolio | cvxpy, scipy | Convex optimization | <200MB |
| Token counting | tiktoken | — | <50MB |

**Realistic NLP memory (all models loaded):** ~1.8–2.2GB. With lazy loading: ~1.2–1.5GB peak.
BERTopic refit is a batch job that can run off-peak — not always-resident.

> **Note:** The "4GB+" estimate is a worst-case for simultaneous batch processing. Benchmark actual RSS before provisioning. A 16GB VPS may be sufficient; 32GB gives headroom to not think about it.

### Background Jobs & Scheduled Tasks

- Outbox relay worker (event publishing via Redis Streams)
- Market data streaming worker (real-time WebSockets)
- Nightly batch jobs
- Alt-data ingestion: Reddit (PRAW), RSS (feedparser), SEC EDGAR — scheduled
- NLP pipeline worker (always-on, document processing)
- Topic refit worker (BERTopic batch, cron-triggered)
- Recon worker (5-second loop, broker reconciliation)
- Market data backfill (on-demand scripts)
- Celery tasks (portfolio construction, Redis as broker)

### External Integrations

| Category | Services |
|----------|----------|
| Market Data | Alpaca, Polygon.io, Alpha Vantage, FRED, Yahoo Finance |
| Brokers | Alpaca, Interactive Brokers (optional), Binance (optional) |
| Alt-Data | Reddit, RSS feeds, SEC EDGAR |
| AI/LLM | Anthropic API, OpenAI API |

### Authentication

- Backend: JWT (HS256, python-jose), configurable issuer/audience
- Access tokens (1hr) + service tokens (24hr)
- Frontend: NextAuth 4, credentials provider, shared JWT secret
- Single-user "operator" scope mode
- Auth can be disabled for local dev

### Data Storage

| Store | Purpose |
|-------|---------|
| PostgreSQL + TimescaleDB | Primary data, time-series hypertables, vector embeddings |
| Redis | Caching, trading state, idempotency keys, event streaming (Streams), task queue |
| MinIO | Raw alt-data documents, model artifacts, backfill data |

### Observability

- Structured logging: structlog (JSON)
- Distributed tracing: OpenTelemetry → OTLP → Jaeger
- Metrics: Prometheus + FastAPI instrumentator
- Dashboards: Grafana 11
- Frontend: Optional Sentry + OTEL endpoint
- Security: Trivy (config scan), gitleaks (secret detection)

---

## 2. Architectural Simplifications

### 2.1 Remove Redpanda/Kafka — Replace with Redis Streams

**Current state:** Redpanda is used for outbox relay, market data event streaming, and alt-data pipeline coordination.

**Assessment:** At personal-project scale (50–200 events/sec for a few hundred symbols), none of these workloads justify a dedicated streaming platform.

| Question | Answer |
|----------|--------|
| Processing tens of thousands of events/sec? | No. ~50–200/sec max. |
| Need event replay? | Not critically. Backfill scripts cover historical data. |
| Need multiple consumer groups? | 1–2 at most. Redis Streams supports this. |
| Need durable event sourcing? | OMS uses Postgres-backed event sourcing already. |

**Recommendation:** Replace Redpanda with Redis Streams.

**Benefits:**
- Eliminates ~1–2GB RAM overhead
- Removes one failure mode and one service to monitor
- Redis Streams provides: pub/sub, consumer groups, persistence, backpressure
- Redis is already in the stack — zero new dependencies
- Karapace schema registry becomes unnecessary (same monorepo controls both sides)

**Migration approach:** Keep the existing Kafka producer/consumer abstractions in code, swap the transport layer to Redis Streams behind the same interface. This is a backend change, not an architecture rewrite.

### 2.2 Kubernetes Artifacts — Keep Code, Don't Deploy

**Current state:** The repo contains Helm charts, Tiltfile, Terraform modules (EKS, RDS, S3, KMS, network, IAM-IRSA, observability), ArgoCD GitOps structure, and three environment configs (dev, staging, prod).

**Assessment:** This is future-scalability preparation, not active infrastructure. For a solo engineer on a personal project:

```
Docker Compose + GitHub Actions + SSH deploy
```

is superior to:

```
Terraform + Kubernetes + Helm + ArgoCD
```

until you're supporting multiple environments or multiple engineers.

**Recommendation:**
- Keep all K8s/Terraform code in the repo (it's valuable reference material)
- Do not deploy or maintain it until revenue or team size justifies it
- Use Docker Compose for production deployment
- The Helm charts become relevant at Phase 3–4 of the migration path

### 2.3 TimescaleDB — Keep It

**Assessment:** This is the one piece of infrastructure complexity that earns its keep.

Trading systems genuinely benefit from:
- Time-series compression (10–20× for historical OHLCV)
- Continuous aggregates (pre-computed rollups: 1min → 5min → 1hr → 1day)
- Hypertables (automatic partitioning by time)
- Time-bucket queries (genuinely faster than vanilla Postgres)

TimescaleDB is a Postgres extension, not a separate service. It adds zero operational overhead — same backup strategy, same connection pool, same Alembic migrations.

**Recommendation:** Keep. Do not remove unless it becomes operationally painful (it won't).

### 2.4 NLP Memory — Benchmark Before Provisioning

**Previous estimate:** "4GB+ RAM required"

**Revised estimate after analysis:**

| Model | Loaded Size |
|-------|-------------|
| FinBERT | ~700MB |
| BGE-small | ~300MB |
| spaCy en_core_web_sm | ~12MB |
| PyTorch runtime (CPU) | ~500MB |
| Python process + libs | ~300MB |
| **Total (all loaded)** | **~1.8–2.2GB** |
| **With lazy loading** | **~1.2–1.5GB peak** |

BERTopic refit (the actual 4GB+ workload) is a batch job — run it off-peak, not always-resident.

**Recommendation:** Start with 16GB VPS (Hetzner CX31, €16.90/mo). Monitor actual RSS usage. Upgrade to 32GB only if measured usage justifies it. Hetzner allows resizing in minutes.

---

## 3. Hosting Requirements (Revised)

After removing Redpanda and right-sizing NLP estimates:

| Requirement | Minimum | Comfortable |
|-------------|---------|-------------|
| Compute (API + OMS) | 2 vCPU, 2GB RAM | 4 vCPU, 4GB RAM |
| Compute (Workers/NLP) | 2 vCPU, 2GB RAM | 4 vCPU, 4GB RAM |
| Compute (Web) | 0.5 vCPU, 512MB | 1 vCPU, 1GB |
| Database | 2 vCPU, 4GB RAM, 50GB SSD | 4 vCPU, 8GB, 100GB |
| Redis (cache + streams + queue) | 512MB | 1GB |
| Object Storage | 10GB | 100GB |
| Network | Low latency to market data APIs | Same |
| **Total (single box)** | **4 vCPU, 12GB RAM** | **8 vCPU, 16–32GB RAM** |

### Hard Constraints

- TimescaleDB extension required (rules out most managed Postgres)
- WebSocket support required
- Long-running background processes (not request/response only)
- Redis Streams for event pub/sub (already in stack)

---

## 4. Workload Analysis

### User Load Estimates

| Metric | 1 user | 10 users | 50 users | 100 users | 500 users |
|--------|--------|----------|----------|-----------|-----------|
| API requests/min | 5–20 | 50–200 | 250–1000 | 500–2000 | 2500–10000 |
| WebSocket connections | 1–3 | 10–30 | 50–150 | 100–300 | 500–1500 |
| DB queries/min | 20–100 | 200–1000 | 1000–5000 | 2000–10000 | 10000–50000 |
| NLP inference/hr | 10–50 | 50–200 | 100–500 | 200–1000 | 500–2000 |
| LLM API calls/hr | 5–20 | 20–100 | 50–300 | 100–500 | 200–1000 |
| Market data events/sec | 10–50 | 10–50 | 50–200 | 100–500 | 200–1000 |

**Key insight:** Market data ingestion, NLP processing, and recon loops run regardless of user count. Baseline compute cost exists even for 1 user. However, without Redpanda, the baseline drops significantly.

---

## 5. Platform Comparison

### Feasibility Filter (Revised — No Kafka Requirement)

| Platform | Viable? | Reason |
|----------|---------|--------|
| Vercel | ⚠️ Frontend only | Good for Next.js frontend, not backend. |
| Railway | ⚠️ Partial | Can run containers, but TimescaleDB limited, expensive at scale. |
| Render | ⚠️ Partial | Background workers OK, but limited ML memory. |
| Fly.io | ⚠️ Partial | Good for containers, stateful services still painful. |
| DigitalOcean | ✅ | Full control via Droplets. Managed Postgres lacks TimescaleDB. |
| Hetzner Cloud | ✅ | Best price/performance. Full control. |
| AWS | ✅ | Full support but most expensive and complex. |
| GCP | ✅ | Good ML support but overkill for personal project. |
| Azure | ✅ | AKS, managed Postgres. Less relevant here. |

### Detailed Scoring (Viable Platforms)

| Criteria | Hetzner | DigitalOcean | AWS | GCP | Fly.io | Railway |
|----------|:-------:|:------------:|:---:|:---:|:------:|:-------:|
| Ease of Setup | 5 | 7 | 3 | 4 | 7 | 8 |
| Developer Experience | 5 | 7 | 5 | 6 | 8 | 9 |
| Learning Curve | 6 | 7 | 3 | 4 | 7 | 9 |
| Cost (1 user) | **10** | 7 | 3 | 4 | 6 | 5 |
| Cost (500 users) | **9** | 7 | 5 | 5 | 5 | 4 |
| Performance | 8 | 7 | 9 | 9 | 7 | 6 |
| Reliability | 7 | 8 | **10** | 9 | 7 | 6 |
| AI/ML Workloads | 6 | 5 | 9 | **10** | 4 | 3 |
| Background Jobs | 9 | 8 | 9 | 9 | 7 | 7 |
| Database Support | 7 | 7 | 9 | 9 | 5 | 6 |
| Monitoring | 4 | 6 | 9 | 9 | 5 | 5 |
| Maintenance Effort | 4 | 5 | 6 | 6 | 7 | 8 |
| Migration Flexibility | 8 | 8 | 7 | 7 | 7 | 5 |
| **Total (/130)** | **88** | **89** | **87** | **91** | **82** | **81** |

---

## 6. Cost Analysis (Revised — No Redpanda)

### Hetzner Cloud (Cheapest Viable)

| Tier | Server | Storage | Backups | **Total** |
|------|--------|---------|---------|-----------|
| Hobby (1 dev) | €16.90 (CX31, 16GB) | €2 | €2 | **~€21 ($23)** |
| Small Beta (50) | €32.49 (CX51, 32GB) | €5 | €3 | **~€40 ($44)** |
| Active (100) | €32.49 (CX51) | €10 | €5 | **~€47 ($52)** |
| Upper (500) | €60 (CCX33, dedicated) | €20 | €8 | **~€88 ($96)** |

*Add $10–50/mo for LLM API costs depending on usage.*

**Note:** All services (API, OMS, Workers, Web, Postgres, Redis, MinIO, monitoring) run on a single VPS. No separate line items for DB/Redis/streaming — they're all containers on the same box.

### DigitalOcean (Balanced)

| Tier | Droplet | Storage | Backups | **Total** |
|------|---------|---------|---------|-----------|
| Hobby | $48 (8GB) | $5 | $5 | **~$58** |
| Small Beta | $96 (16GB) | $10 | $10 | **~$116** |
| Active | $96 (16GB) | $15 | $15 | **~$126** |
| Upper | $192 (32GB) | $25 | $20 | **~$237** |

### AWS (Full EKS — For Reference Only)

| Tier | EKS + Compute | RDS | ElastiCache | S3 | Monitoring | **Total** |
|------|---------------|-----|-------------|-----|------------|-----------|
| Hobby | $73 + $50 | $30 | $15 | $1 | $20 | **~$189** |
| Small Beta | $73 + $100 | $60 | $25 | $5 | $30 | **~$293** |
| Active | $73 + $150 | $100 | $35 | $10 | $50 | **~$418** |
| Upper | $73 + $300 | $150 | $50 | $20 | $75 | **~$668** |

**Hetzner is 8–10× cheaper than AWS** for this workload after removing Redpanda/MSK.

---

## 7. Skills Assessment

| Area | Hetzner (Docker Compose) | AWS EKS | Railway/Fly.io |
|------|:------------------------:|:-------:|:--------------:|
| Deployment | Intermediate | Advanced | Beginner |
| DevOps | Intermediate | Advanced | Beginner |
| Linux | Intermediate | Intermediate | Not needed |
| Docker | Intermediate | Advanced | Beginner |
| Kubernetes | Not needed | **Expert** | Not needed |
| Cloud Networking | Basic | Advanced | Not needed |
| Monitoring | Intermediate | Advanced | Basic |
| Terraform | Not needed | Advanced | Not needed |
| Helm | Not needed | Advanced | Not needed |

---

## 8. Recommended Architectures

### Option A: Simplest Possible — Single VPS + Docker Compose (Recommended)

**Platform:** Hetzner CX31 (4 vCPU, 16GB RAM, €16.90/mo) — upgrade to CX51 if benchmarks show need

```
Single Hetzner VPS
├── Docker Compose
│   ├── API (FastAPI)
│   ├── OMS (FastAPI)
│   ├── Workers (all workers, using Redis Streams + Celery)
│   ├── Web (Next.js)
│   ├── PostgreSQL + TimescaleDB
│   ├── Redis (cache + streams + queue)
│   ├── MinIO
│   ├── Prometheus + Grafana (optional, add when needed)
│   └── Jaeger (optional, add when needed)
├── Caddy (reverse proxy + automatic HTTPS)
├── Automated backups (pg_dump → Hetzner Object Storage)
├── Cloudflare (DNS + DDoS protection)
└── GitHub Actions → SSH deploy
```

**Monthly cost:** ~$23–50 (depending on VPS size + LLM usage)

**Optimized for:**
- ✅ Fastest setup (compose.yml works with Redpanda removed)
- ✅ Lowest maintenance (one server, one SSH target)
- ✅ Lowest cost
- ✅ Fewest failure modes

**What's NOT included (intentionally):**
- ❌ No Kubernetes
- ❌ No Kafka/Redpanda
- ❌ No Terraform
- ❌ No ArgoCD
- ❌ No multi-environment infra

**Deploy workflow:**
```bash
# GitHub Actions on push to main:
ssh deploy@vps "cd /opt/astraeus && docker compose pull && docker compose up -d"
```

**Backup workflow:**
```bash
# Cron daily at 03:00:
pg_dump -Fc astraeus | rclone rcat hetzner-s3:astraeus-backups/$(date +%Y%m%d).dump
```

---

### Option B: Best Balance — Hetzner VPS + Vercel Frontend

**Platform:** Hetzner CX31/CX51 (backend) + Vercel (frontend)

```
Hetzner VPS
├── Docker Compose
│   ├── API + OMS
│   ├── Workers
│   ├── PostgreSQL + TimescaleDB
│   ├── Redis
│   ├── MinIO
│   └── Monitoring (optional)
├── Caddy (reverse proxy + auto-TLS)
├── Daily pg_dump → Hetzner Object Storage
└── GitHub Actions: build → push GHCR → SSH pull & restart

Vercel (free tier)
└── Next.js frontend (free CDN, preview deploys, zero maintenance)

Cloudflare (free)
└── DNS + DDoS protection
```

**Monthly cost:** ~$23–50 (backend) + $0–20 (Vercel free/Pro)

**Why choose this over Option A:**
- Frontend iteration is faster (instant Vercel deploys, preview URLs per PR)
- Frontend scales independently (CDN-backed, no VPS load)
- Saves ~512MB RAM on VPS (Next.js not running there)

**Trade-off:** Split deployment means two places to check when things break.

---

### Option C: Future-Proof — Hetzner Dedicated + k3s

**Platform:** Hetzner Dedicated AX41-NVMe (6-core Ryzen, 64GB RAM, 2×512GB NVMe, ~€44/mo)

```
Hetzner Dedicated AX41-NVMe
├── k3s (single-node lightweight Kubernetes)
│   ├── Existing Helm charts (minimal modification)
│   ├── API + OMS deployments
│   ├── Workers deployment (resource limits)
│   ├── Web deployment
│   ├── PostgreSQL + TimescaleDB (StatefulSet)
│   ├── Redis (StatefulSet)
│   ├── MinIO (StatefulSet)
│   └── Monitoring (Prometheus, Grafana, Jaeger)
├── Traefik Ingress (built into k3s)
├── cert-manager (auto-TLS)
├── Velero (backup to Hetzner Object Storage)
└── GitHub Actions → helm upgrade
```

**Monthly cost:** ~€44 ($48) fixed regardless of load up to 500 users

**Why choose this over Option A:**
- 64GB RAM means never thinking about memory
- Helm charts provide declarative, reproducible deployments
- Adding nodes later is straightforward
- Direct migration path to managed K8s if needed

**Trade-off:** Kubernetes knowledge required. More moving parts. Dedicated servers have hardware failure risk (no live migration).

---

## 9. Final Recommendation

### Choose: Option A (Single VPS + Docker Compose)

**Platform:** Hetzner CX31 (16GB) to start. Upgrade to CX51 (32GB) if benchmarks show need.

### Why

1. **Simplest possible deployment.** One server. One compose file. One SSH target. Your existing `docker-compose.yml` works with Redpanda removed and Redis Streams substituted.

2. **Lowest cost.** ~$23/mo for the VPS. Total with backups and LLM APIs: $35–70/mo. Compare to $189+/mo for AWS.

3. **Fewest failure modes.** Removing Redpanda eliminates one service, ~1.5GB RAM, and one class of operational issues. Redis handles everything Redpanda was doing at this scale.

4. **No unnecessary infrastructure.** No Kubernetes. No Terraform. No ArgoCD. No Helm. These are excellent tools — for teams and scale you don't have yet.

5. **Benchmark-driven sizing.** Start with 16GB. Measure actual memory usage. Upgrade only when data says so. Don't provision 32GB because a worst-case estimate said "4GB+ for NLP."

### Monthly Cost

| Component | Cost |
|-----------|------|
| Hetzner CX31 (16GB) or CX51 (32GB) | €16.90–32.49 (~$18–35) |
| Hetzner Object Storage (backups) | ~$2 |
| Domain + Cloudflare | Free |
| LLM APIs (usage-dependent) | $10–50 |
| **Total** | **$30–87/mo** |

### Required Skills

- Linux basics (SSH, systemd, UFW firewall)
- Docker Compose (already demonstrated)
- Basic networking (DNS, Caddy reverse proxy)
- pg_dump/restore (backup/recovery)

### Biggest Operational Risks

| Risk | Mitigation |
|------|-----------|
| Single point of failure | Daily pg_dump + weekly snapshots. Recovery: 15–30 min. |
| Disk failure | Hetzner Cloud uses redundant storage (CEPH). |
| DDoS | Cloudflare free tier in front of domain. |
| Security breach | UFW firewall, fail2ban, SSH keys only, Docker network isolation. |
| Data loss | Automated backups to separate object storage. Test restores quarterly. |
| You get hit by a bus | Document deploy in README. It's one server, one compose file. |

### When to Change Architecture

| Trigger | Action |
|---------|--------|
| Sustained >70% CPU or RAM on CX51 | Upgrade to Dedicated AX41 (64GB, €44/mo) |
| Need zero-downtime deploys | Move to Option C (k3s) |
| >500 concurrent users | Move to Option C (multi-node k3s) |
| Multiple engineers on the project | Consider k3s or managed K8s |
| Revenue justifies it ($5k+/mo) | Move to managed K8s (EKS/GKE) |
| Need GPU for ML inference | Add Hetzner GPU server or cloud GPU |
| Regulatory/compliance needs | Move to AWS/GCP with proper isolation |

### Migration Path

```
Phase 1: Single VPS (Docker Compose, 16–32GB)     ← START HERE
   ↓ (sustained >70% resource usage)
Phase 2: Dedicated Server (Docker Compose or k3s, 64GB)
   ↓ (>500 concurrent users or multiple engineers)
Phase 3: Multi-node k3s (Hetzner Cloud nodes)
   ↓ (revenue > $5k/mo, compliance needs)
Phase 4: Managed K8s (EKS/GKE with existing Terraform + Helm)
```

Each phase reuses more of the existing infrastructure code. The Helm charts, Terraform modules, and GitOps setup are an investment that pays off at Phase 3–4.

---

## 10. Key Simplifications Summary

| Component | Current | Recommended | Savings |
|-----------|---------|-------------|---------|
| Event Streaming | Redpanda + Karapace | Redis Streams | ~1.5GB RAM, 1 fewer service |
| Orchestration | EKS + Helm + ArgoCD | Docker Compose + SSH | ~$150+/mo, massive ops reduction |
| IaC | Terraform (7 modules, 3 envs) | Not deployed (kept in repo) | Zero maintenance burden |
| NLP provisioning | 32GB assumed | 16GB, benchmark first | ~€16/mo saved |
| Schema Registry | Karapace | Not needed (monorepo) | 1 fewer service |
| **Net effect** | Complex, expensive | Simple, cheap | **~$170+/mo saved, 3 fewer services** |

---

## 11. What to Keep vs What to Shelve

### Keep (earns its complexity)

- ✅ **TimescaleDB** — genuine domain benefit for time-series data
- ✅ **Redis** — now does triple duty (cache + queue + streams)
- ✅ **MinIO** — simple, S3-compatible, low overhead
- ✅ **Docker Compose** — already works, zero learning curve
- ✅ **GitHub Actions CI** — lint, typecheck, test pipeline stays as-is
- ✅ **Prometheus + Grafana** — add when you want visibility (optional day 1)

### Shelve (keep code, don't deploy)

- 📦 **Helm charts** — valuable at Phase 3+
- 📦 **Terraform modules** — valuable at Phase 4
- 📦 **ArgoCD GitOps** — valuable with multiple engineers
- 📦 **Tiltfile / kind cluster** — useful for local K8s dev if needed
- 📦 **Karapace schema registry** — unnecessary in monorepo

### Remove from production stack

- ❌ **Redpanda** — replaced by Redis Streams
- ❌ **EKS** — not deployed, not needed
- ❌ **Multi-environment Terraform** — one environment is fine

---

## 12. The Bottom Line

This project has **enterprise-grade application architecture** (excellent for code quality) but **does not need enterprise-grade infrastructure**. The application code is well-structured and portable — it doesn't care whether it runs on a €17 Hetzner box or a $500/mo EKS cluster.

**The highest-leverage setup for a solo engineer:**

```
Hetzner VPS (16–32GB)
+ Docker Compose
+ PostgreSQL/TimescaleDB
+ Redis (cache + streams + queue)
+ MinIO
+ Caddy
+ Cloudflare
= ~$30–50/mo
```

No Kubernetes. No Kafka. No ArgoCD. No Terraform deployed.

Save the $150+/mo difference and spend it on LLM API credits or market data subscriptions — those actually make the product better.
