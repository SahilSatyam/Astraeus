"""Property test for stress scenario PnL decomposition.

**Validates: Requirements 9.6**

Property 14: Stress scenario PnL decomposition — For any stress scenario
applied to any portfolio, the sum of all factor contributions plus all asset
contributions must equal the total scenario PnL within a rounding tolerance
of 0.01% of NAV.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume

from astraeus_portfolio.contracts import ScenarioName
from astraeus_portfolio.risk.stress import (
    StressContext,
    GFC2008Scenario,
    COVID2020Scenario,
    RateShockScenario,
    FlashCrashScenario,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tolerance: 0.01% of NAV (PnL is expressed as percentage of NAV)
PNL_DECOMPOSITION_TOLERANCE = Decimal("0.01")

# Available sectors for generating random portfolios
SECTORS = [
    "Financials",
    "Energy",
    "Materials",
    "Industrials",
    "Consumer Discretionary",
    "Information Technology",
    "Communication Services",
    "Health Care",
    "Consumer Staples",
    "Utilities",
    "Real Estate",
]


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_stress_context(draw: st.DrawFn) -> StressContext:
    """Generate a random StressContext with valid portfolio data.

    Generates:
    - n assets (2 to 8)
    - Random weights that sum to 1.0
    - Random returns history (T x n) with T >= 63 (enough for GFC)
    - Random factor loadings (n x k) with k in [1, 3]
    - Random sector assignments
    - Random ADV, prices, and NAV
    """
    n = draw(st.integers(min_value=2, max_value=8))
    k = draw(st.integers(min_value=1, max_value=3))
    t = draw(st.integers(min_value=63, max_value=100))

    # Generate symbols
    symbols = [f"SYM_{i}" for i in range(n)]

    # Generate weights that sum to 1.0 (long-only for simplicity)
    raw_weights = draw(
        st.lists(
            st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    weights_arr = np.array(raw_weights, dtype=np.float64)
    weights_arr = weights_arr / weights_arr.sum()  # Normalize to sum to 1.0

    # Generate returns history (T x n) with realistic daily returns
    returns_data = draw(
        st.lists(
            st.lists(
                st.floats(min_value=-0.10, max_value=0.10, allow_nan=False, allow_infinity=False),
                min_size=n,
                max_size=n,
            ),
            min_size=t,
            max_size=t,
        )
    )
    returns_history = np.array(returns_data, dtype=np.float64)

    # Generate factor loadings (n x k) with realistic values
    factor_data = draw(
        st.lists(
            st.lists(
                st.floats(min_value=0.2, max_value=2.0, allow_nan=False, allow_infinity=False),
                min_size=k,
                max_size=k,
            ),
            min_size=n,
            max_size=n,
        )
    )
    factor_loadings = np.array(factor_data, dtype=np.float64)

    # Generate sector map
    sector_assignments = draw(
        st.lists(
            st.sampled_from(SECTORS),
            min_size=n,
            max_size=n,
        )
    )
    sector_map = {symbols[i]: sector_assignments[i] for i in range(n)}

    # Generate ADV (average daily volume in shares)
    adv_data = draw(
        st.lists(
            st.floats(min_value=100_000.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    adv = np.array(adv_data, dtype=np.float64)

    # Generate prices
    prices_data = draw(
        st.lists(
            st.floats(min_value=5.0, max_value=500.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    prices = np.array(prices_data, dtype=np.float64)

    # NAV
    nav = Decimal("10000000")  # $10M

    # Seed
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))

    return StressContext(
        symbols=symbols,
        weights=weights_arr,
        returns_history=returns_history,
        factor_loadings=factor_loadings,
        sector_map=sector_map,
        adv=adv,
        prices=prices,
        nav=nav,
        seed=seed,
    )


@st.composite
def st_stress_context_no_factors(draw: st.DrawFn) -> StressContext:
    """Generate a StressContext without factor loadings (None).

    Tests the code path where factor decomposition falls back to
    attributing all PnL to assets.
    """
    n = draw(st.integers(min_value=2, max_value=8))
    t = draw(st.integers(min_value=63, max_value=100))

    symbols = [f"SYM_{i}" for i in range(n)]

    raw_weights = draw(
        st.lists(
            st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    weights_arr = np.array(raw_weights, dtype=np.float64)
    weights_arr = weights_arr / weights_arr.sum()

    returns_data = draw(
        st.lists(
            st.lists(
                st.floats(min_value=-0.10, max_value=0.10, allow_nan=False, allow_infinity=False),
                min_size=n,
                max_size=n,
            ),
            min_size=t,
            max_size=t,
        )
    )
    returns_history = np.array(returns_data, dtype=np.float64)

    sector_assignments = draw(
        st.lists(
            st.sampled_from(SECTORS),
            min_size=n,
            max_size=n,
        )
    )
    sector_map = {symbols[i]: sector_assignments[i] for i in range(n)}

    adv_data = draw(
        st.lists(
            st.floats(min_value=100_000.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    adv = np.array(adv_data, dtype=np.float64)

    prices_data = draw(
        st.lists(
            st.floats(min_value=5.0, max_value=500.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    prices = np.array(prices_data, dtype=np.float64)

    nav = Decimal("10000000")
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))

    return StressContext(
        symbols=symbols,
        weights=weights_arr,
        returns_history=returns_history,
        factor_loadings=None,
        sector_map=sector_map,
        adv=adv,
        prices=prices,
        nav=nav,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Property 14: Stress scenario PnL decomposition
# ---------------------------------------------------------------------------


class TestStressPnLDecomposition:
    """Property 14: Stress scenario PnL decomposition.

    **Validates: Requirements 9.6**

    For any stress scenario applied to any portfolio, the sum of all factor
    contributions plus all asset contributions must equal the total scenario
    PnL within a rounding tolerance of 0.01% of NAV.
    """

    # --- GFC 2008 Scenario ---

    @given(ctx=st_stress_context())
    @settings(max_examples=100, deadline=None)
    def test_gfc2008_pnl_decomposition_with_factors(self, ctx: StressContext) -> None:
        """GFC 2008 scenario PnL decomposes correctly with factor loadings."""
        scenario = GFC2008Scenario()
        result = scenario.apply(ctx.weights, ctx)

        factor_sum = sum(result.factor_contributions.values(), Decimal("0"))
        asset_sum = sum(result.asset_contributions.values(), Decimal("0"))
        total_contributions = factor_sum + asset_sum

        diff = abs(total_contributions - result.total_pnl_pct)
        assert diff <= PNL_DECOMPOSITION_TOLERANCE, (
            f"GFC 2008 PnL decomposition mismatch: "
            f"factor_sum={factor_sum}, asset_sum={asset_sum}, "
            f"total_contributions={total_contributions}, "
            f"total_pnl_pct={result.total_pnl_pct}, diff={diff}"
        )

    @given(ctx=st_stress_context_no_factors())
    @settings(max_examples=100, deadline=None)
    def test_gfc2008_pnl_decomposition_no_factors(self, ctx: StressContext) -> None:
        """GFC 2008 scenario PnL decomposes correctly without factor loadings."""
        scenario = GFC2008Scenario()
        result = scenario.apply(ctx.weights, ctx)

        factor_sum = sum(result.factor_contributions.values(), Decimal("0"))
        asset_sum = sum(result.asset_contributions.values(), Decimal("0"))
        total_contributions = factor_sum + asset_sum

        diff = abs(total_contributions - result.total_pnl_pct)
        assert diff <= PNL_DECOMPOSITION_TOLERANCE, (
            f"GFC 2008 (no factors) PnL decomposition mismatch: "
            f"total_contributions={total_contributions}, "
            f"total_pnl_pct={result.total_pnl_pct}, diff={diff}"
        )

    # --- COVID 2020 Scenario ---

    @given(ctx=st_stress_context())
    @settings(max_examples=100, deadline=None)
    def test_covid2020_pnl_decomposition_with_factors(self, ctx: StressContext) -> None:
        """COVID 2020 scenario PnL decomposes correctly with factor loadings."""
        scenario = COVID2020Scenario()
        result = scenario.apply(ctx.weights, ctx)

        factor_sum = sum(result.factor_contributions.values(), Decimal("0"))
        asset_sum = sum(result.asset_contributions.values(), Decimal("0"))
        total_contributions = factor_sum + asset_sum

        diff = abs(total_contributions - result.total_pnl_pct)
        assert diff <= PNL_DECOMPOSITION_TOLERANCE, (
            f"COVID 2020 PnL decomposition mismatch: "
            f"total_contributions={total_contributions}, "
            f"total_pnl_pct={result.total_pnl_pct}, diff={diff}"
        )

    @given(ctx=st_stress_context_no_factors())
    @settings(max_examples=100, deadline=None)
    def test_covid2020_pnl_decomposition_no_factors(self, ctx: StressContext) -> None:
        """COVID 2020 scenario PnL decomposes correctly without factor loadings."""
        scenario = COVID2020Scenario()
        result = scenario.apply(ctx.weights, ctx)

        factor_sum = sum(result.factor_contributions.values(), Decimal("0"))
        asset_sum = sum(result.asset_contributions.values(), Decimal("0"))
        total_contributions = factor_sum + asset_sum

        diff = abs(total_contributions - result.total_pnl_pct)
        assert diff <= PNL_DECOMPOSITION_TOLERANCE, (
            f"COVID 2020 (no factors) PnL decomposition mismatch: "
            f"total_contributions={total_contributions}, "
            f"total_pnl_pct={result.total_pnl_pct}, diff={diff}"
        )

    # --- Rate Shock Scenario ---

    @given(ctx=st_stress_context())
    @settings(max_examples=100, deadline=None)
    def test_rate_shock_pnl_decomposition_with_factors(self, ctx: StressContext) -> None:
        """Rate shock scenario PnL decomposes correctly with factor loadings."""
        scenario = RateShockScenario()
        result = scenario.apply(ctx.weights, ctx)

        factor_sum = sum(result.factor_contributions.values(), Decimal("0"))
        asset_sum = sum(result.asset_contributions.values(), Decimal("0"))
        total_contributions = factor_sum + asset_sum

        diff = abs(total_contributions - result.total_pnl_pct)
        assert diff <= PNL_DECOMPOSITION_TOLERANCE, (
            f"Rate shock PnL decomposition mismatch: "
            f"total_contributions={total_contributions}, "
            f"total_pnl_pct={result.total_pnl_pct}, diff={diff}"
        )

    @given(ctx=st_stress_context_no_factors())
    @settings(max_examples=100, deadline=None)
    def test_rate_shock_pnl_decomposition_no_factors(self, ctx: StressContext) -> None:
        """Rate shock scenario PnL decomposes correctly without factor loadings."""
        scenario = RateShockScenario()
        result = scenario.apply(ctx.weights, ctx)

        factor_sum = sum(result.factor_contributions.values(), Decimal("0"))
        asset_sum = sum(result.asset_contributions.values(), Decimal("0"))
        total_contributions = factor_sum + asset_sum

        diff = abs(total_contributions - result.total_pnl_pct)
        assert diff <= PNL_DECOMPOSITION_TOLERANCE, (
            f"Rate shock (no factors) PnL decomposition mismatch: "
            f"total_contributions={total_contributions}, "
            f"total_pnl_pct={result.total_pnl_pct}, diff={diff}"
        )

    # --- Flash Crash Scenario ---

    @given(ctx=st_stress_context())
    @settings(max_examples=100, deadline=None)
    def test_flash_crash_pnl_decomposition_with_factors(self, ctx: StressContext) -> None:
        """Flash crash scenario PnL decomposes correctly with factor loadings."""
        scenario = FlashCrashScenario()
        result = scenario.apply(ctx.weights, ctx)

        factor_sum = sum(result.factor_contributions.values(), Decimal("0"))
        asset_sum = sum(result.asset_contributions.values(), Decimal("0"))
        total_contributions = factor_sum + asset_sum

        diff = abs(total_contributions - result.total_pnl_pct)
        assert diff <= PNL_DECOMPOSITION_TOLERANCE, (
            f"Flash crash PnL decomposition mismatch: "
            f"total_contributions={total_contributions}, "
            f"total_pnl_pct={result.total_pnl_pct}, diff={diff}"
        )

    @given(ctx=st_stress_context_no_factors())
    @settings(max_examples=100, deadline=None)
    def test_flash_crash_pnl_decomposition_no_factors(self, ctx: StressContext) -> None:
        """Flash crash scenario PnL decomposes correctly without factor loadings."""
        scenario = FlashCrashScenario()
        result = scenario.apply(ctx.weights, ctx)

        factor_sum = sum(result.factor_contributions.values(), Decimal("0"))
        asset_sum = sum(result.asset_contributions.values(), Decimal("0"))
        total_contributions = factor_sum + asset_sum

        diff = abs(total_contributions - result.total_pnl_pct)
        assert diff <= PNL_DECOMPOSITION_TOLERANCE, (
            f"Flash crash (no factors) PnL decomposition mismatch: "
            f"total_contributions={total_contributions}, "
            f"total_pnl_pct={result.total_pnl_pct}, diff={diff}"
        )
