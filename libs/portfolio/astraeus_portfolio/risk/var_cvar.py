"""VaR/CVaR computation: historical, parametric, Monte Carlo.

Implements three methods for Value-at-Risk and Conditional Value-at-Risk:
1. Historical: negative β-quantile of portfolio daily returns
2. Parametric: -(μ + z_β·σ) assuming Gaussian distribution
3. Monte Carlo: t-copula (df=4, 10000 paths) with deterministic seed

All results are expressed as a percentage of portfolio NAV.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.stats import norm
from scipy.stats import t as t_dist

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Configuration
# ---------------------------------------------------------------------------


class VaRMethod(StrEnum):
    """Supported VaR computation methods."""

    HISTORICAL = "historical"
    PARAMETRIC = "parametric"
    MONTE_CARLO = "monte_carlo"


@dataclass(frozen=True)
class VaRConfig:
    """Configuration for VaR/CVaR computation."""

    lookback_window: int = 252
    min_observations: int = 60
    mc_paths: int = 10_000
    mc_df: int = 4  # t-copula degrees of freedom
    confidence_levels: tuple[float, ...] = (0.95, 0.99)
    discrepancy_threshold: float = 0.50


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InsufficientDataError(Exception):
    """Raised when insufficient trading days are available."""

    def __init__(self, available: int, minimum_required: int) -> None:
        self.available = available
        self.minimum_required = minimum_required
        super().__init__(
            f"Insufficient trading days: {available} available, {minimum_required} required."
        )


# ---------------------------------------------------------------------------
# Result Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VaRResult:
    """Result for a single VaR/CVaR computation at one confidence level."""

    method: VaRMethod
    confidence_level: float
    var_pct: float  # VaR as percentage of NAV (positive = loss)
    cvar_pct: float  # CVaR as percentage of NAV (positive = loss)


@dataclass(frozen=True)
class VaRReport:
    """Complete VaR/CVaR report across all methods and confidence levels."""

    results: list[VaRResult]
    discrepancy_warnings: list[str]
    lookback_days_used: int
    n_observations: int


# ---------------------------------------------------------------------------
# Core Computation Functions
# ---------------------------------------------------------------------------


def _validate_returns(portfolio_returns: np.ndarray, min_observations: int) -> None:
    """Validate portfolio return series has sufficient data.

    Args:
        portfolio_returns: 1-D array of portfolio daily returns.
        min_observations: Minimum number of trading days required.

    Raises:
        InsufficientDataError: If fewer than min_observations available.
        ValueError: If returns contain NaN or Inf values.
    """
    if portfolio_returns.ndim != 1:
        raise ValueError(f"portfolio_returns must be 1-D, got shape {portfolio_returns.shape}")

    if np.any(np.isnan(portfolio_returns)):
        raise ValueError("portfolio_returns contains NaN values")

    if np.any(np.isinf(portfolio_returns)):
        raise ValueError("portfolio_returns contains Inf values")

    n = len(portfolio_returns)
    if n < min_observations:
        raise InsufficientDataError(available=n, minimum_required=min_observations)


def compute_historical_var(
    portfolio_returns: np.ndarray,
    confidence_level: float,
    lookback_window: int = 252,
) -> tuple[float, float]:
    """Compute historical VaR and CVaR.

    VaR = negative of the (1-β) quantile of portfolio daily returns.
    CVaR = mean of returns at or below the VaR threshold.

    Args:
        portfolio_returns: 1-D array of portfolio daily returns.
        confidence_level: Confidence level β (e.g. 0.95 or 0.99).
        lookback_window: Number of trading days to use.

    Returns:
        Tuple of (VaR_pct, CVaR_pct) as positive percentages of NAV.
    """
    # Use the most recent lookback_window days
    returns = portfolio_returns[-lookback_window:]

    # VaR: negative of the (1-β) quantile
    quantile_level = 1.0 - confidence_level
    var_threshold = np.quantile(returns, quantile_level)
    var_pct = -var_threshold * 100.0  # Convert to positive percentage

    # CVaR: mean of returns at or below the VaR threshold
    tail_returns = returns[returns <= var_threshold]
    if len(tail_returns) == 0:
        # Edge case: no returns at or below threshold
        cvar_pct = var_pct
    else:
        cvar_pct = -np.mean(tail_returns) * 100.0

    return var_pct, cvar_pct


def compute_parametric_var(
    portfolio_returns: np.ndarray,
    confidence_level: float,
    lookback_window: int = 252,
) -> tuple[float, float]:
    """Compute parametric (Gaussian) VaR and CVaR.

    VaR = -(μ + z_β·σ) where μ, σ are estimated from daily returns.
    CVaR = -(μ - σ·φ(z_β)/Φ(-z_β)) for Gaussian.

    Args:
        portfolio_returns: 1-D array of portfolio daily returns.
        confidence_level: Confidence level β (e.g. 0.95 or 0.99).
        lookback_window: Number of trading days to use.

    Returns:
        Tuple of (VaR_pct, CVaR_pct) as positive percentages of NAV.
    """
    # Use the most recent lookback_window days
    returns = portfolio_returns[-lookback_window:]

    mu = np.mean(returns)
    sigma = np.std(returns, ddof=1)

    # z_β is the quantile of the standard normal at (1-β)
    # For β=0.95, z_β = norm.ppf(0.05) ≈ -1.645
    z_beta = norm.ppf(1.0 - confidence_level)

    # VaR = -(μ + z_β·σ)
    var_value = -(mu + z_beta * sigma)
    var_pct = var_value * 100.0

    # CVaR for Gaussian: -(μ - σ·φ(z_β)/Φ(-z_β))
    # where φ is the standard normal PDF and Φ is the CDF
    # Equivalently: CVaR = -(μ + σ · φ(z_β) / (1 - confidence_level))
    # Note: z_beta is negative, so φ(z_beta) = φ(-|z_beta|)
    alpha = 1.0 - confidence_level
    cvar_value = -(mu + sigma * (-norm.pdf(z_beta) / alpha))
    cvar_pct = cvar_value * 100.0

    return var_pct, cvar_pct


def compute_monte_carlo_var(
    portfolio_returns: np.ndarray,
    confidence_level: float,
    lookback_window: int = 252,
    n_paths: int = 10_000,
    df: int = 4,
    seed: int = 42,
) -> tuple[float, float]:
    """Compute Monte Carlo VaR and CVaR using t-copula simulation.

    Simulates portfolio returns using a t-copula with specified degrees of
    freedom, calibrated to the portfolio's historical marginal distribution.

    Args:
        portfolio_returns: 1-D array of portfolio daily returns.
        confidence_level: Confidence level β (e.g. 0.95 or 0.99).
        lookback_window: Number of trading days to use.
        n_paths: Number of simulated paths (default 10000).
        df: Degrees of freedom for t-copula (default 4).
        seed: Deterministic seed for reproducibility.

    Returns:
        Tuple of (VaR_pct, CVaR_pct) as positive percentages of NAV.
    """
    # Use the most recent lookback_window days
    returns = portfolio_returns[-lookback_window:]

    rng = np.random.default_rng(seed)

    # Estimate parameters from historical returns
    np.mean(returns)
    np.std(returns, ddof=1)

    # Generate t-distributed random samples (t-copula with 1 dimension)
    # For a single portfolio return series, the t-copula simplifies to
    # generating t-distributed samples and transforming to match marginals
    #
    # Steps:
    # 1. Generate t-distributed samples with df degrees of freedom
    # 2. Transform through t-CDF to get uniform [0,1]
    # 3. Apply inverse of empirical CDF to get simulated returns

    # Generate t-distributed samples
    t_samples = rng.standard_t(df=df, size=n_paths)

    # Transform through t-CDF to get uniform samples
    uniform_samples = t_dist.cdf(t_samples, df=df)

    # Apply inverse of empirical distribution (quantile function)
    # Use sorted historical returns as the empirical distribution
    simulated_returns = np.quantile(returns, uniform_samples)

    # Compute VaR from simulated distribution
    quantile_level = 1.0 - confidence_level
    var_threshold = np.quantile(simulated_returns, quantile_level)
    var_pct = -var_threshold * 100.0

    # CVaR: mean of simulated returns at or below VaR threshold
    tail_returns = simulated_returns[simulated_returns <= var_threshold]
    if len(tail_returns) == 0:
        cvar_pct = var_pct
    else:
        cvar_pct = -np.mean(tail_returns) * 100.0

    return var_pct, cvar_pct


# ---------------------------------------------------------------------------
# Multi-Asset Monte Carlo (t-copula)
# ---------------------------------------------------------------------------


def compute_monte_carlo_var_multivariate(
    asset_returns: np.ndarray,
    weights: np.ndarray,
    confidence_level: float,
    lookback_window: int = 252,
    n_paths: int = 10_000,
    df: int = 4,
    seed: int = 42,
) -> tuple[float, float]:
    """Compute Monte Carlo VaR/CVaR using multivariate t-copula.

    For multi-asset portfolios, simulates correlated asset returns using
    a t-copula calibrated to the correlation structure of historical returns.

    Args:
        asset_returns: T×n matrix of daily asset returns.
        weights: (n,) portfolio weight vector.
        confidence_level: Confidence level β.
        lookback_window: Number of trading days to use.
        n_paths: Number of simulated paths.
        df: Degrees of freedom for t-copula.
        seed: Deterministic seed.

    Returns:
        Tuple of (VaR_pct, CVaR_pct) as positive percentages of NAV.
    """
    # Use the most recent lookback_window days
    returns = asset_returns[-lookback_window:]
    n_assets = returns.shape[1]

    rng = np.random.default_rng(seed)

    # Compute correlation matrix from historical returns
    corr_matrix = np.corrcoef(returns, rowvar=False)

    # Ensure PSD
    eigvals = np.linalg.eigvalsh(corr_matrix)
    if np.any(eigvals < 0):
        # Apply eigenvalue floor
        eigvals_full, eigvecs = np.linalg.eigh(corr_matrix)
        eigvals_full = np.maximum(eigvals_full, 1e-8)
        corr_matrix = eigvecs @ np.diag(eigvals_full) @ eigvecs.T
        # Re-normalize to correlation matrix
        d = np.sqrt(np.diag(corr_matrix))
        corr_matrix = corr_matrix / np.outer(d, d)

    # Generate multivariate t-distributed samples via t-copula
    # 1. Generate multivariate normal with correlation structure
    # 2. Generate chi-squared for t-distribution scaling
    # 3. Combine to get multivariate t samples
    # 4. Transform through t-CDF to get uniform copula samples
    # 5. Apply inverse empirical CDF per asset

    # Step 1: Cholesky decomposition of correlation matrix
    try:
        L = np.linalg.cholesky(corr_matrix)
    except np.linalg.LinAlgError:
        # Fallback: use eigendecomposition
        eigvals_full, eigvecs = np.linalg.eigh(corr_matrix)
        eigvals_full = np.maximum(eigvals_full, 1e-8)
        L = eigvecs @ np.diag(np.sqrt(eigvals_full))

    # Step 2: Generate standard normal samples and correlate
    z = rng.standard_normal((n_paths, n_assets))
    correlated_normals = z @ L.T

    # Step 3: Generate chi-squared scaling for t-distribution
    chi2_samples = rng.chisquare(df=df, size=n_paths)
    scaling = np.sqrt(df / chi2_samples)
    t_samples = correlated_normals * scaling[:, np.newaxis]

    # Step 4: Transform through t-CDF to get uniform [0,1]
    uniform_samples = t_dist.cdf(t_samples, df=df)

    # Step 5: Apply inverse empirical CDF per asset
    simulated_asset_returns = np.empty_like(uniform_samples)
    for i in range(n_assets):
        simulated_asset_returns[:, i] = np.quantile(returns[:, i], uniform_samples[:, i])

    # Compute portfolio returns from simulated asset returns
    simulated_portfolio_returns = simulated_asset_returns @ weights

    # Compute VaR
    quantile_level = 1.0 - confidence_level
    var_threshold = np.quantile(simulated_portfolio_returns, quantile_level)
    var_pct = -var_threshold * 100.0

    # CVaR: mean of returns at or below VaR threshold
    tail_returns = simulated_portfolio_returns[simulated_portfolio_returns <= var_threshold]
    if len(tail_returns) == 0:
        cvar_pct = var_pct
    else:
        cvar_pct = -np.mean(tail_returns) * 100.0

    return var_pct, cvar_pct


# ---------------------------------------------------------------------------
# Discrepancy Detection
# ---------------------------------------------------------------------------


def _check_discrepancy(
    var_hist: float,
    var_param: float,
    confidence_level: float,
    threshold: float = 0.50,
) -> str | None:
    """Check if historical and parametric VaR differ by more than threshold.

    Args:
        var_hist: Historical VaR (positive percentage).
        var_param: Parametric VaR (positive percentage).
        confidence_level: The confidence level for the comparison.
        threshold: Maximum allowed relative difference (default 0.50 = 50%).

    Returns:
        Warning message if discrepancy detected, None otherwise.
    """
    if var_hist <= 0 or var_param <= 0:
        return None

    min_var = min(var_hist, var_param)
    if min_var == 0:
        return None

    relative_diff = abs(var_hist - var_param) / min_var

    if relative_diff > threshold:
        return (
            f"VaR discrepancy at {confidence_level:.0%} confidence: "
            f"|VaR_hist ({var_hist:.4f}%) - VaR_param ({var_param:.4f}%)| / "
            f"min = {relative_diff:.2%} exceeds threshold {threshold:.0%}"
        )
    return None


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def compute_var_cvar(
    portfolio_returns: np.ndarray,
    config: VaRConfig | None = None,
    seed: int = 42,
) -> VaRReport:
    """Compute VaR/CVaR using all three methods at all confidence levels.

    This is the primary entry point for single-series portfolio returns.

    Args:
        portfolio_returns: 1-D array of portfolio daily returns (most recent last).
        config: VaR computation configuration. Uses defaults if None.
        seed: Deterministic seed for Monte Carlo simulation.

    Returns:
        VaRReport with results for all methods and confidence levels.

    Raises:
        InsufficientDataError: If fewer than config.min_observations days available.
        ValueError: If returns contain NaN/Inf or are not 1-D.
    """
    if config is None:
        config = VaRConfig()

    # Validate input
    _validate_returns(portfolio_returns, config.min_observations)

    # Determine actual lookback window (use available data if less than window)
    n_available = len(portfolio_returns)
    lookback = min(config.lookback_window, n_available)

    results: list[VaRResult] = []
    discrepancy_warnings: list[str] = []

    for confidence_level in config.confidence_levels:
        # Historical VaR/CVaR
        hist_var, hist_cvar = compute_historical_var(portfolio_returns, confidence_level, lookback)
        results.append(
            VaRResult(
                method=VaRMethod.HISTORICAL,
                confidence_level=confidence_level,
                var_pct=hist_var,
                cvar_pct=hist_cvar,
            )
        )

        # Parametric VaR/CVaR
        param_var, param_cvar = compute_parametric_var(
            portfolio_returns, confidence_level, lookback
        )
        results.append(
            VaRResult(
                method=VaRMethod.PARAMETRIC,
                confidence_level=confidence_level,
                var_pct=param_var,
                cvar_pct=param_cvar,
            )
        )

        # Monte Carlo VaR/CVaR
        mc_var, mc_cvar = compute_monte_carlo_var(
            portfolio_returns,
            confidence_level,
            lookback,
            n_paths=config.mc_paths,
            df=config.mc_df,
            seed=seed,
        )
        results.append(
            VaRResult(
                method=VaRMethod.MONTE_CARLO,
                confidence_level=confidence_level,
                var_pct=mc_var,
                cvar_pct=mc_cvar,
            )
        )

        # Check discrepancy between historical and parametric
        warning = _check_discrepancy(
            hist_var, param_var, confidence_level, config.discrepancy_threshold
        )
        if warning is not None:
            discrepancy_warnings.append(warning)
            logger.warning(warning)

    return VaRReport(
        results=results,
        discrepancy_warnings=discrepancy_warnings,
        lookback_days_used=lookback,
        n_observations=n_available,
    )


def compute_var_cvar_multivariate(
    asset_returns: np.ndarray,
    weights: np.ndarray,
    config: VaRConfig | None = None,
    seed: int = 42,
) -> VaRReport:
    """Compute VaR/CVaR for a multi-asset portfolio.

    Uses asset-level returns and weights to compute portfolio returns for
    historical and parametric methods, and multivariate t-copula for MC.

    Args:
        asset_returns: T×n matrix of daily asset returns.
        weights: (n,) portfolio weight vector.
        config: VaR computation configuration. Uses defaults if None.
        seed: Deterministic seed for Monte Carlo simulation.

    Returns:
        VaRReport with results for all methods and confidence levels.

    Raises:
        InsufficientDataError: If fewer than config.min_observations days available.
        ValueError: If inputs are invalid.
    """
    if config is None:
        config = VaRConfig()

    if asset_returns.ndim != 2:
        raise ValueError(f"asset_returns must be 2-D (T×n), got shape {asset_returns.shape}")

    if weights.ndim != 1:
        raise ValueError(f"weights must be 1-D, got shape {weights.shape}")

    if asset_returns.shape[1] != len(weights):
        raise ValueError(
            f"asset_returns has {asset_returns.shape[1]} assets but "
            f"weights has {len(weights)} elements"
        )

    # Compute portfolio returns for historical and parametric methods
    portfolio_returns = asset_returns @ weights

    # Validate
    _validate_returns(portfolio_returns, config.min_observations)

    n_available = len(portfolio_returns)
    lookback = min(config.lookback_window, n_available)

    results: list[VaRResult] = []
    discrepancy_warnings: list[str] = []

    for confidence_level in config.confidence_levels:
        # Historical VaR/CVaR (from portfolio returns)
        hist_var, hist_cvar = compute_historical_var(portfolio_returns, confidence_level, lookback)
        results.append(
            VaRResult(
                method=VaRMethod.HISTORICAL,
                confidence_level=confidence_level,
                var_pct=hist_var,
                cvar_pct=hist_cvar,
            )
        )

        # Parametric VaR/CVaR (from portfolio returns)
        param_var, param_cvar = compute_parametric_var(
            portfolio_returns, confidence_level, lookback
        )
        results.append(
            VaRResult(
                method=VaRMethod.PARAMETRIC,
                confidence_level=confidence_level,
                var_pct=param_var,
                cvar_pct=param_cvar,
            )
        )

        # Monte Carlo VaR/CVaR (multivariate t-copula)
        mc_var, mc_cvar = compute_monte_carlo_var_multivariate(
            asset_returns,
            weights,
            confidence_level,
            lookback,
            n_paths=config.mc_paths,
            df=config.mc_df,
            seed=seed,
        )
        results.append(
            VaRResult(
                method=VaRMethod.MONTE_CARLO,
                confidence_level=confidence_level,
                var_pct=mc_var,
                cvar_pct=mc_cvar,
            )
        )

        # Check discrepancy
        warning = _check_discrepancy(
            hist_var, param_var, confidence_level, config.discrepancy_threshold
        )
        if warning is not None:
            discrepancy_warnings.append(warning)
            logger.warning(warning)

    return VaRReport(
        results=results,
        discrepancy_warnings=discrepancy_warnings,
        lookback_days_used=lookback,
        n_observations=n_available,
    )
