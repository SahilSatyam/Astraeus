"""Stage 7: Thesis Generation — thin wrapper on Phase 6 AI agents.

Generates an AI explanation with citations for each recommendation.
A failure here marks the run as degraded, not failed — recommendations
are still available without thesis text.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

import structlog

from ..contracts import PortfolioAllocation, RiskValidationOutput, ThesisOutput

logger = structlog.get_logger("astraeus.recommender.stages.thesis")


class ThesisStage:
    """Stage 7: AI thesis generation per recommendation.

    Wraps the Phase 6 agent runtime to produce explanations.
    Failures are graceful — a missing thesis doesn't block the recommendation.
    """

    def __init__(
        self,
        agent_runtime: Any = None,
        max_concurrent: int = 3,
        budget_per_rec: float = 0.05,  # USD budget cap per recommendation
    ) -> None:
        """Initialize with Phase 6 agent runtime.

        Args:
            agent_runtime: Phase 6 orchestrator for thesis generation.
            max_concurrent: Max concurrent thesis generations (cost control).
            budget_per_rec: USD budget cap per recommendation thesis.
        """
        self._runtime = agent_runtime
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._budget_per_rec = budget_per_rec

    async def run(
        self,
        run_id: UUID,
        risk_output: RiskValidationOutput,
    ) -> list[ThesisOutput]:
        """Execute Stage 7: generate thesis for each passed allocation.

        Args:
            run_id: Pipeline run identifier.
            risk_output: Stage 6 output with validated allocations.

        Returns:
            List of ThesisOutput (one per allocation, may have generated=False on failure).
        """
        start = time.perf_counter()

        allocations = risk_output.passed_allocations

        logger.info(
            "stage7_thesis_start",
            run_id=str(run_id),
            n_allocations=len(allocations),
        )

        if not self._runtime:
            # No agent runtime available — return placeholder theses
            logger.warning("stage7_no_runtime", run_id=str(run_id))
            return [
                ThesisOutput(
                    run_id=run_id,
                    ticker=alloc.ticker,
                    thesis_run_id=None,
                    summary="Thesis generation pending — agent runtime not configured.",
                    generated=False,
                )
                for alloc in allocations
            ]

        # Generate theses concurrently with semaphore for cost control
        tasks = [
            self._generate_one(run_id, alloc) for alloc in allocations
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        outputs: list[ThesisOutput] = []
        for alloc, result in zip(allocations, results, strict=True):
            if isinstance(result, Exception):
                logger.warning(
                    "stage7_thesis_failed",
                    run_id=str(run_id),
                    ticker=alloc.ticker,
                    error=str(result),
                )
                outputs.append(
                    ThesisOutput(
                        run_id=run_id,
                        ticker=alloc.ticker,
                        thesis_run_id=None,
                        summary=f"Thesis generation failed: {result}",
                        generated=False,
                    )
                )
            else:
                outputs.append(result)

        elapsed_ms = (time.perf_counter() - start) * 1000
        generated_count = sum(1 for o in outputs if o.generated)

        logger.info(
            "stage7_thesis_complete",
            run_id=str(run_id),
            generated=generated_count,
            failed=len(outputs) - generated_count,
            elapsed_ms=round(elapsed_ms, 1),
        )

        return outputs

    async def _generate_one(
        self, run_id: UUID, alloc: PortfolioAllocation
    ) -> ThesisOutput:
        """Generate thesis for a single allocation with concurrency control."""
        async with self._semaphore:
            # Call Phase 6 agent runtime
            result = await self._runtime.generate_thesis(
                ticker=alloc.ticker,
                side=alloc.side,
                weight=alloc.target_weight,
            )

            return ThesisOutput(
                run_id=run_id,
                ticker=alloc.ticker,
                thesis_run_id=result.run_id if hasattr(result, "run_id") else None,
                summary=result.summary if hasattr(result, "summary") else "",
                citations=result.citations if hasattr(result, "citations") else [],
                generated=True,
            )
