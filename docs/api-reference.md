# API Reference

## Overview

Astraeus exposes two HTTP services:
- **API Service** (port 8000) — Main platform API
- **OMS Service** (port 8001) — Order Management System

Both services generate OpenAPI schemas accessible at `/docs` (Swagger UI) and `/redoc`.

## Authentication

All endpoints (except public paths) require a Bearer JWT token:
```
Authorization: Bearer <jwt_token>
```

Public paths (no auth): `/healthz`, `/readyz`, `/metrics`, `/version`, `/docs`, `/openapi.json`

---

## Health & Operations

### GET /healthz — Liveness Probe

**Response 200:**
```json
{
  "status": "ok",
  "service": "api",
  "version": "0.1.0"
}
```

### GET /readyz — Readiness Probe

Checks database connectivity.

**Response 200:**
```json
{
  "status": "ok",
  "service": "api",
  "checks": [
    {"name": "postgres", "healthy": true, "detail": null}
  ]
}
```

**Response 503:**
```json
{
  "detail": "Dependency unavailable.",
  "code": "astraeus.api.dependency_unavailable",
  "checks": [{"name": "postgres", "healthy": false, "detail": "ConnectionRefusedError"}]
}
```

### GET /version — Service Metadata

**Response 200:**
```json
{
  "service": "api",
  "version": "0.1.0",
  "git_sha": "abc1234"
}
```

### GET /metrics — Prometheus Metrics

Returns Prometheus text format metrics. Not included in OpenAPI schema.

---

## Agent Runtime

### POST /agents/runs — Start Workflow Run

**Auth:** Required (analyst+ role)

**Request:**
```json
{
  "workflow": "trade_thesis",
  "inputs": {"symbol": "AAPL", "timeframe": "1M"},
  "options": {
    "channel": "promoted",
    "max_cost_usd": 0.50,
    "timeout_s": 60
  }
}
```

**Valid workflows:** `trade_thesis`, `daily_brief`, `portfolio_commentary`, `risk_drilldown`

**Response 202:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status_url": "/agents/runs/550e8400-e29b-41d4-a716-446655440000"
}
```

**Error 400:** Invalid workflow key

### GET /agents/runs/{run_id} — Get Run Status

**Auth:** Required

**Response 200:**
```json
{
  "run_id": "550e8400-...",
  "status": "completed",
  "workflow_key": "trade_thesis",
  "output": {"thesis": "...", "confidence": 0.85},
  "cost_usd": 0.12,
  "duration_ms": 3400,
  "hitl_required": false,
  "error": ""
}
```

**Status values:** `running`, `completed`, `hitl_pending`, `rejected`, `failed`

### GET /agents/runs/{run_id}/trace — Get Run Trace

**Auth:** Required

**Response 200:**
```json
{
  "run_id": "550e8400-...",
  "workflow_key": "trade_thesis",
  "steps": [
    {"step_id": "...", "agent_name": "research_agent", "status": "completed", "duration_ms": 1200},
    {"step_id": "...", "agent_name": "synthesis_agent", "status": "completed", "duration_ms": 2200}
  ],
  "total_cost_usd": 0.12,
  "total_duration_ms": 3400
}
```

---

## Order Management System (OMS)

### POST /oms/orders — Submit Order

**Auth:** Required (`write:orders` permission — Operator or Service role)

**Request:**
```json
{
  "client_order_id": "strategy-abc-20260531-001",
  "account_id": "paper-001",
  "strategy_id": "momentum_v2",
  "symbol": "AAPL",
  "side": "buy",
  "qty": 100,
  "order_type": "limit",
  "limit_price": 185.50,
  "tif": "DAY"
}
```

**Response 201:** Order created
```json
{
  "order_id": "...",
  "client_order_id": "strategy-abc-20260531-001",
  "state": "submitted",
  "symbol": "AAPL",
  "side": "buy",
  "qty": 100,
  "created_at": "2026-05-31T10:00:00Z"
}
```

**Response 200:** Idempotent — order already exists (returns existing)

**Response 423:** Kill switch is armed
```json
{"detail": "Kill switch armed: global"}
```

**Response 422:** Risk check failed

### POST /oms/orders/{order_id}/cancel — Cancel Order

**Auth:** Required (`write:orders` permission)

**Request:**
```json
{"reason": "Strategy signal reversed"}
```

**Response 200:** Order cancelled

**Response 400:** Invalid state transition

### GET /oms/orders/{order_id} — Get Order

**Auth:** Required (any authenticated user)

### GET /oms/orders — List Orders

**Auth:** Required

**Query Parameters:**
- `account_id` (optional) — Filter by account
- `strategy_id` (optional) — Filter by strategy

**Response 200:** Array of up to 100 orders, newest first

---

## Kill Switch

### POST /killswitch/arm — Arm Kill Switch

**Auth:** Required (`write:kill_switch` permission)

**Request:**
```json
{"scope": "global", "reason": "Market volatility"}
```

### POST /killswitch/disarm — Disarm Kill Switch

**Auth:** Required (`write:kill_switch` permission)

### GET /killswitch/status — Get Kill Switch State

**Auth:** Required

---

## Market Data

### Endpoints (via `marketdata_router`)

- `GET /marketdata/bars` — Query historical bars
- `GET /marketdata/instruments` — List instruments
- `GET /marketdata/gaps` — List detected data gaps
- `WS /ws/bars` — WebSocket streaming for live bars

---

## Features

### Endpoints (via `features_router`)

- `GET /features/registry` — List registered features
- `GET /features/{name}/values` — Query feature values (PIT-safe)

---

## Alternative Data

### Endpoints (via `altdata_router`)

- `GET /altdata/documents` — List ingested documents
- `GET /altdata/sentiment` — Query sentiment scores
- `GET /altdata/entities` — Query entity mentions

---

## RAG (Retrieval-Augmented Generation)

### Endpoints (via `rag_router`)

- `POST /rag/search` — Hybrid search (BM25 + vector)
- `GET /rag/chunks/{doc_id}` — Get document chunks

---

## Recommender

### Endpoints (via `recommender_router`)

- `GET /reco/latest` — Latest recommendations
- `POST /reco/replay` — Replay recommendation pipeline

---

## HITL (Human-in-the-Loop)

### Endpoints (via `hitl_router`)

- `GET /hitl/pending` — List pending approval items
- `POST /hitl/{id}/approve` — Approve an item
- `POST /hitl/{id}/reject` — Reject an item

---

## Error Format

All errors follow RFC 7807 Problem Details:

```json
{
  "detail": "Human-readable error message",
  "code": "astraeus.api.error_code",
  "status": 400,
  "extra": {}
}
```

## Rate Limiting Headers

All mutating responses include:
```
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 299
```

When rate limited (429):
```
Retry-After: 60
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 0
```
