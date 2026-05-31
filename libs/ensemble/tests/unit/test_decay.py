"""Tests for signal decay tracking."""

from datetime import date

from astraeus_ensemble.decay import DecayTracker


class TestDecayTracker:
    def test_unknown_signal_returns_full_weight(self):
        tracker = DecayTracker()
        assert tracker.get_decay_factor("unknown_signal") == 1.0

    def test_healthy_signal_stays_at_one(self):
        tracker = DecayTracker(window_days=20, sharpe_floor=0.3, hit_rate_floor=0.45)

        # Record 20 days of good performance
        for i in range(20):
            tracker.record(
                signal_name="technical",
                run_date=date(2024, 6, i + 1),
                pnl=0.01,  # Consistent positive PnL
                hit=True,
            )

        factor = tracker.get_decay_factor("technical")
        assert factor >= 0.9  # Should be near 1.0

    def test_poor_signal_decays(self):
        tracker = DecayTracker(
            window_days=20, sharpe_floor=0.3, hit_rate_floor=0.45, decay_rate=0.5
        )

        # Record 20 days of poor performance
        for i in range(20):
            tracker.record(
                signal_name="bad_signal",
                run_date=date(2024, 6, i + 1),
                pnl=-0.01,  # Consistent negative PnL
                hit=False,
            )

        factor = tracker.get_decay_factor("bad_signal")
        assert factor < 0.5  # Should have decayed significantly

    def test_decay_never_reaches_zero(self):
        tracker = DecayTracker(window_days=15, decay_rate=0.5)

        # Record many days of terrible performance
        for i in range(30):
            tracker.record(
                signal_name="terrible",
                run_date=date(2024, 1, 1 + i) if i < 28 else date(2024, 2, i - 27),
                pnl=-0.05,
                hit=False,
            )

        factor = tracker.get_decay_factor("terrible")
        assert factor >= 0.05  # Floor prevents full zero

    def test_get_health_returns_metrics(self):
        tracker = DecayTracker(window_days=15)

        for i in range(15):
            tracker.record("tech", date(2024, 6, i + 1), pnl=0.005, hit=True)

        health = tracker.get_health("tech")
        assert health is not None
        assert health.signal_name == "tech"
        assert health.days_tracked == 15
        assert health.rolling_hit_rate == 1.0
