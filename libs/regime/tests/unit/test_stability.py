"""Tests for the regime stability filter."""

from datetime import date

from astraeus_regime.stability import StabilityFilter


class TestStabilityFilter:
    def test_initial_state_is_uncertain(self):
        f = StabilityFilter(threshold_days=3)
        assert f.committed_label == "uncertain"

    def test_commits_after_threshold_days(self):
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        # Day 1: risk_on at 0.8
        label, days = f.update("risk_on", 0.8, date(2024, 6, 10))
        assert label == "uncertain"  # Not yet committed
        assert days == 1

        # Day 2: risk_on at 0.75
        label, days = f.update("risk_on", 0.75, date(2024, 6, 11))
        assert label == "uncertain"
        assert days == 2

        # Day 3: risk_on at 0.9 — commits!
        label, days = f.update("risk_on", 0.9, date(2024, 6, 12))
        assert label == "risk_on"
        assert days == 3

    def test_does_not_commit_below_probability(self):
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        for i in range(5):
            label, _ = f.update("risk_on", 0.4, date(2024, 6, 10 + i))

        assert label == "uncertain"

    def test_resets_on_label_change(self):
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        f.update("risk_on", 0.8, date(2024, 6, 10))
        f.update("risk_on", 0.8, date(2024, 6, 11))
        # Switch to risk_off — resets counter
        label, days = f.update("risk_off", 0.8, date(2024, 6, 12))
        assert days == 1
        assert label == "uncertain"

    def test_preserves_committed_label_during_flip(self):
        f = StabilityFilter(threshold_days=2, probability_threshold=0.6)

        # Commit risk_on
        f.update("risk_on", 0.8, date(2024, 6, 10))
        f.update("risk_on", 0.8, date(2024, 6, 11))

        # Single day of risk_off — committed label stays
        label, _ = f.update("risk_off", 0.8, date(2024, 6, 12))
        assert label == "risk_on"  # Still committed to risk_on

    def test_reset(self):
        f = StabilityFilter(threshold_days=2)
        f.update("risk_on", 0.9, date(2024, 6, 10))
        f.update("risk_on", 0.9, date(2024, 6, 11))
        assert f.committed_label == "risk_on"

        f.reset()
        assert f.committed_label == "uncertain"
        assert f.consecutive_days == 0
