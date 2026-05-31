"""Tool registry and dispatcher.

The dispatcher is the ONLY path to a tool. Tools are not importable
into agent code directly. Allowlist enforcement happens here.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger("astraeus.agent_runtime.tools")


class ToolNotAllowed(Exception):
    """Raised when an agent attempts to call a tool not in its allowlist."""

    def __init__(self, agent_name: str, tool_name: str) -> None:
        self.agent_name = agent_name
        self.tool_name = tool_name
        super().__init__(f"Agent {agent_name!r} is not allowed to call tool {tool_name!r}")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A registered tool with its schema and implementation."""

    name: str
    description: str
    version: str = "1.0.0"
    request_model: type[BaseModel] | None = None
    response_model: type[BaseModel] | None = None
    fn: Callable[..., Awaitable[Any]] | Callable[..., Any] | None = None
    read_only: bool = True  # All tools read-only in Phase 6


@dataclass(slots=True)
class ToolCallRecord:
    """Record of a tool invocation for the trace store."""

    call_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID | None = None
    step_id: uuid.UUID | None = None
    agent_name: str = ""
    tool_name: str = ""
    tool_version: str = ""
    request_hash: str = ""
    response_hash: str = ""
    latency_ms: float = 0.0
    status: str = "success"
    error: str | None = None


# Global tool registry
TOOL_REGISTRY: dict[str, ToolDefinition] = {}

# Agent → allowed tool names
AGENT_TOOL_ALLOWLISTS: dict[str, set[str]] = {
    "research": {
        "search_news",
        "fetch_filing",
        "search_filing_chunks",
        "get_macro_indicator",
        "get_earnings_calendar",
    },
    "sentiment": {
        "get_sentiment_features",
        "search_news",
        "search_social_posts",
        "get_event_study",
    },
    "strategy": {
        "query_strategy_registry",
        "get_strategy_signal",
        "get_factor_exposure",
        "get_backtest_metrics",
    },
    "risk": {
        "get_portfolio_state",
        "run_risk_check",
        "run_stress_scenario",
        "get_correlation_matrix",
        "get_var_cvar",
    },
    "portfolio": {
        "get_portfolio_state",
        "get_exposure_breakdown",
        "get_factor_attribution",
        "get_optimizer_suggestion",
    },
    "execution": {
        "get_liquidity_metrics",
        "get_volatility_estimate",
    },
    "compliance": {
        "lookup_restricted_list",
        "lookup_policy_rule",
        "write_audit_envelope",
    },
}


def register_tool(tool: ToolDefinition) -> None:
    """Register a tool in the global registry."""
    TOOL_REGISTRY[tool.name] = tool
    logger.info("tool_registered", name=tool.name, version=tool.version)


async def dispatch_tool(
    agent_name: str,
    tool_name: str,
    payload: dict[str, Any],
    run_id: uuid.UUID | None = None,
    step_id: uuid.UUID | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch a tool call with allowlist enforcement.

    This is the ONLY path to execute a tool. Agents cannot call tools directly.

    Args:
        agent_name: The agent requesting the tool.
        tool_name: The tool to invoke.
        payload: Tool input parameters.
        run_id: Parent run ID for tracing.
        step_id: Parent step ID for tracing.
        context: Additional context (e.g., session, settings).

    Returns:
        Tool response as a dict.

    Raises:
        ToolNotAllowed: If the agent is not permitted to use this tool.
        KeyError: If the tool is not registered.
    """
    # Allowlist enforcement
    allowed = AGENT_TOOL_ALLOWLISTS.get(agent_name, set())
    if tool_name not in allowed:
        logger.warning(
            "tool_not_allowed",
            agent=agent_name,
            tool=tool_name,
        )
        raise ToolNotAllowed(agent_name, tool_name)

    # Tool lookup
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise KeyError(f"Tool {tool_name!r} not registered")

    if tool.fn is None:
        raise RuntimeError(f"Tool {tool_name!r} has no implementation")

    # Validate input
    request = None
    if tool.request_model:
        request = tool.request_model.model_validate(payload)

    # Execute
    start = time.perf_counter()
    try:
        import asyncio

        if asyncio.iscoroutinefunction(tool.fn):
            if request:
                result = await tool.fn(request, **(context or {}))
            else:
                result = await tool.fn(**(context or {}))
        elif request:
            result = tool.fn(request, **(context or {}))
        else:
            result = tool.fn(**(context or {}))
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "tool_call_error",
            agent=agent_name,
            tool=tool_name,
            error=str(e),
            latency_ms=round(latency_ms, 1),
        )
        raise

    latency_ms = (time.perf_counter() - start) * 1000

    # Validate output
    if tool.response_model and isinstance(result, BaseModel):
        response_dict = result.model_dump()
    elif isinstance(result, dict):
        response_dict = result
    else:
        response_dict = {"result": result}

    logger.info(
        "tool_call_complete",
        agent=agent_name,
        tool=tool_name,
        version=tool.version,
        latency_ms=round(latency_ms, 1),
    )

    return response_dict
