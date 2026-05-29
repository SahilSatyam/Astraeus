"""Property tests for Black-Litterman expired view exclusion.

**Validates: Requirements 5.9**

Property 9: Black-Litterman expired view exclusion
    When views are provided, the BL optimizer must exclude any view whose
    expires_at timestamp is earlier than the current as_of_ts before
    constructing the picking matrix P and return vector Q. If all views are
    expired, it must fall back to equilibrium returns.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume

from astraeus_portfolio.constraints.box import BoxConstraint
from astraeus_portfolio.contracts import OptContext, View
from astraeus_portfolio.optimizers.black_litterman import BlackLittermanOptimizer


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_psd_covariance(draw: st.DrawFn, n: int) -> np.ndarray:
    """Generate a valid n×n positive semi-definite covariance matrix.

    Uses A'A + epsilon*I construction to guarantee PSD with eigenvalue floor.
    """
    a_values = draw(
        st.lists(
            st.lists(
                st.floats(
                    min_value=-0.3, max_value=0.3,
                    allow_nan=False, allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ),
            min_size=n,
            max_size=n,
        )
    )
    A = np.array(a_values, dtype=np.float64)
    cov = (A.T @ A) / n + 1e-5 * np.eye(n)
    cov = (cov + cov.T) / 2.0
    return cov


@st.composite
def st_view(
    draw: st.DrawFn,
    n_assets: int,
    as_of_ts: datetime,
    expired: bool,
) -> View:
    """Generate a View that is either expired or unexpired relative to as_of_ts.

    Args:
        draw: Hypothesis draw function.
        n_assets: Number of assets in the universe.
        as_of_ts: The reference timestamp for expiration check.
        expired: If True, generates a view with expires_at < as_of_ts.
    """
    # Number of sub-views in this view (1 to 2 for simplicity)
    k = draw(st.integers(min_value=1, max_value=2))

    # Generate picking matrix P (k x n_assets)
    # Each row should have at least one non-zero entry
    P_rows = []
    for _ in range(k):
        row = draw(
            st.lists(
                st.floats(
                    min_value=-1.0, max_value=1.0,
                    allow_nan=False, allow_infinity=False,
                ),
                min_size=n_assets,
                max_size=n_assets,
            )
        )
        # Ensure at least one non-zero entry
        if all(abs(v) < 1e-10 for v in row):
            row[0] = 1.0
        P_rows.append(row)

    # Generate Q vector (k expected returns)
    Q = draw(
        st.lists(
            st.floats(
                min_value=-0.05, max_value=0.10,
                allow_nan=False, allow_infinity=False,
            ),
            min_size=k,
            max_size=k,
        )
    )

    # Generate confidence values in [0.01, 0.99]
    confidence = draw(
        st.lists(
            st.floats(
                min_value=0.1, max_value=0.95,
                allow_nan=False, allow_infinity=False,
            ),
            min_size=k,
            max_size=k,
        )
    )

    # Generate expires_at based on expired flag
    if expired:
        # Expired: expires_at is before as_of_ts
        offset_seconds = draw(st.integers(min_value=1, max_value=86400 * 30))
        expires_at = as_of_ts - timedelta(seconds=offset_seconds)
    else:
        # Unexpired: expires_at is at or after as_of_ts
        offset_seconds = draw(st.integers(min_value=0, max_value=86400 * 30))
        expires_at = as_of_ts + timedelta(seconds=offset_seconds)

    view_id = draw(st.text(min_size=4, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))))

    return View(
        view_id=view_id,
        as_of_ts=as_of_ts - timedelta(days=1),
        source="manual",
        P=P_rows,
        Q=Q,
        confidence=confidence,
        rationale="test view",
        expires_at=expires_at,
    )


@st.composite
def st_bl_context_with_expired_views(
    draw: st.DrawFn,
) -> tuple[OptContext, list[View], list[View]]:
    """Generate an OptContext with a mix of expired and unexpired views.

    Returns:
        Tuple of (context_with_all_views, expired_views, unexpired_views).
    """
    n = draw(st.integers(min_value=2, max_value=5))
    as_of_ts = datetime(2024, 6, 15, 16, 30)

    # Generate PSD covariance
    covariance = draw(st_psd_covariance(n))

    # Expected returns
    expected_returns = np.array(
        draw(
            st.lists(
                st.floats(
                    min_value=-0.05, max_value=0.15,
                    allow_nan=False, allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            )
        ),
        dtype=np.float64,
    )

    # Market-cap weights (current_weights used as w_mkt)
    raw_weights = draw(
        st.lists(
            st.floats(
                min_value=0.05, max_value=1.0,
                allow_nan=False, allow_infinity=False,
            ),
            min_size=n,
            max_size=n,
        )
    )
    w_mkt = np.array(raw_weights, dtype=np.float64)
    w_mkt = w_mkt / w_mkt.sum()  # Normalize to sum to 1

    # Generate expired views (at least 1)
    n_expired = draw(st.integers(min_value=1, max_value=3))
    expired_views = [
        draw(st_view(n_assets=n, as_of_ts=as_of_ts, expired=True))
        for _ in range(n_expired)
    ]

    # Generate unexpired views (at least 1)
    n_unexpired = draw(st.integers(min_value=1, max_value=3))
    unexpired_views = [
        draw(st_view(n_assets=n, as_of_ts=as_of_ts, expired=False))
        for _ in range(n_unexpired)
    ]

    all_views = expired_views + unexpired_views

    symbols = [f"ASSET_{i}" for i in range(n)]
    sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer"]
    sector_map = {s: sectors[i % len(sectors)] for i, s in enumerate(symbols)}

    ctx = OptContext(
        strategy_id="test_bl_expired",
        as_of_ts=as_of_ts,
        n_assets=n,
        symbols=symbols,
        expected_returns=expected_returns,
        covariance=covariance,
        current_weights=w_mkt,
        prices=np.ones(n) * 100.0,
        adv=np.ones(n) * 1_000_000.0,
        sector_map=sector_map,
        beta=np.ones(n),
        factor_loadings=None,
        views=all_views,
        scenarios=None,
        regime_label=None,
        constraints=[BoxConstraint(w_max=1.0, l_max=2.0)],
        risk_aversion=5.0,
        solver_chain=["ECOS", "CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000.00"),
        seed=42,
    )

    return ctx, expired_views, unexpired_views


@st.composite
def st_bl_context_all_expired(draw: st.DrawFn) -> OptContext:
    """Generate an OptContext where ALL views are expired.

    This tests the fallback to equilibrium returns.
    """
    n = draw(st.integers(min_value=2, max_value=5))
    as_of_ts = datetime(2024, 6, 15, 16, 30)

    # Generate PSD covariance
    covariance = draw(st_psd_covariance(n))

    # Expected returns
    expected_returns = np.array(
        draw(
            st.lists(
                st.floats(
                    min_value=-0.05, max_value=0.15,
                    allow_nan=False, allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            )
        ),
        dtype=np.float64,
    )

    # Market-cap weights
    raw_weights = draw(
        st.lists(
            st.floats(
                min_value=0.05, max_value=1.0,
                allow_nan=False, allow_infinity=False,
            ),
            min_size=n,
            max_size=n,
        )
    )
    w_mkt = np.array(raw_weights, dtype=np.float64)
    w_mkt = w_mkt / w_mkt.sum()

    # Generate only expired views (at least 1)
    n_expired = draw(st.integers(min_value=1, max_value=4))
    expired_views = [
        draw(st_view(n_assets=n, as_of_ts=as_of_ts, expired=True))
        for _ in range(n_expired)
    ]

    symbols = [f"ASSET_{i}" for i in range(n)]
    sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer"]
    sector_map = {s: sectors[i % len(sectors)] for i, s in enumerate(symbols)}

    ctx = OptContext(
        strategy_id="test_bl_all_expired",
        as_of_ts=as_of_ts,
        n_assets=n,
        symbols=symbols,
        expected_returns=expected_returns,
        covariance=covariance,
        current_weights=w_mkt,
        prices=np.ones(n) * 100.0,
        adv=np.ones(n) * 1_000_000.0,
        sector_map=sector_map,
        beta=np.ones(n),
        factor_loadings=None,
        views=expired_views,
        scenarios=None,
        regime_label=None,
        constraints=[BoxConstraint(w_max=1.0, l_max=2.0)],
        risk_aversion=5.0,
        solver_chain=["ECOS", "CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000.00"),
        seed=42,
    )

    return ctx


# ---------------------------------------------------------------------------
# Property 9: Black-Litterman expired view exclusion
# ---------------------------------------------------------------------------


class TestBLExpiredViewExclusion:
    """Property 9: Black-Litterman expired view exclusion.

    **Validates: Requirements 5.9**

    When views are provided, the BL optimizer must exclude any view whose
    expires_at timestamp is earlier than the current as_of_ts before
    constructing the picking matrix P and return vector Q. If all views are
    expired, it must fall back to equilibrium returns.
    """

    @given(data=st_bl_context_with_expired_views())
    @settings(max_examples=50, deadline=None)
    def test_expired_views_do_not_affect_output(
        self, data: tuple[OptContext, list[View], list[View]]
    ) -> None:
        """Expired views must not affect the BL optimizer output.

        We compare the result of running BL with all views (expired + unexpired)
        against running BL with only the unexpired views. The weights should be
        identical since expired views must be excluded before constructing P and Q.
        """
        ctx_all_views, expired_views, unexpired_views = data

        # Run BL with all views (expired + unexpired)
        bl = BlackLittermanOptimizer(delta=2.5, risk_aversion=5.0)
        result_all = bl.run(ctx_all_views)

        # Run BL with only unexpired views
        ctx_unexpired_only = OptContext(
            strategy_id=ctx_all_views.strategy_id,
            as_of_ts=ctx_all_views.as_of_ts,
            n_assets=ctx_all_views.n_assets,
            symbols=ctx_all_views.symbols,
            expected_returns=ctx_all_views.expected_returns,
            covariance=ctx_all_views.covariance,
            current_weights=ctx_all_views.current_weights,
            prices=ctx_all_views.prices,
            adv=ctx_all_views.adv,
            sector_map=ctx_all_views.sector_map,
            beta=ctx_all_views.beta,
            factor_loadings=ctx_all_views.factor_loadings,
            views=unexpired_views,
            scenarios=ctx_all_views.scenarios,
            regime_label=ctx_all_views.regime_label,
            constraints=ctx_all_views.constraints,
            risk_aversion=ctx_all_views.risk_aversion,
            solver_chain=ctx_all_views.solver_chain,
            fully_invested=ctx_all_views.fully_invested,
            nav=ctx_all_views.nav,
            seed=ctx_all_views.seed,
        )
        result_unexpired = bl.run(ctx_unexpired_only)

        # Both should succeed
        assume(result_all.status in ("optimal", "optimal_inaccurate"))
        assume(result_unexpired.status in ("optimal", "optimal_inaccurate"))

        # Weights should be identical — expired views must not influence the result
        np.testing.assert_allclose(
            result_all.weights,
            result_unexpired.weights,
            atol=1e-8,
            err_msg=(
                f"Expired views affected BL output. "
                f"Max diff: {np.max(np.abs(result_all.weights - result_unexpired.weights)):.2e}. "
                f"n_expired={len(expired_views)}, n_unexpired={len(unexpired_views)}"
            ),
        )

    @given(ctx=st_bl_context_all_expired())
    @settings(max_examples=50, deadline=None)
    def test_all_expired_views_fallback_to_equilibrium(
        self, ctx: OptContext
    ) -> None:
        """When all views are expired, BL must fall back to equilibrium returns.

        The result should be identical to running BL with no views at all,
        which uses equilibrium returns Pi = delta * Sigma * w_mkt directly.
        """
        # Run BL with all-expired views
        bl = BlackLittermanOptimizer(delta=2.5, risk_aversion=5.0)
        result_expired = bl.run(ctx)

        # Run BL with no views (equilibrium fallback)
        ctx_no_views = OptContext(
            strategy_id=ctx.strategy_id,
            as_of_ts=ctx.as_of_ts,
            n_assets=ctx.n_assets,
            symbols=ctx.symbols,
            expected_returns=ctx.expected_returns,
            covariance=ctx.covariance,
            current_weights=ctx.current_weights,
            prices=ctx.prices,
            adv=ctx.adv,
            sector_map=ctx.sector_map,
            beta=ctx.beta,
            factor_loadings=ctx.factor_loadings,
            views=None,
            scenarios=ctx.scenarios,
            regime_label=ctx.regime_label,
            constraints=ctx.constraints,
            risk_aversion=ctx.risk_aversion,
            solver_chain=ctx.solver_chain,
            fully_invested=ctx.fully_invested,
            nav=ctx.nav,
            seed=ctx.seed,
        )
        result_no_views = bl.run(ctx_no_views)

        # Both should succeed
        assume(result_expired.status in ("optimal", "optimal_inaccurate"))
        assume(result_no_views.status in ("optimal", "optimal_inaccurate"))

        # Weights should be identical — all-expired views = no views = equilibrium
        np.testing.assert_allclose(
            result_expired.weights,
            result_no_views.weights,
            atol=1e-8,
            err_msg=(
                f"All-expired views did not fall back to equilibrium. "
                f"Max diff: {np.max(np.abs(result_expired.weights - result_no_views.weights)):.2e}. "
                f"n_views={len(ctx.views)}"
            ),
        )
