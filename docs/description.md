# Institutional-Grade AI Trading & Research Platform - Master Prompt

## Role

You are a principal architect, quantitative researcher, staff-level backend engineer, and systematic trading platform designer.

Your task is to design and help implement an institutional-grade algorithmic trading, market intelligence, and AI-powered research platform using:

* Python
* FastAPI
* PostgreSQL
* Redis
* Celery or Temporal
* Kafka or Redpanda
* Docker + Kubernetes
* Vector database (e.g., pgvector)
* LLM-powered multi-agent orchestration
* Event-driven architecture
* Cloud-native infrastructure

The system must be:

* Resume-worthy for top MBA programs like INSEAD
* Strong enough to discuss in quant/fintech interviews
* Architecturally credible for IB, hedge fund, AWM, prop trading, fintech, or AI infra roles
* Built with production-grade engineering practices
* Modular, observable, testable, and scalable
* Capable of both retail-scale and institutional-style workflows

The output should prioritize:

1. Real-world architecture
2. Production reliability
3. Quantitative rigor
4. Explainability
5. Governance and risk management
6. Extensibility
7. Agentic AI workflows
8. Data quality and reproducibility

Do NOT create toy-project architecture.

Avoid beginner-level simplifications.

Challenge unrealistic assumptions.

Explicitly discuss tradeoffs.

---

# Product Vision

Build a full-stack AI-native quantitative trading and market intelligence platform that:

* Ingests real-time and historical market data
* Performs quantitative analysis and factor modeling
* Backtests systematic trading strategies
* Runs paper trading and live trading
* Performs portfolio optimization
* Uses LLM + agentic systems for research synthesis
* Conducts sentiment analysis from news/social/media/earnings calls
* Generates daily trade recommendations
* Detects market regimes and anomalies
* Provides explainable signals and risk metrics
* Supports multi-asset trading
* Enables strategy experimentation
* Tracks performance and attribution
* Uses AI copilots for research and execution assistance

The platform should feel like a hybrid of:

* Bloomberg Terminal
* Bridgewater research infrastructure
* Two Sigma experimentation platform
* QuantConnect
* Alpaca
* Renaissance-style signal pipelines
* LangGraph/CrewAI style orchestration
* Palantir-style operational intelligence

---

# Core Product Requirements

# 1. Market Data Platform

Design a robust market data ingestion and normalization layer.

## Supported Data Types

* Equities
* ETFs
* Futures
* Forex
* Crypto
* Options
* Macro indicators
* Alternative data

## Data Sources

Support integrations with:

* [Polygon](https://polygon.io)
* [Alpaca](https://alpaca.markets)
* [Binance](https://www.binance.com)
* [Interactive Brokers](https://www.interactivebrokers.com)
* [Yahoo Finance](https://finance.yahoo.com)
* [Alpha Vantage](https://www.alphavantage.co)
* [FRED](https://fred.stlouisfed.org)
* News APIs
* Reddit
* X/Twitter
* SEC filings
* Earnings transcripts

## Required Features

* Historical OHLCV ingestion
* Tick-level streaming support
* WebSocket ingestion
* Corporate action adjustments
* Data normalization
* Schema versioning
* Market calendar support
* Data replay engine
* Data lineage tracking
* Time-series partitioning
* Incremental ingestion
* Deduplication
* Retry and DLQ pipelines
* Idempotent ingestion
* Real-time feature pipelines

## Engineering Expectations

* Kafka/Redpanda event streaming
* PostgreSQL + TimescaleDB
* Redis caching
* Partitioned tables
* Async FastAPI ingestion APIs
* CDC pipelines
* Data contracts
* Schema registry + explicit message serialization (Avro/Protobuf)
* Deterministic ingestion keys + effective exactly-once processing
* Replay/backfill with lineage-aware auditing (outbox + DLQ aware)

---

# 2. Strategy Research Engine

Build a modular quant research framework.

## Strategy Categories

### Statistical

* Mean reversion
* Momentum
* Pairs trading
* Statistical arbitrage
* Cointegration
* Volatility breakout

### ML-Based

* XGBoost alpha models
* LSTM forecasting
* Transformer sequence models
* Reinforcement learning experimentation
* Regime classification
* Meta-labeling

### Factor Investing

* Value
* Quality
* Momentum
* Low volatility
* Carry
* Size

### Options Strategies

* Iron condors
* Covered calls
* Delta-neutral strategies
* Volatility surface modeling

### Market Microstructure

* Order flow imbalance
* VWAP/TWAP execution
* Slippage prediction
* Liquidity modeling

## Required Features

* Vectorized backtesting
* Event-driven backtesting
* Walk-forward optimization
* Monte Carlo simulations
* Hyperparameter optimization
* Bayesian optimization
* Portfolio simulation
* Factor decomposition
* Survivorship bias mitigation
* Lookahead bias prevention
* Transaction cost modeling
* Slippage modeling
* Latency simulation
* Benchmark comparison
* Strategy versioning
* Experiment tracking

## Metrics

* Sharpe ratio
* Sortino ratio
* Calmar ratio
* Alpha/Beta
* Max drawdown
* VaR/CVaR
* Hit ratio
* Turnover
* Exposure analysis
* Tail risk
* Correlation analysis

---

# 3. AI & Agentic Intelligence Layer

Design a sophisticated multi-agent AI architecture.

Do NOT build a simple chatbot.

This should resemble institutional research automation.

## Agent Types

### Research Agent

* Reads news
* Summarizes filings
* Detects macro themes
* Tracks earnings
* Generates market narratives

### Sentiment Agent

* Performs NLP sentiment analysis
* Uses FinBERT or transformer models
* Detects market fear/greed
* Tracks social sentiment divergence
* Detects narrative shifts

### Strategy Agent

* Suggests new strategy ideas
* Identifies factor exposures
* Detects decaying alpha
* Runs feature importance analysis

### Risk Agent

* Monitors exposures
* Detects anomalous trades
* Flags concentration risk
* Evaluates liquidity stress

### Execution Agent

* Chooses execution algorithms
* Simulates execution quality
* Minimizes slippage

### Portfolio Agent

* Portfolio optimization
* Dynamic rebalancing
* Capital allocation
* Hedging recommendations

### Compliance/Governance Agent

* Audit logging
* Explainability generation
* Prompt/version tracking
* Regulatory reporting support

## Agentic Architecture Expectations

* LangGraph or custom orchestration engine
* Stateful workflows
* Tool calling
* Shared memory
* Retrieval-Augmented Generation (RAG)
* Vector database/RAG integration
* Multi-step reasoning
* Human-in-the-loop approvals
* Agent observability
* Prompt versioning
* Guardrails
* Tool allowlists + output validation (structured JSON schemas)
* Prompt-injection defenses (retrieval isolation, sandboxed tools, PII redaction)
* Cost tracking
* Failure recovery
* Deterministic workflows where required

---

# 4. Sentiment & Alternative Data Intelligence

Build institutional-style alternative data pipelines.

## Sources

* Reddit finance communities
* X/Twitter finance discourse
* Financial news
* YouTube finance transcripts
* SEC filings
* Earnings calls
* Google Trends
* Macro news

## Features

* Sentiment scoring
* Entity extraction
* Topic modeling
* Trend detection
* Event extraction
* Narrative clustering
* Sector sentiment heatmaps
* Insider transaction tracking
* Whale wallet tracking (crypto)
* News impact scoring

## Models

* FinBERT
* Sentence Transformers
* BERTopic
* Llama summarization pipelines
* NER pipelines

---

# 5. Portfolio Management System

Build institutional-style portfolio analytics.

## Features

* Portfolio construction
* Mean-variance optimization
* Black-Litterman optimization
* Risk parity
* Kelly criterion experimentation
* Exposure tracking
* Position sizing
* Dynamic hedging
* Sector constraints
* Risk budgeting
* Correlation clustering
* Stress testing

## Reporting

* PnL attribution
* Exposure reports
* Daily performance reports
* Benchmark tracking
* Factor attribution
* Risk dashboards

---

# 6. Live Trading Infrastructure

Design a safe and production-grade execution layer.

## Features

* Broker integrations
* Paper trading
* Live trading
* Smart order routing
* Execution monitoring
* Kill switches
* Circuit breakers
* Trade reconciliation
* Position reconciliation
* Retry handling
* Order state machines
* Idempotent execution
* Trade journaling

## Risk Controls

* Daily loss limits
* Max exposure caps
* Sector concentration checks
* Volatility halts
* Position limits
* Liquidity filters
* AI confidence thresholds

## Broker Integrations

* [Interactive Brokers](https://www.interactivebrokers.com)
* [Alpaca](https://alpaca.markets)
* [Binance](https://www.binance.com)
* [Zerodha Kite](https://kite.trade)

---

# 7. AI-Powered Daily Recommendation Engine

Generate institutional-style daily trade recommendations.

This system should behave less like a retail stock picker and more like an institutional research and portfolio intelligence workflow.

The recommendation engine must synthesize:

* Quantitative signals
* Macro context
* Cross-asset correlations
* Risk constraints
* Liquidity considerations
* AI-generated research
* Sentiment dynamics
* Portfolio exposures
* Regime classification
* Historical analogs

The system should explicitly separate:

* Signal generation
* Signal ranking
* Portfolio construction
* Execution recommendations
* Human approval

Avoid directly connecting LLM output to live order execution.

## Recommendation System Architecture

### Stage 1 - Data Aggregation

Collect and normalize:

* Intraday and EOD market data
* Technical indicators
* Factor exposures
* Volatility surfaces
* Macro indicators
* Yield curves
* Options flow
* News sentiment
* Social sentiment
* Earnings events
* Economic calendar events
* Sector rotation indicators
* Correlation matrices
* Liquidity metrics
* Volume anomalies
* Insider trading activity
* ETF flows
* Crypto sentiment spillovers

Persist all features into a feature store.

### Stage 2 - Market Regime Detection

Detect current market regime.

Examples:

* Risk-on
* Risk-off
* Inflationary
* Deflationary
* High-volatility
* Mean-reverting
* Trending
* Liquidity crisis
* Earnings-driven
* Macro-driven

Possible techniques:

* Hidden Markov Models
* Clustering
* Bayesian switching models
* Volatility state analysis
* Macro factor decomposition

The detected regime must influence:

* Strategy selection
* Risk budgets
* Position sizing
* Confidence scoring

### Stage 3 - Signal Generation

Generate signals from multiple independent models.

## Technical Signals

* Momentum
* Mean reversion
* RSI divergence
* Breakout detection
* Volatility compression
* Trend strength
* Relative strength

## Statistical Signals

* Cointegration
* Z-score deviations
* Factor dislocations
* Correlation breakdowns
* Volatility regime shifts

## ML Signals

* Return forecasting
* Direction classification
* Regime prediction
* Meta-labeling
* Probability calibration

## NLP/Sentiment Signals

* Earnings tone analysis
* News sentiment acceleration
* Social narrative momentum
* CEO language shifts
* Guidance sentiment changes
* Macro news polarity

## Macro Signals

* Rates trend
* Inflation expectations
* Dollar strength
* Yield curve shifts
* Oil and commodity trends
* Credit spreads

### Stage 4 - Ensemble Intelligence Layer

Combine signals using ensemble methods.

Possible methods:

* Weighted ensembles
* Bayesian model averaging
* Stacking
* Dynamic weighting by regime
* Confidence-weighted blending

The ensemble system should:

* Penalize correlated signals
* Downweight unstable models
* Track signal decay
* Monitor feature drift
* Detect overfitting

Avoid naive averaging.

### Stage 5 - Portfolio Construction

Transform ranked signals into actionable portfolio recommendations.

## Requirements

* Capital allocation
* Position sizing
* Exposure balancing
* Risk parity adjustments
* Correlation constraints
* Sector caps
* Liquidity-aware sizing
* Beta neutrality options
* Volatility targeting

## Optimization Techniques

* Mean-variance optimization
* Black-Litterman
* Convex optimization
* Kelly criterion experimentation
* CVaR optimization

The engine should optimize for:

* Risk-adjusted return
* Drawdown control
* Diversification
* Execution feasibility

### Stage 6 - Risk Validation Layer

Every recommendation must pass institutional-style risk checks.

## Risk Checks

* Max drawdown thresholds
* Exposure concentration
* Position limits
* Volatility spikes
* Liquidity constraints
* Earnings-event proximity
* Macro-event risk
* Correlation spikes
* Portfolio stress tests
* VaR/CVaR limits
* Gap-risk exposure

## Stress Testing

Simulate:

* 2008-style crisis
* COVID crash
* Flash crashes
* Interest-rate shocks
* Oil shocks
* Currency shocks
* Liquidity freezes

The system should reject trades that violate risk tolerances.

### Stage 7 - AI Research & Explainability Layer

Use LLMs for synthesis and explanation.

The AI layer should NEVER be the primary alpha generator.

Its role is:

* Research synthesis
* Narrative extraction
* Context generation
* Explainability
* Analyst augmentation

## AI Outputs

### Daily Market Brief

* Macro summary
* Key risks
* Sector leadership
* Narrative shifts
* Economic calendar highlights

### Trade Thesis

For each recommendation:

* Why the signal triggered
* Supporting evidence
* Contradictory evidence
* Historical analogs
* Risk assumptions
* Time horizon
* Confidence rationale

### Portfolio Commentary

* Exposure summary
* Risk concentration
* Hedge effectiveness
* Regime implications

### Explainable AI Features

* SHAP values
* Feature importance
* Signal attribution
* Model confidence calibration
* Drift explanations

### Stage 8 - Human-in-the-Loop Workflow

Institutional systems rarely allow fully autonomous execution.

Build approval workflows.

## Approval Modes

### Advisory Mode

* Recommendations only
* Human executes manually

### Semi-Automated Mode

* Human approval required
* Risk team signoff

### Fully Automated Sandbox

* Limited capital
* Strict risk controls
* Kill switches enabled

Track:

* Recommendation acceptance rate
* Human overrides
* Override rationale
* Recommendation performance post-override

---

# 8. Frontend & User Experience

Build a modern institutional dashboard.

## Frontend Stack

* Next.js
* TypeScript
* Tailwind
* Recharts/ECharts
* WebSocket streaming

## Dashboard Modules

### Research Terminal

* Market overview
* AI summaries
* News feed
* Signal explorer

### Quant Dashboard

* Strategy metrics
* Backtest visualization
* Risk metrics
* Factor analysis

### Portfolio Dashboard

* Holdings
* Exposure analysis
* Rebalancing suggestions
* Performance attribution

### Trading Dashboard

* Orders
* Execution logs
* Live positions
* PnL monitoring

### AI Copilot

* Natural language queries
* Explain strategy performance
* Generate market briefings
* Portfolio Q&A

---

# 9. Observability & Production Engineering

Design this like a real fintech platform.

## Observability

* OpenTelemetry
* Prometheus
* Grafana
* Structured logging
* Tempo/Jaeger distributed tracing (via OpenTelemetry)
* SLO/SLA monitoring

## Security

* JWT/OAuth2
* RBAC
* Secrets management
* API rate limiting
* Encryption at rest/in transit
* Audit trails

## Reliability

* CI/CD pipelines
* Canary deployments
* Blue/green deployment
* Chaos testing
* Backup/recovery
* High availability

## Infrastructure

* Docker
* Kubernetes
* Terraform
* Helm
* GitHub Actions
* ArgoCD

---

# 10. Critical Engineering Constraints

The design must:

* Be reproducible
* Support deterministic backtesting
* Separate research from production trading
* Prevent leakage/lookahead bias
* Support auditability
* Support explainability
* Handle partial failures gracefully
* Avoid tight coupling between agents
* Be observable end-to-end
* Avoid hidden state corruption

Discuss:

* Tradeoffs between event-driven vs synchronous workflows
* Why vectorized backtests differ from execution reality
* Why most retail quant systems fail in production
* Operational risks of AI-generated signals
* Why latency matters differently across strategies
* Data quality failure modes
* Governance implications of autonomous trading agents

---

# 11. Required Deliverables

Generate:

1. High-level architecture diagram
2. Detailed microservice architecture
3. Database schema design
4. Event-driven workflow diagrams
5. AI agent orchestration diagrams
6. Folder structure
7. API design
8. FastAPI service breakdown
9. Backtesting engine architecture
10. Infrastructure setup
11. Kubernetes deployment strategy
12. CI/CD design
13. Risk management framework
14. Quant research workflow
15. Data engineering workflow
16. Daily recommendation workflow
17. Production readiness checklist
18. Scaling strategy
19. Security architecture
20. Cost optimization strategy
21. Roadmap from MVP to institutional platform
22. Interview talking points
23. Resume bullet points
24. Tradeoff analysis
25. Failure modes and mitigation strategies

---

# Final Instruction

Design the platform like a real institutional system that could plausibly evolve into:

* A quant research startup
* An AI-native fintech platform
* A systematic investing platform
* A market intelligence company
* A hedge fund research stack

Be rigorous.

Be realistic.

Discuss failure modes.

Discuss scaling bottlenecks.

Discuss governance.

Discuss operational constraints.

Prioritize depth over buzzwords.

