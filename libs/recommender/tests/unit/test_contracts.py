"""Tests for pipeline contracts — validates Pydantic models serialize correctly."""

from datetime import date
from uuid import uuid4

from astraeus_recommender.contracts import (
    DailyInputSnapshot,
    EnsembleCandidate,
    EnsembleOutput,
    PipelineRun,
    Recommendation,
    RecommendationState,
    RegimeDetection,
    RegimeLabel,
    RunStatus,
    Side,
    SignalName,
    SignalOutput,
    SignalValue,
)


class TestDailyInputSnapshot:
    def test_create_snapshot(self):
        run_id = uuid4()
        snap = DailyInputSnapshot(
            run_id=run_id,
            run_date=date(2024, 6, 15),
            snapshot_hash="abc123",
            symbols=["AAPL", "MSFT"],
            feature_names=["momentum_20d"],
            feature_matrix={"AAPL": {"momentum_20d": 0.05}, "MSFT": {"momentum_20d": -0.02}},
        )
        assert snap.run_id == run_id
        assert len(snap.symbols) == 2
        assert snap.snapshot_hash == "abc123"

    def test_snapshot_serialization(self):
        snap = DailyInputSnapshot(
            run_date=date(2024, 6, 15),
            snapshot_hash="abc",
            symbols=["SPY"],
            feature_names=["vol_20d"],
            feature_matrix={"SPY": {"vol_20d": 0.15}},
        )
        data = snap.model_dump()
        assert "run_id" in data
        assert data["run_date"] == date(2024, 6, 15)


class TestRegimeDetection:
    def test_create_detection(self):
        det = RegimeDetection(
            run_id=uuid4(),
            label=RegimeLabel.RISK_ON,
            probability=0.85,
            stability_days=5,
        )
        assert det.label == RegimeLabel.RISK_ON
        assert det.probability == 0.85


class TestSignalOutput:
    def test_signal_with_values(self):
        output = SignalOutput(
            run_id=uuid4(),
            signal=SignalName.TECHNICAL,
            values=[
                SignalValue(ticker="AAPL", score=0.5, score_z=1.2, confidence=0.9),
                SignalValue(ticker="MSFT", score=-0.3, score_z=-0.8, confidence=0.8),
            ],
        )
        assert len(output.values) == 2
        assert output.signal == SignalName.TECHNICAL


class TestEnsembleOutput:
    def test_ranked_candidates(self):
        output = EnsembleOutput(
            run_id=uuid4(),
            regime=RegimeLabel.TRENDING,
            candidates=[
                EnsembleCandidate(
                    ticker="AAPL",
                    composite_score=0.8,
                    rank=1,
                    component_attribution={"technical": 0.4, "ml_xgb": 0.4},
                ),
            ],
            weights_used={"technical": 0.3, "ml_xgb": 0.3, "macro": 0.4},
        )
        assert output.candidates[0].rank == 1


class TestRecommendation:
    def test_create_recommendation(self):
        rec = Recommendation(
            run_id=uuid4(),
            ticker="AAPL",
            side=Side.LONG,
            target_weight=0.05,
            rank=1,
            composite_score=0.8,
            component_attribution={"technical": 0.4},
            risk_passed=True,
        )
        assert rec.state == RecommendationState.PROPOSED
        assert rec.horizon_days == 60


class TestPipelineRun:
    def test_default_status(self):
        run = PipelineRun(run_date=date(2024, 6, 15))
        assert run.status == RunStatus.QUEUED
        assert run.run_id is not None
