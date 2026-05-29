"""Property test for covariance volatility round-trip.

**Validates: Requirements 1.8**

FOR ALL valid return inputs, estimating covariance then extracting the diagonal
then taking the square root SHALL produce annualized volatilities (using a factor
of sqrt(252)) within 1% relative error of directly computed asset volatilities
(round-trip consistency).

This property holds for the Sample estimator which computes the unbiased sample
covariance (ddof=1). The Ledoit-Wolf estimator shrinks toward identity so it may
not satisfy this exactly.
"""

from __future__ import annotations

import hypothesis.strategies as st
import numpy as np
from astraeus_portfolio.contracts import CovarianceConfig
from astraeus_portfolio.covariance.sample import SampleCovarianceEstimator
from hypothesis import assume, given, settings

# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_valid_return_matrix(draw: st.DrawFn) -> np.ndarray:
    """Generate a valid T×n return matrix where T >= n+1, no NaN/Inf.

    Constrains values to realistic daily return magnitudes to avoid
    numerical issues while still exploring a wide input space.
    """
    n_assets = draw(st.integers(min_value=1, max_value=10))
    # T must be >= n+1 for valid covariance estimation
    n_obs = draw(st.integers(min_value=n_assets + 1, max_value=max(n_assets + 1, 100)))

    # Generate returns in a realistic range (-0.5 to 0.5 daily)
    # Use floats strategy for each element to get good Hypothesis shrinking
    returns = draw(
        st.lists(
            st.lists(
                st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
                min_size=n_assets,
                max_size=n_assets,
            ),
            min_size=n_obs,
            max_size=n_obs,
        )
    )

    matrix = np.array(returns, dtype=np.float64)

    # Ensure no constant columns (zero std would cause division by zero in relative error)
    # A column with all identical values has zero variance
    stds = np.std(matrix, axis=0, ddof=1)
    assume(np.all(stds > 1e-12))

    return matrix


# ---------------------------------------------------------------------------
# Property 2: Covariance volatility round-trip
# ---------------------------------------------------------------------------


class TestCovarianceVolatilityRoundTrip:
    """Property 2: Covariance volatility round-trip.

    **Validates: Requirements 1.8**

    For any valid return matrix, estimating covariance via the Sample estimator,
    extracting the diagonal, and taking sqrt * sqrt(252) produces annualized
    volatilities within 1% relative error of directly computed annualized
    volatilities (std(returns, axis=0, ddof=1) * sqrt(252)).
    """

    @given(returns=st_valid_return_matrix())
    @settings(max_examples=200, deadline=None)
    def test_covariance_diagonal_matches_direct_volatility(self, returns: np.ndarray) -> None:
        """Covariance diagonal sqrt * sqrt(252) matches direct annualized vol within 1% relative error."""
        estimator = SampleCovarianceEstimator()
        config = CovarianceConfig(eigenvalue_floor=1e-8)

        # Step 1: Estimate covariance using Sample estimator
        result = estimator.estimate(returns, config)
        cov_matrix = result.matrix

        # Step 2: Extract diagonal and compute annualized volatility from covariance
        vol_from_cov = np.sqrt(np.diag(cov_matrix)) * np.sqrt(252)

        # Step 3: Directly compute annualized volatility from returns
        vol_direct = np.std(returns, axis=0, ddof=1) * np.sqrt(252)

        # Step 4: Assert relative error <= 1% for each asset
        # relative_error = |vol_from_cov - vol_direct| / vol_direct
        relative_errors = np.abs(vol_from_cov - vol_direct) / vol_direct

        assert np.all(relative_errors <= 0.01), (
            f"Relative error exceeded 1% for at least one asset.\n"
            f"Max relative error: {np.max(relative_errors):.6f}\n"
            f"Vol from covariance: {vol_from_cov}\n"
            f"Vol direct: {vol_direct}\n"
            f"Returns shape: {returns.shape}"
        )
