"""Black-Litterman Optimizer: Bayesian blending of equilibrium and views.

This module implements the Black-Litterman portfolio optimizer that combines
market-implied equilibrium returns with investor views to produce posterior
expected returns, which are then passed to the MVO solver for final weight
computation.

The BL flow:
1. Compute equilibrium returns: Π = δΣw_mkt
2. Filter expired views (expires_at < as_of_ts)
3. If no unexpired views, fall back to equilibrium returns with MVO
4. Compute Omega from confidence via Idzorek's method
5. Compute posterior returns via the BL formula
6. Pass posterior to MVO solver for final weights

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10
"""

from __future__ import annotations

import numpy as np
import structlog

from astraeus_portfolio.contracts import OptContext, OptResult, View
from astraeus_portfolio.optimizers.base import Optimizer, OptimizerConfig
from astraeus_portfolio.optimizers.mvo import MeanVarianceOptimizer, MVOMode

__all__ = [
    "BlackLittermanOptimizer",
    "BLOptimizer",
]

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DELTA = 2.5  # Default implied risk aversion
_CONFIDENCE_CAP = 0.99  # Maximum allowed confidence
_CONDITION_NUMBER_WARN = 1e10  # Condition number warning threshold


# ---------------------------------------------------------------------------
# Black-Litterman Optimizer
# ---------------------------------------------------------------------------


class BlackLittermanOptimizer(Optimizer):
    """Black-Litterman optimizer blending equilibrium returns with investor views.

    This optimizer:
    1. Computes market-implied equilibrium returns Π = δΣw_mkt.
    2. Filters expired views based on as_of_ts.
    3. If unexpired views exist, computes posterior returns via the BL formula.
    4. Computes Omega (view uncertainty) from confidence via Idzorek's method.
    5. Passes posterior returns to the MVO solver for final weight computation.
    6. Falls back to equilibrium returns when no unexpired views are available.

    Attributes:
        delta: Implied risk aversion parameter (default 2.5).
        tau: Scaling factor for the prior covariance (default 1/T).
        mvo: Internal MVO solver used for final weight computation.
    """

    def __init__(
        self,
        delta: float = _DEFAULT_DELTA,
        tau: float | None = None,
        risk_aversion: float = 5.0,
        config: OptimizerConfig | None = None,
    ) -> None:
        """Initialize the Black-Litterman optimizer.

        Args:
            delta: Implied risk aversion for equilibrium returns (default 2.5).
            tau: Scaling factor for prior covariance. If None, defaults to 1/T
                where T is the covariance estimation window (252).
            risk_aversion: Risk aversion for the downstream MVO solver.
            config: Optimizer configuration (solver chain, kwargs, etc.).
        """
        super().__init__(config)
        self.delta = delta
        self._tau_override = tau
        self.risk_aversion = risk_aversion

    def _get_tau(self, ctx: OptContext) -> float:
        """Get tau value, defaulting to 1/T where T is the covariance window.

        Args:
            ctx: The optimization context.

        Returns:
            The tau scaling factor.
        """
        if self._tau_override is not None:
            return self._tau_override
        # Default: 1/T where T is the covariance estimation window (252 trading days)
        T = 252
        return 1.0 / T

    def run(self, ctx: OptContext) -> OptResult:
        """Execute Black-Litterman optimization.

        Pipeline:
        1. Compute equilibrium returns Π = δΣw_mkt.
        2. Filter expired views.
        3. If no unexpired views, pass Π directly to MVO.
        4. Otherwise, compute posterior via BL formula and pass to MVO.

        Args:
            ctx: The optimization context. Must contain market-cap weights
                in current_weights (used as w_mkt) and optionally views.

        Returns:
            An OptResult with the solution weights from the MVO solver.
        """
        n = ctx.n_assets
        sigma = ctx.covariance
        w_mkt = ctx.current_weights  # Market-cap weights

        # Step 1: Compute equilibrium returns Π = δΣw_mkt
        pi = self._compute_equilibrium_returns(sigma, w_mkt)

        # Step 2: Filter expired views
        unexpired_views = self._filter_expired_views(ctx.views, ctx.as_of_ts)

        # Step 3: Determine posterior returns
        if not unexpired_views:
            logger.info(
                "no_unexpired_views_using_equilibrium",
                strategy_id=ctx.strategy_id,
                n_total_views=len(ctx.views) if ctx.views else 0,
            )
            posterior_mu = pi
            posterior_sigma = sigma
        else:
            logger.info(
                "computing_bl_posterior",
                strategy_id=ctx.strategy_id,
                n_views=len(unexpired_views),
            )
            posterior_mu, posterior_sigma = self._compute_posterior(
                pi=pi,
                sigma=sigma,
                views=unexpired_views,
                ctx=ctx,
            )

        # Step 4: Create a new OptContext with posterior returns and pass to MVO
        mvo = MeanVarianceOptimizer(
            mode=MVOMode.TANGENCY,
            risk_aversion=self.risk_aversion,
            config=self.config,
        )

        # Build a new context with posterior returns and covariance
        posterior_ctx = OptContext(
            strategy_id=ctx.strategy_id,
            as_of_ts=ctx.as_of_ts,
            n_assets=ctx.n_assets,
            symbols=ctx.symbols,
            expected_returns=posterior_mu,
            covariance=posterior_sigma,
            current_weights=ctx.current_weights,
            prices=ctx.prices,
            adv=ctx.adv,
            sector_map=ctx.sector_map,
            beta=ctx.beta,
            factor_loadings=ctx.factor_loadings,
            views=ctx.views,
            scenarios=ctx.scenarios,
            regime_label=ctx.regime_label,
            constraints=ctx.constraints,
            risk_aversion=ctx.risk_aversion,
            solver_chain=ctx.solver_chain,
            fully_invested=ctx.fully_invested,
            nav=ctx.nav,
            seed=ctx.seed,
        )

        return mvo.run(posterior_ctx)

    def build_objective(self, w, ctx: OptContext):
        """Build objective — delegates to MVO internally.

        This method satisfies the ABC requirement but is not directly used
        since run() delegates to the MVO solver.
        """
        # This is required by the ABC but the actual optimization is done
        # by the internal MVO solver in run().
        import cvxpy as cp

        return cp.quad_form(w, ctx.covariance)

    def _compute_equilibrium_returns(
        self, sigma: np.ndarray, w_mkt: np.ndarray
    ) -> np.ndarray:
        """Compute market-implied equilibrium returns.

        Π = δ * Σ * w_mkt

        Args:
            sigma: The n×n covariance matrix.
            w_mkt: The n-vector of market-cap weights.

        Returns:
            The n-vector of equilibrium returns.
        """
        return self.delta * sigma @ w_mkt

    def _filter_expired_views(
        self, views: list[View] | None, as_of_ts
    ) -> list[View]:
        """Filter out views whose expires_at is earlier than as_of_ts.

        Args:
            views: List of View objects, or None.
            as_of_ts: The current computation timestamp.

        Returns:
            List of unexpired views.
        """
        if not views:
            return []

        unexpired = [v for v in views if v.expires_at >= as_of_ts]

        n_expired = len(views) - len(unexpired)
        if n_expired > 0:
            logger.info(
                "views_expired",
                n_expired=n_expired,
                n_remaining=len(unexpired),
            )

        return unexpired

    def _compute_posterior(
        self,
        pi: np.ndarray,
        sigma: np.ndarray,
        views: list[View],
        ctx: OptContext,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute BL posterior returns and covariance.

        BL formula:
        mu_BL = inv(inv(tau*Sigma) + P'*inv(Omega)*P) *
                (inv(tau*Sigma)*Pi + P'*inv(Omega)*Q)

        Posterior covariance:
        Sigma_BL = inv(inv(tau*Sigma) + P'*inv(Omega)*P) + Sigma

        Args:
            pi: Equilibrium returns (n,).
            sigma: Covariance matrix (n, n).
            views: List of unexpired views.
            ctx: The optimization context.

        Returns:
            Tuple of (posterior_mu, posterior_sigma).
        """
        n = ctx.n_assets
        tau = self._get_tau(ctx)

        # Construct P matrix (k x n) and Q vector (k,)
        P, Q, confidences = self._construct_view_matrices(views, n)
        k = P.shape[0]

        # Compute Omega from confidence via Idzorek's method
        omega = self._compute_omega_idzorek(P, sigma, tau, confidences)

        # tau * Sigma
        tau_sigma = tau * sigma

        # inv(tau * Sigma)
        tau_sigma_inv = np.linalg.inv(tau_sigma)

        # inv(Omega)
        omega_inv = np.linalg.inv(omega)

        # P' * inv(Omega) * P
        Pt_omega_inv_P = P.T @ omega_inv @ P

        # Check condition number and warn if too high
        cond_number = np.linalg.cond(Pt_omega_inv_P)
        if cond_number > _CONDITION_NUMBER_WARN:
            logger.warning(
                "high_condition_number_contradictory_views",
                condition_number=cond_number,
                threshold=_CONDITION_NUMBER_WARN,
                strategy_id=ctx.strategy_id,
                n_views=k,
            )

        # Posterior precision: inv(tau*Sigma) + P'*inv(Omega)*P
        posterior_precision = tau_sigma_inv + Pt_omega_inv_P

        # Posterior covariance of returns (uncertainty in mean)
        posterior_cov_mu = np.linalg.inv(posterior_precision)

        # Posterior mean: inv(posterior_precision) * (inv(tau*Sigma)*Pi + P'*inv(Omega)*Q)
        posterior_mu = posterior_cov_mu @ (tau_sigma_inv @ pi + P.T @ omega_inv @ Q)

        # Full posterior covariance for optimization: Sigma + posterior_cov_mu
        # This accounts for both estimation uncertainty and asset covariance
        posterior_sigma = sigma + posterior_cov_mu

        return posterior_mu, posterior_sigma

    def _construct_view_matrices(
        self, views: list[View], n_assets: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Construct the combined P matrix, Q vector, and confidence vector from views.

        Args:
            views: List of unexpired View objects.
            n_assets: Number of assets in the universe.

        Returns:
            Tuple of (P, Q, confidences) where:
            - P is (k, n) picking matrix
            - Q is (k,) expected return vector
            - confidences is (k,) confidence vector (capped at 0.99)
        """
        P_rows = []
        Q_values = []
        conf_values = []

        for view in views:
            P_view = np.array(view.P)  # (k_v, n)
            Q_view = np.array(view.Q)  # (k_v,)
            conf_view = np.array(view.confidence)  # (k_v,)

            # Cap confidence at 0.99 (also done at validation, but enforce here)
            conf_view = np.minimum(conf_view, _CONFIDENCE_CAP)

            P_rows.append(P_view)
            Q_values.append(Q_view)
            conf_values.append(conf_view)

        P = np.vstack(P_rows)  # (k_total, n)
        Q = np.concatenate(Q_values)  # (k_total,)
        confidences = np.concatenate(conf_values)  # (k_total,)

        return P, Q, confidences

    def _compute_omega_idzorek(
        self,
        P: np.ndarray,
        sigma: np.ndarray,
        tau: float,
        confidences: np.ndarray,
    ) -> np.ndarray:
        """Compute the view uncertainty matrix Omega using Idzorek's method.

        Idzorek's method maps confidence levels to view uncertainty:
        For each view k, the diagonal element of Omega is:
            omega_k = (1/c_k - 1) * p_k' * (tau * Sigma) * p_k

        where c_k is the confidence (capped at 0.99) and p_k is the k-th row of P.

        This produces a diagonal Omega matrix where higher confidence means
        lower uncertainty (smaller omega_k).

        Args:
            P: The (k, n) picking matrix.
            sigma: The (n, n) covariance matrix.
            tau: The scaling factor for prior covariance.
            confidences: The (k,) confidence vector (already capped at 0.99).

        Returns:
            The (k, k) diagonal Omega matrix.
        """
        k = P.shape[0]
        tau_sigma = tau * sigma
        omega_diag = np.zeros(k)

        for i in range(k):
            p_i = P[i, :]  # (n,)
            # View variance from prior: p_i' * tau * Sigma * p_i
            view_variance = p_i @ tau_sigma @ p_i

            # Idzorek's mapping: omega_i = (1/c_i - 1) * view_variance
            # When c=1.0 (100% confidence), omega -> 0 (no uncertainty)
            # When c->0, omega -> infinity (complete uncertainty)
            c_i = confidences[i]
            omega_diag[i] = (1.0 / c_i - 1.0) * view_variance

        return np.diag(omega_diag)


# Alias for shorter name
BLOptimizer = BlackLittermanOptimizer
