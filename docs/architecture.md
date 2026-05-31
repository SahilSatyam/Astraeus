# Architecture

## System Overview

```mermaid
graph TB
    subgraph "Frontend"
        WEB[Next.js Operator Terminal]
    end

    subgraph "API Layer"
        API[Research API<br/>FastAPI]
        OMS[Order Management<br/>FastAPI]
    end

    subgraph "Workers"
        MW[Market Data Workers]
        RW[Recon Worker]
    end

    subgraph "AI / ML"
        AGENTS[Agent Runtime<br/>LangGraph]
        RAG[RAG Engine<br/>pgvector]
        RECO[Recommendation<br/>Pipeline]
    end

    subgraph "Data Layer"
        PG[(PostgreSQL<br/>+ TimescaleDB)]
        REDIS[(Redis)]
        KAFKA[Redpanda<br/>Kafka API]
        S3[MinIO / S3]
    end

    subgraph "External"
        BROKER[Broker<br/>Alpaca / IBKR]
        MDATA[Market Data<br/>Polygon / Yahoo]
        LLM[LLM Provider<br/>Anthropic]
    end

    WEB --> API
    WEB --> OMS
    API --> PG
    API --> REDIS
    API --> KAFKA
    API --> AGENTS
    API --> RAG
    API --> RECO
    OMS --> PG
    OMS --> BROKER
    MW --> PG
    MW --> KAFKA
    MW --> MDATA
    RW --> PG
    RW --> BROKER
    AGENTS --> LLM
    AGENTS --> RAG
    RAG --> PG
    RECO --> PG
    RECO --> AGENTS
```

## Service Boundaries

| Service | Namespace | Port | Responsibility |
|---------|-----------|------|----------------|
| API | research | 8000 | Research, features, agents, recommendations, HITL |
| OMS | trading | 8000 | Orders, positions, kill switches, reconciliation |
| Workers | research | — | Market data ingestion, nightly jobs, streaming |
| Recon Worker | trading | — | Broker reconciliation (5s cadence) |
| Web | web | 3000 | Operator terminal UI |

## Data Flow: Order Lifecycle

```mermaid
sequenceDiagram
    participant UI as Operator Terminal
    participant API as Research API
    participant OMS as Order Management
    participant BROKER as Broker (Alpaca/IBKR)
    participant RECON as Recon Worker

    UI->>API: Approve recommendation
    API->>OMS: POST /oms/orders
    OMS->>OMS: Check kill switches
    OMS->>OMS: State: NEW → PENDING_NEW
    OMS->>BROKER: Submit order
    BROKER-->>OMS: Accepted (broker_order_id)
    OMS->>OMS: State: SUBMITTED
    OMS-->>UI: Order confirmed (WebSocket)

    loop Every 5 seconds
        RECON->>BROKER: Get positions & orders
        RECON->>OMS: Compare with local state
        alt Drift detected
            RECON->>OMS: Arm kill switch
            RECON-->>UI: Alert (WebSocket)
        end
    end

    BROKER-->>OMS: Fill notification
    OMS->>OMS: State: FILLED
    OMS-->>UI: Fill confirmed (WebSocket)
```

## Data Flow: Daily Recommendation Pipeline

```mermaid
graph LR
    A[Stage 1<br/>Data Aggregation] --> B[Stage 2<br/>Regime Detection]
    B --> C[Stage 3<br/>Signal Generation]
    C --> D[Stage 4<br/>Ensemble]
    D --> E[Stage 5<br/>Portfolio Construction]
    E --> F[Stage 6<br/>Risk Validation]
    F --> G[Stage 7<br/>AI Explainability]
    G --> H[Stage 8<br/>HITL Approval]
```

## Infrastructure

```mermaid
graph TB
    subgraph "AWS (Production)"
        EKS[EKS Cluster]
        RDS[(RDS PostgreSQL<br/>Multi-AZ)]
        SM[Secrets Manager]
        S3P[S3 Data Lake]
        KMS[KMS Encryption]
    end

    subgraph "Kubernetes"
        subgraph "research ns"
            API_POD[API Pods]
            WORKER_POD[Worker Pods]
        end
        subgraph "trading ns"
            OMS_POD[OMS Pods]
            RECON_POD[Recon Pods]
        end
        subgraph "web ns"
            WEB_POD[Web Pods]
        end
        subgraph "platform ns"
            ARGO[ArgoCD]
            LINKERD[Linkerd]
            OTEL[OTel Collector]
        end
    end

    EKS --> RDS
    EKS --> SM
    EKS --> S3P
    SM --> KMS
```

## Key Design Principles

1. **LLM ↔ Broker isolation:** AI agents cannot directly submit orders. Enforced at import level in CI.
2. **Event sourcing for orders:** Every state transition is an immutable event. Full audit trail.
3. **PIT-correct features:** All feature queries respect point-in-time semantics. No lookahead bias.
4. **Kill switches at every level:** Global, account, and strategy scopes. Recon worker auto-arms on drift.
5. **Observability from day 1:** Structured logs, distributed traces, Prometheus metrics on every service.
