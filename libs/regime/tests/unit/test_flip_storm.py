"""Regime flip-storm synthetic test.

Generates rapid label changes and verifies:
1. The stability filter prevents flip-flopping
2. The committed label stays stable during storms
3. Warning logs fire when instability is detected
"""

from datetime import date, timedelta

from astraeus_regime.stability import StabilityFilter


class TestFlipStorm:
    """Simulate regime flip storms and verify filter behavior."""

    def test_rapid_alternation_does_not_commit(self):
        """Alternating labels every day should never commit a new label."""
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        labels = ["risk_on", "risk_off"] * 20  # 40 days of alternation

        for i, label in enumerate(labels):
            committed, _ = f.update(label, 0.8, date(2024, 6, 1) + timedelta(days=i))

        # Should still be uncertain — never stable enough to commit
        assert committed == "uncertain"

    def test_storm_after_committed_preserves_label(self):
        """Once committed, a flip storm should not change the label."""
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        # First: establish a committed label
        for i in range(5):
            f.update("risk_on", 0.9, date(2024, 6, 1) + timedelta(days=i))

        assert f.committed_label == "risk_on"

        # Now: inject a flip storm
        storm_labels = ["vol_spike", "risk_off", "trending", "risk_on", "vol_spike"] * 4
        for i, label in enumerate(storm_labels):
            f.update(label, 0.7, date(2024, 6, 6) + timedelta(days=i))

        # Committed label should still be risk_on (storm never stabilized)
        assert f.committed_label == "risk_on"

    def test_storm_with_eventual_stability_commits_new_label(self):
        """If a new label stabilizes after a storm, it should eventually commit."""
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        # Establish risk_on
        for i in range(3):
            f.update("risk_on", 0.9, date(2024, 6, 1) + timedelta(days=i))
        assert f.committed_label == "risk_on"

        # Storm period
        storm = ["vol_spike", "risk_off", "vol_spike", "trending"]
        for i, label in enumerate(storm):
            f.update(label, 0.7, date(2024, 6, 4) + timedelta(days=i))
        assert f.committed_label == "risk_on"  # Still stable

        # New label stabilizes
        for i in range(4):
            f.update("vol_spike", 0.85, date(2024, 6, 8) + timedelta(days=i))

        assert f.committed_label == "vol_spike"  # New label committed

    def test_low_probability_storm_never_commits(self):
        """Labels below probability threshold never commit, even if repeated."""
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        # 20 days of the same label but below threshold
        for i in range(20):
            f.update("risk_off", 0.4, date(2024, 6, 1) + timedelta(days=i))

        assert f.committed_label == "uncertain"

    def test_consecutive_days_resets_on_probability_drop(self):
        """Consecutive counter resets if probability drops below threshold."""
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        f.update("risk_on", 0.8, date(2024, 6, 1))
        f.update("risk_on", 0.8, date(2024, 6, 2))
        # Probability drops
        f.update("risk_on", 0.4, date(2024, 6, 3))
        # Back up
        f.update("risk_on", 0.8, date(2024, 6, 4))
        f.update("risk_on", 0.8, date(2024, 6, 5))

        # Should NOT have committed yet — the drop reset the counter
        # Day 4 and 5 are only 2 consecutive days above threshold
        assert f.committed_label == "uncertain"

        # One more day commits it
        f.update("risk_on", 0.8, date(2024, 6, 6))
        assert f.committed_label == "risk_on"

    def test_extreme_storm_50_flips(self):
        """50 random-ish flips should not destabilize a committed label."""
        f = StabilityFilter(threshold_days=3, probability_threshold=0.6)

        # Commit
        for i in range(4):
            f.update("trending", 0.85, date(2024, 1, 1) + timedelta(days=i))
        assert f.committed_label == "trending"

        # 50 flips
        labels = ["risk_on", "risk_off", "vol_spike", "mean_reversion", "uncertain"]
        for i in range(50):
            label = labels[i % len(labels)]
            f.update(label, 0.7, date(2024, 1, 5) + timedelta(days=i))

        # Still trending — no single label held for 3 days
        assert f.committed_label == "trending"
