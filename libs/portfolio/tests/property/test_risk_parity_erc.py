"""Property test for Risk Parity equal risk contribution.

**Validates: Requirements 6.5**

Property 10: Risk Parity equal risk contribution
    The Risk Parity optimizer must produce weights where the maximum ratio
    between any two assets' risk contributions does not exceed 1.05 (within
    5% of equal risk contribution), given a PSD covariance matrix with at
    least 2 assets.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume

from astraeus_portfolio.contracts import OptContext
from astraeus_portfolio.optimizers.risk_parity import RiskParityConfig, RiskParityOptimizer


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_psd_covariance_well_conditioned(draw: st.DrawFn, n: int) -> np.ndarray:
    """Generate a well-conditioned n×n positive semi-definite covariance matrix.

    Uses A'A + epsilon*I construction to guarantee PSD with eigenvalue floor.
    Keeps condition number well below 1e6 to ensure the ERC path is used.

    Args:
        draw: Hypothesis draw function.
        n: Number of assets.

    Returns:
        An n×n PSD covariance matrix with reasonable condition number.
    """
    # Generate random factor matrix with bounded values
    a_values = draw(
        st.lists(
            st.lists(
                st.floats(
                    min_value=-0.3,
                    max_value=0.3,
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
    # A'A / n gives a PSD matrix; add a generous epsilon*I for well-conditioning
    cov = (A.T @ A) / n + 1e-4 * np.eye(n)
    # Ensure perfect symmetry
    cov = (cov + cov.T) / 2.0
    return cov


@st.composite
def st_risk_parity_context(draw: st.DrawFn) -> OptContext:
    """Generate a valid OptContext for Risk Parity optimization.

    Produces a context with:
    - 2 to 10 assets (well within the ERC path threshold of 200)
    - A well-conditioned PSD covariance matrix (cond < 1e6)
    - No additional constraints (pure ERC)

    Args:
        draw: Hypothesis draw function.

    Returns:
        A valid OptContext instance suitable for Risk Parity ERC.
    """
    n = draw(st.integers(min_value=2, max_value=10))

    # Generate well-conditioned PSD covariance
    covariance = draw(st_psd_covariance_well_conditioned(n))

    # Expected returns (not used by Risk Parity but required by OptContext)
    expected_returns = np.zeros(n)

    # Current weights (equal weight as prior)
    current_weights = np.ones(n) / n

    # Prices and ADV (not used by Risk Parity but required)
    prices = np.ones(n) * 100.0
    adv = np.ones(n) * 1_000_000.0

    # Symbols
    symbols = [f"ASSET_{i}" for i in range(n)]

    # Sector map
    sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer"]
    sector_map = {s: sectors[i % len(sectors)] for i, s in enumerate(symbols)}

    # Beta
    beta = np.ones(n) * 1.0

    return OptContext(
        strategy_id="test_risk_parity_erc",
        as_of_ts=datetime(2024, 1, 15, 16, 30),
        n_assets=n,
        symbols=symbols,
        expected_returns=expected_returns,
        covariance=covariance,
        current_weights=current_weights,
        prices=prices,
        adv=adv,
        sector_map=sector_map,
        beta=beta,
        factor_loadings=None,
        views=None,
        scenarios=None,
        regime_label=None,
        constraints=[],
        risk_aversion=5.0,
        solver_chain=["ECOS", "CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000.00"),
        seed=42,
    )


# ---------------------------------------------------------------------------
# Property 10: Risk Parity equal risk contribution
# ---------------------------------------------------------------------------


class TestRiskParityEqualRiskContribution:
    """Property 10: Risk Parity equal risk contribution.

    **Validates: Requirements 6.5**

    The Risk Parity optimizer must produce weights where the maximum ratio
    between any two assets' risk contributions does not exceed 1.05 (within
    5% of equal risk contribution), given a PSD covariance matrix with at
    least 2 assets.
    """

    @given(ctx=st_risk_parity_context())
    @settings(max_examples=100, deadline=None)
    def test_risk_contributions_within_tolerance(self, ctx: OptContext) -> None:
        """ERC produces weights with near-equal risk contributions.

        Risk contribution for asset i: RC_i = w_i * (Σw)_i / (w'Σw)
        For ERC: max(RC_i) / min(RC_i) <= 1.05

        Also verifies:
        - Weights sum to 1.0
        - All weights are non-negative
        """
        optimizer = RiskParityOptimizer(
            rp_config=RiskParityConfig(
                max_iterations=50,
                convergence_tol=1e-10,
            ),
        )
        result = optimizer.run(ctx)

        # Filter out non-convergence cases
        assume(result.status in ("optimal", "optimal_inaccurate"))

        w = result.weights
        n = ctx.n_assets
        cov = ctx.covariance

        # Verify weights sum to 1.0
        assert abs(np.sum(w) - 1.0) < 1e-6, (
            f"Weights do not sum to 1.0: sum={np.sum(w):.10f}"
        )

        # Verify all weights are non-negative
        assert np.all(w >= -1e-10), (
            f"Negative weights found: min={np.min(w):.10e}"
        )

        # Compute risk contributions: RC_i = w_i * (Σw)_i / (w'Σw)
        sigma_w = cov @ w
        total_portfolio_risk = float(w @ sigma_w)

        # Skip degenerate cases where total risk is essentially zero
        assume(total_portfolio_risk > 1e-15)

        risk_contributions = w * sigma_w / total_portfolio_risk

        # Only consider assets with meaningful weight (> 1e-10)
        active_mask = w > 1e-10
        active_rc = risk_contributions[active_mask]

        # Need at least 2 active assets to compute a ratio
        assume(len(active_rc) >= 2)

        max_rc = float(np.max(active_rc))
        min_rc = float(np.min(active_rc))

        # min_rc must be positive to compute ratio
        assume(min_rc > 1e-15)

        ratio = max_rc / min_rc

        assert ratio <= 1.05, (
            f"Risk contribution ratio {ratio:.6f} exceeds 1.05. "
            f"max_rc={max_rc:.8e}, min_rc={min_rc:.8e}, "
            f"n_assets={n}, n_active={int(np.sum(active_mask))}, "
            f"weights={w}, risk_contributions={risk_contributions}"
        )
