"""Portfolio agent — reads current portfolio state, explains exposures."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from astraeus_agent_runtime.agents.base import AgentSpec, BaseAgent
from astraeus_agent_runtime.schemas import PortfolioCommentary
from astraeus_agent_runtime.tools.registry import dispatch_tool

logger = structlog.get_logger("astraeus.agent_runtime.agents.portfolio")

PORTFOLIO_SPEC = AgentSpec(
    name="portfolio",
    prompt_key="portfolio_agent.system",
    output_schema=PortfolioCommentary,
    allowed_tools=frozenset(
        {
            "get_portfolio_state",
            "get_exposure_breakdown",
            "get_factor_attribution",
            "get_optimizer_suggestion",
        }
    ),
    model_tier="synthesis",
)


class PortfolioAgent(BaseAgent):
    """Portfolio agent — explains exposures and optimizer-suggested rebalances."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(spec=PORTFOLIO_SPEC, **kwargs)

    async def execute(
        self,
        state: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Execute portfolio commentary."""
        portfolio_id = state.get("metadata", {}).get("portfolio_id", "default")
        as_of = datetime.now(tz=UTC)

        # Step 1: Get portfolio state
        portfolio_data = await self._get_state(portfolio_id, run_id)

        # Step 2: Get exposure breakdown
        exposures = await self._get_exposures(portfolio_id, run_id)

        # Step 3: Call LLM for narrative
        system_prompt = await self._get_system_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Provide portfolio commentary for: {portfolio_id}\n\n"
                    f"Portfolio state:\n{_format_portfolio(portfolio_data)}\n\n"
                    f"Exposure breakdown:\n{_format_exposures(exposures)}\n\n"
                    "Explain current exposures, highlight concentration risks, "
                    "and describe any optimizer-suggested rebalances."
                ),
            }
        ]

        result = await self._call_llm(messages=messages, system=system_prompt, run_id=run_id)

        if "error" not in result:
            result.setdefault("as_of", as_of.isoformat())
            if portfolio_data:
                result.setdefault("total_value", portfolio_data.get("total_value"))

        return result

    async def _get_state(self, portfolio_id: str, run_id: uuid.UUID | None) -> dict[str, Any]:
        try:
            return await dispatch_tool(
                agent_name="portfolio",
                tool_name="get_portfolio_state",
                payload={"portfolio_id": portfolio_id},
                run_id=run_id,
            )
        except Exception as e:
            logger.warning("portfolio_state_failed", error=str(e))
            return {}

    async def _get_exposures(self, portfolio_id: str, run_id: uuid.UUID | None) -> dict[str, Any]:
        try:
            return await dispatch_tool(
                agent_name="portfolio",
                tool_name="get_exposure_breakdown",
                payload={"portfolio_id": portfolio_id},
                run_id=run_id,
            )
        except Exception as e:
            logger.warning("portfolio_exposures_failed", error=str(e))
            return {}


def _format_portfolio(data: dict[str, Any]) -> str:
    if not data:
        return "No portfolio data available."
    total = data.get("total_value", 0)
    positions = data.get("positions", [])
    lines = [f"Total value: ${total:,.2f}", f"Positions: {len(positions)}"]
    for p in positions[:10]:
        lines.append(
            f"  - {p.get('ticker', '?')}: {p.get('weight', 0):.1%} (${p.get('market_value', 0):,.0f})"
        )
    return "\n".join(lines)


def _format_exposures(data: dict[str, Any]) -> str:
    if not data:
        return "No exposure data available."
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for k, v in value.items():
                lines.append(f"  {k}: {v}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) if lines else "No breakdown available."
