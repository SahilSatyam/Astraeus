"""Research agent — synthesizes narrative context for a ticker or theme."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from astraeus_agent_runtime.agents.base import AgentSpec, BaseAgent
from astraeus_agent_runtime.guardrails import sandbox_retrieved_content
from astraeus_agent_runtime.schemas import ResearchOutput
from astraeus_agent_runtime.tools.registry import dispatch_tool

logger = structlog.get_logger("astraeus.agent_runtime.agents.research")

RESEARCH_SPEC = AgentSpec(
    name="research",
    prompt_key="research_agent.system",
    output_schema=ResearchOutput,
    allowed_tools=frozenset({
        "search_news", "fetch_filing", "search_filing_chunks",
        "get_macro_indicator", "get_earnings_calendar",
    }),
    model_tier="reasoning",
)


class ResearchAgent(BaseAgent):
    """Research agent — produces cited findings for a ticker."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(spec=RESEARCH_SPEC, **kwargs)

    async def execute(
        self,
        state: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Execute research synthesis for the given ticker."""
        ticker = state.get("ticker", "")
        lookback_days = state.get("lookback_days", 30)
        focus = state.get("focus", "")

        # Step 1: Gather context via tools
        news_results = await self._search_news(ticker, lookback_days, focus, run_id)
        filing_results = await self._fetch_filings(ticker, run_id)

        # Step 2: Build retrieval context with sandboxing
        chunks = []
        for item in news_results:
            chunks.append({
                "source": item.get("source", "news"),
                "chunk_id": item.get("chunk_id", ""),
                "text": item.get("text", ""),
            })
        for item in filing_results:
            chunks.append({
                "source": "edgar",
                "chunk_id": item.get("chunk_id", ""),
                "text": item.get("text", ""),
            })

        sandboxed_context = sandbox_retrieved_content(chunks)

        # Step 3: Call LLM with structured output
        system_prompt = await self._get_system_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Research ticker: {ticker}\n"
                    f"Lookback: {lookback_days} days\n"
                    f"Focus: {focus or 'general'}\n\n"
                    f"{sandboxed_context}"
                ),
            }
        ]

        result = await self._call_llm(
            messages=messages,
            system=system_prompt,
            run_id=run_id,
        )

        # Ensure ticker and as_of are set
        if "error" not in result:
            result.setdefault("ticker", ticker)
            result.setdefault("as_of", datetime.now(tz=UTC).isoformat())

        return result

    async def _search_news(
        self, ticker: str, lookback_days: int, focus: str, run_id: uuid.UUID | None
    ) -> list[dict[str, Any]]:
        """Search news via the tool dispatcher."""
        query = f"{ticker} {focus}".strip() if focus else ticker
        try:
            response = await dispatch_tool(
                agent_name="research",
                tool_name="search_news",
                payload={"query": query, "ticker": ticker, "lookback_days": lookback_days, "top_k": 10},
                run_id=run_id,
            )
            return response.get("results", [])
        except Exception as e:
            logger.warning("research_news_search_failed", error=str(e))
            return []

    async def _fetch_filings(
        self, ticker: str, run_id: uuid.UUID | None
    ) -> list[dict[str, Any]]:
        """Fetch recent filings via the tool dispatcher."""
        try:
            response = await dispatch_tool(
                agent_name="research",
                tool_name="fetch_filing",
                payload={"ticker": ticker, "filing_type": "10-K"},
                run_id=run_id,
            )
            return response.get("chunks", [])
        except Exception as e:
            logger.warning("research_filing_fetch_failed", error=str(e))
            return []
