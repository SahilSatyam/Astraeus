# Astraeus — Infrastructure Revamp Implementation Plan

> Based on the [Infrastructure Evaluation](./infrastructure-evaluation.md). This plan details the
> code changes required to simplify the stack for single-VPS deployment with Docker Compose.

---

## Summary of Changes

| Change | Scope | Risk | Effort |
|--------|-------|------|--------|
| Replace Redpanda with Redis Streams | Medium (1 lib, 3 compose files, config) | Low | ~2–3 days |
| Remove Karapace schema registry | Small (compose + config) | None | ~1 hour |
| Create production Docker Compose | New file | None | ~1 day |
| Add Caddy reverse proxy | New service | Low | ~2 hours |
| Create deploy workflow (GitHub Actions → SSH) | New workflow | Low | ~half day |
| Add backup automation | New scripts | Low | ~half day |
| Update .env.example and config | Small | None | ~1 hour |
| Update CI workflow (remove Kafka references) | Small | None | ~30 min |

**Total estimated effort:** ~5–7 days of focused work

---

## Phase 1: Replace Redpanda with Redis Streams (Core Change)

This is the only change that touches application code. Everything else is infrastructure/config.

### 1.1 Create Redis Streams transport layer

**New file:** `libs/marketdata/astraeus_marketdata/stream_relay.py`

Replace the `outbox_relay.py` Kafka producer with a Redis Streams publisher. The outbox table pattern stays — only the "drain to" target changes.

**What to implement:**
```python
# New protocol (replaces KafkaProducer)
class StreamPublisher(Protocol):
    async def publish(self, stream: str, data: dict, key: str | None = None) -> str: ...
    async def close(self) -> None: ...

# Redis Streams implementation
class RedisStreamPublisher:
    def __init__(self, redis: Redis) -> None: ...
    async def publish(self, stream: str, data: dict, key: str | None = None) -> str:
        # Uses XADD with auto-generated ID
        ...
    async def close(self) -> None: ...
```

**Changes to `outbox_relay.py`:**
- Replace `create_kafka_producer()` with `create_stream_publisher(redis_url)` 
- Replace `producer.send(topic=..., value=..., key=...)` with `publisher.publish(stream=..., data=..., key=...)`
- Remove `aiokafka` import and fallback logic
- Keep the same relay loop structure (poll outbox → publish → mark published)

**Files to modify:**
- `libs/marketdata/astraeus_marketdata/outbox_relay.py` — rewrite producer to use Redis
- `apps/workers/astraeus_workers/main.py` — replace `create_kafka_producer` call with Redis publisher

### 1.2 Add Redis Streams consumer (optional, for NLP worker)

**Current state:** The NLP worker's `consumer_mode()` is a stub that polls the DB. It never actually consumed from Kafka.

**Decision:** Keep DB polling for now. It works. Redis Streams consumer can be added later if the polling approach becomes a bottleneck. This is not blocking.

**If you want to add it later:**
```python
# Consumer using XREADGROUP
class RedisStreamConsumer:
    def __init__(self, redis: Redis, stream: str, group: str, consumer: str) -> None: ...
    async def consume(self) -> AsyncIterator[StreamMessage]: ...
    async def ack(self, message_id: str) -> None: ...
```

### 1.3 Update configuration

**File:** `libs/config/astraeus_config/base.py`

```python
# REMOVE:
class KafkaSettings(BaseSettings):
    model_config = _config("ASTRAEUS_KAFKA_")
    bootstrap_servers: str = "localhost:9092"
    client_id: str = "astraeus"
    schema_registry_url: str = "http://localhost:8081"

# KEEP (already exists):
class RedisSettings(BaseSettings):
    model_config = _config("ASTRAEUS_REDIS_")
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""

# UPDATE Settings class:
class Settings(BaseSettings):
    ...
    # REMOVE: kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    # KEEP: redis: RedisSettings = Field(default_factory=RedisSettings)
```

### 1.4 Update dependencies

**File:** `libs/marketdata/pyproject.toml`

```toml
# REMOVE from dependencies:
#     "aiokafka>=0.10",

# ADD (if not already present via astraeus-config):
#     "redis[hiredis]>=5.0",
```

**File:** `pyproject.toml` (root)

```toml
# REMOVE from mypy overrides:
#     "aiokafka.*",
```

### 1.5 Update topic naming (cosmetic)

**File:** `libs/contracts/astraeus_contracts/topics.py`

No functional change needed. The topic name builders (`bar_topic()`, `dlq_topic()`, etc.) return strings that work equally well as Redis Stream keys. Keep the naming convention.

**File:** `libs/contracts/TOPIC_NAMING.md`

Update header to say "Redis Streams" instead of "Redpanda/Kafka topics". The naming policy itself stays the same.

### 1.6 Update portfolio events (cosmetic)

**File:** `libs/portfolio/astraeus_portfolio/events.py`

- Update docstring references from "Redpanda" to "Redis Streams"
- `TopicConfig` and `ConsumerConfig` classes can stay — they're just data models
- No functional code changes (consumers were never implemented against Kafka)

### 1.7 Files affected (complete list)

| File | Change Type |
|------|-------------|
| `libs/marketdata/astraeus_marketdata/outbox_relay.py` | **Rewrite** — Redis XADD instead of aiokafka |
| `libs/marketdata/pyproject.toml` | Remove `aiokafka`, add `redis[hiredis]` |
| `libs/config/astraeus_config/base.py` | Remove `KafkaSettings` class |
| `apps/workers/astraeus_workers/main.py` | Update producer creation to use Redis |
| `libs/contracts/TOPIC_NAMING.md` | Update references (cosmetic) |
| `libs/contracts/astraeus_contracts/topics.py` | Update docstring (cosmetic) |
| `libs/portfolio/astraeus_portfolio/events.py` | Update docstrings (cosmetic) |
| `libs/altdata/astraeus_altdata/outbox.py` | Update docstring (cosmetic) |
| `libs/marketdata/astraeus_marketdata/dlq.py` | Update docstring (cosmetic) |
| `pyproject.toml` | Remove `aiokafka.*` from mypy ignores |
| `.env.example` | Remove `ASTRAEUS_KAFKA_*` vars |

---

## Phase 2: Remove Redpanda & Karapace from Docker Compose

### 2.1 Update `infra/docker/compose.yml`

**Remove these services:**
- `redpanda` (entire service block)
- `karapace-registry` (entire service block)

**Remove these volumes:**
- `redpandadata: {}`

**Remove these directories:**
- `infra/docker/karapace/` (schema_registry.config.json)
- `infra/docker/redpanda/` (bootstrap.sh)

### 2.2 Update `infra/docker/compose.override.yml`

**Remove from `api` service environment:**
```yaml
# DELETE:
ASTRAEUS_KAFKA_BOOTSTRAP_SERVERS: redpanda:9092
```

**Remove from `workers` service:**
```yaml
# DELETE from environment:
ASTRAEUS_KAFKA_BOOTSTRAP_SERVERS: redpanda:9092
ASTRAEUS_KAFKA_SCHEMA_REGISTRY_URL: http://karapace-registry:8081

# DELETE from depends_on:
redpanda:
  condition: service_healthy
```

**Remove port mappings:**
```yaml
# DELETE entire blocks:
redpanda:
  ports:
    - "19092:19092"
    - "8082:8082"

karapace-registry:
  ports:
    - "8081:8081"
```

### 2.3 Update `infra/docker/compose.phase5.yml`

**For all services** (altdata-ingest-reddit, altdata-ingest-rss, altdata-ingest-edgar, nlp-pipeline-worker):
- Remove `ASTRAEUS_KAFKA_BOOTSTRAP_SERVERS: redpanda:9092` from environment
- Remove `redpanda: condition: service_healthy` from depends_on

### 2.4 Update `.env.example`

**Remove:**
```bash
# ---- Kafka / Redpanda ----
ASTRAEUS_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
ASTRAEUS_KAFKA_CLIENT_ID=astraeus
ASTRAEUS_KAFKA_SCHEMA_REGISTRY_URL=http://localhost:8081
```

### 2.5 Update `scripts/verify-stack.sh`

Remove any health checks that reference Redpanda or Karapace endpoints.

---

## Phase 3: Create Production Docker Compose

### 3.1 New file: `infra/docker/compose.prod.yml`

A minimal, production-ready compose file for single-VPS deployment.

```yaml
name: astraeus

services:
  api:
    image: ghcr.io/${GITHUB_OWNER:-astraeus}/astraeus-api:${TAG:-latest}
    environment:
      ASTRAEUS_ENV: production
      ASTRAEUS_DB_HOST: postgres
      ASTRAEUS_REDIS_HOST: redis
      ASTRAEUS_MINIO_ENDPOINT: minio:9000
      ASTRAEUS_OBS_LOG_FORMAT: json
    env_file: .env.prod
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G

  oms:
    image: ghcr.io/${GITHUB_OWNER:-astraeus}/astraeus-api:${TAG:-latest}
    command: ["uvicorn", "astraeus_oms.main:app", "--host", "0.0.0.0", "--port", "8001"]
    environment:
      ASTRAEUS_ENV: production
      ASTRAEUS_DB_HOST: postgres
      ASTRAEUS_REDIS_HOST: redis
    env_file: .env.prod
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M

  workers:
    image: ghcr.io/${GITHUB_OWNER:-astraeus}/astraeus-workers:${TAG:-latest}
    environment:
      ASTRAEUS_ENV: production
      ASTRAEUS_DB_HOST: postgres
      ASTRAEUS_REDIS_HOST: redis
      ASTRAEUS_MINIO_ENDPOINT: minio:9000
    env_file: .env.prod
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G  # NLP models

  web:
    image: ghcr.io/${GITHUB_OWNER:-astraeus}/astraeus-web:${TAG:-latest}
    environment:
      API_URL: http://api:8000
      NEXTAUTH_URL: https://${DOMAIN}
    env_file: .env.prod
    depends_on:
      - api
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M

  postgres:
    image: timescale/timescaledb:2.15.0-pg16
    environment:
      POSTGRES_DB: astraeus
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/00-init.sql:ro
      - ./postgres/timescale.sh:/docker-entrypoint-initdb.d/01-timescale.sh:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d astraeus"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G

  redis:
    image: redis:7.2-alpine
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  minio:
    image: minio/minio:RELEASE.2025-09-07T16-13-09Z
    command: ["server", "/data", "--console-address", ":9001"]
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}
    volumes:
      - miniodata:/data
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:9000/minio/health/live || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddydata:/data
      - caddyconfig:/config
    depends_on:
      - api
      - web
    restart: unless-stopped

volumes:
  pgdata: {}
  redisdata: {}
  miniodata: {}
  caddydata: {}
  caddyconfig: {}
```

### 3.2 New file: `infra/docker/caddy/Caddyfile`

```
{$DOMAIN} {
    # Frontend
    handle /* {
        reverse_proxy web:3000
    }

    # API
    handle /api/* {
        reverse_proxy api:8000
    }

    # WebSocket
    handle /ws/* {
        reverse_proxy api:8000
    }

    # OMS API (internal or separate subdomain)
    handle /oms/* {
        reverse_proxy oms:8001
    }
}
```

### 3.3 New file: `infra/docker/.env.prod.example`

```bash
# Production environment template
# Copy to .env.prod and fill in real values

DOMAIN=astraeus.example.com
TAG=latest
GITHUB_OWNER=your-github-username

# Database
DB_USER=astraeus
DB_PASSWORD=CHANGE_ME_STRONG_PASSWORD

# MinIO
MINIO_USER=astraeus
MINIO_PASSWORD=CHANGE_ME_STRONG_PASSWORD

# Auth
ASTRAEUS_AUTH_JWT_SECRET=CHANGE_ME_RANDOM_64_CHARS
NEXTAUTH_SECRET=CHANGE_ME_SAME_AS_JWT_SECRET

# Market Data API Keys
ASTRAEUS_MD_ALPACA_API_KEY=
ASTRAEUS_MD_ALPACA_API_SECRET=

# LLM
ASTRAEUS_LLM_ANTHROPIC_API_KEY=
ASTRAEUS_LLM_OPENAI_API_KEY=
```

---

## Phase 4: Deploy Automation

### 4.1 New file: `.github/workflows/deploy.yml`

```yaml
name: Deploy

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths-ignore:
      - 'docs/**'
      - '*.md'

jobs:
  deploy:
    name: Deploy to VPS
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    needs: [build]  # Reference the existing docker.yml build job
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /opt/astraeus
            docker compose -f compose.prod.yml pull
            docker compose -f compose.prod.yml up -d --remove-orphans
            docker image prune -f
```

### 4.2 New file: `scripts/deploy-vps.sh`

Manual deploy script for when you want to deploy without CI:

```bash
#!/usr/bin/env bash
set -euo pipefail

VPS_HOST="${VPS_HOST:?Set VPS_HOST}"
VPS_USER="${VPS_USER:-deploy}"

echo "==> Deploying to ${VPS_HOST}..."
ssh "${VPS_USER}@${VPS_HOST}" << 'EOF'
  cd /opt/astraeus
  docker compose -f compose.prod.yml pull
  docker compose -f compose.prod.yml up -d --remove-orphans
  docker image prune -f
  echo "==> Deploy complete"
EOF
```

### 4.3 New file: `scripts/setup-vps.sh`

One-time VPS setup script:

```bash
#!/usr/bin/env bash
# Run this once on a fresh Hetzner VPS (Ubuntu 22.04+)
set -euo pipefail

echo "==> Installing Docker..."
curl -fsSL https://get.docker.com | sh
systemctl enable docker

echo "==> Creating deploy user..."
useradd -m -s /bin/bash -G docker deploy
mkdir -p /home/deploy/.ssh
# Add your SSH public key here
# echo "ssh-ed25519 AAAA..." >> /home/deploy/.ssh/authorized_keys

echo "==> Creating app directory..."
mkdir -p /opt/astraeus
chown deploy:deploy /opt/astraeus

echo "==> Setting up firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> Installing fail2ban..."
apt-get install -y fail2ban
systemctl enable fail2ban

echo "==> Enabling unattended upgrades..."
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades

echo "==> Done! Copy compose.prod.yml and .env.prod to /opt/astraeus/"
```

---

## Phase 5: Backup Automation

### 5.1 New file: `scripts/backup-db.sh`

```bash
#!/usr/bin/env bash
# Daily database backup to Hetzner Object Storage via rclone
set -euo pipefail

BACKUP_DIR="/tmp/astraeus-backups"
DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="astraeus-${DATE}.dump"
REMOTE="hetzner-s3:astraeus-backups"
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"

echo "==> Dumping database..."
docker exec astraeus-postgres-1 pg_dump -U astraeus -Fc astraeus > "${BACKUP_DIR}/${BACKUP_FILE}"

echo "==> Uploading to object storage..."
rclone copy "${BACKUP_DIR}/${BACKUP_FILE}" "${REMOTE}/daily/"

echo "==> Cleaning old remote backups (>${RETENTION_DAYS} days)..."
rclone delete "${REMOTE}/daily/" --min-age "${RETENTION_DAYS}d"

echo "==> Cleaning local temp..."
rm -f "${BACKUP_DIR}/${BACKUP_FILE}"

echo "==> Backup complete: ${BACKUP_FILE}"
```

### 5.2 Cron setup (document in README)

```bash
# Add to deploy user's crontab:
# Daily DB backup at 03:00 UTC
0 3 * * * /opt/astraeus/scripts/backup-db.sh >> /var/log/astraeus-backup.log 2>&1
```

---

## Phase 6: Update CI/CD

### 6.1 Update `.github/workflows/ci.yml`

No changes needed. The integration tests already only use Postgres + Redis (no Redpanda service in CI).

### 6.2 Update `.github/workflows/docker.yml`

Add web to the build matrix:

```yaml
matrix:
  app: [api, workers, web]
```

### 6.3 Update `Makefile`

```makefile
# UPDATE the COMPOSE variable to not reference override by default for prod:
COMPOSE := docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml

# ADD new targets:
prod:  ## Deploy production stack (requires .env.prod).
	docker compose -f infra/docker/compose.prod.yml up -d --remove-orphans

prod-logs:  ## Tail production logs.
	docker compose -f infra/docker/compose.prod.yml logs -f --tail=100

prod-down:  ## Stop production stack.
	docker compose -f infra/docker/compose.prod.yml down

backup:  ## Run database backup.
	./scripts/backup-db.sh
```

---

## Phase 7: Documentation & Cleanup

### 7.1 Update `README.md`

Add a "Production Deployment" section:
- VPS setup instructions
- How to deploy
- How backups work
- How to restore from backup
- Monitoring access (Grafana URL)

### 7.2 Update ADR (if exists) or create one

**New file:** `docs/adr/0XX-replace-redpanda-with-redis-streams.md`

Document the decision to remove Redpanda, the reasoning, and the migration approach.

### 7.3 Files to delete (cleanup)

| Path | Reason |
|------|--------|
| `infra/docker/karapace/` | Schema registry no longer needed |
| `infra/docker/redpanda/` | Redpanda bootstrap no longer needed |

### 7.4 Files to keep (shelved, not deleted)

| Path | Reason |
|------|--------|
| `infra/terraform/` | Valuable for Phase 4 migration |
| `apps/*/deploy/chart/` | Helm charts for future k3s/EKS |
| `gitops/` | ArgoCD config for future use |
| `Tiltfile` | Local k8s dev if needed |
| `infra/kind/` | Kind cluster bootstrap |

---

## Execution Order & Dependencies

```
Phase 1 (Redis Streams)
  ├── 1.1 Create stream_relay.py
  ├── 1.2 (Skip — NLP worker already polls DB)
  ├── 1.3 Update config (remove KafkaSettings)
  ├── 1.4 Update pyproject.toml dependencies
  ├── 1.5–1.6 Update docstrings
  └── 1.7 Run tests, verify nothing breaks
         │
         ▼
Phase 2 (Remove Redpanda from Compose)
  ├── 2.1 Update compose.yml
  ├── 2.2 Update compose.override.yml
  ├── 2.3 Update compose.phase5.yml
  ├── 2.4 Update .env.example
  └── 2.5 Update verify-stack.sh
         │
         ▼
Phase 3 (Production Compose) ←── Can start in parallel with Phase 1
  ├── 3.1 Create compose.prod.yml
  ├── 3.2 Create Caddyfile
  └── 3.3 Create .env.prod.example
         │
         ▼
Phase 4 (Deploy Automation)
  ├── 4.1 Create deploy.yml workflow
  ├── 4.2 Create deploy-vps.sh
  └── 4.3 Create setup-vps.sh
         │
         ▼
Phase 5 (Backups)
  ├── 5.1 Create backup-db.sh
  └── 5.2 Document cron setup
         │
         ▼
Phase 6 (CI/CD Updates)
  ├── 6.1 Verify CI still passes
  ├── 6.2 Add web to docker build matrix
  └── 6.3 Update Makefile
         │
         ▼
Phase 7 (Documentation)
  ├── 7.1 Update README
  ├── 7.2 Write ADR
  └── 7.3 Delete karapace/ and redpanda/ dirs
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Redis Streams doesn't handle backpressure well | Low | Medium | Outbox table acts as buffer; relay controls drain rate |
| Losing events during migration | Low | Medium | Outbox table is the source of truth; unpublished rows retry |
| NLP worker breaks without Kafka | None | None | It never used Kafka — already polls DB |
| Portfolio events break | None | None | Consumer code was never implemented against Kafka |
| Tests fail after removing aiokafka | Low | Low | Only outbox_relay tests need updating |
| Production compose doesn't work first try | Medium | Low | Test locally with `docker compose -f compose.prod.yml up` |

---

## Verification Checklist

After each phase, verify:

- [ ] `make lint` passes
- [ ] `make typecheck` passes
- [ ] `make test` passes (unit tests)
- [ ] `make dev` brings up the full local stack
- [ ] Outbox relay publishes to Redis Streams (check with `redis-cli XLEN md.equity.daily.v1`)
- [ ] Market data backfill still works (`make backfill SYMBOLS=SPY START=2024-01-01 END=2024-01-31`)
- [ ] NLP worker still processes documents
- [ ] API health endpoint responds
- [ ] WebSocket connections work

---

## What This Does NOT Change

- **Application logic** — No business logic changes. Same ingestion, same NLP, same portfolio construction.
- **Database schema** — The `outbox` table stays exactly as-is. Same columns, same indexes.
- **API contracts** — No endpoint changes. Frontend is unaffected.
- **Test structure** — Same test markers, same pytest config.
- **Helm charts / Terraform** — Left untouched (shelved, not deleted).
- **CI pipeline** — Lint, typecheck, unit tests, integration tests all stay the same.

---

## Timeline Estimate

| Phase | Effort | Can Parallelize? |
|-------|--------|-----------------|
| Phase 1 | 2–3 days | No (blocking) |
| Phase 2 | 2 hours | After Phase 1 |
| Phase 3 | 1 day | Yes (parallel with Phase 1) |
| Phase 4 | Half day | After Phase 3 |
| Phase 5 | Half day | After Phase 3 |
| Phase 6 | 1 hour | After Phase 1+2 |
| Phase 7 | Half day | Last |
| **Total** | **~5–7 days** | |

The critical path is Phase 1 → Phase 2 → Phase 6. Everything else can be done in parallel or after.
