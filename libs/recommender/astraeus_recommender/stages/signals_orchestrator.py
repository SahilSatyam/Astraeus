"""Stage 3: Signal Generation — orchestrates all 5 signal generators.

Each signal generator is independent with its own state.
Per-signal SLA: < 5 min daily.
Signals never see ranks — they output raw scores only.
"""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

import structlog

from ..contracts import DailyInputSnapshot, SignalOutput
from .signals.base import SignalGenerator

logger = structlog.get_logger("astraeus.recommender.stages.signals_orchestrator")


class SignalsStage:
    """Stage 3: Orchestrates all signal generators in parallel.

    Each generator runs independently. A failure in one signal does not
    block others — the run continues in degraded mode.
    """

    def __init__(self, generators: list[SignalGenerator]) -> None:
        self._generators = generators

    async def run(
        self,
        run_id: UUID,
        snapshot: DailyInputSnapshot,
    ) -> list[SignalOutput]:
        """Execute all signal generators concurrently.

        Args:
            run_id: Pipeline run identifier.
            snapshot: Stage 1 output.

        Returns:
            List of SignalOutput from each successful generator.
        """
        start = time.perf_counter()

        logger.info(
            "stage3_signals_start",
            run_id=str(run_id),
            n_generators=len(self._generators),
        )

        # Run all generators concurrently
        tasks = [gen.run(run_id, snapshot) for gen in self._generators]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        outputs: list[SignalOutput] = []
        failed: list[str] = []

        for gen, result in zip(self._generators, results, strict=True):
            if isinstance(result, Exception):
                logger.error(
                    "signal_generator_failed",
                    signal=gen.name,
                    run_id=str(run_id),
                    error=str(result),
                )
                failed.append(gen.name)
            else:
                outputs.append(result)

        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "stage3_signals_complete",
            run_id=str(run_id),
            successful=len(outputs),
            failed=failed,
            elapsed_ms=round(elapsed_ms, 1),
        )

        if not outputs:
            raise RuntimeError(
                f"All signal generators failed: {failed}. Cannot proceed to ensemble."
            )

        return outputs
