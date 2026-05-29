"""Property test for VaR/CVaR relationship invariant.

**Validates: Requirements 8.1, 8.4**

Property 13: For any valid portfolio return series, CVaR must always be
greater than or equal to VaR at the same confidence level. This holds for
all three methods (historical, parametric, Monte Carlo) and both confidence
levels (95%, 99%).

Additionally, VaR at 99% >= VaR at 95% for each method (higher confidence
implies higher VaR).
"""

from __future__ import annotations

import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume

from astraeus_portfolio.risk.var_cvar import (
    VaRConfig,
    VaRMethod,
    compute_var_cvar,
)


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_portfolio_returns(draw: st.DrawFn) -> np.ndarray:
    """Generate a valid portfolio return series for VaR/CVaR computation.

    Constraints:
    - At least 60 days (min_observations requirement)
    - No NaN or Inf values
    - Realistic daily return magnitudes in [-0.10, 0.10]
    """
    n_days = draw(st.integers(min_value=60, max_value=300))

    returns = draw(
        st.lists(
            st.floats(
                min_value=-0.10,
                max_value=0.10,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=n_days,
            max_size=n_days,
        )
    )
    arr = np.array(returns, dtype=np.float64)

    # Ensure not all returns are identical (would cause zero std dev issues)
    assume(np.std(arr) > 1e-10)

    return arr


# ---------------------------------------------------------------------------
# Property 13: VaR/CVaR relationship invariant
# ---------------------------------------------------------------------------


class TestVaRCVaRRelationshipInvariant:
    """Property 13: VaR/CVaR relationship invariant.

    **Validates: Requirements 8.1, 8.4**

    For any valid portfolio return series:
    1. CVaR >= VaR at the same confidence level for all methods
    2. VaR at 99% >= VaR at 95% for each method
    """

    @given(returns=st_portfolio_returns())
    @settings(max_examples=200, deadline=None)
    def test_cvar_geq_var_all_methods(self, returns: np.ndarray) -> None:
        """CVaR must be >= VaR at the same confidence level for all methods."""
        config = VaRConfig(
            confidence_levels=(0.95, 0.99),
            min_observations=60,
        )

        report = compute_var_cvar(returns, config=config, seed=42)

        for result in report.results:
            assert result.cvar_pct >= result.var_pct, (
                f"CVaR ({result.cvar_pct:.6f}%) < VaR ({result.var_pct:.6f}%) "
                f"for method={result.method}, confidence={result.confidence_level}"
            )

    @given(returns=st_portfolio_returns())
    @settings(max_examples=200, deadline=None)
    def test_var_99_geq_var_95_per_method(self, returns: np.ndarray) -> None:
        """VaR at 99% confidence must be >= VaR at 95% for each method."""
        config = VaRConfig(
            confidence_levels=(0.95, 0.99),
            min_observations=60,
        )

        report = compute_var_cvar(returns, config=config, seed=42)

        # Group results by method
        for method in VaRMethod:
            method_results = [r for r in report.results if r.method == method]
            if len(method_results) < 2:
                continue

            var_by_confidence = {
                r.confidence_level: r.var_pct for r in method_results
            }

            if 0.95 in var_by_confidence and 0.99 in var_by_confidence:
                assert var_by_confidence[0.99] >= var_by_confidence[0.95], (
                    f"VaR at 99% ({var_by_confidence[0.99]:.6f}%) < "
                    f"VaR at 95% ({var_by_confidence[0.95]:.6f}%) "
                    f"for method={method}"
                )
