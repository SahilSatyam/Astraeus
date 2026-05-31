"""Agent run state — the shared state graph for LangGraph orchestration.

The state is a TypedDict that flows through the LangGraph state graph.
Each agent node reads its slice and appends its output.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class RunMetadata(BaseModel):
    """Metadata for a single agent run."""

    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    workflow_key: str = ""
    ticker: str | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    channel: str = "promoted"  # prompt registry channel
    max_cost_usd: float = 1.0
    timeout_s: int = 120
    mode: str = "production"  # production | eval


class AgentState(TypedDict, total=False):
    """LangGraph state flowing through the orchestration graph.

    Each agent reads what it needs and appends its output key.
    """

    # --- Inputs ---
    metadata: dict[str, Any]
    ticker: str
    lookback_days: int
    focus: str

    # --- Agent outputs (appended by each node) ---
    research_output: dict[str, Any]
    sentiment_output: dict[str, Any]
    strategy_output: dict[str, Any]
    risk_output: dict[str, Any]
    portfolio_output: dict[str, Any]
    execution_output: dict[str, Any]
    compliance_output: dict[str, Any]

    # --- Orchestrator bookkeeping ---
    steps: list[dict[str, Any]]
    total_cost_usd: float
    total_duration_ms: float
    hitl_required: bool
    hitl_reason: str
    error: str
    status: str  # running | completed | hitl_pending | failed
