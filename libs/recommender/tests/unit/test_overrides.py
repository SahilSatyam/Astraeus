"""Tests for the override-learning dataset."""

from uuid import uuid4

from astraeus_recommender.overrides import OverrideDataset, OverrideRecord


class TestOverrideDataset:
    def test_add_and_count(self):
        ds = OverrideDataset()
        assert ds.count == 0

        record = OverrideRecord(
            rec_id=uuid4(),
            run_id=uuid4(),
            run_date="2024-06-15",
            ticker="AAPL",
            original_side="long",
            original_weight=0.05,
            override_weight=0.03,
            decision="override",
            rationale="Position too large given earnings risk",
            regime_label="risk_on",
            composite_score=0.8,
            component_attribution={"technical": 0.4, "ml_xgb": 0.4},
        )
        ds.add(record)
        assert ds.count == 1

    def test_export_csv_empty(self):
        ds = OverrideDataset()
        assert ds.export_csv() == ""

    def test_export_csv_with_records(self):
        ds = OverrideDataset()
        for i in range(3):
            ds.add(
                OverrideRecord(
                    rec_id=uuid4(),
                    run_id=uuid4(),
                    run_date=f"2024-06-{15 + i}",
                    ticker="AAPL",
                    original_side="long",
                    original_weight=0.05,
                    override_weight=None,
                    decision="reject",
                    rationale=f"Reason {i}",
                    regime_label="risk_off",
                    composite_score=0.5 + i * 0.1,
                    component_attribution={"technical": 0.3, "macro": 0.2},
                )
            )

        csv_output = ds.export_csv()
        lines = csv_output.strip().split("\n")
        assert len(lines) == 4  # header + 3 records
        assert "rec_id" in lines[0]
        assert "signal_technical" in lines[0]
        assert "signal_macro" in lines[0]
