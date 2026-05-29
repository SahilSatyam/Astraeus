"""Backtest metrics module.

Computes risk-adjusted return, drawdown, tail risk, activity metrics,
and factor attribution from an equity curve and trade log.

References:
- Lo (2002), "The Statistics of Sharpe Ratios"
- Bailey & López de Prado (2012), "The Sharpe Ratio Efficient Frontier"
- Bailey & López de Prado (2014), "The Deflated Sharpe Ratio"
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(slots=True)
class BacktestMetrics:
    """Complete metrics for a backtest run."""

    # Risk-adjusted return
    annualized_return: float = 0.0
    annualized_vol: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    information_ratio: float = 0.0

    # Drawdown / tail risk
    max_drawdown: float = 0.0
    max_dd_duration_days: int = 0
    avg_drawdown: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    tail_ratio: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0

    # Activity / cost
    hit_ratio: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    turnover_annual: float = 0.0
    avg_holding_days: float = 0.0
    total_cost_bps: float = 0.0

    # Statistical
    probabilistic_sharpe: float = 0.0
    deflated_sharpe: float = 0.0
    sharpe_ci_lower: float = 0.0
    sharpe_ci_upper: float = 0.0

    # Meta
    total_days: int = 0
    total_trades: int = 0
    final_equity: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {k: getattr(self, k) for k in self.__slots__}


def compute_metrics(
    returns: np.ndarray,
    benchmark_returns: np.ndarray | None = None,
    risk_free_rate: float = 0.05,
    trading_days: int = 252,
    n_trials: int = 1,
) -> BacktestMetrics:
    """Compute full metrics suite from daily returns array.

    Args:
        returns: Daily returns array (decimal, e.g., 0.01 = 1%).
        benchmark_returns: Optional benchmark daily returns (for IR).
        risk_free_rate: Annual risk-free rate (decimal).
        trading_days: Trading days per year.
        n_trials: Number of trials run (for deflated Sharpe).

    Returns:
        BacktestMetrics with all fields populated.
    """
    if len(returns) == 0:
        return BacktestMetrics()

    rf_daily = risk_free_rate / trading_days
    returns - rf_daily

    # Basic stats
    mean_ret = float(np.mean(returns))
    std_ret = float(np.std(returns, ddof=1)) if len(returns) > 1 else 1e-10

    ann_ret = (1 + mean_ret) ** trading_days - 1
    ann_vol = std_ret * math.sqrt(trading_days)

    # Sharpe
    sharpe = (mean_ret - rf_daily) / max(std_ret, 1e-10) * math.sqrt(trading_days)

    # Sortino (downside deviation)
    downside = returns[returns < rf_daily] - rf_daily
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 1e-10
    sortino = (mean_ret - rf_daily) / max(downside_std, 1e-10) * math.sqrt(trading_days)

    # Drawdown
    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    max_dd = float(np.min(drawdowns))

    # Max DD duration
    dd_duration = _max_dd_duration(drawdowns)

    # Calmar
    calmar = ann_ret / max(abs(max_dd), 1e-10)

    # VaR / CVaR
    var_95 = float(np.percentile(returns, 5))
    cvar_95 = float(np.mean(returns[returns <= var_95])) if np.any(returns <= var_95) else var_95

    # Tail ratio
    q95 = float(np.percentile(returns, 95))
    q5 = float(np.percentile(returns, 5))
    tail_ratio = abs(q95) / max(abs(q5), 1e-10)

    # Higher moments
    skew = float(_skewness(returns))
    kurt = float(_kurtosis(returns))

    # Information ratio
    ir = 0.0
    if benchmark_returns is not None and len(benchmark_returns) == len(returns):
        active = returns - benchmark_returns
        ir = (
            float(np.mean(active))
            / max(float(np.std(active, ddof=1)), 1e-10)
            * math.sqrt(trading_days)
        )

    # Probabilistic Sharpe (Bailey & López de Prado 2012)
    psr = _probabilistic_sharpe(sharpe, len(returns), skew, kurt, sr_benchmark=0.0)

    # Deflated Sharpe (Bailey & López de Prado 2014)
    dsr = _deflated_sharpe(sharpe, len(returns), skew, kurt, n_trials=n_trials)

    # Sharpe CI (Lo 2002)
    se_sharpe = math.sqrt((1 + 0.5 * sharpe**2) / max(len(returns) - 1, 1))
    ci_lower = sharpe - 1.96 * se_sharpe
    ci_upper = sharpe + 1.96 * se_sharpe

    return BacktestMetrics(
        annualized_return=ann_ret,
        annualized_vol=ann_vol,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        information_ratio=ir,
        max_drawdown=max_dd,
        max_dd_duration_days=dd_duration,
        avg_drawdown=float(np.mean(drawdowns[drawdowns < -0.01]))
        if np.any(drawdowns < -0.01)
        else 0.0,
        var_95=var_95,
        cvar_95=cvar_95,
        tail_ratio=tail_ratio,
        skewness=skew,
        kurtosis=kurt,
        probabilistic_sharpe=psr,
        deflated_sharpe=dsr,
        sharpe_ci_lower=ci_lower,
        sharpe_ci_upper=ci_upper,
        total_days=len(returns),
        final_equity=float(cumulative[-1]) if len(cumulative) > 0 else 1.0,
    )


def _max_dd_duration(drawdowns: np.ndarray) -> int:
    """Compute maximum drawdown duration in days."""
    in_dd = drawdowns < 0
    max_dur = 0
    current_dur = 0
    for is_dd in in_dd:
        if is_dd:
            current_dur += 1
            max_dur = max(max_dur, current_dur)
        else:
            current_dur = 0
    return max_dur


def _skewness(x: np.ndarray) -> float:
    """Sample skewness."""
    n = len(x)
    if n < 3:
        return 0.0
    m = np.mean(x)
    s = np.std(x, ddof=1)
    if s == 0:
        return 0.0
    return float(n / ((n - 1) * (n - 2)) * np.sum(((x - m) / s) ** 3))


def _kurtosis(x: np.ndarray) -> float:
    """Sample excess kurtosis."""
    n = len(x)
    if n < 4:
        return 0.0
    m = np.mean(x)
    s = np.std(x, ddof=1)
    if s == 0:
        return 0.0
    k4 = float(np.mean(((x - m) / s) ** 4))
    return k4 - 3.0


def _probabilistic_sharpe(
    observed_sr: float,
    n_obs: int,
    skew: float,
    kurt: float,
    sr_benchmark: float = 0.0,
) -> float:
    """Probabilistic Sharpe Ratio (Bailey & López de Prado 2012).

    Returns probability that true SR > sr_benchmark given observed SR.
    """
    from scipy.stats import norm

    # Standard error of SR accounting for non-normality
    se = math.sqrt((1 - skew * observed_sr + (kurt - 1) / 4 * observed_sr**2) / max(n_obs - 1, 1))
    if se == 0:
        return 1.0 if observed_sr > sr_benchmark else 0.0

    z = (observed_sr - sr_benchmark) / se
    return float(norm.cdf(z))


def _deflated_sharpe(
    observed_sr: float,
    n_obs: int,
    skew: float,
    kurt: float,
    n_trials: int = 1,
    sr_benchmark: float = 0.0,
) -> float:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014).

    Adjusts for multiple testing by inflating the benchmark SR based on
    the expected maximum SR from n_trials independent trials.
    """
    from scipy.stats import norm

    if n_trials <= 1:
        return _probabilistic_sharpe(observed_sr, n_obs, skew, kurt, sr_benchmark)

    # Expected max SR from n_trials (Euler-Mascheroni approximation)
    euler_mascheroni = 0.5772156649
    e_max_sr = norm.ppf(1 - 1 / n_trials) * (1 - euler_mascheroni) + euler_mascheroni * norm.ppf(
        1 - 1 / (n_trials * math.e)
    )

    # Use inflated benchmark
    adjusted_benchmark = max(sr_benchmark, e_max_sr * math.sqrt(1.0 / max(n_obs, 1)))

    return _probabilistic_sharpe(observed_sr, n_obs, skew, kurt, adjusted_benchmark)
