"""Tests for the pipeline orchestrator — replay determinism and partial-failure tolerance."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from astraeus_recommender.contracts import (
    DailyInputSnapshot,
    EnsembleCandidate,
    EnsembleOutput,
    PortfolioAllocation,
    PortfolioOutput,
    RegimeDetection,
    RegimeLabel,
    RiskCheckResult,
    RiskValidationOutput,
    RunStatus,
    Side,
    SignalName,
    SignalOutput,
    SignalValue,
    ThesisOutput,
)
from astraeus_recommender.orchestrator import PipelineOrchestrator
from astraeus_recommender.stages.aggregate import AggregateStage
from astraeus_recommender.stages.ensemble import EnsembleStage
from astraeus_recommender.stages.hitl import HITLStage
from astraeus_recommender.stages.portfolio import PortfolioStage
from astraeus_recommender.stages.regime import RegimeStage
from astraeus_recommender.stages.risk import RiskStage
from astraeus_recommender.stages.signals_orchestrator import SignalsStage
from astraeus_recommender.stages.thesis import ThesisStage


def _make_snapshot(run_id=None):
    return DailyInputSnapshot(
        run_id=run_id or uuid4(),
        run_date=date(2024, 6, 15),
        snapshot_hash="abc123def456",
        symbols=["AAPL", "MSFT", "GOOGL"],
        feature_names=["momentum_20d", "vol_20d"],
        feature_matrix={
            "AAPL": {"momentum_20d": 0.05, "vol_20d": 0.18},
            "MSFT": {"momentum_20d": 0.03, "vol_20d": 0.15},
            "GOOGL": {"momentum_20d": -0.02, "vol_20d": 0.22},
        },
    )


def _make_regime(run_id):
    return RegimeDetection(
        run_id=run_id,
        label=RegimeLabel.RISK_ON,
        probability=0.85,
        stability_days=5,
    )


def _make_signals(run_id):
    return [
        SignalOutput(
            run_id=run_id,
            signal=SignalName.TECHNICAL,
            values=[
                SignalValue(ticker="AAPL", score=0.8, score_z=1.5, confidence=0.9),
                SignalValue(ticker="MSFT", score=0.5, score_z=0.5, confidence=0.8),
                SignalValue(ticker="GOOGL", score=-0.3, score_z=-1.0, confidence=0.7),
            ],
        ),
    ]


def _make_ensemble(run_id):
    return EnsembleOutput(
        run_id=run_id,
        regime=RegimeLabel.RISK_ON,
        candidates=[
            EnsembleCandidate(
                ticker="AAPL",
                composite_score=0.8,
                rank=1,
                component_attribution={"technical": 0.8},
            ),
            EnsembleCandidate(
                ticker="MSFT",
                composite_score=0.5,
                rank=2,
                component_attribution={"technical": 0.5},
            ),
        ],
        weights_used={"technical": 1.0},
    )


def _make_portfolio(run_id):
    return PortfolioOutput(
        run_id=run_id,
        allocations=[
            PortfolioAllocation(ticker="AAPL", side=Side.LONG, target_weight=0.06),
            PortfolioAllocation(ticker="MSFT", side=Side.LONG, target_weight=0.04),
        ],
        optimizer_used="score_proportional",
    )


def _make_risk_output(run_id):
    return RiskValidationOutput(
        run_id=run_id,
        passed_allocations=[
            PortfolioAllocation(ticker="AAPL", side=Side.LONG, target_weight=0.06),
            PortfolioAllocation(ticker="MSFT", side=Side.LONG, target_weight=0.04),
        ],
        checks=[RiskCheckResult(rule="max_single_position", passed=True)],
        all_passed=True,
    )


def _make_theses(run_id):
    return [
        ThesisOutput(run_id=run_id, ticker="AAPL", summary="Strong momentum", generated=True),
        ThesisOutput(run_id=run_id, ticker="MSFT", summary="Moderate outlook", generated=True),
    ]


def _build_orchestrator(
    aggregate_output=None,
    regime_output=None,
    signals_output=None,
    ensemble_output=None,
    portfolio_output=None,
    risk_output=None,
    thesis_output=None,
):
    """Build an orchestrator with mocked stages."""
    aggregate = MagicMock(spec=AggregateStage)
    aggregate.run = AsyncMock(return_value=aggregate_output or _make_snapshot())

    regime = MagicMock(spec=RegimeStage)
    regime.run = AsyncMock(side_effect=lambda rid, snap: regime_output or _make_regime(rid))

    signals = MagicMock(spec=SignalsStage)
    signals.run = AsyncMock(side_effect=lambda rid, snap: signals_output or _make_signals(rid))

    ensemble = MagicMock(spec=EnsembleStage)
    ensemble.run = AsyncMock(
        side_effect=lambda rid, reg, sigs: ensemble_output or _make_ensemble(rid)
    )

    portfolio = MagicMock(spec=PortfolioStage)
    portfolio.run = AsyncMock(side_effect=lambda rid, ens: portfolio_output or _make_portfolio(rid))

    risk = MagicMock(spec=RiskStage)
    risk.run = AsyncMock(side_effect=lambda rid, port: risk_output or _make_risk_output(rid))

    thesis = MagicMock(spec=ThesisStage)
    thesis.run = AsyncMock(side_effect=lambda rid, risk_out: thesis_output or _make_theses(rid))

    hitl = HITLStage()

    return PipelineOrchestrator(
        aggregate=aggregate,
        regime=regime,
        signals=signals,
        ensemble=ensemble,
        portfolio=portfolio,
        risk=risk,
        thesis=thesis,
        hitl=hitl,
    )


class TestPipelineOrchestrator:
    """Test the full pipeline orchestrator."""

    @pytest.mark.asyncio
    async def test_successful_run(self):
        orchestrator = _build_orchestrator()
        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DONE
        assert len(result.recommendations) == 2
        assert result.recommendations[0].ticker == "AAPL"
        assert result.recommendations[0].rank == 1

    @pytest.mark.asyncio
    async def test_replay_determinism(self):
        """Same inputs should produce same recommendations."""
        run_id = uuid4()
        orchestrator = _build_orchestrator()

        result1 = await orchestrator.run(run_date=date(2024, 6, 15), run_id=run_id)
        result2 = await orchestrator.run(run_date=date(2024, 6, 15), run_id=run_id)

        # Same number of recommendations
        assert len(result1.recommendations) == len(result2.recommendations)
        # Same tickers in same order
        tickers1 = [r.ticker for r in result1.recommendations]
        tickers2 = [r.ticker for r in result2.recommendations]
        assert tickers1 == tickers2

    @pytest.mark.asyncio
    async def test_stage5_failure_degrades_run(self):
        """Portfolio stage failure should degrade, not fail, the run."""
        portfolio = MagicMock(spec=PortfolioStage)
        portfolio.run = AsyncMock(side_effect=RuntimeError("Optimizer crashed"))

        orchestrator = _build_orchestrator()
        orchestrator._stages["portfolio"] = portfolio

        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DEGRADED
        assert "portfolio" in result.run.failed_stages

    @pytest.mark.asyncio
    async def test_thesis_failure_degrades_run(self):
        """Thesis stage failure should degrade the run but still produce recommendations."""
        thesis = MagicMock(spec=ThesisStage)
        thesis.run = AsyncMock(side_effect=RuntimeError("LLM outage"))

        orchestrator = _build_orchestrator()
        orchestrator._stages["thesis"] = thesis

        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DEGRADED
        assert "thesis" in result.run.failed_stages
        # Recommendations still produced (from HITL assembly with empty theses)
        assert len(result.recommendations) == 2

    @pytest.mark.asyncio
    async def test_aggregate_failure_is_fatal(self):
        """Stage 1 failure should fail the entire run."""
        aggregate = MagicMock(spec=AggregateStage)
        aggregate.run = AsyncMock(side_effect=RuntimeError("Feature store down"))

        orchestrator = _build_orchestrator()
        orchestrator._stages["aggregate"] = aggregate

        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.FAILED
        assert "aggregate" in result.run.failed_stages

    @pytest.mark.asyncio
    async def test_all_signals_fail_is_fatal(self):
        """If all signal generators fail, the run should fail."""
        signals = MagicMock(spec=SignalsStage)
        signals.run = AsyncMock(side_effect=RuntimeError("All signal generators failed"))

        orchestrator = _build_orchestrator()
        orchestrator._stages["signals"] = signals

        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_stage_timings_recorded(self):
        """All stage timings should be recorded."""
        orchestrator = _build_orchestrator()
        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert "aggregate" in result.run.stage_timings
        assert "regime" in result.run.stage_timings
        assert "signals" in result.run.stage_timings
        assert "ensemble" in result.run.stage_timings
        assert "total" in result.run.stage_timings
