"""Factor attribution module.

OLS time-series regression of strategy returns against Fama-French 3 + Carhart momentum:
    r_p = α + β_M × MKT + β_S × SMB + β_H × HML + β_U × UMD + ε

Factor returns sourced from Ken French data library.
Output: factor exposures (β), R², alpha (and t-stat), residual return.

References:
- Fama & French (1993), "Common risk factors in the returns on stocks and bonds"
- Carhart (1997), "On persistence in mutual fund performance"
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import structlog

logger = structlog.get_logger("astraeus.strategy.attribution")


@dataclass(slots=True)
class FactorExposure:
    """Exposure to a single factor."""

    factor_name: str
    beta: float
    t_stat: float
    p_value: float


@dataclass(slots=True)
class AttributionResult:
    """Full factor attribution result."""

    alpha: float = 0.0  # annualized
    alpha_t_stat: float = 0.0
    r_squared: float = 0.0
    adj_r_squared: float = 0.0
    exposures: list[FactorExposure] | None = None
    residual_vol: float = 0.0
    n_observations: int = 0

    @property
    def factor_names(self) -> list[str]:
        if self.exposures is None:
            return []
        return [e.factor_name for e in self.exposures]


def compute_attribution(
    strategy_returns: np.ndarray,
    factor_returns: dict[str, np.ndarray],
    risk_free_rate: np.ndarray | None = None,
    trading_days: int = 252,
) -> AttributionResult:
    """Run factor attribution regression.

    Args:
        strategy_returns: Daily strategy returns (excess of risk-free if rf provided).
        factor_returns: Dict mapping factor name to daily return array.
            Expected keys: 'MKT', 'SMB', 'HML', 'UMD' (Carhart momentum).
        risk_free_rate: Daily risk-free rate array (subtracted from strategy returns).
        trading_days: Trading days per year for annualization.

    Returns:
        AttributionResult with alpha, betas, t-stats, and R².
    """
    n = len(strategy_returns)
    if n < 30:
        logger.warning("insufficient_data_for_attribution", n=n)
        return AttributionResult(n_observations=n)

    # Compute excess returns
    y = strategy_returns.copy()
    if risk_free_rate is not None:
        y = y - risk_free_rate[:n]

    # Build factor matrix
    factor_names = sorted(factor_returns.keys())
    X_cols: list[np.ndarray] = []
    valid_factors: list[str] = []

    for fname in factor_names:
        fret = factor_returns[fname]
        if len(fret) >= n:
            X_cols.append(fret[:n])
            valid_factors.append(fname)

    if not X_cols:
        logger.warning("no_valid_factors_for_attribution")
        return AttributionResult(n_observations=n)

    # Add intercept (alpha)
    X = np.column_stack([np.ones(n), *X_cols])

    # OLS: β = (X'X)^{-1} X'y
    try:
        XtX = X.T @ X
        XtX_inv = np.linalg.inv(XtX)
        beta_hat = XtX_inv @ (X.T @ y)
    except np.linalg.LinAlgError:
        logger.warning("singular_matrix_in_attribution")
        return AttributionResult(n_observations=n)

    # Residuals and R²
    y_hat = X @ beta_hat
    residuals = y - y_hat
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1 - ss_res / max(ss_tot, 1e-10)

    k = len(valid_factors)  # number of regressors (excluding intercept)
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / max(n - k - 2, 1)

    # Standard errors and t-stats
    sigma_sq = ss_res / max(n - k - 1, 1)
    se = np.sqrt(np.diag(XtX_inv) * sigma_sq)

    # Alpha (intercept)
    alpha_daily = float(beta_hat[0])
    alpha_annual = alpha_daily * trading_days
    alpha_se = float(se[0])
    alpha_t = alpha_daily / max(alpha_se, 1e-10)

    # Factor exposures
    exposures: list[FactorExposure] = []
    for i, fname in enumerate(valid_factors):
        beta_i = float(beta_hat[i + 1])
        se_i = float(se[i + 1])
        t_i = beta_i / max(se_i, 1e-10)

        # Approximate p-value from t-distribution (two-tailed)
        # Using normal approximation for large n
        p_value = 2 * (1 - _norm_cdf(abs(t_i)))

        exposures.append(
            FactorExposure(
                factor_name=fname,
                beta=beta_i,
                t_stat=t_i,
                p_value=p_value,
            )
        )

    residual_vol = float(np.std(residuals)) * np.sqrt(trading_days)

    logger.info(
        "attribution_complete",
        alpha_annual=round(alpha_annual, 4),
        alpha_t=round(alpha_t, 2),
        r_squared=round(r_squared, 3),
        factors=valid_factors,
    )

    return AttributionResult(
        alpha=alpha_annual,
        alpha_t_stat=alpha_t,
        r_squared=r_squared,
        adj_r_squared=adj_r_squared,
        exposures=exposures,
        residual_vol=residual_vol,
        n_observations=n,
    )


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    import math

    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
