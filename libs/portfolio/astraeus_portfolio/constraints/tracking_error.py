"""Tracking error constraint: TE band.

Enforces (w - w_bench)' * Sigma * (w - w_bench) <= TE_max^2 where TE_max
is the maximum annualized tracking error expressed as a decimal.

Priority: 2 (relaxed after turnover but before sector/concentration).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cvxpy as cp
import numpy as np

from astraeus_portfolio.constraints.base import Constraint

if TYPE_CHECKING:
    from astraeus_portfolio.contracts import OptContext


class TrackingErrorConstraint(Constraint):
    """Tracking error constraint bounding deviation from a benchmark.

    Enforces that the ex-ante tracking error (annualized) does not exceed
    TE_max. The tracking error is computed as:
        TE = sqrt((w - w_bench)' * Sigma * (w - w_bench))

    The benchmark weights can be provided at construction time or sourced
    from the OptContext (via current_weights as a fallback).

    Attributes:
        te_max: Maximum annualized tracking error (decimal, e.g. 0.02 = 2%).
        benchmark_weights: Optional benchmark weight vector. If None, uses
            ctx.current_weights as the benchmark.
    """

    def __init__(
        self,
        te_max: float,
        benchmark_weights: np.ndarray | None = None,
    ) -> None:
        """Initialize tracking error constraint.

        Args:
            te_max: Maximum annualized tracking error (required).
            benchmark_weights: Benchmark weight vector of shape (n_assets,).
                If None, the optimizer context's current_weights are used.
        """
        super().__init__(name="tracking_error", priority=2, relaxable=True)
        self.te_max = te_max
        self.benchmark_weights = benchmark_weights

    def _get_benchmark(self, ctx: OptContext) -> np.ndarray:
        """Resolve benchmark weights from constructor or context.

        Args:
            ctx: The optimization context.

        Returns:
            Benchmark weight vector of shape (n_assets,).
        """
        if self.benchmark_weights is not None:
            return self.benchmark_weights
        return ctx.current_weights

    def to_cvxpy(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Convert to cvxpy constraint.

        Produces: cp.quad_form(w - w_bench, Sigma) <= te_max^2

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context with covariance matrix.

        Returns:
            List containing the quadratic tracking error constraint.
        """
        w_bench = self._get_benchmark(ctx)
        sigma = ctx.covariance

        return [cp.quad_form(w - w_bench, sigma) <= self.te_max**2]

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Report actual tracking error metrics.

        Args:
            w_value: The solved weight vector as a numpy array of shape (n_assets,).
            ctx: The optimization context.

        Returns:
            Dictionary with:
                - satisfied: Whether the tracking error is within the limit.
                - tracking_error: Actual annualized tracking error.
                - te_max: Configured maximum tracking error.
                - te_variance: The tracking error variance (w-w_bench)'Sigma(w-w_bench).
        """
        w_bench = self._get_benchmark(ctx)
        diff = w_value - w_bench
        sigma = ctx.covariance

        te_variance = float(diff @ sigma @ diff)
        tracking_error = float(np.sqrt(max(te_variance, 0.0)))

        satisfied = tracking_error <= self.te_max + 1e-8

        return {
            "satisfied": satisfied,
            "tracking_error": tracking_error,
            "te_max": self.te_max,
            "te_variance": te_variance,
        }
