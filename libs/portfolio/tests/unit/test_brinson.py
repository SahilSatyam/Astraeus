"""Unit tests for Brinson-Fachler sector attribution."""

from datetime import datetime
from uuid import uuid4

import pytest
from astraeus_portfolio.attribution.brinson import (
    UNCLASSIFIED_SECTOR,
    BrinsonAttributionError,
    BrinsonResult,
    run_brinson,
)


@pytest.fixture
def portfolio_id():
    return uuid4()


@pytest.fixture
def as_of_ts():
    return datetime(2024, 1, 15, 16, 30, 0)


class TestBrinsonBasicDecomposition:
    """Test the core Brinson-Fachler decomposition formulas."""

    def test_simple_two_sector_attribution(self, portfolio_id, as_of_ts):
        """Two sectors with known weights and returns produce correct effects."""
        # Portfolio: 60% Tech, 40% Healthcare
        # Benchmark: 50% Tech, 50% Healthcare
        portfolio_weights = {"AAPL": 0.30, "MSFT": 0.30, "JNJ": 0.20, "PFE": 0.20}
        benchmark_weights = {"AAPL": 0.25, "MSFT": 0.25, "JNJ": 0.25, "PFE": 0.25}

        # Returns
        portfolio_returns = {"AAPL": 0.02, "MSFT": 0.03, "JNJ": 0.01, "PFE": 0.005}
        benchmark_returns = {"AAPL": 0.015, "MSFT": 0.025, "JNJ": 0.008, "PFE": 0.004}

        sector_map = {
            "AAPL": "Information Technology",
            "MSFT": "Information Technology",
            "JNJ": "Health Care",
            "PFE": "Health Care",
        }

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        assert isinstance(result, BrinsonResult)
        assert result.portfolio_id == portfolio_id
        assert result.as_of_ts == as_of_ts
        assert result.benchmark == "SPY"
        assert len(result.sector_effects) == 2

    def test_effects_sum_to_active_return(self, portfolio_id, as_of_ts):
        """Sum of all effects across sectors equals total active return."""
        portfolio_weights = {"AAPL": 0.40, "MSFT": 0.20, "JNJ": 0.25, "XOM": 0.15}
        benchmark_weights = {"AAPL": 0.30, "MSFT": 0.30, "JNJ": 0.20, "XOM": 0.20}

        portfolio_returns = {"AAPL": 0.03, "MSFT": 0.01, "JNJ": -0.01, "XOM": 0.02}
        benchmark_returns = {"AAPL": 0.025, "MSFT": 0.015, "JNJ": -0.005, "XOM": 0.018}

        sector_map = {
            "AAPL": "Information Technology",
            "MSFT": "Information Technology",
            "JNJ": "Health Care",
            "XOM": "Energy",
        }

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        # Compute expected active return
        port_return = sum(portfolio_weights[s] * portfolio_returns[s] for s in portfolio_weights)
        bench_return = sum(benchmark_weights[s] * benchmark_returns[s] for s in benchmark_weights)
        expected_active_bps = (port_return - bench_return) * 10000

        # Sum of effects should equal active return within 0.01 bps
        assert abs(float(result.total_active_return_bps) - expected_active_bps) < 0.01

    def test_allocation_effect_formula(self, portfolio_id, as_of_ts):
        """Allocation effect: (w_p_s - w_b_s) * (r_b_s - r_b)."""
        # Single stock per sector for easy manual calculation
        portfolio_weights = {"AAPL": 0.70, "JNJ": 0.30}
        benchmark_weights = {"AAPL": 0.50, "JNJ": 0.50}

        portfolio_returns = {"AAPL": 0.02, "JNJ": 0.01}
        benchmark_returns = {"AAPL": 0.02, "JNJ": 0.01}

        sector_map = {"AAPL": "Information Technology", "JNJ": "Health Care"}

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        # r_b = 0.50*0.02 + 0.50*0.01 = 0.015
        # Tech allocation: (0.70 - 0.50) * (0.02 - 0.015) = 0.20 * 0.005 = 0.001 = 10 bps
        # HC allocation: (0.30 - 0.50) * (0.01 - 0.015) = -0.20 * -0.005 = 0.001 = 10 bps
        tech_effect = next(e for e in result.sector_effects if e.sector == "Information Technology")
        hc_effect = next(e for e in result.sector_effects if e.sector == "Health Care")

        assert abs(float(tech_effect.allocation_bps) - 10.0) < 0.01
        assert abs(float(hc_effect.allocation_bps) - 10.0) < 0.01

    def test_selection_effect_formula(self, portfolio_id, as_of_ts):
        """Selection effect: w_b_s * (r_p_s - r_b_s)."""
        # Same weights, different returns
        portfolio_weights = {"AAPL": 0.50, "JNJ": 0.50}
        benchmark_weights = {"AAPL": 0.50, "JNJ": 0.50}

        portfolio_returns = {"AAPL": 0.03, "JNJ": 0.01}
        benchmark_returns = {"AAPL": 0.02, "JNJ": 0.01}

        sector_map = {"AAPL": "Information Technology", "JNJ": "Health Care"}

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        # Tech selection: 0.50 * (0.03 - 0.02) = 0.005 = 50 bps
        # HC selection: 0.50 * (0.01 - 0.01) = 0 bps
        tech_effect = next(e for e in result.sector_effects if e.sector == "Information Technology")
        hc_effect = next(e for e in result.sector_effects if e.sector == "Health Care")

        assert abs(float(tech_effect.selection_bps) - 50.0) < 0.01
        assert abs(float(hc_effect.selection_bps) - 0.0) < 0.01

    def test_interaction_effect_formula(self, portfolio_id, as_of_ts):
        """Interaction effect: (w_p_s - w_b_s) * (r_p_s - r_b_s)."""
        portfolio_weights = {"AAPL": 0.70, "JNJ": 0.30}
        benchmark_weights = {"AAPL": 0.50, "JNJ": 0.50}

        portfolio_returns = {"AAPL": 0.03, "JNJ": 0.01}
        benchmark_returns = {"AAPL": 0.02, "JNJ": 0.01}

        sector_map = {"AAPL": "Information Technology", "JNJ": "Health Care"}

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        # Tech interaction: (0.70 - 0.50) * (0.03 - 0.02) = 0.20 * 0.01 = 0.002 = 20 bps
        # HC interaction: (0.30 - 0.50) * (0.01 - 0.01) = -0.20 * 0.0 = 0 bps
        tech_effect = next(e for e in result.sector_effects if e.sector == "Information Technology")
        hc_effect = next(e for e in result.sector_effects if e.sector == "Health Care")

        assert abs(float(tech_effect.interaction_bps) - 20.0) < 0.01
        assert abs(float(hc_effect.interaction_bps) - 0.0) < 0.01


class TestBrinsonEdgeCases:
    """Test edge cases and special handling."""

    def test_sector_in_portfolio_not_in_benchmark(self, portfolio_id, as_of_ts):
        """Sectors in portfolio but not benchmark get benchmark weight/return = 0."""
        portfolio_weights = {"AAPL": 0.50, "TSLA": 0.50}
        benchmark_weights = {"AAPL": 1.0}

        portfolio_returns = {"AAPL": 0.02, "TSLA": 0.05}
        benchmark_returns = {"AAPL": 0.02}

        sector_map = {
            "AAPL": "Information Technology",
            "TSLA": "Consumer Discretionary",
        }

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        # Consumer Discretionary: benchmark weight = 0, benchmark return = 0
        cd_effect = next(e for e in result.sector_effects if e.sector == "Consumer Discretionary")
        # Allocation: (0.50 - 0.0) * (0.0 - r_b) where r_b = 1.0*0.02 = 0.02
        # = 0.50 * (-0.02) = -0.01 = -100 bps
        assert abs(float(cd_effect.allocation_bps) - (-100.0)) < 0.01
        # Selection: 0.0 * (0.05 - 0.0) = 0
        assert abs(float(cd_effect.selection_bps)) < 0.01
        # Interaction: (0.50 - 0.0) * (0.05 - 0.0) = 0.025 = 250 bps
        assert abs(float(cd_effect.interaction_bps) - 250.0) < 0.01

    def test_unclassified_holdings(self, portfolio_id, as_of_ts):
        """Holdings without sector classification go to 'Unclassified'."""
        portfolio_weights = {"AAPL": 0.50, "UNKNOWN": 0.50}
        benchmark_weights = {"AAPL": 1.0}

        portfolio_returns = {"AAPL": 0.02, "UNKNOWN": 0.01}
        benchmark_returns = {"AAPL": 0.02}

        # Only AAPL has a sector classification
        sector_map = {"AAPL": "Information Technology"}

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        sector_names = [e.sector for e in result.sector_effects]
        assert UNCLASSIFIED_SECTOR in sector_names

    def test_reject_no_classified_holdings(self, portfolio_id, as_of_ts):
        """Reject if < 1 holding has valid sector classification."""
        portfolio_weights = {"UNKNOWN1": 0.50, "UNKNOWN2": 0.50}
        benchmark_weights = {"AAPL": 1.0}

        portfolio_returns = {"UNKNOWN1": 0.02, "UNKNOWN2": 0.01}
        benchmark_returns = {"AAPL": 0.02}

        # No holdings in sector_map
        sector_map = {"AAPL": "Information Technology"}

        with pytest.raises(BrinsonAttributionError, match="Insufficient classified"):
            run_brinson(
                portfolio_id=portfolio_id,
                as_of_ts=as_of_ts,
                portfolio_weights=portfolio_weights,
                benchmark_weights=benchmark_weights,
                portfolio_returns=portfolio_returns,
                benchmark_returns=benchmark_returns,
                sector_map=sector_map,
            )

    def test_single_holding_single_sector(self, portfolio_id, as_of_ts):
        """Minimal case: one holding, one sector."""
        portfolio_weights = {"AAPL": 1.0}
        benchmark_weights = {"AAPL": 1.0}

        portfolio_returns = {"AAPL": 0.02}
        benchmark_returns = {"AAPL": 0.015}

        sector_map = {"AAPL": "Information Technology"}

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        assert len(result.sector_effects) == 1
        # Same weights, so allocation = 0, interaction = 0
        # Selection = 1.0 * (0.02 - 0.015) = 0.005 = 50 bps
        effect = result.sector_effects[0]
        assert abs(float(effect.allocation_bps)) < 0.01
        assert abs(float(effect.selection_bps) - 50.0) < 0.01
        assert abs(float(effect.interaction_bps)) < 0.01

    def test_zero_returns(self, portfolio_id, as_of_ts):
        """All zero returns produce zero effects."""
        portfolio_weights = {"AAPL": 0.60, "JNJ": 0.40}
        benchmark_weights = {"AAPL": 0.50, "JNJ": 0.50}

        portfolio_returns = {"AAPL": 0.0, "JNJ": 0.0}
        benchmark_returns = {"AAPL": 0.0, "JNJ": 0.0}

        sector_map = {"AAPL": "Information Technology", "JNJ": "Health Care"}

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        for effect in result.sector_effects:
            assert abs(float(effect.allocation_bps)) < 0.01
            assert abs(float(effect.selection_bps)) < 0.01
            assert abs(float(effect.interaction_bps)) < 0.01

        assert abs(float(result.total_active_return_bps)) < 0.01


class TestBrinsonResultConversion:
    """Test conversion to AttributionResult."""

    def test_to_attribution_result(self, portfolio_id, as_of_ts):
        """BrinsonResult converts correctly to AttributionResult."""
        portfolio_weights = {"AAPL": 0.60, "JNJ": 0.40}
        benchmark_weights = {"AAPL": 0.50, "JNJ": 0.50}

        portfolio_returns = {"AAPL": 0.03, "JNJ": 0.01}
        benchmark_returns = {"AAPL": 0.02, "JNJ": 0.01}

        sector_map = {"AAPL": "Information Technology", "JNJ": "Health Care"}

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
        )

        attr_result = result.to_attribution_result()

        assert attr_result.portfolio_id == portfolio_id
        assert attr_result.method == "brinson"
        assert attr_result.factor_pnl is None
        assert attr_result.idio_pnl_bps is None
        assert attr_result.sector_pnl is not None
        # Should have 3 entries per sector (allocation, selection, interaction)
        assert len(attr_result.sector_pnl) == 2 * 3  # 2 sectors * 3 effects

    def test_custom_benchmark_name(self, portfolio_id, as_of_ts):
        """Custom benchmark name is stored in result."""
        portfolio_weights = {"AAPL": 1.0}
        benchmark_weights = {"AAPL": 1.0}
        portfolio_returns = {"AAPL": 0.02}
        benchmark_returns = {"AAPL": 0.02}
        sector_map = {"AAPL": "Information Technology"}

        result = run_brinson(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_map=sector_map,
            benchmark_name="QQQ",
        )

        assert result.benchmark == "QQQ"
