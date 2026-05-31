# Operational Runbooks

## Service Startup

### Full Stack (Local Development)

```bash
# Start all services
make dev

# Verify health
curl http://localhost:8000/healthz
```

**What happens:**
1. Docker Compose builds app images
2. Starts infrastructure (Postgres, Redis, MinIO, Jaeger, Prometheus, Grafana)
3. Waits for health checks to pass
4. Runs MinIO bucket initialization
5. Runs `scripts/verify-stack.sh` smoke test

### Production Startup

```bash
# On VPS
cd /opt/astraeus
docker compose -f compose.prod.yml up -d --remove-orphans
```

**Startup order (enforced by depends_on):**
1. PostgreSQL (waits for `pg_isready`)
2. Redis (waits for `redis-cli ping`)
3. MinIO (waits for health endpoint)
4. API (runs migrations, then starts uvicorn)
5. OMS, Workers
6. Web
7. Caddy (depends on API + Web)

### Individual Service Restart

```bash
# Restart just the API
docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml restart api

# Restart workers
docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml restart workers
```

---

## Service Shutdown

### Graceful Shutdown (Local)

```bash
make stop    # Stop containers, keep volumes
make down    # Remove containers, keep volumes
```

### Graceful Shutdown (Production)

```bash
docker compose -f compose.prod.yml down
```

### Workers Graceful Shutdown

Workers handle SIGINT/SIGTERM:
1. Set stop event
2. Cancel all async tasks
3. Wait for in-flight work to complete
4. Close Redis publisher connection
5. Exit cleanly

---

## Incident Response

### High Error Rate (>5% 5xx)

1. **Check logs:** `make logs` or `docker compose logs api --tail=100`
2. **Check traces:** Open Jaeger (http://localhost:16686), filter by error=true
3. **Check DB:** `docker exec -it astraeus-postgres-1 pg_isready`
4. **Check Redis:** `docker exec -it astraeus-redis-1 redis-cli ping`
5. **Check rate limiting:** Look for 429 responses in logs
6. **Restart if needed:** `docker compose restart api`

### Database Connection Exhaustion

**Symptoms:** Requests timing out, "connection pool exhausted" in logs

**Resolution:**
1. Check active connections: `SELECT count(*) FROM pg_stat_activity;`
2. Kill idle connections: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle' AND query_start < now() - interval '10 minutes';`
3. Increase pool size: Set `ASTRAEUS_DB_POOL_SIZE=20` and restart
4. Check for connection leaks in recent code changes

### Kill Switch Accidentally Armed

**Symptoms:** All order submissions return 423

**Resolution:**
```bash
# Check kill switch state
curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/killswitch/status

# Disarm (requires operator role)
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scope": "global"}' \
  http://localhost:8001/killswitch/disarm
```

### Reconciliation Drift Detected

**Symptoms:** `reconciliation_diff` entries appearing

**Resolution:**
1. Check diffs: `SELECT * FROM reconciliation_diff WHERE resolved_at IS NULL;`
2. Compare local vs broker positions
3. If broker is source of truth, update local position
4. If local is correct, investigate broker-side issue
5. Mark resolved: `UPDATE reconciliation_diff SET resolved_at = now(), resolution = 'manual' WHERE diff_id = '...';`

---

## Disaster Recovery

### Database Backup

```bash
# Manual backup
make backup
# Runs: scripts/backup-db.sh

# Backup command (inside container)
docker exec astraeus-postgres-1 pg_dump -U astraeus -d astraeus | gzip > backup_$(date +%Y%m%d).sql.gz
```

### Database Restore

```bash
# Stop services that write to DB
docker compose stop api oms workers

# Restore from backup
gunzip -c backup_20260531.sql.gz | docker exec -i astraeus-postgres-1 psql -U astraeus -d astraeus

# Re-run migrations (in case backup is older)
make migrate

# Restart services
docker compose start api oms workers
```

### Full Environment Recovery

```bash
# On a fresh VPS:
git clone https://github.com/SahilSatyam/Astraeus.git /opt/astraeus
cd /opt/astraeus

# Restore .env.prod from secure backup
cp /path/to/backup/.env.prod .

# Pull images and start
docker compose -f compose.prod.yml pull
docker compose -f compose.prod.yml up -d

# Restore database from backup
gunzip -c backup.sql.gz | docker exec -i astraeus-postgres-1 psql -U astraeus -d astraeus
```

---

## Rollback Procedures

### Application Rollback

```bash
# On VPS — roll back to previous image tag
export TAG=sha-abc1234  # Previous known-good SHA
docker compose -f compose.prod.yml pull
docker compose -f compose.prod.yml up -d --remove-orphans
```

### Database Migration Rollback

```bash
# Roll back one migration
make downgrade

# Roll back to specific revision
cd libs/db && uv run alembic downgrade 202605291500
```

**Warning:** Some migrations are destructive (DROP TABLE). Always check the downgrade function before rolling back.

### Redis Recovery

Redis uses AOF persistence. On corruption:
```bash
docker compose stop redis
docker volume rm astraeus_redisdata
docker compose up -d redis
```

**Impact:** Rate limit counters reset, cached data lost. No data loss for persistent state (all in PostgreSQL).

### MinIO Recovery

```bash
# Re-create buckets
docker compose --profile init run --rm minio-init
```

**Impact:** If MinIO data volume is lost, raw document bodies are gone. Metadata in PostgreSQL remains. Re-ingest documents from sources.

---

## Monitoring Checks

### Health Check Commands

```bash
# API liveness
curl -f http://localhost:8000/healthz

# API readiness (checks DB)
curl -f http://localhost:8000/readyz

# PostgreSQL
docker exec astraeus-postgres-1 pg_isready -U astraeus -d astraeus

# Redis
docker exec astraeus-redis-1 redis-cli ping

# MinIO
curl -f http://localhost:9000/minio/health/live
```

### Log Inspection

```bash
# All services
make logs

# Specific service
docker compose logs api --tail=50 --follow

# Filter for errors
docker compose logs api 2>&1 | grep '"level":"error"'
```
