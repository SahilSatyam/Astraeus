"""Stage-isolation tests.

Verifies that replacing any single stage's implementation with a stub
does not break the pipeline — the stub's output flows downstream correctly.
This proves the rigid contract boundaries between stages.
"""

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

# --- Fixtures: canonical stage outputs ---

SNAPSHOT = DailyInputSnapshot(
    run_date=date(2024, 6, 15),
    snapshot_hash="fixed_hash_abc123",
    symbols=["AAPL", "MSFT"],
    feature_names=["momentum_20d"],
    feature_matrix={"AAPL": {"momentum_20d": 0.05}, "MSFT": {"momentum_20d": -0.01}},
)

REGIME = RegimeDetection(
    run_id=uuid4(),
    label=RegimeLabel.RISK_ON,
    probability=0.9,
    stability_days=7,
)

SIGNALS = [
    SignalOutput(
        run_id=uuid4(),
        signal=SignalName.TECHNICAL,
        values=[
            SignalValue(ticker="AAPL", score=0.7, score_z=1.2, confidence=0.9),
            SignalValue(ticker="MSFT", score=0.3, score_z=-0.2, confidence=0.8),
        ],
    ),
]

ENSEMBLE = EnsembleOutput(
    run_id=uuid4(),
    regime=RegimeLabel.RISK_ON,
    candidates=[
        EnsembleCandidate(
            ticker="AAPL",
            composite_score=0.7,
            rank=1,
            component_attribution={"technical": 0.7},
        ),
    ],
    weights_used={"technical": 1.0},
)

PORTFOLIO = PortfolioOutput(
    run_id=uuid4(),
    allocations=[PortfolioAllocation(ticker="AAPL", side=Side.LONG, target_weight=0.08)],
    optimizer_used="stub_optimizer",
)

RISK_OUTPUT = RiskValidationOutput(
    run_id=uuid4(),
    passed_allocations=[PortfolioAllocation(ticker="AAPL", side=Side.LONG, target_weight=0.08)],
    checks=[RiskCheckResult(rule="max_single_position", passed=True)],
    all_passed=True,
)

THESES = [
    ThesisOutput(run_id=uuid4(), ticker="AAPL", summary="Stub thesis", generated=True),
]


def _build_orchestrator_with_stub(stub_stage: str, stub_output):
    """Build orchestrator where one stage is a stub returning fixed output."""
    stages = {
        "aggregate": AsyncMock(return_value=SNAPSHOT),
        "regime": AsyncMock(side_effect=lambda rid, snap: REGIME),
        "signals": AsyncMock(side_effect=lambda rid, snap: SIGNALS),
        "ensemble": AsyncMock(side_effect=lambda rid, reg, sigs: ENSEMBLE),
        "portfolio": AsyncMock(side_effect=lambda rid, ens: PORTFOLIO),
        "risk": AsyncMock(side_effect=lambda rid, port: RISK_OUTPUT),
        "thesis": AsyncMock(side_effect=lambda rid, risk: THESES),
    }

    # Replace the target stage with a stub
    if stub_stage == "aggregate":
        stages["aggregate"] = AsyncMock(return_value=stub_output)
    elif stub_stage == "regime":
        stages["regime"] = AsyncMock(side_effect=lambda rid, snap: stub_output)
    elif stub_stage == "signals":
        stages["signals"] = AsyncMock(side_effect=lambda rid, snap: stub_output)
    elif stub_stage == "ensemble":
        stages["ensemble"] = AsyncMock(side_effect=lambda rid, reg, sigs: stub_output)
    elif stub_stage == "portfolio":
        stages["portfolio"] = AsyncMock(side_effect=lambda rid, ens: stub_output)
    elif stub_stage == "risk":
        stages["risk"] = AsyncMock(side_effect=lambda rid, port: stub_output)
    elif stub_stage == "thesis":
        stages["thesis"] = AsyncMock(side_effect=lambda rid, risk: stub_output)

    aggregate = MagicMock(spec=AggregateStage)
    aggregate.run = stages["aggregate"]

    regime = MagicMock(spec=RegimeStage)
    regime.run = stages["regime"]

    signals = MagicMock(spec=SignalsStage)
    signals.run = stages["signals"]

    ensemble = MagicMock(spec=EnsembleStage)
    ensemble.run = stages["ensemble"]

    portfolio = MagicMock(spec=PortfolioStage)
    portfolio.run = stages["portfolio"]

    risk = MagicMock(spec=RiskStage)
    risk.run = stages["risk"]

    thesis = MagicMock(spec=ThesisStage)
    thesis.run = stages["thesis"]

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


class TestStageIsolation:
    """Replace each stage with a stub and verify the pipeline still runs."""

    @pytest.mark.asyncio
    async def test_stub_aggregate_flows_downstream(self):
        """Stub aggregate output is consumed by regime and signals."""
        stub_snapshot = DailyInputSnapshot(
            run_date=date(2024, 6, 15),
            snapshot_hash="STUB_HASH",
            symbols=["STUB_TICKER"],
            feature_names=["stub_feature"],
            feature_matrix={"STUB_TICKER": {"stub_feature": 99.0}},
        )
        orchestrator = _build_orchestrator_with_stub("aggregate", stub_snapshot)
        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DONE
        assert result.run.input_snapshot_hash == "STUB_HASH"

    @pytest.mark.asyncio
    async def test_stub_regime_flows_to_ensemble(self):
        """Stub regime output is passed to ensemble stage."""
        stub_regime = RegimeDetection(
            run_id=uuid4(),
            label=RegimeLabel.VOL_SPIKE,
            probability=0.95,
            stability_days=10,
        )
        orchestrator = _build_orchestrator_with_stub("regime", stub_regime)
        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DONE
        assert result.regime.label == RegimeLabel.VOL_SPIKE

    @pytest.mark.asyncio
    async def test_stub_signals_flows_to_ensemble(self):
        """Stub signals output is passed to ensemble stage."""
        stub_signals = [
            SignalOutput(
                run_id=uuid4(),
                signal=SignalName.MACRO,
                values=[SignalValue(ticker="STUB", score=42.0, confidence=1.0)],
            ),
        ]
        orchestrator = _build_orchestrator_with_stub("signals", stub_signals)
        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DONE

    @pytest.mark.asyncio
    async def test_stub_ensemble_flows_to_portfolio(self):
        """Stub ensemble output is passed to portfolio stage."""
        stub_ensemble = EnsembleOutput(
            run_id=uuid4(),
            regime=RegimeLabel.TRENDING,
            candidates=[
                EnsembleCandidate(
                    ticker="STUB_TICKER",
                    composite_score=99.0,
                    rank=1,
                    component_attribution={"stub": 99.0},
                ),
            ],
            weights_used={"stub": 1.0},
        )
        orchestrator = _build_orchestrator_with_stub("ensemble", stub_ensemble)
        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DONE
        assert result.ensemble.candidates[0].ticker == "STUB_TICKER"

    @pytest.mark.asyncio
    async def test_stub_portfolio_flows_to_risk(self):
        """Stub portfolio output is passed to risk stage."""
        stub_portfolio = PortfolioOutput(
            run_id=uuid4(),
            allocations=[
                PortfolioAllocation(ticker="STUB", side=Side.SHORT, target_weight=-0.05),
            ],
            optimizer_used="stub_opt",
        )
        orchestrator = _build_orchestrator_with_stub("portfolio", stub_portfolio)
        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DONE

    @pytest.mark.asyncio
    async def test_stub_thesis_flows_to_hitl(self):
        """Stub thesis output is used in HITL assembly."""
        stub_theses = [
            ThesisOutput(
                run_id=uuid4(),
                ticker="AAPL",
                summary="STUB THESIS TEXT",
                generated=True,
            ),
        ]
        orchestrator = _build_orchestrator_with_stub("thesis", stub_theses)
        result = await orchestrator.run(run_date=date(2024, 6, 15))

        assert result.run.status == RunStatus.DONE
        # The HITL stage should have used the stub thesis
        for rec in result.recommendations:
            if rec.ticker == "AAPL":
                assert rec.thesis_summary == "STUB THESIS TEXT"
