"""Mean-Variance Optimizer: tangency, min-variance, target-return modes.

This module implements the Mean-Variance Optimization (MVO) portfolio optimizer
with three operational modes:

- **Tangency**: Maximizes the Sharpe ratio by minimizing λ·w'Σw - μ'w.
- **Min-Variance**: Minimizes portfolio variance w'Σw without using expected returns.
- **Target-Return**: Minimizes portfolio variance subject to μ'w >= r_target.

The optimizer extends the Optimizer ABC and inherits the solver chain and
constraint relaxation fallback logic from the base class.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7
"""

from __future__ import annotations

from enum import StrEnum

import cvxpy as cp
import numpy as np
import structlog

from astraeus_portfolio.contracts import OptContext, OptResult, RelaxationEvent
from astraeus_portfolio.optimizers.base import Optimizer, OptimizerConfig

__all__ = [
    "MVOMode",
    "MVOValidationError",
    "MeanVarianceOptimizer",
    "MVOOptimizer",
]

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# MVO Mode Enum
# ---------------------------------------------------------------------------


class MVOMode(StrEnum):
    """Operational modes for the Mean-Variance Optimizer."""

    TANGENCY = "tangency"
    MIN_VARIANCE = "min_variance"
    TARGET_RETURN = "target_return"


# ---------------------------------------------------------------------------
# Validation Error
# ---------------------------------------------------------------------------


class MVOValidationError(ValueError):
    """Raised when MVO input validation fails.

    Attributes:
        reason: A machine-readable reason code for the validation failure.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


# ---------------------------------------------------------------------------
# Mean-Variance Optimizer
# ---------------------------------------------------------------------------


class MeanVarianceOptimizer(Optimizer):
    """Mean-Variance Optimizer supporting tangency, min-variance, and target-return modes.

    This optimizer constructs a quadratic program whose objective depends on the
    selected mode:

    - Tangency: minimize λ·w'Σw - μ'w (risk-return tradeoff)
    - Min-Variance: minimize w'Σw (pure risk minimization)
    - Target-Return: minimize w'Σw subject to μ'w >= r_target

    The optimizer validates inputs before optimization:
    - Covariance matrix must be positive semi-definite.
    - Universe must contain at least 2 assets.
    - risk_aversion (λ) must be in [0.1, 100.0].

    Attributes:
        mode: The optimization mode (tangency, min_variance, or target_return).
        risk_aversion: The risk aversion parameter λ (used in tangency mode).
        target_return: The target annualized return (used in target_return mode).
    """

    def __init__(
        self,
        mode: MVOMode = MVOMode.TANGENCY,
        risk_aversion: float = 5.0,
        target_return: float | None = None,
        config: OptimizerConfig | None = None,
    ) -> None:
        """Initialize the Mean-Variance Optimizer.

        Args:
            mode: The optimization mode. Defaults to tangency.
            risk_aversion: Risk aversion parameter λ for tangency mode.
                Must be in [0.1, 100.0]. Defaults to 5.0.
            target_return: Target annualized return for target_return mode.
                Must be in [0.0, 1.0]. Required when mode is TARGET_RETURN.
            config: Optimizer configuration (solver chain, kwargs, etc.).

        Raises:
            ValueError: If risk_aversion is outside [0.1, 100.0].
            ValueError: If mode is TARGET_RETURN but target_return is not provided.
            ValueError: If target_return is outside [0.0, 1.0].
        """
        super().__init__(config)

        # Validate risk_aversion
        if not (0.1 <= risk_aversion <= 100.0):
            raise ValueError(
                f"risk_aversion must be in [0.1, 100.0], got {risk_aversion}"
            )

        # Validate target_return for target_return mode
        if mode == MVOMode.TARGET_RETURN:
            if target_return is None:
                raise ValueError(
                    "target_return is required when mode is TARGET_RETURN"
                )
            if not (0.0 <= target_return <= 1.0):
                raise ValueError(
                    f"target_return must be in [0.0, 1.0], got {target_return}"
                )

        self.mode = mode
        self.risk_aversion = risk_aversion
        self.target_return = target_return

    def run(self, ctx: OptContext) -> OptResult:
        """Execute MVO with input validation, then delegate to base class solver chain.

        Validates:
        - Universe contains at least 2 assets.
        - Covariance matrix is positive semi-definite.
        - risk_aversion from context is in valid range.

        For target-return mode, injects the return constraint (μ'w >= r_target)
        into the problem alongside the standard constraints.

        If validation fails, raises MVOValidationError without attempting optimization.

        Args:
            ctx: The optimization context.

        Returns:
            An OptResult with the solution weights and metadata.

        Raises:
            MVOValidationError: If the covariance matrix is not PSD or the
                universe contains fewer than 2 assets.
        """
        self._validate_inputs(ctx)
        return super().run(ctx)

    def build_objective(self, w: cp.Variable, ctx: OptContext) -> cp.Expression:
        """Build the MVO objective expression based on the selected mode.

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context with expected returns and covariance.

        Returns:
            A cvxpy expression to be minimized:
            - Tangency: λ·w'Σw - μ'w
            - Min-Variance: w'Σw
            - Target-Return: w'Σw
        """
        covariance = ctx.covariance

        if self.mode == MVOMode.TANGENCY:
            # Tangency: minimize λ·w'Σw - μ'w
            risk_term = cp.quad_form(w, covariance)
            return_term = ctx.expected_returns @ w
            return self.risk_aversion * risk_term - return_term

        elif self.mode == MVOMode.MIN_VARIANCE:
            # Min-Variance: minimize w'Σw (no expected returns)
            return cp.quad_form(w, covariance)

        else:
            # Target-Return: minimize w'Σw (return constraint added via
            # _build_investment_constraint override)
            return cp.quad_form(w, covariance)

    def _build_investment_constraint(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Build investment constraints including target-return constraint.

        Extends the base class to add the return target constraint for
        target-return mode: μ'w >= r_target.

        Args:
            w: The cvxpy weight variable.
            ctx: The optimization context.

        Returns:
            List of cvxpy constraints including the sum-of-weights constraint
            and, for target-return mode, the return target constraint.
        """
        constraints = super()._build_investment_constraint(w, ctx)

        if self.mode == MVOMode.TARGET_RETURN and self.target_return is not None:
            # μ'w >= r_target
            constraints.append(ctx.expected_returns @ w >= self.target_return)

        return constraints

    def _validate_inputs(self, ctx: OptContext) -> None:
        """Validate MVO-specific inputs before optimization.

        Checks:
        1. Universe must contain at least 2 assets.
        2. Covariance matrix must be positive semi-definite.

        Args:
            ctx: The optimization context.

        Raises:
            MVOValidationError: If any validation check fails.
        """
        # Check universe size
        if ctx.n_assets < 2:
            raise MVOValidationError(
                reason="insufficient_assets",
                message=(
                    f"MVO requires at least 2 assets, got {ctx.n_assets}. "
                    "Cannot construct a meaningful portfolio with fewer than 2 assets."
                ),
            )

        # Check covariance matrix shape
        cov = ctx.covariance
        if cov.shape != (ctx.n_assets, ctx.n_assets):
            raise MVOValidationError(
                reason="covariance_shape_mismatch",
                message=(
                    f"Covariance matrix shape {cov.shape} does not match "
                    f"expected ({ctx.n_assets}, {ctx.n_assets})."
                ),
            )

        # Check symmetry (within tolerance)
        if not np.allclose(cov, cov.T, atol=1e-10):
            raise MVOValidationError(
                reason="covariance_not_symmetric",
                message="Covariance matrix is not symmetric.",
            )

        # Check PSD via eigenvalues
        try:
            eigenvalues = np.linalg.eigvalsh(cov)
        except np.linalg.LinAlgError as e:
            raise MVOValidationError(
                reason="covariance_eigenvalue_computation_failed",
                message=f"Failed to compute eigenvalues of covariance matrix: {e}",
            ) from e

        if np.any(eigenvalues < -1e-8):
            min_eigenvalue = float(eigenvalues.min())
            raise MVOValidationError(
                reason="covariance_not_psd",
                message=(
                    f"Covariance matrix is not positive semi-definite. "
                    f"Minimum eigenvalue: {min_eigenvalue:.2e}. "
                    "Apply nearest-PSD correction before optimization."
                ),
            )


# Alias for backward compatibility and shorter name
MVOOptimizer = MeanVarianceOptimizer
