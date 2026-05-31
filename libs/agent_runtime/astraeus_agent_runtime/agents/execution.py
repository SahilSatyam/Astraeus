"""Execution agent — Phase 6 stub returning advisory-only output.

This agent exists only to DESCRIBE execution preferences for human review.
It does NOT call brokers. It does NOT place orders. The `requires_human_execution`
field is always True.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from astraeus_agent_runtime.agents.base import AgentSpec, BaseAgent
from astraeus_agent_runtime.schemas import ExecutionAdvice
from astraeus_agent_runtime.tools.registry import dispatch_tool

logger = structlog.get_logger("astraeus.agent_runtime.agents.execution")

EXECUTION_SPEC = AgentSpec(
    name="execution",
    prompt_key="execution_agent.system",
    output_schema=ExecutionAdvice,
    allowed_tools=frozenset(
        {
            "get_liquidity_metrics",
            "get_volatility_estimate",
        }
    ),
    model_tier="classification",
    max_retries=1,  # Simple output, fewer retries needed
)


class ExecutionAgent(BaseAgent):
    """Execution agent — advisory only. No order tools. Always requires human."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(spec=EXECUTION_SPEC, **kwargs)

    async def execute(
        self,
        state: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Return execution advice (algo selection) for human review."""
        ticker = state.get("ticker", "")

        # Step 1: Get liquidity/volatility context
        liquidity = await self._get_liquidity(ticker, run_id)
        volatility = await self._get_volatility(ticker, run_id)

        # Step 2: Call LLM for algo recommendation
        system_prompt = await self._get_system_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Recommend execution algorithm for trading: {ticker}\n\n"
                    f"Liquidity metrics: {liquidity}\n"
                    f"Volatility estimate: {volatility}\n\n"
                    "Select the best algo (TWAP, VWAP, IS, POV, MARKET) and parameters. "
                    "Remember: requires_human_execution is ALWAYS True."
                ),
            }
        ]

        result = await self._call_llm(messages=messages, system=system_prompt, run_id=run_id)

        # Force requires_human_execution = True regardless of LLM output
        if "error" not in result:
            result["requires_human_execution"] = True

        return result

    async def _get_liquidity(self, ticker: str, run_id: uuid.UUID | None) -> dict[str, Any]:
        try:
            return await dispatch_tool(
                agent_name="execution",
                tool_name="get_liquidity_metrics",
                payload={"ticker": ticker},
                run_id=run_id,
            )
        except Exception as e:
            logger.warning("execution_liquidity_failed", error=str(e))
            return {"adv_20d": None, "spread_bps": None}

    async def _get_volatility(self, ticker: str, run_id: uuid.UUID | None) -> dict[str, Any]:
        try:
            return await dispatch_tool(
                agent_name="execution",
                tool_name="get_volatility_estimate",
                payload={"ticker": ticker},
                run_id=run_id,
            )
        except Exception as e:
            logger.warning("execution_volatility_failed", error=str(e))
            return {"realized_vol_20d": None, "implied_vol": None}
