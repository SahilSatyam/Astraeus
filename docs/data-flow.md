# Data Flow

## Overview

Astraeus processes data through several distinct flows:
1. **Real-time streaming** — Live market bars via WebSocket
2. **Batch ingestion** — Historical backfill and nightly jobs
3. **Event-driven** — Outbox pattern for reliable inter-service communication
4. **NLP pipeline** — Document ingestion → chunking → embedding → indexing
5. **Portfolio pipeline** — Signals → optimization → risk check → execution

## Real-Time Market Data Flow

```mermaid
sequenceDiagram
    participant Alpaca WS
    participant StreamingWorker
    participant DB (TimescaleDB)
    participant Outbox
    participant OutboxRelay
    participant Redis Streams
    participant API (WebSocket)
    participant Client

    Alpaca WS->>StreamingWorker: Bar update (JSON)
    StreamingWorker->>StreamingWorker: Validate + normalize
    StreamingWorker->>DB (TimescaleDB): INSERT market_bars_raw
    StreamingWorker->>Outbox: INSERT outbox (same tx)
    Note over StreamingWorker,Outbox: Atomic: data + event in one transaction
    OutboxRelay->>Outbox: SELECT WHERE published_at IS NULL
    OutboxRelay->>Redis Streams: XADD bars.{resolution}.{symbol}
    OutboxRelay->>Outbox: UPDATE SET published_at = now()
    API (WebSocket)->>Redis Streams: XREAD (blocking)
    API (WebSocket)->>Client: Push bar update
```

## Batch Ingestion Flow

```mermaid
flowchart TD
    A[make backfill SYMBOLS=SPY START=... END=...] --> B[md-backfill.py]
    B --> C{Source?}
    C -->|yahoo| D[Yahoo Finance API]
    C -->|alpaca| E[Alpaca Historical API]
    C -->|polygon| F[Polygon.io API]
    D --> G[Normalize to BarEvent schema]
    E --> G
    F --> G
    G --> H[Validate schema_version + payload_hash]
    H --> I[INSERT market_bars_raw]
    I --> J[INSERT data_lineage]
    J --> K[INSERT outbox]
    K --> L[COMMIT transaction]
    L --> M[Log ingestion_run metrics]
```

## Outbox Relay Pattern

```mermaid
flowchart TD
    subgraph "Transaction Boundary"
        A[Business Logic] --> B[INSERT data]
        A --> C[INSERT outbox entry]
        B --> D[COMMIT]
        C --> D
    end

    subgraph "Relay Loop (every 2s)"
        E[SELECT unpublished] --> F{Events found?}
        F -->|Yes| G[XADD to Redis Stream]
        G --> H[UPDATE published_at]
        F -->|No| I[Sleep 2s]
    end

    subgraph "Consumer"
        J[XREAD blocking] --> K[Process event]
        K --> L[ACK]
    end

    D -.-> E
    H -.-> J
```

**Design Decisions:**
- Outbox guarantees at-least-once delivery (no lost events)
- Redis Streams provide consumer groups for fan-out
- 2-second relay interval balances latency vs DB load
- If Redis is unavailable, relay logs events and retries

## NLP Pipeline Flow

```mermaid
flowchart TD
    subgraph Ingestion
        A[Reddit/RSS/EDGAR] --> B[Raw Document]
        B --> C[Store body in MinIO]
        C --> D[INSERT raw_document metadata]
    end

    subgraph Chunking
        D --> E[Load body from MinIO]
        E --> F[Token-aware splitting]
        F --> G[INSERT document_chunk]
    end

    subgraph Embedding
        G --> H[sentence-transformers BGE-small]
        H --> I[UPDATE chunk SET embedding = vector]
    end

    subgraph NER
        G --> J[spaCy NER]
        J --> K[INSERT entity_mention]
    end

    subgraph Sentiment
        D --> L[FinBERT per ticker]
        L --> M[INSERT sentiment_score]
    end

    subgraph Topics
        G --> N[BERTopic fit/transform]
        N --> O[INSERT topic_assignment]
    end

    subgraph Indexing
        I --> P[HNSW vector index]
        G --> Q[GIN full-text index]
    end
```

## Portfolio Construction Pipeline

```mermaid
sequenceDiagram
    participant Scheduler
    participant FeatureStore
    participant RegimeDetector
    participant Strategy
    participant Optimizer
    participant RiskGateway
    participant DB
    participant OMS

    Scheduler->>FeatureStore: Materialize features (PIT)
    FeatureStore->>RegimeDetector: Current regime?
    RegimeDetector-->>Strategy: regime = {bull|bear|neutral}
    Strategy->>Strategy: Generate signals
    Strategy->>Optimizer: signals + constraints
    Optimizer->>Optimizer: cvxpy solve (min variance / max Sharpe)
    Optimizer->>RiskGateway: Proposed portfolio
    RiskGateway->>RiskGateway: Check VaR, exposure, concentration
    alt Risk Passed
        RiskGateway->>DB: INSERT target_portfolio (status=passed)
        RiskGateway->>DB: INSERT risk_report
        DB->>OMS: Generate orders (target vs current)
    else Risk Failed (fallback)
        RiskGateway->>Optimizer: Apply fallback constraints
        Optimizer->>DB: INSERT target_portfolio (status=fallback_applied)
    else Risk Rejected
        RiskGateway->>DB: INSERT risk_rejection
        Note over RiskGateway: No orders generated
    end
```

## Order Execution Flow

```mermaid
sequenceDiagram
    participant Client
    participant OMS API
    participant RiskGateway
    participant KillSwitch
    participant StateMachine
    participant Broker (Alpaca)
    participant DB
    participant ReconWorker

    Client->>OMS API: POST /oms/orders
    OMS API->>KillSwitch: Is armed?
    alt Kill Switch Armed
        OMS API-->>Client: 423 Locked
    end
    OMS API->>RiskGateway: Pre-trade checks
    RiskGateway->>RiskGateway: ExposureCap + PositionLimit + DailyLoss + AIConfidence
    alt Risk Check Failed
        OMS API-->>Client: 422 Risk Rejection
    end
    OMS API->>StateMachine: Create order (pending_new)
    OMS API->>DB: INSERT order_t + order_event
    OMS API->>Broker (Alpaca): Submit order
    Broker (Alpaca)-->>OMS API: broker_order_id
    OMS API->>StateMachine: Transition → submitted
    OMS API->>DB: INSERT order_event (submitted)
    OMS API-->>Client: 201 Created

    loop Fill events
        Broker (Alpaca)->>OMS API: Fill notification
        OMS API->>StateMachine: Transition → partially_filled/filled
        OMS API->>DB: INSERT fill + order_event
        OMS API->>DB: UPDATE position
    end

    loop Every 5 seconds
        ReconWorker->>Broker (Alpaca): GET positions
        ReconWorker->>DB: SELECT positions
        ReconWorker->>ReconWorker: Compare
        alt Drift detected
            ReconWorker->>DB: INSERT reconciliation_diff
        end
    end
```

## AI Copilot Flow

```mermaid
sequenceDiagram
    participant User
    participant API
    participant Orchestrator
    participant RAG
    participant LLM (Claude)
    participant DB

    User->>API: POST /agents/runs {workflow: "trade_thesis", inputs: {symbol: "AAPL"}}
    API->>Orchestrator: run_workflow()
    Orchestrator->>DB: INSERT agent_run (status=running)
    Orchestrator->>RAG: Retrieve relevant context
    RAG->>DB: Hybrid search (BM25 + vector)
    RAG-->>Orchestrator: Top-k chunks
    Orchestrator->>LLM (Claude): Prompt + context
    LLM (Claude)-->>Orchestrator: Structured output
    Orchestrator->>DB: INSERT agent_step + llm_call_ledger
    Orchestrator->>DB: UPDATE agent_run (status=completed, output=...)
    API-->>User: 202 Accepted {run_id, status_url}
    User->>API: GET /agents/runs/{run_id}
    API-->>User: {status: "completed", output: {...}}
```

## Topic Naming Convention

Events are published to Redis Streams with structured topic names:

| Topic Pattern | Example | Description |
|---------------|---------|-------------|
| `bars.{resolution}.{symbol}` | `bars.1d.AAPL` | Price bar events |
| `ticks.{symbol}` | `ticks.SPY` | Tick-level events |
| `corporate_actions.{symbol}` | `corporate_actions.TSLA` | Splits, dividends |
| `fundamentals.{symbol}` | `fundamentals.MSFT` | Fundamental data |
| `macro.{indicator}` | `macro.GDP` | Macroeconomic indicators |
| `dlq.{original_topic}` | `dlq.bars.1d.AAPL` | Dead letter queue |
