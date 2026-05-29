"""Unit tests for BoxConstraint and LiquidityConstraint."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import cvxpy as cp
import numpy as np
import pytest

from astraeus_portfolio.constraints import BoxConstraint, LiquidityConstraint
from astraeus_portfolio.contracts import OptContext


@pytest.fixture
def ctx_5_assets() -> OptContext:
    """Create a 5-asset OptContext for testing."""
    n = 5
    return OptContext(
        strategy_id="test",
        as_of_ts=datetime(2024, 1, 1),
        n_assets=n,
        symbols=["A", "B", "C", "D", "E"],
        expected_returns=np.array([0.01] * n),
        covariance=np.eye(n) * 0.01,
        current_weights=np.array([0.2, 0.2, 0.2, 0.2, 0.2]),
        prices=np.array([100.0, 50.0, 200.0, 75.0, 150.0]),
        adv=np.array([1_000_000.0, 500_000.0, 200_000.0, 800_000.0, 600_000.0]),
        sector_map={"A": "Tech", "B": "Health", "C": "Finance", "D": "Tech", "E": "Energy"},
        beta=np.array([1.0] * n),
        factor_loadings=None,
        views=None,
        scenarios=None,
        regime_label=None,
        constraints=[],
        nav=Decimal("10000000"),
        seed=42,
    )


# ---------------------------------------------------------------------------
# BoxConstraint tests
# ---------------------------------------------------------------------------


class TestBoxConstraint:
    """Tests for BoxConstraint."""

    def test_default_params(self) -> None:
        box = BoxConstraint()
        assert box.name == "box"
        assert box.priority == 0
        assert box.relaxable is False
        assert box.w_max == 0.10
        assert box.l_max == 1.0

    def test_custom_params(self) -> None:
        box = BoxConstraint(w_max=0.05, l_max=1.5)
        assert box.w_max == 0.05
        assert box.l_max == 1.5

    def test_invalid_w_max(self) -> None:
        with pytest.raises(ValueError, match="w_max"):
            BoxConstraint(w_max=0.0)
        with pytest.raises(ValueError, match="w_max"):
            BoxConstraint(w_max=1.5)
        with pytest.raises(ValueError, match="w_max"):
            BoxConstraint(w_max=-0.1)

    def test_invalid_l_max(self) -> None:
        with pytest.raises(ValueError, match="l_max"):
            BoxConstraint(l_max=0.0)
        with pytest.raises(ValueError, match="l_max"):
            BoxConstraint(l_max=-1.0)

    def test_to_cvxpy_returns_three_constraints(self, ctx_5_assets: OptContext) -> None:
        box = BoxConstraint()
        w = cp.Variable(5)
        constraints = box.to_cvxpy(w, ctx_5_assets)
        assert len(constraints) == 3

    def test_to_cvxpy_feasible_solution(self, ctx_5_assets: OptContext) -> None:
        """Verify that a feasible solution exists with box constraints."""
        box = BoxConstraint(w_max=0.10, l_max=1.0)
        w = cp.Variable(5)
        constraints = box.to_cvxpy(w, ctx_5_assets)
        # Equal weight at 0.10 should be feasible (sum = 0.5 <= 1.0)
        prob = cp.Problem(
            cp.Minimize(cp.sum_squares(w - 0.10)),
            constraints,
        )
        prob.solve()
        assert prob.status in ("optimal", "optimal_inaccurate")
        assert np.all(w.value >= -1e-8)
        assert np.all(w.value <= 0.10 + 1e-8)

    def test_diagnostic_satisfied(self, ctx_5_assets: OptContext) -> None:
        box = BoxConstraint(w_max=0.10, l_max=1.0)
        w_val = np.array([0.05, 0.08, 0.10, 0.02, 0.03])
        diag = box.diagnostic(w_val, ctx_5_assets)
        assert diag["satisfied"] is True
        assert diag["max_weight"] == pytest.approx(0.10)
        assert diag["min_weight"] == pytest.approx(0.02)
        assert diag["gross_leverage"] == pytest.approx(0.28)

    def test_diagnostic_violated_weight(self, ctx_5_assets: OptContext) -> None:
        box = BoxConstraint(w_max=0.10, l_max=1.0)
        w_val = np.array([0.15, 0.08, 0.10, 0.02, 0.03])  # 0.15 > 0.10
        diag = box.diagnostic(w_val, ctx_5_assets)
        assert diag["satisfied"] is False

    def test_diagnostic_violated_negative(self, ctx_5_assets: OptContext) -> None:
        box = BoxConstraint(w_max=0.10, l_max=1.0)
        w_val = np.array([-0.05, 0.08, 0.10, 0.02, 0.03])
        diag = box.diagnostic(w_val, ctx_5_assets)
        assert diag["satisfied"] is False

    def test_diagnostic_violated_leverage(self, ctx_5_assets: OptContext) -> None:
        box = BoxConstraint(w_max=0.30, l_max=1.0)
        w_val = np.array([0.25, 0.25, 0.25, 0.25, 0.25])  # sum = 1.25 > 1.0
        diag = box.diagnostic(w_val, ctx_5_assets)
        assert diag["satisfied"] is False
        assert diag["gross_leverage"] == pytest.approx(1.25)


# ---------------------------------------------------------------------------
# LiquidityConstraint tests
# ---------------------------------------------------------------------------


class TestLiquidityConstraint:
    """Tests for LiquidityConstraint."""

    def test_default_params(self) -> None:
        liq = LiquidityConstraint()
        assert liq.name == "liquidity"
        assert liq.priority == 0
        assert liq.relaxable is False
        assert liq.adv_pct == 0.05

    def test_custom_params(self) -> None:
        liq = LiquidityConstraint(adv_pct=0.10)
        assert liq.adv_pct == 0.10

    def test_invalid_adv_pct(self) -> None:
        with pytest.raises(ValueError, match="adv_pct"):
            LiquidityConstraint(adv_pct=0.0)
        with pytest.raises(ValueError, match="adv_pct"):
            LiquidityConstraint(adv_pct=-0.1)
        with pytest.raises(ValueError, match="adv_pct"):
            LiquidityConstraint(adv_pct=1.5)

    def test_to_cvxpy_returns_one_constraint(self, ctx_5_assets: OptContext) -> None:
        liq = LiquidityConstraint()
        w = cp.Variable(5)
        constraints = liq.to_cvxpy(w, ctx_5_assets)
        assert len(constraints) == 1

    def test_to_cvxpy_feasible_no_trade(self, ctx_5_assets: OptContext) -> None:
        """No trade (w == w_prev) should always be feasible."""
        liq = LiquidityConstraint(adv_pct=0.05)
        w = cp.Variable(5)
        constraints = liq.to_cvxpy(w, ctx_5_assets)
        # Target the current weights (no trade)
        prob = cp.Problem(
            cp.Minimize(cp.sum_squares(w - ctx_5_assets.current_weights)),
            constraints,
        )
        prob.solve()
        assert prob.status in ("optimal", "optimal_inaccurate")
        np.testing.assert_allclose(w.value, ctx_5_assets.current_weights, atol=1e-6)

    def test_diagnostic_satisfied(self, ctx_5_assets: OptContext) -> None:
        """Small trade within ADV limits."""
        liq = LiquidityConstraint(adv_pct=0.05)
        # current_weights = [0.2, 0.2, 0.2, 0.2, 0.2]
        # Small change: trade = |0.19 - 0.2| * 10M = 100,000
        # ADV capacity for asset A: 0.05 * 1,000,000 * 100 = 5,000,000
        w_val = np.array([0.19, 0.21, 0.20, 0.20, 0.20])
        diag = liq.diagnostic(w_val, ctx_5_assets)
        assert diag["satisfied"] is True
        assert diag["n_breaching"] == 0

    def test_diagnostic_violated(self, ctx_5_assets: OptContext) -> None:
        """Large trade exceeding ADV limits for asset C (small ADV)."""
        liq = LiquidityConstraint(adv_pct=0.05)
        # Asset C: ADV=200,000, price=200 => capacity = 0.05 * 200,000 * 200 = 2,000,000
        # Trade for C: |0.0 - 0.2| * 10,000,000 = 2,000,000 (exactly at limit)
        # Make it exceed: |0.0 - 0.2| * 10,000,000 = 2,000,000 vs capacity 2,000,000
        # Use a bigger trade
        w_val = np.array([0.2, 0.2, -0.01, 0.2, 0.2])  # trade = 0.21 * 10M = 2,100,000 > 2M
        diag = liq.diagnostic(w_val, ctx_5_assets)
        assert diag["satisfied"] is False
        assert diag["n_breaching"] >= 1

    def test_diagnostic_max_trade_pct(self, ctx_5_assets: OptContext) -> None:
        """Verify max_trade_pct_adv calculation."""
        liq = LiquidityConstraint(adv_pct=0.05)
        # Asset A: trade = |0.1 - 0.2| * 10M = 1,000,000
        # Capacity A: 0.05 * 1,000,000 * 100 = 5,000,000
        # trade_pct = 1,000,000 / (1,000,000 * 100) = 0.01
        # Wait, capacity is adv * price = 1,000,000 * 100 = 100,000,000
        # trade_pct = 1,000,000 / 100,000,000 = 0.01
        w_val = np.array([0.1, 0.2, 0.2, 0.2, 0.2])
        diag = liq.diagnostic(w_val, ctx_5_assets)
        # trade for A: |0.1 - 0.2| * 10M = 1M
        # adv_capacity for A: 1,000,000 * 100 = 100,000,000
        # pct = 1M / 100M = 0.01
        assert diag["max_trade_pct_adv"] == pytest.approx(0.01)
        assert diag["satisfied"] is True
