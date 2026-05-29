"""Covariance utilities: nearest_psd, eigenvalue floor, input validation."""

from __future__ import annotations

import numpy as np


def nearest_psd(matrix: np.ndarray, floor: float = 1e-8) -> np.ndarray:
    """Project a symmetric matrix to the nearest positive semi-definite matrix.

    Uses eigenvalue decomposition to clip all eigenvalues to at least `floor`,
    then reconstructs the matrix. The result is guaranteed symmetric and PSD.

    Args:
        matrix: A square symmetric matrix (n×n).
        floor: Minimum eigenvalue threshold. All eigenvalues below this
            value are raised to `floor`. Defaults to 1e-8.

    Returns:
        A symmetric n×n positive semi-definite matrix with all eigenvalues
        >= floor.

    Raises:
        ValueError: If the matrix is not 2-D or not square.
    """
    if matrix.ndim != 2:
        msg = f"Expected a 2-D matrix, got {matrix.ndim}-D array."
        raise ValueError(msg)

    n, m = matrix.shape
    if n != m:
        msg = f"Expected a square matrix, got shape ({n}, {m})."
        raise ValueError(msg)

    # Symmetrize to handle floating-point asymmetry
    sym = (matrix + matrix.T) / 2.0

    # Eigenvalue decomposition
    eigenvalues, eigenvectors = np.linalg.eigh(sym)

    # Floor eigenvalues
    eigenvalues_clipped = np.maximum(eigenvalues, floor)

    # Reconstruct the matrix
    result = (eigenvectors * eigenvalues_clipped) @ eigenvectors.T

    # Ensure perfect symmetry
    result = (result + result.T) / 2.0

    return result


def validate_returns(returns: np.ndarray) -> None:
    """Validate a return matrix for covariance estimation.

    Checks that:
    1. The input contains no NaN or Inf values.
    2. The number of observations T >= n + 1 (where n is the number of assets).
    3. The input has consistent dimensions (is a 2-D matrix).

    Args:
        returns: T×n matrix of daily returns.

    Raises:
        ValueError: With a specific message indicating which check failed:
            - "Return matrix must be a 2-D array" for non-2D inputs.
            - "Return matrix contains NaN values" for NaN presence.
            - "Return matrix contains Inf values" for Inf presence.
            - "Insufficient observations: ..." for T < n + 1.
    """
    if returns.ndim != 2:
        msg = (
            f"Return matrix must be a 2-D array, got {returns.ndim}-D array "
            f"with shape {returns.shape}."
        )
        raise ValueError(msg)

    if np.any(np.isnan(returns)):
        msg = "Return matrix contains NaN values."
        raise ValueError(msg)

    if np.any(np.isinf(returns)):
        msg = "Return matrix contains Inf values."
        raise ValueError(msg)

    t, n = returns.shape

    if t < n + 1:
        msg = (
            f"Insufficient observations: got T={t} observations for n={n} "
            f"assets, but require T >= n + 1 = {n + 1}."
        )
        raise ValueError(msg)
