"""Tests for the regime-conditional weight matrix."""

from astraeus_ensemble.weights import RegimeWeightMatrix, WeightConfig


class TestRegimeWeightMatrix:
    def test_initial_weights_are_equal(self):
        signals = ["a", "b", "c"]
        regimes = ["risk_on", "risk_off"]
        matrix = RegimeWeightMatrix(signals=signals, regimes=regimes)

        weights = matrix.get_weights("risk_on")
        expected = 1.0 / 3
        for w in weights.values():
            assert abs(w - expected) < 1e-6

    def test_unknown_regime_returns_flat(self):
        matrix = RegimeWeightMatrix(signals=["a", "b"], regimes=["risk_on"])
        weights = matrix.get_weights("unknown_regime")
        assert abs(weights["a"] - 0.5) < 1e-6
        assert abs(weights["b"] - 0.5) < 1e-6

    def test_update_weights_from_performance(self):
        signals = ["tech", "macro", "ml"]
        matrix = RegimeWeightMatrix(
            signals=signals,
            regimes=["risk_on"],
            config=WeightConfig(shrinkage_factor=0.0),  # No shrinkage for test clarity
        )

        # tech performed 3x better than others
        matrix.update_weights("risk_on", {"tech": 0.6, "macro": 0.2, "ml": 0.2})

        weights = matrix.get_weights("risk_on")
        assert weights["tech"] > weights["macro"]
        assert weights["tech"] > weights["ml"]

    def test_shrinkage_pulls_toward_flat(self):
        signals = ["a", "b"]
        matrix = RegimeWeightMatrix(
            signals=signals,
            regimes=["risk_on"],
            config=WeightConfig(shrinkage_factor=1.0),  # Full shrinkage
        )

        # Even with extreme performance difference, shrinkage keeps flat
        matrix.update_weights("risk_on", {"a": 1.0, "b": 0.0})

        weights = matrix.get_weights("risk_on")
        # With full shrinkage, weights should be equal
        assert abs(weights["a"] - weights["b"]) < 0.01

    def test_weights_sum_to_one(self):
        signals = ["a", "b", "c", "d"]
        matrix = RegimeWeightMatrix(signals=signals, regimes=["r1"])
        matrix.update_weights("r1", {"a": 0.5, "b": 0.3, "c": 0.1, "d": 0.1})

        weights = matrix.get_weights("r1")
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-6
