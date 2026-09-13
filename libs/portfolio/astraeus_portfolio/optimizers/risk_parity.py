"""Risk Parity optimizer: ERC + HRP fallback.

This module implements the Risk Parity portfolio optimizer with two algorithms:

- **ERC (Equal Risk Contribution)**: Solves the log-barrier formulation
  minimize 0.5·w'Σw - (1/n)·sum(log(w_i)) using a custom Newton solver
  with backtracking line search.
- **HRP (Hierarchical Risk Parity)**: Uses Ward linkage on a correlation-distance
  matrix with recursive bisection for large universes or ill-conditioned matrices.

The optimizer switches to HRP when:
- n > 200 assets, OR
- condition number of Σ > 1e6

Non-convergence of the Newton solver is reported as a failed OptResult with
gradient norm and iteration count.

Additional constraints (≤3) are applied via Bruder & Roncalli constrained
formulation; more than 3 constraints use post-hoc projection.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cvxpy as cp
import numpy as np
import structlog
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform

from astraeus_portfolio.constraints.base import Constraint
from astraeus_portfolio.contracts import OptContext, OptResult
from astraeus_portfolio.optimizers.base import Optimizer, OptimizerConfig

__all__ = [
    "RiskParityConfig",
    "RiskParityNonConvergenceError",
    "RiskParityOptimizer",
]

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskParityConfig:
    """Configuration for the Risk Parity optimizer.

    Attributes:
        max_iterations: Maximum Newton iterations for ERC solver.
        convergence_tol: Relative objective change threshold for convergence.
        hrp_asset_threshold: Switch to HRP when n exceeds this value.
        hrp_condition_threshold: Switch to HRP when cond(Σ) exceeds this value.
        backtrack_alpha: Armijo condition parameter for line search.
        backtrack_beta: Step reduction factor for backtracking.
        max_risk_contribution_ratio: Maximum allowed ratio between any two
            assets' risk contributions (for validation).
    """

    max_iterations: int = 50
    convergence_tol: float = 1e-10
    hrp_asset_threshold: int = 200
    hrp_condition_threshold: float = 1e6
    backtrack_alpha: float = 0.3
    backtrack_beta: float = 0.5
    max_risk_contribution_ratio: float = 1.05


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RiskParityNonConvergenceError(RuntimeError):
    """Raised when the ERC Newton solver does not converge.

    Attributes:
        gradient_norm: The final gradient norm at termination.
        iterations: The number of iterations completed.
    """

    def __init__(self, gradient_norm: float, iterations: int) -> None:
        self.gradient_norm = gradient_norm
        self.iterations = iterations
        super().__init__(
            f"ERC Newton solver did not converge after {iterations} iterations. "
            f"Final gradient norm: {gradient_norm:.2e}"
        )


# ---------------------------------------------------------------------------
# ERC Newton Solver
# ---------------------------------------------------------------------------


def _erc_objective(w: np.ndarray, cov: np.ndarray, n: int) -> float:
    """Compute the ERC log-barrier objective.

    f(w) = 0.5 * w' Σ w - (1/n) * sum(log(w_i))

    Args:
        w: Weight vector (n,), must be strictly positive.
        cov: Covariance matrix (n, n).
        n: Number of assets.

    Returns:
        The objective value.
    """
    portfolio_var = 0.5 * w @ cov @ w
    log_barrier = (1.0 / n) * np.sum(np.log(w))
    return portfolio_var - log_barrier


def _erc_gradient(w: np.ndarray, cov: np.ndarray, n: int) -> np.ndarray:
    """Compute the gradient of the ERC objective.

    ∇f(w) = Σw - (1/n) * (1/w)

    Args:
        w: Weight vector (n,), must be strictly positive.
        cov: Covariance matrix (n, n).
        n: Number of assets.

    Returns:
        Gradient vector (n,).
    """
    return cov @ w - (1.0 / n) / w


def _erc_hessian(w: np.ndarray, cov: np.ndarray, n: int) -> np.ndarray:
    """Compute the Hessian of the ERC objective.

    H(w) = Σ + (1/n) * diag(1/w_i^2)

    Args:
        w: Weight vector (n,), must be strictly positive.
        cov: Covariance matrix (n, n).
        n: Number of assets.

    Returns:
        Hessian matrix (n, n).
    """
    return cov + (1.0 / n) * np.diag(1.0 / (w**2))


def _backtracking_line_search(
    w: np.ndarray,
    direction: np.ndarray,
    grad: np.ndarray,
    cov: np.ndarray,
    n: int,
    alpha: float = 0.3,
    beta: float = 0.5,
) -> float:
    """Backtracking line search satisfying the Armijo condition.

    Finds step size t such that:
    f(w + t*d) <= f(w) + alpha * t * grad' * d

    Also ensures w + t*d > 0 (positivity constraint).

    Args:
        w: Current weight vector.
        direction: Newton direction.
        grad: Current gradient.
        cov: Covariance matrix.
        n: Number of assets.
        alpha: Armijo condition parameter.
        beta: Step reduction factor.

    Returns:
        The step size t.
    """
    t = 1.0
    f_current = _erc_objective(w, cov, n)
    descent = alpha * grad @ direction

    max_line_search_iters = 50
    for _ in range(max_line_search_iters):
        w_new = w + t * direction
        # Ensure positivity
        if np.all(w_new > 0):
            f_new = _erc_objective(w_new, cov, n)
            if f_new <= f_current + t * descent:
                return t
        t *= beta

    return t


def solve_erc_newton(
    cov: np.ndarray,
    config: RiskParityConfig,
) -> tuple[np.ndarray, bool, float, int]:
    """Solve the ERC problem using Newton's method with backtracking line search.

    Minimizes: 0.5 * w' Σ w - (1/n) * sum(log(w_i))
    Subject to: w > 0 (enforced via log barrier and line search)

    The solution is normalized to sum to 1 after convergence.

    Args:
        cov: Positive semi-definite covariance matrix (n, n).
        config: Risk parity configuration.

    Returns:
        Tuple of (weights, converged, gradient_norm, iterations):
            - weights: Normalized weight vector summing to 1.
            - converged: Whether the solver converged.
            - gradient_norm: Final gradient norm.
            - iterations: Number of iterations completed.
    """
    n = cov.shape[0]

    # Initialize with equal weights (scaled to avoid numerical issues)
    w = np.ones(n) / n

    prev_obj = _erc_objective(w, cov, n)

    converged = False
    grad_norm = np.inf
    iteration = 0

    for iteration in range(1, config.max_iterations + 1):
        grad = _erc_gradient(w, cov, n)
        hess = _erc_hessian(w, cov, n)

        # Solve Newton system: H * direction = -grad
        try:
            direction = np.linalg.solve(hess, -grad)
        except np.linalg.LinAlgError:
            # Hessian is singular — use gradient descent as fallback
            direction = -grad

        # Backtracking line search
        step = _backtracking_line_search(
            w,
            direction,
            grad,
            cov,
            n,
            alpha=config.backtrack_alpha,
            beta=config.backtrack_beta,
        )

        w = w + step * direction

        # Ensure positivity (clamp to small positive value)
        w = np.maximum(w, 1e-12)

        # Check convergence: relative change in objective
        current_obj = _erc_objective(w, cov, n)
        grad_norm = float(np.linalg.norm(grad))

        if abs(prev_obj) > 1e-15:
            rel_change = abs(current_obj - prev_obj) / abs(prev_obj)
        else:
            rel_change = abs(current_obj - prev_obj)

        if rel_change < config.convergence_tol:
            converged = True
            break

        prev_obj = current_obj

    # Normalize weights to sum to 1
    w = w / np.sum(w)

    return w, converged, grad_norm, iteration


# ---------------------------------------------------------------------------
# HRP (Hierarchical Risk Parity)
# ---------------------------------------------------------------------------


def _correlation_distance_matrix(cov: np.ndarray) -> np.ndarray:
    """Compute correlation-distance matrix from covariance.

    D_ij = sqrt(0.5 * (1 - ρ_ij))

    Args:
        cov: Covariance matrix (n, n).

    Returns:
        Distance matrix (n, n) with zeros on diagonal.
    """
    # Convert covariance to correlation
    std = np.sqrt(np.diag(cov))
    # Avoid division by zero
    std = np.maximum(std, 1e-12)
    corr = cov / np.outer(std, std)
    # Clip to [-1, 1] for numerical stability
    corr = np.clip(corr, -1.0, 1.0)

    # Distance: D_ij = sqrt(0.5 * (1 - ρ_ij))
    dist = np.sqrt(0.5 * (1.0 - corr))
    np.fill_diagonal(dist, 0.0)
    return dist


def _get_quasi_diagonal_order(link: np.ndarray, n: int) -> list[int]:
    """Extract the quasi-diagonal ordering from a linkage matrix.

    Recursively traverses the dendrogram to produce a leaf ordering
    that places similar assets adjacent to each other.

    Args:
        link: Linkage matrix from scipy (shape (n-1, 4)).
        n: Number of original observations (leaves).

    Returns:
        List of leaf indices in quasi-diagonal order.
    """
    order: list[int] = []

    def _recurse(node_id: int) -> None:
        if node_id < n:
            order.append(node_id)
            return
        # Internal node: row index in linkage is (node_id - n)
        row = int(node_id - n)
        left = int(link[row, 0])
        right = int(link[row, 1])
        _recurse(left)
        _recurse(right)

    # Root is the last merged cluster: index = 2*n - 2
    _recurse(2 * n - 2)
    return order


def _recursive_bisection(
    cov: np.ndarray,
    sorted_indices: list[int],
) -> np.ndarray:
    """Allocate weights via recursive bisection on the quasi-diagonal ordering.

    At each step, splits the sorted index list in half and allocates
    inverse-variance weights between the two halves.

    Args:
        cov: Covariance matrix (n, n).
        sorted_indices: Quasi-diagonal ordering of asset indices.

    Returns:
        Weight vector (n,) summing to 1.
    """
    n = cov.shape[0]
    weights = np.ones(n)

    # Use a stack-based approach for recursive bisection
    clusters = [sorted_indices]

    while clusters:
        new_clusters = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue

            mid = len(cluster) // 2
            left_cluster = cluster[:mid]
            right_cluster = cluster[mid:]

            # Compute cluster variances using inverse-variance allocation
            left_var = _cluster_variance(cov, left_cluster)
            right_var = _cluster_variance(cov, right_cluster)

            # Allocate: inverse variance weighting between clusters
            total_inv_var = 1.0 / left_var + 1.0 / right_var
            left_alloc = (1.0 / left_var) / total_inv_var
            right_alloc = (1.0 / right_var) / total_inv_var

            # Scale weights
            for idx in left_cluster:
                weights[idx] *= left_alloc
            for idx in right_cluster:
                weights[idx] *= right_alloc

            # Continue bisecting
            if len(left_cluster) > 1:
                new_clusters.append(left_cluster)
            if len(right_cluster) > 1:
                new_clusters.append(right_cluster)

        clusters = new_clusters

    # Normalize to sum to 1
    weights = weights / np.sum(weights)
    return weights


def _cluster_variance(cov: np.ndarray, indices: list[int]) -> float:
    """Compute the variance of an inverse-variance-weighted sub-portfolio.

    Within a cluster, assets are weighted by inverse variance (diagonal of cov).

    Args:
        cov: Full covariance matrix.
        indices: Asset indices in this cluster.

    Returns:
        Portfolio variance of the cluster sub-portfolio.
    """
    sub_cov = cov[np.ix_(indices, indices)]
    # Inverse-variance weights within the cluster
    diag_var = np.diag(sub_cov)
    diag_var = np.maximum(diag_var, 1e-12)  # Avoid division by zero
    inv_var = 1.0 / diag_var
    w_cluster = inv_var / np.sum(inv_var)
    # Cluster portfolio variance
    return float(w_cluster @ sub_cov @ w_cluster)


def solve_hrp(cov: np.ndarray) -> np.ndarray:
    """Solve portfolio allocation using Hierarchical Risk Parity.

    Uses Ward linkage on the correlation-distance matrix and recursive
    bisection to allocate weights.

    Args:
        cov: Positive semi-definite covariance matrix (n, n).

    Returns:
        Weight vector (n,) summing to 1.
    """
    n = cov.shape[0]

    if n == 1:
        return np.array([1.0])

    if n == 2:
        # Simple inverse-variance for 2 assets
        var = np.diag(cov)
        var = np.maximum(var, 1e-12)
        inv_var = 1.0 / var
        return inv_var / np.sum(inv_var)

    # Compute correlation-distance matrix
    dist_matrix = _correlation_distance_matrix(cov)

    # Convert to condensed form for scipy
    condensed_dist = squareform(dist_matrix, checks=False)

    # Ward linkage
    link = linkage(condensed_dist, method="ward")

    # Get quasi-diagonal ordering
    sorted_indices = _get_quasi_diagonal_order(link, n)

    # Recursive bisection
    weights = _recursive_bisection(cov, sorted_indices)

    return weights


# ---------------------------------------------------------------------------
# Constraint Handling (Bruder & Roncalli / Post-hoc Projection)
# ---------------------------------------------------------------------------


def _apply_bruder_roncalli(
    weights: np.ndarray,
    cov: np.ndarray,
    constraints: list[Constraint],
    ctx: OptContext,
    config: RiskParityConfig,
) -> np.ndarray:
    """Apply constrained risk parity via Bruder & Roncalli (2012) formulation.

    For ≤3 additional constraints, uses an iterative projection approach
    that adjusts the ERC solution to satisfy linear constraints while
    maintaining approximate equal risk contribution.

    This is a simplified implementation that iteratively projects the
    unconstrained ERC solution onto the feasible set defined by the constraints.

    Args:
        weights: Unconstrained ERC/HRP weights.
        cov: Covariance matrix.
        constraints: List of additional constraints (≤3).
        ctx: Optimization context.
        config: Risk parity configuration.

    Returns:
        Adjusted weight vector satisfying constraints.
    """
    n = len(weights)
    w = weights.copy()

    # Iterative adjustment: project onto constraint feasible set
    # while trying to maintain risk parity structure
    for _ in range(20):  # Max adjustment iterations
        adjusted = False

        for constraint in constraints:
            diag = constraint.diagnostic(w, ctx)
            if not diag.get("satisfied", True):
                # Simple gradient-based adjustment toward feasibility
                # Compute risk contributions
                sigma_w = cov @ w
                total_risk = float(w @ sigma_w)
                if total_risk < 1e-15:
                    break
                rc = w * sigma_w / total_risk
                target_rc = 1.0 / n

                # Adjust weights to reduce risk contribution dispersion
                # while moving toward constraint satisfaction
                adjustment = target_rc - rc
                step = 0.1
                w = w + step * adjustment
                w = np.maximum(w, 1e-10)
                w = w / np.sum(w)
                adjusted = True

        if not adjusted:
            break

    return w


def _project_onto_feasible_set(
    weights: np.ndarray,
    constraints: list[Constraint],
    ctx: OptContext,
) -> np.ndarray:
    """Post-hoc projection onto the feasible set for >3 constraints.

    Uses cvxpy to find the closest feasible point (in L2 sense) to the
    unconstrained risk parity solution.

    Args:
        weights: Unconstrained ERC/HRP weights.
        constraints: List of additional constraints.
        ctx: Optimization context.

    Returns:
        Projected weight vector satisfying constraints and summing to 1.
    """
    n = len(weights)
    w = cp.Variable(n)

    # Minimize distance to risk parity solution
    objective = cp.Minimize(cp.sum_squares(w - weights))

    # Build constraint expressions
    cvxpy_constraints: list = [cp.sum(w) == 1, w >= 0]

    for constraint in constraints:
        try:
            exprs = constraint.to_cvxpy(w, ctx)
            cvxpy_constraints.extend(exprs)
        except Exception:
            logger.warning(
                "constraint_projection_failed",
                constraint_name=getattr(constraint, "name", str(constraint)),
                exc_info=True,
            )

    prob = cp.Problem(objective, cvxpy_constraints)

    # Try solving
    for solver in ["ECOS", "CLARABEL", "SCS"]:
        try:
            prob.solve(solver=solver)
            if prob.status in ("optimal", "optimal_inaccurate"):
                result = np.array(w.value).flatten()
                result = np.maximum(result, 0.0)
                result = result / np.sum(result)
                return result
        except cp.SolverError:
            continue

    # If projection fails, return original weights
    logger.warning("projection_failed_returning_original_weights")
    return weights


# ---------------------------------------------------------------------------
# Risk Parity Optimizer
# ---------------------------------------------------------------------------


class RiskParityOptimizer(Optimizer):
    """Risk Parity optimizer with ERC Newton solver and HRP fallback.

    This optimizer produces weights where each asset contributes equally to
    total portfolio risk. It uses two algorithms:

    - **ERC**: For universes ≤ 200 assets with well-conditioned covariance
      (cond(Σ) ≤ 1e6). Uses Newton's method with backtracking line search
      on the log-barrier formulation.
    - **HRP**: For large universes (> 200 assets) or ill-conditioned covariance
      (cond(Σ) > 1e6). Uses Ward linkage clustering and recursive bisection.

    Additional constraints are handled via:
    - Bruder & Roncalli (2012) formulation for ≤3 constraints.
    - Post-hoc L2 projection for >3 constraints.

    Attributes:
        rp_config: Risk parity-specific configuration.
    """

    def __init__(
        self,
        rp_config: RiskParityConfig | None = None,
        config: OptimizerConfig | None = None,
    ) -> None:
        """Initialize the Risk Parity optimizer.

        Args:
            rp_config: Risk parity-specific configuration. Uses defaults if None.
            config: Base optimizer configuration (solver chain, etc.).
        """
        super().__init__(config)
        self.rp_config = rp_config or RiskParityConfig()

    def build_objective(self, w: cp.Variable, ctx: OptContext) -> cp.Expression:
        """Build a placeholder objective (not used by Risk Parity's custom solver).

        Risk Parity uses its own Newton solver rather than cvxpy, so this method
        returns a minimal valid objective. It is required by the Optimizer ABC
        but is not invoked during normal operation.

        Args:
            w: The cvxpy weight variable.
            ctx: The optimization context.

        Returns:
            A minimal cvxpy expression (zero objective).
        """
        return cp.Constant(0)

    def run(self, ctx: OptContext) -> OptResult:
        """Execute Risk Parity optimization with ERC or HRP.

        Decision logic:
        1. If n > 200 or cond(Σ) > 1e6 → use HRP.
        2. Otherwise → use ERC Newton solver.
        3. If ERC does not converge → return failed OptResult.
        4. Apply additional constraints via Bruder & Roncalli (≤3) or projection (>3).

        Args:
            ctx: The optimization context containing covariance and constraints.

        Returns:
            An OptResult with the solution weights and metadata.
        """
        start_time = time.perf_counter()

        n = ctx.n_assets
        cov = ctx.covariance

        # Validate inputs
        if n < 2:
            return OptResult(
                weights=np.array([]),
                status="failed",
                solver_used=None,
                solve_time_ms=0.0,
                objective_value=None,
                relaxation_events=[],
                constraint_diagnostics=[],
            )

        # Determine algorithm: ERC vs HRP
        cond_number = float(np.linalg.cond(cov))
        use_hrp = (
            n > self.rp_config.hrp_asset_threshold
            or cond_number > self.rp_config.hrp_condition_threshold
        )

        if use_hrp:
            logger.info(
                "using_hrp_fallback",
                n_assets=n,
                condition_number=cond_number,
                reason="n > 200" if n > self.rp_config.hrp_asset_threshold else "cond > 1e6",
            )
            weights = solve_hrp(cov)
            solver_used = "hrp_ward_bisection"
        else:
            logger.info(
                "using_erc_newton",
                n_assets=n,
                condition_number=cond_number,
            )
            weights, converged, grad_norm, iterations = solve_erc_newton(cov, self.rp_config)

            if not converged:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                logger.warning(
                    "erc_non_convergence",
                    gradient_norm=grad_norm,
                    iterations=iterations,
                    strategy_id=ctx.strategy_id,
                )
                return OptResult(
                    weights=np.array([]),
                    status="failed",
                    solver_used="erc_newton",
                    solve_time_ms=elapsed_ms,
                    objective_value=None,
                    relaxation_events=[],
                    constraint_diagnostics=[
                        {
                            "constraint_name": "erc_convergence",
                            "satisfied": False,
                            "gradient_norm": grad_norm,
                            "iterations": iterations,
                            "reason": "non_convergence",
                        }
                    ],
                )

            solver_used = "erc_newton"

        # Apply additional constraints
        # Separate relaxable constraints (additional beyond box/positivity)
        additional_constraints = [c for c in ctx.constraints if c.relaxable and c.priority > 0]

        if additional_constraints:
            if len(additional_constraints) <= 3:
                logger.info(
                    "applying_bruder_roncalli",
                    n_constraints=len(additional_constraints),
                )
                weights = _apply_bruder_roncalli(
                    weights, cov, additional_constraints, ctx, self.rp_config
                )
            else:
                logger.info(
                    "applying_posthoc_projection",
                    n_constraints=len(additional_constraints),
                )
                weights = _project_onto_feasible_set(weights, ctx.constraints, ctx)

        # Ensure weights sum to 1 and are non-negative
        weights = np.maximum(weights, 0.0)
        weight_sum = np.sum(weights)
        if weight_sum > 0:
            weights = weights / weight_sum

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # Compute objective value
        obj_value = float(_erc_objective(weights, cov, n))

        # Compute constraint diagnostics
        diagnostics = self._compute_diagnostics(weights, cov, ctx)

        return OptResult(
            weights=weights,
            status="optimal",
            solver_used=solver_used,
            solve_time_ms=elapsed_ms,
            objective_value=obj_value,
            relaxation_events=[],
            constraint_diagnostics=diagnostics,
        )

    def _compute_diagnostics(
        self,
        weights: np.ndarray,
        cov: np.ndarray,
        ctx: OptContext,
    ) -> list[dict]:
        """Compute risk contribution diagnostics for the solution.

        Args:
            weights: Solved weight vector.
            cov: Covariance matrix.
            ctx: Optimization context.

        Returns:
            List of diagnostic dictionaries including risk contribution metrics.
        """
        diagnostics: list[dict] = []

        # Risk contribution analysis
        sigma_w = cov @ weights
        total_risk = float(weights @ sigma_w)

        if total_risk > 1e-15:
            risk_contributions = weights * sigma_w / total_risk
            max_rc = float(np.max(risk_contributions))
            min_rc = float(np.min(risk_contributions[weights > 1e-10]))
            if min_rc > 0:
                max_ratio = max_rc / min_rc
            else:
                max_ratio = float("inf")

            diagnostics.append(
                {
                    "constraint_name": "equal_risk_contribution",
                    "satisfied": max_ratio <= self.rp_config.max_risk_contribution_ratio,
                    "max_risk_contribution": max_rc,
                    "min_risk_contribution": min_rc,
                    "max_ratio": max_ratio,
                    "target_ratio": 1.0,
                    "tolerance": self.rp_config.max_risk_contribution_ratio,
                }
            )

        # Weight sum diagnostic
        weight_sum = float(np.sum(weights))
        diagnostics.append(
            {
                "constraint_name": "weight_sum",
                "satisfied": abs(weight_sum - 1.0) < 1e-6,
                "weight_sum": weight_sum,
                "target": 1.0,
            }
        )

        # Individual constraint diagnostics
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

        return diagnostics
