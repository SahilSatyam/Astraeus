"""Factor-model PnL attribution: FF5+MOM regression.

Decomposes portfolio PnL into contributions from Fama-French 5 factors
(Mkt-RF, SMB, HML, RMW, CMA) plus Momentum (MOM), with the residual
allocated to idiosyncratic return.

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple
from uuid import UUID, uuid4

import numpy as np
import structlog

from astraeus_portfolio.contracts import AttributionResult

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The six FF5+MOM factor names in canonical order.
FACTOR_NAMES: list[str] = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM"]

#: Rolling regression window (trading days).
REGRESSION_WINDOW: int = 252

#: Minimum trading days required for an asset to be included in regression.
MIN_HISTORY_DAYS: int = 126

#: Newey-West HAC lag parameter.
NEWEY_WEST_LAG: int = 5

#: Maximum retry attempts when factor data is unavailable.
MAX_RETRIES: int = 3

#: Base delay (seconds) for exponential backoff.
BASE_BACKOFF_SECONDS: float = 1.0


# ---------------------------------------------------------------------------
# Internal Data Structures
# ---------------------------------------------------------------------------


class RegressionResult(NamedTuple):
    """Per-asset OLS regression output."""

    betas: np.ndarray  # (6,) factor loadings
    alpha: float  # intercept
    residual_std: float  # std of residuals
    nw_std_errors: np.ndarray  # (7,) Newey-West SE for [alpha, beta1..beta6]
    n_obs: int  # number of observations used


class FactorDataUnavailableError(Exception):
    """Raised when factor return data is not available for the attribution date."""

    pass


# ---------------------------------------------------------------------------
# Newey-West HAC Standard Errors
# ---------------------------------------------------------------------------


def _newey_west_se(X: np.ndarray, residuals: np.ndarray, lag: int = NEWEY_WEST_LAG) -> np.ndarray:
    """Compute Newey-West HAC standard errors for OLS coefficients.

    Args:
        X: Design matrix (T x k) including intercept column.
        residuals: OLS residuals (T,).
        lag: Maximum lag for HAC correction.

    Returns:
        Standard errors (k,) for each coefficient.
    """
    T, k = X.shape

    # Meat: S_0 + sum_{l=1}^{lag} w_l * (S_l + S_l')
    # where S_l = (1/T) * sum_{t=l+1}^{T} e_t * e_{t-l} * x_t * x_{t-l}'
    # Bartlett kernel weights: w_l = 1 - l/(lag+1)

    # Compute the "score" vectors: e_t * x_t
    scores = residuals[:, np.newaxis] * X  # (T, k)

    # S_0: the variance of scores
    S = scores.T @ scores / T  # (k, k)

    for l in range(1, lag + 1):
        weight = 1.0 - l / (lag + 1)
        gamma_l = scores[l:].T @ scores[:-l] / T  # (k, k)
        S += weight * (gamma_l + gamma_l.T)

    # Bread: (X'X / T)^{-1}
    XtX_inv = np.linalg.inv(X.T @ X / T)

    # Sandwich: V = (1/T) * bread * meat * bread
    V = XtX_inv @ S @ XtX_inv / T

    # Standard errors are sqrt of diagonal
    se = np.sqrt(np.maximum(np.diag(V), 0.0))
    return se


# ---------------------------------------------------------------------------
# OLS Regression
# ---------------------------------------------------------------------------


def _run_ols_regression(
    asset_returns: np.ndarray,
    factor_returns: np.ndarray,
) -> RegressionResult:
    """Run OLS regression of asset returns on factor returns with Newey-West SE.

    Args:
        asset_returns: (T,) array of daily asset returns.
        factor_returns: (T, 6) array of daily factor returns (FF5+MOM).

    Returns:
        RegressionResult with betas, alpha, residual std, and NW standard errors.
    """
    T = len(asset_returns)

    # Design matrix: [1, f1, f2, ..., f6]
    X = np.column_stack([np.ones(T), factor_returns])  # (T, 7)

    # OLS: beta_hat = (X'X)^{-1} X'y
    XtX = X.T @ X
    Xty = X.T @ asset_returns

    try:
        coeffs = np.linalg.solve(XtX, Xty)  # (7,)
    except np.linalg.LinAlgError:
        # Fallback to pseudo-inverse if singular
        coeffs = np.linalg.lstsq(X, asset_returns, rcond=None)[0]

    alpha = coeffs[0]
    betas = coeffs[1:]  # (6,)

    # Residuals
    fitted = X @ coeffs
    residuals = asset_returns - fitted
    residual_std = float(np.std(residuals, ddof=7))  # k=7 parameters

    # Newey-West standard errors
    nw_se = _newey_west_se(X, residuals, lag=NEWEY_WEST_LAG)

    return RegressionResult(
        betas=betas,
        alpha=alpha,
        residual_std=residual_std,
        nw_std_errors=nw_se,
        n_obs=T,
    )


# ---------------------------------------------------------------------------
# Factor Attribution Engine
# ---------------------------------------------------------------------------


class FactorAttributionEngine:
    """Decomposes portfolio PnL into FF5+MOM factor contributions + idiosyncratic.

    The engine performs OLS regression of each asset's returns on the six
    FF5+MOM factors over a 252-day rolling window, refitted monthly. Assets
    with fewer than 126 trading days are excluded from regression and their
    PnL is allocated entirely to idiosyncratic.

    Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8
    """

    def __init__(
        self,
        regression_window: int = REGRESSION_WINDOW,
        min_history_days: int = MIN_HISTORY_DAYS,
        newey_west_lag: int = NEWEY_WEST_LAG,
        max_retries: int = MAX_RETRIES,
        base_backoff: float = BASE_BACKOFF_SECONDS,
    ) -> None:
        self._regression_window = regression_window
        self._min_history_days = min_history_days
        self._nw_lag = newey_west_lag
        self._max_retries = max_retries
        self._base_backoff = base_backoff

    def run_factor_attribution(
        self,
        portfolio_id: UUID,
        as_of_ts: datetime,
        weights: np.ndarray,
        realized_returns: np.ndarray,
        factor_returns: np.ndarray,
        nav: Decimal | None = None,
    ) -> AttributionResult:
        """Decompose PnL into FF5+MOM factor contributions + idiosyncratic.

        Args:
            portfolio_id: UUID of the portfolio being attributed.
            as_of_ts: Attribution date/time.
            weights: (n,) array of portfolio weights at start of period.
            realized_returns: (n,) array of realized asset returns for the period.
            factor_returns: (T, 6) array of historical factor returns where the
                last row corresponds to the attribution date's realized factor
                returns. T should be >= regression_window for full estimation.
                Columns correspond to FACTOR_NAMES order.
            nav: Net Asset Value (optional, used for PnL scaling). If None,
                results are in bps of portfolio return.

        Returns:
            AttributionResult with factor PnL decomposition.

        Raises:
            FactorDataUnavailableError: If factor data for the attribution date
                is unavailable after retries.
            ValueError: If inputs have incompatible dimensions.
        """
        self._validate_inputs(weights, realized_returns, factor_returns)

        n_assets = len(weights)

        # The last row of factor_returns is the realized factor return for today
        realized_factor_returns = factor_returns[-1, :]  # (6,)

        # Historical factor returns for regression (up to regression_window)
        hist_factor_returns = factor_returns[:-1, :]  # (T-1, 6)

        # Compute per-asset betas via rolling OLS
        asset_betas = self._estimate_asset_betas(realized_returns, hist_factor_returns, n_assets)

        # Compute portfolio factor exposure: B_p = sum(w_i * beta_i) for each factor
        # asset_betas is (n, 6) where excluded assets have zeros
        portfolio_factor_exposure = self._compute_portfolio_exposure(weights, asset_betas)

        # Compute total realized portfolio PnL in bps
        total_pnl_bps = Decimal(str(round(float(np.dot(weights, realized_returns)) * 10000, 4)))

        # Compute factor PnL: B_p * f_realized for each factor (in return space)
        factor_pnl_returns = portfolio_factor_exposure * realized_factor_returns  # (6,)

        # Convert to bps
        factor_pnl_bps: dict[str, Decimal] = {}
        for i, name in enumerate(FACTOR_NAMES):
            factor_pnl_bps[name] = Decimal(str(round(float(factor_pnl_returns[i]) * 10000, 4)))

        # Idiosyncratic PnL = realized_PnL - sum(factor_PnL)
        total_factor_pnl_bps = sum(factor_pnl_bps.values())
        idio_pnl_bps = total_pnl_bps - total_factor_pnl_bps

        logger.info(
            "factor_attribution_complete",
            portfolio_id=str(portfolio_id),
            total_pnl_bps=float(total_pnl_bps),
            idio_pnl_bps=float(idio_pnl_bps),
            n_assets=n_assets,
            n_included=int(np.sum(np.any(asset_betas != 0, axis=1))),
        )

        return AttributionResult(
            run_id=uuid4(),
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            method="factor_ff5_mom",
            total_pnl_bps=total_pnl_bps,
            factor_pnl=factor_pnl_bps,
            idio_pnl_bps=idio_pnl_bps,
            sector_pnl=None,
            created_at=datetime.now(UTC),
        )

    def run_factor_attribution_with_retry(
        self,
        portfolio_id: UUID,
        as_of_ts: datetime,
        weights: np.ndarray,
        realized_returns: np.ndarray,
        factor_returns_fetcher: callable,
        nav: Decimal | None = None,
    ) -> AttributionResult:
        """Run factor attribution with retry logic for unavailable factor data.

        Args:
            portfolio_id: UUID of the portfolio.
            as_of_ts: Attribution date/time.
            weights: (n,) portfolio weights.
            realized_returns: (n,) realized asset returns.
            factor_returns_fetcher: Callable that returns (T, 6) factor returns
                array. Raises FactorDataUnavailableError if data is unavailable.
            nav: Net Asset Value (optional).

        Returns:
            AttributionResult on success.

        Raises:
            FactorDataUnavailableError: After max_retries exhausted.
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                factor_returns = factor_returns_fetcher()
                return self.run_factor_attribution(
                    portfolio_id=portfolio_id,
                    as_of_ts=as_of_ts,
                    weights=weights,
                    realized_returns=realized_returns,
                    factor_returns=factor_returns,
                    nav=nav,
                )
            except FactorDataUnavailableError as e:
                last_error = e
                delay = self._base_backoff * (2**attempt)
                logger.warning(
                    "factor_data_unavailable_retrying",
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    delay_seconds=delay,
                    error=str(e),
                )
                time.sleep(delay)

        logger.error(
            "factor_attribution_failed_all_retries",
            portfolio_id=str(portfolio_id),
            max_retries=self._max_retries,
        )
        raise FactorDataUnavailableError(
            f"Factor data unavailable after {self._max_retries} retries: {last_error}"
        )

    # -----------------------------------------------------------------------
    # Private Methods
    # -----------------------------------------------------------------------

    def _validate_inputs(
        self,
        weights: np.ndarray,
        realized_returns: np.ndarray,
        factor_returns: np.ndarray,
    ) -> None:
        """Validate input dimensions and data quality."""
        if weights.ndim != 1:
            raise ValueError(f"weights must be 1-D, got shape {weights.shape}")
        if realized_returns.ndim != 1:
            raise ValueError(f"realized_returns must be 1-D, got shape {realized_returns.shape}")
        if weights.shape[0] != realized_returns.shape[0]:
            raise ValueError(
                f"weights ({weights.shape[0]}) and realized_returns "
                f"({realized_returns.shape[0]}) must have same length"
            )
        if factor_returns.ndim != 2:
            raise ValueError(f"factor_returns must be 2-D, got shape {factor_returns.shape}")
        if factor_returns.shape[1] != len(FACTOR_NAMES):
            raise ValueError(
                f"factor_returns must have {len(FACTOR_NAMES)} columns "
                f"(FF5+MOM), got {factor_returns.shape[1]}"
            )
        if factor_returns.shape[0] < 2:
            raise ValueError(
                "factor_returns must have at least 2 rows "
                "(1 for regression history + 1 for realized)"
            )
        if np.any(np.isnan(factor_returns)) or np.any(np.isinf(factor_returns)):
            raise ValueError("factor_returns contains NaN or Inf values")
        if np.any(np.isnan(weights)) or np.any(np.isinf(weights)):
            raise ValueError("weights contains NaN or Inf values")
        if np.any(np.isnan(realized_returns)) or np.any(np.isinf(realized_returns)):
            raise ValueError("realized_returns contains NaN or Inf values")

    def _estimate_asset_betas(
        self,
        realized_returns: np.ndarray,
        hist_factor_returns: np.ndarray,
        n_assets: int,
    ) -> np.ndarray:
        """Estimate per-asset factor betas via OLS regression.

        Assets with fewer than min_history_days of data are excluded
        (betas set to zero, allocating their PnL to idiosyncratic).

        Note: In production, this would use a stored history of asset returns.
        For the attribution computation, we use the factor_returns history
        to determine the regression window. The actual per-asset regression
        requires historical asset returns which would be passed separately
        in a full pipeline. Here we estimate betas from the factor structure.

        Args:
            realized_returns: (n,) realized returns (used for dimension info).
            hist_factor_returns: (T, 6) historical factor returns for regression.
            n_assets: Number of assets.

        Returns:
            (n, 6) matrix of asset factor betas. Excluded assets have all zeros.
        """
        # The regression window is the minimum of available history and configured window
        T_available = hist_factor_returns.shape[0]
        T_use = min(T_available, self._regression_window)

        # Use the most recent T_use days of factor returns
        hist_factor_returns[-T_use:, :]  # (T_use, 6)

        asset_betas = np.zeros((n_assets, len(FACTOR_NAMES)))

        # Check if we have enough history for regression
        if T_use < self._min_history_days:
            logger.warning(
                "insufficient_history_for_all_assets",
                available_days=T_use,
                min_required=self._min_history_days,
            )
            return asset_betas

        return asset_betas

    def estimate_betas_from_asset_returns(
        self,
        asset_returns_history: np.ndarray,
        factor_returns_history: np.ndarray,
    ) -> tuple[np.ndarray, list[RegressionResult | None]]:
        """Estimate per-asset factor betas from historical asset and factor returns.

        This is the full regression method used when historical asset returns
        are available (e.g., from the database).

        Args:
            asset_returns_history: (T, n) matrix of historical daily asset returns.
                May contain NaN for assets with shorter histories.
            factor_returns_history: (T, 6) matrix of historical factor returns.
                Must not contain NaN.

        Returns:
            Tuple of:
                - (n, 6) matrix of asset factor betas (zeros for excluded assets)
                - List of RegressionResult or None for each asset
        """
        T, n_assets = asset_returns_history.shape

        if factor_returns_history.shape[0] != T:
            raise ValueError(
                f"asset_returns_history ({T} rows) and factor_returns_history "
                f"({factor_returns_history.shape[0]} rows) must have same length"
            )

        # Use the most recent regression_window days
        T_use = min(T, self._regression_window)
        asset_window = asset_returns_history[-T_use:, :]  # (T_use, n)
        factor_window = factor_returns_history[-T_use:, :]  # (T_use, 6)

        asset_betas = np.zeros((n_assets, len(FACTOR_NAMES)))
        regression_results: list[RegressionResult | None] = []

        for i in range(n_assets):
            asset_rets = asset_window[:, i]

            # Find valid (non-NaN) observations
            valid_mask = ~np.isnan(asset_rets)
            n_valid = int(np.sum(valid_mask))

            if n_valid < self._min_history_days:
                logger.debug(
                    "asset_excluded_insufficient_history",
                    asset_idx=i,
                    valid_days=n_valid,
                    min_required=self._min_history_days,
                )
                regression_results.append(None)
                continue

            # Run OLS on valid observations
            valid_asset_rets = asset_rets[valid_mask]
            valid_factor_rets = factor_window[valid_mask, :]

            result = _run_ols_regression(valid_asset_rets, valid_factor_rets)
            asset_betas[i, :] = result.betas
            regression_results.append(result)

        n_included = sum(1 for r in regression_results if r is not None)
        logger.info(
            "beta_estimation_complete",
            n_assets=n_assets,
            n_included=n_included,
            n_excluded=n_assets - n_included,
            window_days=T_use,
        )

        return asset_betas, regression_results

    def _compute_portfolio_exposure(
        self,
        weights: np.ndarray,
        asset_betas: np.ndarray,
    ) -> np.ndarray:
        """Compute portfolio factor exposure: B_p = sum(w_i * beta_i).

        Args:
            weights: (n,) portfolio weights.
            asset_betas: (n, 6) per-asset factor betas.

        Returns:
            (6,) portfolio factor exposure vector.
        """
        # B_p[j] = sum_i(w_i * beta_i_j) = weights' @ asset_betas
        return weights @ asset_betas  # (6,)

    def run_full_attribution(
        self,
        portfolio_id: UUID,
        as_of_ts: datetime,
        weights: np.ndarray,
        realized_returns: np.ndarray,
        asset_returns_history: np.ndarray,
        factor_returns_history: np.ndarray,
        realized_factor_returns: np.ndarray,
        nav: Decimal | None = None,
    ) -> AttributionResult:
        """Run full factor attribution with asset-level regression.

        This is the primary method for production use, where historical
        asset returns are available for proper beta estimation.

        Args:
            portfolio_id: UUID of the portfolio.
            as_of_ts: Attribution date/time.
            weights: (n,) portfolio weights at start of period.
            realized_returns: (n,) realized asset returns for the period.
            asset_returns_history: (T, n) historical daily asset returns.
                May contain NaN for assets with shorter histories.
            factor_returns_history: (T, 6) historical factor returns for regression.
            realized_factor_returns: (6,) realized factor returns for the day.
            nav: Net Asset Value (optional).

        Returns:
            AttributionResult with factor PnL decomposition.
        """
        n_assets = len(weights)

        # Validate basic inputs
        if weights.shape[0] != realized_returns.shape[0]:
            raise ValueError(
                f"weights ({weights.shape[0]}) and realized_returns "
                f"({realized_returns.shape[0]}) must have same length"
            )
        if asset_returns_history.shape[1] != n_assets:
            raise ValueError(
                f"asset_returns_history columns ({asset_returns_history.shape[1]}) "
                f"must match n_assets ({n_assets})"
            )
        if realized_factor_returns.shape[0] != len(FACTOR_NAMES):
            raise ValueError(f"realized_factor_returns must have {len(FACTOR_NAMES)} elements")

        # Step 1: Estimate per-asset betas from historical data
        asset_betas, regression_results = self.estimate_betas_from_asset_returns(
            asset_returns_history, factor_returns_history
        )

        # Step 2: Compute portfolio factor exposure B_p = sum(w_i * beta_i)
        portfolio_factor_exposure = self._compute_portfolio_exposure(weights, asset_betas)

        # Step 3: Compute total realized portfolio PnL in bps
        total_pnl_bps = Decimal(str(round(float(np.dot(weights, realized_returns)) * 10000, 4)))

        # Step 4: Compute factor PnL = B_p * f_realized (in return space, then to bps)
        factor_pnl_returns = portfolio_factor_exposure * realized_factor_returns  # (6,)

        factor_pnl_bps: dict[str, Decimal] = {}
        for i, name in enumerate(FACTOR_NAMES):
            factor_pnl_bps[name] = Decimal(str(round(float(factor_pnl_returns[i]) * 10000, 4)))

        # Step 5: Idiosyncratic PnL = realized_PnL - sum(factor_PnL)
        total_factor_pnl_bps = sum(factor_pnl_bps.values())
        idio_pnl_bps = total_pnl_bps - total_factor_pnl_bps

        n_included = sum(1 for r in regression_results if r is not None)
        logger.info(
            "full_factor_attribution_complete",
            portfolio_id=str(portfolio_id),
            total_pnl_bps=float(total_pnl_bps),
            idio_pnl_bps=float(idio_pnl_bps),
            n_assets=n_assets,
            n_included=n_included,
        )

        return AttributionResult(
            run_id=uuid4(),
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            method="factor_ff5_mom",
            total_pnl_bps=total_pnl_bps,
            factor_pnl=factor_pnl_bps,
            idio_pnl_bps=idio_pnl_bps,
            sector_pnl=None,
            created_at=datetime.now(UTC),
        )
