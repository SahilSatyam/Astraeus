"""Stage 8: HITL (Human-in-the-Loop) — approval workflow and override capture.

Assembles final recommendations and manages the approval lifecycle.
Every recommendation has a state: proposed | approved | rejected | overridden | expired.
"""

from __future__ import annotations

import time
from uuid import UUID

import structlog

from ..contracts import (
    DecisionType,
    EnsembleOutput,
    PortfolioAllocation,
    Recommendation,
    RecommendationDecision,
    RecommendationState,
    RiskValidationOutput,
    ThesisOutput,
)
from ..overrides import OverrideDataset, OverrideRecord
from ..statemachine import transition

logger = structlog.get_logger("astraeus.recommender.stages.hitl")


class HITLStage:
    """Stage 8: Human-in-the-loop approval workflow.

    Assembles recommendations from upstream stages and manages
    the approval/rejection/override lifecycle.
    """

    def __init__(
        self,
        override_dataset: OverrideDataset | None = None,
        horizon_days: int = 60,
    ) -> None:
        self._overrides = override_dataset or OverrideDataset()
        self._horizon_days = horizon_days

    async def assemble(
        self,
        run_id: UUID,
        ensemble: EnsembleOutput,
        risk_output: RiskValidationOutput,
        theses: list[ThesisOutput],
    ) -> list[Recommendation]:
        """Assemble final recommendations from upstream stage outputs.

        Args:
            run_id: Pipeline run identifier.
            ensemble: Stage 4 output (for scores and attribution).
            risk_output: Stage 6 output (for risk status).
            theses: Stage 7 output (for thesis text).

        Returns:
            List of Recommendation objects in PROPOSED state.
        """
        start = time.perf_counter()

        logger.info("stage8_hitl_assemble_start", run_id=str(run_id))

        # Build lookup maps
        thesis_map: dict[str, ThesisOutput] = {t.ticker: t for t in theses}
        alloc_map: dict[str, PortfolioAllocation] = {
            a.ticker: a for a in risk_output.passed_allocations
        }

        recommendations: list[Recommendation] = []

        for candidate in ensemble.candidates:
            alloc = alloc_map.get(candidate.ticker)
            if alloc is None:
                # This candidate was rejected by risk — skip
                continue

            thesis = thesis_map.get(candidate.ticker)

            rec = Recommendation(
                run_id=run_id,
                ticker=candidate.ticker,
                side=alloc.side,
                target_weight=alloc.target_weight,
                rank=candidate.rank,
                composite_score=candidate.composite_score,
                component_attribution=candidate.component_attribution,
                risk_passed=True,
                risk_notes=None,
                thesis_run_id=thesis.thesis_run_id if thesis else None,
                thesis_summary=thesis.summary if thesis else "",
                state=RecommendationState.PROPOSED,
                horizon_days=self._horizon_days,
            )
            recommendations.append(rec)

        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "stage8_hitl_assemble_complete",
            run_id=str(run_id),
            n_recommendations=len(recommendations),
            elapsed_ms=round(elapsed_ms, 1),
        )

        return recommendations

    async def decide(
        self,
        recommendation: Recommendation,
        decision: RecommendationDecision,
        regime_label: str = "",
    ) -> Recommendation:
        """Apply a HITL decision to a recommendation.

        Args:
            recommendation: The recommendation to decide on.
            decision: The decision (approve/reject/override).
            regime_label: Current regime for override dataset.

        Returns:
            Updated recommendation with new state.

        Raises:
            InvalidTransitionError: If the transition is not allowed.
        """
        logger.info(
            "stage8_hitl_decide",
            rec_id=str(recommendation.rec_id),
            ticker=recommendation.ticker,
            decision=decision.decision,
        )

        # Apply state transition
        new_state = transition(recommendation.state, decision.decision)
        recommendation.state = new_state

        # Capture override data for the learning dataset
        if decision.decision in (DecisionType.REJECT, DecisionType.OVERRIDE):
            record = OverrideRecord(
                rec_id=recommendation.rec_id,
                run_id=recommendation.run_id,
                run_date=str(recommendation.created_at.date()),
                ticker=recommendation.ticker,
                original_side=recommendation.side,
                original_weight=recommendation.target_weight,
                override_weight=decision.override_weight,
                decision=decision.decision,
                rationale=decision.rationale,
                regime_label=regime_label,
                composite_score=recommendation.composite_score,
                component_attribution=recommendation.component_attribution,
            )
            self._overrides.add(record)

        logger.info(
            "stage8_hitl_decided",
            rec_id=str(recommendation.rec_id),
            ticker=recommendation.ticker,
            new_state=new_state,
        )

        return recommendation

    @property
    def override_dataset(self) -> OverrideDataset:
        """Access the override dataset for export."""
        return self._overrides
