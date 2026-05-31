"""Strategy agent — reads strategy registry, identifies decay/themes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from astraeus_agent_runtime.agents.base import AgentSpec, BaseAgent
from astraeus_agent_runtime.schemas import StrategyOutput
from astraeus_agent_runtime.tools.registry import dispatch_tool

logger = structlog.get_logger("astraeus.agent_runtime.agents.strategy")

STRATEGY_SPEC = AgentSpec(
    name="strategy",
    prompt_key="strategy_agent.system",
    output_schema=StrategyOutput,
    allowed_tools=frozenset({
        "query_strategy_registry", "get_strategy_signal", "get_factor_exposure",
        "get_backtest_metrics",
    }),
    model_tier="reasoning",
)


class StrategyAgent(BaseAgent):
    """Strategy agent — surfaces relevant strategies, describes thesis fit, flags decay."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(spec=STRATEGY_SPEC, **kwargs)

    async def execute(
        self,
        state: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Execute strategy analysis for the given ticker."""
        ticker = state.get("ticker", "")
        as_of = datetime.now(tz=UTC)

        # Step 1: Query strategy registry for relevant strategies
        strategies = await self._query_strategies(ticker, run_id)

        # Step 2: Get signals for matched strategies
        signals = await self._get_signals(strategies, run_id)

        # Step 3: Call LLM for narrative synthesis
        system_prompt = await self._get_system_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Analyze strategy fit for ticker: {ticker}\n\n"
                    f"Matched strategies from registry:\n{_format_strategies(strategies)}\n\n"
                    f"Current signals:\n{_format_signals(signals)}\n\n"
                    "Identify which strategies fit this ticker, flag any showing decay, "
                    "and describe thematic connections."
                ),
            }
        ]

        result = await self._call_llm(messages=messages, system=system_prompt, run_id=run_id)

        if "error" not in result:
            result.setdefault("ticker", ticker)
            result.setdefault("as_of", as_of.isoformat())

        return result

    async def _query_strategies(
        self, ticker: str, run_id: uuid.UUID | None
    ) -> list[dict[str, Any]]:
        try:
            response = await dispatch_tool(
                agent_name="strategy",
                tool_name="query_strategy_registry",
                payload={"ticker": ticker},
                run_id=run_id,
            )
            return response.get("strategies", [])
        except Exception as e:
            logger.warning("strategy_query_failed", error=str(e))
            return []

    async def _get_signals(
        self, strategies: list[dict[str, Any]], run_id: uuid.UUID | None
    ) -> list[dict[str, Any]]:
        signals = []
        for strat in strategies[:5]:  # Cap at 5 to limit tool calls
            try:
                response = await dispatch_tool(
                    agent_name="strategy",
                    tool_name="get_strategy_signal",
                    payload={"strategy_id": strat.get("strategy_id", "")},
                    run_id=run_id,
                )
                signals.append(response)
            except Exception as e:
                logger.warning("strategy_signal_failed", strategy=strat.get("strategy_id"), error=str(e))
        return signals


def _format_strategies(strategies: list[dict[str, Any]]) -> str:
    if not strategies:
        return "No strategies matched."
    lines = []
    for s in strategies:
        lines.append(f"- {s.get('strategy_id', 'unknown')} v{s.get('version', '?')}: {s.get('description', '')}")
    return "\n".join(lines)


def _format_signals(signals: list[dict[str, Any]]) -> str:
    if not signals:
        return "No signals available."
    lines = []
    for s in signals:
        lines.append(f"- {s.get('strategy_id', '?')}: signal={s.get('signal', 'N/A')}, as_of={s.get('as_of', '?')}")
    return "\n".join(lines)
