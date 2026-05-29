"""CVaR optimizer: Rockafellar-Uryasev LP formulation.

This module implements the Conditional Value-at-Risk (CVaR) optimizer using
the Rockafellar-Uryasev linear programming formulation over return scenarios.

The LP formulation:
    minimize  α + (1/(1-β)) · (1/S) · sum(u_s)
    subject to:
        u_s >= -r_s' · w - α,  for all s = 1..S
        u_s >= 0,              for all s = 1..S
        sum(w_i) = 1           (full investment)
        + all constraints from OptContext

Where:
    - w: portfolio weight vector (n assets)
    - α: VaR threshold (scalar variable)
    - u_s: auxiliary variables (one per scenario, capturing tail losses)
    - r_s: return vector for scenario s (row of the scenario matrix)
    - β: confidence level (default 0.95)
    - S: number of scenarios

Scenario generation modes:
    - Historical: 1000 most recent daily return vectors from ctx.scenarios
    - Bootstrap: 5000 block-bootstrap resamples with block size 5

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9
"""

from __future__ import annotations

from enum import StrEnum

import cvxpy as cp
import numpy as np
import structlog

from astraeus_portfolio.contracts import OptContext, OptResult
from astraeus_portfolio.optimizers.base import Optimizer, OptimizerConfig

__all__ = [
    "CVaROptimizer",
    "CVaRValidationError",
    "ScenarioMode",
]

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BETA = 0.95
HISTORICAL_SCENARIO_COUNT = 1000
BOOTSTRAP_SCENARIO_COUNT = 5000
BOOTSTRAP_BLOCK_SIZE = 5
MIN_SCENARIO_FACTOR = 2  # S >= 2 * n_assets


# ---------------------------------------------------------------------------
# Scenario Mode Enum
# ---------------------------------------------------------------------------


class ScenarioMode(StrEnum):
    """Scenario generation modes for CVaR optimization."""

    HISTORICAL = "historical"
    BOOTSTRAP = "bootstrap"


# ---------------------------------------------------------------------------
# Validation Error
# ---------------------------------------------------------------------------


class CVaRValidationError(ValueError):
    """Raised when CVaR optimizer input validation fails.

    Attributes:
        reason: A machine-readable reason code for the validation failure.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


# ---------------------------------------------------------------------------
# Scenario Generation
# ---------------------------------------------------------------------------


def _generate_historical_scenarios(scenarios: np.ndarray) -> np.ndarray:
    """Extract the 1000 most recent daily return vectors.

    Args:
        scenarios: Full historical return matrix of shape (T, n).

    Returns:
        The 1000 most recent rows as an (S, n) matrix.

    Raises:
        CVaRValidationError: If fewer than 1000 vectors are available.
    """
    n_available = scenarios.shape[0]
    if n_available < HISTORICAL_SCENARIO_COUNT:
        raise CVaRValidationError(
            reason="insufficient_historical_data",
            message=(
                f"Historical scenario generation requires at least "
                f"{HISTORICAL_SCENARIO_COUNT} daily return vectors, "
                f"but only {n_available} are available."
            ),
        )
    return scenarios[-HISTORICAL_SCENARIO_COUNT:]


def _generate_bootstrap_scenarios(
    scenarios: np.ndarray,
    n_scenarios: int = BOOTSTRAP_SCENARIO_COUNT,
    block_size: int = BOOTSTRAP_BLOCK_SIZE,
    seed: int = 42,
) -> np.ndarray:
    """Generate block-bootstrap resampled return vectors.

    Uses stationary block bootstrap with a fixed block size. Blocks are
    sampled with replacement from the available history and concatenated
    to form each resampled return vector.

    Args:
        scenarios: Full historical return matrix of shape (T, n).
        n_scenarios: Number of bootstrap resamples to generate (default 5000).
        block_size: Size of each contiguous block (default 5).
        seed: Random seed for reproducibility.

    Returns:
        An (n_scenarios, n) matrix of resampled return vectors.
    """
    rng = np.random.default_rng(seed)
    t_available = scenarios.shape[0]
    n_assets = scenarios.shape[1]

    # Number of blocks needed per scenario (each scenario is one return vector
    # formed by averaging a block of consecutive returns)
    resampled = np.empty((n_scenarios, n_assets), dtype=np.float64)

    # For each scenario, pick a random block start and average the block
    max_start = t_available - block_size
    max_start = max(max_start, 0)

    block_starts = rng.integers(0, max_start + 1, size=n_scenarios)

    for i, start in enumerate(block_starts):
        block = scenarios[start : start + block_size]
        # Compound the block returns: product of (1 + r) - 1
        compounded = np.prod(1.0 + block, axis=0) - 1.0
        resampled[i] = compounded

    return resampled


# ---------------------------------------------------------------------------
# CVaR Optimizer
# ---------------------------------------------------------------------------


class CVaROptimizer(Optimizer):
    """CVaR optimizer using the Rockafellar-Uryasev LP formulation.

    Minimizes Conditional Value-at-Risk (expected shortfall) at a given
    confidence level β over a set of return scenarios. The LP formulation
    introduces auxiliary variables to linearize the CVaR objective.

    Scenario generation supports two modes:
    - Historical: uses the 1000 most recent daily return vectors.
    - Bootstrap: generates 5000 block-bootstrap resamples with block size 5.

    Validation requirements:
    - Number of scenarios S must be >= 2 * n_assets.
    - Historical mode requires at least 1000 return vectors.
    - Scenario matrix must contain no NaN values.

    Attributes:
        beta: Confidence level for CVaR (default 0.95).
        scenario_mode: Scenario generation method (historical or bootstrap).
    """

    def __init__(
        self,
        beta: float = DEFAULT_BETA,
        scenario_mode: ScenarioMode = ScenarioMode.HISTORICAL,
        config: OptimizerConfig | None = None,
    ) -> None:
        """Initialize the CVaR optimizer.

        Args:
            beta: Confidence level for CVaR. Must be in (0, 1). Default 0.95.
            scenario_mode: Scenario generation mode. Default is historical.
            config: Optimizer configuration (solver chain, kwargs, etc.).

        Raises:
            ValueError: If beta is not in (0, 1).
        """
        super().__init__(config)

        if not (0.0 < beta < 1.0):
            raise ValueError(f"beta must be in (0, 1), got {beta}")

        self.beta = beta
        self.scenario_mode = scenario_mode

    def run(self, ctx: OptContext) -> OptResult:
        """Execute CVaR optimization with scenario generation and validation.

        Pipeline:
        1. Generate or extract scenarios based on the configured mode.
        2. Validate scenario count (S >= 2*n) and data quality (no NaN).
        3. Formulate the Rockafellar-Uryasev LP.
        4. Delegate to the base class solver chain and fallback logic.

        Args:
            ctx: The optimization context. Must have ctx.scenarios populated
                with historical return data (S, n) matrix.

        Returns:
            An OptResult with the solution weights and metadata.

        Raises:
            CVaRValidationError: If scenarios are insufficient, contain NaN,
                or fail the S >= 2*n requirement.
        """
        # Validate that scenarios are provided
        if ctx.scenarios is None:
            raise CVaRValidationError(
                reason="no_scenarios",
                message="CVaR optimizer requires scenarios in OptContext.scenarios.",
            )

        # Generate scenarios based on mode
        scenario_matrix = self._generate_scenarios(ctx)

        # Validate scenario count vs asset count
        s_count = scenario_matrix.shape[0]
        n_assets = ctx.n_assets
        min_required = MIN_SCENARIO_FACTOR * n_assets

        if s_count < min_required:
            raise CVaRValidationError(
                reason="insufficient_scenarios",
                message=(
                    f"CVaR optimizer requires at least {min_required} scenarios "
                    f"(2 × {n_assets} assets), but only {s_count} are available."
                ),
            )

        # Validate no NaN in scenario matrix
        if np.any(np.isnan(scenario_matrix)):
            raise CVaRValidationError(
                reason="nan_in_scenarios",
                message="Scenario matrix contains NaN values.",
            )

        # Store the scenario matrix for use in build_objective
        self._scenario_matrix = scenario_matrix

        logger.info(
            "cvar_optimization_starting",
            strategy_id=ctx.strategy_id,
            beta=self.beta,
            scenario_mode=self.scenario_mode,
            n_scenarios=s_count,
            n_assets=n_assets,
        )

        return super().run(ctx)

    def build_objective(self, w: cp.Variable, ctx: OptContext) -> cp.Expression:
        """Build the Rockafellar-Uryasev CVaR LP objective.

        The LP formulation:
            minimize  α + (1/(1-β)) · (1/S) · sum(u_s)

        With auxiliary constraints added via _build_auxiliary_constraints.

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context.

        Returns:
            A cvxpy expression representing the CVaR objective to minimize.
        """
        scenario_matrix = self._scenario_matrix
        s_count = scenario_matrix.shape[0]

        # α (VaR threshold) is a scalar variable
        self._alpha = cp.Variable(name="alpha")

        # u_s auxiliary variables (one per scenario)
        self._u = cp.Variable(s_count, name="u", nonneg=True)

        # Objective: α + (1/(1-β)) · (1/S) · sum(u_s)
        tail_weight = 1.0 / (1.0 - self.beta)
        scenario_avg = 1.0 / s_count

        objective = self._alpha + tail_weight * scenario_avg * cp.sum(self._u)

        return objective

    def _build_investment_constraint(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Build investment constraints plus CVaR auxiliary constraints.

        Extends the base class to add the Rockafellar-Uryasev auxiliary
        constraints:
            u_s >= -r_s' · w - α,  for all s
            u_s >= 0               (handled by nonneg=True on variable)

        Args:
            w: The cvxpy weight variable.
            ctx: The optimization context.

        Returns:
            List of cvxpy constraints including sum-of-weights and
            CVaR auxiliary constraints.
        """
        constraints = super()._build_investment_constraint(w, ctx)

        scenario_matrix = self._scenario_matrix
        scenario_matrix.shape[0]

        # Auxiliary constraints: u_s >= -r_s' · w - α
        # Vectorized: u >= -R @ w - α (element-wise)
        # R is (S, n), w is (n,), so R @ w is (S,)
        portfolio_returns = scenario_matrix @ w  # (S,) vector of scenario returns
        constraints.append(self._u >= -portfolio_returns - self._alpha)

        return constraints

    def _generate_scenarios(self, ctx: OptContext) -> np.ndarray:
        """Generate or extract scenarios based on the configured mode.

        Args:
            ctx: The optimization context with ctx.scenarios as the raw
                historical return data.

        Returns:
            An (S, n) scenario matrix ready for optimization.

        Raises:
            CVaRValidationError: If historical mode has insufficient data.
        """
        raw_scenarios = ctx.scenarios

        if self.scenario_mode == ScenarioMode.HISTORICAL:
            return _generate_historical_scenarios(raw_scenarios)
        # Bootstrap mode
        return _generate_bootstrap_scenarios(
            raw_scenarios,
            n_scenarios=BOOTSTRAP_SCENARIO_COUNT,
            block_size=BOOTSTRAP_BLOCK_SIZE,
            seed=ctx.seed,
        )
