"""Sentiment agent — wraps Phase 5 sentiment features with narrative layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from astraeus_agent_runtime.agents.base import AgentSpec, BaseAgent
from astraeus_agent_runtime.guardrails import sandbox_retrieved_content
from astraeus_agent_runtime.schemas import SentimentNarrative
from astraeus_agent_runtime.tools.registry import dispatch_tool

logger = structlog.get_logger("astraeus.agent_runtime.agents.sentiment")

SENTIMENT_SPEC = AgentSpec(
    name="sentiment",
    prompt_key="sentiment_agent.system",
    output_schema=SentimentNarrative,
    allowed_tools=frozenset({
        "get_sentiment_features", "search_news", "search_social_posts", "get_event_study",
    }),
    model_tier="synthesis",
)


class SentimentAgent(BaseAgent):
    """Sentiment agent — explains WHY sentiment moved, never computes it."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(spec=SENTIMENT_SPEC, **kwargs)

    async def execute(
        self,
        state: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Execute sentiment narrative for the given ticker."""
        ticker = state.get("ticker", "")
        lookback_days = state.get("lookback_days", 30)
        as_of = datetime.now(tz=UTC)

        # Step 1: Get pre-computed sentiment features
        sentiment_data = await self._get_sentiment(ticker, as_of, lookback_days, run_id)

        # Step 2: Search for supporting news
        news_results = await self._search_supporting_news(ticker, lookback_days, run_id)

        # Step 3: Build context
        chunks = [
            {"source": item.get("source", "news"), "chunk_id": item.get("chunk_id", ""), "text": item.get("text", "")}
            for item in news_results
        ]
        sandboxed_context = sandbox_retrieved_content(chunks) if chunks else ""

        # Step 4: Call LLM
        system_prompt = await self._get_system_prompt()
        score_info = ""
        if sentiment_data:
            score_info = (
                f"Pre-computed sentiment score: {sentiment_data.get('daily_score', 'N/A')}\n"
                f"5-day MA: {sentiment_data.get('ma5', 'N/A')}\n"
                f"Dispersion: {sentiment_data.get('dispersion', 'N/A')}\n"
                f"Document count: {sentiment_data.get('doc_count', 'N/A')}\n"
            )

        messages = [
            {
                "role": "user",
                "content": (
                    f"Analyze sentiment for: {ticker}\n"
                    f"Lookback: {lookback_days} days\n\n"
                    f"FEATURE STORE DATA (pre-computed, do NOT recompute):\n{score_info}\n"
                    f"{sandboxed_context}"
                ),
            }
        ]

        result = await self._call_llm(messages=messages, system=system_prompt, run_id=run_id)

        if "error" not in result:
            result.setdefault("ticker", ticker)
            result.setdefault("as_of", as_of.isoformat())
            if sentiment_data:
                result.setdefault("score", sentiment_data.get("daily_score"))

        return result

    async def _get_sentiment(
        self, ticker: str, as_of: datetime, lookback_days: int, run_id: uuid.UUID | None
    ) -> dict[str, Any]:
        try:
            return await dispatch_tool(
                agent_name="sentiment",
                tool_name="get_sentiment_features",
                payload={"ticker": ticker, "as_of": as_of.isoformat(), "lookback_days": lookback_days},
                run_id=run_id,
            )
        except Exception as e:
            logger.warning("sentiment_features_failed", error=str(e))
            return {}

    async def _search_supporting_news(
        self, ticker: str, lookback_days: int, run_id: uuid.UUID | None
    ) -> list[dict[str, Any]]:
        try:
            response = await dispatch_tool(
                agent_name="sentiment",
                tool_name="search_news",
                payload={"query": ticker, "ticker": ticker, "lookback_days": lookback_days, "top_k": 8},
                run_id=run_id,
            )
            return response.get("results", [])
        except Exception as e:
            logger.warning("sentiment_news_search_failed", error=str(e))
            return []
