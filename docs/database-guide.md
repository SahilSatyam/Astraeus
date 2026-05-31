# Database Guide

## Architecture

Astraeus uses PostgreSQL 16 with two extensions:
- **TimescaleDB 2.15** — Time-series hypertables with automatic partitioning and compression
- **pgvector** — Vector similarity search for RAG embeddings

### Databases

| Database | Purpose |
|----------|---------|
| `astraeus` | OLTP — services, control plane, all application tables |
| `astraeus_research` | Research — TimescaleDB hypertables for analysis (created by init.sql) |

### Connection Configuration

```
postgresql+asyncpg://astraeus:***@localhost:5432/astraeus  (async, runtime)
postgresql+psycopg://astraeus:***@localhost:5432/astraeus  (sync, Alembic)
```

Pool settings: size=10, max_overflow=20, timeout=30s

---

## Schema Overview

```mermaid
erDiagram
    system_health {
        int id PK
        varchar component UK
        timestamptz checked_at
    }

    instruments {
        varchar symbol PK
        varchar asset_class
        varchar primary_exchange
        date listed_at
        date delisted_at
        varchar sector
        varchar industry
        boolean is_active
    }

    market_bars_raw {
        varchar symbol PK
        timestamptz ts PK
        varchar resolution PK
        varchar source PK
        numeric open
        numeric high
        numeric low
        numeric close
        bigint volume
        numeric vwap
        int trades
        smallint schema_version
        uuid ingest_run_id
        bytea payload_hash
    }

    market_bars_adjusted {
        varchar symbol PK
        timestamptz ts PK
        varchar resolution PK
        varchar source PK
        numeric open
        numeric high
        numeric low
        numeric close
        timestamptz adjusted_at
        bytea adjustment_hash
    }

    corporate_actions {
        uuid id PK
        varchar symbol
        varchar action_type
        date ex_date
        numeric ratio
        numeric cash_amount
        varchar source
        jsonb raw_payload
    }

    order_t {
        uuid order_id PK
        text client_order_id UK
        text account_id
        text strategy_id
        text symbol
        text side
        numeric qty
        text order_type
        numeric limit_price
        text tif
        text state
        text submitted_to
        text broker_order_id
    }

    order_event {
        bigint event_seq PK
        uuid order_id FK
        text event_type
        jsonb payload
        timestamptz occurred_at
    }

    fill {
        uuid fill_id PK
        uuid order_id FK
        numeric qty
        numeric price
        numeric fees
        text venue
        timestamptz occurred_at
    }

    position {
        text account_id PK
        text symbol PK
        numeric qty
        numeric avg_cost
    }
```

## Tables by Phase

### Phase 0 — Foundation
| Table | Purpose |
|-------|---------|
| `system_health` | Readiness probe marker |

### Phase 1 — Market Data
| Table | Type | Purpose |
|-------|------|---------|
| `instruments` | Regular | Canonical symbol registry |
| `market_bars_raw` | Hypertable (7-day chunks) | Raw OHLCV bars |
| `market_bars_adjusted` | Hypertable (7-day chunks) | Split/dividend-adjusted bars |
| `corporate_actions` | Regular | Splits, dividends, mergers |
| `data_lineage` | Regular | Provenance tracking |
| `outbox` | Regular | Transactional outbox |
| `data_gaps` | Regular | Detected missing data |

### Phase 2 — Feature Store
| Table | Purpose |
|-------|---------|
| `feature_registry` | Feature catalog with metadata |
| `feature_materialization_runs` | Backfill/materialization tracking |
| `universe` | Bitemporal membership (PIT-safe) |
| `security_master` | Canonical symbol with identifiers |
| `security_alias` | External identifier resolution |

### Phase 4 — Portfolio & Risk
| Table | Purpose |
|-------|---------|
| `target_portfolios` | Versioned target allocations |
| `portfolio_weights` | Per-asset weights |
| `risk_reports` | VaR, CVaR, stress scenarios |
| `risk_rejections` | Structured rejection logging |
| `attribution_runs` | PnL decomposition |
| `factor_returns` | Ken French factor data (hypertable) |
| `task_runs` | Pipeline idempotency tracking |

### Phase 5 — Alt-Data & NLP
| Table | Purpose |
|-------|---------|
| `raw_document` | Document metadata (body in MinIO) |
| `document_chunk` | Text chunks with vector embeddings |
| `entity_mention` | NER-detected entities |
| `sentiment_score` | Per-doc per-ticker sentiment |
| `topic_model_run` | BERTopic refit metadata |
| `topic_assignment` | Topic assignments per chunk |

### Phase 6 — Agent Runtime
| Table | Purpose |
|-------|---------|
| `agent_run` | Workflow run metadata |
| `agent_step` | Per-agent step within a run |
| `llm_call_ledger` | LLM API call tracking (cost, tokens) |
| `tool_call_ledger` | Tool invocation tracking |
| `prompt_registry` | Versioned prompts with lifecycle |
| `hitl_queue` | Human-in-the-loop items |

### Phase 8 — Trading Infrastructure
| Table | Purpose |
|-------|---------|
| `order_t` | Order records with state machine |
| `order_event` | Append-only event log |
| `fill` | Individual fill records |
| `position` | Current position snapshot |
| `reconciliation_diff` | Detected drift |
| `kill_switch_state` | Kill switch per scope |
| `trade_journal` | Append-only audit log |

---

## Key Indexes

| Table | Index | Type | Purpose |
|-------|-------|------|---------|
| `market_bars_raw` | `(symbol, ts)` | B-tree | Symbol lookup |
| `market_bars_raw` | `(ingest_run_id)` | B-tree | Run correlation |
| `document_chunk` | `embedding` | HNSW (cosine) | Vector similarity |
| `document_chunk` | `to_tsvector(text)` | GIN | Full-text search |
| `risk_rejections` | `failed_checks` | GIN | JSONB query |
| `outbox` | `published_at WHERE NULL` | Partial B-tree | Unpublished events |
| `hitl_queue` | `(priority, created_at)` | B-tree | Priority queue |

---

## Compression Policies

| Hypertable | Segment By | Compress After |
|------------|-----------|:-------------:|
| `market_bars_raw` | `symbol, source` | 30 days |
| `market_bars_adjusted` | `symbol, source` | 30 days |

---

## Stored Functions

| Function | Purpose |
|----------|---------|
| `pit_latest(table, symbol, as_of)` | Point-in-time feature retrieval |

---

## Database Roles

| Role | Permissions | Purpose |
|------|-------------|---------|
| `astraeus` (owner) | ALL | Application user |
| `researcher_ro` | SELECT only | JupyterLab read-only access |

---

## Migration Management

```bash
# Apply all pending migrations
make migrate

# Roll back one migration
make downgrade

# Create a new migration
make revision MSG="add new_table"
```

Migrations run automatically on API container startup:
```
cd /app/libs/db && alembic upgrade head && cd /app && uvicorn ...
```

---

## Query Patterns

### Point-in-Time Feature Retrieval
```sql
SELECT * FROM pit_latest('feature_sma_20'::regclass, 'AAPL', '2026-05-31'::timestamptz);
```

### Latest Bars for Symbol
```sql
SELECT * FROM market_bars_raw
WHERE symbol = 'SPY' AND resolution = '1d'
ORDER BY ts DESC LIMIT 30;
```

### Unpublished Outbox Events
```sql
SELECT * FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT 100;
```

### Active Kill Switches
```sql
SELECT * FROM kill_switch_state WHERE armed = true;
```
