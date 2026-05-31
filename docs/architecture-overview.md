# Architecture Overview

## Executive Summary

Astraeus is an institutional-grade AI-powered quantitative trading and research platform. It combines real-time market data ingestion, NLP-driven alternative data analysis, portfolio optimization, order management, and an AI copilot into a single deployable stack.

**Business Problem:** Provide a solo engineer or small team with the same quantitative research and trading infrastructure that institutional hedge funds use — at a fraction of the cost (~$30/month on a single VPS).

**Key Goals:**
- Real-time market data ingestion and streaming
- AI-assisted trade research and recommendations
- Automated portfolio construction with risk management
- Event-sourced order management with pre-trade risk checks
- Full observability and auditability

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Scalability | ~500 concurrent users on single VPS (16GB RAM) |
| Availability | 99.5% uptime (single-node, graceful degradation) |
| Latency (API) | p95 < 250ms for CRUD, p95 < 2s for AI workflows |
| Data Freshness | Real-time streaming (sub-second), batch nightly |
| Security | JWT auth, RBAC, secrets validation, rate limiting |
| Observability | Structured logging, distributed tracing, metrics |
| Cost | < $30/month infrastructure |

## Architectural Principles

1. **Monorepo with workspace isolation** — All 22 Python libraries and 5 apps share a single lockfile but maintain strict import boundaries.
2. **Event-driven where it matters** — Outbox pattern for reliable event publishing; Redis Streams for inter-service communication.
3. **Fail-fast on misconfiguration** — Services refuse to boot in staging/prod with default development secrets.
4. **Point-in-time correctness** — All financial data uses bitemporal modeling (event_ts + knowledge_ts) to prevent lookahead bias.
5. **Defense in depth** — Rate limiting, pre-trade risk checks, circuit breakers, kill switches, and reconciliation loops.
6. **Observability by default** — Every request gets a trace_id, request_id, and structured log context.

## Design Decisions and Trade-offs

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Single VPS deployment | Cost efficiency, operational simplicity | No HA, single point of failure |
| PostgreSQL + TimescaleDB | One database for OLTP + time-series + vectors | Higher memory usage vs. specialized stores |
| Redis for everything (cache, streams, rate limiting) | Operational simplicity | Not as durable as Kafka for event streaming |
| Monorepo (uv workspace) | Single lockfile, atomic refactors, shared CI | Larger clone, longer initial sync |
| FastAPI + async | High throughput on single process, native async DB | Python GIL limits CPU-bound work |
| Docker Compose (not K8s) for prod | Simplicity for single-node | Manual scaling, no auto-healing |

---

## High-Level Architecture Diagram

```mermaid
C4Context
    title Astraeus System Context

    Person(user, "Trader/Analyst", "Uses web UI and API")
    System(astraeus, "Astraeus Platform", "AI-powered quant trading platform")
    System_Ext(alpaca, "Alpaca", "Broker API (orders, positions, streaming)")
    System_Ext(polygon, "Polygon.io", "Historical market data")
    System_Ext(yahoo, "Yahoo Finance", "Free historical data")
    System_Ext(fred, "FRED", "Economic indicators")
    System_Ext(reddit, "Reddit API", "Alternative data")
    System_Ext(llm, "LLM APIs", "Claude / GPT-4")
    System_Ext(huggingface, "HuggingFace", "NLP models (FinBERT, embeddings)")

    Rel(user, astraeus, "HTTPS / WebSocket")
    Rel(astraeus, alpaca, "REST / WebSocket")
    Rel(astraeus, polygon, "REST")
    Rel(astraeus, yahoo, "REST")
    Rel(astraeus, fred, "REST")
    Rel(astraeus, reddit, "REST")
    Rel(astraeus, llm, "REST")
    Rel(astraeus, huggingface, "Model download")
```

## Container Diagram

```mermaid
C4Container
    title Astraeus Container Diagram

    Person(user, "User")

    Container_Boundary(frontend, "Frontend") {
        Container(web, "Web App", "Next.js 16, React 19", "SPA with SSR")
    }

    Container_Boundary(gateway, "Reverse Proxy") {
        Container(caddy, "Caddy", "HTTP/2, auto-TLS", "Routes traffic, terminates TLS")
    }

    Container_Boundary(backend, "Backend Services") {
        Container(api, "API Service", "FastAPI, Python 3.12", "Main CRUD, AI copilot, recommendations")
        Container(oms, "OMS Service", "FastAPI, Python 3.12", "Order management, risk checks, kill switch")
        Container(workers, "Workers", "Python 3.12, asyncio", "Streaming, outbox relay, nightly batch")
        Container(recon, "Recon Worker", "Python 3.12", "5-second reconciliation loop")
    }

    Container_Boundary(data, "Data Layer") {
        ContainerDb(postgres, "PostgreSQL 16", "TimescaleDB + pgvector", "OLTP, time-series, embeddings")
        ContainerDb(redis, "Redis 7.2", "Cache + Streams", "Rate limiting, event bus, task queue")
        ContainerDb(minio, "MinIO", "S3-compatible", "Documents, model artifacts")
    }

    Container_Boundary(obs, "Observability") {
        Container(jaeger, "Jaeger", "Tracing", "Distributed trace collection")
        Container(prometheus, "Prometheus", "Metrics", "Time-series metrics store")
        Container(grafana, "Grafana", "Dashboards", "Visualization and alerting")
    }

    Rel(user, caddy, "HTTPS")
    Rel(caddy, web, "/")
    Rel(caddy, api, "/api/*, /ws/*")
    Rel(caddy, oms, "/oms/*")
    Rel(web, api, "REST/WS")
    Rel(api, postgres, "asyncpg")
    Rel(api, redis, "redis-py")
    Rel(api, minio, "S3 API")
    Rel(oms, postgres, "asyncpg")
    Rel(oms, redis, "redis-py")
    Rel(workers, postgres, "asyncpg")
    Rel(workers, redis, "Streams")
    Rel(recon, postgres, "asyncpg")
    Rel(api, jaeger, "OTLP/gRPC")
    Rel(prometheus, api, "scrape /metrics")
    Rel(grafana, prometheus, "PromQL")
```

## Request Lifecycle

```mermaid
sequenceDiagram
    participant Client
    participant Caddy
    participant API
    participant Middleware
    participant Router
    participant DB
    participant Redis

    Client->>Caddy: HTTPS Request
    Caddy->>API: HTTP (stripped TLS)
    API->>Middleware: ProxyHeaders (extract real IP)
    Middleware->>Middleware: RequestContext (bind request_id, trace_id)
    Middleware->>Middleware: RateLimit (check Redis/in-memory)
    alt Rate Limited
        Middleware-->>Client: 429 Too Many Requests
    end
    Middleware->>Router: Route to handler
    Router->>DB: Query (async SQLAlchemy)
    DB-->>Router: Result
    Router-->>API: Response
    API-->>Caddy: HTTP Response
    Caddy-->>Client: HTTPS Response
```

## Event Flow (Outbox Pattern)

```mermaid
sequenceDiagram
    participant Service
    participant DB
    participant OutboxRelay
    participant Redis Streams
    participant Consumer

    Service->>DB: INSERT data + INSERT outbox (same tx)
    DB-->>Service: Committed
    loop Every 2 seconds
        OutboxRelay->>DB: SELECT unpublished FROM outbox
        OutboxRelay->>Redis Streams: XADD event
        OutboxRelay->>DB: UPDATE outbox SET published_at = now()
    end
    Consumer->>Redis Streams: XREAD (blocking)
    Redis Streams-->>Consumer: Event payload
```

## Data Flow Overview

```mermaid
flowchart LR
    subgraph Sources
        A[Alpaca WS]
        B[Polygon REST]
        C[Yahoo Finance]
        D[FRED]
        E[Reddit]
        F[RSS/EDGAR]
    end

    subgraph Ingestion
        G[Streaming Worker]
        H[Batch Backfill]
        I[Alt-Data Ingest]
    end

    subgraph Storage
        J[(PostgreSQL + TimescaleDB)]
        K[(Redis Streams)]
        L[(MinIO)]
    end

    subgraph Processing
        M[NLP Pipeline]
        N[Feature Store]
        O[Regime Detection]
    end

    subgraph Output
        P[Portfolio Optimizer]
        Q[Recommender]
        R[AI Copilot]
        S[OMS]
    end

    A --> G --> J
    B --> H --> J
    C --> H
    D --> H
    E --> I --> L
    F --> I
    I --> M --> J
    J --> N --> J
    J --> O --> J
    N --> P --> S
    N --> Q --> R
    J --> R
```

## Order Lifecycle (Event Sourcing)

```mermaid
stateDiagram-v2
    [*] --> pending_new: submit_order()
    pending_new --> submitted: broker_ack
    pending_new --> rejected: risk_check_fail
    submitted --> partially_filled: partial_fill
    submitted --> filled: full_fill
    submitted --> pending_cancel: cancel_request
    partially_filled --> filled: remaining_fill
    partially_filled --> pending_cancel: cancel_request
    pending_cancel --> cancelled: cancel_ack
    pending_cancel --> filled: fill_before_cancel
    filled --> [*]
    cancelled --> [*]
    rejected --> [*]
```

## Kill Switch Flow

```mermaid
flowchart TD
    A[Order Request] --> B{Kill Switch Armed?}
    B -->|No| C{Pre-Trade Risk Check}
    B -->|Yes| D[423 Locked - Kill Switch Active]
    C -->|Pass| E[Submit to Broker]
    C -->|Fail| F[Reject Order]
    E --> G[Event Sourced State Machine]
    G --> H[Position Update]
    H --> I[Reconciliation Loop]
```
