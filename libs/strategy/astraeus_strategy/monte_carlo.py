"""Monte Carlo simulation module.

Two modes:
(a) Bootstrapped returns — stationary block bootstrap (Politis & Romano 1994)
    with block length per Politis & White (2004). Reports confidence bands.
(b) Parameter perturbation — perturb each param ±1σ on a grid to test
    sensitivity. A sharp peak at the optimum is overfitting; wide plateau
    is more credible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

from astraeus_strategy.metrics import BacktestMetrics, compute_metrics

logger = structlog.get_logger("astraeus.strategy.monte_carlo")


@dataclass(slots=True)
class MonteCarloResult:
    """Results from Monte Carlo simulation."""

    n_paths: int = 0
    sharpe_mean: float = 0.0
    sharpe_std: float = 0.0
    sharpe_5th: float = 0.0
    sharpe_95th: float = 0.0
    return_mean: float = 0.0
    return_5th: float = 0.0
    return_95th: float = 0.0
    max_dd_mean: float = 0.0
    max_dd_5th: float = 0.0
    max_dd_95th: float = 0.0
    prob_positive_sharpe: float = 0.0
    all_sharpes: list[float] = field(default_factory=list)


def bootstrap_returns(
    returns: np.ndarray,
    n_paths: int = 1000,
    block_length: int | None = None,
    seed: int = 42,
) -> MonteCarloResult:
    """Stationary block bootstrap on daily returns.

    Generates n_paths synthetic return series by resampling blocks of
    the original returns. Block length is auto-selected if not provided
    (Politis & White 2004 optimal block length).

    Args:
        returns: Original daily returns array.
        n_paths: Number of bootstrap paths to generate.
        block_length: Fixed block length (auto if None).
        seed: Random seed for reproducibility.

    Returns:
        MonteCarloResult with distribution statistics.
    """
    rng = np.random.default_rng(seed)
    n = len(returns)

    if n < 30:
        logger.warning("insufficient_data_for_bootstrap", n=n)
        return MonteCarloResult()

    # Auto block length: Politis & White (2004) approximation
    if block_length is None:
        # Simple heuristic: cube root of sample size
        block_length = max(int(n ** (1 / 3)), 5)

    sharpes: list[float] = []
    ann_returns: list[float] = []
    max_dds: list[float] = []

    for _ in range(n_paths):
        # Generate synthetic path via block bootstrap
        synthetic = _block_bootstrap(returns, n, block_length, rng)
        metrics = compute_metrics(synthetic)
        sharpes.append(metrics.sharpe)
        ann_returns.append(metrics.annualized_return)
        max_dds.append(metrics.max_drawdown)

    sharpes_arr = np.array(sharpes)
    returns_arr = np.array(ann_returns)
    dds_arr = np.array(max_dds)

    return MonteCarloResult(
        n_paths=n_paths,
        sharpe_mean=float(np.mean(sharpes_arr)),
        sharpe_std=float(np.std(sharpes_arr)),
        sharpe_5th=float(np.percentile(sharpes_arr, 5)),
        sharpe_95th=float(np.percentile(sharpes_arr, 95)),
        return_mean=float(np.mean(returns_arr)),
        return_5th=float(np.percentile(returns_arr, 5)),
        return_95th=float(np.percentile(returns_arr, 95)),
        max_dd_mean=float(np.mean(dds_arr)),
        max_dd_5th=float(np.percentile(dds_arr, 5)),
        max_dd_95th=float(np.percentile(dds_arr, 95)),
        prob_positive_sharpe=float(np.mean(sharpes_arr > 0)),
        all_sharpes=sharpes,
    )


def parameter_perturbation(
    base_params: dict[str, float],
    run_fn: Any,  # Callable[[dict], BacktestMetrics]
    sigma: dict[str, float] | None = None,
    n_steps: int = 5,
    seed: int = 42,
) -> dict[str, list[tuple[float, float]]]:
    """Perturb each parameter ±1σ and measure Sharpe sensitivity.

    For each parameter, varies it across n_steps while holding others fixed.
    A sharp peak at the optimum suggests overfitting; a wide plateau is
    more credible.

    Args:
        base_params: Optimal parameter values.
        run_fn: Function that takes params dict and returns BacktestMetrics.
        sigma: Per-parameter standard deviation for perturbation.
            If None, uses 10% of base value.
        n_steps: Number of steps in each direction.
        seed: Random seed.

    Returns:
        Dict mapping param_name to list of (param_value, sharpe) tuples.
    """
    if sigma is None:
        sigma = {k: abs(v) * 0.1 + 1e-6 for k, v in base_params.items()}

    results: dict[str, list[tuple[float, float]]] = {}

    for param_name, base_value in base_params.items():
        param_sigma = sigma.get(param_name, abs(base_value) * 0.1 + 1e-6)
        sweep: list[tuple[float, float]] = []

        for step in range(-n_steps, n_steps + 1):
            perturbed_value = base_value + step * param_sigma / n_steps
            test_params = {**base_params, param_name: perturbed_value}

            try:
                metrics = run_fn(test_params)
                sweep.append((perturbed_value, metrics.sharpe))
            except Exception:
                sweep.append((perturbed_value, float("nan")))

        results[param_name] = sweep

    return results


def _block_bootstrap(
    returns: np.ndarray,
    target_length: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate a single bootstrap path using stationary block bootstrap."""
    n = len(returns)
    result = np.empty(target_length)
    pos = 0

    while pos < target_length:
        # Random start point
        start = rng.integers(0, n)
        # Geometric block length (stationary bootstrap)
        actual_block = min(
            rng.geometric(1.0 / block_length),
            target_length - pos,
        )

        for i in range(actual_block):
            result[pos] = returns[(start + i) % n]
            pos += 1
            if pos >= target_length:
                break

    return result
