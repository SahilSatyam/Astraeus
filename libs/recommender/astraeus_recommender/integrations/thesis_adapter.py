"""Adapter bridging Phase 7 thesis stage to Phase 6 agent runtime.

Uses the WorkflowOrchestrator to run the 'trade_thesis' workflow
for each recommendation that passes risk validation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog

if TYPE_CHECKING:
    from astraeus_agent_runtime.orchestrator import WorkflowOrchestrator


logger = structlog.get_logger("astraeus.recommender.integrations.thesis")


class ThesisResult:
    """Result from thesis generation via Phase 6."""

    def __init__(
        self,
        run_id: UUID | None = None,
        summary: str = "",
        citations: list[str] | None = None,
    ) -> None:
        self.run_id = run_id
        self.summary = summary
        self.citations = citations or []


class ThesisGeneratorAdapter:
    """Bridges Phase 7 to Phase 6 agent runtime for thesis generation.

    Calls the 'trade_thesis' workflow for each ticker, extracting
    the research summary and citations from the agent output.
    """

    def __init__(
        self,
        orchestrator: WorkflowOrchestrator | None = None,
        max_cost_per_thesis: float = 0.05,
        timeout_s: int = 30,
    ) -> None:
        self._orchestrator = orchestrator
        self._max_cost = max_cost_per_thesis
        self._timeout_s = timeout_s

    async def generate_thesis(
        self,
        ticker: str,
        side: str,
        weight: float,
    ) -> ThesisResult:
        """Generate a thesis for a single recommendation.

        Args:
            ticker: Symbol to generate thesis for.
            side: Trade direction (long/short/flat).
            weight: Target portfolio weight.

        Returns:
            ThesisResult with run_id, summary, and citations.
        """
        if self._orchestrator is None:
            logger.warning("thesis_no_orchestrator", ticker=ticker)
            return ThesisResult(
                summary=f"Thesis pending — agent runtime not configured. "
                f"{side.upper()} {ticker} at {weight:.1%} weight.",
            )

        try:
            result = await self._orchestrator.run_workflow(
                workflow="trade_thesis",
                inputs={
                    "ticker": ticker,
                    "focus": f"{side} position, target weight {weight:.2%}",
                    "lookback_days": 30,
                },
                options={
                    "max_cost_usd": self._max_cost,
                    "timeout_s": self._timeout_s,
                    "channel": "promoted",
                },
            )

            # Extract thesis from workflow output
            run_id_str = result.get("run_id")
            run_id = UUID(run_id_str) if run_id_str else uuid4()

            output = result.get("output", {})
            research = output.get("research", {})

            summary = research.get("summary", "")
            citations = research.get("citations", [])

            if not summary and output:
                # Fallback: use any available text
                summary = str(output.get("summary", ""))[:500]

            return ThesisResult(
                run_id=run_id,
                summary=summary,
                citations=citations,
            )

        except Exception as e:
            logger.warning(
                "thesis_generation_failed",
                ticker=ticker,
                error=str(e),
            )
            return ThesisResult(
                summary=f"Thesis generation failed: {e}",
            )
