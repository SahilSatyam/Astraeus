"""Pipeline orchestrator — runs the 8-stage recommendation pipeline.

In production this would be a Temporal Workflow. For now it's a plain async
orchestrator that runs stages sequentially with partial-failure tolerance.

A failure in Stage 5+ does not corrupt Stage 1-4 outputs; the run is marked
'degraded' and the cause is logged.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog

from .contracts import (
    EnsembleOutput,
    PipelineRun,
    Recommendation,
    RiskValidationOutput,
    RunStatus,
)
from .stages.aggregate import AggregateStage
from .stages.ensemble import EnsembleStage
from .stages.hitl import HITLStage
from .stages.portfolio import PortfolioStage
from .stages.regime import RegimeStage
from .stages.risk import RiskStage
from .stages.signals_orchestrator import SignalsStage
from .stages.thesis import ThesisStage
from .telemetry import RecommenderMetrics

logger = structlog.get_logger("astraeus.recommender.orchestrator")


class PipelineOrchestrator:
    """Orchestrates the 8-stage daily recommendation pipeline.

    Handles partial-failure tolerance: early-stage failures are fatal,
    late-stage failures (thesis, HITL) degrade the run but preserve outputs.
    """

    def __init__(
        self,
        aggregate: AggregateStage,
        regime: RegimeStage,
        signals: SignalsStage,
        ensemble: EnsembleStage,
        portfolio: PortfolioStage,
        risk: RiskStage,
        thesis: ThesisStage,
        hitl: HITLStage,
        metrics: RecommenderMetrics | None = None,
    ) -> None:
        self._stages = {
            "aggregate": aggregate,
            "regime": regime,
            "signals": signals,
            "ensemble": ensemble,
            "portfolio": portfolio,
            "risk": risk,
            "thesis": thesis,
            "hitl": hitl,
        }
        self._metrics = metrics

    async def run(
        self,
        run_date: date,
        run_id: UUID | None = None,
        code_commit: str = "",
    ) -> PipelineRunResult:
        """Execute the full pipeline for a given date.

        Args:
            run_date: Trading date for this run.
            run_id: Optional run ID (generated if not provided).
            code_commit: Git commit hash for reproducibility.

        Returns:
            PipelineRunResult with run metadata and recommendations.
        """
        if run_id is None:
            run_id = uuid4()

        pipeline_run = PipelineRun(
            run_id=run_id,
            run_date=run_date,
            status=RunStatus.RUNNING,
            code_commit=code_commit,
        )

        logger.info(
            "pipeline_start",
            run_id=str(run_id),
            run_date=run_date.isoformat(),
        )

        result = PipelineRunResult(run=pipeline_run)
        total_start = time.perf_counter()

        try:
            # Stage 1: Aggregate (fatal on failure)
            snapshot = await self._run_stage(
                "aggregate",
                pipeline_run,
                self._stages["aggregate"].run,
                run_id,
                run_date,
            )

            pipeline_run.input_snapshot_hash = snapshot.snapshot_hash

            # Stage 2: Regime Detection (fatal on failure)
            regime = await self._run_stage(
                "regime",
                pipeline_run,
                self._stages["regime"].run,
                run_id,
                snapshot,
            )
            result.regime = regime

            # Stage 3: Signal Generation (fatal if ALL fail)
            signals = await self._run_stage(
                "signals",
                pipeline_run,
                self._stages["signals"].run,
                run_id,
                snapshot,
            )

            # Stage 4: Ensemble (fatal on failure)
            ensemble_output = await self._run_stage(
                "ensemble",
                pipeline_run,
                self._stages["ensemble"].run,
                run_id,
                regime,
                signals,
            )
            result.ensemble = ensemble_output

            # Stage 5: Portfolio Construction (degraded on failure)
            portfolio_output = await self._run_stage_degraded(
                "portfolio",
                pipeline_run,
                self._stages["portfolio"].run,
                run_id,
                ensemble_output,
            )

            if portfolio_output is None:
                pipeline_run.status = RunStatus.DEGRADED
                self._emit_completion_metrics(pipeline_run, result)
                result.run = pipeline_run
                return result

            # Stage 6: Risk Validation (degraded on failure)
            risk_output = await self._run_stage_degraded(
                "risk",
                pipeline_run,
                self._stages["risk"].run,
                run_id,
                portfolio_output,
            )

            if risk_output is None:
                pipeline_run.status = RunStatus.DEGRADED
                self._emit_completion_metrics(pipeline_run, result)
                result.run = pipeline_run
                return result

            result.risk = risk_output

            # Stage 7: Thesis Generation (degraded on failure — recs still available)
            theses = await self._run_stage_degraded(
                "thesis",
                pipeline_run,
                self._stages["thesis"].run,
                run_id,
                risk_output,
            )

            if theses is None:
                theses = []
                pipeline_run.status = RunStatus.DEGRADED
                pipeline_run.failed_stages.append("thesis")

            # Stage 8: HITL Assembly
            recommendations = await self._run_stage(
                "hitl",
                pipeline_run,
                self._stages["hitl"].assemble,
                run_id,
                ensemble_output,
                risk_output,
                theses,
            )
            result.recommendations = recommendations

            # Mark complete
            if pipeline_run.status != RunStatus.DEGRADED:
                pipeline_run.status = RunStatus.DONE

        except Exception as e:
            logger.error(
                "pipeline_fatal_failure",
                run_id=str(run_id),
                error=str(e),
            )
            pipeline_run.status = RunStatus.FAILED
            pipeline_run.notes = str(e)

        pipeline_run.finished_at = datetime.now().astimezone()
        total_elapsed = time.perf_counter() - total_start
        pipeline_run.stage_timings["total"] = total_elapsed

        self._emit_completion_metrics(pipeline_run, result)

        logger.info(
            "pipeline_complete",
            run_id=str(run_id),
            status=pipeline_run.status,
            total_seconds=round(total_elapsed, 2),
            n_recommendations=len(result.recommendations),
        )

        result.run = pipeline_run
        return result

    async def _run_stage(
        self,
        stage_name: str,
        pipeline_run: PipelineRun,
        fn: Any,
        *args: Any,
    ) -> Any:
        """Run a stage that is fatal on failure."""
        start = time.perf_counter()
        try:
            result = await fn(*args)
            elapsed = time.perf_counter() - start
            pipeline_run.stage_timings[stage_name] = elapsed
            self._emit_stage_duration(stage_name, elapsed)
            return result
        except Exception:
            elapsed = time.perf_counter() - start
            pipeline_run.stage_timings[stage_name] = elapsed
            pipeline_run.failed_stages.append(stage_name)
            self._emit_stage_failure(stage_name)
            raise

    async def _run_stage_degraded(
        self,
        stage_name: str,
        pipeline_run: PipelineRun,
        fn: Any,
        *args: Any,
    ) -> Any | None:
        """Run a stage that degrades (not fails) the pipeline on error."""
        start = time.perf_counter()
        try:
            result = await fn(*args)
            elapsed = time.perf_counter() - start
            pipeline_run.stage_timings[stage_name] = elapsed
            self._emit_stage_duration(stage_name, elapsed)
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            pipeline_run.stage_timings[stage_name] = elapsed
            pipeline_run.failed_stages.append(stage_name)
            self._emit_stage_failure(stage_name)
            logger.error(
                "stage_degraded_failure",
                stage=stage_name,
                run_id=str(pipeline_run.run_id),
                error=str(e),
            )
            return None

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------

    def _emit_stage_duration(self, stage_name: str, elapsed: float) -> None:
        """Emit stage duration histogram."""
        if self._metrics:
            self._metrics.run_duration.labels(stage=stage_name).observe(elapsed)

    def _emit_stage_failure(self, stage_name: str) -> None:
        """Increment stage failure counter."""
        if self._metrics:
            self._metrics.stage_failure_total.labels(stage=stage_name).inc()

    def _emit_completion_metrics(
        self, pipeline_run: PipelineRun, result: PipelineRunResult
    ) -> None:
        """Emit end-of-run metrics: regime label, recommendation counts, freshness."""
        if not self._metrics:
            return

        # Regime label gauge
        if result.regime:
            self._metrics.regime_label.labels(label=result.regime.label).set(1)

        # Recommendation counts by state
        state_counts: dict[str, int] = {}
        for rec in result.recommendations:
            state_counts[rec.state] = state_counts.get(rec.state, 0) + 1
        for state, count in state_counts.items():
            self._metrics.recommendations_count.labels(state=state).set(count)

        # Risk rejection rate
        if result.risk:
            total = len(result.risk.passed_allocations) + len(result.risk.rejected_allocations)
            if total > 0:
                for check in result.risk.checks:
                    if not check.passed:
                        rate = 1.0  # This check failed
                        self._metrics.risk_rejection_rate.labels(rule=check.rule).set(rate)

        # Pipeline freshness (minutes since completion)
        if pipeline_run.finished_at:
            self._metrics.pipeline_freshness.set(0.0)  # Just completed


class PipelineRunResult:
    """Result container for a pipeline execution."""

    def __init__(self, run: PipelineRun) -> None:
        self.run = run
        self.regime: Any = None
        self.ensemble: EnsembleOutput | None = None
        self.risk: RiskValidationOutput | None = None
        self.recommendations: list[Recommendation] = []
