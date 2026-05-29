"""Property test for Effective Number of Bets > 1.

**Validates: Requirements 10.4**

Property 15: If the portfolio contains more than one asset with a non-zero weight,
the Effective Number of Bets must be strictly greater than 1.0.

ENB = 1 / sum(p_c^2) where p_c = w_c'Σw / w'Σw
"""

from __future__ import annotations

import hypothesis.strategies as st
import numpy as np
from astraeus_portfolio.risk.clustering import compute_cluster_report
from hypothesis import assume, given, settings

# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_psd_covariance(draw: st.DrawFn, n: int) -> np.ndarray:
    """Generate a valid n×n positive semi-definite covariance matrix.

    Constructs as A'A + epsilon*I to guarantee PSD with non-trivial structure.
    """
    # Generate a random matrix and form A'A for PSD guarantee
    a_values = draw(
        st.lists(
            st.lists(
                st.floats(
                    min_value=-0.5,
                    max_value=0.5,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ),
            min_size=n,
            max_size=n,
        )
    )
    A = np.array(a_values, dtype=np.float64)
    cov = A.T @ A + 1e-6 * np.eye(n)
    # Ensure symmetry
    cov = (cov + cov.T) / 2.0
    return cov


@st.composite
def st_portfolio_with_multiple_nonzero_weights(
    draw: st.DrawFn,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Generate a portfolio with at least 2 assets having non-zero weights.

    Returns:
        Tuple of (returns, weights, covariance, symbols) where:
        - returns: T×n matrix with T >= 60, no NaN
        - weights: (n,) vector with at least 2 non-zero entries summing to 1
        - covariance: (n, n) PSD matrix
        - symbols: list of n asset symbols
    """
    # Number of assets: at least 2, up to 8
    n = draw(st.integers(min_value=2, max_value=8))

    # Number of non-zero weight assets: at least 2, up to n
    n_nonzero = draw(st.integers(min_value=2, max_value=n))

    # Generate positive weights for the non-zero positions
    raw_weights = draw(
        st.lists(
            st.floats(
                min_value=0.01,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=n_nonzero,
            max_size=n_nonzero,
        )
    )
    raw_weights_arr = np.array(raw_weights, dtype=np.float64)
    # Normalize to sum to 1
    normalized = raw_weights_arr / raw_weights_arr.sum()

    # Build full weight vector with zeros for remaining assets
    weights = np.zeros(n, dtype=np.float64)
    # Place non-zero weights in the first n_nonzero positions
    weights[:n_nonzero] = normalized

    # Shuffle the weight positions
    perm = draw(st.permutations(list(range(n))))
    weights = weights[list(perm)]

    # Generate PSD covariance matrix
    covariance = draw(st_psd_covariance(n))

    # Generate return history: at least 60 days, no NaN
    t = draw(st.integers(min_value=60, max_value=120))
    returns_data = draw(
        st.lists(
            st.lists(
                st.floats(
                    min_value=-0.10,
                    max_value=0.10,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ),
            min_size=t,
            max_size=t,
        )
    )
    returns = np.array(returns_data, dtype=np.float64)

    # Generate symbols
    symbols = [f"ASSET_{i}" for i in range(n)]

    return returns, weights, covariance, symbols


# ---------------------------------------------------------------------------
# Property 15: Effective Number of Bets > 1
# ---------------------------------------------------------------------------


class TestEffectiveNumberOfBetsGreaterThanOne:
    """Property 15: Effective Number of Bets > 1.

    **Validates: Requirements 10.4**

    If the portfolio contains more than one asset with a non-zero weight,
    the Effective Number of Bets must be strictly greater than 1.0.
    """

    @given(data=st_portfolio_with_multiple_nonzero_weights())
    @settings(max_examples=200, deadline=None)
    def test_enb_greater_than_one_for_multi_asset_portfolio(
        self,
        data: tuple[np.ndarray, np.ndarray, np.ndarray, list[str]],
    ) -> None:
        """ENB > 1 when portfolio has more than one non-zero weight asset."""
        returns, weights, covariance, symbols = data

        # Filter out degenerate cases where total portfolio variance is zero
        total_var = float(weights @ covariance @ weights)
        assume(abs(total_var) > 1e-15)

        # Confirm we have at least 2 non-zero weight assets
        non_zero_count = int(np.sum(np.abs(weights) > 1e-12))
        assume(non_zero_count > 1)

        report = compute_cluster_report(
            returns=returns,
            weights=weights,
            covariance=covariance,
            symbols=symbols,
        )

        assert float(report.effective_n_bets) > 1.0, (
            f"ENB = {report.effective_n_bets} is not > 1.0 "
            f"for a portfolio with {non_zero_count} non-zero weight assets. "
            f"Weights: {weights}"
        )
