"""Unit tests for the transaction cost model.

Tests commission, spread estimation, market impact, and slippage.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest
from astraeus_strategy.cost_model import (
    BROKER_ALPACA,
    BROKER_IB_PRO,
    BrokerProfile,
    CostBreakdown,
    CostModel,
    SpreadEstimator,
)


class TestBrokerProfile:
    """Test broker commission calculations."""

    @pytest.mark.unit
    def test_ib_pro_commission(self):
        """IB Pro: $0.0035/share, min $0.35."""
        comm = BROKER_IB_PRO.commission(1000, 150.0)
        assert comm == 3.50  # 1000 * 0.0035

    @pytest.mark.unit
    def test_ib_pro_minimum(self):
        """IB Pro minimum commission applies for small orders."""
        comm = BROKER_IB_PRO.commission(10, 150.0)
        assert comm == 0.35  # min applies (10 * 0.0035 = 0.035 < 0.35)

    @pytest.mark.unit
    def test_ib_pro_cap(self):
        """IB Pro commission capped at 1% of trade value."""
        # Very cheap stock: 1000 shares at $0.10 = $100 trade value
        # Raw: 1000 * 0.0035 = $3.50, cap: $100 * 0.01 = $1.00
        comm = BROKER_IB_PRO.commission(1000, 0.10)
        assert comm == 1.00

    @pytest.mark.unit
    def test_alpaca_zero_commission(self):
        """Alpaca has zero commission."""
        comm = BROKER_ALPACA.commission(5000, 200.0)
        assert comm == 0.0

    @pytest.mark.unit
    def test_custom_broker_profile(self):
        """Custom broker profile works correctly."""
        broker = BrokerProfile("custom", per_share=0.01, min_per_order=1.0, max_pct_of_trade=0.005)
        comm = broker.commission(500, 100.0)
        # 500 * 0.01 = 5.0, max(5.0, 1.0) = 5.0, min(5.0, 50000*0.005=250) = 5.0
        assert comm == 5.0


class TestSpreadEstimator:
    """Test spread estimation methods."""

    @pytest.mark.unit
    def test_fixed_bps_method(self):
        """Fixed BPS returns half the configured spread."""
        est = SpreadEstimator(method="fixed_bps", fixed_bps=10.0)
        half_spread = est.estimate_half_spread_bps()
        assert half_spread == 5.0

    @pytest.mark.unit
    def test_corwin_schultz_positive(self):
        """Corwin-Schultz returns positive half-spread."""
        est = SpreadEstimator(method="corwin_schultz")
        half_spread = est.estimate_half_spread_bps(high=152.0, low=148.0)
        assert half_spread > 0

    @pytest.mark.unit
    def test_corwin_schultz_floor(self):
        """Corwin-Schultz has a 1 bps floor."""
        est = SpreadEstimator(method="corwin_schultz")
        # Very tight range
        half_spread = est.estimate_half_spread_bps(high=100.01, low=100.00)
        assert half_spread >= 1.0

    @pytest.mark.unit
    def test_fallback_when_data_missing(self):
        """Falls back to fixed_bps when required data is missing."""
        est = SpreadEstimator(method="corwin_schultz", fixed_bps=8.0)
        half_spread = est.estimate_half_spread_bps()  # no high/low
        assert half_spread == 4.0  # fixed_bps / 2


class TestCostModel:
    """Test the full cost model."""

    @pytest.mark.unit
    def test_all_components_positive(self):
        """All cost components are non-negative."""
        model = CostModel(rng=np.random.default_rng(42))
        cost = model.compute(
            shares=1000,
            price=150.0,
            adv=5_000_000,
            sigma_daily=0.02,
            high=152.0,
            low=148.0,
        )
        assert cost.commission >= 0
        assert cost.spread_cost >= 0
        assert cost.impact_cost >= 0
        assert cost.slippage >= 0

    @pytest.mark.unit
    def test_total_is_sum_of_components(self):
        """Total cost equals sum of all components."""
        model = CostModel(rng=np.random.default_rng(42))
        cost = model.compute(shares=500, price=200.0, adv=1_000_000, sigma_daily=0.015)
        expected = cost.commission + cost.spread_cost + cost.impact_cost + cost.slippage
        assert abs(cost.total - expected) < 1e-10

    @pytest.mark.unit
    def test_larger_order_higher_impact(self):
        """Larger orders have higher market impact (square-root law)."""
        model = CostModel(rng=np.random.default_rng(42))
        small = model.compute(shares=100, price=150.0, adv=1_000_000, sigma_daily=0.02)
        large = model.compute(shares=10000, price=150.0, adv=1_000_000, sigma_daily=0.02)
        assert large.impact_cost > small.impact_cost

    @pytest.mark.unit
    def test_higher_volatility_higher_impact(self):
        """Higher volatility increases market impact."""
        model = CostModel(rng=np.random.default_rng(42))
        low_vol = model.compute(shares=1000, price=150.0, adv=1_000_000, sigma_daily=0.01)
        high_vol = model.compute(shares=1000, price=150.0, adv=1_000_000, sigma_daily=0.04)
        assert high_vol.impact_cost > low_vol.impact_cost

    @pytest.mark.unit
    def test_higher_adv_lower_impact(self):
        """Higher ADV (more liquid) reduces market impact."""
        model = CostModel(rng=np.random.default_rng(42))
        illiquid = model.compute(shares=1000, price=150.0, adv=100_000, sigma_daily=0.02)
        liquid = model.compute(shares=1000, price=150.0, adv=10_000_000, sigma_daily=0.02)
        assert liquid.impact_cost < illiquid.impact_cost

    @pytest.mark.unit
    def test_alpaca_zero_commission(self):
        """Alpaca broker has zero commission component."""
        model = CostModel(broker=BROKER_ALPACA, rng=np.random.default_rng(42))
        cost = model.compute(shares=1000, price=150.0, adv=1_000_000, sigma_daily=0.02)
        assert cost.commission == 0.0

    @pytest.mark.unit
    def test_latency_increases_slippage(self):
        """Higher latency increases slippage."""
        model = CostModel(rng=np.random.default_rng(42))
        no_latency = model.compute(
            shares=1000, price=150.0, adv=1_000_000, sigma_daily=0.02, latency_ms=0
        )
        model_2 = CostModel(rng=np.random.default_rng(42))
        high_latency = model_2.compute(
            shares=1000, price=150.0, adv=1_000_000, sigma_daily=0.02, latency_ms=500
        )
        assert high_latency.slippage >= no_latency.slippage

    @pytest.mark.unit
    def test_reproducible_with_same_rng(self):
        """Same RNG seed produces same slippage."""
        model1 = CostModel(rng=np.random.default_rng(123))
        model2 = CostModel(rng=np.random.default_rng(123))
        cost1 = model1.compute(shares=1000, price=150.0, adv=1_000_000, sigma_daily=0.02)
        cost2 = model2.compute(shares=1000, price=150.0, adv=1_000_000, sigma_daily=0.02)
        assert cost1.slippage == cost2.slippage


class TestCostBreakdown:
    """Test CostBreakdown dataclass."""

    @pytest.mark.unit
    def test_total_property(self):
        cb = CostBreakdown(commission=1.0, spread_cost=2.0, impact_cost=3.0, slippage=0.5)
        assert cb.total == 6.5

    @pytest.mark.unit
    def test_frozen_dataclass(self):
        """CostBreakdown is immutable."""
        cb = CostBreakdown(commission=1.0)
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            cb.commission = 2.0  # type: ignore
