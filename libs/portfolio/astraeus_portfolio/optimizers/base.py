"""Optimizer ABC with solver chain and fallback logic.

This module provides the abstract base class for all portfolio optimizers.
Concrete optimizers implement `build_objective(w, ctx)` while inheriting the
shared `run(ctx) -> OptResult` pipeline that handles:

1. Problem construction from objective + constraints
2. Sequential solver attempts (default: ECOS → CLARABEL → SCS)
3. Constraint relaxation fallback on infeasibility
4. Deterministic OptResult construction

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np
import structlog

from astraeus_portfolio.constraints.base import relax_constraints
from astraeus_portfolio.contracts import OptContext, OptResult, RelaxationEvent

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizerConfig:
    """Configuration for the optimizer solver chain and behavior.

    Attributes:
        solver_chain: Ordered list of cvxpy solver names to attempt.
        solver_kwargs: Per-solver keyword arguments (e.g., tolerances).
        verbose: Whether to enable solver verbose output.
    """

    solver_chain: list[str] = field(default_factory=lambda: ["ECOS", "CLARABEL", "SCS"])
    solver_kwargs: dict[str, dict] = field(default_factory=dict)
    verbose: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flatten_constraints(
    nested: list[list[cp.constraints.constraint.Constraint]],
) -> list[cp.constraints.constraint.Constraint]:
    """Flatten a list of constraint lists into a single list."""
    flat: list[cp.constraints.constraint.Constraint] = []
    for group in nested:
        flat.extend(group)
    return flat


def _get_solver_attr(solver_name: str) -> str:
    """Map solver name string to the cvxpy solver constant name.

    cvxpy expects solver constants like cp.ECOS, cp.CLARABEL, cp.SCS.
    We accept string names and map them to the attribute.
    """
    return solver_name.upper()


# ---------------------------------------------------------------------------
# Optimizer ABC
# ---------------------------------------------------------------------------


class Optimizer(ABC):
    """Abstract base class for portfolio optimizers.

    Concrete subclasses implement `build_objective` to define the optimization
    objective. The `run` method handles the full pipeline: problem construction,
    solver chain execution, and constraint relaxation fallback.

    Attributes:
        config: Optimizer configuration (solver chain, kwargs, etc.).
    """

    def __init__(self, config: OptimizerConfig | None = None) -> None:
        """Initialize the optimizer with configuration.

        Args:
            config: Optimizer configuration. Uses defaults if None.
        """
        self.config = config or OptimizerConfig()

    @abstractmethod
    def build_objective(self, w: cp.Variable, ctx: OptContext) -> cp.Expression:
        """Build the optimization objective expression.

        Concrete optimizers implement this to define their specific objective
        (e.g., mean-variance, CVaR, risk parity).

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context with expected returns, covariance, etc.

        Returns:
            A cvxpy expression to be minimized.
        """
        ...

    def run(self, ctx: OptContext) -> OptResult:
        """Execute optimization with solver chain and constraint relaxation fallback.

        Pipeline:
        1. Build the cvxpy Problem from objective + constraints.
        2. Try each solver in the configured chain sequentially.
        3. If a solver returns "optimal" or "optimal_inaccurate", accept the solution.
        4. If all solvers fail, invoke constraint relaxation: drop relaxable
           constraints one at a time in descending priority order, re-solving
           after each removal.
        5. If all relaxable constraints are exhausted and the problem remains
           infeasible, return a failed OptResult with empty weights.

        Args:
            ctx: The optimization context containing all inputs and constraints.

        Returns:
            An OptResult with the solution weights, status, solver info, and
            any relaxation events that occurred.
        """
        w = cp.Variable(ctx.n_assets)
        objective = cp.Minimize(self.build_objective(w, ctx))

        # Build full-investment constraint
        investment_constraints = self._build_investment_constraint(w, ctx)

        # Build constraints from the constraint objects in context
        all_constraint_exprs = self._build_constraint_expressions(w, ctx, ctx.constraints)
        all_constraint_exprs.extend(investment_constraints)

        prob = cp.Problem(objective, all_constraint_exprs)

        # --- Phase 1: Try solver chain on full problem ---
        solver_chain = ctx.solver_chain if ctx.solver_chain else self.config.solver_chain
        result = self._try_solver_chain(prob, w, ctx, solver_chain)
        if result is not None:
            return result

        # --- Phase 2: Constraint relaxation fallback ---
        logger.info(
            "all_solvers_failed_attempting_relaxation",
            strategy_id=ctx.strategy_id,
            n_constraints=len(ctx.constraints),
        )
        return self._handle_infeasible(w, ctx, solver_chain)

    def _build_investment_constraint(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Build the sum-of-weights constraint based on fully_invested flag.

        Args:
            w: The cvxpy weight variable.
            ctx: The optimization context.

        Returns:
            A list containing the investment constraint (sum=1 or sum=0).
        """
        if ctx.fully_invested:
            return [cp.sum(w) == 1]
        return [cp.sum(w) == 0]

    def _build_constraint_expressions(
        self,
        w: cp.Variable,
        ctx: OptContext,
        constraints: list,
    ) -> list[cp.constraints.constraint.Constraint]:
        """Convert Constraint objects to cvxpy constraint expressions.

        Args:
            w: The cvxpy weight variable.
            ctx: The optimization context.
            constraints: List of Constraint ABC instances.

        Returns:
            Flattened list of cvxpy constraint expressions.
        """
        nested = []
        for c in constraints:
            try:
                exprs = c.to_cvxpy(w, ctx)
                nested.append(exprs)
            except Exception:
                logger.warning(
                    "constraint_build_failed",
                    constraint_name=getattr(c, "name", str(c)),
                    exc_info=True,
                )
        return _flatten_constraints(nested)

    def _try_solver_chain(
        self,
        prob: cp.Problem,
        w: cp.Variable,
        ctx: OptContext,
        solver_chain: list[str],
    ) -> OptResult | None:
        """Attempt to solve the problem with each solver in the chain.

        Args:
            prob: The cvxpy Problem to solve.
            w: The weight variable.
            ctx: The optimization context.
            solver_chain: Ordered list of solver names to try.

        Returns:
            An OptResult if a solver succeeds, or None if all fail.
        """
        for solver_name in solver_chain:
            solver_kwargs = self.config.solver_kwargs.get(solver_name, {})
            try:
                start = time.perf_counter()
                prob.solve(
                    solver=_get_solver_attr(solver_name),
                    verbose=self.config.verbose,
                    **solver_kwargs,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000.0

                if prob.status in ("optimal", "optimal_inaccurate"):
                    logger.info(
                        "solver_succeeded",
                        solver=solver_name,
                        status=prob.status,
                        elapsed_ms=round(elapsed_ms, 2),
                    )
                    return self._build_result(
                        w=w,
                        ctx=ctx,
                        status=prob.status,
                        solver_used=solver_name,
                        solve_time_ms=elapsed_ms,
                        objective_value=prob.value,
                        relaxation_events=[],
                    )
                logger.debug(
                    "solver_non_optimal",
                    solver=solver_name,
                    status=prob.status,
                )
            except cp.SolverError as e:
                logger.debug(
                    "solver_error",
                    solver=solver_name,
                    error=str(e),
                )
                continue
            except Exception:
                logger.warning(
                    "solver_unexpected_error",
                    solver=solver_name,
                    exc_info=True,
                )
                continue

        return None

    def _handle_infeasible(
        self,
        w: cp.Variable,
        ctx: OptContext,
        solver_chain: list[str],
    ) -> OptResult:
        """Handle infeasibility via constraint relaxation.

        Drops relaxable constraints one at a time in descending priority order,
        re-solving after each removal. Emits a RelaxationEvent for each dropped
        constraint.

        Args:
            w: The cvxpy weight variable.
            ctx: The optimization context.
            solver_chain: The solver chain to use for re-solving.

        Returns:
            An OptResult — either a successful solution with relaxation events,
            or a failed result with empty weights if all relaxable constraints
            are exhausted.
        """
        relaxation_events: list[RelaxationEvent] = []

        for remaining_constraints, event in relax_constraints(ctx.constraints):
            relaxation_events.append(event)
            logger.info(
                "constraint_relaxed",
                constraint_name=event.constraint_name,
                priority=event.priority,
                iteration=event.iteration,
            )

            # Rebuild problem with reduced constraints
            w_new = cp.Variable(ctx.n_assets)
            objective = cp.Minimize(self.build_objective(w_new, ctx))
            investment_constraints = self._build_investment_constraint(w_new, ctx)
            constraint_exprs = self._build_constraint_expressions(w_new, ctx, remaining_constraints)
            constraint_exprs.extend(investment_constraints)
            prob = cp.Problem(objective, constraint_exprs)

            # Try solver chain on relaxed problem
            for solver_name in solver_chain:
                solver_kwargs = self.config.solver_kwargs.get(solver_name, {})
                try:
                    start = time.perf_counter()
                    prob.solve(
                        solver=_get_solver_attr(solver_name),
                        verbose=self.config.verbose,
                        **solver_kwargs,
                    )
                    elapsed_ms = (time.perf_counter() - start) * 1000.0

                    if prob.status in ("optimal", "optimal_inaccurate"):
                        logger.info(
                            "relaxation_solved",
                            solver=solver_name,
                            status=prob.status,
                            n_relaxed=len(relaxation_events),
                        )
                        return self._build_result(
                            w=w_new,
                            ctx=ctx,
                            status=prob.status,
                            solver_used=solver_name,
                            solve_time_ms=elapsed_ms,
                            objective_value=prob.value,
                            relaxation_events=relaxation_events,
                        )
                except cp.SolverError:
                    continue
                except Exception:
                    logger.warning(
                        "relaxation_solver_unexpected_error",
                        solver=solver_name,
                        exc_info=True,
                    )
                    continue

        # All relaxable constraints exhausted — return failed result
        logger.warning(
            "all_relaxable_constraints_exhausted",
            strategy_id=ctx.strategy_id,
            n_relaxation_events=len(relaxation_events),
        )
        return OptResult(
            weights=np.array([]),
            status="failed",
            solver_used=None,
            solve_time_ms=0.0,
            objective_value=None,
            relaxation_events=relaxation_events,
            constraint_diagnostics=[],
        )

    def _build_result(
        self,
        w: cp.Variable,
        ctx: OptContext,
        status: str,
        solver_used: str,
        solve_time_ms: float,
        objective_value: float | None,
        relaxation_events: list[RelaxationEvent],
    ) -> OptResult:
        """Construct an OptResult from a solved problem.

        Extracts the weight vector from the cvxpy variable and computes
        constraint diagnostics for all constraints in the context.

        Args:
            w: The solved cvxpy weight variable.
            ctx: The optimization context.
            status: The problem status string.
            solver_used: Name of the solver that produced the solution.
            solve_time_ms: Wall-clock solve time in milliseconds.
            objective_value: The optimal objective value.
            relaxation_events: Any relaxation events that occurred.

        Returns:
            A fully populated OptResult.
        """
        weights = np.array(w.value).flatten()

        # Compute constraint diagnostics
        diagnostics = []
        for c in ctx.constraints:
            try:
                diag = c.diagnostic(weights, ctx)
                diagnostics.append(
                    {
                        "constraint_name": c.name,
                        "satisfied": diag.get("satisfied", True),
                        **diag,
                    }
                )
            except Exception:
                diagnostics.append(
                    {
                        "constraint_name": getattr(c, "name", str(c)),
                        "satisfied": None,
                        "error": "diagnostic_failed",
                    }
                )

        return OptResult(
            weights=weights,
            status=status,
            solver_used=solver_used,
            solve_time_ms=solve_time_ms,
            objective_value=objective_value,
            relaxation_events=relaxation_events,
            constraint_diagnostics=diagnostics,
        )
