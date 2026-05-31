# Astraeus Agent Runtime — Phase 6

Multi-agent orchestration layer producing cited, schema-valid research artifacts.

## North Star

> Agents augment analysts. Agents never autonomously trade. No agent has order tools.

## Architecture

```
POST /agents/runs → WorkflowOrchestrator
                        │
                        ├─ Research Agent (search_news, fetch_filing)
                        ├─ Sentiment Agent (get_sentiment_features, search_news)
                        ├─ Strategy Agent (query_strategy_registry, get_strategy_signal)
                        ├─ Risk Agent (run_risk_check, get_portfolio_state)
                        ├─ Portfolio Agent (get_exposure_breakdown, get_optimizer_suggestion)
                        ├─ Execution Agent (get_liquidity_metrics — advisory only)
                        └─ Compliance Agent (lookup_restricted_list — final gate)
                                │
                                ▼
                        Schema-valid output + run trace + cost ledger
```

## Workflows

| Workflow | Agents | Use Case |
|----------|--------|----------|
| `trade_thesis` | Research → Sentiment → Strategy → Risk → Compliance | Full thesis for a ticker |
| `daily_brief` | Research → Sentiment → Risk → Compliance | Daily market summary |
| `portfolio_commentary` | Sentiment → Strategy → Risk → Portfolio → Compliance | Portfolio review |
| `risk_drilldown` | Risk → Portfolio → Compliance | Deep risk analysis |

## API Contract (for Phase 7 + Phase 9)

```http
POST /agents/runs
{
  "workflow": "trade_thesis",
  "inputs": {"ticker": "AAPL", "lookback_days": 30, "focus": "services growth"},
  "options": {"channel": "promoted", "max_cost_usd": 0.50, "timeout_s": 60}
}
→ 202 {"run_id": "...", "status_url": "/agents/runs/{run_id}"}

GET /agents/runs/{run_id}
→ {"run_id": "...", "status": "completed", "output": {...}, "cost_usd": 0.31, "duration_ms": 24210}

GET /agents/runs/{run_id}/trace
→ {"run_id": "...", "steps": [...], "total_cost_usd": 0.31}
```

## HITL Queue

Any agent can trigger HITL (risk breach, compliance flag, cost overrun).
Items flow: `pending → claimed → approved | rejected | edited`.

```http
GET  /hitl/items?status=pending
POST /hitl/items/{id}/claim    {"claimed_by": "<reviewer_uuid>"}
POST /hitl/items/{id}/approve
POST /hitl/items/{id}/reject?reason=...
POST /hitl/items/{id}/edit     {"edited_output": {...}}
```

## Output Schema Versioning

All outputs are Pydantic models with `schema_version` field. Breaking changes
bump the version (v1 → v2). Phase 7 and Phase 9 declare which versions they accept.

Key schemas: `ResearchOutput`, `SentimentNarrative`, `StrategyOutput`,
`RiskAssessment`, `ExecutionAdvice`, `PortfolioCommentary`, `ComplianceResult`,
`TradeThesisOutput`, `DailyBriefOutput`.

## Guardrails

1. **Input**: PII redaction + prompt-injection detection (regex + classifier)
2. **Retrieval**: `<untrusted_data>` sandboxing — retrieved content never in system role
3. **Output**: Schema validation, citation validation (high/medium confidence → ≥1 citation)

## Prompt Registry

Prompts versioned in `prompts/*.yaml`. Lifecycle: `draft → candidate → promoted → retired`.
Promotion requires passing eval suite. Runtime resolves by channel (`promoted` default).

## Cost Tracking

Every LLM call recorded with input/output tokens, cache hits, and USD cost.
Budget caps: per-run, per-agent, per-workflow. Circuit-break at 100% of cap.

## Eval Suite

- **Golden tasks**: 5 curated regression tests (AAPL thesis, TSLA sentiment, daily brief, etc.)
- **Faithfulness**: Claim → citation grounding (≥90% entailed)
- **Injection battery**: 50 adversarial inputs (≥95% detected)

## Runbook

**Queue stuck**: Check `/hitl/items?status=pending`. Expired items auto-resolve after 24h TTL.

**Cost overrun**: Run terminates with `status=failed`, `error=Cost overrun: $X > $Y`.
Check `agent_llm_cost_usd_total` metric. Adjust `max_cost_usd` in run options.

**Model outage**: LLM client retries 2x with exponential backoff. On exhaustion,
step fails and run terminates. No automatic fallback to different model tier.
