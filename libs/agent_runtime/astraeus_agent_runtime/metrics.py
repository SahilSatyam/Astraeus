"""Prometheus metrics for the agent runtime.

Exposes counters, histograms, and gauges for:
- Run completions by workflow and status
- Agent step latency and cost
- LLM call latency, tokens, and cost by model
- Tool call latency by tool name
- HITL queue depth and resolution rate
- Budget alerts (per-agent, per-workflow, daily caps)
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("astraeus.agent_runtime.metrics")

try:
    from prometheus_client import Counter, Gauge, Histogram

    # --- Run-level metrics ---
    RUNS_TOTAL = Counter(
        "agent_runs_total",
        "Total agent workflow runs",
        ["workflow_key", "status"],
    )
    RUN_DURATION_MS = Histogram(
        "agent_run_duration_ms",
        "Workflow run duration in milliseconds",
        ["workflow_key"],
        buckets=[500, 1000, 2000, 5000, 10000, 30000, 60000, 120000],
    )
    RUN_COST_USD = Histogram(
        "agent_run_cost_usd",
        "Workflow run cost in USD",
        ["workflow_key"],
        buckets=[0.01, 0.05, 0.10, 0.25, 0.50, 1.0, 2.0, 5.0],
    )

    # --- Agent step metrics ---
    STEP_DURATION_MS = Histogram(
        "agent_step_duration_ms",
        "Agent step duration in milliseconds",
        ["agent_name"],
        buckets=[100, 500, 1000, 2000, 5000, 10000, 30000],
    )

    # --- LLM call metrics ---
    LLM_CALLS_TOTAL = Counter(
        "agent_llm_calls_total",
        "Total LLM calls",
        ["agent_name", "model", "status"],
    )
    LLM_LATENCY_MS = Histogram(
        "agent_llm_latency_ms",
        "LLM call latency in milliseconds",
        ["model"],
        buckets=[200, 500, 1000, 2000, 5000, 10000, 30000],
    )
    LLM_TOKENS_INPUT = Counter(
        "agent_llm_tokens_input_total",
        "Total input tokens consumed",
        ["model"],
    )
    LLM_TOKENS_OUTPUT = Counter(
        "agent_llm_tokens_output_total",
        "Total output tokens generated",
        ["model"],
    )
    LLM_COST_USD = Counter(
        "agent_llm_cost_usd_total",
        "Total LLM cost in USD",
        ["agent_name", "model"],
    )
    LLM_CACHE_HIT_RATE = Gauge(
        "agent_llm_cache_hit_rate",
        "Prompt cache hit rate (0-1)",
        ["model"],
    )

    # --- Tool call metrics ---
    TOOL_CALLS_TOTAL = Counter(
        "agent_tool_calls_total",
        "Total tool calls",
        ["agent_name", "tool_name", "status"],
    )
    TOOL_LATENCY_MS = Histogram(
        "agent_tool_latency_ms",
        "Tool call latency in milliseconds",
        ["tool_name"],
        buckets=[10, 50, 100, 500, 1000, 5000],
    )

    # --- HITL metrics ---
    HITL_QUEUE_DEPTH = Gauge(
        "agent_hitl_queue_depth",
        "Current HITL queue depth",
        ["status"],
    )
    HITL_ITEMS_TOTAL = Counter(
        "agent_hitl_items_total",
        "Total HITL items submitted",
        ["trigger", "workflow_key"],
    )

    # --- Budget metrics ---
    BUDGET_ALERTS_TOTAL = Counter(
        "agent_budget_alerts_total",
        "Budget alert firings",
        ["level", "scope"],  # level: soft/hard, scope: agent/workflow/daily
    )

    _METRICS_AVAILABLE = True

except ImportError:
    _METRICS_AVAILABLE = False
    logger.info("prometheus_client_not_available", msg="Metrics disabled")


def record_run_complete(run_result: dict[str, Any]) -> None:
    """Record metrics for a completed workflow run."""
    if not _METRICS_AVAILABLE:
        return

    workflow = run_result.get("workflow_key", "unknown")
    status = run_result.get("status", "unknown")
    cost = run_result.get("cost_usd", 0.0)
    duration = run_result.get("duration_ms", 0.0)

    RUNS_TOTAL.labels(workflow_key=workflow, status=status).inc()
    RUN_DURATION_MS.labels(workflow_key=workflow).observe(duration)
    RUN_COST_USD.labels(workflow_key=workflow).observe(cost)


def record_step_complete(agent_name: str, duration_ms: float) -> None:
    """Record metrics for a completed agent step."""
    if not _METRICS_AVAILABLE:
        return
    STEP_DURATION_MS.labels(agent_name=agent_name).observe(duration_ms)


def record_llm_call(
    agent_name: str,
    model: str,
    status: str,
    latency_ms: float,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    cache_read_tokens: int = 0,
) -> None:
    """Record metrics for an LLM call."""
    if not _METRICS_AVAILABLE:
        return

    LLM_CALLS_TOTAL.labels(agent_name=agent_name, model=model, status=status).inc()
    LLM_LATENCY_MS.labels(model=model).observe(latency_ms)
    LLM_TOKENS_INPUT.labels(model=model).inc(input_tokens)
    LLM_TOKENS_OUTPUT.labels(model=model).inc(output_tokens)
    LLM_COST_USD.labels(agent_name=agent_name, model=model).inc(cost_usd)

    # Cache hit rate
    if input_tokens > 0:
        hit_rate = cache_read_tokens / input_tokens
        LLM_CACHE_HIT_RATE.labels(model=model).set(hit_rate)


def record_tool_call(agent_name: str, tool_name: str, status: str, latency_ms: float) -> None:
    """Record metrics for a tool call."""
    if not _METRICS_AVAILABLE:
        return
    TOOL_CALLS_TOTAL.labels(agent_name=agent_name, tool_name=tool_name, status=status).inc()
    TOOL_LATENCY_MS.labels(tool_name=tool_name).observe(latency_ms)


def record_hitl_submit(trigger: str, workflow_key: str) -> None:
    """Record a HITL item submission."""
    if not _METRICS_AVAILABLE:
        return
    HITL_ITEMS_TOTAL.labels(trigger=trigger, workflow_key=workflow_key).inc()


def record_budget_alert(level: str, scope: str) -> None:
    """Record a budget alert firing."""
    if not _METRICS_AVAILABLE:
        return
    BUDGET_ALERTS_TOTAL.labels(level=level, scope=scope).inc()
